"""Gap analysis service — readiness scan against degree baselines."""

import json
from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_profile_repo import ProfileRepository
from app.services.llm_service import LLMService
from app.utils.exceptions import NotFoundError

logger = get_logger(__name__)


class GapAnalysisService:
    """Identifies readiness gaps for a student's target degree level."""

    def __init__(self):
        self.profile_repo = ProfileRepository()
        self.llm_service = LLMService()

    async def analyze(self, profile_id: str) -> dict[str, Any]:
        """Run gap analysis on an existing profile."""
        row = await self.profile_repo.get_profile_by_id(profile_id)
        if not row:
            raise NotFoundError("Profile")

        profile_json = row.get("profile_json")
        if isinstance(profile_json, str):
            profile_json = json.loads(profile_json)

        target_degree = row.get("target_degree_level", "unknown")
        if target_degree == "unknown":
            return {
                "readiness_score": None,
                "gaps_identified": [],
                "recommendations": [
                    {
                        "area": "target_degree",
                        "action": "Please specify your target degree level",
                        "priority": "high",
                    }
                ],
            }

        result = await self.llm_service.run_gap_analysis(profile_json, target_degree)
        logger.info("gap_analysis_completed", profile_id=profile_id)
        return result
