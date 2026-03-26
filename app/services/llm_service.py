"""LLM service with primary/fallback provider and structured extraction."""

import json
import time
from typing import Any, Optional

from app.config import settings
from app.core.logging import get_logger
from app.llm.anthropic_client import call_anthropic
from app.llm.openai_client import call_openai
from app.llm.prompts import get_gap_analysis_prompt, get_profile_extraction_prompt
from app.llm.schemas import ExtractedProfile
from app.models.llm_models import LLMExtractionResult
from app.utils.exceptions import LLMExtractionError

logger = get_logger(__name__)


class LLMService:
    """Orchestrates LLM calls with primary -> fallback provider logic."""

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

        # Primary: OpenAI
        try:
            if settings.OPENAI_API_KEY:
                result = await call_openai(system_prompt, user_content)
                profile = ExtractedProfile(**result["content"])
                latency = int((time.perf_counter() - start) * 1000)
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
            logger.warning("openai_extraction_failed", error=str(exc))
            fallback_reason = f"OpenAI failed: {exc}"

        # Fallback: Anthropic
        try:
            if settings.ANTHROPIC_API_KEY:
                result = await call_anthropic(system_prompt, user_content)
                profile = ExtractedProfile(**result["content"])
                latency = int((time.perf_counter() - start) * 1000)
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
            logger.error("anthropic_extraction_failed", error=str(exc))
            raise LLMExtractionError(f"Both LLM providers failed. Last error: {exc}") from exc

        raise LLMExtractionError("No LLM API key configured")

    async def run_gap_analysis(self, profile_json: dict, target_degree: str) -> dict:
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
                return result["content"]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("openai_gap_analysis_failed", error=str(exc))

        try:
            if settings.ANTHROPIC_API_KEY:
                result = await call_anthropic(system_prompt, user_content)
                return result["content"]
        except Exception as exc:  # pylint: disable=broad-exception-caught
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
