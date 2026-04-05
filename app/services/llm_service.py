"""LLM service with primary/fallback provider and structured extraction."""

import json
import re
import time
from typing import Any, Optional

import structlog

from app.config import settings
from app.core.logging import get_logger
from app.llm.anthropic_client import call_anthropic
from app.llm.openai_client import call_openai
from app.llm.prompts import get_gap_analysis_prompt, get_profile_extraction_prompt
from app.llm.schemas import ExtractedProfile
from app.models.llm_models import LLMExtractionResult
from app.repositories.mysql_llm_log_repo import LLMCallLogRepository
from app.utils.exceptions import LLMExtractionError

logger = get_logger(__name__)

PROFILE_EXTRACTION_PROMPT_VERSION = "profile_extraction_v2"
GAP_ANALYSIS_PROMPT_VERSION = "gap_analysis_v2"


class LLMService:
    """Orchestrates LLM calls with primary -> fallback provider logic."""

    def __init__(self):
        self.llm_log_repo = LLMCallLogRepository()

    async def extract_profile(
        self, document_text: str, target_degree_hint: Optional[str] = None
    ) -> LLMExtractionResult:
        """Extract structured profile data from document text using LLM.

        Tries OpenAI first; falls back to Anthropic on failure.
        """
        runtime_context: dict[str, Any] = {
            "document_metadata": {
                "text_length": len(document_text),
                "has_target_hint": target_degree_hint is not None,
            },
        }
        if target_degree_hint:
            runtime_context["user_provided_target_degree"] = target_degree_hint

        system_prompt = get_profile_extraction_prompt(context=runtime_context, fmt="text")
        user_content = self._build_extraction_input(document_text, target_degree_hint)

        start = time.perf_counter()
        fallback_reason: Optional[str] = None

        # Primary: OpenAI (required)
        if not self._has_real_openai_key():
            raise LLMExtractionError("OpenAI API key is not configured")

        try:
            result = await call_openai(system_prompt, user_content)
            profile = self._parse_profile(result["content"])
            latency = int((time.perf_counter() - start) * 1000)
            await self._log_llm_call(
                operation="profile_extraction",
                provider=result["provider"],
                model=result["model"],
                input_tokens=result.get("input_tokens"),
                output_tokens=result.get("output_tokens"),
                latency_ms=latency,
                success=True,
                retry_count=self._get_retry_count(call_openai),
                prompt_template_version=PROFILE_EXTRACTION_PROMPT_VERSION,
            )
            return LLMExtractionResult(
                profile_data=profile.model_dump(),
                provider=result["provider"],
                model=result["model"],
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                latency_ms=latency,
                fallback_used=False,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self._log_llm_call(
                operation="profile_extraction",
                provider="openai",
                model=settings.OPENAI_MODEL,
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=False,
                error_message=str(exc),
                retry_count=self._get_retry_count(call_openai),
                prompt_template_version=PROFILE_EXTRACTION_PROMPT_VERSION,
            )
            logger.warning("openai_extraction_failed", error=str(exc))
            fallback_reason = f"OpenAI failed: {exc}"

        # Fallback: Anthropic (optional)
        if self._has_real_anthropic_key():
            try:
                result = await call_anthropic(system_prompt, user_content)
                profile = self._parse_profile(result["content"])
                latency = int((time.perf_counter() - start) * 1000)
                await self._log_llm_call(
                    operation="profile_extraction",
                    provider=result["provider"],
                    model=result["model"],
                    input_tokens=result.get("input_tokens"),
                    output_tokens=result.get("output_tokens"),
                    latency_ms=latency,
                    success=True,
                    retry_count=self._get_retry_count(call_anthropic),
                    prompt_template_version=PROFILE_EXTRACTION_PROMPT_VERSION,
                )
                return LLMExtractionResult(
                    profile_data=profile.model_dump(),
                    provider=result["provider"],
                    model=result["model"],
                    input_tokens=result["input_tokens"],
                    output_tokens=result["output_tokens"],
                    latency_ms=latency,
                    fallback_used=True,
                    fallback_reason=fallback_reason,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                await self._log_llm_call(
                    operation="profile_extraction",
                    provider="anthropic",
                    model=settings.ANTHROPIC_MODEL,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    success=False,
                    error_message=str(exc),
                    retry_count=self._get_retry_count(call_anthropic),
                    prompt_template_version=PROFILE_EXTRACTION_PROMPT_VERSION,
                )
                logger.error("anthropic_extraction_failed", error=str(exc))
                raise LLMExtractionError(f"Both LLM providers failed. Last error: {exc}") from exc
        else:
            # No fallback configured; report only OpenAI error
            raise LLMExtractionError(
                f"OpenAI extraction failed and Anthropic fallback is not configured. Error: {fallback_reason}"
            )

    async def run_gap_analysis(self, profile_json: dict, target_degree: str, profile_id: Optional[str] = None) -> dict:
        """Run a gap analysis on an extracted profile."""
        runtime_context: dict[str, Any] = {
            "target_degree": target_degree,
            "profile_summary": {
                "has_gpa": profile_json.get("gpa_highest") is not None,
                "education_count": len(profile_json.get("education", [])),
                "research_count": len(profile_json.get("research_experience", [])),
            },
        }
        system_prompt = get_gap_analysis_prompt(context=runtime_context, fmt="text")
        user_content = (
            f"TARGET DEGREE: {target_degree}\n\nSTUDENT PROFILE:\n" f"{json.dumps(profile_json, indent=2, default=str)}"
        )

        try:
            if settings.OPENAI_API_KEY:
                result = await call_openai(system_prompt, user_content)
                await self._log_llm_call(
                    operation="gap_analysis",
                    provider=result["provider"],
                    model=result["model"],
                    profile_id=profile_id,
                    input_tokens=result.get("input_tokens"),
                    output_tokens=result.get("output_tokens"),
                    success=True,
                    retry_count=self._get_retry_count(call_openai),
                    prompt_template_version=GAP_ANALYSIS_PROMPT_VERSION,
                )
                return result["content"]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self._log_llm_call(
                operation="gap_analysis",
                provider="openai",
                model=settings.OPENAI_MODEL,
                profile_id=profile_id,
                success=False,
                error_message=str(exc),
                retry_count=self._get_retry_count(call_openai),
                prompt_template_version=GAP_ANALYSIS_PROMPT_VERSION,
            )
            logger.warning("openai_gap_analysis_failed", error=str(exc))

        try:
            if settings.ANTHROPIC_API_KEY:
                result = await call_anthropic(system_prompt, user_content)
                await self._log_llm_call(
                    operation="gap_analysis",
                    provider=result["provider"],
                    model=result["model"],
                    profile_id=profile_id,
                    input_tokens=result.get("input_tokens"),
                    output_tokens=result.get("output_tokens"),
                    success=True,
                    retry_count=self._get_retry_count(call_anthropic),
                    prompt_template_version=GAP_ANALYSIS_PROMPT_VERSION,
                )
                return result["content"]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self._log_llm_call(
                operation="gap_analysis",
                provider="anthropic",
                model=settings.ANTHROPIC_MODEL,
                profile_id=profile_id,
                success=False,
                error_message=str(exc),
                retry_count=self._get_retry_count(call_anthropic),
                prompt_template_version=GAP_ANALYSIS_PROMPT_VERSION,
            )
            logger.error("anthropic_gap_analysis_failed", error=str(exc))
            raise LLMExtractionError(f"Gap analysis failed: {exc}") from exc

        raise LLMExtractionError("No LLM API key configured for gap analysis")

    # ------------------------------------------------------------------

    @staticmethod
    def _build_extraction_input(text: str, target_degree_hint: Optional[str] = None) -> str:
        parts = []
        if target_degree_hint:
            parts.append(f"USER-PROVIDED TARGET DEGREE: {target_degree_hint}")
        parts.append(f"DOCUMENT TEXT:\n{text}")
        return "\n\n".join(parts)

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
        content["target_degree_level"] = cls._normalize_degree_level(content.get("target_degree_level"))
        content["target_degree_source"] = cls._normalize_degree_source(content.get("target_degree_source"))

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
    def _normalize_degree_level(value: Any) -> str:
        if value is None:
            return "unknown"
        text = str(value).strip().lower()
        if "phd" in text or "doctor" in text:
            return "phd"
        if "master" in text:
            return "master"
        if "bachelor" in text or re.search(r"\bbs\b|\bba\b|\bbsc\b", text):
            return "bachelor"
        return "unknown"

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
        """Persist llm_call_logs rows without impacting main request flow."""
        try:
            trace_id = structlog.contextvars.get_contextvars().get("trace_id", "")
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
