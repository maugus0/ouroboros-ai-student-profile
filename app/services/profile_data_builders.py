"""Helpers for transforming extracted profile JSON into normalized storage rows."""

import hashlib
import json
import re
from typing import Any


def build_profile_fields(
    profile_id: str, source_document_id: str, profile_data: dict[str, Any]
) -> list[dict[str, Any]]:
    """Flatten extracted profile JSON into profile_fields records."""
    field_categories = {
        "full_name": "personal",
        "email": "personal",
        "phone": "personal",
        "nationality": "personal",
        "date_of_birth": "personal",
        "target_degree_level": "academic",
        "current_degree_level": "academic",
        "target_degree_confidence": "academic",
        "target_degree_source": "academic",
        "target_degree_needs_clarification": "academic",
        "target_degree_reasoning": "academic",
        "gpa_highest": "academic",
        "gpa_scale": "academic",
        "publications": "research",
        "languages": "skills",
        "certifications": "skills",
        "research_interests": "research",
    }

    confidence_map = profile_data.get("confidence_map") or {}
    evidence_map = profile_data.get("evidence_map") or {}

    rows: list[dict[str, Any]] = []
    for field_name, category in field_categories.items():
        value = profile_data.get(field_name)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue

        raw_confidence = confidence_map.get(field_name)
        confidence_score = None
        if raw_confidence is not None:
            try:
                parsed = float(raw_confidence)
                if 0.0 <= parsed <= 1.0:
                    confidence_score = parsed
            except (TypeError, ValueError):
                confidence_score = None

        evidence = evidence_map.get(field_name)
        evidence_snippet = None
        if isinstance(evidence, str) and evidence.strip():
            evidence_snippet = evidence.strip()

        rows.append(
            {
                "profile_id": profile_id,
                "field_category": category,
                "field_name": field_name,
                "field_value": value,
                "confidence_score": confidence_score,
                "evidence_snippet": evidence_snippet,
                "source_document_id": source_document_id,
            }
        )

    return rows


def normalize_skill_name(skill: str) -> str:
    """Normalize skill labels for consistent indexing."""
    normalized = re.sub(r"\s+", " ", skill.strip().lower())
    normalized = normalized.replace("python3", "python").replace("py3", "python")
    return normalized


def build_normalized_skills(source_document_id: str, profile_data: dict[str, Any]) -> list[dict[str, Any]]:
    skills = profile_data.get("technical_skills") if isinstance(profile_data.get("technical_skills"), list) else []
    confidence_map = profile_data.get("confidence_map") if isinstance(profile_data.get("confidence_map"), dict) else {}
    confidence = confidence_map.get("technical_skills")
    confidence_score = None
    if confidence is not None:
        try:
            parsed = float(confidence)
            if 0.0 <= parsed <= 1.0:
                confidence_score = parsed
        except (TypeError, ValueError):
            confidence_score = None

    dedup: dict[str, str] = {}
    for item in skills:
        raw_skill = str(item).strip()
        if not raw_skill:
            continue
        normalized = normalize_skill_name(raw_skill)
        if not normalized:
            continue
        dedup.setdefault(normalized, raw_skill)

    rows: list[dict[str, Any]] = []
    for normalized, raw in dedup.items():
        rows.append(
            {
                "raw_skill": raw,
                "normalized_skill": normalized,
                "confidence_score": confidence_score,
                "source_document_id": source_document_id,
            }
        )
    return rows


