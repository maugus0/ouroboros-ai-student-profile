"""Tests for profile service helpers and parse flow orchestration."""

import pytest

from app.models.llm_models import LLMExtractionResult
from app.services.profile_service import ProfileService
from tests.fake_repos import FakeDocumentRepository, FakeProfileRepository


@pytest.mark.asyncio
async def test_fake_profile_repo():
    """Verify the in-memory fake repo works for basic operations."""
    repo = FakeProfileRepository()
    pid = await repo.create_profile({"full_name": "John Doe", "email": "john@test.com"})
    assert pid is not None
    profile = await repo.get_profile_by_id(pid)
    assert profile["full_name"] == "John Doe"
    assert await repo.count_profiles() == 1


@pytest.mark.asyncio
async def test_fake_document_repo():

    repo = FakeDocumentRepository()
    did = await repo.create_document({"profile_id": "p1", "file_name": "cv.pdf"})
    assert did is not None
    docs = await repo.get_documents_by_profile("p1")
    assert len(docs) == 1


def test_build_normalized_skills_deduplicates_and_normalizes_aliases():
    profile_data = {
        "technical_skills": ["Python", "python3", "SQL", " sql "],
        "confidence_map": {"technical_skills": 0.86},
    }

    rows = ProfileService._build_normalized_skills("doc-1", profile_data)
    normalized = {row["normalized_skill"] for row in rows}
    raw_values = {row["raw_skill"] for row in rows}

    assert normalized == {"python", "sql"}
    assert len(rows) == 2
    assert raw_values.issubset({"Python", "python3", "SQL", "sql"})
    assert all(row["confidence_score"] == 0.86 for row in rows)


def test_build_education_entries_deduplicates_semantically_identical_rows():
    profile_data = {
        "education": [
            {
                "institution": "NUS",
                "degree": "BSc",
                "field_of_study": "Computer Science",
                "start_date": "2020",
                "end_date": "2024",
                "gpa": 3.8,
                "gpa_scale": 4.0,
                "achievements": ["Dean list"],
            },
            {
                "institution": "NUS",
                "degree": "BSc",
                "field_of_study": "Computer Science",
                "start_date": "2020",
                "end_date": "2024",
                "gpa": 3.8,
                "gpa_scale": 4.0,
                "achievements": ["Dean list"],
            },
        ],
    }

    rows = ProfileService._build_education_entries("doc-1", profile_data)

    assert len(rows) == 1
    assert rows[0]["entry_fingerprint"]


def test_build_experience_entries_deduplicates_semantically_identical_rows():
    profile_data = {
        "work_experience": [
            {
                "company": "Acme",
                "position": "Engineer",
                "start_date": "2024-01",
                "end_date": "2025-01",
                "description": "Backend work",
                "skills_used": ["Python"],
            },
            {
                "company": "Acme",
                "position": "Engineer",
                "start_date": "2024-01",
                "end_date": "2025-01",
                "description": "Backend work",
                "skills_used": ["Python"],
            },
        ],
        "research_experience": [],
    }

    rows = ProfileService._build_experience_entries("doc-1", profile_data)

    assert len(rows) == 1
    assert rows[0]["entry_fingerprint"]


