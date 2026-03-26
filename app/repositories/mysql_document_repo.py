"""Data-access layer for the documents table (raw SQL, aiomysql)."""

from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_base import MySQLBaseRepository
from app.utils.helpers import generate_uuid

logger = get_logger(__name__)


class DocumentRepository(MySQLBaseRepository):
    """CRUD operations on the ``documents`` table."""

    async def create_document(self, doc_data: dict[str, Any]) -> str:
        """Insert a document metadata record and return its UUID."""
        doc_id = generate_uuid()
        query = """
            INSERT INTO documents (
                id, profile_id, document_type, file_name, file_extension,
                file_size_bytes, mime_type, file_path, file_hash,
                extracted_text_length, ocr_used, extraction_method, extraction_time_ms
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            doc_id,
            doc_data["profile_id"],
            doc_data.get("document_type", "unknown"),
            doc_data["file_name"],
            doc_data["file_extension"],
            doc_data["file_size_bytes"],
            doc_data.get("mime_type"),
            doc_data.get("file_path"),
            doc_data.get("file_hash"),
            doc_data.get("extracted_text_length"),
            doc_data.get("ocr_used", False),
            doc_data.get("extraction_method", "unknown"),
            doc_data.get("extraction_time_ms"),
        )
        await self.execute_write(query, params)
        logger.info("document_created", document_id=doc_id, profile_id=doc_data["profile_id"])
        return doc_id

    async def get_document_by_id(self, document_id: str) -> dict[str, Any] | None:
        """Retrieve a single document by UUID."""
        query = "SELECT * FROM documents WHERE id = %s"
        return await self.execute_one(query, (document_id,))

    async def get_documents_by_profile(self, profile_id: str) -> list[dict[str, Any]]:
        """Retrieve all documents belonging to a profile."""
        query = "SELECT * FROM documents WHERE profile_id = %s ORDER BY created_at DESC"
        return await self.execute_query(query, (profile_id,))

    async def delete_document(self, document_id: str) -> int:
        """Delete a document record by UUID."""
        query = "DELETE FROM documents WHERE id = %s"
        return await self.execute_write(query, (document_id,))
