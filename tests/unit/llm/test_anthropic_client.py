"""Tests for Anthropic client response parsing."""

import pytest

from app.llm.anthropic_client import _build_response_preview, _parse_anthropic_json


def test_parse_anthropic_json_accepts_fenced_json_object():
    raw = """
    ```json
    {"full_name": "Jane Doe", "education": []}
    ```
    """

    parsed = _parse_anthropic_json(raw)

    assert parsed == {"full_name": "Jane Doe", "education": []}


def test_parse_anthropic_json_accepts_prefixed_json_object():
    raw = 'Here is the extracted profile:\n{"full_name": "Jane Doe", "education": []}'

    parsed = _parse_anthropic_json(raw)

    assert parsed == {"full_name": "Jane Doe", "education": []}


def test_parse_anthropic_json_accepts_json_object_with_trailing_text():
    raw = '{"full_name": "Jane Doe", "education": []}\n\n' "Additional note: some fields may need manual review."

    parsed = _parse_anthropic_json(raw)

    assert parsed == {"full_name": "Jane Doe", "education": []}


def test_parse_anthropic_json_ignores_array_like_prefix_before_object():
    raw = 'Candidate fields: ["education", "research_experience"]\n' '{"full_name": "Jane Doe", "education": []}'

    parsed = _parse_anthropic_json(raw)

    assert parsed == {"full_name": "Jane Doe", "education": []}


def test_parse_anthropic_json_rejects_non_json_text():
    with pytest.raises(ValueError, match="Anthropic returned non-JSON content"):
        _parse_anthropic_json("I cannot comply with that request.")


def test_parse_anthropic_json_error_includes_response_preview():
    raw = "Here is my answer, not JSON at all."

    with pytest.raises(ValueError, match="Response preview: Here is my answer, not JSON at all."):
        _parse_anthropic_json(raw)


def test_build_response_preview_truncates_long_content():
    raw = "a" * 600 + "b" * 600

    preview = _build_response_preview(raw, limit=100)

    assert "[TRUNCATED RAW RESPONSE]" in preview
    assert preview.startswith("a" * 50)
    assert preview.endswith("b" * 50)