@pytest.mark.asyncio
async def test_parse_and_create_profile_runs_auto_gap_analysis():
    service = ProfileService()

    class _StubParser:
        async def extract_text(self, _file_content_base64, _file_name):
            return {
                "text": "Student CV",
                "file_size_bytes": 123,
                "file_hash": "abc",
                "extracted_text_length": 10,
                "ocr_used": False,
                "extraction_method": "pdfplumber",
                "extraction_time_ms": 10,
            }

    class _StubLLMService:
        async def extract_profile(self, _document_text, _target_degree_hint=None):
            return LLMExtractionResult(
                profile_data={
                    "full_name": "Jane Doe",
                    "technical_skills": ["Python", "SQL"],
                    "education": [{"institution": "NUS", "degree": "BSc"}],
                    "work_experience": [{"company": "A", "position": "Engineer"}],
                    "research_experience": [],
                    "confidence_map": {"technical_skills": 0.9},
                    "evidence_map": {},
                    "target_degree_level": "master",
                    "current_degree_level": "bachelor",
                    "target_degree_confidence": 0.8,
                    "target_degree_source": "trajectory_inference",
                },
                provider="openai",
                model="gpt-test",
            )

    class _StubFieldRepo:
        async def create_field(self, _row):
            return "field-1"

    class _StubNormalizedRepo:
        def __init__(self):
            self.skills_rows = None
            self.education_rows = None
            self.experience_rows = None
            self.version_snapshots = []

        async def replace_extracted_skills(self, _profile_id, rows):
            self.skills_rows = rows

        async def replace_education_entries(self, _profile_id, rows):
            self.education_rows = rows

        async def replace_experience_entries(self, _profile_id, rows):
            self.experience_rows = rows

        async def create_profile_version_snapshot(self, profile_id, version_number, profile_json, change_reason):
            self.version_snapshots.append(
                {
                    "profile_id": profile_id,
                    "version_number": version_number,
                    "profile_json": profile_json,
                    "change_reason": change_reason,
                }
            )
            return "ver-1"

        async def get_latest_profile_version(self, _profile_id):
            if not self.version_snapshots:
                return None
            return self.version_snapshots[-1]

    class _StubGapService:
        async def analyze(self, _profile_id):
            return {"readiness_score": 0.7, "readiness_signals": []}

    service.profile_repo = FakeProfileRepository()
    service.document_repo = FakeDocumentRepository()
    service.field_repo = _StubFieldRepo()
    service.normalized_repo = _StubNormalizedRepo()
    service.parser = _StubParser()
    service.llm_service = _StubLLMService()
    service.gap_service = _StubGapService()

    result = await service.parse_and_create_profile(
        user_id="user-1",
        file_name="cv.pdf",
        file_content_base64="dGVzdA==",
        document_type="cv",
    )

    assert result["gap_analysis"]["readiness_score"] == 0.7
    assert result["profile_id"] is not None
    assert service.normalized_repo.skills_rows is not None
    assert len(service.normalized_repo.skills_rows) == 2
    assert service.normalized_repo.version_snapshots[0]["version_number"] == 1


@pytest.mark.asyncio
async def test_parse_and_create_profile_skips_auto_gap_analysis_when_disabled():
    service = ProfileService()

    class _StubParser:
        async def extract_text(self, _file_content_base64, _file_name):
            return {
                "text": "Student CV",
                "file_size_bytes": 123,
                "file_hash": "abc",
                "extracted_text_length": 10,
                "ocr_used": False,
                "extraction_method": "pdfplumber",
                "extraction_time_ms": 10,
            }

    class _StubLLMService:
        async def extract_profile(self, _document_text, _target_degree_hint=None):
            return LLMExtractionResult(
                profile_data={
                    "full_name": "Jane Doe",
                    "technical_skills": ["Python"],
                    "education": [{"institution": "NUS", "degree": "BSc"}],
                    "work_experience": [{"company": "A", "position": "Engineer"}],
                    "research_experience": [],
                    "target_degree_level": "master",
                    "current_degree_level": "bachelor",
                    "target_degree_confidence": 0.8,
                    "target_degree_source": "trajectory_inference",
                },
                provider="openai",
                model="gpt-test",
            )

    class _StubNormalizedRepo:
        async def replace_extracted_skills(self, _profile_id, _rows):
            return None

        async def replace_education_entries(self, _profile_id, _rows):
            return None

        async def replace_experience_entries(self, _profile_id, _rows):
            return None

        async def create_profile_version_snapshot(self, _profile_id, _version_number, _profile_json, _change_reason):
            return "ver-1"

    class _StubGapService:
        def __init__(self):
            self.called = False

        async def analyze(self, _profile_id):
            self.called = True
            return {"readiness_score": 0.7, "readiness_signals": []}

    gap_service = _StubGapService()
    service.profile_repo = FakeProfileRepository()
    service.document_repo = FakeDocumentRepository()
    service.normalized_repo = _StubNormalizedRepo()
    service.parser = _StubParser()
    service.llm_service = _StubLLMService()
    service.gap_service = gap_service

    result = await service.parse_and_create_profile(
        user_id="user-1",
        file_name="cv.pdf",
        file_content_base64="dGVzdA==",
        document_type="cv",
        run_gap_analysis=False,
    )

    assert result["gap_analysis"] is None
    assert gap_service.called is False


