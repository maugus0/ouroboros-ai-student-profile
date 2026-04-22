"""Prompt lint and token validation tests.

Validates:
- Prompt JSON files exist and are well-formed
- Token budgets are within safe limits
- All required sections are present
"""

import json
from pathlib import Path

import pytest

# Token budgets for each prompt type
TOKEN_BUDGETS = {
    "profile_extraction_core_v1.json": 6000,  # Core extraction pass
    "profile_extraction_enrichment_v1.json": 4000,  # Enrichment pass
    "profile_extraction_v2.json": 8000,  # Full extraction (v2)
    "target_degree_detection_v2.json": 2000,  # Target degree detection
    "gap_analysis_v2.json": 6000,  # Gap analysis
}


def get_prompts_dir():
    """Get the prompts directory path."""
    return Path(__file__).parent.parent.parent / "prompts"


@pytest.mark.parametrize(
    "filename,max_tokens",
    list(TOKEN_BUDGETS.items()),
)
def test_prompt_files_exist_and_valid(filename, max_tokens):
    """Verify prompt files exist and are valid JSON."""
    prompt_path = get_prompts_dir() / filename
    assert prompt_path.exists(), f"Prompt file not found: {filename}"

    try:
        with open(prompt_path, encoding="utf-8") as f:
            prompt = json.load(f)
        assert isinstance(prompt, dict), f"{filename} is not a valid JSON object"
    except json.JSONDecodeError as e:
        pytest.fail(f"{filename} has invalid JSON: {e}")


def test_prompt_token_budgets():
    """Verify prompt content approximates expected token counts.

    Note: This is a rough approximation using 4 chars ≈ 1 token.
    Actual token counts depend on the LLM's tokenizer.
    """
    for filename, max_tokens in TOKEN_BUDGETS.items():
        prompt_path = get_prompts_dir() / filename

        if not prompt_path.exists():
            pytest.skip(f"Prompt file not found: {filename}")

        with open(prompt_path, encoding="utf-8") as f:
            prompt = json.load(f)

        # Rough token estimation: ~4 chars per token
        prompt_str = json.dumps(prompt, indent=2)
        estimated_tokens = len(prompt_str) // 4

        # Warn if approaching budget (80% threshold)
        warning_threshold = max_tokens * 0.8
        assert (
            estimated_tokens < max_tokens
        ), f"{filename} estimated tokens ({estimated_tokens}) exceed budget ({max_tokens})"

        if estimated_tokens > warning_threshold:
            print(
                f"⚠️ {filename}: {estimated_tokens} tokens " f"({int(estimated_tokens / max_tokens * 100)}% of budget)"
            )


def test_prompt_required_sections():
    """Verify all prompts have required structure."""
    required_top_level = ["prompt_template"]

    for filename in TOKEN_BUDGETS:
        prompt_path = get_prompts_dir() / filename

        if not prompt_path.exists():
            pytest.skip(f"Prompt file not found: {filename}")

        with open(prompt_path, encoding="utf-8") as f:
            prompt = json.load(f)

        for section in required_top_level:
            assert section in prompt, f"{filename} missing required top-level key: {section}"
            assert prompt[section], f"{filename} key '{section}' is empty"
