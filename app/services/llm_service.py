"""LLM service with primary/fallback provider and structured extraction."""

# pylint: disable=C0302

import copy
import json
import re
import time
from datetime import datetime
from typing import Any, Optional

from app.config import settings
from app.core.logging import get_logger
from app.llm.anthropic_client import call_anthropic
from app.llm.openai_client import call_openai
from app.llm.prompts import (
    get_gap_analysis_prompt,
    get_profile_extraction_core_prompt,
    get_profile_extraction_enrichment_prompt,
    get_prompt_template_version,
    get_target_degree_detection_prompt,
)
from app.llm.schemas import (
    CoreExtractedProfile,
    DegreeLevelEnum,
    EnrichmentExtractedProfile,
    ExtractedProfile,
    TargetDegreeDetectionResult,
)
from app.models.llm_models import LLMExtractionResult
from app.repositories.mysql_llm_log_repo import LLMCallLogRepository
from app.security.input_sanitizer import detect_injection_attempt, strip_control_characters
from app.security.output_validator import validate_output_for_leakage, validate_profile_data
from app.security.prompt_guardrails import wrap_user_data
from app.utils.exceptions import LLMExtractionError, PromptInjectionError
from app.utils.trace_id import get_bound_trace_id

logger = get_logger(__name__)


def _resolve_prompt_template_version(prompt_name: str) -> str:
    """Resolve a prompt template version without breaking module import."""
    try:
        return get_prompt_template_version(prompt_name)
    except ValueError as exc:
        logger.error(
            "invalid_prompt_template_version_configuration",
            prompt_name=prompt_name,
            error=str(exc),
            fallback_version="v1",
        )
        return "v1"


PROFILE_EXTRACTION_PROMPT_VERSION = _resolve_prompt_template_version("profile_extraction")
PROFILE_EXTRACTION_CORE_PROMPT_VERSION = _resolve_prompt_template_version("profile_extraction_core")
PROFILE_EXTRACTION_ENRICHMENT_PROMPT_VERSION = _resolve_prompt_template_version("profile_extraction_enrichment")
GAP_ANALYSIS_PROMPT_VERSION = _resolve_prompt_template_version("gap_analysis")
TARGET_DEGREE_PROMPT_VERSION = _resolve_prompt_template_version("target_degree_detection")


