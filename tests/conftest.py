"""Pytest configuration and shared fixtures."""

import os

import pytest

os.environ.setdefault("ALLOW_DB_FAILURE", "true")
os.environ.setdefault("USE_MOCK_DATA", "true")
os.environ.setdefault("X_SERVICE_TOKEN", "test-service-token")


@pytest.fixture
def mock_settings():
    from app.config import settings

    return {
        "DB_HOST": "localhost",
        "DB_NAME": "test_db",
        "USE_MOCK_DATA": True,
        "ALLOW_DB_FAILURE": True,
        "X_SERVICE_TOKEN": settings.X_SERVICE_TOKEN,
    }


@pytest.fixture
def service_token_header():
    """Header value always matches ``settings.X_SERVICE_TOKEN`` (local + CI)."""
    from app.config import settings

    return {"X-Service-Token": settings.X_SERVICE_TOKEN}
