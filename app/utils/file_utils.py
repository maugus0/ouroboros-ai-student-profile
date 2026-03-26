"""File type detection and utility functions for document uploads."""

import os
from pathlib import Path

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

MIME_TYPE_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def get_file_extension(filename: str) -> str:
    """Extract the lowercase file extension from a filename."""
    return Path(filename).suffix.lower()


def get_mime_type(filename: str) -> str:
    """Map a file extension to its MIME type."""
    ext = get_file_extension(filename)
    return MIME_TYPE_MAP.get(ext, "application/octet-stream")


def validate_file_extension(filename: str) -> bool:
    """Check whether the file extension is in the allowed list."""
    ext = get_file_extension(filename)
    return ext in settings.get_allowed_extensions_list()


def validate_file_size(size_bytes: int) -> bool:
    """Check whether the file size is within the configured limit."""
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    return size_bytes <= max_bytes


def ensure_upload_dir() -> str:
    """Create the temp upload directory if it does not exist."""
    os.makedirs(settings.TEMP_UPLOAD_DIR, exist_ok=True)
    return settings.TEMP_UPLOAD_DIR


def cleanup_temp_file(file_path: str) -> None:
    """Remove a temporary file if it exists."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.debug("temp_file_removed", path=file_path)
    except OSError as exc:
        logger.warning("temp_file_cleanup_failed", path=file_path, error=str(exc))
