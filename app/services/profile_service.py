"""Profile orchestration - parse document -> LLM extract -> store."""

import hashlib
import json
import re
import time
from datetime import date, datetime
from typing import Any, Optional

from app.core.logging import get_logger
from app.repositories.mysql_document_repo import DocumentRepository
from app.repositories.mysql_field_repo import FieldRepository
from app.repositories.mysql_profile_normalized_repo import ProfileNormalizedRepository
from app.repositories.mysql_profile_repo import ProfileRepository
from app.services.document_parser import DocumentParser
from app.services.gap_analysis_service import GapAnalysisService
from app.services.llm_service import LLMService
from app.utils.exceptions import NotFoundError
from app.utils.file_utils import get_file_extension, get_mime_type

logger = get_logger(__name__)


class ProfileService:
    """High-level business logic for student profiles."""

    def __init__(self):
        self.profile_repo = ProfileRepository()
        self.document_repo = DocumentRepository()
        self.field_repo = FieldRepository()
        self.normalized_repo = ProfileNormalizedRepository()
        self.parser = DocumentParser()
        self.llm_service = LLMService()
        self.gap_service = GapAnalysisService()

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
            "profile_prompt_version": "profile_extraction_v1",
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

            try:
                await self.normalized_repo.create_profile_version_snapshot(
                    profile_id=profile_id,
                    version_number=next_version,
                    profile_json=merged_profile_json,
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
        updated_profile_data["target_degree_needs_clarification"] = bool(updated_queue)

        # Only update scalar columns in student_profiles; profile state lives in profile_versions
        next_version = int(row.get("profile_version") or 1) + 1
        updates: dict[str, Any] = {
            "target_degree_needs_clarification": bool(updated_queue),
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
        """Convert clarification value for strict DB columns; return None to skip DB write."""
        if value is None:
            return None

        if field == "date_of_birth":
            if isinstance(value, date):
                return value
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, str):
                return ProfileService._parse_date_text(value)
            return None

        if field in {"gpa_highest", "gpa_scale"}:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        if field in {"current_degree_level", "target_degree_level"}:
            return ProfileService._normalize_degree_level_value(field, value)

        return value

    @staticmethod
    def _normalize_field_name(field: Any) -> str:
        if field is None:
            return ""

        text = str(field).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "dob": "date_of_birth",
            "birth_date": "date_of_birth",
            "target_degree": "target_degree_level",
            "current_degree": "current_degree_level",
            "gpa": "gpa_highest",
            "highest_gpa": "gpa_highest",
        }
        return aliases.get(text, text)

    @staticmethod
    def _parse_gpa_value(value: Any) -> tuple[Optional[float], Optional[float]]:
        """Parse GPA values from scalar or ratio text (e.g., '4.0/5.0')."""
        if value is None:
            return None, None

        if isinstance(value, (int, float)):
            return float(value), None

        text = str(value).strip()
        if not text:
            return None, None

        ratio_match = re.match(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$", text)
        if ratio_match:
            return float(ratio_match.group(1)), float(ratio_match.group(2))

        try:
            return float(text), None
        except ValueError:
            return None, None

    @staticmethod
    def _normalize_degree_level_value(field: str, value: Any) -> Optional[str]:
        text = str(value or "").strip().lower()
        if not text:
            return None

        if "phd" in text or "doctor" in text:
            return "phd"
        if "master" in text:
            return "master"
        if "bachelor" in text or re.search(r"\bbs\b|\bba\b|\bbsc\b", text):
            return "bachelor"
        if field == "current_degree_level" and ("high school" in text or "high_school" in text or text == "highschool"):
            return "high_school"
        if text == "unknown":
            return "unknown"
        return None

    @staticmethod
    def _parse_date_text(value: str) -> Optional[date]:
        text = value.strip()
        if not text:
            return None

        formats = (
            "%Y-%m-%d",
            "%d %b %Y",
            "%d %B %Y",
            "%b %d %Y",
            "%B %d %Y",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%m/%d/%Y",
        )
        for fmt in formats:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @classmethod
    def _apply_react_decision_pattern(cls, profile_data: dict[str, Any]) -> dict[str, Any]:
        """Apply an internal Reason-Act-Observe pass for all fields requiring clarification.

        Reason: Evaluate if fields are missing, contradictory, or low-confidence.
        Act: Mark fields that need clarification in the decision trace.
        Observe: Derive the clarification queue from the decision trace (single source of truth).
        """
        normalized = dict(profile_data or {})

        confidence_map = normalized.get("confidence_map") if isinstance(normalized.get("confidence_map"), dict) else {}
        contradiction_flags = (
            normalized.get("contradiction_flags") if isinstance(normalized.get("contradiction_flags"), list) else []
        )

        contradicted_fields: set[str] = set()
        for item in contradiction_flags:
            if not isinstance(item, dict):
                continue
            field = cls._normalize_field_name(item.get("field") or item.get("field_name"))
            if field:
                contradicted_fields.add(field)

        # Define rules for critical fields
        critical_rules = {
            "full_name": {
                "question": "What is your full name?",
                "min_confidence": 0.75,
                "require_when_missing": False,
            },
            "email": {
                "question": "What is your email address?",
                "min_confidence": 0.75,
                "require_when_missing": False,
            },
            "current_degree_level": {
                "question": "What is your current degree level?",
                "min_confidence": 0.7,
                "require_when_missing": True,
            },
            "target_degree_level": {
                "question": "What is your target degree level?",
                "min_confidence": 0.7,
                "require_when_missing": True,
            },
            "gpa_highest": {
                "question": "What is your highest GPA?",
                "min_confidence": 0.65,
                "require_when_missing": False,
            },
        }

        # Default questions for non-critical fields
        default_questions = {
            "publications": "Do you have publications? Please provide title, venue, and year if available.",
            "phone": "What is your phone number?",
            "nationality": "What is your nationality?",
            "date_of_birth": "What is your date of birth?",
            "gpa_scale": "What GPA scale is used?",
        }

        decision_trace: dict[str, Any] = {}

        # Evaluate critical fields
        for field, rule in critical_rules.items():
            value = normalized.get(field)
            reason = None

            if field in {"current_degree_level", "target_degree_level"}:
                normalized_degree = cls._normalize_degree_level_value(field, value)
                if normalized_degree is None or normalized_degree == "unknown":
                    reason = "missing_or_unknown"
            else:
                is_missing = value is None or (isinstance(value, str) and not value.strip())
                if is_missing and rule["require_when_missing"]:
                    reason = "missing_or_unknown"

            if reason is None and field in contradicted_fields:
                reason = "contradiction_detected"

            if reason is None and field in confidence_map:
                try:
                    confidence = float(confidence_map[field])
                    min_confidence = rule.get("min_confidence")
                    if isinstance(min_confidence, (int, float)) and confidence < float(min_confidence):
                        reason = "low_confidence"
                except (TypeError, ValueError):
                    reason = "invalid_confidence"

            if reason is None:
                decision_trace[field] = {"decision": "accept"}
            else:
                decision_trace[field] = {"decision": "clarify", "reason": reason}

        # CRITICAL: Check if current_degree == target_degree (ambiguous case)
        current_normalized = cls._normalize_degree_level_value(
            "current_degree_level", normalized.get("current_degree_level")
        )
        target_normalized = cls._normalize_degree_level_value(
            "target_degree_level", normalized.get("target_degree_level")
        )

        if (
            current_normalized not in {None, "unknown"}
            and target_normalized not in {None, "unknown"}
            and current_normalized == target_normalized
        ):
            # Current degree matches inferred target → ambiguous, flag for clarification
            decision_trace["target_degree_level"] = {
                "decision": "clarify",
                "reason": "ambiguous_current_equals_target",
            }

        # Evaluate fields from incoming clarification_queue or missing_critical_fields.
        # Skip fields already answered by user (confidence = 1.0).
        fields_to_check = set()

        # Add fields from incoming queue (but skip if already answered by user with confidence = 1.0)
        queue = list(normalized.get("clarification_queue") or [])
        for item in queue:
            if isinstance(item, dict):
                field = cls._normalize_field_name(item.get("field"))
                if field:
                    # Only add to check if not already answered by user
                    field_confidence = confidence_map.get(field)
                    try:
                        is_user_answered = field_confidence is not None and float(field_confidence) == 1.0
                    except (TypeError, ValueError):
                        is_user_answered = False

                    if not is_user_answered:
                        fields_to_check.add(field)

        # Add fields from missing_critical_fields
        missing_fields = list(normalized.get("missing_critical_fields") or [])
        for field in missing_fields:
            field_norm = cls._normalize_field_name(field)
            if field_norm:
                fields_to_check.add(field_norm)

        # Evaluate non-critical fields (only if they're in the queue or missing_critical_fields)
        for field in fields_to_check:
            if field not in decision_trace:
                decision_trace[field] = {"decision": "clarify", "reason": "missing_or_unknown"}

        # Publications clarification is required for PhD candidates when missing.
        # If explicitly answered by user (confidence = 1.0), mark as accepted in decision trace.
        target_degree_normalized = cls._normalize_degree_level_value(
            "target_degree_level", normalized.get("target_degree_level")
        )
        publications = normalized.get("publications")
        has_publications = isinstance(publications, list) and len(publications) > 0
        publications_confidence = confidence_map.get("publications")

        # Check if publications has been explicitly answered by user (confidence = 1.0)
        publications_already_answered = False
        if publications_confidence is not None:
            try:
                is_user_answered = float(publications_confidence) == 1.0
                publications_already_answered = is_user_answered
            except (TypeError, ValueError):
                pass

        # Keep publications visible in trace once answered, even when queue becomes empty.
        if publications_already_answered and "publications" not in decision_trace:
            decision_trace["publications"] = {"decision": "accept"}

        if (
            target_degree_normalized == "phd"
            and not has_publications
            and not publications_already_answered
            and "publications" not in decision_trace
        ):
            decision_trace["publications"] = {"decision": "clarify", "reason": "missing_or_unknown"}

        # Derive the clarification queue from decision_trace (fields with "decision": "clarify")
        new_queue: list[dict[str, Any]] = []
        for field, trace_entry in decision_trace.items():
            if isinstance(trace_entry, dict) and trace_entry.get("decision") == "clarify":
                question = critical_rules.get(field, {}).get("question") or default_questions.get(
                    field, f"Please provide your {field.replace('_', ' ')}."
                )
                new_queue.append({"field": field, "question": question})

        normalized["clarification_queue"] = new_queue
        normalized.pop("missing_critical_fields", None)
        normalized["react_decision_trace"] = decision_trace
        normalized["target_degree_needs_clarification"] = bool(new_queue)
        return normalized

    @staticmethod
    def _build_profile_fields(
        profile_id: str, source_document_id: str, profile_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Flatten extracted profile JSON into profile_fields records.

        Array-heavy fields are persisted in dedicated normalized tables to avoid
        storing the same payload in multiple places.
        """
        field_categories = {
            "full_name": "personal",
            "email": "personal",
            "phone": "personal",
            "nationality": "personal",
            "date_of_birth": "personal",
            "target_degree_level": "academic",
            "current_degree_level": "academic",
            "target_degree_confidence": "academic",
            "target_degree_source": "academic",
            "target_degree_needs_clarification": "academic",
            "target_degree_reasoning": "academic",
            "gpa_highest": "academic",
            "gpa_scale": "academic",
            "publications": "research",
            "languages": "skills",
            "certifications": "skills",
            "research_interests": "research",
        }

        confidence_map = profile_data.get("confidence_map") or {}
        evidence_map = profile_data.get("evidence_map") or {}

        rows: list[dict[str, Any]] = []
        for field_name, category in field_categories.items():
            value = profile_data.get(field_name)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, dict)) and not value:
                continue

            raw_confidence = confidence_map.get(field_name)
            confidence_score = None
            if raw_confidence is not None:
                try:
                    parsed = float(raw_confidence)
                    if 0.0 <= parsed <= 1.0:
                        confidence_score = parsed
                except (TypeError, ValueError):
                    confidence_score = None

            evidence = evidence_map.get(field_name)
            evidence_snippet = None
            if isinstance(evidence, str) and evidence.strip():
                evidence_snippet = evidence.strip()

            rows.append(
                {
                    "profile_id": profile_id,
                    "field_category": category,
                    "field_name": field_name,
                    "field_value": value,
                    "confidence_score": confidence_score,
                    "evidence_snippet": evidence_snippet,
                    "source_document_id": source_document_id,
                }
            )

        return rows

    @staticmethod
    def _normalize_skill_name(skill: str) -> str:
        """Normalize skill labels for consistent indexing."""
        normalized = re.sub(r"\s+", " ", skill.strip().lower())
        normalized = normalized.replace("python3", "python").replace("py3", "python")
        return normalized

    @classmethod
    def _build_normalized_skills(cls, source_document_id: str, profile_data: dict[str, Any]) -> list[dict[str, Any]]:
        skills = profile_data.get("technical_skills") if isinstance(profile_data.get("technical_skills"), list) else []
        confidence_map = (
            profile_data.get("confidence_map") if isinstance(profile_data.get("confidence_map"), dict) else {}
        )
        confidence = confidence_map.get("technical_skills")
        confidence_score = None
        if confidence is not None:
            try:
                parsed = float(confidence)
                if 0.0 <= parsed <= 1.0:
                    confidence_score = parsed
            except (TypeError, ValueError):
                confidence_score = None

        dedup: dict[str, str] = {}
        for item in skills:
            raw_skill = str(item).strip()
            if not raw_skill:
                continue
            normalized = cls._normalize_skill_name(raw_skill)
            if not normalized:
                continue
            dedup.setdefault(normalized, raw_skill)

        rows: list[dict[str, Any]] = []
        for normalized, raw in dedup.items():
            rows.append(
                {
                    "raw_skill": raw,
                    "normalized_skill": normalized,
                    "confidence_score": confidence_score,
                    "source_document_id": source_document_id,
                }
            )
        return rows

    @staticmethod
    def _build_education_entries(source_document_id: str, profile_data: dict[str, Any]) -> list[dict[str, Any]]:
        education = profile_data.get("education") if isinstance(profile_data.get("education"), list) else []
        confidence_map = (
            profile_data.get("confidence_map") if isinstance(profile_data.get("confidence_map"), dict) else {}
        )
        evidence_map = profile_data.get("evidence_map") if isinstance(profile_data.get("evidence_map"), dict) else {}
        confidence_score = confidence_map.get("education")
        parsed_confidence = None
        try:
            if confidence_score is not None:
                score = float(confidence_score)
                if 0.0 <= score <= 1.0:
                    parsed_confidence = score
        except (TypeError, ValueError):
            parsed_confidence = None

        rows: list[dict[str, Any]] = []
        seen_fingerprints: set[str] = set()
        for index, item in enumerate(education):
            if not isinstance(item, dict):
                continue
            institution = str(item.get("institution") or "").strip()
            degree = str(item.get("degree") or "").strip()
            if not institution or not degree:
                continue
            row = {
                "institution": institution,
                "degree": degree,
                "field_of_study": item.get("field_of_study"),
                "start_date": item.get("start_date"),
                "end_date": item.get("end_date"),
                "gpa": item.get("gpa"),
                "gpa_scale": item.get("gpa_scale"),
                "achievements": item.get("achievements") if isinstance(item.get("achievements"), list) else [],
                "evidence_snippet": evidence_map.get("education"),
                "confidence_score": parsed_confidence,
                "source_document_id": source_document_id,
                "sort_index": index,
            }
            fingerprint = ProfileService._entry_fingerprint(
                row,
                keys=[
                    "institution",
                    "degree",
                    "field_of_study",
                    "start_date",
                    "end_date",
                    "gpa",
                    "gpa_scale",
                    "achievements",
                ],
            )
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            row["entry_fingerprint"] = fingerprint
            rows.append(row)
        return rows

    @staticmethod
    def _build_experience_entries(source_document_id: str, profile_data: dict[str, Any]) -> list[dict[str, Any]]:
        confidence_map = (
            profile_data.get("confidence_map") if isinstance(profile_data.get("confidence_map"), dict) else {}
        )
        evidence_map = profile_data.get("evidence_map") if isinstance(profile_data.get("evidence_map"), dict) else {}

        def _coerce_confidence(value: Any) -> float | None:
            try:
                if value is None:
                    return None
                parsed = float(value)
                if 0.0 <= parsed <= 1.0:
                    return parsed
            except (TypeError, ValueError):
                return None
            return None

        rows: list[dict[str, Any]] = []
        seen_fingerprints: set[str] = set()
        work_confidence = _coerce_confidence(confidence_map.get("work_experience"))
        research_confidence = _coerce_confidence(confidence_map.get("research_experience"))

        work_experience = (
            profile_data.get("work_experience") if isinstance(profile_data.get("work_experience"), list) else []
        )
        for index, item in enumerate(work_experience):
            if not isinstance(item, dict):
                continue
            company = str(item.get("company") or "").strip()
            position = str(item.get("position") or "").strip()
            if not company or not position:
                continue
            row = {
                "experience_type": "work",
                "organization": company,
                "title": position,
                "role": None,
                "start_date": item.get("start_date"),
                "end_date": item.get("end_date"),
                "description": item.get("description"),
                "skills_used": item.get("skills_used") if isinstance(item.get("skills_used"), list) else [],
                "publication_venue": None,
                "evidence_snippet": evidence_map.get("work_experience"),
                "confidence_score": work_confidence,
                "source_document_id": source_document_id,
                "sort_index": index,
            }
            fingerprint = ProfileService._entry_fingerprint(
                row,
                keys=[
                    "experience_type",
                    "organization",
                    "title",
                    "start_date",
                    "end_date",
                    "description",
                    "skills_used",
                ],
            )
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            row["entry_fingerprint"] = fingerprint
            rows.append(row)

        research_experience = (
            profile_data.get("research_experience") if isinstance(profile_data.get("research_experience"), list) else []
        )
        for index, item in enumerate(research_experience):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            row = {
                "experience_type": "research",
                "organization": None,
                "title": title,
                "role": item.get("role"),
                "start_date": item.get("date"),
                "end_date": None,
                "description": item.get("description"),
                "skills_used": [],
                "publication_venue": item.get("publication_venue"),
                "evidence_snippet": evidence_map.get("research_experience"),
                "confidence_score": research_confidence,
                "source_document_id": source_document_id,
                "sort_index": index,
            }
            fingerprint = ProfileService._entry_fingerprint(
                row,
                keys=[
                    "experience_type",
                    "title",
                    "role",
                    "start_date",
                    "description",
                    "publication_venue",
                ],
            )
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            row["entry_fingerprint"] = fingerprint
            rows.append(row)

        return rows

    @staticmethod
    def _entry_fingerprint(payload: dict[str, Any], keys: list[str]) -> str:
        """Return stable SHA-256 fingerprint for dedupe-sensitive fields."""
        normalized = {key: payload.get(key) for key in keys}
        canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