@pytest.mark.asyncio
async def test_update_profile_increments_profile_version():
    service = ProfileService()

    class _StubProfileRepo:
        def __init__(self):
            self.updated = None

        async def get_profile_by_id(self, _profile_id):
            return {"id": "p1", "profile_version": 1}

        async def update_profile(self, _profile_id, updates):
            self.updated = updates
            return 1

    class _StubNormalizedRepo:
        async def create_profile_version_snapshot(self, _profile_id, _version_number, _profile_json, _change_reason):
            return "ver-2"

        async def get_latest_profile_version(self, _profile_id):
            return {"profile_json": {}}

    service.profile_repo = _StubProfileRepo()
    service.normalized_repo = _StubNormalizedRepo()

    async def _stub_get_profile(_profile_id):
        return {"id": "p1", "profile_version": 2}

    service.get_profile = _stub_get_profile  # type: ignore[method-assign]

    result = await service.update_profile("p1", {"full_name": "New"})

    assert service.profile_repo.updated["profile_version"] == 2
    assert result["profile_version"] == 2


@pytest.mark.asyncio
async def test_update_profile_merges_updates_into_snapshot_and_recomputes_clarifications():
    service = ProfileService()

    class _StubProfileRepo:
        def __init__(self):
            self.updated = None

        async def get_profile_by_id(self, _profile_id):
            return {"id": "p1", "profile_version": 1}

        async def update_profile(self, _profile_id, updates):
            self.updated = updates
            return 1

    class _StubNormalizedRepo:
        def __init__(self):
            self.snapshot_payload = None

        async def create_profile_version_snapshot(self, profile_id, version_number, profile_json, change_reason):
            self.snapshot_payload = profile_json
            return "ver-2"

        async def get_latest_profile_version(self, _profile_id):
            return {
                "profile_json": {
                    "full_name": "Jane Doe",
                    "target_degree_level": "master",
                    "confidence_map": {"target_degree_level": 0.5},
                    "clarification_queue": [],
                }
            }

    normalized_repo = _StubNormalizedRepo()
    service.profile_repo = _StubProfileRepo()
    service.normalized_repo = normalized_repo

    async def _stub_get_profile(_profile_id):
        return {"id": "p1", "profile_version": 2}

    service.get_profile = _stub_get_profile  # type: ignore[method-assign]

    await service.update_profile("p1", {"current_degree_level": "master", "target_degree_level": "phd", "gpa": 3.95})

    assert service.profile_repo.updated["current_degree_level"] == "master"
    assert normalized_repo.snapshot_payload is not None
    assert normalized_repo.snapshot_payload["current_degree_level"] == "master"
    assert normalized_repo.snapshot_payload["target_degree_level"] == "phd"
    assert normalized_repo.snapshot_payload["gpa"] == 3.95
    assert normalized_repo.snapshot_payload["target_degree_source"] == "user_input"
    assert normalized_repo.snapshot_payload["target_degree_confidence"] == 1.0
    assert normalized_repo.snapshot_payload["confidence_map"]["current_degree_level"] == 1.0
    assert normalized_repo.snapshot_payload["confidence_map"]["target_degree_level"] == 1.0
    assert normalized_repo.snapshot_payload["confidence_map"]["gpa"] == 1.0

    queue_fields = {item["field"] for item in normalized_repo.snapshot_payload["clarification_queue"]}
    assert "publications" in queue_fields


