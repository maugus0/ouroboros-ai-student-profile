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

from app.utils.prompt_utils import build_prompt_json, build_prompt_text

_VALID_FORMATS: frozenset[str] = frozenset({"json", "text"})


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
    _require_prompt_format(fmt)
    if fmt == "text":
        return build_prompt_text("profile_extraction_v1.json", context)
    return build_prompt_json("profile_extraction_v1.json", context)


def get_target_degree_detection_prompt(
    context: dict[str, Any] | None = None,
    fmt: str = "json",
) -> str:
    """Build the target-degree detection system prompt."""
    _require_prompt_format(fmt)
    if fmt == "text":
        return build_prompt_text("target_degree_detection_v1.json", context)
    return build_prompt_json("target_degree_detection_v1.json", context)


def get_gap_analysis_prompt(
    context: dict[str, Any] | None = None,
    fmt: str = "json",
) -> str:
    """Build the gap-analysis system prompt."""
    _require_prompt_format(fmt)
    if fmt == "text":
        return build_prompt_text("gap_analysis_v1.json", context)
    return build_prompt_json("gap_analysis_v1.json", context)
