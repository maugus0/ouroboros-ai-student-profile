"""Data-access layer for the student_profiles table (raw SQL, aiomysql)."""

from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_base import MySQLBaseRepository
from app.utils.helpers import generate_uuid

logger = get_logger(__name__)

PROFILE_UPDATE_COLUMNS: tuple[str, ...] = (
    "full_name",
    "email",
    "phone",
    "nationality",
    "date_of_birth",
    "current_degree_level",
    "target_degree_level",
    "target_degree_confidence",
    "target_degree_source",
    "target_degree_needs_clarification",
    "gpa",
    "gpa_scale",
    "gpa_normalized",
    "gpa_confidence",
    "profile_version",
    "profile_prompt_version",
    "llm_model_used",
    "llm_fallback_used",
    "llm_fallback_reason",
    "total_processing_time_ms",
)


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
                profile_version, profile_prompt_version,
                llm_model_used, llm_fallback_used, llm_fallback_reason,
                total_processing_time_ms
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
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
            profile_data.get("profile_version", 1),
            profile_data.get("profile_prompt_version"),
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
        allowed_updates = {key: value for key, value in updates.items() if key in PROFILE_UPDATE_COLUMNS}
        if not allowed_updates:
            return 0

        query = """
            UPDATE student_profiles SET
                full_name = CASE WHEN %s THEN %s ELSE full_name END,
                email = CASE WHEN %s THEN %s ELSE email END,
                phone = CASE WHEN %s THEN %s ELSE phone END,
                nationality = CASE WHEN %s THEN %s ELSE nationality END,
                date_of_birth = CASE WHEN %s THEN %s ELSE date_of_birth END,
                current_degree_level = CASE WHEN %s THEN %s ELSE current_degree_level END,
                target_degree_level = CASE WHEN %s THEN %s ELSE target_degree_level END,
                target_degree_confidence = CASE WHEN %s THEN %s ELSE target_degree_confidence END,
                target_degree_source = CASE WHEN %s THEN %s ELSE target_degree_source END,
                target_degree_needs_clarification = CASE WHEN %s THEN %s ELSE target_degree_needs_clarification END,
                gpa = CASE WHEN %s THEN %s ELSE gpa END,
                gpa_scale = CASE WHEN %s THEN %s ELSE gpa_scale END,
                gpa_normalized = CASE WHEN %s THEN %s ELSE gpa_normalized END,
                gpa_confidence = CASE WHEN %s THEN %s ELSE gpa_confidence END,
                profile_version = CASE WHEN %s THEN %s ELSE profile_version END,
                profile_prompt_version = CASE WHEN %s THEN %s ELSE profile_prompt_version END,
                llm_model_used = CASE WHEN %s THEN %s ELSE llm_model_used END,
                llm_fallback_used = CASE WHEN %s THEN %s ELSE llm_fallback_used END,
                llm_fallback_reason = CASE WHEN %s THEN %s ELSE llm_fallback_reason END,
                total_processing_time_ms = CASE WHEN %s THEN %s ELSE total_processing_time_ms END
            WHERE id = %s
        """
        params: list[Any] = []
        for column in PROFILE_UPDATE_COLUMNS:
            value_present = column in allowed_updates
            params.extend([value_present, allowed_updates.get(column)])

        params.append(profile_id)
        rows = await self.execute_write(query, tuple(params))
        logger.info("profile_updated", profile_id=profile_id, fields=list(allowed_updates.keys()))
        return rows

    async def delete_profile(self, profile_id: str) -> int:
        """Delete a profile by UUID (cascades to documents, fields, etc.)."""
        query = "DELETE FROM student_profiles WHERE id = %s"
        return await self.execute_write(query, (profile_id,))
