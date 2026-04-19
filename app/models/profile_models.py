"""Pydantic schemas for student profile API requests and responses."""

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ParseRequest(BaseModel):
    """Request body for POST /parse — sent by orchestrator."""

    user_id: Optional[str] = Field(default=None, description="Optional user id fallback when header/context is absent")
    intent: Optional[str] = Field(
        default="profile_completion",
        description="Request-time intent passed through by the orchestrator",
    )
    document_type: str = Field(default="cv", pattern="^(cv|transcript|unknown)$")
    file_name: str
    file_content_base64: str = Field(description="Base64-encoded file content")
    target_degree_hint: Optional[str] = Field(
        default=None,
        description="Optional user-provided target degree level",
    )
    run_gap_analysis: bool = Field(
        default=False,
        description="Whether to run automatic gap analysis immediately after profile creation",
    )


class SyncUserProfileRequest(BaseModel):
    """Request body for syncing basic user identity fields into student profile."""

    user_id: Optional[str] = Field(default=None, description="Optional user id fallback when header/context is absent")
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)

    @field_validator("full_name", "email", mode="before")
    @classmethod
    def _strip_nullable_strings(cls, value: Any):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("email")
    @classmethod
    def _validate_email_format(cls, value: Optional[str]):
        if value is None:
            return value
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
            raise ValueError("email must be a valid email address")
        return value


class CollectFromChatRequest(BaseModel):
    """Request body for collecting profile field values from chat turns."""

    user_id: Optional[str] = Field(default=None, description="Optional user id fallback when header/context is absent")
    fields: dict[str, Any] = Field(default_factory=dict, description="Extracted profile fields from chat content")
    extractions: dict[str, Any] = Field(
        default_factory=dict,
        description="Candidate extraction metadata by field (value/confidence/reason/source_span)",
    )
    extraction_telemetry: dict[str, Any] = Field(default_factory=dict)
    pending_clarification_fields: list[str] = Field(default_factory=list)
    correction_fields: list[str] = Field(default_factory=list)
    chat_id: Optional[str] = Field(default=None)
    message_id: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def _validate_payload(self):
        if not self.fields and not self.extractions:
            raise ValueError("fields or extractions must contain at least one extracted field")
        return self


class ProfileResponse(BaseModel):
    """Full profile as returned by GET /api/v1/profiles/{id}."""

    id: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    nationality: Optional[str] = None
    date_of_birth: Optional[str] = None

    current_degree_level: str = "unknown"
    target_degree_level: str = "unknown"
    target_degree_confidence: Optional[float] = None
    target_degree_source: str = "unknown"
    target_degree_needs_clarification: bool = False

    gpa: Optional[float] = None
    gpa_scale: Optional[float] = None
    gpa_normalized: Optional[float] = None
    gpa_confidence: Optional[float] = None

    profile_json: dict[str, Any] = Field(default_factory=dict)
    confidence_map: dict[str, float] = Field(default_factory=dict)
    evidence_map: dict[str, str] = Field(default_factory=dict)
    contradiction_flags: list[dict[str, str]] = Field(default_factory=list)
    clarification_queue: list[dict[str, str]] = Field(default_factory=list)
    react_decision_trace: dict[str, Any] = Field(default_factory=dict)

    llm_model_used: Optional[str] = None
    llm_fallback_used: bool = False
    total_processing_time_ms: Optional[int] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProfileUpdate(BaseModel):
    """Request body for PATCH/PUT /api/v1/profiles/{id}."""

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)
    nationality: Optional[str] = Field(default=None, min_length=2, max_length=100)
    current_degree_level: Optional[str] = None
    target_degree_level: Optional[str] = None
    gpa: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    gpa_scale: Optional[float] = Field(default=None, gt=0.0, le=100.0)

    @field_validator("full_name", "email", "phone", "nationality", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("email")
    @classmethod
    def _validate_email_format(cls, value: Optional[str]):
        if value is None:
            return value
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
            raise ValueError("email must be a valid email address")
        return value

    @field_validator("phone")
    @classmethod
    def _validate_phone_format(cls, value: Optional[str]):
        if value is None:
            return value
        if not re.match(r"^[+()\-\s\d]{7,50}$", value):
            raise ValueError("phone must contain only digits, spaces, and +()- symbols")
        return value

    @field_validator("target_degree_level")
    @classmethod
    def _validate_target_degree_level(cls, value: Optional[str]):
        if value is None:
            return value
        normalized = value.strip().lower()
        allowed = {"bachelor", "master", "phd", "unknown"}
        if normalized not in allowed:
            raise ValueError("target_degree_level must be one of: bachelor, master, phd, unknown")
        return normalized

    @field_validator("current_degree_level")
    @classmethod
    def _validate_current_degree_level(cls, value: Optional[str]):
        if value is None:
            return value
        normalized = value.strip().lower()
        allowed = {"high_school", "bachelor", "master", "phd", "unknown"}
        if normalized not in allowed:
            raise ValueError("current_degree_level must be one of: high_school, bachelor, master, phd, unknown")
        return normalized

    @model_validator(mode="after")
    def _validate_model(self):
        provided = [
            self.full_name,
            self.email,
            self.phone,
            self.nationality,
            self.current_degree_level,
            self.target_degree_level,
            self.gpa,
            self.gpa_scale,
        ]
        if not any(value is not None for value in provided):
            raise ValueError("At least one field must be provided")

        if self.gpa is not None and self.gpa_scale is not None and self.gpa > self.gpa_scale:
            raise ValueError("gpa must be less than or equal to gpa_scale")

        return self


class ProfileSummary(BaseModel):
    """Lightweight profile for list endpoints."""

    id: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    target_degree_level: str = "unknown"
    gpa: Optional[float] = None
    created_at: Optional[datetime] = None


class ClarificationAnswer(BaseModel):
    """Single answer to a clarification question."""

    field: str
    value: Any


class ClarificationSubmitRequest(BaseModel):
    """Batch clarification answers submitted by orchestrator."""

    answers: list[ClarificationAnswer] = Field(default_factory=list)


class GapAnalysisJobResponse(BaseModel):
    """Async gap-analysis job snapshot."""

    job_id: str
    profile_id: str
    status: str
    error_message: Optional[str] = None
    result: Optional[dict[str, Any]] = None


class ProfileStatusResponse(BaseModel):
    """Readiness snapshot for an extracted student profile."""

    user_id: str
    completed: bool
    missing_fields: list[str] = Field(default_factory=list)
    updated_at: Optional[datetime] = None
