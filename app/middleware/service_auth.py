"""FastAPI dependency for inter-service X-Service-Token validation."""

from fastapi import Depends, HTTPException, Request, status

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def require_service_token(request: Request) -> None:
    """FastAPI dependency — validates the X-Service-Token header.

    Raises:
        HTTPException: If token is missing or invalid.
    """
    token = request.headers.get("X-Service-Token")

    if not token:
        logger.warning("missing_service_token", path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Service-Token header required",
        )

    if token != settings.X_SERVICE_TOKEN:
        logger.warning("invalid_service_token", path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid service token",
        )
