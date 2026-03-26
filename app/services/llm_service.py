"""LLM service with primary/fallback provider and structured extraction."""

import time
from typing import Optional

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
    """Orchestrates LLM calls with primary → fallback provider logic."""

    async def extract_profile(
        self, document_text: str, target_degree_hint: Optional[str] = None
    ) -> LLMExtractionResult:
        """Extract structured profile data from document text using LLM.

        Tries OpenAI first; falls back to Anthropic on failure.
        """
        system_prompt = get_profile_extraction_prompt()
        user_content = self._build_extraction_input(document_text, target_degree_hint)

        start = time.perf_counter()
        fallback_used = False
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
        except Exception as exc:
            logger.warning("openai_extraction_failed", error=str(exc))
            fallback_reason = f"OpenAI failed: {exc}"

        # Fallback: Anthropic
        try:
            if settings.ANTHROPIC_API_KEY:
                fallback_used = True
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
        except Exception as exc:
            logger.error("anthropic_extraction_failed", error=str(exc))
            raise LLMExtractionError(
                f"Both LLM providers failed. Last error: {exc}"
            ) from exc

        raise LLMExtractionError("No LLM API key configured")

    async def run_gap_analysis(self, profile_json: dict, target_degree: str) -> dict:
        """Run a gap analysis on an extracted profile."""
        system_prompt = get_gap_analysis_prompt()
        user_content = (
            f"TARGET DEGREE: {target_degree}\n\n"
            f"STUDENT PROFILE:\n{self._dict_to_text(profile_json)}"
        )

        try:
            if settings.OPENAI_API_KEY:
                result = await call_openai(system_prompt, user_content)
                return result["content"]
        except Exception as exc:
            logger.warning("openai_gap_analysis_failed", error=str(exc))

        try:
            if settings.ANTHROPIC_API_KEY:
                result = await call_anthropic(system_prompt, user_content)
                return result["content"]
        except Exception as exc:
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
    def _dict_to_text(d: dict) -> str:
        import json

        return json.dumps(d, indent=2, default=str)
