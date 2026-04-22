"""Tests for clarification flow and async gap-analysis job lifecycle."""

from datetime import date

import pytest

from app.services.gap_analysis_service import GapAnalysisService
from app.services.profile_service import ProfileService


class _StubProfileRepo:
    def __init__(self, row):
        self.row = row
        self.updates = None

    async def get_profile_by_id(self, _profile_id):
        return self.row

    async def update_profile(self, _profile_id, updates):
        self.updates = updates
        return 1


class _StubGapJobRepo:
    def __init__(self):
        self.created = []
        self.updated = []
        self.job = None

    async def create_job(self, payload):
        self.created.append(payload)
        return "job-1"

    async def update_job(self, job_id, payload):
        self.updated.append((job_id, payload))
        return 1

    async def get_job(self, _job_id):
        return self.job


class _StubLLM:
    async def run_gap_analysis(self, _profile_json, _target_degree, profile_id=None):
        return {"readiness_score": 0.7, "gaps_identified": [], "recommendations": []}


class _StubGapRepo:
    async def create_analysis(self, _data):
        return "analysis-1"


class _StubNormalizedRepo:
    def __init__(self, profile_json):
        self.profile_json = profile_json

    async def get_latest_profile_version(self, _profile_id):
        return {"profile_json": self.profile_json}

    async def create_profile_version_snapshot(self, _profile_id, _version_number, _profile_json, _change_reason):
        return "ver-1"


@pytest.mark.asyncio
async def test_submit_clarifications_moves_status_to_analysis_ready():
    initial_profile_json = {"full_name": "Test"}

    row = {
        "profile_version": 1,
    }
    service = ProfileService()
    service.profile_repo = _StubProfileRepo(row)
    service.normalized_repo = _StubNormalizedRepo(initial_profile_json)

    result = await service.submit_clarifications(
        "profile-1",
        [
            {"field": "target_degree_level", "value": "master"},
            {"field": "current_degree_level", "value": "bachelor"},
        ],
    )

    assert result["status"] == "analysis_ready"
    assert result["clarification_queue"] == []
    assert service.profile_repo.updates["target_degree_level"] == "master"


def test_required_degree_clarifications_are_backfilled_when_unknown():
    profile_data = {
        "full_name": "Test",
        "current_degree_level": "unknown",
        "target_degree_level": None,
        "clarification_queue": [],
    }

    normalized = ProfileService._apply_react_decision_pattern(profile_data)

    queue_fields = {item["field"] for item in normalized["clarification_queue"]}
    assert queue_fields == {"current_degree_level", "target_degree_level"}


def test_missing_fields_are_moved_to_clarification_queue():
    profile_data = {
        "full_name": "John Doe",
        "clarification_queue": [],
        "missing_critical_fields": ["email", "research_interests"],
    }

    normalized = ProfileService._apply_react_decision_pattern(profile_data)

    queue_fields = {item["field"] for item in normalized["clarification_queue"]}
    assert "research_interests" in queue_fields
    assert normalized["react_decision_trace"]["email"]["decision"] == "accept"
    assert "missing_critical_fields" not in normalized


def test_publications_clarification_is_required_for_phd_when_missing():
    profile_data = {
        "target_degree_level": "phd",
        "publications": [],
        "clarification_queue": [],
    }

    normalized = ProfileService._apply_react_decision_pattern(profile_data)

    queue_fields = {item["field"] for item in normalized["clarification_queue"]}
    assert "publications" in queue_fields
    assert normalized["target_degree_needs_clarification"] is False


def test_react_keeps_publications_in_trace_as_accept_after_user_answer():
    profile_data = {
        "target_degree_level": "phd",
        "publications": "No, does not have publications",
        "confidence_map": {"publications": 1.0},
        "clarification_queue": [],
    }

    normalized = ProfileService._apply_react_decision_pattern(profile_data)

    assert normalized["react_decision_trace"]["publications"]["decision"] == "accept"
    queue_fields = {item["field"] for item in normalized["clarification_queue"]}
    assert "publications" not in queue_fields


def test_react_marks_low_confidence_critical_field_for_clarification():
    profile_data = {
        "target_degree_level": "master",
        "confidence_map": {"target_degree_level": 0.4},
        "clarification_queue": [],
    }

    normalized = ProfileService._apply_react_decision_pattern(profile_data)

    queue_fields = {item["field"] for item in normalized["clarification_queue"]}
    assert "target_degree_level" in queue_fields
    assert normalized["react_decision_trace"]["target_degree_level"]["decision"] == "clarify"
    assert normalized["react_decision_trace"]["target_degree_level"]["reason"] == "low_confidence"
    assert normalized["target_degree_needs_clarification"] is True


