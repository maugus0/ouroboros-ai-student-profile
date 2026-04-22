"""Input sanitization to prevent prompt injection and malicious content."""

import hashlib
import re
import unicodedata
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.utils.exceptions import PromptInjectionError, ValidationError

logger = get_logger(__name__)

# Instruction-like substrings commonly used in jailbreaks (case-insensitive match).
CONTROL_PATTERNS = [
    r"<\|.*?\|>",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[\s*INST\s*\]",
    r"###\s*SYSTEM",
    r"###\s*ASSISTANT",
    r"###\s*USER",
    r"###\s*IGNORE",
    r"IGNORE\s+(PREVIOUS|ALL)\s+INSTRUCTIONS",
    r"DISREGARD\s+(PREVIOUS|ALL)\s+INSTRUCTIONS",
    r"OVERRIDE\s+SYSTEM",
    r"NEW\s+INSTRUCTIONS?\s*:",
    r"BEGIN\s+SYSTEM\s+PROMPT",
    r"END\s+SYSTEM\s+PROMPT",
    r"<\s*script",
    r"</\s*script\s*>",
]


def strip_control_characters(text: str, *, preserve_newline_tab: bool = True) -> str:
    """Remove Unicode control characters (category ``Cc``).

    Optionally keeps ``\\n`` and ``\\t`` so multi-line bios stay readable; other
    ``Cc`` (NUL, bells, escape, etc.) are stripped.
    """
    if not text:
        return text
    out: list[str] = []
    for ch in text:
        if preserve_newline_tab and ch in "\n\t":
            out.append(ch)
            continue
        if unicodedata.category(ch) == "Cc":
            continue
        out.append(ch)
    return "".join(out)


def detect_injection_attempt(text: str) -> bool:
    """Detect potential prompt injection patterns in text.

    Args:
        text: Text to check for injection patterns

    Returns:
        True if suspicious patterns detected, False otherwise
    """
    if not text or not settings.ENABLE_PROMPT_INJECTION_DETECTION:
        return False

    for pattern in CONTROL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def sanitize_text(text: str, field_name: str = "input") -> str:
    """Sanitize text input.

    Args:
        text: Raw text from user
        field_name: Field name for logging

    Returns:
        Cleaned text

    Raises:
        ValidationError: If input is too long
        PromptInjectionError: If control instructions are detected
    """
    if not text:
        return text

    text = strip_control_characters(text)

    if len(text) > settings.MAX_INPUT_LENGTH:
        raise ValidationError(f"{field_name} exceeds maximum length of {settings.MAX_INPUT_LENGTH} characters")

    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r" +", " ", text).strip()

    if settings.ENABLE_PROMPT_INJECTION_DETECTION:
        for pattern in CONTROL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(
                    "potential_prompt_injection_detected",
                    field=field_name,
                    pattern=pattern,
                    text_length=len(text),
                    text_hash=hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
                )
                raise PromptInjectionError(
                    f"{field_name} contains suspicious patterns that may attempt prompt injection"
                )

    return text


def sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively sanitize all text fields in a dictionary."""
    sanitized: dict[str, Any] = {}

    for key, value in data.items():
        if isinstance(value, str):
            sanitized[key] = sanitize_text(value, field_name=key)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_dict(value)
        elif isinstance(value, list):
            sanitized[key] = [_sanitize_list_item(item, key) for item in value]
        else:
            sanitized[key] = value

    return sanitized


def _sanitize_list_item(item: Any, field_name: str) -> Any:
    if isinstance(item, str):
        return sanitize_text(item, field_name=field_name)
    if isinstance(item, dict):
        return sanitize_dict(item)
    return item