@pytest.mark.asyncio
async def test_get_profile_status_prefers_latest_snapshot_values():
    service = ProfileService()

    class _StubProfileRepo:
        async def get_latest_profile_by_user_id(self, _user_id):
            return {
                "id": "p1",
                "full_name": "",
                "email": "stale@example.com",
                "current_degree_level": "unknown",
                "target_degree_level": "unknown",
                "gpa": None,
                "gpa_scale": None,
                "target_degree_needs_clarification": False,
                "updated_at": "2026-04-12T00:00:00",
            }

    class _StubNormalizedRepo:
        async def get_latest_profile_version(self, _profile_id):
            return {
                "profile_json": {
                    "full_name": "Jane Doe",
                    "email": "jane@example.com",
                    "current_degree_level": "bachelor",
                    "target_degree_level": "master",
                    "gpa": 3.8,
                    "gpa_scale": 4.0,
                    "intended_field_of_study": "computer science",
                    "target_study_country": "singapore",
                    "enrollment_timeline": "2027-fall",
                    "funding_source": "scholarship",
                    "clarification_queue": [],
                }
            }

    service.profile_repo = _StubProfileRepo()
    service.normalized_repo = _StubNormalizedRepo()

    result = await service.get_profile_status("user-1", intent="program_discovery")

    assert result["completed"] is True
    assert result["missing_fields"] == []
    assert result["updated_at"] == "2026-04-12T00:00:00"
    assert result["intent"] == "program_discovery"


@pytest.mark.asyncio
async def test_collect_from_chat_persists_extraction_trace_and_correction_metadata():
    service = ProfileService()

    class _StubProfileRepo:
        def __init__(self):
            self.updated = []

        async def get_latest_profile_by_user_id(self, _user_id):
            return {"id": "profile-1", "profile_version": 1}

        async def get_profile_by_id(self, _profile_id):
            return {"id": "profile-1", "profile_version": 1}

        async def update_profile(self, _profile_id, updates):
            self.updated.append(updates)
            return 1

    class _StubNormalizedRepo:
        def __init__(self):
            self.latest = {
                "profile_json": {
                    "clarification_queue": [],
                    "confidence_map": {},
                }
            }
            self.snapshots = []

        async def get_latest_profile_version(self, _profile_id):
            return self.latest

        async def create_profile_version_snapshot(self, profile_id, version_number, profile_json, change_reason):
            self.snapshots.append(
                {
                    "profile_id": profile_id,
                    "version_number": version_number,
                    "profile_json": profile_json,
                    "change_reason": change_reason,
                }
            )
            self.latest = {"profile_json": profile_json}
            return "ver-2"

    profile_repo = _StubProfileRepo()
    normalized_repo = _StubNormalizedRepo()
    service.profile_repo = profile_repo
    service.normalized_repo = normalized_repo

    async def _stub_submit_clarifications(_profile_id, _answers):
        return {
            "applied_fields": ["target_study_country"],
            "clarification_queue": [],
        }

    async def _stub_get_profile_status(_user_id, intent=None):
        return {
            "user_id": "user-1",
            "completed": False,
            "missing_fields": ["gpa"],
            "optional_missing_fields": [],
            "updated_at": None,
            "intent": intent,
        }

    service.submit_clarifications = _stub_submit_clarifications  # type: ignore[method-assign]
    service.get_profile_status = _stub_get_profile_status  # type: ignore[method-assign]

    result = await service.collect_from_chat(
        user_id="user-1",
        fields={"target_study_country": "Australia"},
        extractions={
            "target_study_country": {
                "value": "Australia",
                "confidence": 0.92,
                "reason": "country_correction",
                "source_span": "Not Canada, Australia instead",
                "is_correction": True,
            }
        },
        extraction_telemetry={
            "candidate_count": 1,
            "persisted_count": 1,
            "correction_count": 1,
            "clarification_count": 0,
            "hit_rate": 1.0,
            "correction_rate": 1.0,
            "clarification_rate": 0.0,
        },
        correction_fields=["target_study_country"],
        pending_clarification_fields=["gpa"],
        chat_id="chat-1",
        message_id="msg-1",
    )

    assert result["applied_fields"] == ["target_study_country"]
    assert result["pending_clarification_fields"] == ["gpa"]
    assert result["correction_fields"] == ["target_study_country"]
    assert normalized_repo.snapshots[-1]["change_reason"] == "chat_extraction_trace_update"
    trace = normalized_repo.snapshots[-1]["profile_json"]["chat_extraction_trace"]
    assert trace[-1]["field"] == "target_study_country"
    assert trace[-1]["is_correction"] is True
    assert trace[-1]["persisted"] is True
    telemetry = normalized_repo.snapshots[-1]["profile_json"]["extraction_telemetry"]
    assert telemetry["turn_count"] == 1
    assert telemetry["candidate_count_total"] == 1
    assert telemetry["persisted_count_total"] == 1
    assert telemetry["correction_count_total"] == 1
    assert telemetry["clarification_count_total"] == 0
    assert telemetry["hit_rate"] == 1.0
    assert telemetry["correction_rate"] == 1.0
    assert telemetry["clarification_rate"] == 0.0


