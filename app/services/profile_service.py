"""Profile orchestration — parse document → LLM extract → store."""

import json
import time
from typing import Any, Optional

from app.core.logging import get_logger
from app.repositories.mysql_document_repo import DocumentRepository
from app.repositories.mysql_profile_repo import ProfileRepository
from app.services.document_parser import DocumentParser
from app.services.llm_service import LLMService
from app.utils.exceptions import NotFoundError
from app.utils.file_utils import get_file_extension, get_mime_type

logger = get_logger(__name__)


class ProfileService:
    """High-level business logic for student profiles."""

    def __init__(self):
        self.profile_repo = ProfileRepository()
        self.document_repo = DocumentRepository()
        self.parser = DocumentParser()
        self.llm_service = LLMService()

    async def parse_and_create_profile(
        self,
        user_id: str,
        file_name: str,
        file_content_base64: str,
        document_type: str = "cv",
        target_degree_hint: Optional[str] = None,
    ) -> dict[str, Any]:
        """Full pipeline: decode → extract text → LLM parse → store profile + document."""
        overall_start = time.perf_counter()

        # 1. Extract text from document
        extraction = await self.parser.extract_text(file_content_base64, file_name)
        document_text = extraction["text"]

        if not document_text.strip():
            logger.warning("empty_document_text", file_name=file_name)

        # 2. LLM extraction
        llm_result = await self.llm_service.extract_profile(document_text, target_degree_hint)
        profile_data = llm_result.profile_data

        total_ms = int((time.perf_counter() - overall_start) * 1000)

        # 3. Store profile
        record = {
            **self._flatten_profile_for_db(profile_data),
            "profile_json": profile_data,
            "llm_model_used": llm_result.model,
            "llm_fallback_used": llm_result.fallback_used,
            "llm_fallback_reason": llm_result.fallback_reason,
            "total_processing_time_ms": total_ms,
        }
        profile_id = await self.profile_repo.create_profile(record)

        # 4. Store document metadata
        ext = get_file_extension(file_name)
        await self.document_repo.create_document(
            {
                "profile_id": profile_id,
                "document_type": document_type,
                "file_name": file_name,
                "file_extension": ext,
                "file_size_bytes": extraction["file_size_bytes"],
                "mime_type": get_mime_type(file_name),
                "file_hash": extraction["file_hash"],
                "extracted_text_length": extraction["extracted_text_length"],
                "ocr_used": extraction["ocr_used"],
                "extraction_method": extraction["extraction_method"],
                "extraction_time_ms": extraction["extraction_time_ms"],
            }
        )

        logger.info("profile_pipeline_completed", profile_id=profile_id, total_ms=total_ms)

        return {
            "profile_id": profile_id,
            "profile_data": profile_data,
            "llm_provider": llm_result.provider,
            "llm_model": llm_result.model,
            "fallback_used": llm_result.fallback_used,
            "total_processing_time_ms": total_ms,
        }

    async def get_profile(self, profile_id: str) -> dict[str, Any]:
        """Retrieve a profile by ID."""
        row = await self.profile_repo.get_profile_by_id(profile_id)
        if not row:
            raise NotFoundError("Profile")
        return self._deserialize_json_fields(row)

    async def list_profiles(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """Return a paginated list of profiles."""
        offset = (page - 1) * page_size
        items = await self.profile_repo.list_profiles(limit=page_size, offset=offset)
        total = await self.profile_repo.count_profiles()
        total_pages = (total + page_size - 1) // page_size
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    async def update_profile(self, profile_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update specific fields on a profile."""
        existing = await self.profile_repo.get_profile_by_id(profile_id)
        if not existing:
            raise NotFoundError("Profile")

        clean = {k: v for k, v in updates.items() if v is not None}
        if clean:
            await self.profile_repo.update_profile(profile_id, clean)

        return await self.get_profile(profile_id)

    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_profile_for_db(profile_data: dict) -> dict:
        """Map ExtractedProfile fields to the flat student_profiles columns."""
        return {
            "full_name": profile_data.get("full_name"),
            "email": profile_data.get("email"),
            "phone": profile_data.get("phone"),
            "nationality": profile_data.get("nationality"),
            "date_of_birth": profile_data.get("date_of_birth"),
            "target_degree_level": profile_data.get("target_degree_level", "unknown"),
            "target_degree_confidence": profile_data.get("target_degree_confidence"),
            "target_degree_source": profile_data.get("target_degree_source", "unknown"),
            "target_degree_needs_clarification": profile_data.get("target_degree_needs_clarification", False),
            "gpa": profile_data.get("gpa_highest"),
            "gpa_scale": profile_data.get("gpa_scale"),
            "confidence_map": profile_data.get("confidence_map", {}),
            "evidence_map": profile_data.get("evidence_map", {}),
            "contradiction_flags": profile_data.get("contradiction_flags", []),
            "missing_critical_fields": profile_data.get("missing_critical_fields", []),
            "clarification_queue": profile_data.get("clarification_queue", []),
        }

    @staticmethod
    def _deserialize_json_fields(row: dict) -> dict:
        """Parse JSON string columns back into Python objects."""
        json_keys = [
            "profile_json", "confidence_map", "evidence_map",
            "contradiction_flags", "missing_critical_fields", "clarification_queue",
        ]
        for key in json_keys:
            val = row.get(key)
            if isinstance(val, str):
                try:
                    row[key] = json.loads(val)
                except json.JSONDecodeError:
                    pass
        return row
