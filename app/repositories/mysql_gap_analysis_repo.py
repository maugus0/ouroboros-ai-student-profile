"""Data-access layer for the gap_analysis table (raw SQL, aiomysql)."""

import json
from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_base import MySQLBaseRepository
from app.utils.helpers import generate_uuid

logger = get_logger(__name__)


class GapAnalysisRepository(MySQLBaseRepository):
    """CRUD operations on the ``gap_analysis`` table."""

    async def create_analysis(self, analysis_data: dict[str, Any]) -> str:
        """Insert a gap analysis record and return its UUID."""
        analysis_id = generate_uuid()
        query = """
            INSERT INTO gap_analysis (
                id, profile_id, target_degree_level,
                readiness_score, gaps_identified, recommendations,
                baseline_template
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            analysis_id,
            analysis_data["profile_id"],
            analysis_data["target_degree_level"],
            analysis_data.get("readiness_score"),
            json.dumps(analysis_data.get("gaps_identified", [])),
            json.dumps(analysis_data.get("recommendations", [])),
            analysis_data.get("baseline_template"),
        )
        await self.execute_write(query, params)
        logger.info("gap_analysis_created", analysis_id=analysis_id, profile_id=analysis_data["profile_id"])
        return analysis_id

    async def get_latest_by_profile(self, profile_id: str) -> dict[str, Any] | None:
        """Retrieve the latest gap analysis result for a profile."""
        query = "SELECT * FROM gap_analysis WHERE profile_id = %s ORDER BY analyzed_at DESC LIMIT 1"
        return await self.execute_one(query, (profile_id,))
