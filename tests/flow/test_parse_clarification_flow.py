"""Flow test: simulate parse -> clarification resolution through API endpoints."""


class _FakeFlowProfileService:
    """In-memory profile service stub for orchestratorless flow simulation."""

    def __init__(self):
        self._profiles = {}

    async def parse_and_create_profile(
        self,
        user_id: str,
        file_name: str,
        file_content_base64: str,
        intent: str | None = None,
        document_type: str = "cv",
        target_degree_hint: str | None = None,
        run_gap_analysis: bool = True,
    ):
        profile_id = "sim-profile-1"
        self._profiles[profile_id] = {
            "profile_id": profile_id,
            "user_id": user_id,
            "profile_data": {
                "full_name": "John Doe",
                "email": "john.doe@example.com",
                "target_degree_level": None,
                "clarification_queue": [
                    {"field": "target_degree_level", "question": "What is your target degree level?"},
                    {"field": "research_interests", "question": "What are your research interests?"},
                ],
            },
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "fallback_used": False,
            "total_processing_time_ms": 123,
            "file_name": file_name,
            "document_type": document_type,
            "target_degree_hint": target_degree_hint,
            "run_gap_analysis": run_gap_analysis,
            "file_content_base64": file_content_base64,
            "intent": intent,
        }
        return self._profiles[profile_id]

    async def get_clarifications(self, profile_id: str):
        profile = self._profiles[profile_id]["profile_data"]
        queue = profile.get("clarification_queue", [])
        return {
            "profile_id": profile_id,
            "status": "needs_clarification" if queue else "analysis_ready",
            "clarification_queue": queue,
        }

    async def submit_clarifications(self, profile_id: str, answers: list[dict]):
        profile = self._profiles[profile_id]["profile_data"]
        answer_map = {item["field"]: item["value"] for item in answers}

        for field, value in answer_map.items():
            profile[field] = value

        profile["clarification_queue"] = [
            item for item in profile.get("clarification_queue", []) if item.get("field") not in answer_map
        ]

        return {
            "profile_id": profile_id,
            "applied_fields": list(answer_map.keys()),
            "clarification_queue": profile["clarification_queue"],
            "status": "analysis_ready" if not profile["clarification_queue"] else "needs_clarification",
        }


def test_parse_then_resolve_clarification_flow(client, monkeypatch, service_token_header):
    fake_service = _FakeFlowProfileService()
    monkeypatch.setattr("app.api.profiles._profile_service", fake_service)

    # 1) Simulate parse call from orchestrator.
    parse_resp = client.post(
        "/api/v1/profiles/parse",
        headers={**service_token_header, "X-User-ID": "user-1"},
        json={
            "file_name": "cv.pdf",
            "file_content_base64": "aGVsbG8=",
            "document_type": "cv",
        },
    )
    assert parse_resp.status_code == 200
    parse_payload = parse_resp.json()["data"]
    profile_id = parse_payload["profile_id"]

    # 2) Get clarification queue.
    clar_resp = client.get(f"/api/v1/profiles/{profile_id}/clarifications", headers=service_token_header)
    assert clar_resp.status_code == 200
    clar_data = clar_resp.json()["data"]
    assert clar_data["status"] == "needs_clarification"
    assert len(clar_data["clarification_queue"]) == 2

    # 3) Submit clarification answers.
    submit_resp = client.post(
        f"/api/v1/profiles/{profile_id}/clarifications",
        headers=service_token_header,
        json={
            "answers": [
                {"field": "target_degree_level", "value": "master"},
                {"field": "research_interests", "value": ["machine learning", "data systems"]},
            ]
        },
    )
    assert submit_resp.status_code == 200
    submit_data = submit_resp.json()["data"]
    assert submit_data["status"] == "analysis_ready"
    assert submit_data["clarification_queue"] == []

    # 4) Confirm readiness after submission.
    clar_resp_after = client.get(f"/api/v1/profiles/{profile_id}/clarifications", headers=service_token_header)
    assert clar_resp_after.status_code == 200
    clar_data_after = clar_resp_after.json()["data"]
    assert clar_data_after["status"] == "analysis_ready"
    assert clar_data_after["clarification_queue"] == []
