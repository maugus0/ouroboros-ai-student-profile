"""Tests for LLM service (mocked — no real API calls)."""

import pytest

from app.config import settings
from app.services.llm_service import LLMService
from app.utils.exceptions import LLMExtractionError


@pytest.mark.asyncio
async def test_extract_profile_no_openai_key(monkeypatch):
    """OpenAI key is required for extraction."""
    monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", "")
    monkeypatch.setattr("app.config.settings.ANTHROPIC_API_KEY", "")

    service = LLMService()
    with pytest.raises(LLMExtractionError, match="No LLM API key configured for extraction"):
        await service.extract_profile("Some document text")


@pytest.mark.asyncio
async def test_run_gap_analysis_placeholder_keys_treated_as_not_configured(monkeypatch):
    """Placeholder keys should be ignored for gap analysis, same as extraction."""
    monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", "sk-your-openai-key-here")
    monkeypatch.setattr("app.config.settings.ANTHROPIC_API_KEY", "sk-ant-your-anthropic-key-here")

    async def should_not_be_called(*_args, **_kwargs):
        raise AssertionError("LLM provider call should not be attempted with placeholder keys")

    monkeypatch.setattr("app.services.llm_service.call_openai", should_not_be_called)
    monkeypatch.setattr("app.services.llm_service.call_anthropic", should_not_be_called)

    service = LLMService()
    with pytest.raises(LLMExtractionError, match="No LLM API key configured for gap analysis"):
        await service.run_gap_analysis({"education": []}, "Master of Computer Science")


