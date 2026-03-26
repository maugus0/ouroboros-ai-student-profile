"""Pydantic schemas for LLM call logging and extraction results."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class LLMCallLog(BaseModel):
    """Record of a single LLM API call for audit purposes."""

    id: str
    profile_id: Optional[str] = None
    operation: str
    llm_provider: str
    model_name: str

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_cost_usd: Optional[float] = None
    latency_ms: Optional[int] = None

    success: bool
    error_message: Optional[str] = None
    retry_count: int = 0
    trace_id: str

    created_at: Optional[datetime] = None


class LLMExtractionResult(BaseModel):
    """Wrapper around the LLM extraction output plus metadata."""

    profile_data: dict[str, Any] = Field(default_factory=dict)
    provider: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
