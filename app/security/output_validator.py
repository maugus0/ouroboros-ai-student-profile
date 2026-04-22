"""Validate LLM outputs for quality, safety, and data integrity in student profiles."""

import hashlib
import json
import re
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def _content_metadata(text: str) -> dict[str, Any]:
    """Return non-sensitive content metadata for logging."""
    return {
        "content_length": len(text),
        "content_hash": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
    }


# Hallucination indicators: suspicious claims unlikely in student data.
HALLUCINATION_INDICATORS = [
    "unknown university",
    "fake degree",
    "not a real field",
    "placeholder",
    "example",
    "test",
    "[redacted",
    "[hidden",
    "to be determined",
    "tbd",
    "n/a",
]

# Word-boundary indicators of incomplete or vague extraction.
INCOMPLETE_EXTRACTION_REGEXES = [
    re.compile(r"\bvague\b", re.IGNORECASE),
    re.compile(r"\bunclear\b", re.IGNORECASE),
    re.compile(r"\bunspecified\b", re.IGNORECASE),
    re.compile(r"\bunknown\b.*degree\b", re.IGNORECASE),
    re.compile(r"\bmissing\b.*information\b", re.IGNORECASE),
]

PROMPT_LEAKAGE_PATTERNS = [
    r"\bas an ai\b",
    r"\bi cannot\b",
    r"\bi don't have access\b",
    r"\bi'm unable to\b",
    r"\buser_data section\b",
    r"\bsystem instructions\b",
    r"===== ",
    r"<\|.*?\|>",
    r"\[INST\]",
    r"<\|im_start\|>",
    r"treat as data only",
    r"STUDENT_CONTEXT",
    r"PROFILE_EXTRACTION",
]

# Patterns that suggest the model echoed jailbreak / instruction text.
OUTPUT_INJECTION_PATTERNS = [
    r"ignore (all |previous )?instructions",
    r"disregard (all |previous )?instructions",
    r"you are now (a |an )?",
    r"new task:",
    r"developer mode",
    r"jailbreak",
    r"<\|assistant\|>",
    r"<\|system\|>",
]


def _relevance_strings(target_program: dict[str, Any], program_id: str | None) -> list[str]:
    """Collect distinctive substrings for profile validation (degree, university, field)."""
    keys = (
        "target_degree",
        "target_degree_level",
        "university_name",
        "university",
        "field_of_study",
        "program_name",
    )
    seen: set[str] = set()
    out: list[str] = []
    for key in keys:
        raw = str(target_program.get(key) or "").strip()
        if len(raw) < 2:
            continue
        if len(raw) == 2 and not raw.isalpha():
            continue
        low = raw.lower()
        if low not in seen:
            seen.add(low)
            out.append(low)
    pid = (program_id or "").strip()
    if pid and len(pid) >= 3:
        pl = pid.lower()
        if pl not in seen:
            out.append(pl)
    return out


def _text_mentions_reference(haystack_lower: str, ref_lower: str) -> bool:
    """Short alphabetic tokens must match as whole words; longer refs use substring match."""
    if len(ref_lower) <= 4 and ref_lower.isalpha():
        return bool(re.search(rf"\b{re.escape(ref_lower)}\b", haystack_lower, re.IGNORECASE))
    return ref_lower in haystack_lower


def validate_profile_data(
    profile_dict: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate extracted profile data for completeness, consistency, and plausibility.

    Args:
        profile_dict: Extracted profile data

    Returns:
        (is_valid, list_of_issues)
    """
    issues: list[str] = []

    # Check for hallucination indicators
    profile_str = json.dumps(profile_dict).lower()
    profile_meta = _content_metadata(profile_str)
    for indicator in HALLUCINATION_INDICATORS:
        if indicator.lower() in profile_str:
            issues.append(f"Potential hallucination detected: '{indicator}'")
            logger.warning("hallucination_detected", indicator=indicator, **profile_meta)

    # Check for incomplete extraction patterns
    for regex in INCOMPLETE_EXTRACTION_REGEXES:
        if regex.search(profile_str):
            issues.append(f"Incomplete extraction detected: {regex.pattern}")
            logger.warning("incomplete_extraction", pattern=regex.pattern, **profile_meta)

    # Validate key fields are present and non-empty
    required_fields = ["target_degree_level", "education"]
    for field in required_fields:
        if not profile_dict.get(field):
            issues.append(f"Missing or empty required field: {field}")

    # Validate education array has at least one entry
    education = profile_dict.get("education") or []
    if not isinstance(education, list) or len(education) == 0:
        issues.append("No education records extracted")

    is_valid = len(issues) == 0
    return is_valid, issues


def validate_output_for_leakage(content: str) -> list[str]:
    """Check LLM output for prompt leakage and injection patterns.

    Used for security monitoring of LLM outputs to detect potential
    data boundary violations or jailbreak echoes.

    Args:
        content: LLM-generated content to validate

    Returns:
        List of issues found (empty if clean)
    """
    issues: list[str] = []

    if not content:
        return issues

    content_meta = _content_metadata(content)

    # Check for prompt leakage patterns
    for pattern in PROMPT_LEAKAGE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"Prompt leakage detected: {pattern}")
            logger.warning("prompt_leakage_in_output", pattern=pattern, **content_meta)

    # Check for injection echo patterns
    for pattern in OUTPUT_INJECTION_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"Injection pattern echoed: {pattern}")
            logger.warning("output_injection_pattern", pattern=pattern, **content_meta)

    return issues
