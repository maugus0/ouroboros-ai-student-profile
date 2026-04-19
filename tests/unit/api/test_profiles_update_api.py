"""Unit tests for profile update API behavior."""


def test_patch_profile_merges_updates_into_snapshot_and_recomputes_queue(client, monkeypatch, service_token_header):
    captured = {"snapshot": None}

    class _StubProfileRepo:
        def __init__(self):
            self.updated = None

        async def get_profile_by_id(self, _profile_id):
            return {"id": "p1", "profile_version": 1}

        async def update_profile(self, _profile_id, updates):
            self.updated = updates
            return 1

    class _StubNormalizedRepo:
        async def get_latest_profile_version(self, _profile_id):
            return {
                "profile_json": {
                    "full_name": "Jane Doe",
                    "current_degree_level": "bachelor",
                    "target_degree_level": "master",
                    "confidence_map": {"target_degree_level": 0.4},
                    "clarification_queue": [],
                }
            }

        async def create_profile_version_snapshot(self, profile_id, version_number, profile_json, change_reason):
            captured["snapshot"] = {
                "profile_id": profile_id,
                "version_number": version_number,
                "profile_json": profile_json,
                "change_reason": change_reason,
            }
            return "ver-2"

    async def _fake_get_profile(_profile_id):
        return {"id": "p1", "profile_version": 2}

    monkeypatch.setattr("app.api.profiles._profile_service.profile_repo", _StubProfileRepo())
    monkeypatch.setattr("app.api.profiles._profile_service.normalized_repo", _StubNormalizedRepo())
    monkeypatch.setattr("app.api.profiles._profile_service.get_profile", _fake_get_profile)

    response = client.patch(
        "/api/v1/profiles/p1",
        headers=service_token_header,
        json={"target_degree_level": "phd", "gpa": 3.95},
    )

    assert response.status_code == 200
    assert response.json()["data"]["profile_version"] == 2

    assert captured["snapshot"] is not None
    profile_json = captured["snapshot"]["profile_json"]
    assert captured["snapshot"]["change_reason"] == "profile_update"
    assert profile_json["target_degree_level"] == "phd"
    assert profile_json["gpa"] == 3.95
    assert profile_json["target_degree_source"] == "user_input"
    assert profile_json["target_degree_confidence"] == 1.0
    assert profile_json["confidence_map"]["target_degree_level"] == 1.0
    assert profile_json["confidence_map"]["gpa"] == 1.0

    queue_fields = {item["field"] for item in profile_json["clarification_queue"]}
    assert "publications" in queue_fields
