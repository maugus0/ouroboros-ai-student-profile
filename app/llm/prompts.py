"""Prompt loading and building with runtime context injection.

Each prompt function loads its JSON template from ``prompts/``,
optionally merges runtime context, and returns a string in the
requested format (``json`` or ``text``).
"""

from typing import Any

from app.utils.prompt_utils import build_prompt_json, build_prompt_text


def get_profile_extraction_prompt(
    context: dict[str, Any] | None = None,
    fmt: str = "json",
) -> str:
    """Build the profile-extraction system prompt.

    Args:
        context: Runtime data to inject (document metadata, user hints, etc.).
        fmt: ``"json"`` or ``"text"`` — output format preference.
    """
    if fmt == "text":
        return build_prompt_text("profile_extraction_v1.json", context)
    return build_prompt_json("profile_extraction_v1.json", context)


def get_target_degree_detection_prompt(
    context: dict[str, Any] | None = None,
    fmt: str = "json",
) -> str:
    """Build the target-degree detection system prompt."""
    if fmt == "text":
        return build_prompt_text("target_degree_detection_v1.json", context)
    return build_prompt_json("target_degree_detection_v1.json", context)


def get_gap_analysis_prompt(
    context: dict[str, Any] | None = None,
    fmt: str = "json",
) -> str:
    """Build the gap-analysis system prompt."""
    if fmt == "text":
        return build_prompt_text("gap_analysis_v1.json", context)
    return build_prompt_json("gap_analysis_v1.json", context)
