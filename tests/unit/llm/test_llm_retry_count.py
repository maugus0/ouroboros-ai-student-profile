"""Tests for retry-count extraction helper in LLM service."""

from app.services.llm_service import LLMService


class _DummyRetry:
    def __init__(self, statistics):
        self.statistics = statistics


class _DummyFunc:
    def __init__(self, statistics):
        self.retry = _DummyRetry(statistics)


def test_get_retry_count_with_attempt_number():
    func = _DummyFunc({"attempt_number": 3})
    assert LLMService._get_retry_count(func) == 2


def test_get_retry_count_without_retry_info():
    assert LLMService._get_retry_count(object()) == 0
