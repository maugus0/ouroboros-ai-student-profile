"""Tests for application configuration."""

import os


def test_settings_load():
    os.environ.setdefault("ALLOW_DB_FAILURE", "true")
    os.environ.setdefault("X_SERVICE_TOKEN", "test-service-token")

    from app.config import settings

    assert settings.DB_NAME == "student_profile_db"
    assert isinstance(settings.DB_PORT, int)
    assert settings.DB_PORT > 0
    assert settings.DB_POOL_NAME == "student_profile_pool"


def test_settings_db_helpers():
    os.environ.setdefault("ALLOW_DB_FAILURE", "true")
    os.environ.setdefault("X_SERVICE_TOKEN", "test-service-token")

    from app.config import settings

    assert isinstance(settings.get_db_host(), str)
    assert isinstance(settings.get_db_port(), int)
    assert isinstance(settings.get_db_name(), str)
    assert isinstance(settings.get_db_user(), str)


def test_allowed_extensions():
    os.environ.setdefault("X_SERVICE_TOKEN", "test-service-token")
    from app.config import settings

    exts = settings.get_allowed_extensions_list()
    assert ".pdf" in exts
    assert ".docx" in exts
