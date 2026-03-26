"""Pydantic schemas for student profile API requests and responses."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    """Request body for POST /parse — sent by orchestrator."""

    user_id: str
    document_type: str = Field(default="cv", pattern="^(cv|transcript|unknown)$")
    file_name: str
    file_content_base64: str = Field(description="Base64-encoded file content")
    target_degree_hint: Optional[str] = Field(
        default=None,
        description="Optional user-provided target degree level",
    )


class ProfileResponse(BaseModel):
    """Full profile as returned by GET /profiles/{id}."""

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
    missing_critical_fields: list[str] = Field(default_factory=list)
    clarification_queue: list[dict[str, str]] = Field(default_factory=list)

    llm_model_used: Optional[str] = None
    llm_fallback_used: bool = False
    total_processing_time_ms: Optional[int] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProfileUpdate(BaseModel):
    """Request body for PATCH /profiles/{id}."""

    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    nationality: Optional[str] = None
    target_degree_level: Optional[str] = None
    gpa: Optional[float] = None
    gpa_scale: Optional[float] = None


class ProfileSummary(BaseModel):
    """Lightweight profile for list endpoints."""

    id: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    target_degree_level: str = "unknown"
    gpa: Optional[float] = None
    created_at: Optional[datetime] = None
