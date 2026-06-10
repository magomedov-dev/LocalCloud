"""Юнит-тесты для security.dependencies.nodes."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.models.enums import SystemRole, UserStatus
from security.dependencies.auth import SecurityDependencyError
from security.dependencies.nodes import (
    get_accessible_node_dependency,
    get_node_by_id,
    get_node_permissions,
    require_node_permission_dependency,
)
from security.permissions.enums import PermissionAction


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def make_session_returning(value: object) -> AsyncMock:
    """Вернуть mock AsyncSession, у которого execute возвращает скалярное значение."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = value
    # для get_node_permissions используется scalars().all()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = value if isinstance(value, list) else []
    result_mock.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=result_mock)
    return session


def make_session_raising(exc: Exception) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=exc)
    return session


def make_node(owner_id: uuid.UUID | None = None, is_deleted: bool = False) -> MagicMock:
    from database.models.enums import NodeVisibility

    node = MagicMock()
    node.id = uuid.uuid4()
    node.owner_id = owner_id or uuid.uuid4()
    node.is_deleted = is_deleted
    node.permissions = []
    node.visibility = NodeVisibility.PRIVATE
    return node


def make_user(
    status: UserStatus = UserStatus.ACTIVE,
    role: SystemRole = SystemRole.USER,
) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.status = status
    user.role = role
    return user


# ---------------------------------------------------------------------------
# get_node_by_id
# ---------------------------------------------------------------------------


class TestGetNodeById:
    @pytest.mark.asyncio
    async def test_returns_node_when_found(self) -> None:
        node = make_node()
        session = make_session_returning(node)

        result = await get_node_by_id(session, node.id)
        assert result is node

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        session = make_session_returning(None)

        result = await get_node_by_id(session, uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_sqlalchemy_error_raises_403(self) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        session = make_session_raising(SQLAlchemyError("db error"))

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_node_by_id(session, uuid.uuid4())

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_node_permissions
# ---------------------------------------------------------------------------


class TestGetNodePermissions:
    @pytest.mark.asyncio
    async def test_returns_list_of_permissions(self) -> None:
        perm1 = MagicMock()
        perm2 = MagicMock()
        session = make_session_returning([perm1, perm2])

        result = await get_node_permissions(session, uuid.uuid4())
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_permissions(self) -> None:
        session = make_session_returning([])

        result = await get_node_permissions(session, uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_sqlalchemy_error_raises_403(self) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        session = make_session_raising(SQLAlchemyError("db failure"))

        with pytest.raises(SecurityDependencyError) as exc_info:
            await get_node_permissions(session, uuid.uuid4())

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_node_permission_dependency
# ---------------------------------------------------------------------------


class TestRequireNodePermissionDependency:
    def test_returns_callable(self) -> None:
        dep = require_node_permission_dependency(PermissionAction.READ)
        assert callable(dep)

    @pytest.mark.asyncio
    async def test_node_not_found_raises_403(self) -> None:
        dep = require_node_permission_dependency(PermissionAction.READ)
        node_id = uuid.uuid4()
        user = make_user()
        session = make_session_returning(None)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await dep(node_id=node_id, user=user, session=session)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_owner_can_read_own_node(self) -> None:
        user = make_user()
        node = make_node(owner_id=user.id)
        dep = require_node_permission_dependency(PermissionAction.READ)
        session = make_session_returning(node)

        # владелец узла должен пройти без исключения
        result = await dep(node_id=node.id, user=user, session=session)
        assert result is None

    @pytest.mark.asyncio
    async def test_anonymous_user_denied_on_private_node(self) -> None:
        """Анонимный пользователь без публичного узла должен получить 403."""
        from database.models.enums import NodeVisibility

        node = make_node()
        node.visibility = NodeVisibility.PRIVATE
        dep = require_node_permission_dependency(PermissionAction.READ)
        session = make_session_returning(node)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await dep(node_id=node.id, user=None, session=session)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_user_can_access_any_node(self) -> None:
        """Администратору всегда должен предоставляться доступ."""
        admin = make_user(role=SystemRole.ADMIN)

        node = make_node()
        dep = require_node_permission_dependency(PermissionAction.READ)
        session = make_session_returning(node)

        result = await dep(node_id=node.id, user=admin, session=session)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_owner_without_permission_raises_403(self) -> None:
        """Обычному пользователю, не владельцу и без явных прав, доступ запрещён."""
        from database.models.enums import NodeVisibility

        user = make_user()
        node = make_node()  # другой owner_id
        node.permissions = []  # нет прав
        node.visibility = NodeVisibility.PRIVATE
        dep = require_node_permission_dependency(PermissionAction.WRITE)
        session = make_session_returning(node)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await dep(node_id=node.id, user=user, session=session)

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_accessible_node_dependency
# ---------------------------------------------------------------------------


class TestGetAccessibleNodeDependency:
    def test_returns_callable(self) -> None:
        dep = get_accessible_node_dependency(PermissionAction.READ)
        assert callable(dep)

    @pytest.mark.asyncio
    async def test_node_not_found_raises_403(self) -> None:
        dep = get_accessible_node_dependency(PermissionAction.READ)
        session = make_session_returning(None)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await dep(node_id=uuid.uuid4(), user=make_user(), session=session)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_owner_gets_node_back(self) -> None:
        user = make_user()
        node = make_node(owner_id=user.id)
        dep = get_accessible_node_dependency(PermissionAction.READ)
        session = make_session_returning(node)

        result = await dep(node_id=node.id, user=user, session=session)
        assert result is node

    @pytest.mark.asyncio
    async def test_admin_gets_node_back(self) -> None:
        admin = make_user(role=SystemRole.ADMIN)
        node = make_node()
        dep = get_accessible_node_dependency(PermissionAction.READ)
        session = make_session_returning(node)

        result = await dep(node_id=node.id, user=admin, session=session)
        assert result is node

    @pytest.mark.asyncio
    async def test_anonymous_denied_on_private_node_raises_403(self) -> None:
        from database.models.enums import NodeVisibility

        node = make_node()
        node.visibility = NodeVisibility.PRIVATE
        dep = get_accessible_node_dependency(PermissionAction.READ)
        session = make_session_returning(node)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await dep(node_id=node.id, user=None, session=session)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_non_owner_without_permission_raises_403(self) -> None:
        from database.models.enums import NodeVisibility

        user = make_user()
        node = make_node()  # другой владелец
        node.permissions = []
        node.visibility = NodeVisibility.PRIVATE
        dep = get_accessible_node_dependency(PermissionAction.WRITE)
        session = make_session_returning(node)

        with pytest.raises(SecurityDependencyError) as exc_info:
            await dep(node_id=node.id, user=user, session=session)

        assert exc_info.value.status_code == 403
