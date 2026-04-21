"""Prompt loading and building with runtime context injection.

Templates live under ``prompts/`` as versioned JSON. These helpers are
used by in-process code (e.g. ``LLMService``), not by HTTP clients.
The Ouroboros orchestrator calls this microservice over HTTP; those
requests are handled in ``app/api`` and eventually invoke services that
build prompts here.

Each function returns a string in the requested format (``json`` or
``text``). Unknown ``fmt`` values raise ``ValueError`` so typos fail
fast at development time.
"""

from typing import Any

from app.config import settings
from app.utils.prompt_utils import build_prompt_json, build_prompt_text

_VALID_FORMATS: frozenset[str] = frozenset({"json", "text"})
_VALID_PROMPT_TYPES: frozenset[str] = frozenset({"profile_extraction", "target_degree_detection", "gap_analysis"})


def _require_prompt_type(prompt_type: str) -> None:
    if prompt_type not in _VALID_PROMPT_TYPES:
        raise ValueError(f"Unsupported prompt type {prompt_type!r}; expected one of {sorted(_VALID_PROMPT_TYPES)}.")


def _normalize_version(version: str) -> str:
    normalized = str(version or "").strip().lower()
    if not normalized:
        raise ValueError("Prompt version cannot be empty.")
    if not normalized.startswith("v"):
        normalized = f"v{normalized}"
    if not normalized[1:].isdigit():
        raise ValueError(f"Invalid prompt version {version!r}; expected format v<number>.")
    return normalized


def _get_configured_version(prompt_type: str) -> str:
    _require_prompt_type(prompt_type)
    configured_by_type = {
        "profile_extraction": settings.PROFILE_EXTRACTION_PROMPT_VERSION,
        "target_degree_detection": settings.TARGET_DEGREE_PROMPT_VERSION,
        "gap_analysis": settings.GAP_ANALYSIS_PROMPT_VERSION,
    }
    return _normalize_version(configured_by_type[prompt_type])


def _resolve_template_file(prompt_type: str) -> str:
    version = _get_configured_version(prompt_type)
    return f"{prompt_type}_{version}.json"


def get_prompt_template_version(prompt_type: str) -> str:
    """Return prompt template version label for logs, e.g. profile_extraction_v2."""
    template_file = _resolve_template_file(prompt_type)
    return template_file.removesuffix(".json")


def _build_prompt(prompt_type: str, context: dict[str, Any] | None = None, fmt: str = "json") -> str:
    _require_prompt_format(fmt)
    template_file = _resolve_template_file(prompt_type)
    if fmt == "text":
        return build_prompt_text(template_file, context)
    return build_prompt_json(template_file, context)


def _require_prompt_format(fmt: str) -> None:
    if fmt not in _VALID_FORMATS:
        raise ValueError(f"Unsupported prompt format {fmt!r}; expected one of {sorted(_VALID_FORMATS)}.")


def get_profile_extraction_prompt(
    context: dict[str, Any] | None = None,
    fmt: str = "json",
) -> str:
    """Build the profile-extraction system prompt.

    Args:
        context: Runtime data to inject (document metadata, user hints, etc.).
        fmt: ``"json"`` (machine-oriented) or ``"text"`` (plain-text sections for the LLM).
    """
    return _build_prompt("profile_extraction", context, fmt)


def get_target_degree_detection_prompt(
    context: dict[str, Any] | None = None,
    fmt: str = "json",
) -> str:
    """Build the target-degree detection system prompt."""
    return _build_prompt("target_degree_detection", context, fmt)


def get_gap_analysis_prompt(
    context: dict[str, Any] | None = None,
    fmt: str = "json",
) -> str:
    """Build the gap-analysis system prompt."""
    return _build_prompt("gap_analysis", context, fmt)
