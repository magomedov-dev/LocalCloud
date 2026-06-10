"""Юнит-тесты для AccessService (проверка прав доступа к узлам)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from database import DatabaseError, EntityNotFoundError
from database.models.enums import (
    NodeType,
    NodeVisibility,
    PermissionLevel,
    SystemRole,
    UserStatus,
)
from schemas.permissions import PermissionCheckRequest
from security.permissions import (
    PermissionAction,
    PermissionCheckResult,
    PermissionDeniedReason,
)
from security.permissions.exceptions import PermissionCheckError
from services.access import (
    AccessPermission,
    AccessService,
    REPOSITORY_PAGE_LIMIT,
    get_access_service,
)
from services.exceptions import (
    NotFoundServiceError,
    PermissionServiceError,
    ServiceError,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def make_uow(**repos):
    uow = AsyncMock()
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    for name, repo in repos.items():
        setattr(uow, name, repo)
    return uow


def make_factory(uow):
    return MagicMock(return_value=uow)


def make_node_mock(
    node_id=None,
    owner_id=None,
    node_type=NodeType.FOLDER,
    visibility=NodeVisibility.PRIVATE,
    is_deleted=False,
):
    node = MagicMock()
    node.id = node_id or uuid.uuid4()
    node.owner_id = owner_id or uuid.uuid4()
    node.node_type = node_type
    node.visibility = visibility
    node.is_deleted = is_deleted
    return node


def make_user_mock(user_id=None, status=UserStatus.ACTIVE, role=SystemRole.USER):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.status = status
    user.role = role
    return user


def make_nodes_repo(node):
    repo = AsyncMock()
    repo.get_required_by_id = AsyncMock(return_value=node)
    repo.get_required_active_node_by_id = AsyncMock(return_value=node)
    return repo


def make_users_repo(user):
    repo = AsyncMock()
    repo.get_required_user_by_id = AsyncMock(return_value=user)
    return repo


def make_permissions_repo(permissions=None):
    repo = AsyncMock()
    repo.get_node_permissions = AsyncMock(return_value=permissions or [])
    return repo


def make_uow_for_owner(node, user):
    """Собрать UoW, где пользователь владеет узлом (доступ разрешён)."""
    return make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo(),
    )


def make_service(uow):
    return AccessService(uow_factory=make_factory(uow))


def make_permission_mock(
    user_id,
    permission_level=PermissionLevel.READ,
    can_read=True,
    can_download=False,
    can_write=False,
    can_delete=False,
    can_share=False,
    revoked_at=None,
    expires_at=None,
):
    perm = MagicMock()
    perm.id = uuid.uuid4()
    perm.user_id = user_id
    perm.permission_level = permission_level
    perm.can_read = can_read
    perm.can_download = can_download
    perm.can_write = can_write
    perm.can_delete = can_delete
    perm.can_share = can_share
    perm.revoked_at = revoked_at
    perm.expires_at = expires_at
    return perm


# ---------------------------------------------------------------------------
# get_access_service factory
# ---------------------------------------------------------------------------


def test_get_access_service_returns_instance():
    svc = get_access_service()
    assert isinstance(svc, AccessService)


def test_get_access_service_with_factory():
    uow = make_uow()
    svc = get_access_service(uow_factory=make_factory(uow))
    assert isinstance(svc, AccessService)
    assert svc.uow_factory is not None


# ---------------------------------------------------------------------------
# check_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_access_allowed_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
    )

    assert response.allowed is True
    assert response.node_id == node.id


@pytest.mark.asyncio
async def test_check_access_denied_for_non_owner_without_permission():
    node = make_node_mock(owner_id=uuid.uuid4())
    other_user_id = uuid.uuid4()
    user = make_user_mock(user_id=other_user_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=other_user_id,
        action=PermissionAction.WRITE,
    )

    assert response.allowed is False
    assert response.message is not None


@pytest.mark.asyncio
async def test_check_access_anonymous_private_node_denied():
    node = make_node_mock(visibility=NodeVisibility.PRIVATE)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=None,
        action=PermissionAction.READ,
    )

    assert response.allowed is False


@pytest.mark.asyncio
async def test_check_access_uses_external_uow():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    # фабрика возвращает другой uow, который не должен использоваться
    service = AccessService(uow_factory=make_factory(make_uow()))

    response = await service.check_access(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
        uow=uow,
    )

    assert response.allowed is True
    uow.nodes.get_required_active_node_by_id.assert_awaited()


@pytest.mark.asyncio
async def test_check_access_database_error_propagates():
    node = make_node_mock()
    nodes_repo = AsyncMock()
    nodes_repo.get_required_active_node_by_id = AsyncMock(
        side_effect=DatabaseError("boom")
    )
    uow = make_uow(
        nodes=nodes_repo,
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.check_access(
            node_id=node.id,
            user_id=uuid.uuid4(),
            action=PermissionAction.READ,
        )


@pytest.mark.asyncio
async def test_check_access_entity_not_found_raises_not_found():
    nodes_repo = AsyncMock()
    nodes_repo.get_required_active_node_by_id = AsyncMock(
        side_effect=EntityNotFoundError("missing")
    )
    uow = make_uow(
        nodes=nodes_repo,
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    with pytest.raises(NotFoundServiceError):
        await service.check_access(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action=PermissionAction.READ,
        )


# ---------------------------------------------------------------------------
# check_node_access (точка входа через DTO)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_node_access_allowed():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    request = PermissionCheckRequest(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
    )
    response = await service.check_node_access(request, uow=uow)
    assert response.allowed is True


# ---------------------------------------------------------------------------
# require_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_access_returns_response_when_allowed():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    response = await service.require_access(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
        uow=uow,
    )
    assert response.allowed is True


@pytest.mark.asyncio
async def test_require_access_raises_permission_error_when_denied():
    node = make_node_mock(owner_id=uuid.uuid4())
    other_user_id = uuid.uuid4()
    user = make_user_mock(user_id=other_user_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.require_access(
            node_id=node.id,
            user_id=other_user_id,
            action=PermissionAction.WRITE,
            uow=uow,
        )


# ---------------------------------------------------------------------------
# get_accessible_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_accessible_node_returns_node_when_allowed():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    result = await service.get_accessible_node(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
        uow=uow,
    )
    assert result is node


@pytest.mark.asyncio
async def test_get_accessible_node_raises_permission_error_when_denied():
    node = make_node_mock(owner_id=uuid.uuid4())
    other_user_id = uuid.uuid4()
    user = make_user_mock(user_id=other_user_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.get_accessible_node(
            node_id=node.id,
            user_id=other_user_id,
            action=PermissionAction.WRITE,
            uow=uow,
        )


@pytest.mark.asyncio
async def test_get_accessible_node_without_external_uow():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    result = await service.get_accessible_node(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
    )
    assert result is node


@pytest.mark.asyncio
async def test_get_accessible_node_not_found_raises():
    nodes_repo = AsyncMock()
    nodes_repo.get_required_active_node_by_id = AsyncMock(
        side_effect=EntityNotFoundError("missing")
    )
    uow = make_uow(
        nodes=nodes_repo,
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    with pytest.raises(NotFoundServiceError):
        await service.get_accessible_node(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action=PermissionAction.READ,
            uow=uow,
        )


@pytest.mark.asyncio
async def test_get_accessible_node_database_error():
    nodes_repo = AsyncMock()
    nodes_repo.get_required_active_node_by_id = AsyncMock(
        side_effect=DatabaseError("boom")
    )
    uow = make_uow(
        nodes=nodes_repo,
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_accessible_node(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action=PermissionAction.READ,
            uow=uow,
        )


# ---------------------------------------------------------------------------
# get_effective_permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_effective_permissions_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    result = await service.get_effective_permissions(
        node_id=node.id,
        user_id=owner_id,
        uow=uow,
    )
    assert result.node_id == node.id
    assert result.is_owner is True
    assert result.can_read is True


@pytest.mark.asyncio
async def test_get_effective_permissions_database_error():
    nodes_repo = AsyncMock()
    nodes_repo.get_required_active_node_by_id = AsyncMock(
        side_effect=DatabaseError("boom")
    )
    uow = make_uow(
        nodes=nodes_repo,
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_effective_permissions(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            uow=uow,
        )


# ---------------------------------------------------------------------------
# булевы хелперы can_*
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_read_node_true_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    assert await service.can_read_node(node_id=node.id, user_id=owner_id, uow=uow) is True


@pytest.mark.asyncio
async def test_can_write_node_false_for_non_owner():
    node = make_node_mock(owner_id=uuid.uuid4())
    other_user_id = uuid.uuid4()
    user = make_user_mock(user_id=other_user_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    assert (
        await service.can_write_node(node_id=node.id, user_id=other_user_id, uow=uow)
        is False
    )


@pytest.mark.asyncio
async def test_can_download_node_true_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    assert (
        await service.can_download_node(node_id=node.id, user_id=owner_id, uow=uow)
        is True
    )


@pytest.mark.asyncio
async def test_can_delete_node_true_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    assert (
        await service.can_delete_node(node_id=node.id, user_id=owner_id, uow=uow)
        is True
    )


@pytest.mark.asyncio
async def test_can_share_node_true_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    assert (
        await service.can_share_node(node_id=node.id, user_id=owner_id, uow=uow)
        is True
    )


@pytest.mark.asyncio
async def test_can_manage_node_true_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    assert (
        await service.can_manage_node(node_id=node.id, user_id=owner_id, uow=uow)
        is True
    )


# ---------------------------------------------------------------------------
# хелперы require_*
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_read_node_allowed():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    response = await service.require_read_node(
        node_id=node.id, user_id=owner_id, uow=uow
    )
    assert response.allowed is True


@pytest.mark.asyncio
async def test_require_write_node_denied():
    node = make_node_mock(owner_id=uuid.uuid4())
    other_user_id = uuid.uuid4()
    user = make_user_mock(user_id=other_user_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.require_write_node(
            node_id=node.id, user_id=other_user_id, uow=uow
        )


@pytest.mark.asyncio
async def test_require_delete_node_allowed_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    response = await service.require_delete_node(
        node_id=node.id, user_id=owner_id, uow=uow
    )
    assert response.allowed is True


@pytest.mark.asyncio
async def test_require_share_node_allowed_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    response = await service.require_share_node(
        node_id=node.id, user_id=owner_id, uow=uow
    )
    assert response.allowed is True


@pytest.mark.asyncio
async def test_require_manage_node_allowed_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    response = await service.require_manage_node(
        node_id=node.id, user_id=owner_id, uow=uow
    )
    assert response.allowed is True


# ---------------------------------------------------------------------------
# постраничная загрузка прав / неактивный пользователь
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_access_inactive_user_denied():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id, status=UserStatus.BLOCKED)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
        uow=uow,
    )
    assert response.allowed is False


@pytest.mark.asyncio
async def test_check_access_deleted_node_denied_without_allow_deleted():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id, is_deleted=True)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
        allow_deleted=True,
        uow=uow,
    )
    # allow_deleted True -> владельцу всё ещё разрешено
    assert response.allowed is True


@pytest.mark.asyncio
async def test_load_permissions_paginates(monkeypatch):
    """Репозиторий прав опрашивается, пока не вернётся неполная страница."""
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)

    # Собрать объект, похожий на право доступа, с нужными атрибутами
    def make_perm():
        perm = MagicMock()
        perm.id = uuid.uuid4()
        perm.user_id = uuid.uuid4()
        perm.permission_level = PermissionLevel.READ
        perm.can_read = True
        perm.can_download = True
        perm.can_write = False
        perm.can_delete = False
        perm.can_share = False
        perm.revoked_at = None
        perm.expires_at = None
        return perm

    perms_repo = AsyncMock()
    # Первый вызов возвращает неполную страницу (меньше лимита) -> остановка
    perms_repo.get_node_permissions = AsyncMock(return_value=[make_perm()])

    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=perms_repo,
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
        uow=uow,
    )
    assert response.allowed is True
    perms_repo.get_node_permissions.assert_awaited()


# ---------------------------------------------------------------------------
# AccessPermission.is_active_at
# ---------------------------------------------------------------------------


def test_access_permission_active_when_not_revoked_or_expired():
    now = datetime.now(UTC)
    perm = AccessPermission(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        permission_level=PermissionLevel.READ,
        can_read=True,
        can_download=False,
        can_write=False,
        can_delete=False,
        can_share=False,
        revoked_at=None,
        expires_at=now + timedelta(hours=1),
    )
    assert perm.is_active_at(now) is True


def test_access_permission_inactive_when_revoked():
    now = datetime.now(UTC)
    perm = AccessPermission(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        permission_level=PermissionLevel.READ,
        can_read=True,
        can_download=False,
        can_write=False,
        can_delete=False,
        can_share=False,
        revoked_at=now - timedelta(hours=1),
        expires_at=None,
    )
    assert perm.is_active_at(now) is False


def test_access_permission_inactive_when_expired():
    now = datetime.now(UTC)
    perm = AccessPermission(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        permission_level=PermissionLevel.READ,
        can_read=True,
        can_download=False,
        can_write=False,
        can_delete=False,
        can_share=False,
        revoked_at=None,
        expires_at=now - timedelta(hours=1),
    )
    assert perm.is_active_at(now) is False


# ---------------------------------------------------------------------------
# разрешение доступа: прямое право / наследование / общий / публичный
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_access_granted_via_direct_permission():
    node = make_node_mock(owner_id=uuid.uuid4(), visibility=NodeVisibility.SHARED)
    grantee_id = uuid.uuid4()
    user = make_user_mock(user_id=grantee_id)
    perm = make_permission_mock(
        grantee_id,
        permission_level=PermissionLevel.WRITE,
        can_read=True,
        can_write=True,
    )
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo([perm]),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=grantee_id,
        action=PermissionAction.WRITE,
        uow=uow,
    )
    assert response.allowed is True
    assert response.permission_level == PermissionLevel.WRITE


@pytest.mark.asyncio
async def test_check_access_denied_when_permission_revoked():
    node = make_node_mock(owner_id=uuid.uuid4(), visibility=NodeVisibility.SHARED)
    grantee_id = uuid.uuid4()
    user = make_user_mock(user_id=grantee_id)
    perm = make_permission_mock(
        grantee_id,
        can_read=True,
        revoked_at=datetime.now(UTC) - timedelta(hours=1),
    )
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo([perm]),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=grantee_id,
        action=PermissionAction.READ,
        uow=uow,
    )
    assert response.allowed is False


@pytest.mark.asyncio
async def test_check_access_denied_when_permission_expired():
    node = make_node_mock(owner_id=uuid.uuid4(), visibility=NodeVisibility.SHARED)
    grantee_id = uuid.uuid4()
    user = make_user_mock(user_id=grantee_id)
    perm = make_permission_mock(
        grantee_id,
        can_read=True,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo([perm]),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=grantee_id,
        action=PermissionAction.READ,
        uow=uow,
    )
    assert response.allowed is False


@pytest.mark.asyncio
async def test_check_access_denied_insufficient_permission_level():
    node = make_node_mock(owner_id=uuid.uuid4(), visibility=NodeVisibility.SHARED)
    grantee_id = uuid.uuid4()
    user = make_user_mock(user_id=grantee_id)
    perm = make_permission_mock(
        grantee_id,
        permission_level=PermissionLevel.READ,
        can_read=True,
        can_write=False,
    )
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo([perm]),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=grantee_id,
        action=PermissionAction.WRITE,
        uow=uow,
    )
    assert response.allowed is False
    assert response.message is not None


@pytest.mark.asyncio
async def test_check_access_public_node_anonymous_read_allowed():
    node = make_node_mock(owner_id=uuid.uuid4(), visibility=NodeVisibility.PUBLIC)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=None,
        action=PermissionAction.READ,
        uow=uow,
    )
    assert response.allowed is True


@pytest.mark.asyncio
async def test_check_access_public_node_ignored_when_allow_public_false():
    node = make_node_mock(owner_id=uuid.uuid4(), visibility=NodeVisibility.PUBLIC)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=None,
        action=PermissionAction.READ,
        allow_public=False,
        uow=uow,
    )
    assert response.allowed is False
    assert response.denied_reason == PermissionDeniedReason.ANONYMOUS_USER


@pytest.mark.asyncio
async def test_check_access_admin_role_allowed():
    node = make_node_mock(owner_id=uuid.uuid4())
    admin_id = uuid.uuid4()
    user = make_user_mock(user_id=admin_id, role=SystemRole.ADMIN)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=admin_id,
        action=PermissionAction.DELETE,
        uow=uow,
    )
    assert response.allowed is True
    uow.users.get_required_user_by_id.assert_awaited()


# ---------------------------------------------------------------------------
# get_effective_permissions: ветки источника shared / public / granted (_allows)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_effective_permissions_public_node_anonymous():
    node = make_node_mock(owner_id=uuid.uuid4(), visibility=NodeVisibility.PUBLIC)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    result = await service.get_effective_permissions(
        node_id=node.id,
        user_id=None,
        uow=uow,
    )
    assert result.is_public is True
    assert result.can_read is True
    assert result.can_download is True
    assert result.can_write is False
    assert result.can_delete is False
    assert result.can_share is False


@pytest.mark.asyncio
async def test_get_effective_permissions_granted_permission_level():
    node = make_node_mock(owner_id=uuid.uuid4(), visibility=NodeVisibility.SHARED)
    grantee_id = uuid.uuid4()
    user = make_user_mock(user_id=grantee_id)
    perm = make_permission_mock(
        grantee_id,
        permission_level=PermissionLevel.WRITE,
        can_read=True,
        can_download=True,
        can_write=True,
    )
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo([perm]),
    )
    service = make_service(uow)

    result = await service.get_effective_permissions(
        node_id=node.id,
        user_id=grantee_id,
        uow=uow,
    )
    assert result.is_owner is False
    assert result.permission_level == PermissionLevel.WRITE
    assert result.can_read is True
    assert result.can_write is True
    assert result.can_delete is False
    assert result.can_share is False


@pytest.mark.asyncio
async def test_get_effective_permissions_denied_all_false():
    node = make_node_mock(owner_id=uuid.uuid4(), visibility=NodeVisibility.PRIVATE)
    other_id = uuid.uuid4()
    user = make_user_mock(user_id=other_id)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    result = await service.get_effective_permissions(
        node_id=node.id,
        user_id=other_id,
        uow=uow,
    )
    assert result.can_read is False
    assert result.can_download is False
    assert result.can_write is False
    assert result.can_delete is False
    assert result.can_share is False


# ---------------------------------------------------------------------------
# хелпер require_download_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_download_node_allowed_for_owner():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    response = await service.require_download_node(
        node_id=node.id, user_id=owner_id, uow=uow
    )
    assert response.allowed is True


# ---------------------------------------------------------------------------
# Постраничность: полная страница, за которой следует неполная
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_permissions_paginates_multiple_pages():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    user = make_user_mock(user_id=owner_id)

    full_page = [
        make_permission_mock(uuid.uuid4()) for _ in range(REPOSITORY_PAGE_LIMIT)
    ]
    short_page = [make_permission_mock(uuid.uuid4())]

    perms_repo = AsyncMock()
    perms_repo.get_node_permissions = AsyncMock(side_effect=[full_page, short_page])

    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=perms_repo,
    )
    service = make_service(uow)

    response = await service.check_access(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
        uow=uow,
    )
    assert response.allowed is True
    assert perms_repo.get_node_permissions.await_count == 2
    # второй вызов должен использовать следующее смещение
    second_call = perms_repo.get_node_permissions.await_args_list[1]
    assert second_call.kwargs["offset"] == REPOSITORY_PAGE_LIMIT


# ---------------------------------------------------------------------------
# Оборачивание ошибок: PermissionCheckError и непредвиденные исключения
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_access_wraps_permission_check_error(monkeypatch):
    node = make_node_mock(owner_id=uuid.uuid4())
    user_id = uuid.uuid4()
    user = make_user_mock(user_id=user_id)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    def _raise(**_kwargs):
        raise PermissionCheckError("bad action")

    monkeypatch.setattr("services.access.check_node_permission", _raise)

    with pytest.raises(PermissionServiceError):
        await service.check_access(
            node_id=node.id,
            user_id=user_id,
            action=PermissionAction.READ,
            uow=uow,
        )


@pytest.mark.asyncio
async def test_check_access_wraps_unexpected_error():
    node = make_node_mock(owner_id=uuid.uuid4())
    nodes_repo = AsyncMock()
    nodes_repo.get_required_active_node_by_id = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    uow = make_uow(
        nodes=nodes_repo,
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.check_access(
            node_id=node.id,
            user_id=uuid.uuid4(),
            action=PermissionAction.READ,
            uow=uow,
        )


@pytest.mark.asyncio
async def test_get_effective_permissions_wraps_permission_check_error(monkeypatch):
    node = make_node_mock(owner_id=uuid.uuid4())
    user_id = uuid.uuid4()
    user = make_user_mock(user_id=user_id)
    uow = make_uow(
        nodes=make_nodes_repo(node),
        users=make_users_repo(user),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    def _raise(**_kwargs):
        raise PermissionCheckError("bad action")

    monkeypatch.setattr("services.access.check_node_permission", _raise)

    with pytest.raises(PermissionServiceError):
        await service.get_effective_permissions(
            node_id=node.id,
            user_id=user_id,
            uow=uow,
        )


@pytest.mark.asyncio
async def test_get_effective_permissions_wraps_unexpected_error():
    nodes_repo = AsyncMock()
    nodes_repo.get_required_active_node_by_id = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    uow = make_uow(
        nodes=nodes_repo,
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_effective_permissions(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            uow=uow,
        )


@pytest.mark.asyncio
async def test_get_accessible_node_wraps_unexpected_error():
    nodes_repo = AsyncMock()
    nodes_repo.get_required_active_node_by_id = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    uow = make_uow(
        nodes=nodes_repo,
        users=make_users_repo(make_user_mock()),
        permissions=make_permissions_repo(),
    )
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_accessible_node(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action=PermissionAction.READ,
            uow=uow,
        )


# ---------------------------------------------------------------------------
# get_accessible_node без внешнего uow (ветка отказа own_uow)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_accessible_node_own_uow_denied():
    node = make_node_mock(owner_id=uuid.uuid4())
    other_user_id = uuid.uuid4()
    user = make_user_mock(user_id=other_user_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.get_accessible_node(
            node_id=node.id,
            user_id=other_user_id,
            action=PermissionAction.WRITE,
        )


# ---------------------------------------------------------------------------
# Защитные ветки при None-результате (требуют мокинга функции проверки)
# ---------------------------------------------------------------------------


def _result_with_node(node_id, *, allowed=True):
    return PermissionCheckResult(
        allowed=allowed,
        action=PermissionAction.READ,
        node_id=node_id,
        user_id=None,
        is_owner=True,
        permission_level=PermissionLevel.OWNER,
    )


@pytest.mark.asyncio
async def test_check_access_raises_when_result_is_none(monkeypatch):
    node = make_node_mock(owner_id=uuid.uuid4())
    owner_id = node.owner_id
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    monkeypatch.setattr(
        "services.access.check_node_permission", lambda **_kw: None
    )

    with pytest.raises(ServiceError):
        await service.check_access(
            node_id=node.id,
            user_id=owner_id,
            action=PermissionAction.READ,
            uow=uow,
        )


@pytest.mark.asyncio
async def test_require_node_id_raises_when_missing(monkeypatch):
    node = make_node_mock(owner_id=uuid.uuid4())
    owner_id = node.owner_id
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    result = PermissionCheckResult(
        allowed=True,
        action=PermissionAction.READ,
        node_id=None,
        user_id=owner_id,
        is_owner=True,
        permission_level=PermissionLevel.OWNER,
    )
    monkeypatch.setattr(
        "services.access.check_node_permission", lambda **_kw: result
    )

    # _require_node_id бросает PermissionDeniedError -> оборачивается в PermissionServiceError
    with pytest.raises(PermissionServiceError):
        await service.check_access(
            node_id=node.id,
            user_id=owner_id,
            action=PermissionAction.READ,
            uow=uow,
        )


@pytest.mark.asyncio
async def test_get_effective_permissions_reraises_service_error(monkeypatch):
    node = make_node_mock(owner_id=uuid.uuid4())
    owner_id = node.owner_id
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    sentinel = ServiceError("sentinel", service="access", operation="x")

    def _raise(**_kwargs):
        raise sentinel

    monkeypatch.setattr("services.access.check_node_permission", _raise)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_effective_permissions(
            node_id=node.id,
            user_id=owner_id,
            uow=uow,
        )
    # чистый ServiceError должен пробрасываться без повторного оборачивания
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_check_response_denied_reason_none_uses_default_message(monkeypatch):
    node = make_node_mock(owner_id=uuid.uuid4())
    owner_id = node.owner_id
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    # отказ без причины -> ветка по умолчанию _message_for_denied_reason(None)
    result = PermissionCheckResult(
        allowed=False,
        action=PermissionAction.READ,
        node_id=node.id,
        user_id=owner_id,
        reason=None,
    )
    monkeypatch.setattr(
        "services.access.check_node_permission", lambda **_kw: result
    )

    response = await service.check_access(
        node_id=node.id,
        user_id=owner_id,
        action=PermissionAction.READ,
        uow=uow,
    )
    assert response.allowed is False
    assert response.message == "Недостаточно прав для доступа к узлу."


@pytest.mark.asyncio
async def test_effective_permissions_allowed_without_permission_level(monkeypatch):
    """_allows откатывается к совпадению по действию, когда permission_level None."""
    node = make_node_mock(owner_id=uuid.uuid4())
    owner_id = node.owner_id
    user = make_user_mock(user_id=owner_id)
    uow = make_uow_for_owner(node, user)
    service = make_service(uow)

    # разрешено, не владелец/админ, нет публичного источника, нет permission_level:
    # совпадает только действие READ -> can_read True, остальные False.
    result = PermissionCheckResult(
        allowed=True,
        action=PermissionAction.READ,
        node_id=node.id,
        user_id=owner_id,
        is_owner=False,
        is_admin=False,
        permission_level=None,
        details={"source": "node_permission"},
    )
    monkeypatch.setattr(
        "services.access.check_node_permission", lambda **_kw: result
    )

    effective = await service.get_effective_permissions(
        node_id=node.id,
        user_id=owner_id,
        uow=uow,
    )
    assert effective.can_read is True
    assert effective.can_download is False
    assert effective.can_write is False
    assert effective.can_delete is False
    assert effective.can_share is False
