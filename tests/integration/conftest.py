"""Pytest configuration and fixtures for integration tests with real MySQL."""

import os
from pathlib import Path

import mysql.connector
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

# Load environment variables before importing app
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
env_file = os.path.join(ROOT_DIR, ".env")
if os.path.exists(env_file):
    load_dotenv(env_file)

# Set integration test flags
os.environ["ALLOW_DB_FAILURE"] = "false"
os.environ["USE_MOCK_DATA"] = "false"

# pylint: disable=wrong-import-position
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def integration_client():
    """Fixture to provide a test client connected to real database."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def service_token_header():
    """Header value for service authentication."""
    return {"X-Service-Token": settings.X_SERVICE_TOKEN}


@pytest.fixture(scope="session", autouse=True)
def setup_integration_db():
    """Set up test database schema before running integration tests."""
    conn = mysql.connector.connect(
        host=settings.get_db_host(),
        port=settings.get_db_port(),
        database=settings.get_db_name(),
        user=settings.get_db_user(),
        password=settings.get_db_password(),
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
    )
    cursor = conn.cursor()

    migrations_dir = Path(ROOT_DIR) / "migrations"
    if migrations_dir.exists():
        sql_files = sorted([f for f in migrations_dir.glob("*.sql") if f.name[0].isdigit()])
        for sql_file in sql_files:
            sql = sql_file.read_text(encoding="utf-8")
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)
            conn.commit()

    # Legacy table used by FieldRepository and some unit/flow test paths.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profile_fields (
            id VARCHAR(36) PRIMARY KEY,
            profile_id VARCHAR(36) NOT NULL,
            field_category VARCHAR(100) NOT NULL,
            field_name VARCHAR(255) NOT NULL,
            field_value JSON NOT NULL,
            confidence_score DECIMAL(3,2) NULL,
            evidence_snippet TEXT NULL,
            source_document_id VARCHAR(36) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_profile_id (profile_id),
            INDEX idx_field_category (field_category)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    conn.commit()

    cursor.close()
    conn.close()


@pytest.fixture
def cleanup_integration_db():
    """Clean up test data after each test."""
    yield

    conn = mysql.connector.connect(
        host=settings.get_db_host(),
        port=settings.get_db_port(),
        database=settings.get_db_name(),
        user=settings.get_db_user(),
        password=settings.get_db_password(),
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
    )
    cursor = conn.cursor()

    tables = [
        "llm_call_logs",
        "gap_analysis_jobs",
        "gap_analysis",
        "experience_entries",
        "education_entries",
        "extracted_skills",
        "profile_versions",
        "profile_fields",
        "documents",
        "student_profiles",
    ]
    for table in tables:
        try:
            cursor.execute(f"TRUNCATE TABLE {table}")
        except mysql.connector.Error:
            pass
    conn.commit()
    cursor.close()
    conn.close()
