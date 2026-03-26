"""FastAPI dependency for inter-service X-Service-Token validation."""

from fastapi import Request

from app.core.security import validate_service_token


async def require_service_token(request: Request) -> None:
    """FastAPI dependency — validates the X-Service-Token header.

    Raises:
        HTTPException: If token is missing or invalid.
    """
    validate_service_token(request)