def build_education_entries(source_document_id: str, profile_data: dict[str, Any]) -> list[dict[str, Any]]:
    education = profile_data.get("education") if isinstance(profile_data.get("education"), list) else []
    confidence_map = profile_data.get("confidence_map") if isinstance(profile_data.get("confidence_map"), dict) else {}
    evidence_map = profile_data.get("evidence_map") if isinstance(profile_data.get("evidence_map"), dict) else {}
    confidence_score = confidence_map.get("education")
    parsed_confidence = None
    try:
        if confidence_score is not None:
            score = float(confidence_score)
            if 0.0 <= score <= 1.0:
                parsed_confidence = score
    except (TypeError, ValueError):
        parsed_confidence = None

    rows: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()
    for index, item in enumerate(education):
        if not isinstance(item, dict):
            continue
        institution = str(item.get("institution") or "").strip()
        degree = str(item.get("degree") or "").strip()
        if not institution or not degree:
            continue
        row = {
            "institution": institution,
            "degree": degree,
            "field_of_study": item.get("field_of_study"),
            "start_date": item.get("start_date"),
            "end_date": item.get("end_date"),
            "gpa": item.get("gpa"),
            "gpa_scale": item.get("gpa_scale"),
            "achievements": item.get("achievements") if isinstance(item.get("achievements"), list) else [],
            "evidence_snippet": evidence_map.get("education"),
            "confidence_score": parsed_confidence,
            "source_document_id": source_document_id,
            "sort_index": index,
        }
        fingerprint = entry_fingerprint(
            row,
            keys=[
                "institution",
                "degree",
                "field_of_study",
                "start_date",
                "end_date",
                "gpa",
                "gpa_scale",
                "achievements",
            ],
        )
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        row["entry_fingerprint"] = fingerprint
        rows.append(row)
    return rows


def build_experience_entries(source_document_id: str, profile_data: dict[str, Any]) -> list[dict[str, Any]]:
    confidence_map = profile_data.get("confidence_map") if isinstance(profile_data.get("confidence_map"), dict) else {}
    evidence_map = profile_data.get("evidence_map") if isinstance(profile_data.get("evidence_map"), dict) else {}

    def _coerce_confidence(value: Any) -> float | None:
        try:
            if value is None:
                return None
            parsed = float(value)
            if 0.0 <= parsed <= 1.0:
                return parsed
        except (TypeError, ValueError):
            return None
        return None

    rows: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()
    work_confidence = _coerce_confidence(confidence_map.get("work_experience"))
    research_confidence = _coerce_confidence(confidence_map.get("research_experience"))

    work_experience = (
        profile_data.get("work_experience") if isinstance(profile_data.get("work_experience"), list) else []
    )
    for index, item in enumerate(work_experience):
        if not isinstance(item, dict):
            continue
        company = str(item.get("company") or "").strip()
        position = str(item.get("position") or "").strip()
        if not company or not position:
            continue
        row = {
            "experience_type": "work",
            "organization": company,
            "title": position,
            "role": None,
            "start_date": item.get("start_date"),
            "end_date": item.get("end_date"),
            "description": item.get("description"),
            "skills_used": item.get("skills_used") if isinstance(item.get("skills_used"), list) else [],
            "publication_venue": None,
            "evidence_snippet": evidence_map.get("work_experience"),
            "confidence_score": work_confidence,
            "source_document_id": source_document_id,
            "sort_index": index,
        }
        fingerprint = entry_fingerprint(
            row,
            keys=[
                "experience_type",
                "organization",
                "title",
                "start_date",
                "end_date",
                "description",
                "skills_used",
            ],
        )
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        row["entry_fingerprint"] = fingerprint
        rows.append(row)

    research_experience = (
        profile_data.get("research_experience") if isinstance(profile_data.get("research_experience"), list) else []
    )
    for index, item in enumerate(research_experience):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        row = {
            "experience_type": "research",
            "organization": None,
            "title": title,
            "role": item.get("role"),
            "start_date": item.get("date"),
            "end_date": None,
            "description": item.get("description"),
            "skills_used": [],
            "publication_venue": item.get("publication_venue"),
            "evidence_snippet": evidence_map.get("research_experience"),
            "confidence_score": research_confidence,
            "source_document_id": source_document_id,
            "sort_index": index,
        }
        fingerprint = entry_fingerprint(
            row,
            keys=[
                "experience_type",
                "title",
                "role",
                "start_date",
                "description",
                "publication_venue",
            ],
        )
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        row["entry_fingerprint"] = fingerprint
        rows.append(row)

    return rows


def entry_fingerprint(payload: dict[str, Any], keys: list[str]) -> str:
    """Return stable SHA-256 fingerprint for dedupe-sensitive fields."""
    normalized = {key: payload.get(key) for key in keys}
    canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