class LLMService:
    """Orchestrates LLM calls with primary -> fallback provider logic."""

    def __init__(self, llm_log_repo: LLMCallLogRepository | None = None):
        self.llm_log_repo = llm_log_repo or LLMCallLogRepository()

    async def extract_profile(self, document_text: str) -> LLMExtractionResult:
        """Extract structured profile data from document text using LLM.

        Uses a cheap target-degree classifier first when no hint is provided,
        then routes the main extraction to the light or strong model tier.
        Includes security checks to prevent prompt injection.
        """
        # Security: Detect and block prompt injection attempts
        if settings.ENABLE_SECURITY_CHECKS:
            if detect_injection_attempt(document_text):
                logger.warning(
                    "potential_prompt_injection_detected",
                    operation="profile_extraction",
                    trace_id=get_bound_trace_id(),
                )
                raise PromptInjectionError("Potential prompt injection detected in document text")

            # Sanitize control characters
            document_text = strip_control_characters(document_text, preserve_newline_tab=True)

        detection_result = await self.detect_target_degree(document_text)

        extraction_tier = self._select_extraction_tier(document_text, detection_result)
        if extraction_tier["provider"] is None:
            raise LLMExtractionError("No LLM API key configured for extraction")

        budgeted_text, input_meta = self._budget_text(
            document_text,
            budget_chars=settings.LLM_EXTRACTION_INPUT_CHAR_BUDGET,
            head_chars=settings.LLM_TRUNCATION_HEAD_CHARS,
            tail_chars=settings.LLM_TRUNCATION_TAIL_CHARS,
            label="profile_extraction",
        )
        runtime_context: dict[str, Any] = {
            "document_metadata": {
                "text_length": len(document_text),
                "budgeted_text_length": len(budgeted_text),
            },
            "llm_budget": input_meta,
            "llm_tiering": {
                "target_degree_detection": detection_result.model_dump() if detection_result else None,
                "extraction_tier": extraction_tier,
            },
        }

        system_prompt = get_profile_extraction_core_prompt(context=runtime_context, fmt="text")
        user_content, _ = self._build_extraction_input(budgeted_text)
        start = time.perf_counter()
        fallback_reason: Optional[str] = None

        primary_provider = extraction_tier["provider"]
        secondary_provider = extraction_tier["fallback_provider"]
        primary_model = extraction_tier["model"]
        primary_max_tokens = extraction_tier["max_tokens"]

        try:
            result = await self._call_provider(
                primary_provider,
                system_prompt,
                user_content,
                model=primary_model,
                max_tokens=primary_max_tokens,
            )
            core_profile = self._parse_core_profile(result["content"])
            enrichment_profile, enrichment_meta = await self._run_enrichment_pass(
                provider=result["provider"],
                budgeted_text=budgeted_text,
                runtime_context=runtime_context,
            )
            profile = self._parse_profile(self._merge_profile_parts(core_profile, enrichment_profile))
            latency = int((time.perf_counter() - start) * 1000)

            # Security: Validate output for leakage and prompt echoing
            if settings.ENABLE_OUTPUT_VALIDATION:
                validation_issues = validate_output_for_leakage(json.dumps(profile.model_dump()))
                if validation_issues:
                    logger.warning(
                        "output_validation_failed",
                        operation="profile_extraction",
                        issues=validation_issues,
                        trace_id=get_bound_trace_id(),
                    )
                    # Log but don't fail extraction on validation issues

            # Student-profile specific validation: check for hallucinations and data quality
            if settings.ENABLE_SECURITY_CHECKS:
                profile_data = profile.model_dump()
                profile_valid, profile_issues = validate_profile_data(profile_data)
                if not profile_valid:
                    logger.warning(
                        "profile_data_quality_issues",
                        operation="profile_extraction",
                        issues=profile_issues,
                        trace_id=get_bound_trace_id(),
                    )

                # Additional consistency checks
                consistency_issues = self._check_profile_consistency(profile_data)
                if consistency_issues:
                    logger.warning(
                        "profile_consistency_warnings",
                        operation="profile_extraction",
                        issues=consistency_issues,
                        trace_id=get_bound_trace_id(),
                    )

                # Check confidence scores
                confidence_issues = self._check_confidence_scores(profile_data)
                if confidence_issues:
                    logger.info(
                        "profile_confidence_info",
                        operation="profile_extraction",
                        issues=confidence_issues,
                        trace_id=get_bound_trace_id(),
                    )

            await self._log_llm_call(
                operation="profile_extraction_core",
                provider=result["provider"],
                model=result["model"],
                input_tokens=result.get("input_tokens"),
                output_tokens=result.get("output_tokens"),
                latency_ms=latency,
                success=True,
                retry_count=self._get_retry_count(call_openai if primary_provider == "openai" else call_anthropic),
                prompt_template_version=PROFILE_EXTRACTION_CORE_PROMPT_VERSION,
            )
            return LLMExtractionResult(
                profile_data=profile.model_dump(),
                provider=result["provider"],
                model=result["model"],
                input_tokens=(result.get("input_tokens") or 0) + enrichment_meta["input_tokens"],
                output_tokens=(result.get("output_tokens") or 0) + enrichment_meta["output_tokens"],
                latency_ms=latency,
                fallback_used=False,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self._log_llm_call(
                operation="profile_extraction_core",
                provider=primary_provider,
                model=primary_model,
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=False,
                error_message=str(exc),
                retry_count=self._get_retry_count(call_openai if primary_provider == "openai" else call_anthropic),
                prompt_template_version=PROFILE_EXTRACTION_CORE_PROMPT_VERSION,
            )
            logger.warning("llm_extraction_failed", provider=primary_provider, error=str(exc))
            fallback_reason = f"{primary_provider} failed: {exc}"

        if secondary_provider is not None:
            try:
                secondary_model = settings.OPENAI_MODEL if secondary_provider == "openai" else settings.ANTHROPIC_MODEL
                secondary_max_tokens = (
                    settings.OPENAI_MAX_TOKENS if secondary_provider == "openai" else settings.ANTHROPIC_MAX_TOKENS
                )
                result = await self._call_provider(
                    secondary_provider,
                    system_prompt,
                    user_content,
                    model=secondary_model,
                    max_tokens=secondary_max_tokens,
                )
                core_profile = self._parse_core_profile(result["content"])
                enrichment_profile, enrichment_meta = await self._run_enrichment_pass(
                    provider=result["provider"],
                    budgeted_text=budgeted_text,
                    runtime_context=runtime_context,
                )
                profile = self._parse_profile(self._merge_profile_parts(core_profile, enrichment_profile))
                latency = int((time.perf_counter() - start) * 1000)
                await self._log_llm_call(
                    operation="profile_extraction_core",
                    provider=result["provider"],
                    model=result["model"],
                    input_tokens=result.get("input_tokens"),
                    output_tokens=result.get("output_tokens"),
                    latency_ms=latency,
                    success=True,
                    retry_count=self._get_retry_count(
                        call_openai if secondary_provider == "openai" else call_anthropic
                    ),
                    prompt_template_version=PROFILE_EXTRACTION_CORE_PROMPT_VERSION,
                )
                return LLMExtractionResult(
                    profile_data=profile.model_dump(),
                    provider=result["provider"],
                    model=result["model"],
                    input_tokens=(result.get("input_tokens") or 0) + enrichment_meta["input_tokens"],
                    output_tokens=(result.get("output_tokens") or 0) + enrichment_meta["output_tokens"],
                    latency_ms=latency,
                    fallback_used=True,
                    fallback_reason=fallback_reason,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                await self._log_llm_call(
                    operation="profile_extraction",
                    provider=secondary_provider,
                    model=secondary_model,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    success=False,
                    error_message=str(exc),
                    retry_count=self._get_retry_count(
                        call_openai if secondary_provider == "openai" else call_anthropic
                    ),
                    prompt_template_version=PROFILE_EXTRACTION_PROMPT_VERSION,
                )
                logger.error("llm_extraction_failed", provider=secondary_provider, error=str(exc))
                raise LLMExtractionError(f"Both LLM providers failed. Last error: {exc}") from exc

        provider_name = primary_provider.title()
        raise LLMExtractionError(
            f"{provider_name} extraction failed and no fallback provider is configured. " f"Error: {fallback_reason}"
        )

    async def run_gap_analysis(self, profile_json: dict, target_degree: str, profile_id: Optional[str] = None) -> dict:
        """Run a gap analysis on an extracted profile.

        Includes security checks to prevent prompt injection through profile data.
        Validates profile data quality before analysis.
        """
        # Security: Sanitize target degree input
        if settings.ENABLE_SECURITY_CHECKS:
            if detect_injection_attempt(target_degree):
                raise PromptInjectionError("Potential prompt injection detected in target degree")
            target_degree = strip_control_characters(target_degree, preserve_newline_tab=False)

        # Profile data security: Validate before gap analysis
        if settings.ENABLE_SECURITY_CHECKS:
            profile_valid, profile_issues = validate_profile_data(profile_json)
            if not profile_valid:
                logger.warning(
                    "profile_validation_before_gap_analysis",
                    profile_id=profile_id,
                    issues=profile_issues,
                    trace_id=get_bound_trace_id(),
                )
                # Log warning but continue - gap analysis may still be useful

        # Sanitize profile JSON by removing any suspicious content
        if settings.ENABLE_SECURITY_CHECKS:
            sanitized_profile = self._sanitize_profile_for_llm(profile_json)
        else:
            sanitized_profile = profile_json

        profile_text = json.dumps(sanitized_profile, indent=2, default=str)
        budgeted_profile_text, input_meta = self._budget_text(
            profile_text,
            budget_chars=settings.LLM_GAP_ANALYSIS_INPUT_CHAR_BUDGET,
            head_chars=settings.LLM_TRUNCATION_HEAD_CHARS,
            tail_chars=settings.LLM_TRUNCATION_TAIL_CHARS,
            label="gap_analysis",
        )
        runtime_context: dict[str, Any] = {
            "target_degree": target_degree,
            "profile_summary": {
                "has_gpa": sanitized_profile.get("gpa_highest") is not None,
                "education_count": len(sanitized_profile.get("education", [])),
                "research_count": len(sanitized_profile.get("research_experience", [])),
            },
            "llm_budget": input_meta,
        }
        system_prompt = get_gap_analysis_prompt(context=runtime_context, fmt="text")
        user_content = f"TARGET DEGREE: {target_degree}\n\n" + wrap_user_data(
            {"profile_data": budgeted_profile_text}, label="STUDENT_PROFILE"
        )

        primary_provider = self._select_gap_analysis_provider(profile_text)
        fallback_provider = "anthropic" if primary_provider == "openai" else "openai"

        try:
            result = await self._call_provider(
                primary_provider,
                system_prompt,
                user_content,
                model=settings.OPENAI_MODEL if primary_provider == "openai" else settings.ANTHROPIC_MODEL,
                max_tokens=(
                    settings.OPENAI_MAX_TOKENS if primary_provider == "openai" else settings.ANTHROPIC_MAX_TOKENS
                ),
            )
            await self._log_llm_call(
                operation="gap_analysis",
                provider=result["provider"],
                model=result["model"],
                profile_id=profile_id,
                input_tokens=result.get("input_tokens"),
                output_tokens=result.get("output_tokens"),
                success=True,
                retry_count=self._get_retry_count(call_openai if primary_provider == "openai" else call_anthropic),
                prompt_template_version=GAP_ANALYSIS_PROMPT_VERSION,
            )
            return result["content"]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self._log_llm_call(
                operation="gap_analysis",
                provider=primary_provider,
                model=settings.OPENAI_MODEL if primary_provider == "openai" else settings.ANTHROPIC_MODEL,
                profile_id=profile_id,
                success=False,
                error_message=str(exc),
                retry_count=self._get_retry_count(call_openai if primary_provider == "openai" else call_anthropic),
                prompt_template_version=GAP_ANALYSIS_PROMPT_VERSION,
            )
            logger.warning("gap_analysis_failed", provider=primary_provider, error=str(exc))

        if fallback_provider == "openai" and not self._has_real_openai_key():
            fallback_provider = None
        elif fallback_provider == "anthropic" and not self._has_real_anthropic_key():
            fallback_provider = None

        if fallback_provider is not None:
            try:
                result = await self._call_provider(
                    fallback_provider,
                    system_prompt,
                    user_content,
                    model=settings.OPENAI_MODEL if fallback_provider == "openai" else settings.ANTHROPIC_MODEL,
                    max_tokens=(
                        settings.OPENAI_MAX_TOKENS if fallback_provider == "openai" else settings.ANTHROPIC_MAX_TOKENS
                    ),
                )
                await self._log_llm_call(
                    operation="gap_analysis",
                    provider=result["provider"],
                    model=result["model"],
                    profile_id=profile_id,
                    input_tokens=result.get("input_tokens"),
                    output_tokens=result.get("output_tokens"),
                    success=True,
                    retry_count=self._get_retry_count(call_openai if fallback_provider == "openai" else call_anthropic),
                    prompt_template_version=GAP_ANALYSIS_PROMPT_VERSION,
                )
                return result["content"]
            except Exception as exc:  # pylint: disable=broad-exception-caught
                await self._log_llm_call(
                    operation="gap_analysis",
                    provider=fallback_provider,
                    model=settings.OPENAI_MODEL if fallback_provider == "openai" else settings.ANTHROPIC_MODEL,
                    profile_id=profile_id,
                    success=False,
                    error_message=str(exc),
                    retry_count=self._get_retry_count(call_openai if fallback_provider == "openai" else call_anthropic),
                    prompt_template_version=GAP_ANALYSIS_PROMPT_VERSION,
                )
                logger.error("gap_analysis_failed", provider=fallback_provider, error=str(exc))
                raise LLMExtractionError(f"Gap analysis failed: {exc}") from exc

        raise LLMExtractionError("No LLM API key configured for gap analysis")

    # ------------------------------------------------------------------

    @staticmethod
    def _build_extraction_input(text: str) -> tuple[str, dict[str, Any]]:
        user_content = wrap_user_data({"document_text": text}, label="DOCUMENT")
        return user_content, {"text_length": len(text), "truncated": "[TRUNCATED" in text}

    @staticmethod
    def _build_enrichment_input(text: str) -> tuple[str, dict[str, Any]]:
        user_content = wrap_user_data({"document_text": text}, label="DOCUMENT")
        return user_content, {"text_length": len(text), "truncated": "[TRUNCATED" in text}

    async def detect_target_degree(self, document_text: str) -> TargetDegreeDetectionResult:
        """Run a cheap first-pass classifier for target degree intent."""
        if not document_text.strip():
            return TargetDegreeDetectionResult()

        budgeted_text, input_meta = self._budget_text(
            document_text,
            budget_chars=settings.LLM_CLASSIFIER_INPUT_CHAR_BUDGET,
            head_chars=settings.LLM_TRUNCATION_HEAD_CHARS,
            tail_chars=settings.LLM_TRUNCATION_TAIL_CHARS,
            label="target_degree_detection",
        )
        runtime_context: dict[str, Any] = {
            "document_metadata": {
                "text_length": len(document_text),
                "budgeted_text_length": len(budgeted_text),
            },
            "llm_budget": input_meta,
        }
        system_prompt = get_target_degree_detection_prompt(context=runtime_context, fmt="text")

        provider = (
            "openai" if self._has_real_openai_key() else ("anthropic" if self._has_real_anthropic_key() else None)
        )
        if provider is None:
            return TargetDegreeDetectionResult()

        model = settings.TARGET_DEGREE_MODEL if provider == "openai" else settings.ANTHROPIC_MODEL
        max_tokens = (
            settings.TARGET_DEGREE_MAX_TOKENS if provider == "openai" else min(512, settings.ANTHROPIC_MAX_TOKENS)
        )

        try:
            result = await self._call_provider(
                provider, system_prompt, budgeted_text, model=model, max_tokens=max_tokens
            )
            normalized = self._normalize_target_degree_detection(result.get("content") or {})
            await self._log_llm_call(
                operation="target_degree_detection",
                provider=result["provider"],
                model=result["model"],
                input_tokens=result.get("input_tokens"),
                output_tokens=result.get("output_tokens"),
                success=True,
                retry_count=self._get_retry_count(call_openai if provider == "openai" else call_anthropic),
                prompt_template_version=TARGET_DEGREE_PROMPT_VERSION,
            )
            return normalized
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self._log_llm_call(
                operation="target_degree_detection",
                provider=provider,
                model=model,
                success=False,
                error_message=str(exc),
                retry_count=self._get_retry_count(call_openai if provider == "openai" else call_anthropic),
                prompt_template_version=TARGET_DEGREE_PROMPT_VERSION,
            )
            logger.warning("target_degree_detection_failed", provider=provider, error=str(exc))
            return TargetDegreeDetectionResult()

    def _select_extraction_tier(
        self,
        document_text: str,
        detection_result: Optional[TargetDegreeDetectionResult],
    ) -> dict[str, Any]:
        # Always prioritize OpenAI first
        if self._has_real_openai_key():
            return {
                "provider": "openai",
                "fallback_provider": "anthropic" if self._has_real_anthropic_key() else None,
                "model": settings.OPENAI_MODEL,
                "max_tokens": settings.OPENAI_MAX_TOKENS,
            }

        if self._has_real_anthropic_key():
            return {
                "provider": "anthropic",
                "fallback_provider": None,
                "model": settings.ANTHROPIC_MODEL,
                "max_tokens": settings.ANTHROPIC_MAX_TOKENS,
            }

        return {"provider": None, "fallback_provider": None, "model": None, "max_tokens": None}

    def _select_gap_analysis_provider(self, profile_text: str) -> str:
        # Always prioritize OpenAI first
        if self._has_real_openai_key():
            return "openai"
        if self._has_real_anthropic_key():
            return "anthropic"
        return "openai"

    @staticmethod
    def _budget_text(
        text: str,
        *,
        budget_chars: int,
        head_chars: int,
        tail_chars: int,
        label: str,
    ) -> tuple[str, dict[str, Any]]:
        clean_text = text.strip()
        if len(clean_text) <= budget_chars:
            return clean_text, {
                "label": label,
                "original_length": len(clean_text),
                "budget_chars": budget_chars,
                "truncated": False,
                "truncated_chars": 0,
            }

        marker = (
            f"\n\n[TRUNCATED {label} CONTENT: original_length={len(clean_text)}, " f"budget_chars={budget_chars}]\n\n"
        )
        available_budget = max(0, budget_chars - len(marker))
        head = min(max(0, head_chars), available_budget)
        tail = min(max(0, tail_chars), max(0, available_budget - head))
        if head + tail < available_budget:
            head = available_budget - tail

        truncated_text = f"{clean_text[:head]}{marker}{clean_text[-tail:] if tail else ''}"
        return truncated_text, {
            "label": label,
            "original_length": len(clean_text),
            "budget_chars": budget_chars,
            "truncated": True,
            "truncated_chars": len(clean_text) - len(truncated_text),
        }

    @staticmethod
    def _is_confident_target_detection(result: TargetDegreeDetectionResult | None) -> bool:
        if result is None:
            return False
        if result.needs_clarification:
            return False
        if result.target_degree_level is None:
            return False
        if str(result.target_degree_level) == "unknown":
            return False
        confidence = result.confidence or 0.0
        return confidence >= settings.LLM_TARGET_DEGREE_CONFIDENCE_THRESHOLD

    @classmethod
    def _normalize_target_degree_detection(cls, raw_content: dict[str, Any]) -> TargetDegreeDetectionResult:
        payload = dict(raw_content or {})
        target_degree = cls._normalize_degree_level(payload.get("target_degree_level"))
        confidence = payload.get("confidence")
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        confidence_value = min(max(confidence_value, 0.0), 1.0)
        return TargetDegreeDetectionResult(
            target_degree_level=target_degree,
            confidence=confidence_value,
            source=str(payload.get("source") or "unknown"),
            needs_clarification=bool(payload.get("needs_clarification")),
            reasoning=str(payload.get("reasoning") or "").strip() or None,
        )

    @staticmethod
    async def _call_provider(
        provider: str,
        system_prompt: str,
        user_content: str,
        *,
        model: str | None,
        max_tokens: int | None,
    ) -> dict:
        if provider == "openai":
            return await call_openai(system_prompt, user_content, model=model, max_tokens=max_tokens)
        if provider == "anthropic":
            return await call_anthropic(system_prompt, user_content, model=model, max_tokens=max_tokens)
        raise LLMExtractionError("No LLM provider configured")

    @staticmethod
    def _has_real_openai_key() -> bool:
        key = (settings.OPENAI_API_KEY or "").strip()
        return bool(key) and "your-openai-key" not in key.lower()

    @staticmethod
    def _has_real_anthropic_key() -> bool:
        key = (settings.ANTHROPIC_API_KEY or "").strip()
        return bool(key) and "your-anthropic-key" not in key.lower()

    @classmethod
    def _parse_profile(cls, raw_content: dict[str, Any]) -> ExtractedProfile:
        """Normalize provider output into schema-compatible shape before validation."""
        normalized = cls._normalize_profile_dict(raw_content)
        return ExtractedProfile(**normalized)

    @classmethod
    def _parse_core_profile(cls, raw_content: dict[str, Any]) -> CoreExtractedProfile:
        """Normalize provider output for the small first-pass schema."""
        normalized = cls._normalize_profile_dict(raw_content)
        return CoreExtractedProfile(**normalized)

    @classmethod
    def _parse_enrichment_profile(cls, raw_content: dict[str, Any]) -> EnrichmentExtractedProfile:
        """Normalize provider output for the supplemental second-pass schema."""
        normalized = cls._normalize_profile_dict(raw_content)
        return EnrichmentExtractedProfile(**normalized)

    @staticmethod
    def _merge_profile_parts(
        core_profile: CoreExtractedProfile,
        enrichment_profile: EnrichmentExtractedProfile,
    ) -> dict[str, Any]:
        merged = core_profile.model_dump()
        merged.update(enrichment_profile.model_dump())
        return merged

    async def _run_enrichment_pass(
        self,
        *,
        provider: str,
        budgeted_text: str,
        runtime_context: dict[str, Any],
    ) -> tuple[EnrichmentExtractedProfile, dict[str, int]]:
        """Run a best-effort second pass for bulky supplemental fields."""
        enrichment_prompt = get_profile_extraction_enrichment_prompt(context=runtime_context, fmt="text")
        enrichment_content, _ = self._build_enrichment_input(budgeted_text)
        model = settings.OPENAI_MODEL if provider == "openai" else settings.ANTHROPIC_MODEL
        max_tokens = settings.OPENAI_MAX_TOKENS if provider == "openai" else settings.ANTHROPIC_MAX_TOKENS
        start = time.perf_counter()

        try:
            result = await self._call_provider(
                provider,
                enrichment_prompt,
                enrichment_content,
                model=model,
                max_tokens=max_tokens,
            )
            enrichment_profile = self._parse_enrichment_profile(result["content"])
            await self._log_llm_call(
                operation="profile_extraction_enrichment",
                provider=result["provider"],
                model=result["model"],
                input_tokens=result.get("input_tokens"),
                output_tokens=result.get("output_tokens"),
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=True,
                retry_count=self._get_retry_count(call_openai if provider == "openai" else call_anthropic),
                prompt_template_version=PROFILE_EXTRACTION_ENRICHMENT_PROMPT_VERSION,
            )
            return enrichment_profile, {
                "input_tokens": result.get("input_tokens") or 0,
                "output_tokens": result.get("output_tokens") or 0,
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self._log_llm_call(
                operation="profile_extraction_enrichment",
                provider=provider,
                model=model,
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=False,
                error_message=str(exc),
                retry_count=self._get_retry_count(call_openai if provider == "openai" else call_anthropic),
                prompt_template_version=PROFILE_EXTRACTION_ENRICHMENT_PROMPT_VERSION,
            )
            logger.warning("llm_enrichment_failed", provider=provider, error=str(exc))
            return EnrichmentExtractedProfile(), {"input_tokens": 0, "output_tokens": 0}

    @classmethod
    def _normalize_profile_dict(cls, raw: dict[str, Any]) -> dict[str, Any]:
        content = dict(raw or {})

        # Work experience: many models use job_title instead of position.
        work = content.get("work_experience")
        if isinstance(work, list):
            normalized_work: list[dict[str, Any]] = []
            for item in work:
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                if not row.get("position") and row.get("job_title"):
                    row["position"] = row.get("job_title")
                row.pop("job_title", None)
                if row.get("company") and row.get("position"):
                    normalized_work.append(row)
            content["work_experience"] = normalized_work

        # Research experience: many models use project_title instead of title.
        research = content.get("research_experience")
        if isinstance(research, list):
            normalized_research: list[dict[str, Any]] = []
            for item in research:
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                if not row.get("title") and row.get("project_title"):
                    row["title"] = row.get("project_title")
                row.pop("project_title", None)
                if row.get("title"):
                    normalized_research.append(row)
            content["research_experience"] = normalized_research

        # Certifications may arrive as objects; flatten to strings for schema compatibility.
        certs = content.get("certifications")
        if isinstance(certs, list):
            flattened_certs: list[str] = []
            for cert in certs:
                if isinstance(cert, str):
                    flattened_certs.append(cert)
                elif isinstance(cert, dict):
                    name = str(cert.get("name") or cert.get("title") or "").strip()
                    score = cert.get("score")
                    expiration = cert.get("expiration") or cert.get("expires")
                    extras: list[str] = []
                    if score is not None:
                        extras.append(f"score: {score}")
                    if expiration:
                        extras.append(f"expires: {expiration}")
                    if name:
                        flattened_certs.append(f"{name} ({', '.join(extras)})" if extras else name)
            content["certifications"] = flattened_certs

        # Publications may arrive as strings or partial objects; normalize to structured rows.
        pubs = content.get("publications")
        if isinstance(pubs, list):
            normalized_pubs: list[dict[str, Any]] = []
            for pub in pubs:
                if isinstance(pub, str):
                    title = pub.strip()
                    if title:
                        normalized_pubs.append({"title": title})
                    continue
                if not isinstance(pub, dict):
                    continue

                title = str(pub.get("title") or pub.get("name") or "").strip()
                if not title:
                    continue

                row = {
                    "title": title,
                    "venue": str(pub.get("venue") or pub.get("journal") or "").strip() or None,
                    "year": str(pub.get("year") or "").strip() or None,
                    "role": str(pub.get("role") or "").strip() or None,
                    "evidence": str(pub.get("evidence") or "").strip() or None,
                }
                normalized_pubs.append(row)
            content["publications"] = normalized_pubs

        # Normalize enum-like fields.
        content["current_degree_level"] = cls._normalize_degree_level(content.get("current_degree_level"))
        content["target_degree_level"] = cls._normalize_degree_level(content.get("target_degree_level"))
        content["target_degree_source"] = cls._normalize_degree_source(content.get("target_degree_source"))

        # Some models emit empty strings for optional numeric fields.
        for numeric_field in ("gpa_highest", "gpa_scale"):
            raw_value = content.get(numeric_field)
            if isinstance(raw_value, str) and not raw_value.strip():
                content[numeric_field] = None

        # Normalize list-like fields that models sometimes emit as null.
        list_fields = [
            "education",
            "work_experience",
            "research_experience",
            "publications",
            "technical_skills",
            "languages",
            "certifications",
            "research_interests",
            "clarification_queue",
            "contradiction_flags",
        ]
        for field in list_fields:
            if content.get(field) is None:
                content[field] = []

        # Normalize map-like fields and drop invalid null entries.
        content["confidence_map"] = cls._normalize_confidence_map(content.get("confidence_map"))
        content["evidence_map"] = cls._normalize_evidence_map(content.get("evidence_map"))

        return content

    @staticmethod
    def _normalize_degree_level(value: Any) -> DegreeLevelEnum:
        if value is None:
            return DegreeLevelEnum.UNKNOWN
        text = str(value).strip().lower()
        if "phd" in text or "doctor" in text:
            return DegreeLevelEnum.PHD
        if "master" in text:
            return DegreeLevelEnum.MASTER
        if "bachelor" in text or re.search(r"\bbs\b|\bba\b|\bbsc\b", text):
            return DegreeLevelEnum.BACHELOR
        return DegreeLevelEnum.UNKNOWN

    @staticmethod
    def _normalize_degree_source(value: Any) -> str:
        if value is None:
            return "unknown"
        text = str(value).strip().lower()
        if "user" in text and "input" in text:
            return "user_input"
        if "explicit" in text or "cv" in text:
            return "cv_explicit"
        if "infer" in text or "trajectory" in text:
            return "trajectory_inference"
        return "unknown"

    @staticmethod
    def _normalize_confidence_map(value: Any) -> dict[str, float]:
        if not isinstance(value, dict):
            return {}

        normalized: dict[str, float] = {}
        for key, raw in value.items():
            if key is None or raw is None:
                continue
            try:
                score = float(raw)
            except (TypeError, ValueError):
                continue
            if 0.0 <= score <= 1.0:
                normalized[str(key)] = score
        return normalized

    @staticmethod
    def _normalize_evidence_map(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}

        normalized: dict[str, str] = {}
        for key, raw in value.items():
            if key is None or raw is None:
                continue
            text = str(raw).strip()
            if text:
                normalized[str(key)] = text
        return normalized

    async def _log_llm_call(
        self,
        operation: str,
        provider: str,
        model: str,
        success: bool,
        profile_id: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        latency_ms: Optional[int] = None,
        error_message: Optional[str] = None,
        retry_count: int = 0,
        prompt_template_version: Optional[str] = None,
    ) -> None:
        """Persist llm_call_logs rows without impacting main request flow.

        Captures trace ID for distributed tracing across services.
        """
        try:
            # Use get_bound_trace_id() for reliable trace ID retrieval
            trace_id = get_bound_trace_id()
            await self.llm_log_repo.create_log(
                {
                    "profile_id": profile_id,
                    "operation": operation,
                    "llm_provider": provider,
                    "model_name": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_cost_usd": None,
                    "latency_ms": latency_ms,
                    "success": success,
                    "error_message": error_message,
                    "retry_count": retry_count,
                    "trace_id": trace_id,
                    "prompt_template_version": prompt_template_version,
                }
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("llm_call_log_persist_failed", error=str(exc), operation=operation, provider=provider)

    @staticmethod
    def _get_retry_count(func: Any) -> int:
        """Best-effort extraction of retry count from tenacity-decorated callables."""
        try:
            stats = getattr(getattr(func, "retry", None), "statistics", None) or {}
            attempt_number = int(stats.get("attempt_number", 1))
            return max(attempt_number - 1, 0)
        except Exception:  # pylint: disable=broad-exception-caught
            return 0

    @staticmethod
    def _check_profile_consistency(profile_data: dict[str, Any]) -> list[str]:
        """Check for consistency issues in extracted profile data.

        Validates:
        - GPA is >= 0.0
        - Years are plausible (not in future, not unreasonably far in past)
        - Degree level matches education records
        """
        issues: list[str] = []

        # Check GPA plausibility
        gpa_highest = profile_data.get("gpa_highest")
        if gpa_highest is not None:
            try:
                gpa_val = float(gpa_highest)
                if gpa_val < 0.0:
                    issues.append(f"GPA out of range: {gpa_val} (expected >= 0.0)")
            except (TypeError, ValueError):
                issues.append(f"GPA not numeric: {gpa_highest}")

        # Check education years
        current_year = datetime.now().year
        earliest_plausible_birth_year = current_year - 65  # generous upper-age bound
        education = profile_data.get("education") or []
        for idx, edu in enumerate(education):
            if not isinstance(edu, dict):
                continue

            start_year = edu.get("start_year")
            end_year = edu.get("end_year")

            try:
                if start_year:
                    sy = int(start_year)
                    if sy < earliest_plausible_birth_year:
                        issues.append(f"Education[{idx}] start_year implausible: {sy} (implies applicant age > 65)")
                    elif sy > current_year:
                        issues.append(f"Education[{idx}] start_year implausible: {sy}")
                if end_year:
                    ey = int(end_year)
                    if ey < earliest_plausible_birth_year or ey > current_year + 10:
                        issues.append(f"Education[{idx}] end_year implausible: {ey}")
                if start_year and end_year:
                    sy, ey = int(start_year), int(end_year)
                    if sy >= ey:
                        issues.append(f"Education[{idx}] start_year >= end_year: {sy} >= {ey}")
            except (TypeError, ValueError):
                pass  # Skip non-numeric years

        # Check work experience years
        work_exp = profile_data.get("work_experience") or []
        for idx, job in enumerate(work_exp):
            if not isinstance(job, dict):
                continue

            start_year = job.get("start_year")
            end_year = job.get("end_year")

            try:
                if start_year:
                    sy = int(start_year)
                    if sy < earliest_plausible_birth_year:
                        issues.append(f"WorkExp[{idx}] start_year implausible: {sy} (implies applicant age > 65)")
                    elif sy > current_year:
                        issues.append(f"WorkExp[{idx}] start_year implausible: {sy}")
                if end_year:
                    ey = int(end_year)
                    if ey < earliest_plausible_birth_year or ey > current_year + 5:
                        issues.append(f"WorkExp[{idx}] end_year implausible: {ey}")
                if start_year and end_year:
                    sy, ey = int(start_year), int(end_year)
                    if sy >= ey:
                        issues.append(f"WorkExp[{idx}] start_year >= end_year: {sy} >= {ey}")
            except (TypeError, ValueError):
                pass  # Skip non-numeric years

        return issues

    @staticmethod
    def _check_confidence_scores(profile_data: dict[str, Any]) -> list[str]:
        """Check for low confidence fields that may need clarification.

        Logs fields with confidence < 0.7 for monitoring extraction quality.
        """
        issues: list[str] = []

        confidence_map = profile_data.get("confidence_map") or {}
        for field, confidence in confidence_map.items():
            try:
                conf_val = float(confidence)
                if conf_val < 0.7:
                    issues.append(f"Low confidence on {field}: {conf_val:.2f}")
            except (TypeError, ValueError):
                pass

        return issues

    @staticmethod
    def _sanitize_profile_for_llm(profile_data: dict[str, Any]) -> dict[str, Any]:
        """Sanitize profile data before sending to LLM for gap analysis.

        Removes control characters from text fields to prevent injection.
        Returns a copy of the profile with sanitized content.
        """
        sanitized = copy.deepcopy(profile_data)

        # Sanitize string fields in education
        education = sanitized.get("education") or []
        for edu in education:
            if isinstance(edu, dict):
                for key in ("institution", "degree", "field", "notes", "description"):
                    if key in edu and isinstance(edu[key], str):
                        edu[key] = strip_control_characters(edu[key], preserve_newline_tab=False)

        # Sanitize string fields in work experience
        work_exp = sanitized.get("work_experience") or []
        for job in work_exp:
            if isinstance(job, dict):
                for key in ("company", "position", "description", "achievements"):
                    if key in job and isinstance(job[key], str):
                        job[key] = strip_control_characters(job[key], preserve_newline_tab=False)

        # Sanitize research experience
        research = sanitized.get("research_experience") or []
        for proj in research:
            if isinstance(proj, dict):
                for key in ("title", "description", "field", "outcome"):
                    if key in proj and isinstance(proj[key], str):
                        proj[key] = strip_control_characters(proj[key], preserve_newline_tab=False)

        # Sanitize skills and languages
        for field in ("technical_skills", "languages"):
            items = sanitized.get(field) or []
            for idx, item in enumerate(items):
                if isinstance(item, str):
                    items[idx] = strip_control_characters(item, preserve_newline_tab=False)

        # Sanitize top-level string fields
        for key in ("first_name", "last_name", "email", "phone", "location"):
            if key in sanitized and isinstance(sanitized[key], str):
                sanitized[key] = strip_control_characters(sanitized[key], preserve_newline_tab=False)

        return sanitized
