"""Tests for the profile status API."""


def test_get_profile_status(client, monkeypatch, internal_token_header):
    async def fake_get_profile_status(user_id: str, intent: str | None = None):
        assert user_id == "test-user"
        assert intent == "program_discovery"
        return {
            "user_id": user_id,
            "profile_id": "profile-1",
            "completed": False,
            "missing_fields": ["email", "gpa"],
            "updated_at": None,
            "intent": intent,
        }

    monkeypatch.setattr("app.api.profiles._profile_service.get_profile_status", fake_get_profile_status)

    response = client.get(
        "/api/v1/profiles/status",
        headers={**internal_token_header, "X-User-ID": "test-user"},
        params={"intent": "program_discovery"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["user_id"] == "test-user"
    assert payload["profile_id"] == "profile-1"
    assert payload["completed"] is False
    assert payload["missing_fields"] == ["email", "gpa"]
    assert payload["intent"] == "program_discovery"


def test_get_profile_status_rejects_mismatched_header_and_jwt_sub(client, internal_token_header):
    response = client.get(
        "/api/v1/profiles/status",
        headers={**internal_token_header, "X-User-ID": "different-user"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "X-User-ID does not match token subject"


def test_sync_user_profile(client, monkeypatch, internal_token_header):
    async def fake_sync_user_profile(user_id: str, payload: dict):
        assert user_id == "user-123"
        assert payload == {"full_name": "Jane Doe", "email": "jane@example.com"}
        return {
            "user_id": user_id,
            "profile_id": "profile-1",
            "synced": True,
            "created": True,
            "applied_fields": ["full_name", "email"],
        }

    monkeypatch.setattr("app.api.profiles._profile_service.sync_user_profile", fake_sync_user_profile)

    response = client.post(
        "/api/v1/profiles/sync-user",
        headers={**internal_token_header, "X-User-ID": "user-123"},
        json={"full_name": "Jane Doe", "email": "jane@example.com"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["user_id"] == "user-123"
    assert payload["synced"] is True
    assert payload["created"] is True


def test_collect_from_chat(client, monkeypatch, internal_token_header):
    async def fake_collect_from_chat(
        user_id: str,
        fields: dict,
        extractions=None,
        extraction_telemetry=None,
        pending_clarification_fields=None,
        correction_fields=None,
        chat_id=None,
        message_id=None,
    ):
        assert user_id == "user-123"
        assert fields == {"target_degree_level": "master", "gpa": 3.8}
        assert extractions == {}
        assert extraction_telemetry == {}
        assert pending_clarification_fields == []
        assert correction_fields == []
        assert chat_id == "chat-1"
        assert message_id == "msg-1"
        return {
            "user_id": user_id,
            "profile_id": "profile-1",
            "applied_fields": ["target_degree_level", "gpa"],
            "readiness": {
                "user_id": user_id,
                "completed": False,
                "missing_fields": ["gpa_scale"],
                "updated_at": None,
            },
            "chat_context": {"chat_id": chat_id, "message_id": message_id},
        }

    monkeypatch.setattr("app.api.profiles._profile_service.collect_from_chat", fake_collect_from_chat)

    response = client.post(
        "/api/v1/profiles/collect-from-chat",
        headers={**internal_token_header, "X-User-ID": "user-123"},
        json={
            "fields": {"target_degree_level": "master", "gpa": 3.8},
            "chat_id": "chat-1",
            "message_id": "msg-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["user_id"] == "user-123"
    assert payload["profile_id"] == "profile-1"
    assert payload["readiness"]["missing_fields"] == ["gpa_scale"]