@pytest.mark.asyncio
async def test_extract_profile_uses_tiered_model_selection_and_truncation(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-test-anthropic")

    calls: list[dict[str, object]] = []

    async def fake_openai(system_prompt, user_content, model=None, max_tokens=None, temperature=None):
        calls.append(
            {
                "provider": "openai",
                "system_prompt": system_prompt,
                "user_content": user_content,
                "model": model,
                "max_tokens": max_tokens,
            }
        )
        if "DECISION FRAMEWORK" in system_prompt:
            return {
                "content": {
                    "target_degree_level": "unknown",
                    "confidence": 0.35,
                    "source": "ambiguous",
                    "needs_clarification": True,
                    "reasoning": "Insufficient evidence to choose a future degree level.",
                },
                "provider": "openai",
                "model": model or settings.TARGET_DEGREE_MODEL,
                "input_tokens": 10,
                "output_tokens": 5,
            }

        return {
            "content": {
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "education": [],
                "work_experience": [],
                "research_experience": [],
                "technical_skills": [],
                "languages": [],
                "certifications": [],
                "research_interests": [],
                "publications": [],
            },
            "provider": "openai",
            "model": model or settings.OPENAI_MODEL,
            "input_tokens": 10,
            "output_tokens": 20,
        }

    async def fake_anthropic(system_prompt, user_content, model=None, max_tokens=None):
        calls.append(
            {
                "provider": "anthropic",
                "system_prompt": system_prompt,
                "user_content": user_content,
                "model": model,
                "max_tokens": max_tokens,
            }
        )
        return {
            "content": {
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "education": [],
                "work_experience": [],
                "research_experience": [],
                "technical_skills": [],
                "languages": [],
                "certifications": [],
                "research_interests": [],
                "publications": [],
            },
            "provider": "anthropic",
            "model": model or settings.ANTHROPIC_MODEL,
            "input_tokens": 12,
            "output_tokens": 18,
        }

    monkeypatch.setattr("app.services.llm_service.call_openai", fake_openai)
    monkeypatch.setattr("app.services.llm_service.call_anthropic", fake_anthropic)

    service = LLMService()
    long_document = "Bachelor student with research and internship details. " * 500

    result = await service.extract_profile(long_document)

    assert result.provider == "anthropic"
    assert len(calls) == 2
    assert calls[0]["provider"] == "openai"
    assert calls[1]["provider"] == "anthropic"
    assert calls[0]["model"] == settings.TARGET_DEGREE_MODEL
    assert calls[0]["max_tokens"] == settings.TARGET_DEGREE_MAX_TOKENS
    assert calls[1]["model"] == settings.ANTHROPIC_MODEL
    assert calls[1]["max_tokens"] == settings.ANTHROPIC_MAX_TOKENS
    assert "[TRUNCATED target_degree_detection CONTENT" in str(calls[0]["user_content"])
    assert "[TRUNCATED profile_extraction CONTENT" in str(calls[1]["user_content"])


@pytest.mark.asyncio
async def test_run_gap_analysis_uses_budgeted_profile_payload(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

    captured = {}

    async def fake_openai(system_prompt, user_content, model=None, max_tokens=None, temperature=None):
        captured["system_prompt"] = system_prompt
        captured["user_content"] = user_content
        captured["model"] = model
        captured["max_tokens"] = max_tokens
        return {
            "content": {"readiness_score": 0.72, "readiness_signals": [], "recommendations": []},
            "provider": "openai",
            "model": model or settings.OPENAI_MODEL,
            "input_tokens": 15,
            "output_tokens": 25,
        }

    monkeypatch.setattr("app.services.llm_service.call_openai", fake_openai)

    service = LLMService()
    profile_json = {
        "education": [],
        "work_experience": [],
        "research_experience": [],
        "technical_skills": [],
        "languages": [],
        "certifications": [],
        "research_interests": [],
        "publications": [],
        "notes": "x" * (settings.LLM_GAP_ANALYSIS_INPUT_CHAR_BUDGET + 5000),
    }

    result = await service.run_gap_analysis(profile_json, "master")

    assert result["readiness_score"] == 0.72
    assert captured["model"] == settings.OPENAI_MODEL
    assert captured["max_tokens"] == settings.OPENAI_MAX_TOKENS
    assert "[TRUNCATED gap_analysis CONTENT" in captured["user_content"]


def test_anthropic_placeholder_key_not_treated_as_real(monkeypatch):
    """Placeholder Anthropic keys should not trigger fallback attempts."""
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-your-anthropic-key-here")
    assert LLMService._has_real_anthropic_key() is False


def test_normalize_profile_dict_maps_common_model_variants():
    """Model output variants should be normalized into schema-compatible values."""
    raw = {
        "full_name": "John Doe",
        "target_degree_level": "Master",
        "target_degree_source": "inferred from current education and experience",
        "confidence_map": {"full_name": 1, "email": "0.9", "bad": 2, "none": None},
        "evidence_map": {"full_name": "Header", "nationality": None, "empty": "   "},
        "work_experience": [
            {
                "company": "TechCorp Inc",
                "job_title": "Software Engineer",
            }
        ],
        "certifications": [
            {
                "name": "TOEFL ITP",
                "score": 587,
                "expiration": "Aug 2025",
            }
        ],
        "publications": [
            {
                "name": "Graph Representation Learning for Admissions",
                "journal": "IEEE Access",
                "year": 2024,
            }
        ],
        "research_interests": None,
    }

    normalized = LLMService._normalize_profile_dict(raw)

    assert normalized["target_degree_level"] == "master"
    assert normalized["target_degree_source"] == "trajectory_inference"
    assert normalized["work_experience"][0]["position"] == "Software Engineer"
    assert normalized["certifications"][0].startswith("TOEFL ITP")
    assert normalized["publications"][0]["title"] == "Graph Representation Learning for Admissions"
    assert normalized["publications"][0]["venue"] == "IEEE Access"
    assert normalized["publications"][0]["year"] == "2024"
    assert normalized["research_interests"] == []
    assert normalized["confidence_map"] == {"full_name": 1.0, "email": 0.9}
    assert normalized["evidence_map"] == {"full_name": "Header"}
