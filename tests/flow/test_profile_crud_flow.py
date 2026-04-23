"""Flow tests for profile CRUD and separated skills/gaps views."""

from datetime import datetime, timezone


def test_profile_crud_and_split_views(client, monkeypatch, internal_token_header):
    profile_id = "profile-123"
    updated_time = datetime.now(timezone.utc).isoformat()

    async def fake_get_profile(pid: str):
        assert pid == profile_id
        return {
            "id": profile_id,
            "full_name": "Jane Student",
            "email": "jane@student.com",
            "profile_json": {"technical_skills": ["Python", "SQL"]},
            "updated_at": updated_time,
        }

    async def fake_update_profile(pid: str, updates: dict):
        assert pid == profile_id
        return {
            "id": profile_id,
            "full_name": updates.get("full_name", "Jane Student"),
            "email": "jane@student.com",
            "gpa": updates.get("gpa"),
            "gpa_scale": updates.get("gpa_scale"),
            "updated_at": updated_time,
        }

    async def fake_get_profile_skills(pid: str):
        assert pid == profile_id
        return {
            "profile_id": profile_id,
            "skills": [
                {
                    "raw_skill": "Python",
                    "normalized_skill": "python",
                    "confidence_score": 0.92,
                },
                {
                    "raw_skill": "SQL",
                    "normalized_skill": "sql",
                    "confidence_score": 0.92,
                },
            ],
            "total": 2,
        }

    async def fake_get_latest_analysis(pid: str):
        assert pid == profile_id
        return {
            "analysis_id": "gap-1",
            "profile_id": profile_id,
            "target_degree_level": "master",
            "readiness_score": 0.71,
            "gaps_identified": [{"category": "research", "status": "missing"}],
            "recommendations": [{"area": "research", "action": "add one publication"}],
        }

    monkeypatch.setattr("app.api.profiles._profile_service.get_profile", fake_get_profile)
    monkeypatch.setattr("app.api.profiles._profile_service.update_profile", fake_update_profile)
    monkeypatch.setattr("app.api.profiles._profile_service.get_profile_skills", fake_get_profile_skills)
    monkeypatch.setattr("app.api.profiles._gap_service.get_latest_analysis", fake_get_latest_analysis)

    get_resp = client.get(f"/api/v1/profiles/{profile_id}", headers=internal_token_header)
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["id"] == profile_id

    put_resp = client.put(
        f"/api/v1/profiles/{profile_id}",
        headers=internal_token_header,
        json={"full_name": "Jane Updated", "gpa": 3.8, "gpa_scale": 4.0},
    )
    assert put_resp.status_code == 200
    put_data = put_resp.json()["data"]
    assert put_data["full_name"] == "Jane Updated"
    assert put_data["updated_at"] == updated_time

    skills_resp = client.get(f"/api/v1/profiles/{profile_id}/skills", headers=internal_token_header)
    assert skills_resp.status_code == 200
    skills_data = skills_resp.json()["data"]
    assert skills_data["total"] == 2
    assert skills_data["skills"][0]["normalized_skill"] == "python"

    gaps_resp = client.get(f"/api/v1/profiles/{profile_id}/gaps", headers=internal_token_header)
    assert gaps_resp.status_code == 200
    gaps_data = gaps_resp.json()["data"]
    assert gaps_data["profile_id"] == profile_id
    assert gaps_data["gaps_identified"][0]["status"] == "missing"


def test_put_profile_rejects_invalid_payload(client, internal_token_header):
    response = client.put(
        "/api/v1/profiles/profile-123",
        headers=internal_token_header,
        json={"gpa": 4.5, "gpa_scale": 4.0},
    )

    assert response.status_code == 422
