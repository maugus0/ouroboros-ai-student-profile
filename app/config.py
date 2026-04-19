"""Application configuration loaded from environment variables."""

import json
import os
import tempfile

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    """All application settings. Loaded from .env file."""

    # ========== Database ==========
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "student_profile_db"
    DB_USERNAME: str = "root"
    DB_PASSWORD: str = ""

    DB_POOL_SIZE: int = 10
    DB_POOL_NAME: str = "student_profile_pool"
    DB_CONNECTION_TIMEOUT: int = 20

    # ========== Inter-Service Auth ==========
    # Kubernetes internal service token verification (Slice 4)
    INTERNAL_TOKEN_VERIFY_ENABLED: bool = False
    INTERNAL_TOKEN_SIGNING_ALGORITHM: str = "RS256"
    INTERNAL_TOKEN_PUBLIC_KEY: str = ""
    INTERNAL_TOKEN_PUBLIC_KEYS: str = "{}"
    INTERNAL_TOKEN_JWKS_URL: str = ""
    INTERNAL_TOKEN_JWKS_REFRESH_SECONDS: int = 60
    INTERNAL_TOKEN_JWKS_TIMEOUT_SECONDS: int = 2
    INTERNAL_TOKEN_AUDIENCE: str = "ouroboros.student-profile"
    INTERNAL_TOKEN_ISSUER: str = "ouroboros-orchestrator-internal"

    # ========== LLM Configuration ==========
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MAX_TOKENS: int = 2000
    OPENAI_TEMPERATURE: float = 0.0

    TARGET_DEGREE_MODEL: str = "gpt-4o-mini"
    TARGET_DEGREE_MAX_TOKENS: int = 400

    LLM_CLASSIFIER_INPUT_CHAR_BUDGET: int = 6000
    LLM_EXTRACTION_INPUT_CHAR_BUDGET: int = 14000
    LLM_GAP_ANALYSIS_INPUT_CHAR_BUDGET: int = 12000
    LLM_LONG_DOCUMENT_CHAR_THRESHOLD: int = 12000
    LLM_TARGET_DEGREE_CONFIDENCE_THRESHOLD: float = 0.75
    LLM_TRUNCATION_HEAD_CHARS: int = 4500
    LLM_TRUNCATION_TAIL_CHARS: int = 1500

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    ANTHROPIC_MAX_TOKENS: int = 2000

    LLM_MAX_RETRIES: int = 3
    LLM_RETRY_DELAY: int = 2

    # ========== Document Processing ==========
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: str = ".pdf,.docx"
    TEMP_UPLOAD_DIR: str = os.path.join(tempfile.gettempdir(), "ouroboros-ai-student-profile", "uploads")

    TESSERACT_PATH: str = ""
    OCR_LANGUAGE: str = "eng"

    # ========== Application ==========
    LOG_LEVEL: str = "INFO"
    UVICORN_HOST: str = "127.0.0.1"
    UVICORN_PORT: int = 8001
    USE_MOCK_DATA: bool = True
    ALLOW_DB_FAILURE: bool = False

    # ========== Docker ==========
    RUN_STARTUP_SCRIPTS: bool = True
    DOCKER_MYSQL_PORT: int = 3308

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    def get_db_host(self) -> str:
        return os.getenv("MYSQL_HOST", self.DB_HOST)

    def get_db_name(self) -> str:
        return os.getenv("MYSQL_DATABASE", self.DB_NAME)

    def get_db_user(self) -> str:
        return os.getenv("MYSQL_USER", self.DB_USERNAME)

    def get_db_password(self) -> str:
        return os.getenv("MYSQL_PASSWORD", self.DB_PASSWORD)

    def get_db_port(self) -> int:
        val = os.getenv("MYSQL_PORT")
        return int(val) if val is not None else self.DB_PORT

    def get_allowed_extensions_list(self) -> list[str]:
        return [ext.strip() for ext in self.ALLOWED_EXTENSIONS.split(",")]

    def get_internal_token_public_keys(self) -> dict[str, str]:
        """Parse INTERNAL_TOKEN_PUBLIC_KEYS JSON string into a kid->PEM dict."""
        try:
            parsed = json.loads(self.INTERNAL_TOKEN_PUBLIC_KEYS)
            if isinstance(parsed, dict):
                return {str(key): str(value) for key, value in parsed.items()}
        except (json.JSONDecodeError, TypeError):
            pass
        return {}


settings = Settings()