@pytest.mark.asyncio
async def test_collect_from_chat_preserves_ambiguous_field_candidates_until_clarified():
    service = ProfileService()

    class _StubProfileRepo:
        def __init__(self):
            self.profile = None
            self.updated = []

        async def create_profile(self, record):
            self.profile = {"id": "profile-1", **record}
            return "profile-1"

        async def get_latest_profile_by_user_id(self, _user_id):
            return self.profile

        async def get_profile_by_id(self, _profile_id):
            return self.profile

        async def update_profile(self, _profile_id, updates):
            self.updated.append(updates)
            if self.profile is None:
                self.profile = {"id": _profile_id}
            self.profile.update(updates)
            return 1

    class _StubNormalizedRepo:
        def __init__(self):
            self.latest = {"profile_json": {"clarification_queue": [], "confidence_map": {}}}
            self.snapshots = []

        async def get_latest_profile_version(self, _profile_id):
            return self.latest

        async def create_profile_version_snapshot(self, profile_id, version_number, profile_json, change_reason):
            payload = {
                "profile_id": profile_id,
                "version_number": version_number,
                "profile_json": profile_json,
                "change_reason": change_reason,
            }
            self.snapshots.append(payload)
            self.latest = {"profile_json": profile_json}
            return "ver-2"

    service.profile_repo = _StubProfileRepo()
    service.normalized_repo = _StubNormalizedRepo()

    result = await service.collect_from_chat(
        user_id="user-1",
        fields={},
        extractions={
            "intended_field_of_study": {
                "value": ["Computer Science", "Data Science"],
                "confidence": 0.71,
                "reason": "ambiguous_programs",
                "source_span": "computer science or data science",
            }
        },
        extraction_telemetry={
            "candidate_count": 1,
            "persisted_count": 0,
            "correction_count": 0,
            "clarification_count": 1,
            "hit_rate": 0.0,
            "correction_rate": 0.0,
            "clarification_rate": 1.0,
        },
        chat_id="chat-1",
        message_id="msg-1",
    )

    assert result["applied_fields"] == []
    assert set(result["pending_clarification_fields"]) == {"intended_field_of_study"}
    trace = service.normalized_repo.snapshots[-1]["profile_json"]["chat_extraction_trace"]
    assert trace[-1]["field"] == "intended_field_of_study"
    assert trace[-1]["persisted"] is False
    assert trace[-1]["value"] == ["Computer Science", "Data Science"]
    pending_candidates = service.normalized_repo.snapshots[-1]["profile_json"]["pending_field_candidates"]
    assert pending_candidates["intended_field_of_study"] == ["Computer Science", "Data Science"]

    await service.submit_clarifications(
        "profile-1",
        [{"field": "intended_field_of_study", "value": "Computer Science"}],
    )

    assert "pending_field_candidates" not in service.normalized_repo.latest["profile_json"]


@pytest.mark.asyncio
async def test_collect_from_chat_fields_only_without_extraction_payload_returns_without_unbound_errors():
    service = ProfileService()

    class _StubProfileRepo:
        async def get_latest_profile_by_user_id(self, _user_id):
            return {"id": "profile-1", "profile_version": 1}

        async def get_profile_by_id(self, _profile_id):
            return {"id": "profile-1", "profile_version": 1}

        async def update_profile(self, _profile_id, _updates):
            return 1

    class _StubNormalizedRepo:
        async def get_latest_profile_version(self, _profile_id):
            return {"profile_json": {"clarification_queue": [], "confidence_map": {}}}

        async def create_profile_version_snapshot(self, _profile_id, _version_number, _profile_json, _change_reason):
            return "ver-2"

    service.profile_repo = _StubProfileRepo()
    service.normalized_repo = _StubNormalizedRepo()

    async def _stub_submit_clarifications(_profile_id, _answers):
        return {
            "applied_fields": ["target_study_country"],
            "clarification_queue": [],
        }

    async def _stub_get_profile_status(_user_id, intent=None):
        return {
            "user_id": "user-1",
            "completed": False,
            "missing_fields": ["gpa"],
            "optional_missing_fields": [],
            "updated_at": None,
            "intent": intent,
        }

    service.submit_clarifications = _stub_submit_clarifications  # type: ignore[method-assign]
    service.get_profile_status = _stub_get_profile_status  # type: ignore[method-assign]

    result = await service.collect_from_chat(
        user_id="user-1",
        fields={"target_study_country": "Australia"},
        extractions={},
        extraction_telemetry={},
        pending_clarification_fields=[],
        correction_fields=[],
        chat_id="chat-1",
        message_id="msg-1",
    )

    assert result["applied_fields"] == ["target_study_country"]
    assert result["pending_clarification_fields"] == []
    assert result["correction_fields"] == []


