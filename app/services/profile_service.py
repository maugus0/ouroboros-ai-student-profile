"""Profile orchestration - parse document -> LLM extract -> store."""

# pylint: disable=too-many-lines

import time
from datetime import date
from typing import Any, Optional

from app.core.logging import get_logger
from app.repositories.mysql_document_repo import DocumentRepository
from app.repositories.mysql_profile_normalized_repo import ProfileNormalizedRepository
from app.repositories.mysql_profile_repo import ProfileRepository
from app.services.document_parser import DocumentParser
from app.services.gap_analysis_service import GapAnalysisService
from app.services.llm_service import LLMService
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
from app.utils.exceptions import NotFoundError
from app.utils.file_utils import get_file_extension, get_mime_type

logger = get_logger(__name__)


class ProfileService:
    """High-level business logic for student profiles."""

    _READINESS_FIELD_SPECS = (
        {
            "name": "full_name",
            "json_paths": ("full_name", "identity.full_name"),
            "required": True,
        },
        {
            "name": "email",
            "json_paths": ("email", "identity.email"),
            "required": True,
        },
        {
            "name": "current_degree_level",
            "json_paths": ("current_degree_level", "education.current_degree_level"),
            "required": True,
        },
        {
            "name": "target_degree_level",
            "json_paths": ("target_degree_level", "preferences.target_degree_level"),
            "required": True,
        },
        {
            "name": "gpa",
            "json_paths": ("gpa", "gpa_highest", "education.current_gpa"),
            "required": True,
        },
        {
            "name": "gpa_scale",
            "json_paths": ("gpa_scale", "education.gpa_scale"),
            "required": True,
        },
        {
            "name": "intended_field_of_study",
            "json_paths": (
                "intended_field_of_study",
                "target_field_of_study",
                "preferences.field_of_study",
                "academic_preferences.field_of_study",
            ),
            "required": True,
        },
        {
            "name": "target_study_country",
            "json_paths": (
                "target_study_country",
                "preferences.target_country",
                "application_preferences.target_country",
            ),
            "required": False,
        },
        {
            "name": "enrollment_timeline",
            "json_paths": (
                "enrollment_timeline",
                "target_intake",
                "preferences.target_intake",
            ),
            "required": False,
        },
        {
            "name": "funding_source",
            "json_paths": (
                "funding_source",
                "financial_profile.funding_source",
                "scholarship_preferences.funding_source",
            ),
            "required": False,
        },
    )

    _SYNCED_PROFILE_FIELDS = (
        "full_name",
        "email",
        "phone",
        "nationality",
        "date_of_birth",
        "current_degree_level",
        "target_degree_level",
        "gpa",
        "gpa_scale",
    )

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
        user_id: str,
        file_name: str,
        file_content_base64: str,
        intent: Optional[str] = None,
        document_type: str = "cv",
        target_degree_hint: Optional[str] = None,
        run_gap_analysis: bool = True,
    ) -> dict[str, Any]:
        """Full pipeline: decode → extract text → LLM parse → store profile + document."""
        overall_start = time.perf_counter()
        logger.info(
            "profile_parse_started",
            file_name=file_name,
            document_type=document_type,
            intent=intent,
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
        profile_data["extraction_summary"] = self._build_extraction_summary(profile_data)

        total_ms = int((time.perf_counter() - overall_start) * 1000)

        # 3. Store lean profile record (scalar columns only; full state in profile_versions)
        record = {
            "user_id": user_id,
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
        # 6. Skill gaps can be identified automatically right after extraction.
        if run_gap_analysis:
            try:
                gap_analysis = await self.gap_service.analyze(profile_id)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("automatic_gap_analysis_failed", profile_id=profile_id, error=str(exc))

        logger.info("profile_pipeline_completed", profile_id=profile_id, total_ms=total_ms)

        return {
            "profile_id": profile_id,
            "profile_data": profile_data,
            "extraction_summary": profile_data.get("extraction_summary"),
            "llm_provider": llm_result.provider,
            "llm_model": llm_result.model,
            "fallback_used": llm_result.fallback_used,
            "gap_analysis": gap_analysis,
            "total_processing_time_ms": total_ms,
            "intent": intent,
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

        merged_row, merged_profile_json = self._merge_profile_sources(row, profile_json)

        # Remove keys duplicated by top-level scalar columns to keep payload concise.
        compact_profile_json = {key: value for key, value in merged_profile_json.items() if key not in merged_row}

        # Keep response compact: expose profile_json once (no duplicated top-level mirrors).
        profile = {
            **merged_row,
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
                "current_degree_level": "current_degree_level",
                "target_degree_level": "target_degree_level",
                "gpa": "gpa",
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

    async def sync_user_profile(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Seed or update student profile using user basics from orchestrator."""
        full_name = payload.get("full_name")
        email = payload.get("email")

        clean_sync_fields: dict[str, Any] = {}
        if isinstance(full_name, str) and full_name.strip():
            clean_sync_fields["full_name"] = full_name.strip()
        if isinstance(email, str) and email.strip():
            clean_sync_fields["email"] = email.strip()

        if not clean_sync_fields:
            return {
                "user_id": user_id,
                "synced": False,
                "reason": "no_syncable_fields",
            }

        existing = await self.profile_repo.get_latest_profile_by_user_id(user_id)
        if not existing:
            record = {
                "user_id": user_id,
                **clean_sync_fields,
                "profile_version": 1,
                "profile_prompt_version": "user_sync_seed_v1",
                "target_degree_source": "unknown",
            }
            profile_id = await self.profile_repo.create_profile(record)
            base_snapshot = {
                **clean_sync_fields,
                "confidence_map": {field: 1.0 for field in clean_sync_fields},
            }
            await self.normalized_repo.create_profile_version_snapshot(
                profile_id=profile_id,
                version_number=1,
                profile_json=self._apply_react_decision_pattern(base_snapshot),
                change_reason="user_sync_seed",
            )
            return {
                "user_id": user_id,
                "profile_id": profile_id,
                "synced": True,
                "created": True,
                "applied_fields": list(clean_sync_fields.keys()),
            }

        profile_id = existing["id"]
        next_version = int(existing.get("profile_version") or 1) + 1

        updates = {**clean_sync_fields, "profile_version": next_version}
        await self.profile_repo.update_profile(profile_id, updates)

        latest_version = await self.normalized_repo.get_latest_profile_version(profile_id)
        merged_profile_json = dict(latest_version.get("profile_json") or {}) if latest_version else {}
        merged_profile_json.update(clean_sync_fields)

        confidence_map = merged_profile_json.get("confidence_map")
        if not isinstance(confidence_map, dict):
            confidence_map = {}
        for field in clean_sync_fields:
            confidence_map[field] = 1.0
        merged_profile_json["confidence_map"] = confidence_map

        await self.normalized_repo.create_profile_version_snapshot(
            profile_id=profile_id,
            version_number=next_version,
            profile_json=self._apply_react_decision_pattern(merged_profile_json),
            change_reason="user_sync_update",
        )

        return {
            "user_id": user_id,
            "profile_id": profile_id,
            "synced": True,
            "created": False,
            "applied_fields": list(clean_sync_fields.keys()),
        }

    async def collect_from_chat(
        self,
        user_id: str,
        fields: dict[str, Any],
        *,
        extractions: Optional[dict[str, Any]] = None,
        extraction_telemetry: Optional[dict[str, Any]] = None,
        pending_clarification_fields: Optional[list[str]] = None,
        correction_fields: Optional[list[str]] = None,
        chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Persist chat-extracted fields into the latest profile and return updated readiness."""
        candidate_fields = {key: value for key, value in (fields or {}).items() if value is not None}
        has_extraction_payload = bool(
            extractions or extraction_telemetry or pending_clarification_fields or correction_fields
        )
        if not candidate_fields and not has_extraction_payload:
            readiness = await self.get_profile_status(user_id)
            return {
                "user_id": user_id,
                "profile_id": None,
                "applied_fields": [],
                "readiness": readiness,
                "chat_context": {"chat_id": chat_id, "message_id": message_id},
            }

        # Seed profile if absent using any immediately mappable fields.
        seed_payload: dict[str, Any] = {}
        if isinstance(candidate_fields.get("full_name"), str):
            seed_payload["full_name"] = candidate_fields["full_name"]
        if isinstance(candidate_fields.get("email"), str):
            seed_payload["email"] = candidate_fields["email"]
        if seed_payload:
            await self.sync_user_profile(user_id, seed_payload)

        existing = await self.profile_repo.get_latest_profile_by_user_id(user_id)
        if not existing:
            profile_id = await self.profile_repo.create_profile(
                {
                    "user_id": user_id,
                    "profile_version": 1,
                    "profile_prompt_version": "chat_collect_seed_v1",
                    "target_degree_source": "unknown",
                }
            )
            await self.normalized_repo.create_profile_version_snapshot(
                profile_id=profile_id,
                version_number=1,
                profile_json=self._apply_react_decision_pattern({}),
                change_reason="chat_collect_seed",
            )
        else:
            profile_id = existing["id"]

        if candidate_fields:
            answers = [{"field": key, "value": value} for key, value in candidate_fields.items()]
            submission = await self.submit_clarifications(profile_id, answers)
        else:
            submission = {
                "applied_fields": [],
                "clarification_queue": [],
            }

        correction_set = set(correction_fields or [])
        pending_set = set(pending_clarification_fields or [])

        if has_extraction_payload:
            latest_version = await self.normalized_repo.get_latest_profile_version(profile_id)
            profile_json = dict(latest_version.get("profile_json") or {}) if latest_version else {}
            trace = profile_json.get("chat_extraction_trace")
            if not isinstance(trace, list):
                trace = []
            pending_candidates = profile_json.get("pending_field_candidates")
            if not isinstance(pending_candidates, dict):
                pending_candidates = {}

            persisted_fields = set(submission.get("applied_fields") or [])

            for field, extraction in (extractions or {}).items():
                if not isinstance(extraction, dict):
                    continue
                candidate_value = extraction.get("value")
                if isinstance(candidate_value, list) and candidate_value:
                    deduped_candidates = self._dedupe_preserve_order(
                        [str(item).strip() for item in candidate_value if str(item).strip()]
                    )
                    if deduped_candidates:
                        pending_candidates[field] = deduped_candidates
                        pending_set.add(field)
                trace.append(
                    {
                        "field": field,
                        "value": extraction.get("value"),
                        "confidence": extraction.get("confidence"),
                        "reason": extraction.get("reason"),
                        "source_span": extraction.get("source_span"),
                        "persisted": field in persisted_fields,
                        "is_correction": bool(extraction.get("is_correction") or field in correction_set),
                        "chat_id": chat_id,
                        "message_id": message_id,
                    }
                )

            if pending_set:
                profile_json["pending_clarification_fields"] = list(pending_set)
            elif "pending_clarification_fields" in profile_json:
                profile_json.pop("pending_clarification_fields", None)

            if pending_candidates:
                profile_json["pending_field_candidates"] = pending_candidates
            elif "pending_field_candidates" in profile_json:
                profile_json.pop("pending_field_candidates", None)

            profile_json["chat_extraction_trace"] = trace[-100:]
            profile_json["extraction_telemetry"] = self._merge_extraction_telemetry(
                profile_json.get("extraction_telemetry"),
                extraction_telemetry,
            )

            row = await self.profile_repo.get_profile_by_id(profile_id)
            if row:
                next_version = int(row.get("profile_version") or 1) + 1
                await self.profile_repo.update_profile(profile_id, {"profile_version": next_version})
                await self.normalized_repo.create_profile_version_snapshot(
                    profile_id=profile_id,
                    version_number=next_version,
                    profile_json=self._apply_react_decision_pattern(profile_json),
                    change_reason="chat_extraction_trace_update",
                )

        readiness = await self.get_profile_status(user_id)

        return {
            "user_id": user_id,
            "profile_id": profile_id,
            "applied_fields": submission.get("applied_fields", []),
            "clarification_queue": submission.get("clarification_queue", []),
            "pending_clarification_fields": list(pending_set),
            "correction_fields": list(correction_set),
            "extraction_telemetry": self._merge_extraction_telemetry(None, extraction_telemetry),
            "readiness": readiness,
            "chat_context": {"chat_id": chat_id, "message_id": message_id},
        }

    async def get_profile_status(self, user_id: str, intent: str | None = None) -> dict[str, Any]:
        """Return a deterministic readiness snapshot for the user's latest profile."""
        default_missing = [
            str(spec["name"]) for spec in self._READINESS_FIELD_SPECS if bool(spec.get("required", True))
        ]
        default_optional_missing = [
            str(spec["name"]) for spec in self._READINESS_FIELD_SPECS if not bool(spec.get("required", True))
        ]
        optional_missing: list[str] = []
        row = await self.profile_repo.get_latest_profile_by_user_id(user_id)
        if not row:
            return {
                "user_id": user_id,
                "completed": False,
                "missing_fields": default_missing,
                "optional_missing_fields": default_optional_missing,
                "updated_at": None,
                "intent": intent,
            }

        profile_id = row["id"]

        latest_version = await self.normalized_repo.get_latest_profile_version(profile_id)
        profile_json = dict(latest_version.get("profile_json") or {}) if latest_version else {}
        merged_row, merged_profile_json = self._merge_profile_sources(row, profile_json)
        clarification_queue = merged_profile_json.get("clarification_queue") or []

        missing_fields: list[str] = []
        for field_spec in self._READINESS_FIELD_SPECS:
            field_name = str(field_spec["name"])
            value = merged_row.get(field_name)
            if value is None:
                json_paths = field_spec.get("json_paths")
                if not isinstance(json_paths, tuple):
                    json_paths = ()
                value = self._resolve_profile_json_value(
                    merged_profile_json,
                    json_paths,
                )
            if not self._is_meaningful_profile_value(field_name, value):
                if bool(field_spec.get("required", True)):
                    missing_fields.append(field_name)
                else:
                    optional_missing.append(field_name)
                continue

        for item in clarification_queue:
            field = item.get("field") if isinstance(item, dict) else None
            if field and field not in missing_fields:
                missing_fields.append(field)

        completed = not missing_fields and not bool(merged_row.get("target_degree_needs_clarification"))

        return {
            "user_id": user_id,
            "profile_id": profile_id,
            "completed": completed,
            "missing_fields": missing_fields,
            "optional_missing_fields": optional_missing,
            "updated_at": merged_row.get("updated_at"),
            "intent": intent,
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
            "gpa": "gpa",
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

        pending_candidates = updated_profile_data.get("pending_field_candidates")
        if not isinstance(pending_candidates, dict):
            pending_candidates = {}
        for field in answer_map:
            pending_candidates.pop(field, None)
        if pending_candidates:
            updated_profile_data["pending_field_candidates"] = pending_candidates
        elif "pending_field_candidates" in updated_profile_data:
            updated_profile_data.pop("pending_field_candidates", None)

        # Only update scalar columns in student_profiles; profile state lives in profile_versions
        next_version = int(row.get("profile_version") or 1) + 1
        updates: dict[str, Any] = {
            "target_degree_needs_clarification": bool(updated_profile_data.get("target_degree_needs_clarification")),
            "profile_version": next_version,
        }
        for source_field, target_field in top_level_mapping.items():
            if source_field in answer_map:
                if source_field == "gpa":
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
        gpa_source = profile_data.get("gpa")
        if gpa_source is None:
            gpa_source = profile_data.get("gpa_highest")
        parsed_gpa, inferred_gpa_scale = ProfileService._parse_gpa_value(gpa_source)
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

    @classmethod
    def _merge_profile_sources(
        cls,
        row: dict[str, Any],
        profile_json: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Merge scalar columns and snapshot JSON, preferring the latest meaningful snapshot value."""
        merged_row = dict(row)
        merged_profile_json = dict(profile_json)

        for field in cls._SYNCED_PROFILE_FIELDS:
            snapshot_value = profile_json.get(field)
            row_value = row.get(field)

            if cls._is_meaningful_profile_value(field, snapshot_value):
                merged_row[field] = snapshot_value
            elif cls._is_meaningful_profile_value(field, row_value):
                merged_row[field] = row_value

            if cls._is_meaningful_profile_value(field, merged_row.get(field)):
                merged_profile_json[field] = merged_row[field]

        return merged_row, merged_profile_json

    @staticmethod
    def _is_meaningful_profile_value(field: str, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return False
            if field in {"current_degree_level", "target_degree_level"} and text.lower() == "unknown":
                return False
        return True

    @staticmethod
    def _resolve_profile_json_value(profile_json: dict[str, Any], paths: tuple[str, ...]) -> Any:
        for path in paths:
            value = ProfileService._get_nested_value(profile_json, path)
            if value is not None:
                return value
        return None

    @staticmethod
    def _get_nested_value(payload: dict[str, Any], path: str) -> Any:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

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

    @staticmethod
    def _build_extraction_summary(profile_data: dict[str, Any]) -> dict[str, Any]:
        confidence_map = profile_data.get("confidence_map")
        if not isinstance(confidence_map, dict):
            confidence_map = {}

        high_confidence_fields: list[str] = []
        needs_confirmation_fields: list[str] = []
        for field, raw_confidence in confidence_map.items():
            try:
                confidence = float(raw_confidence)
            except (TypeError, ValueError):
                continue

            if confidence >= 0.85:
                high_confidence_fields.append(str(field))
            elif confidence >= 0.5:
                needs_confirmation_fields.append(str(field))

        return {
            "high_confidence_fields": high_confidence_fields,
            "needs_confirmation_fields": needs_confirmation_fields,
            "clarification_queue_count": len(profile_data.get("clarification_queue") or []),
        }

    @staticmethod
    def _merge_extraction_telemetry(
        existing: Any,
        latest_turn: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        existing_map = existing if isinstance(existing, dict) else {}
        turn = latest_turn if isinstance(latest_turn, dict) else {}

        turn_count = int(existing_map.get("turn_count") or 0) + (1 if turn else 0)
        candidate_total = int(existing_map.get("candidate_count_total") or 0) + int(turn.get("candidate_count") or 0)
        persisted_total = int(existing_map.get("persisted_count_total") or 0) + int(turn.get("persisted_count") or 0)
        correction_total = int(existing_map.get("correction_count_total") or 0) + int(turn.get("correction_count") or 0)
        clarification_total = int(existing_map.get("clarification_count_total") or 0) + int(
            turn.get("clarification_count") or 0
        )

        denominator = candidate_total if candidate_total > 0 else 1
        merged: dict[str, Any] = {
            "turn_count": turn_count,
            "candidate_count_total": candidate_total,
            "persisted_count_total": persisted_total,
            "correction_count_total": correction_total,
            "clarification_count_total": clarification_total,
            "hit_rate": round(persisted_total / denominator, 4),
            "correction_rate": round(correction_total / denominator, 4),
            "clarification_rate": round(clarification_total / denominator, 4),
        }
        if turn:
            merged["last_turn"] = turn
        elif isinstance(existing_map.get("last_turn"), dict):
            merged["last_turn"] = existing_map.get("last_turn")
        return merged

    @staticmethod
    def _dedupe_preserve_order(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            normalized = item.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped
