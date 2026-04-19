"""Tests for profile_fields generation in parse pipeline."""

from app.services.profile_service import ProfileService


def test_build_profile_fields_generates_rows_for_meaningful_values():
    profile_data = {
        "full_name": "John Doe",
        "email": "john.doe@example.com",
        "target_degree_level": "master",
        "technical_skills": ["Python", "FastAPI"],
        "education": [{"institution": "UGM", "degree": "CS"}],
        "research_interests": [],
        "gpa": 3.38,
        "confidence_map": {"full_name": 1.0, "email": 1.0, "gpa": 0.9},
        "evidence_map": {"full_name": "Header", "email": "Header", "gpa": "Education section"},
    }

    rows = ProfileService._build_profile_fields("profile-1", "doc-1", profile_data)

    field_names = {row["field_name"] for row in rows}
    assert "full_name" in field_names
    assert "email" in field_names
    assert "gpa" in field_names
    assert "research_interests" not in field_names  # empty list should be skipped
    assert "technical_skills" not in field_names
    assert "education" not in field_names

    full_name_row = next(row for row in rows if row["field_name"] == "full_name")
    assert full_name_row["field_category"] == "personal"
    assert full_name_row["confidence_score"] == 1.0
    assert full_name_row["evidence_snippet"] == "Header"
    assert full_name_row["source_document_id"] == "doc-1"


def test_build_profile_fields_skips_empty_values():
    profile_data = {
        "full_name": "",
        "email": None,
        "technical_skills": [],
        "education": [],
        "target_degree_level": "unknown",
        "confidence_map": {},
        "evidence_map": {},
    }

    rows = ProfileService._build_profile_fields("profile-2", "doc-2", profile_data)
    assert len(rows) == 1
    assert rows[0]["field_name"] == "target_degree_level"
