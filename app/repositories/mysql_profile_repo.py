"""Data-access layer for the student_profiles table (raw SQL, aiomysql)."""

import json
from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_base import MySQLBaseRepository
from app.utils.helpers import generate_uuid, get_current_time_iso

logger = get_logger(__name__)


class ProfileRepository(MySQLBaseRepository):
    """CRUD operations on the ``student_profiles`` table."""

    async def create_profile(self, profile_data: dict[str, Any]) -> str:
        """Insert a new student profile and return its UUID."""
        profile_id = generate_uuid()
        query = """
            INSERT INTO student_profiles (
                id, full_name, email, phone, nationality, date_of_birth,
                current_degree_level, target_degree_level,
                target_degree_confidence, target_degree_source,
                target_degree_needs_clarification,
                gpa, gpa_scale, gpa_normalized, gpa_confidence,
                profile_json, confidence_map, evidence_map,
                contradiction_flags, missing_critical_fields, clarification_queue,
                llm_model_used, llm_fallback_used, llm_fallback_reason,
                total_processing_time_ms
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
        """
        params = (
            profile_id,
            profile_data.get("full_name"),
            profile_data.get("email"),
            profile_data.get("phone"),
            profile_data.get("nationality"),
            profile_data.get("date_of_birth"),
            profile_data.get("current_degree_level", "unknown"),
            profile_data.get("target_degree_level", "unknown"),
            profile_data.get("target_degree_confidence"),
            profile_data.get("target_degree_source", "unknown"),
            profile_data.get("target_degree_needs_clarification", False),
            profile_data.get("gpa"),
            profile_data.get("gpa_scale"),
            profile_data.get("gpa_normalized"),
            profile_data.get("gpa_confidence"),
            json.dumps(profile_data.get("profile_json", {})),
            json.dumps(profile_data.get("confidence_map", {})),
            json.dumps(profile_data.get("evidence_map", {})),
            json.dumps(profile_data.get("contradiction_flags", [])),
            json.dumps(profile_data.get("missing_critical_fields", [])),
            json.dumps(profile_data.get("clarification_queue", [])),
            profile_data.get("llm_model_used"),
            profile_data.get("llm_fallback_used", False),
            profile_data.get("llm_fallback_reason"),
            profile_data.get("total_processing_time_ms"),
        )
        await self.execute_write(query, params)
        logger.info("profile_created", profile_id=profile_id)
        return profile_id

    async def get_profile_by_id(self, profile_id: str) -> dict[str, Any] | None:
        """Retrieve a single profile by UUID."""
        query = "SELECT * FROM student_profiles WHERE id = %s"
        return await self.execute_one(query, (profile_id,))

    async def get_profile_by_email(self, email: str) -> dict[str, Any] | None:
        """Retrieve a profile by email address."""
        query = "SELECT * FROM student_profiles WHERE email = %s"
        return await self.execute_one(query, (email,))

    async def list_profiles(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """Return a paginated list of profiles."""
        query = "SELECT * FROM student_profiles ORDER BY created_at DESC LIMIT %s OFFSET %s"
        return await self.execute_query(query, (limit, offset))

    async def count_profiles(self) -> int:
        """Return the total number of profiles."""
        result = await self.execute_one("SELECT COUNT(*) AS total FROM student_profiles")
        return result["total"] if result else 0

    async def update_profile(self, profile_id: str, updates: dict[str, Any]) -> int:
        """Update specific fields on a profile."""
        if not updates:
            return 0

        json_fields = {
            "profile_json", "confidence_map", "evidence_map",
            "contradiction_flags", "missing_critical_fields", "clarification_queue",
        }

        set_clauses = []
        params = []
        for key, value in updates.items():
            set_clauses.append(f"{key} = %s")
            params.append(json.dumps(value) if key in json_fields else value)

        params.append(profile_id)
        query = f"UPDATE student_profiles SET {', '.join(set_clauses)} WHERE id = %s"
        rows = await self.execute_write(query, tuple(params))
        logger.info("profile_updated", profile_id=profile_id, fields=list(updates.keys()))
        return rows

    async def delete_profile(self, profile_id: str) -> int:
        """Delete a profile by UUID (cascades to documents, fields, etc.)."""
        query = "DELETE FROM student_profiles WHERE id = %s"
        return await self.execute_write(query, (profile_id,))
