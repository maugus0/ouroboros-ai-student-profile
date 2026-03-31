"""Tests for centralized logging redaction."""

from app.core.logging import REDACTED, redact_sensitive_data


def test_redact_sensitive_keys_recursively():
    event = {
        "event": "example",
        "model_name": "gpt-4o-mini",
        "full_name": "John Doe",
        "email": "john.doe@example.com",
        "metadata": {
            "date_of_birth": "2000-09-07",
            "profile_json": {"phone": "+65-1234-5678"},
        },
    }

    redacted = redact_sensitive_data(None, "info", event)

    assert redacted["event"] == "example"
    assert redacted["model_name"] == "gpt-4o-mini"
    assert redacted["full_name"] == REDACTED
    assert redacted["email"] == REDACTED
    assert redacted["metadata"]["date_of_birth"] == REDACTED
    assert redacted["metadata"]["profile_json"] == REDACTED


def test_redact_text_patterns_in_freeform_strings():
    event = {
        "error": "failed for john.doe@example.com using Bearer abcdef123 token=xyz",
    }

    redacted = redact_sensitive_data(None, "warning", event)

    assert "john.doe@example.com" not in redacted["error"]
    assert "abcdef123" not in redacted["error"]
    assert "token=xyz" not in redacted["error"]
    assert REDACTED in redacted["error"]
