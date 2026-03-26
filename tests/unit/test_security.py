"""Tests for X-Service-Token validation."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_missing_service_token():
    response = client.get("/profiles")
    assert response.status_code == 401


def test_invalid_service_token():
    response = client.get("/profiles", headers={"X-Service-Token": "wrong-token"})
    assert response.status_code == 403


def test_valid_service_token_returns_non_401(service_token_header):
    response = client.get("/profiles/non-existent-id", headers=service_token_header)
    # Expect 500 (no DB pool) — the important thing is it's NOT 401/403
    assert response.status_code not in (401, 403)
