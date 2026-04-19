"""Data-access layer for async gap analysis jobs."""

import json
from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_base import MySQLBaseRepository
from app.utils.helpers import generate_uuid

logger = get_logger(__name__)

GAP_JOB_UPDATE_COLUMNS: tuple[str, ...] = (
    "status",
    "result_json",
    "error_message",
    "started_at",
    "completed_at",
)


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
        logger.info(
            "gap_analysis_job_created",
            job_id=job_id,
            profile_id=job_data["profile_id"],
            status=job_data.get("status", "queued"),
        )
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
        allowed_updates = {key: value for key, value in updates.items() if key in GAP_JOB_UPDATE_COLUMNS}
        if not allowed_updates:
            return 0

        query = """
            UPDATE gap_analysis_jobs SET
                status = CASE WHEN %s THEN %s ELSE status END,
                result_json = CASE WHEN %s THEN %s ELSE result_json END,
                error_message = CASE WHEN %s THEN %s ELSE error_message END,
                started_at = CASE WHEN %s THEN %s ELSE started_at END,
                completed_at = CASE WHEN %s THEN %s ELSE completed_at END
            WHERE id = %s
        """
        params: list[Any] = []
        for column in GAP_JOB_UPDATE_COLUMNS:
            value_present = column in allowed_updates
            value = allowed_updates.get(column)
            if column == "result_json" and value_present and value is not None:
                value = json.dumps(value)
            params.extend([value_present, value])

        params.append(job_id)
        return await self.execute_write(query, tuple(params))