@pytest.mark.asyncio
async def test_get_profile_status_scans_nested_json_properties_for_required_fields():
    service = ProfileService()

    class _StubProfileRepo:
        async def get_latest_profile_by_user_id(self, _user_id):
            return {
                "id": "p1",
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "current_degree_level": "bachelor",
                "target_degree_level": "master",
                "gpa": 3.8,
                "gpa_scale": 4.0,
                "target_degree_needs_clarification": False,
                "updated_at": "2026-04-12T00:00:00",
            }

    class _StubNormalizedRepo:
        async def get_latest_profile_version(self, _profile_id):
            return {
                "profile_json": {
                    "academic_preferences": {"field_of_study": "computer science"},
                    "application_preferences": {"target_country": "singapore"},
                    "preferences": {"target_intake": "2027-fall"},
                    "financial_profile": {"funding_source": "family"},
                    "clarification_queue": [],
                }
            }

    service.profile_repo = _StubProfileRepo()
    service.normalized_repo = _StubNormalizedRepo()

    result = await service.get_profile_status("user-1", intent="scholarship_search")

    assert result["completed"] is True
    assert result["missing_fields"] == []
    assert result["intent"] == "scholarship_search"


@pytest.mark.asyncio
async def test_get_profile_status_treats_optional_fields_as_non_blocking():
    service = ProfileService()

    class _StubProfileRepo:
        async def get_latest_profile_by_user_id(self, _user_id):
            return {
                "id": "p1",
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "current_degree_level": "bachelor",
                "target_degree_level": "master",
                "gpa": 3.8,
                "gpa_scale": 4.0,
                "target_degree_needs_clarification": False,
                "updated_at": "2026-04-12T00:00:00",
            }

    class _StubNormalizedRepo:
        async def get_latest_profile_version(self, _profile_id):
            return {
                "profile_json": {
                    "intended_field_of_study": "computer science",
                    "clarification_queue": [],
                }
            }

    service.profile_repo = _StubProfileRepo()
    service.normalized_repo = _StubNormalizedRepo()

    result = await service.get_profile_status("user-1", intent="application_planning")

    assert result["completed"] is True
    assert result["missing_fields"] == []
    assert result["optional_missing_fields"] == ["target_study_country", "enrollment_timeline", "funding_source"]
    assert result["intent"] == "application_planning"


@pytest.mark.asyncio
async def test_get_profile_removes_duplicated_keys_from_profile_json():
    service = ProfileService()

    class _StubProfileRepo:
        async def get_profile_by_id(self, _profile_id):
            return {
                "id": "p1",
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "current_degree_level": "master",
            }

    class _StubNormalizedRepo:
        async def get_latest_profile_version(self, _profile_id):
            return {
                "profile_json": {
                    "full_name": "Jane Doe",
                    "email": "jane@example.com",
                    "current_degree_level": "master",
                    "technical_skills": ["Python"],
                    "education": [{"institution": "NUS", "degree": "MTech"}],
                }
            }

    service.profile_repo = _StubProfileRepo()
    service.normalized_repo = _StubNormalizedRepo()

    result = await service.get_profile("p1")

    assert result["full_name"] == "Jane Doe"
    assert "full_name" not in result["profile_json"]
    assert "email" not in result["profile_json"]
    assert "current_degree_level" not in result["profile_json"]
    assert result["profile_json"]["technical_skills"] == ["Python"]
    assert len(result["profile_json"]["education"]) == 1
