"""System prompts for LLM extraction operations."""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "system_prompts"


def _load_prompt(filename: str) -> str:
    """Load a prompt text file from the system_prompts directory."""
    path = _PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def get_profile_extraction_prompt() -> str:
    return _load_prompt("profile_extraction_v1.txt")


def get_target_degree_detection_prompt() -> str:
    return _load_prompt("target_degree_detection_v1.txt")


def get_gap_analysis_prompt() -> str:
    return _load_prompt("gap_analysis_v1.txt")
