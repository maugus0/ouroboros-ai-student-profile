"""Tests for LLM prompt generation functions."""

import json

import pytest

from app.llm.prompts import (
    get_gap_analysis_prompt,
    get_profile_extraction_prompt,
    get_target_degree_detection_prompt,
)


def test_profile_extraction_prompt_json_format():
    prompt = get_profile_extraction_prompt(fmt="json")
    parsed = json.loads(prompt)

    assert "agent_identity" in parsed
    assert "extraction_rules" in parsed


def test_profile_extraction_prompt_text_format():
    prompt = get_profile_extraction_prompt(fmt="text")

    assert "AGENT IDENTITY" in prompt
    assert "EXTRACTION RULES" in prompt
    assert len(prompt) > 100


def test_profile_extraction_with_context():
    context = {"user_provided_target_degree": "phd"}
    prompt = get_profile_extraction_prompt(context=context, fmt="json")

    parsed = json.loads(prompt)
    assert "runtime_context" in parsed
    assert parsed["runtime_context"]["user_provided_target_degree"] == "phd"


def test_target_degree_detection_prompt():
    prompt = get_target_degree_detection_prompt(fmt="json")
    parsed = json.loads(prompt)

    assert "agent_identity" in parsed
    assert "decision_framework" in parsed


def test_gap_analysis_prompt():
    prompt = get_gap_analysis_prompt(fmt="json")
    parsed = json.loads(prompt)

    assert "baseline_expectations" in parsed
    assert "master" in parsed["baseline_expectations"]
    assert "phd" in parsed["baseline_expectations"]


def test_gap_analysis_with_context():
    context = {"target_degree": "master", "profile_summary": {"has_gpa": True}}
    prompt = get_gap_analysis_prompt(context=context, fmt="json")

    parsed = json.loads(prompt)
    assert parsed["runtime_context"]["target_degree"] == "master"


@pytest.mark.parametrize(
    "bad_fmt",
    ["JSON", "txt", "markdown", ""],
)
def test_invalid_prompt_format_raises(bad_fmt):
    with pytest.raises(ValueError, match="Unsupported prompt format"):
        get_profile_extraction_prompt(fmt=bad_fmt)
