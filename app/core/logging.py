"""Structured logging configuration using structlog."""

import logging
import re
import sys
from typing import Any, cast

import structlog

REDACTED = "[REDACTED]"
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*")
_KEY_VALUE_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret|authorization)\s*[:=]\s*([^\s,;]+)"
)

_SENSITIVE_EXACT_KEYS = {
    "full_name",
    "first_name",
    "last_name",
    "student_name",
    "email",
    "phone",
    "date_of_birth",
    "birth_date",
    "dob",
    "nationality",
    "address",
    "profile_json",
    "clarification_queue",
    "answers",
}

_SENSITIVE_KEY_TOKENS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "file_content",
    "document_text",
}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _SENSITIVE_EXACT_KEYS:
        return True
    return any(token in lowered for token in _SENSITIVE_KEY_TOKENS)


def _redact_text(value: str) -> str:
    masked = _EMAIL_PATTERN.sub(REDACTED, value)
    masked = _BEARER_PATTERN.sub("Bearer [REDACTED]", masked)
    return _KEY_VALUE_SECRET_PATTERN.sub(lambda m: f"{m.group(1)}={REDACTED}", masked)


def _redact_value(key: str | None, value: Any) -> Any:
    if key and _is_sensitive_key(key):
        return REDACTED

    if isinstance(value, dict):
        return {k: _redact_value(str(k), v) for k, v in value.items()}

    if isinstance(value, list):
        return [_redact_value(None, item) for item in value]

    if isinstance(value, tuple):
        return tuple(_redact_value(None, item) for item in value)

    if isinstance(value, str):
        return _redact_text(value)

    return value


def redact_sensitive_data(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor to sanitize sensitive values before rendering."""
    return {key: _redact_value(str(key), value) for key, value in event_dict.items()}


def setup_logging(log_level: str = "INFO", environment: str = "development") -> None:
    """
    Configure structured logging for the application.
    JSON output in production, coloured console output in development.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        redact_sensitive_data,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if environment == "production":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=cast(Any, processors),
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    """Get a structured logger instance bound with the given name."""
    return structlog.get_logger(name)
