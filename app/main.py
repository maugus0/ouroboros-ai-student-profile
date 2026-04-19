"""FastAPI application entry point for the Student Profile Agent."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.api import documents, health, profiles
from app.config import APP_VERSION, settings
from app.core.logging import get_logger, setup_logging
from app.middleware.logging_middleware import LoggingMiddleware
from app.repositories.db_pool import DatabasePoolConfig, close_pool, create_pool
from app.utils.exceptions import StudentProfileBaseError

load_dotenv()


@asynccontextmanager
async def lifespan(_application: FastAPI):
    """Application startup and shutdown lifecycle."""
    setup_logging(log_level=settings.LOG_LEVEL)
    logger = get_logger("startup")

    logger.info("student_profile_agent_starting", version=APP_VERSION)

    if not settings.ALLOW_DB_FAILURE:
        try:
            await create_pool(
                DatabasePoolConfig(
                    host=settings.get_db_host(),
                    port=settings.get_db_port(),
                    db=settings.get_db_name(),
                    user=settings.get_db_user(),
                    password=settings.get_db_password(),
                    pool_size=settings.DB_POOL_SIZE,
                )
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("database_connection_failed", error=str(exc))
            raise
    else:
        logger.warning("database_skipped", reason="ALLOW_DB_FAILURE is True")

    yield

    await close_pool()
    logger.info("student_profile_agent_stopped")


app = FastAPI(
    title="Student Profile Agent",
    version=APP_VERSION,
    description="Microservice for parsing CV/transcript documents and extracting structured student profiles",
    lifespan=lifespan,
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "filter": True,
        "docExpansion": "none",
    },
)

# -- Exception Handlers ------------------------------------------------


@app.exception_handler(StudentProfileBaseError)
async def student_profile_error_handler(_request: Request, exc: StudentProfileBaseError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.message},
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(_request: Request, exc: RuntimeError):
    return JSONResponse(
        status_code=503,
        content={"success": False, "message": str(exc)},
    )


# -- Middleware ---------------------------------------------------------

app.add_middleware(LoggingMiddleware)

# -- Routers -----------------------------------------------------------

app.include_router(health.router)
app.include_router(profiles.router)
app.include_router(documents.router)


# -- Custom OpenAPI ----------------------------------------------------


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["info"]["x-logo"] = {"url": "https://ouroboros.ai/logo.png"}
    schema.setdefault("components", {})
    schema["components"].setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["InternalBearer"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Internal bearer token issued by the orchestrator",
    }

    public_paths = {"/", "/health"}
    for path, path_item in schema.get("paths", {}).items():
        if path in public_paths:
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if isinstance(operation, dict):
                operation.setdefault("security", [{"InternalBearer": []}])

    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi  # type: ignore[method-assign]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.UVICORN_HOST, port=settings.UVICORN_PORT, reload=True)
