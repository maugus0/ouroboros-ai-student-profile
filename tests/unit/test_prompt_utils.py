"""Tests for prompt utility functions."""

import json

import pytest

from app.utils.prompt_utils import (
    build_prompt_json,
    build_prompt_text,
    load_prompt_template,
    merge_runtime_context,
)


def test_load_prompt_template():
    """Verify we can load a JSON prompt template."""
    template = load_prompt_template("profile_extraction_v1.json")
    assert "prompt_template" in template
    assert "base" in template["prompt_template"]


def test_load_nonexistent_template_raises():
    with pytest.raises(FileNotFoundError):
        load_prompt_template("nonexistent.json")


def test_merge_runtime_context():
    template = load_prompt_template("profile_extraction_v1.json")
    context = {
        "document_metadata": {"text_length": 5000},
        "user_provided_target_degree": "master",
    }

    prompt = merge_runtime_context(template, context)

    assert "runtime_context" in prompt
    assert prompt["runtime_context"]["document_metadata"]["text_length"] == 5000
    assert prompt["runtime_context"]["user_provided_target_degree"] == "master"


def test_merge_strips_internal_keys():
    template = load_prompt_template("profile_extraction_v1.json")
    context = {
        "agent_capabilities": ["should_be_removed"],
        "internal_flags": {"debug": True},
        "keep_this": "yes",
    }

    prompt = merge_runtime_context(template, context)
    rc = prompt["runtime_context"]

    assert "agent_capabilities" not in rc
    assert "internal_flags" not in rc
    assert rc["keep_this"] == "yes"


def test_merge_without_context_has_no_runtime_key():
    template = load_prompt_template("profile_extraction_v1.json")
    prompt = merge_runtime_context(template)

    assert "runtime_context" not in prompt
    assert "agent_identity" in prompt


def test_build_prompt_json_returns_valid_json():
    context = {"test_key": "test_value"}
    result = build_prompt_json("profile_extraction_v1.json", context)

    parsed = json.loads(result)
    assert "runtime_context" in parsed
    assert parsed["runtime_context"]["test_key"] == "test_value"


def test_build_prompt_text_contains_sections():
    result = build_prompt_text("profile_extraction_v1.json")

    assert "AGENT IDENTITY" in result
    assert "EXTRACTION RULES" in result
    assert isinstance(result, str)
    assert len(result) > 100


def test_all_templates_load():
    """All three prompt templates should load without error."""
    for filename in (
        "profile_extraction_v1.json",
        "target_degree_detection_v1.json",
        "gap_analysis_v1.json",
    ):
        template = load_prompt_template(filename)
        assert "prompt_template" in template
