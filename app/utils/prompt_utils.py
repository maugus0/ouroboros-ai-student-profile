"""Utilities for building dynamic prompts with runtime context injection.

Uses best practices: versioned JSON prompt templates on disk, merged with
runtime context and serialised for the LLM.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt_template(filename: str) -> dict[str, Any]:
    """Load a JSON prompt template from the prompts/ directory."""
    path = _PROMPTS_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")

    try:
        content = path.read_text(encoding="utf-8")
        return json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("invalid_prompt_json", file=filename, error=str(exc))
        raise ValueError(f"Invalid JSON in prompt template {filename}: {exc}") from exc


def merge_runtime_context(
    template: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge runtime context into the base prompt structure.

    Returns a new dict containing the base template keys plus a
    ``runtime_context`` key when *context* is not ``None`` (including
    when it is an empty dict, so callers can explicitly signal
    "context was supplied but is empty").
    """
    prompt = dict(template.get("prompt_template", {}).get("base", {}))

    if context is not None:
        prompt["runtime_context"] = _clean_context(context)

    return prompt


def build_prompt_json(
    template_file: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Load template, merge context, return a JSON string for the LLM."""
    template = load_prompt_template(template_file)
    prompt = merge_runtime_context(template, context)

    return json.dumps(
        prompt,
        ensure_ascii=False,
        indent=2,
        default=_json_serializer,
    )


def build_prompt_text(
    template_file: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Load template, merge context, return a structured text string.

    Converts the JSON template into human-readable sections so models
    that prefer plain-text system prompts still get full context.
    """
    prompt_json = build_prompt_json(template_file, context)
    prompt_dict = json.loads(prompt_json)

    lines: list[str] = []

    if "agent_identity" in prompt_dict:
        identity = prompt_dict.pop("agent_identity")
        lines.append("=== AGENT IDENTITY ===")
        for key, value in identity.items():
            if isinstance(value, list):
                lines.append(f"{_label(key)}:")
                for item in value:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{_label(key)}: {value}")
        lines.append("")

    for key, value in prompt_dict.items():
        lines.append(f"=== {_label(key)} ===")
        lines.append(_format_section(value))
        lines.append("")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------


def _clean_context(context: dict[str, Any]) -> dict[str, Any]:
    """Strip sensitive / internal-only keys before injecting into prompts."""
    cleaned = dict(context)
    for drop_key in ("agent_capabilities", "internal_flags"):
        cleaned.pop(drop_key, None)
    return cleaned


def _json_serializer(obj: Any) -> Any:
    """Handle Decimal, set, and other non-standard JSON types."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    return str(obj)


def _label(key: str) -> str:
    return key.upper().replace("_", " ")


def _format_section(value: Any, indent: int = 0) -> str:
    prefix = "  " * indent

    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                parts.append(f"{prefix}{_label(k)}:")
                parts.append(_format_section(v, indent + 1))
            else:
                parts.append(f"{prefix}{_label(k)}: {v}")
        return "\n".join(parts)

    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, (dict, list)):
                parts.append(_format_section(item, indent))
            else:
                parts.append(f"{prefix}- {item}")
        return "\n".join(parts)

    return f"{prefix}{value}"
