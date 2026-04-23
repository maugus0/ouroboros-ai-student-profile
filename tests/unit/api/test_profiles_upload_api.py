"""Unit tests for multipart profile upload endpoint."""


def test_parse_upload_success(client, monkeypatch, internal_token_header):
    async def fake_parse_and_create_profile(**kwargs):
        assert kwargs["intent"] == "profile_completion"
        return {
            "profile_id": "test-profile-id",
            "profile_data": {
                "full_name": "John Doe",
                "email": "john.doe@example.com",
            },
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "fallback_used": False,
            "total_processing_time_ms": 100,
            "received": kwargs,
        }

    monkeypatch.setattr(
        "app.api.profiles._profile_service.parse_and_create_profile",
        fake_parse_and_create_profile,
    )

    files = {"file": ("cv.pdf", b"dummy pdf bytes", "application/pdf")}
    data = {
        "intent": "profile_completion",
        "document_type": "cv",
        "run_gap_analysis": "false",
    }

    response = client.post(
        "/api/v1/profiles/parse-upload",
        headers={**internal_token_header, "X-User-ID": "user-1"},
        data=data,
        files=files,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["profile_id"] == "test-profile-id"
    assert payload["data"]["received"]["file_name"] == "cv.pdf"
    assert payload["data"]["received"]["document_type"] == "cv"
    assert payload["data"]["received"]["run_gap_analysis"] is False


def test_parse_upload_accepts_optional_user_id(client, monkeypatch, internal_token_header):
    async def fake_parse_and_create_profile(**kwargs):
        assert kwargs["intent"] == "profile_completion"
        return {
            "profile_id": "test-profile-id-2",
            "profile_data": {},
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "fallback_used": False,
            "total_processing_time_ms": 100,
            "received": kwargs,
        }

    monkeypatch.setattr(
        "app.api.profiles._profile_service.parse_and_create_profile",
        fake_parse_and_create_profile,
    )

    files = {"file": ("cv.pdf", b"dummy pdf bytes", "application/pdf")}
    data = {
        "user_id": "legacy-user-id",
        "intent": "profile_completion",
        "document_type": "cv",
    }

    response = client.post(
        "/api/v1/profiles/parse-upload",
        headers={**internal_token_header, "X-User-ID": "legacy-user-id"},
        data=data,
        files=files,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["received"]["document_type"] == "cv"
    assert payload["data"]["received"]["run_gap_analysis"] is False


def test_parse_upload_requires_service_token(client):
    files = {"file": ("cv.pdf", b"dummy pdf bytes", "application/pdf")}
    data = {"user_id": "user-1", "document_type": "cv"}

    response = client.post(
        "/api/v1/profiles/parse-upload",
        data=data,
        files=files,
    )

    assert response.status_code == 401
