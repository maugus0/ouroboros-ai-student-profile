"""Data-access layer for async gap analysis jobs."""

import json
from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_base import MySQLBaseRepository
from app.utils.helpers import generate_uuid

logger = get_logger(__name__)


class GapAnalysisJobRepository(MySQLBaseRepository):
    """CRUD operations on the ``gap_analysis_jobs`` table."""

    async def create_job(self, job_data: dict[str, Any]) -> str:
        job_id = generate_uuid()
        query = """
            INSERT INTO gap_analysis_jobs (id, profile_id, status, result_json, error_message)
            VALUES (%s, %s, %s, %s, %s)
        """
        params = (
            job_id,
            job_data["profile_id"],
            job_data.get("status", "queued"),
            json.dumps(job_data.get("result_json")) if job_data.get("result_json") is not None else None,
            job_data.get("error_message"),
        )
        await self.execute_write(query, params)
        logger.info("gap_analysis_job_created", job_id=job_id, profile_id=job_data["profile_id"], status=job_data.get("status", "queued"))
        return job_id

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        query = "SELECT * FROM gap_analysis_jobs WHERE id = %s"
        row = await self.execute_one(query, (job_id,))
        if row and isinstance(row.get("result_json"), str):
            try:
                row["result_json"] = json.loads(row["result_json"])
            except json.JSONDecodeError:
                pass
        return row

    async def update_job(self, job_id: str, updates: dict[str, Any]) -> int:
        if not updates:
            return 0

        set_clauses = []
        params = []
        for key, value in updates.items():
            set_clauses.append(f"{key} = %s")
            if key == "result_json" and value is not None:
                params.append(json.dumps(value))
            else:
                params.append(value)

        params.append(job_id)
        query = f"UPDATE gap_analysis_jobs SET {', '.join(set_clauses)} WHERE id = %s"
        return await self.execute_write(query, tuple(params))
