"""Data-access layer for the profile_fields table (raw SQL, aiomysql)."""

import json
from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_base import MySQLBaseRepository
from app.utils.helpers import generate_uuid

logger = get_logger(__name__)


class FieldRepository(MySQLBaseRepository):
    """CRUD operations on the ``profile_fields`` table for granular field updates."""

    async def create_field(self, field_data: dict[str, Any]) -> str:
        """Insert a profile field record and return its UUID."""
        field_id = generate_uuid()
        query = """
            INSERT INTO profile_fields (
                id, profile_id, field_category, field_name, field_value,
                confidence_score, evidence_snippet, source_document_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            field_id,
            field_data["profile_id"],
            field_data["field_category"],
            field_data["field_name"],
            json.dumps(field_data["field_value"]),
            field_data.get("confidence_score"),
            field_data.get("evidence_snippet"),
            field_data.get("source_document_id"),
        )
        await self.execute_write(query, params)
        return field_id

    async def get_fields_by_profile(self, profile_id: str, category: str | None = None) -> list[dict[str, Any]]:
        """Retrieve fields for a profile, optionally filtered by category."""
        if category:
            query = "SELECT * FROM profile_fields WHERE profile_id = %s AND field_category = %s ORDER BY field_name"
            return await self.execute_query(query, (profile_id, category))

        query = "SELECT * FROM profile_fields WHERE profile_id = %s ORDER BY field_category, field_name"
        return await self.execute_query(query, (profile_id,))

    async def update_field(self, field_id: str, updates: dict[str, Any]) -> int:
        """Update a single profile field."""
        if not updates:
            return 0

        set_clauses = []
        params = []
        for key, value in updates.items():
            set_clauses.append(f"{key} = %s")
            params.append(json.dumps(value) if key == "field_value" else value)

        params.append(field_id)
        query = f"UPDATE profile_fields SET {', '.join(set_clauses)} WHERE id = %s"
        return await self.execute_write(query, tuple(params))

    async def delete_fields_by_profile(self, profile_id: str) -> int:
        """Delete all fields belonging to a profile."""
        query = "DELETE FROM profile_fields WHERE profile_id = %s"
        return await self.execute_write(query, (profile_id,))
