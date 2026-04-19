"""Integration tests for all repository classes against real MySQL."""

from __future__ import annotations

import asyncio
from datetime import date

import mysql.connector
import pytest
import pytest_asyncio

from app.config import settings
from app.repositories.db_pool import DatabasePoolConfig, close_pool, create_pool
from app.repositories.mysql_document_repo import DocumentRepository
from app.repositories.mysql_field_repo import FieldRepository
from app.repositories.mysql_gap_analysis_repo import GapAnalysisRepository
from app.repositories.mysql_gap_job_repo import GapAnalysisJobRepository
from app.repositories.mysql_llm_log_repo import LLMCallLogRepository
from app.repositories.mysql_profile_normalized_repo import ProfileNormalizedRepository
from app.repositories.mysql_profile_repo import ProfileRepository


@pytest_asyncio.fixture(autouse=True)
async def repo_pool():
    """Initialise aiomysql pool per test to keep loop ownership consistent."""
    await close_pool()
    await create_pool(
        DatabasePoolConfig(
            host=settings.get_db_host(),
            port=settings.get_db_port(),
            db=settings.get_db_name(),
            user=settings.get_db_user(),
            password=settings.get_db_password(),
            pool_size=5,
        )
    )
    yield
    await close_pool()


def _fetch_one(query: str, params: tuple):
    conn = mysql.connector.connect(
        host=settings.get_db_host(),
        port=settings.get_db_port(),
        database=settings.get_db_name(),
        user=settings.get_db_user(),
        password=settings.get_db_password(),
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params)
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


@pytest.mark.asyncio
async def test_profile_repository_crud(cleanup_integration_db):
    repo = ProfileRepository()

    profile_id = await repo.create_profile(
        {
            "full_name": "Repo User",
            "email": "repo.user@example.com",
            "current_degree_level": "bachelor",
            "target_degree_level": "master",
            "gpa": 3.75,
            "gpa_scale": 4.0,
        }
    )

    created = await repo.get_profile_by_id(profile_id)
    assert created is not None
    assert created["email"] == "repo.user@example.com"

    by_email = await repo.get_profile_by_email("repo.user@example.com")
    assert by_email is not None
    assert by_email["id"] == profile_id

    updated_rows = await repo.update_profile(profile_id, {"full_name": "Repo User Updated", "gpa": 3.9})
    assert updated_rows == 1

    listed = await repo.list_profiles(limit=10, offset=0)
    assert any(item["id"] == profile_id for item in listed)

    total = await repo.count_profiles()
    assert total >= 1

    deleted_rows = await repo.delete_profile(profile_id)
    assert deleted_rows == 1
    assert await repo.get_profile_by_id(profile_id) is None


@pytest.mark.asyncio
async def test_document_repository_crud(cleanup_integration_db):
    profile_repo = ProfileRepository()
    doc_repo = DocumentRepository()

    profile_id = await profile_repo.create_profile(
        {
            "full_name": "Doc Owner",
            "email": "doc.owner@example.com",
            "current_degree_level": "bachelor",
            "target_degree_level": "master",
        }
    )

    document_id = await doc_repo.create_document(
        {
            "profile_id": profile_id,
            "document_type": "cv",
            "file_name": "owner_cv.pdf",
            "file_extension": ".pdf",
            "file_size_bytes": 1024,
            "mime_type": "application/pdf",
            "file_hash": "abc123",
            "extracted_text_length": 120,
            "ocr_used": False,
            "extraction_method": "digital_pdf",
            "extraction_time_ms": 12,
        }
    )

    one = await doc_repo.get_document_by_id(document_id)
    assert one is not None
    assert one["id"] == document_id

    many = await doc_repo.get_documents_by_profile(profile_id)
    assert len(many) == 1
    assert many[0]["id"] == document_id

    deleted_rows = await doc_repo.delete_document(document_id)
    assert deleted_rows == 1
    assert await doc_repo.get_document_by_id(document_id) is None


@pytest.mark.asyncio
async def test_field_repository_crud(cleanup_integration_db):
    profile_repo = ProfileRepository()
    field_repo = FieldRepository()

    profile_id = await profile_repo.create_profile(
        {
            "full_name": "Field Owner",
            "email": "field.owner@example.com",
            "current_degree_level": "bachelor",
            "target_degree_level": "master",
        }
    )

    field_id = await field_repo.create_field(
        {
            "profile_id": profile_id,
            "field_category": "education",
            "field_name": "institution",
            "field_value": {"name": "NUS"},
            "confidence_score": 0.9,
            "evidence_snippet": "National University of Singapore",
        }
    )

    all_fields = await field_repo.get_fields_by_profile(profile_id)
    assert len(all_fields) == 1
    assert all_fields[0]["id"] == field_id

    category_fields = await field_repo.get_fields_by_profile(profile_id, "education")
    assert len(category_fields) == 1

    updated_rows = await field_repo.update_field(field_id, {"field_value": {"name": "NUS Updated"}})
    assert updated_rows == 1

    updated = _fetch_one("SELECT field_value FROM profile_fields WHERE id = %s", (field_id,))
    assert updated is not None
    assert "NUS Updated" in str(updated["field_value"])

    deleted_rows = await field_repo.delete_fields_by_profile(profile_id)
    assert deleted_rows == 1
    assert len(await field_repo.get_fields_by_profile(profile_id)) == 0


