"""Tests for LLM service (mocked — no real API calls)."""

import pytest

from app.services.llm_service import LLMService
from app.utils.exceptions import LLMExtractionError


@pytest.mark.asyncio
async def test_extract_profile_no_api_keys(monkeypatch):
    """With no API keys configured, extraction should raise."""
    monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", "")
    monkeypatch.setattr("app.config.settings.ANTHROPIC_API_KEY", "")

    service = LLMService()
    with pytest.raises(LLMExtractionError, match="No LLM API key configured"):
        await service.extract_profile("Some document text")
