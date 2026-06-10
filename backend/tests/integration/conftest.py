"""Общие фикстуры для интеграционных тестов."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from database.models.enums import SystemRole, UserStatus
from security.dependencies.users import get_current_active_user

API_V1 = "/api/v1"


async def _mock_db_session_gen() -> AsyncGenerator[Any, None]:
    """Отдаёт mock-сессию БД, чтобы избежать реальных подключений к базе."""
    yield AsyncMock()


@pytest.fixture(autouse=True)
def _mock_app_lifecycle() -> Generator[None, None, None]:
    """Не даёт TestClient подключаться к реальной БД/хранилищу при старте."""
    from database.client import get_db_session

    with (
        patch("app.main.startup_backend", new_callable=AsyncMock),
        patch("app.main.shutdown_backend", new_callable=AsyncMock),
    ):
        app.dependency_overrides[get_db_session] = _mock_db_session_gen
        yield
        app.dependency_overrides.pop(get_db_session, None)


def _make_mock_user(
    *,
    user_id: uuid.UUID | None = None,
    email: str = "test@example.com",
    username: str = "testuser",
    status: UserStatus = UserStatus.ACTIVE,
    role: SystemRole = SystemRole.USER,
) -> MagicMock:
    """Создаёт mock ORM-объект User для подмены зависимости аутентификации."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = email
    user.username = username
    user.status = status
    user.last_login_at = None
    user.approved_at = None
    user.blocked_at = None
    user.rejected_at = None
    user.deleted_at = None
    user.block_reason = None
    user.rejection_reason = None
    user.created_at = datetime.now(tz=timezone.utc)
    user.updated_at = datetime.now(tz=timezone.utc)
    user.role = role
    user.__class__.__name__ = "User"
    return user


@pytest.fixture
def mock_user() -> MagicMock:
    """Возвращает mock активного пользователя."""
    return _make_mock_user()


@pytest.fixture
def mock_admin_user() -> MagicMock:
    """Возвращает mock администратора с ролью admin."""
    return _make_mock_user(role=SystemRole.ADMIN)


@pytest.fixture
def client(mock_user: MagicMock) -> Generator[TestClient, None, None]:
    """TestClient с подменой аутентификации на mock активного пользователя."""
    app.dependency_overrides[get_current_active_user] = lambda: mock_user
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(mock_admin_user: MagicMock) -> Generator[TestClient, None, None]:
    """TestClient с подменой аутентификации на администратора."""
    app.dependency_overrides[get_current_active_user] = lambda: mock_admin_user
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client() -> Generator[TestClient, None, None]:
    """TestClient без подмены аутентификации (проверка поведения 401)."""
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
