"""Data-access layer for normalized profile tables."""

import json
from typing import Any

from app.repositories.mysql_base import MySQLBaseRepository
from app.utils.helpers import generate_uuid


class ProfileNormalizedRepository(MySQLBaseRepository):
    """CRUD helpers for extracted_skills, education_entries, experience_entries, profile_versions."""

    async def replace_extracted_skills(self, profile_id: str, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO extracted_skills (
                id, profile_id, raw_skill, normalized_skill,
                confidence_score, source_document_id
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """
        params_list = [
            (
                generate_uuid(),
                profile_id,
                row["raw_skill"],
                row["normalized_skill"],
                row.get("confidence_score"),
                row.get("source_document_id"),
            )
            for row in rows
        ]
        await self._replace_rows_transactional(
            delete_query="DELETE FROM extracted_skills WHERE profile_id = %s",
            profile_id=profile_id,
            insert_query=query,
            insert_params=params_list,
        )

    async def get_skills_by_profile(self, profile_id: str) -> list[dict[str, Any]]:
        """Fetch normalized skills for a profile ordered for stable API responses."""
        query = """
            SELECT raw_skill, normalized_skill, confidence_score, created_at
            FROM extracted_skills
            WHERE profile_id = %s
            ORDER BY normalized_skill ASC
        """
        return await self.execute_query(query, (profile_id,))

    async def replace_education_entries(self, profile_id: str, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO education_entries (
                id, profile_id, institution, degree, field_of_study,
                start_date, end_date, gpa, gpa_scale, achievements,
                evidence_snippet, confidence_score, source_document_id, sort_index,
                entry_fingerprint
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params_list = [
            (
                generate_uuid(),
                profile_id,
                row["institution"],
                row["degree"],
                row.get("field_of_study"),
                row.get("start_date"),
                row.get("end_date"),
                row.get("gpa"),
                row.get("gpa_scale"),
                json.dumps(row.get("achievements") or []),
                row.get("evidence_snippet"),
                row.get("confidence_score"),
                row.get("source_document_id"),
                row.get("sort_index", 0),
                row.get("entry_fingerprint"),
            )
            for row in rows
        ]
        await self._replace_rows_transactional(
            delete_query="DELETE FROM education_entries WHERE profile_id = %s",
            profile_id=profile_id,
            insert_query=query,
            insert_params=params_list,
        )

    async def replace_experience_entries(self, profile_id: str, rows: list[dict[str, Any]]) -> None:
        query = """
            INSERT INTO experience_entries (
                id, profile_id, experience_type, organization, title, role,
                start_date, end_date, description, skills_used,
                publication_venue, evidence_snippet, confidence_score,
                source_document_id, sort_index, entry_fingerprint
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params_list = [
            (
                generate_uuid(),
                profile_id,
                row["experience_type"],
                row.get("organization"),
                row["title"],
                row.get("role"),
                row.get("start_date"),
                row.get("end_date"),
                row.get("description"),
                json.dumps(row.get("skills_used") or []),
                row.get("publication_venue"),
                row.get("evidence_snippet"),
                row.get("confidence_score"),
                row.get("source_document_id"),
                row.get("sort_index", 0),
                row.get("entry_fingerprint"),
            )
            for row in rows
        ]
        await self._replace_rows_transactional(
            delete_query="DELETE FROM experience_entries WHERE profile_id = %s",
            profile_id=profile_id,
            insert_query=query,
            insert_params=params_list,
        )

    async def create_profile_version_snapshot(
        self,
        profile_id: str,
        version_number: int,
        profile_json: dict[str, Any],
        change_reason: str,
    ) -> str:
        query = """
            INSERT INTO profile_versions (
                id, profile_id, version_number, profile_json, change_reason
            ) VALUES (%s, %s, %s, %s, %s)
        """
        version_id = generate_uuid()
        params = (
            version_id,
            profile_id,
            version_number,
            json.dumps(profile_json or {}),
            change_reason,
        )
        await self.execute_write(query, params)
        return version_id

    async def get_latest_profile_version(self, profile_id: str) -> dict[str, Any] | None:
        """Fetch the latest (highest version_number) profile snapshot."""
        query = """
            SELECT * FROM profile_versions
            WHERE profile_id = %s
            ORDER BY version_number DESC
            LIMIT 1
        """
        row = await self.execute_one(query, (profile_id,))
        if row and isinstance(row.get("profile_json"), str):
            try:
                row["profile_json"] = json.loads(row["profile_json"])
            except (json.JSONDecodeError, TypeError):
                row["profile_json"] = {}
        return row