def test_react_allows_same_current_and_target_degree_levels():
    profile_data = {
        "current_degree_level": "master",
        "target_degree_level": "master",
        "confidence_map": {
            "current_degree_level": 1.0,
            "target_degree_level": 1.0,
        },
        "clarification_queue": [],
    }

    normalized = ProfileService._apply_react_decision_pattern(profile_data)

    queue_fields = {item["field"] for item in normalized["clarification_queue"]}
    assert "target_degree_level" not in queue_fields
    assert normalized["target_degree_needs_clarification"] is False


def test_react_marks_contradicted_field_for_clarification():
    profile_data = {
        "full_name": "John Doe",
        "confidence_map": {"full_name": 0.95},
        "contradiction_flags": [{"field": "full_name", "description": "Name conflict across documents"}],
        "clarification_queue": [],
    }

    normalized = ProfileService._apply_react_decision_pattern(profile_data)

    queue_fields = {item["field"] for item in normalized["clarification_queue"]}
    assert "full_name" in queue_fields
    assert normalized["react_decision_trace"]["full_name"]["decision"] == "clarify"
    assert normalized["react_decision_trace"]["full_name"]["reason"] == "contradiction_detected"


@pytest.mark.asyncio
async def test_submit_clarifications_updates_dob_from_human_date_format():
    initial_profile_json = {"full_name": "Test"}

    row = {
        "profile_version": 1,
    }
    service = ProfileService()
    service.profile_repo = _StubProfileRepo(row)
    service.normalized_repo = _StubNormalizedRepo(initial_profile_json)

    result = await service.submit_clarifications(
        "profile-1",
        [
            {"field": "date_of_birth", "value": "15 Jan 2000"},
            {"field": "current_degree_level", "value": "bachelor"},
            {"field": "target_degree_level", "value": "master"},
        ],
    )

    assert result["status"] == "analysis_ready"
    assert service.profile_repo.updates["date_of_birth"] == date(2000, 1, 15)
    assert service.profile_repo.updates["current_degree_level"] == "bachelor"
    assert service.profile_repo.updates["target_degree_level"] == "master"


@pytest.mark.asyncio
async def test_submit_clarifications_updates_target_degree_metadata_and_gpa_ratio():
    initial_profile_json = {"full_name": "Test"}

    row = {
        "profile_version": 1,
    }
    service = ProfileService()
    service.profile_repo = _StubProfileRepo(row)
    service.normalized_repo = _StubNormalizedRepo(initial_profile_json)

    await service.submit_clarifications(
        "profile-1",
        [
            {"field": "target_degree_level", "value": "PhD"},
            {"field": "gpa", "value": "4.0/5.0"},
            {"field": "current_degree_level", "value": "master"},
        ],
    )

    assert service.profile_repo.updates["target_degree_level"] == "phd"
    assert service.profile_repo.updates["target_degree_source"] == "user_input"
    assert service.profile_repo.updates["target_degree_confidence"] == 1.0
    # For PhD targets, publications may still require clarification, but target-degree itself should be resolved.
    assert service.profile_repo.updates["target_degree_needs_clarification"] is False
    assert service.profile_repo.updates["gpa"] == 4.0
    assert service.profile_repo.updates["gpa_scale"] == 5.0


@pytest.mark.asyncio
async def test_get_clarifications_includes_react_decision_trace():
    initial_profile_json = {
        "full_name": "John Doe",
        "react_decision_trace": {"target_degree_level": {"decision": "clarify", "reason": "low_confidence"}},
    }
    row = {
        "profile_version": 1,
    }
    service = ProfileService()
    service.profile_repo = _StubProfileRepo(row)
    service.normalized_repo = _StubNormalizedRepo(initial_profile_json)

    result = await service.get_clarifications("profile-1")

    assert "react_decision_trace" in result
    assert result["react_decision_trace"]["target_degree_level"]["decision"] == "clarify"


@pytest.mark.asyncio
async def test_create_gap_job_blocked_when_clarification_pending():
    profile_json_with_queue = {
        "field": "target_degree_level",
        "clarification_queue": [{"field": "target_degree_level"}],
    }

    service = GapAnalysisService()
    service.profile_repo = _StubProfileRepo({"id": "profile-1"})
    service.normalized_repo = _StubNormalizedRepo(profile_json_with_queue)
    service.gap_job_repo = _StubGapJobRepo()

    job = await service.create_gap_job("profile-1")

    assert job["status"] == "blocked"
    assert "clarification" in (job["error_message"] or "").lower()


@pytest.mark.asyncio
async def test_process_gap_job_completes_when_ready():
    profile_json = {
        "full_name": "Test",
        "target_degree_level": "master",
    }

    service = GapAnalysisService()
    service.profile_repo = _StubProfileRepo({"target_degree_level": "master"})
    service.normalized_repo = _StubNormalizedRepo(profile_json)
    job_repo = _StubGapJobRepo()
    service.gap_job_repo = job_repo
    service.llm_service = _StubLLM()
    service.gap_repo = _StubGapRepo()

    await service.process_gap_job("job-1", "profile-1")

    assert job_repo.updated[0][1]["status"] == "running"
    assert job_repo.updated[-1][1]["status"] == "completed"
