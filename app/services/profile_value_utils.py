"""Utility helpers for profile value normalization and coercion."""

import re
from datetime import date, datetime
from typing import Any, Optional


def normalize_field_name(field: Any) -> str:
    if field is None:
        return ""

    text = str(field).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "dob": "date_of_birth",
        "birth_date": "date_of_birth",
        "target_degree": "target_degree_level",
        "current_degree": "current_degree_level",
        "gpa_highest": "gpa",
        "highest_gpa": "gpa",
    }
    return aliases.get(text, text)


def parse_gpa_value(value: Any) -> tuple[Optional[float], Optional[float]]:
    """Parse GPA values from scalar or ratio text (e.g., '4.0/5.0')."""
    if value is None:
        return None, None

    if isinstance(value, (int, float)):
        return float(value), None

    text = str(value).strip()
    if not text:
        return None, None

    ratio_match = re.match(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$", text)
    if ratio_match:
        return float(ratio_match.group(1)), float(ratio_match.group(2))

    try:
        return float(text), None
    except ValueError:
        return None, None


def normalize_degree_level_value(field: str, value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if not text:
        return None

    if "phd" in text or "doctor" in text:
        return "phd"
    if "master" in text:
        return "master"
    if "bachelor" in text or re.search(r"\bbs\b|\bba\b|\bbsc\b", text):
        return "bachelor"
    if field == "current_degree_level" and ("high school" in text or "high_school" in text or text == "highschool"):
        return "high_school"
    if text == "unknown":
        return "unknown"
    return None


def parse_date_text(value: str) -> Optional[date]:
    text = value.strip()
    if not text:
        return None

    formats = (
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d %Y",
        "%B %d %Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def coerce_top_level_value(field: str, value: Any) -> Any:
    """Convert clarification value for strict DB columns; return None to skip DB write."""
    if value is None:
        return None

    if field == "date_of_birth":
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            return parse_date_text(value)
        return None

    if field in {"gpa", "gpa_highest", "gpa_scale"}:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    if field in {"current_degree_level", "target_degree_level"}:
        return normalize_degree_level_value(field, value)

    return value
