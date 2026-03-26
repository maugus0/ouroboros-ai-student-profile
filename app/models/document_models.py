"""Pydantic schemas for document API requests and responses."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    """Document metadata as returned by GET /documents/{id}."""

    id: str
    profile_id: str
    document_type: str
    file_name: str
    file_extension: str
    file_size_bytes: int
    mime_type: Optional[str] = None
    file_path: Optional[str] = None

    extracted_text_length: Optional[int] = None
    ocr_used: bool = False
    extraction_method: str = "unknown"
    extraction_time_ms: Optional[int] = None

    created_at: Optional[datetime] = None
