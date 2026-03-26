"""General-purpose utility functions."""

import uuid
from datetime import datetime, timezone


def generate_uuid() -> str:
    """Generate a UUID-v4 string."""
    return str(uuid.uuid4())


def get_current_time() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def get_current_time_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
