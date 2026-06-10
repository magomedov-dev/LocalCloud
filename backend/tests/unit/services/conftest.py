"""Общие фикстуры и хелперы для юнит-тестов сервисов."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.models.enums import SessionStatus, UserStatus


# ---------------------------------------------------------------------------
# Хелперы для фабрики UoW
# ---------------------------------------------------------------------------


def make_uow_mock(**repos: Any) -> AsyncMock:
    """Создать мок UoW с указанными моками репозиториев."""
    uow = AsyncMock()
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()
    uow.flush_and_refresh = AsyncMock(side_effect=lambda obj: obj)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    for repo_name, repo_mock in repos.items():
        setattr(uow, repo_name, repo_mock)
    return uow


def make_uow_factory(uow: AsyncMock) -> MagicMock:
    """Создать вызываемую фабрику, возвращающую переданный UoW."""
    factory = MagicMock(return_value=uow)
    return factory


# ---------------------------------------------------------------------------
# Мок сервиса аудита
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_service() -> MagicMock:
    """Фикстура мока сервиса аудита с async-методами логирования."""
    svc = MagicMock()
    svc.log_user_event = AsyncMock()
    svc.log_system_event = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# Фабрика мока пользователя
# ---------------------------------------------------------------------------


def make_user_mock(
    *,
    user_id: uuid.UUID | None = None,
    email: str = "user@example.com",
    username: str = "testuser",
    status: UserStatus = UserStatus.ACTIVE,
    password_hash: str = "",
    last_login_at: datetime | None = None,
) -> MagicMock:
    """Вернуть мок, имитирующий ORM-модель User."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = email
    user.username = username
    user.status = status
    user.password_hash = password_hash
    user.last_login_at = last_login_at
    user.approved_at = None
    user.blocked_at = None
    user.rejected_at = None
    user.deleted_at = None
    user.block_reason = None
    user.rejection_reason = None
    user.created_at = datetime.now(UTC)
    user.updated_at = datetime.now(UTC)
    user.can_login = status == UserStatus.ACTIVE
    return user


# ---------------------------------------------------------------------------
# Фабрика мока refresh-токена
# ---------------------------------------------------------------------------


def make_token_mock(
    *,
    token_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    status: SessionStatus = SessionStatus.ACTIVE,
    can_be_used: bool = True,
    expires_at: datetime | None = None,
) -> MagicMock:
    """Вернуть мок, имитирующий ORM-модель RefreshToken."""
    token = MagicMock()
    token.id = token_id or uuid.uuid4()
    token.user_id = user_id or uuid.uuid4()
    token.status = status
    token.expires_at = expires_at or datetime.now(UTC)
    token.revoked_at = None
    token.revoke_reason = None
    token.replaced_by_token_id = None
    token.parent_token_id = None
    token.ip_address = None
    token.user_agent = None
    token.device_name = None
    token.created_at = datetime.now(UTC)
    token.can_be_used_at = MagicMock(return_value=can_be_used)
    return token
