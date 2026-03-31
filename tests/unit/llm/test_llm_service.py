"""Tests for LLM service (mocked — no real API calls)."""

from app.config import settings
import pytest

from app.services.llm_service import LLMService
from app.utils.exceptions import LLMExtractionError


@pytest.mark.asyncio
async def test_extract_profile_no_openai_key(monkeypatch):
    """OpenAI key is required for extraction."""
    monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", "")
    monkeypatch.setattr("app.config.settings.ANTHROPIC_API_KEY", "")

    service = LLMService()
    with pytest.raises(LLMExtractionError, match="OpenAI API key is not configured"):
        await service.extract_profile("Some document text")


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