@pytest.mark.asyncio
async def test_gap_analysis_repository_latest(cleanup_integration_db):
    profile_repo = ProfileRepository()
    repo = GapAnalysisRepository()

    profile_id = await profile_repo.create_profile(
        {
            "full_name": "Gap Owner",
            "email": "gap.owner@example.com",
            "current_degree_level": "bachelor",
            "target_degree_level": "master",
        }
    )

    first_id = await repo.create_analysis(
        {
            "profile_id": profile_id,
            "target_degree_level": "master",
            "readiness_score": 0.61,
            "gaps_identified": [{"category": "research", "status": "missing"}],
            "recommendations": [{"action": "add publication"}],
            "baseline_template": "template-a",
        }
    )

    await asyncio.sleep(0.01)

    second_id = await repo.create_analysis(
        {
            "profile_id": profile_id,
            "target_degree_level": "master",
            "readiness_score": 0.75,
            "gaps_identified": [{"category": "project", "status": "partial"}],
            "recommendations": [{"action": "improve projects"}],
            "baseline_template": "template-b",
        }
    )

    latest = await repo.get_latest_by_profile(profile_id)
    assert latest is not None
    assert latest["id"] in {first_id, second_id}
    assert latest["profile_id"] == profile_id
    assert float(latest["readiness_score"]) in {0.61, 0.75}


@pytest.mark.asyncio
async def test_gap_analysis_job_repository_crud(cleanup_integration_db):
    profile_repo = ProfileRepository()
    repo = GapAnalysisJobRepository()

    profile_id = await profile_repo.create_profile(
        {
            "full_name": "Job Owner",
            "email": "job.owner@example.com",
            "current_degree_level": "bachelor",
            "target_degree_level": "master",
        }
    )

    job_id = await repo.create_job({"profile_id": profile_id})

    job = await repo.get_job(job_id)
    assert job is not None
    assert job["status"] == "queued"

    updated_rows = await repo.update_job(
        job_id,
        {
            "status": "completed",
            "result_json": {"readiness_score": 0.81},
            "error_message": None,
        },
    )
    assert updated_rows == 1

    updated = await repo.get_job(job_id)
    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["result_json"]["readiness_score"] == 0.81


@pytest.mark.asyncio
async def test_profile_normalized_repository_methods(cleanup_integration_db):
    profile_repo = ProfileRepository()
    repo = ProfileNormalizedRepository()

    profile_id = await profile_repo.create_profile(
        {
            "full_name": "Normalized Owner",
            "email": "normalized.owner@example.com",
            "current_degree_level": "bachelor",
            "target_degree_level": "master",
        }
    )

    await repo.replace_extracted_skills(
        profile_id,
        [
            {"raw_skill": "Python", "normalized_skill": "python", "confidence_score": 0.91},
            {"raw_skill": "SQL", "normalized_skill": "sql", "confidence_score": 0.88},
        ],
    )
    skills = await repo.get_skills_by_profile(profile_id)
    assert [row["normalized_skill"] for row in skills] == ["python", "sql"]

    await repo.replace_education_entries(
        profile_id,
        [
            {
                "institution": "NUS",
                "degree": "BSc",
                "field_of_study": "Computer Science",
                "start_date": date(2020, 1, 1),
                "end_date": date(2024, 1, 1),
                "gpa": 3.8,
                "gpa_scale": 4.0,
                "achievements": ["Dean list"],
                "sort_index": 0,
            }
        ],
    )

    edu_count = _fetch_one("SELECT COUNT(*) AS total FROM education_entries WHERE profile_id = %s", (profile_id,))
    assert edu_count is not None
    assert edu_count["total"] == 1

    await repo.replace_experience_entries(
        profile_id,
        [
            {
                "experience_type": "research",
                "organization": "Ouroboros",
                "title": "AI Agent",
                "role": "Engineer",
                "description": "Built an AI pipeline",
                "skills_used": ["python", "sql"],
                "sort_index": 0,
            }
        ],
    )

    exp_count = _fetch_one("SELECT COUNT(*) AS total FROM experience_entries WHERE profile_id = %s", (profile_id,))
    assert exp_count is not None
    assert exp_count["total"] == 1

    version_id = await repo.create_profile_version_snapshot(
        profile_id=profile_id,
        version_number=1,
        profile_json={"full_name": "Normalized Owner"},
        change_reason="initial",
    )
    assert version_id

    latest = await repo.get_latest_profile_version(profile_id)
    assert latest is not None
    assert latest["version_number"] == 1
    assert latest["profile_json"]["full_name"] == "Normalized Owner"


@pytest.mark.asyncio
async def test_llm_call_log_repository_create(cleanup_integration_db):
    profile_repo = ProfileRepository()
    repo = LLMCallLogRepository()

    profile_id = await profile_repo.create_profile(
        {
            "full_name": "Log Owner",
            "email": "log.owner@example.com",
            "current_degree_level": "bachelor",
            "target_degree_level": "master",
        }
    )

    log_id = await repo.create_log(
        {
            "profile_id": profile_id,
            "operation": "extract_profile",
            "llm_provider": "openai",
            "model_name": "gpt-4o-mini",
            "input_tokens": 100,
            "output_tokens": 200,
            "total_cost_usd": 0.002,
            "latency_ms": 180,
            "success": True,
            "retry_count": 0,
            "trace_id": "trace-1",
            "prompt_template_version": "profile_extraction_v2",
        }
    )

    row = _fetch_one("SELECT * FROM llm_call_logs WHERE id = %s", (log_id,))
    assert row is not None
    assert row["operation"] == "extract_profile"
    assert row["llm_provider"] == "openai"
