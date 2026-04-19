"""Unit tests for basic health and security API behavior."""

import json
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

INTERNAL_TEST_KEY = "internal-test-signing-key-with-32-bytes"


def _generate_rsa_keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def _build_internal_bearer_token(
    *,
    audience: str = "ouroboros.student-profile",
    issuer: str = "ouroboros-orchestrator-internal",
    expires_delta_seconds: int = 120,
) -> str:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "user-123",
            "aud": audience,
            "iss": issuer,
            "iat": now,
            "exp": now + timedelta(seconds=expires_delta_seconds),
            "trace_id": "trace-1",
            "jti": "jti-1",
        },
        INTERNAL_TEST_KEY,
        algorithm="HS256",
        headers={"kid": "internal-v1"},
    )
    return f"Bearer {token}"


def _build_internal_bearer_token_rs256(
    private_key: str,
    *,
    audience: str = "ouroboros.student-profile",
    issuer: str = "ouroboros-orchestrator-internal",
    expires_delta_seconds: int = 120,
    kid: str = "internal-v1",
) -> str:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "user-123",
            "aud": audience,
            "iss": issuer,
            "iat": now,
            "exp": now + timedelta(seconds=expires_delta_seconds),
            "trace_id": "trace-1",
            "jti": "jti-1",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )
    return f"Bearer {token}"


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["message"] == "Student Profile Agent"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "version" in data
    assert data["database"] in ("connected", "not_connected")


def test_health_check_works(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_valid_internal_bearer_token_returns_non_401_when_enabled(client, monkeypatch):
    token = _build_internal_bearer_token()

    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_VERIFY_ENABLED", True)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "HS256")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEY", INTERNAL_TEST_KEY)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_AUDIENCE", "ouroboros.student-profile")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_ISSUER", "ouroboros-orchestrator-internal")

    response = client.get(
        "/api/v1/profiles/non-existent-id",
        headers={"Authorization": token, "X-User-ID": "user-123"},
    )
    assert response.status_code not in (401, 403)


def test_internal_bearer_token_verification_bypassed_when_disabled(client, monkeypatch):
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_VERIFY_ENABLED", False)

    response = client.get(
        "/api/v1/profiles/non-existent-id",
        headers={"X-User-ID": "user-123"},
    )
    assert response.status_code not in (401, 403)


def test_invalid_internal_bearer_token_rejected(client, monkeypatch):
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_VERIFY_ENABLED", True)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "HS256")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEY", INTERNAL_TEST_KEY)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_AUDIENCE", "ouroboros.student-profile")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_ISSUER", "ouroboros-orchestrator-internal")

    response = client.get(
        "/api/v1/profiles/non-existent-id",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


def test_internal_bearer_token_rejected_on_audience_mismatch(client, monkeypatch):
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_VERIFY_ENABLED", True)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "HS256")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEY", INTERNAL_TEST_KEY)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_AUDIENCE", "ouroboros.student-profile")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_ISSUER", "ouroboros-orchestrator-internal")

    response = client.get(
        "/api/v1/profiles/non-existent-id",
        headers={"Authorization": _build_internal_bearer_token(audience="ouroboros.other-service")},
    )
    assert response.status_code == 401


def test_internal_bearer_token_rejected_on_issuer_mismatch(client, monkeypatch):
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_VERIFY_ENABLED", True)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "HS256")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEY", INTERNAL_TEST_KEY)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_AUDIENCE", "ouroboros.student-profile")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_ISSUER", "ouroboros-orchestrator-internal")

    response = client.get(
        "/api/v1/profiles/non-existent-id",
        headers={"Authorization": _build_internal_bearer_token(issuer="unexpected-issuer")},
    )
    assert response.status_code == 401


def test_internal_bearer_token_rejected_when_expired(client, monkeypatch):
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_VERIFY_ENABLED", True)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "HS256")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEY", INTERNAL_TEST_KEY)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_AUDIENCE", "ouroboros.student-profile")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_ISSUER", "ouroboros-orchestrator-internal")

    response = client.get(
        "/api/v1/profiles/non-existent-id",
        headers={"Authorization": _build_internal_bearer_token(expires_delta_seconds=-60)},
    )
    assert response.status_code == 401


def test_internal_bearer_token_uses_jwks_for_kid_resolution(client, monkeypatch):
    private_pem, public_pem = _generate_rsa_keypair()

    async def _resolve_jwks_key_mock(_url: str, _kid: str) -> str:
        return public_pem

    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_VERIFY_ENABLED", True)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "RS256")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEY", "")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEYS", "{}")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_JWKS_URL", "http://jwks.example/jwks.json")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_AUDIENCE", "ouroboros.student-profile")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_ISSUER", "ouroboros-orchestrator-internal")
    monkeypatch.setattr("app.middleware.service_auth._jwks_cache_by_url", {})
    monkeypatch.setattr(
        "app.middleware.service_auth._resolve_jwks_key",
        _resolve_jwks_key_mock,
    )

    response = client.get(
        "/api/v1/profiles/non-existent-id",
        headers={
            "Authorization": _build_internal_bearer_token_rs256(private_pem, kid="internal-v5"),
            "X-User-ID": "user-123",
        },
    )
    assert response.status_code not in (401, 403)


def test_internal_bearer_token_uses_configured_public_keys_by_kid_without_jwks(client, monkeypatch):
    private_pem, public_pem = _generate_rsa_keypair()

    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_VERIFY_ENABLED", True)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "RS256")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEY", "")
    monkeypatch.setattr(
        "app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEYS",
        json.dumps({"internal-config-kid": public_pem.replace("\n", "\\n")}),
    )
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_JWKS_URL", "")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_AUDIENCE", "ouroboros.student-profile")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_ISSUER", "ouroboros-orchestrator-internal")

    response = client.get(
        "/api/v1/profiles/non-existent-id",
        headers={
            "Authorization": _build_internal_bearer_token_rs256(private_pem, kid="internal-config-kid"),
            "X-User-ID": "user-123",
        },
    )
    assert response.status_code not in (401, 403)


def test_internal_bearer_token_rejected_on_unknown_kid_when_no_fallback_key(client, monkeypatch):
    private_pem, _public_pem = _generate_rsa_keypair()

    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_VERIFY_ENABLED", True)
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_SIGNING_ALGORITHM", "RS256")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEY", "")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_PUBLIC_KEYS", "{}")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_JWKS_URL", "")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_AUDIENCE", "ouroboros.student-profile")
    monkeypatch.setattr("app.middleware.service_auth.settings.INTERNAL_TOKEN_ISSUER", "ouroboros-orchestrator-internal")

    response = client.get(
        "/api/v1/profiles/non-existent-id",
        headers={"Authorization": _build_internal_bearer_token_rs256(private_pem, kid="missing-kid")},
    )
    assert response.status_code == 401
