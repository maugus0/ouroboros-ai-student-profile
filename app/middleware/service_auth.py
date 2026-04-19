"""FastAPI dependency for inter-service X-Service-Token validation."""

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from app.core.security import validate_service_token_value

service_token_header = APIKeyHeader(
    name="X-Service-Token",
    scheme_name="X-Service-Token",
    description="Service-to-service token required for protected endpoints.",
    auto_error=False,
)


async def require_service_token(
    request: Request,
    service_token: str | None = Security(service_token_header),
) -> None:
    """FastAPI dependency — validates the X-Service-Token header.

    Raises:
        HTTPException: If token is missing or invalid.
    """
    validate_service_token_value(token=service_token, path=request.url.path)
