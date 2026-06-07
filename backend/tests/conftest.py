"""Общие фикстуры pytest: тестовые настройки приложения и безопасности."""

from __future__ import annotations

import pytest

from core.config import (
    ApplicationSettings,
    CookieSettings,
    DatabaseSettings,
    LoggingSettings,
    SecuritySettings,
    Settings,
    StorageSettings,
    WorkerSettings,
)


@pytest.fixture(scope="session")
def test_security_settings() -> SecuritySettings:
    return SecuritySettings(
        SECRET_KEY="test-secret-key-for-pytest-only-1234",
        JWT_ALGORITHM="HS256",
        JWT_ISSUER="test-issuer",
        JWT_AUDIENCE="test-audience",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        REFRESH_TOKEN_EXPIRE_DAYS=7,
        PASSWORD_HASH_SCHEME="bcrypt",
    )


@pytest.fixture(scope="session")
def test_settings(test_security_settings: SecuritySettings) -> Settings:
    return Settings(
        app=ApplicationSettings(),
        logging=LoggingSettings(),
        security=test_security_settings,
        cookies=CookieSettings(),
        database=DatabaseSettings(),
        storage=StorageSettings(),
        workers=WorkerSettings(),
    )
