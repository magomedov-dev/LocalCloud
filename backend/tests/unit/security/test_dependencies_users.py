"""Юнит-тесты для security.dependencies.users."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.models.enums import SystemRole, UserStatus
from security.dependencies.auth import SecurityDependencyError
from security.dependencies.users import (
    get_current_active_user,
    get_current_admin_user,
    get_current_user,
    get_current_user_from_refresh_token,
    get_optional_active_user,
    get_optional_current_user,
    get_user_by_id,
    require_active_authenticated_user,
    require_admin_user,
    require_authenticated_user,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def make_user(
    status: UserStatus = UserStatus.ACTIVE,
    role: SystemRole = SystemRole.USER,
) -> MagicMock:
    """Создать mock ORM-объекта User."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.status = status
    user.role = role
    return user


def make_admin_user() -> MagicMock:
    """Создать mock пользователя с ролью администратора."""
    return make_user(role=SystemRole.ADMIN)


def make_payload(user_id: uuid.UUID | None = None) -> MagicMock:
    payload = MagicMock()
    payload.user_id = user_id or uuid.uuid4()
    return payload


# ---------------------------------------------------------------------------
# get_user_by_id
# ---------------------------------------------------------------------------


class TestGetUserById:
    @pytest.mark.asyncio
    async def test_returns_user_when_found(self) -> None:
        user = make_user()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result_mock)

        found = await get_user_by_id(session, user.id)
        assert found is user

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        found = await get_user_by_id(session, uuid.uuid4())
        assert found is None

    @pytest.mark.asyncio
    async def test_sqlalchemy_error_raises_401(self) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=SQLAlchemyError("db failure"))

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_user_by_id(session, uuid.uuid4())

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_returns_user_when_found(self) -> None:
        user = make_user()
        payload = make_payload(user_id=user.id)
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result_mock)

        found = await get_current_user(payload, session)
        assert found is user

    @pytest.mark.asyncio
    async def test_raises_401_when_user_not_found(self) -> None:
        payload = make_payload()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_current_user(payload, session)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_optional_current_user
# ---------------------------------------------------------------------------


class TestGetOptionalCurrentUser:
    @pytest.mark.asyncio
    async def test_returns_none_when_payload_is_none(self) -> None:
        session = AsyncMock()
        result = await get_optional_current_user(None, session)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_when_found(self) -> None:
        user = make_user()
        payload = make_payload(user_id=user.id)
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result_mock)

        found = await get_optional_current_user(payload, session)
        assert found is user

    @pytest.mark.asyncio
    async def test_raises_401_when_payload_present_but_user_not_found(self) -> None:
        payload = make_payload()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_optional_current_user(payload, session)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user_from_refresh_token
# ---------------------------------------------------------------------------


class TestGetCurrentUserFromRefreshToken:
    @pytest.mark.asyncio
    async def test_returns_user_when_found(self) -> None:
        user = make_user()
        payload = make_payload(user_id=user.id)
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=result_mock)

        found = await get_current_user_from_refresh_token(payload, session)
        assert found is user

    @pytest.mark.asyncio
    async def test_raises_401_when_user_not_found(self) -> None:
        payload = make_payload()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_current_user_from_refresh_token(payload, session)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_active_user
# ---------------------------------------------------------------------------


class TestGetCurrentActiveUser:
    @pytest.mark.asyncio
    async def test_active_user_is_returned(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        result = await get_current_active_user(user)
        assert result is user

    @pytest.mark.asyncio
    async def test_blocked_user_raises_403(self) -> None:
        user = make_user(status=UserStatus.BLOCKED)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_current_active_user(user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_pending_user_raises_403(self) -> None:
        user = make_user(status=UserStatus.PENDING)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_current_active_user(user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_deleted_user_raises_403(self) -> None:
        user = make_user(status=UserStatus.DELETED)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_current_active_user(user)

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_optional_active_user
# ---------------------------------------------------------------------------


class TestGetOptionalActiveUser:
    @pytest.mark.asyncio
    async def test_returns_none_when_user_is_none(self) -> None:
        result = await get_optional_active_user(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_active_user(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        result = await get_optional_active_user(user)
        assert result is user

    @pytest.mark.asyncio
    async def test_inactive_user_raises_403(self) -> None:
        user = make_user(status=UserStatus.BLOCKED)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_optional_active_user(user)

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_current_admin_user
# ---------------------------------------------------------------------------


class TestGetCurrentAdminUser:
    @pytest.mark.asyncio
    async def test_admin_user_is_returned(self) -> None:
        user = make_admin_user()
        result = await get_current_admin_user(user)
        assert result is user

    @pytest.mark.asyncio
    async def test_non_admin_raises_403(self) -> None:
        user = make_user()  # без роли администратора

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_current_admin_user(user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_inactive_admin_user_raises_403(self) -> None:
        # даже если у пользователя роль admin, при status=BLOCKED должна быть ошибка
        user = make_user(status=UserStatus.BLOCKED, role=SystemRole.ADMIN)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_current_admin_user(user)

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Проброс пользователя (pass-through helpers)
# ---------------------------------------------------------------------------


class TestPassThroughHelpers:
    def test_require_authenticated_user_returns_user(self) -> None:
        user = make_user()
        result = require_authenticated_user(user)
        assert result is user

    def test_require_active_authenticated_user_returns_user(self) -> None:
        user = make_user()
        result = require_active_authenticated_user(user)
        assert result is user

    def test_require_admin_user_returns_user(self) -> None:
        user = make_admin_user()
        result = require_admin_user(user)
        assert result is user
