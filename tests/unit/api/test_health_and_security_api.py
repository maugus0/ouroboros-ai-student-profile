"""Unit tests for basic health and security API behavior."""


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


def test_missing_service_token(client):
    response = client.get("/api/v1/profiles")
    assert response.status_code == 401


def test_invalid_service_token(client):
    response = client.get("/api/v1/profiles", headers={"X-Service-Token": "wrong-token"})
    assert response.status_code == 403


def test_valid_service_token_returns_non_401(client, service_token_header):
    response = client.get("/api/v1/profiles/non-existent-id", headers=service_token_header)
    # Expect 500 (no DB pool) — the important thing is it's NOT 401/403
    assert response.status_code not in (401, 403)
