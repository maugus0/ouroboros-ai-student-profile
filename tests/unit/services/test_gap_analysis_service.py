"""Tests for gap analysis service persistence behavior."""

import pytest

from app.services.gap_analysis_service import GapAnalysisService
from app.utils.exceptions import NotFoundError


class _StubProfileRepo:
    def __init__(self, row):
        self._row = row

    async def get_profile_by_id(self, _profile_id):
        return self._row


class _StubLLMService:
    def __init__(self, result):
        self._result = result

    async def run_gap_analysis(self, _profile_json, _target_degree, profile_id=None):
        return self._result


class _StubNormalizedRepo:
    def __init__(self, profile_json=None):
        self._profile_json = profile_json or {}

    async def get_latest_profile_version(self, _profile_id):
        return {"profile_json": self._profile_json}


class _StubGapRepo:
    def __init__(self):
        self.calls = []

    async def create_analysis(self, analysis_data):
        self.calls.append(analysis_data)
        return "analysis-1"


@pytest.mark.asyncio
async def test_analyze_persists_gap_result():
    service = GapAnalysisService()
    service.profile_repo = _StubProfileRepo(
        {
            "target_degree_level": "master",
        }
    )
    service.normalized_repo = _StubNormalizedRepo({"full_name": "Test"})
    service.llm_service = _StubLLMService(
        {
            "readiness_score": 0.75,
            "gaps_identified": [{"area": "research", "severity": "medium"}],
            "recommendations": [{"area": "research", "action": "add research project"}],
        }
    )
    service.gap_repo = _StubGapRepo()

    result = await service.analyze("profile-1")

    assert result["readiness_score"] == 0.75
    assert isinstance(result["readiness_signals"], list)
    assert result["signal_summary"]["missing"] >= 1
    assert len(service.gap_repo.calls) == 1
    persisted = service.gap_repo.calls[0]
    assert persisted["profile_id"] == "profile-1"
    assert persisted["target_degree_level"] == "master"
    assert persisted["baseline_template"] == "baseline_master_v1"


@pytest.mark.asyncio
async def test_analyze_unknown_degree_persists_placeholder_result():
    service = GapAnalysisService()
    service.profile_repo = _StubProfileRepo(
        {
            "target_degree_level": "unknown",
        }
    )
    service.normalized_repo = _StubNormalizedRepo({"full_name": "Test"})
    service.gap_repo = _StubGapRepo()

    result = await service.analyze("profile-1")

    assert result["readiness_score"] is None
    assert result["signal_summary"]["missing"] == 1
    assert len(service.gap_repo.calls) == 1
    persisted = service.gap_repo.calls[0]
    assert persisted["profile_id"] == "profile-1"
    assert persisted["target_degree_level"] == "unknown"
    assert persisted["baseline_template"] == "baseline_unknown_v1"


@pytest.mark.asyncio
async def test_analyze_profile_not_found():
    service = GapAnalysisService()
    service.profile_repo = _StubProfileRepo(None)

    with pytest.raises(NotFoundError):
        await service.analyze("missing")
