"""Pytest configuration and shared fixtures."""

import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ALLOW_DB_FAILURE", "true")
os.environ.setdefault("USE_MOCK_DATA", "true")
# Use internal bearer tokens; configure for HS256 test tokens
os.environ.setdefault("INTERNAL_TOKEN_VERIFY_ENABLED", "true")
os.environ.setdefault("INTERNAL_TOKEN_SIGNING_ALGORITHM", "HS256")
os.environ.setdefault("INTERNAL_TOKEN_PUBLIC_KEY", "internal-test-signing-key-with-32-bytes")
os.environ.setdefault("INTERNAL_TOKEN_ISSUER", "ouroboros-orchestrator-internal")
os.environ.setdefault("INTERNAL_TOKEN_AUDIENCE", "ouroboros.student-profile")

from app.main import app  # noqa: E402  # pylint: disable=wrong-import-position


@pytest.fixture
def mock_settings():
    return {
        "DB_HOST": "localhost",
        "DB_NAME": "test_db",
        "USE_MOCK_DATA": True,
        "ALLOW_DB_FAILURE": True,
        "INTERNAL_TOKEN_VERIFY_ENABLED": True,
    }


@pytest.fixture
def service_token_header():
    """Returns an internal bearer token for testing.

    Note: Legacy X-Service-Token support has been removed.
    All tests now use Kubernetes-native internal bearer tokens.
    """
    # Generate a valid HS256 JWT token for testing
    test_key = "internal-test-signing-key-with-32-bytes"
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "test-user",
            "aud": "ouroboros.student-profile",
            "iss": "ouroboros-orchestrator-internal",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "sid": "test-session",
            "trace_id": "test-trace",
            "jti": "test-jti",
        },
        test_key,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    """Shared API test client for unit and flow tests."""
    with TestClient(app) as test_client:
        yield test_client
