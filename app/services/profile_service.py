"""Profile orchestration - parse document -> LLM extract -> store."""

import time
from datetime import date
from typing import Any, Optional

from app.core.logging import get_logger
from app.repositories.mysql_document_repo import DocumentRepository
from app.repositories.mysql_profile_normalized_repo import ProfileNormalizedRepository
from app.repositories.mysql_profile_repo import ProfileRepository
from app.services.profile_clarification_engine import apply_react_decision_pattern
from app.services.profile_data_builders import (
    build_education_entries,
    build_experience_entries,
    build_normalized_skills,
    build_profile_fields,
    entry_fingerprint,
    normalize_skill_name,
)
from app.services.profile_value_utils import (
    coerce_top_level_value,
    normalize_degree_level_value,
    normalize_field_name,
    parse_date_text,
    parse_gpa_value,
)
from app.services.document_parser import DocumentParser
from app.services.gap_analysis_service import GapAnalysisService
from app.services.llm_service import LLMService
from app.utils.exceptions import NotFoundError
from app.utils.file_utils import get_file_extension, get_mime_type

logger = get_logger(__name__)


class ProfileService:
    """High-level business logic for student profiles."""

    def __init__(
        self,
        profile_repo: ProfileRepository | None = None,
        document_repo: DocumentRepository | None = None,
        normalized_repo: ProfileNormalizedRepository | None = None,
        parser: DocumentParser | None = None,
        llm_service: LLMService | None = None,
        gap_service: GapAnalysisService | None = None,
    ):
        self.profile_repo = profile_repo or ProfileRepository()
        self.document_repo = document_repo or DocumentRepository()
        self.normalized_repo = normalized_repo or ProfileNormalizedRepository()
        self.parser = parser or DocumentParser()
        self.llm_service = llm_service or LLMService()
        self.gap_service = gap_service or GapAnalysisService()

    async def parse_and_create_profile(
        self,
        file_name: str,
        file_content_base64: str,
        document_type: str = "cv",
        target_degree_hint: Optional[str] = None,
    ) -> dict[str, Any]:
        """Full pipeline: decode → extract text → LLM parse → store profile + document."""
        overall_start = time.perf_counter()
        logger.info(
            "profile_parse_started",
            file_name=file_name,
            document_type=document_type,
        )

        # 1. Extract text from document
        extraction = await self.parser.extract_text(file_content_base64, file_name)
        document_text = extraction["text"]

        if not document_text.strip():
            logger.warning("empty_document_text", file_name=file_name)

        # 2. LLM extraction
        llm_result = await self.llm_service.extract_profile(document_text, target_degree_hint)
        profile_data = dict(llm_result.profile_data or {})
        # Apply ReAct decision pattern to evaluate all fields and derive clarification queue
        profile_data = self._apply_react_decision_pattern(profile_data)

        total_ms = int((time.perf_counter() - overall_start) * 1000)

        # 3. Store lean profile record (scalar columns only; full state in profile_versions)
        record = {
            **self._flatten_profile_for_db(profile_data),
            "profile_version": 1,
            "profile_prompt_version": "profile_extraction_v2",
            "llm_model_used": llm_result.model,
            "llm_fallback_used": llm_result.fallback_used,
            "llm_fallback_reason": llm_result.fallback_reason,
            "total_processing_time_ms": total_ms,
        }
        profile_id = await self.profile_repo.create_profile(record)

        # 4. Store document metadata
        ext = get_file_extension(file_name)
        document_id = await self.document_repo.create_document(
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

        # 5. Persist normalized rows for direct querying + version snapshot
        # (profile_fields table no longer used; profile_versions is authoritative JSON source)
        try:
            skill_rows = self._build_normalized_skills(
                source_document_id=document_id,
                profile_data=profile_data,
            )
            education_rows = self._build_education_entries(
                source_document_id=document_id,
                profile_data=profile_data,
            )
            experience_rows = self._build_experience_entries(
                source_document_id=document_id,
                profile_data=profile_data,
            )
            await self.normalized_repo.replace_extracted_skills(profile_id, skill_rows)
            await self.normalized_repo.replace_education_entries(profile_id, education_rows)
            await self.normalized_repo.replace_experience_entries(profile_id, experience_rows)
            await self.normalized_repo.create_profile_version_snapshot(
                profile_id=profile_id,
                version_number=1,
                profile_json=profile_data,
                change_reason="initial_parse",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("normalized_profile_persist_failed", profile_id=profile_id, error=str(exc))

        gap_analysis: dict[str, Any] | None = None
        # 6. Skill gaps are identified automatically right after extraction.
        try:
            gap_analysis = await self.gap_service.analyze(profile_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("automatic_gap_analysis_failed", profile_id=profile_id, error=str(exc))

        logger.info("profile_pipeline_completed", profile_id=profile_id, total_ms=total_ms)

        return {
            "profile_id": profile_id,
            "profile_data": profile_data,
            "llm_provider": llm_result.provider,
            "llm_model": llm_result.model,
            "fallback_used": llm_result.fallback_used,
            "gap_analysis": gap_analysis,
            "total_processing_time_ms": total_ms,
        }

    async def get_profile(self, profile_id: str) -> dict[str, Any]:
        """Retrieve a profile by ID.

        Returns scalar columns from student_profiles and the latest profile_json
        snapshot from profile_versions (source of truth for full JSON state).
        """
        row = await self.profile_repo.get_profile_by_id(profile_id)
        if not row:
            raise NotFoundError("Profile")

        # Fetch latest version snapshot from profile_versions
        latest_version = await self.normalized_repo.get_latest_profile_version(profile_id)
        profile_json = {}
        if latest_version:
            profile_json = dict(latest_version.get("profile_json") or {})

        # Remove keys duplicated by top-level scalar columns to keep payload concise.
        compact_profile_json = {key: value for key, value in profile_json.items() if key not in row}

        # Keep response compact: expose profile_json once (no duplicated top-level mirrors).
        profile = {
            **row,
            "profile_json": compact_profile_json,
        }
        return profile

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
        """Update specific fields on a profile.

        Updates only scalar columns in student_profiles.
        Profile state (full JSON) is maintained in profile_versions.
        """
        existing = await self.profile_repo.get_profile_by_id(profile_id)
        if not existing:
            raise NotFoundError("Profile")

        clean = {k: v for k, v in updates.items() if v is not None}
        if clean:
            next_version = int(existing.get("profile_version") or 1) + 1
            clean["profile_version"] = next_version
            await self.profile_repo.update_profile(profile_id, clean)

            # Fetch latest version snapshot to use as base for next snapshot
            latest_version = await self.normalized_repo.get_latest_profile_version(profile_id)
            merged_profile_json = dict(latest_version.get("profile_json") or {}) if latest_version else {}

            # Merge incoming updates into the profile_json snapshot payload.
            snapshot_updates = {key: value for key, value in clean.items() if key != "profile_version"}
            if "gpa" in snapshot_updates:
                snapshot_updates["gpa_highest"] = snapshot_updates["gpa"]

            # PATCH/PUT updates are user input; reflect stronger provenance in snapshot metadata.
            if "target_degree_level" in snapshot_updates:
                snapshot_updates["target_degree_source"] = "user_input"
                snapshot_updates["target_degree_confidence"] = 1.0

            merged_profile_json.update(snapshot_updates)

            # Mark user-updated fields as high-confidence in snapshot confidence_map.
            confidence_map = (
                merged_profile_json.get("confidence_map")
                if isinstance(merged_profile_json.get("confidence_map"), dict)
                else {}
            )
            confidence_field_map = {
                "full_name": "full_name",
                "email": "email",
                "phone": "phone",
                "nationality": "nationality",
                "target_degree_level": "target_degree_level",
                "gpa": "gpa_highest",
                "gpa_scale": "gpa_scale",
            }
            for source_field, target_field in confidence_field_map.items():
                if source_field in snapshot_updates:
                    confidence_map[target_field] = 1.0
            if confidence_map:
                merged_profile_json["confidence_map"] = confidence_map

            # Keep clarification queue/trace consistent with latest snapshot values.
            snapshot_profile_json = self._apply_react_decision_pattern(merged_profile_json)
            clean["target_degree_needs_clarification"] = bool(
                snapshot_profile_json.get("target_degree_needs_clarification")
            )

            try:
                await self.normalized_repo.create_profile_version_snapshot(
                    profile_id=profile_id,
                    version_number=next_version,
                    profile_json=snapshot_profile_json,
                    change_reason="profile_update",
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("profile_version_snapshot_failed", profile_id=profile_id, error=str(exc))

        return await self.get_profile(profile_id)

    async def get_profile_skills(self, profile_id: str) -> dict[str, Any]:
        """Return normalized skills list for a profile."""
        row = await self.profile_repo.get_profile_by_id(profile_id)
        if not row:
            raise NotFoundError("Profile")

        skills = await self.normalized_repo.get_skills_by_profile(profile_id)
        return {
            "profile_id": profile_id,
            "skills": skills,
            "total": len(skills),
        }

    async def get_clarifications(self, profile_id: str) -> dict[str, Any]:
        """Return current clarification queue and readiness state."""
        row = await self.profile_repo.get_profile_by_id(profile_id)
        if not row:
            raise NotFoundError("Profile")

        # Fetch latest version snapshot from profile_versions (source of truth)
        latest_version = await self.normalized_repo.get_latest_profile_version(profile_id)
        profile_json = dict(latest_version.get("profile_json") or {}) if latest_version else {}

        # Re-apply ReAct decision pattern to regenerate both trace and queue from source data
        react_state = self._apply_react_decision_pattern(profile_json)
        queue = react_state.get("clarification_queue") or []
        react_decision_trace = react_state.get("react_decision_trace") or {}

        status = self._compute_profile_status(queue)

        return {
            "profile_id": profile_id,
            "status": status,
            "clarification_queue": queue,
            "react_decision_trace": react_decision_trace,
        }

    async def submit_clarifications(self, profile_id: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply clarification answers and update profile readiness state."""
        row = await self.profile_repo.get_profile_by_id(profile_id)
        if not row:
            raise NotFoundError("Profile")

        # Fetch latest version snapshot from profile_versions (source of truth)
        latest_version = await self.normalized_repo.get_latest_profile_version(profile_id)
        profile_json = dict(latest_version.get("profile_json") or {}) if latest_version else {}

        answer_map: dict[str, Any] = {}
        for item in answers:
            field = self._normalize_field_name(item.get("field"))
            if field:
                answer_map[field] = item.get("value")

        applied_fields: list[str] = []

        # Update profile data with clarification answers and mark them as high confidence
        confidence_map = (
            profile_json.get("confidence_map") if isinstance(profile_json.get("confidence_map"), dict) else {}
        )
        for field, value in answer_map.items():
            profile_json[field] = value
            confidence_map[field] = 1.0  # User-provided values are 100% confident
            applied_fields.append(field)

        if confidence_map:
            profile_json["confidence_map"] = confidence_map

        top_level_mapping = {
            "full_name": "full_name",
            "email": "email",
            "phone": "phone",
            "nationality": "nationality",
            "date_of_birth": "date_of_birth",
            "current_degree_level": "current_degree_level",
            "target_degree_level": "target_degree_level",
            "gpa_highest": "gpa",
            "gpa_scale": "gpa_scale",
        }

        # Re-apply ReAct decision pattern with updated profile data to regenerate react_decision_trace
        updated_profile_data = self._apply_react_decision_pattern(profile_json)
        updated_react_decision_trace = updated_profile_data.get("react_decision_trace") or {}
        updated_queue = updated_profile_data.get("clarification_queue") or []

        if "target_degree_level" in answer_map:
            # Clarification answers are user input and should override target-degree metadata.
            updated_profile_data["target_degree_source"] = "user_input"
            updated_profile_data["target_degree_confidence"] = 1.0
            updated_profile_data["target_degree_reasoning"] = "Provided via clarification answer"
        updated_profile_data["target_degree_needs_clarification"] = bool(
            updated_profile_data.get("target_degree_needs_clarification")
        )

        # Only update scalar columns in student_profiles; profile state lives in profile_versions
        next_version = int(row.get("profile_version") or 1) + 1
        updates: dict[str, Any] = {
            "target_degree_needs_clarification": bool(updated_profile_data.get("target_degree_needs_clarification")),
            "profile_version": next_version,
        }
        for source_field, target_field in top_level_mapping.items():
            if source_field in answer_map:
                if source_field == "gpa_highest":
                    parsed_gpa, inferred_scale = self._parse_gpa_value(answer_map[source_field])
                    if parsed_gpa is not None:
                        updates["gpa"] = parsed_gpa
                    if inferred_scale is not None and "gpa_scale" not in answer_map:
                        updates["gpa_scale"] = inferred_scale
                    continue
                coerced = self._coerce_top_level_value(source_field, answer_map[source_field])
                if coerced is not None:
                    updates[target_field] = coerced

        if "target_degree_level" in answer_map:
            updates["target_degree_source"] = "user_input"
            updates["target_degree_confidence"] = 1.0

        await self.profile_repo.update_profile(profile_id, updates)
        try:
            await self.normalized_repo.create_profile_version_snapshot(
                profile_id=profile_id,
                version_number=next_version,
                profile_json=updated_profile_data,
                change_reason="clarification_submit",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("profile_version_snapshot_failed", profile_id=profile_id, error=str(exc))

        status = self._compute_profile_status(updated_queue)
        return {
            "profile_id": profile_id,
            "applied_fields": applied_fields,
            "clarification_queue": updated_queue,
            "react_decision_trace": updated_react_decision_trace,
            "status": status,
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_profile_for_db(profile_data: dict) -> dict:
        """Map ExtractedProfile fields to the flat student_profiles columns (scalar only).

        Note: JSON fields (confidence_map, evidence_map, contradiction_flags, clarification_queue)
        are stored in profile_versions snapshots, not in student_profiles (lean storage model).
        """
        parsed_gpa, inferred_gpa_scale = ProfileService._parse_gpa_value(profile_data.get("gpa_highest"))
        gpa_scale = ProfileService._coerce_top_level_value("gpa_scale", profile_data.get("gpa_scale"))
        if gpa_scale is None:
            gpa_scale = inferred_gpa_scale

        return {
            "full_name": profile_data.get("full_name"),
            "email": profile_data.get("email"),
            "phone": profile_data.get("phone"),
            "nationality": profile_data.get("nationality"),
            "date_of_birth": profile_data.get("date_of_birth"),
            "current_degree_level": profile_data.get("current_degree_level", "unknown"),
            "target_degree_level": profile_data.get("target_degree_level", "unknown"),
            "target_degree_confidence": profile_data.get("target_degree_confidence"),
            "target_degree_source": profile_data.get("target_degree_source", "unknown"),
            "target_degree_needs_clarification": profile_data.get("target_degree_needs_clarification", False),
            "gpa": parsed_gpa,
            "gpa_scale": gpa_scale,
        }

    @staticmethod
    def _compute_profile_status(clarification_queue: list[Any]) -> str:
        if clarification_queue:
            return "needs_clarification"
        return "analysis_ready"

    @staticmethod
    def _coerce_top_level_value(field: str, value: Any) -> Any:
        return coerce_top_level_value(field, value)

    @staticmethod
    def _normalize_field_name(field: Any) -> str:
        return normalize_field_name(field)

    @staticmethod
    def _parse_gpa_value(value: Any) -> tuple[Optional[float], Optional[float]]:
        return parse_gpa_value(value)

    @staticmethod
    def _normalize_degree_level_value(field: str, value: Any) -> Optional[str]:
        return normalize_degree_level_value(field, value)

    @staticmethod
    def _parse_date_text(value: str) -> Optional[date]:
        return parse_date_text(value)

    @classmethod
    def _apply_react_decision_pattern(cls, profile_data: dict[str, Any]) -> dict[str, Any]:
        return apply_react_decision_pattern(profile_data)

    @staticmethod
    def _build_profile_fields(
        profile_id: str, source_document_id: str, profile_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return build_profile_fields(profile_id, source_document_id, profile_data)

    @staticmethod
    def _normalize_skill_name(skill: str) -> str:
        return normalize_skill_name(skill)

    @classmethod
    def _build_normalized_skills(cls, source_document_id: str, profile_data: dict[str, Any]) -> list[dict[str, Any]]:
        return build_normalized_skills(source_document_id, profile_data)

    @staticmethod
    def _build_education_entries(source_document_id: str, profile_data: dict[str, Any]) -> list[dict[str, Any]]:
        return build_education_entries(source_document_id, profile_data)

    @staticmethod
    def _build_experience_entries(source_document_id: str, profile_data: dict[str, Any]) -> list[dict[str, Any]]:
        return build_experience_entries(source_document_id, profile_data)

    @staticmethod
    def _entry_fingerprint(payload: dict[str, Any], keys: list[str]) -> str:
        return entry_fingerprint(payload, keys)
