"""Health-check endpoints."""

from fastapi import APIRouter

from app.config import APP_VERSION
from app.repositories.mysql_base import MySQLBaseRepository

router = APIRouter(tags=["Health"])


@router.get("/")
async def root():
    return {
        "message": "Student Profile Agent",
        "version": APP_VERSION,
        "status": "healthy",
    }


@router.get("/health")
async def health_check():
    repo = MySQLBaseRepository()

    try:
        await repo.execute_one("SELECT 1 AS ok")
        database_status = "connected"
        service_status = "healthy"
    except Exception:  # pylint: disable=broad-exception-caught
        database_status = "not_connected"
        service_status = "degraded"

    return {
        "status": service_status,
        "version": APP_VERSION,
        "database": database_status,
    }
