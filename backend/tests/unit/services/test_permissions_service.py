"""Юнит-тесты для PermissionsService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from database import DatabaseError
from database.models.enums import NodeType, NodeVisibility, PermissionLevel
from schemas.permissions import (
    EffectivePermissionRead,
    PermissionCheckRequest,
    PermissionCheckResponse,
    PermissionGrantRequest,
    PermissionRevokeRequest,
    PermissionUpdateRequest,
)
from security.permissions import PermissionAction
from services.exceptions import (
    NotFoundServiceError,
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
)
from services.permissions import (
    PermissionsService,
    _apply_permission_update,
    _empty_result_error,
    _jsonable,
    _validate_limit,
    get_permissions_service,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def make_uow(**repos):
    uow = AsyncMock()
    uow.commit = AsyncMock()
    uow.flush = AsyncMock()
    uow.refresh = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    for name, repo in repos.items():
        setattr(uow, name, repo)
    return uow


def make_factory(uow):
    return MagicMock(return_value=uow)


def make_audit():
    svc = MagicMock()
    svc.log_user_event = AsyncMock()
    svc.log_system_event = AsyncMock()
    svc.log_event = AsyncMock()
    return svc


def make_node_mock(node_id=None, owner_id=None):
    node = MagicMock()
    node.id = node_id or uuid.uuid4()
    node.owner_id = owner_id or uuid.uuid4()
    node.parent_id = None
    node.name = "test-node"
    node.node_type = NodeType.FOLDER
    node.visibility = NodeVisibility.PRIVATE
    node.path = "/test-node"
    node.depth = 1
    node.is_deleted = False
    node.created_at = datetime.now(UTC)
    node.updated_at = datetime.now(UTC)
    return node


def make_permission_mock(
    permission_id=None,
    node_id=None,
    user_id=None,
    actor_id=None,
    can_read=True,
    can_write=False,
):
    perm = MagicMock()
    perm.id = permission_id or uuid.uuid4()
    perm.node_id = node_id or uuid.uuid4()
    perm.user_id = user_id or uuid.uuid4()
    perm.subject_type = "user"
    perm.permission_level = PermissionLevel.READ
    perm.granted_by = actor_id or uuid.uuid4()
    perm.can_read = can_read
    perm.can_download = True
    perm.can_write = can_write
    perm.can_delete = False
    perm.can_share = False
    perm.expires_at = None
    perm.revoked_at = None
    perm.revoke_reason = None
    perm.created_at = datetime.now(UTC)
    return perm


def make_access(node=None):
    svc = MagicMock()
    svc.get_accessible_node = AsyncMock(return_value=node or make_node_mock())
    svc.require_access = AsyncMock()
    return svc


def make_permissions_service(uow, access_svc=None, audit_svc=None):
    return PermissionsService(
        uow_factory=make_factory(uow),
        access_service=access_svc or make_access(),
        audit_service=audit_svc or make_audit(),
    )


# ---------------------------------------------------------------------------
# Тесты: grant_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_permission_returns_node_permission_read():
    """grant_permission возвращает NodePermissionRead при успехе."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    target_user_id = uuid.uuid4()
    owner_id = uuid.uuid4()  # отличается от цели

    node = make_node_mock(node_id=node_id, owner_id=owner_id)
    perm = make_permission_mock(node_id=node_id, user_id=target_user_id, actor_id=actor_id)
    perm.permission_level = PermissionLevel.READ

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=MagicMock(id=target_user_id))

    permissions_repo = AsyncMock()
    permissions_repo.grant_permission = AsyncMock(return_value=perm)

    access = make_access(node=node)
    uow = make_uow(users=users_repo, permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    data = PermissionGrantRequest(
        node_id=node_id,
        user_id=target_user_id,
        can_read=True,
        can_download=True,
        can_write=False,
        can_delete=False,
        can_share=False,
    )
    result = await service.grant_permission(data, actor_id=actor_id)

    assert result is not None
    assert str(result.node_id) == str(node_id)
    permissions_repo.grant_permission.assert_called_once()


@pytest.mark.asyncio
async def test_grant_permission_to_owner_raises_validation_error():
    """grant_permission вызывает ValidationServiceError, когда цель — владелец."""
    actor_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    node_id = uuid.uuid4()

    # Владелец — целевой пользователь
    node = make_node_mock(node_id=node_id, owner_id=owner_id)
    perm = make_permission_mock(node_id=node_id, user_id=owner_id)

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=MagicMock(id=owner_id))

    permissions_repo = AsyncMock()
    permissions_repo.grant_permission = AsyncMock(return_value=perm)

    access = make_access(node=node)
    uow = make_uow(users=users_repo, permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    data = PermissionGrantRequest(
        node_id=node_id,
        user_id=owner_id,  # нацелено на владельца
        can_read=True,
        can_download=True,
        can_write=False,
        can_delete=False,
        can_share=False,
    )

    with pytest.raises(ValidationServiceError):
        await service.grant_permission(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_grant_permission_access_denied_raises_permission_error():
    """grant_permission вызывает PermissionServiceError, когда у актора нет права SHARE."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    target_user_id = uuid.uuid4()

    access = MagicMock()
    access.get_accessible_node = AsyncMock(
        side_effect=PermissionServiceError(
            "No share access",
            user_id=actor_id,
            resource_type="node",
            resource_id=node_id,
            action="share",
        )
    )
    uow = make_uow()
    service = make_permissions_service(uow, access_svc=access)

    data = PermissionGrantRequest(
        node_id=node_id,
        user_id=target_user_id,
        can_read=True,
        can_download=True,
        can_write=False,
        can_delete=False,
        can_share=False,
    )

    with pytest.raises(PermissionServiceError):
        await service.grant_permission(data, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: revoke_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_permission_returns_updated_permission():
    """revoke_permission помечает право отозванным и возвращает его."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()
    node_id = uuid.uuid4()

    perm = make_permission_mock(permission_id=perm_id, node_id=node_id)
    perm.revoke = MagicMock()  # метод, который устанавливает revoked_at

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(return_value=perm)
    permissions_repo.get_permission_by_node_user = AsyncMock(return_value=perm)

    access = make_access()
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    data = PermissionRevokeRequest(permission_id=perm_id)
    result = await service.revoke_permission(data, actor_id=actor_id)

    assert result is not None


# ---------------------------------------------------------------------------
# Тесты: get_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_permission_returns_node_permission_read():
    """get_permission возвращает NodePermissionRead для существующего права."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()
    node_id = uuid.uuid4()
    perm = make_permission_mock(permission_id=perm_id, node_id=node_id)

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(return_value=perm)

    access = make_access()
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    result = await service.get_permission(perm_id, actor_id=actor_id)

    assert result is not None
    assert str(result.id) == str(perm_id)


@pytest.mark.asyncio
async def test_get_permission_raises_not_found_when_missing():
    """get_permission вызывает NotFoundServiceError, когда право не существует."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(return_value=None)

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    with pytest.raises(NotFoundServiceError):
        await service.get_permission(perm_id, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: list_node_permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_node_permissions_returns_page():
    """list_node_permissions возвращает PageResponse с правами."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    perm = make_permission_mock(node_id=node_id)

    permissions_repo = AsyncMock()
    permissions_repo.get_node_permissions = AsyncMock(return_value=[perm])
    permissions_repo.count_node_permissions = AsyncMock(return_value=1)

    access = make_access()
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    result = await service.list_node_permissions(
        node_id=node_id,
        actor_id=actor_id,
    )

    assert result is not None
    assert result.meta.total == 1
    assert len(result.items) == 1


# ---------------------------------------------------------------------------
# Тесты: grant_permission — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_permission_wraps_database_error():
    """grant_permission преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    target_user_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=uuid.uuid4())

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(
        side_effect=DatabaseError("db down")
    )
    permissions_repo = AsyncMock()
    access = make_access(node=node)
    uow = make_uow(users=users_repo, permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    data = PermissionGrantRequest(
        node_id=node_id,
        user_id=target_user_id,
        can_read=True,
        can_download=True,
    )

    with pytest.raises(ServiceError) as exc_info:
        await service.grant_permission(data, actor_id=actor_id)
    assert exc_info.value.operation == "grant_permission"


@pytest.mark.asyncio
async def test_grant_permission_wraps_unexpected_error():
    """grant_permission преобразует непредвиденную ошибку в ServiceError."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    target_user_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=uuid.uuid4())

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    permissions_repo = AsyncMock()
    access = make_access(node=node)
    uow = make_uow(users=users_repo, permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    data = PermissionGrantRequest(
        node_id=node_id,
        user_id=target_user_id,
        can_read=True,
    )

    with pytest.raises(ServiceError) as exc_info:
        await service.grant_permission(data, actor_id=actor_id)
    assert exc_info.value.operation == "grant_permission"


@pytest.mark.asyncio
async def test_grant_permission_logs_audit_event():
    """grant_permission записывает событие аудита после успешной выдачи права."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    target_user_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=uuid.uuid4())
    perm = make_permission_mock(
        node_id=node_id, user_id=target_user_id, actor_id=actor_id
    )

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(
        return_value=MagicMock(id=target_user_id)
    )
    permissions_repo = AsyncMock()
    permissions_repo.grant_permission = AsyncMock(return_value=perm)

    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(users=users_repo, permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access, audit_svc=audit)

    data = PermissionGrantRequest(
        node_id=node_id, user_id=target_user_id, can_read=True
    )
    await service.grant_permission(data, actor_id=actor_id)

    audit.log_event.assert_awaited_once()


# ---------------------------------------------------------------------------
# Тесты: update_permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_permission_by_id_returns_updated():
    """update_permission разрешает по permission_id и применяет изменения."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()
    node_id = uuid.uuid4()
    perm = make_permission_mock(permission_id=perm_id, node_id=node_id)
    perm.sync_permission_level_from_flags = MagicMock()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(return_value=perm)

    access = make_access()
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    data = PermissionUpdateRequest(permission_id=perm_id, can_write=True)
    result = await service.update_permission(data, actor_id=actor_id)

    assert result is not None
    assert perm.can_write is True
    perm.sync_permission_level_from_flags.assert_called_once()
    access.require_access.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_permission_with_explicit_level_and_expiry():
    """update_permission применяет явный уровень и expires_at."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()
    node_id = uuid.uuid4()
    perm = make_permission_mock(permission_id=perm_id, node_id=node_id)
    perm.sync_permission_level_from_flags = MagicMock()
    expires = datetime.now(UTC)

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(return_value=perm)

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    data = PermissionUpdateRequest(
        permission_id=perm_id,
        permission_level=PermissionLevel.WRITE,
        can_read=True,
        can_download=True,
        can_write=True,
        can_delete=True,
        can_share=True,
        expires_at=expires,
    )
    result = await service.update_permission(data, actor_id=actor_id)

    assert result is not None
    assert perm.permission_level == PermissionLevel.WRITE
    assert perm.expires_at == expires
    perm.sync_permission_level_from_flags.assert_not_called()


@pytest.mark.asyncio
async def test_update_permission_empty_flags_raises_validation():
    """update_permission вызывает ValidationServiceError, когда не разрешено ни одно действие."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()
    perm = make_permission_mock(permission_id=perm_id)
    perm.sync_permission_level_from_flags = MagicMock()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(return_value=perm)

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    data = PermissionUpdateRequest(
        permission_id=perm_id,
        can_read=False,
        can_download=False,
        can_write=False,
        can_delete=False,
        can_share=False,
    )

    with pytest.raises(ValidationServiceError):
        await service.update_permission(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_update_permission_not_found_raises():
    """update_permission вызывает NotFoundServiceError, когда право отсутствует."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(return_value=None)

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    data = PermissionUpdateRequest(permission_id=perm_id, can_read=True)

    with pytest.raises(NotFoundServiceError):
        await service.update_permission(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_update_permission_wraps_database_error():
    """update_permission преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(
        side_effect=DatabaseError("db")
    )

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    data = PermissionUpdateRequest(permission_id=perm_id, can_read=True)

    with pytest.raises(ServiceError) as exc_info:
        await service.update_permission(data, actor_id=actor_id)
    assert exc_info.value.operation == "update_permission"


# ---------------------------------------------------------------------------
# Тесты: revoke_permission (more)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_permission_reraises_service_error():
    """update_permission пробрасывает ServiceError из require_access."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()
    perm = make_permission_mock(permission_id=perm_id)

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(return_value=perm)

    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied")
    )
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    data = PermissionUpdateRequest(permission_id=perm_id, can_read=True)

    with pytest.raises(PermissionServiceError):
        await service.update_permission(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_update_permission_wraps_unexpected_error():
    """update_permission преобразует непредвиденную ошибку в ServiceError."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    data = PermissionUpdateRequest(permission_id=perm_id, can_read=True)

    with pytest.raises(ServiceError) as exc_info:
        await service.update_permission(data, actor_id=actor_id)
    assert exc_info.value.operation == "update_permission"


@pytest.mark.asyncio
async def test_revoke_permission_by_node_and_user():
    """revoke_permission разрешает по паре node_id/user_id, когда id не задан."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    target_user_id = uuid.uuid4()
    perm = make_permission_mock(node_id=node_id, user_id=target_user_id)
    perm.revoke = MagicMock()

    permissions_repo = AsyncMock()
    permissions_repo.get_by_node_and_user = AsyncMock(return_value=perm)

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    data = PermissionRevokeRequest(
        node_id=node_id, user_id=target_user_id, revoke_reason="cleanup"
    )
    result = await service.revoke_permission(data, actor_id=actor_id)

    assert result is not None
    perm.revoke.assert_called_once()
    permissions_repo.get_by_node_and_user.assert_awaited_once()


@pytest.mark.asyncio
async def test_revoke_permission_not_found_raises():
    """revoke_permission вызывает NotFoundServiceError, когда право отсутствует."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    target_user_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_by_node_and_user = AsyncMock(return_value=None)

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    data = PermissionRevokeRequest(node_id=node_id, user_id=target_user_id)

    with pytest.raises(NotFoundServiceError):
        await service.revoke_permission(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_revoke_permission_wraps_database_error():
    """revoke_permission преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(
        side_effect=DatabaseError("db")
    )

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    data = PermissionRevokeRequest(permission_id=perm_id)

    with pytest.raises(ServiceError) as exc_info:
        await service.revoke_permission(data, actor_id=actor_id)
    assert exc_info.value.operation == "revoke_permission"


@pytest.mark.asyncio
async def test_revoke_permission_wraps_unexpected_error():
    """revoke_permission преобразует непредвиденную ошибку в ServiceError."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    data = PermissionRevokeRequest(permission_id=perm_id)

    with pytest.raises(ServiceError) as exc_info:
        await service.revoke_permission(data, actor_id=actor_id)
    assert exc_info.value.operation == "revoke_permission"


# ---------------------------------------------------------------------------
# Тесты: get_permission (more)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_permission_access_denied_raises():
    """get_permission вызывает PermissionServiceError при отказе в доступе."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()
    perm = make_permission_mock(permission_id=perm_id)

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(return_value=perm)

    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied")
    )
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.get_permission(perm_id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_get_permission_wraps_database_error():
    """get_permission преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(
        side_effect=DatabaseError("db")
    )

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_permission(perm_id, actor_id=actor_id)
    assert exc_info.value.operation == "get_permission"


# ---------------------------------------------------------------------------
# Тесты: list_node_permissions (more)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_permission_wraps_unexpected_error():
    """get_permission преобразует непредвиденную ошибку в ServiceError."""
    actor_id = uuid.uuid4()
    perm_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_permission_by_id = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_permission(perm_id, actor_id=actor_id)
    assert exc_info.value.operation == "get_permission"


@pytest.mark.asyncio
async def test_list_node_permissions_wraps_database_error():
    """list_node_permissions преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_node_permissions = AsyncMock(
        side_effect=DatabaseError("db")
    )

    access = make_access()
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    with pytest.raises(ServiceError) as exc_info:
        await service.list_node_permissions(node_id=node_id, actor_id=actor_id)
    assert exc_info.value.operation == "list_node_permissions"


@pytest.mark.asyncio
async def test_list_node_permissions_wraps_unexpected_error():
    """list_node_permissions преобразует непредвиденную ошибку в ServiceError."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_node_permissions = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    access = make_access()
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access)

    with pytest.raises(ServiceError) as exc_info:
        await service.list_node_permissions(node_id=node_id, actor_id=actor_id)
    assert exc_info.value.operation == "list_node_permissions"


@pytest.mark.asyncio
async def test_list_node_permissions_reraises_service_error():
    """list_node_permissions пробрасывает ServiceError из require_access."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()

    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied")
    )
    uow = make_uow(permissions=AsyncMock())
    service = make_permissions_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.list_node_permissions(node_id=node_id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_list_node_permissions_invalid_limit_raises():
    """list_node_permissions вызывает ValidationServiceError для limit < 1."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    uow = make_uow(permissions=AsyncMock())
    service = make_permissions_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.list_node_permissions(
            node_id=node_id, actor_id=actor_id, limit=0
        )


# ---------------------------------------------------------------------------
# Тесты: list_shared_with_me
# ---------------------------------------------------------------------------


def _attach_shared_node(perm, *, name="shared.pdf", mime="application/pdf",
                        is_deleted=False, grantor_username="alice"):
    """Привязывает к моку права загруженный узел, его File и грантора."""
    node = make_node_mock(node_id=perm.node_id)
    node.name = name
    node.node_type = NodeType.FILE
    node.is_deleted = is_deleted
    file = MagicMock()
    file.size_bytes = 2048
    file.mime_type = mime
    node.__dict__["file"] = file
    perm.node = node
    grantor = MagicMock()
    grantor.username = grantor_username
    perm.__dict__["grantor"] = grantor
    return perm


@pytest.mark.asyncio
async def test_list_nodes_shared_by_me_uses_single_distinct_query():
    """list_nodes_shared_by_me берёт node_id одним DISTINCT-запросом."""
    user_id = uuid.uuid4()
    ids = [uuid.uuid4(), uuid.uuid4()]
    permissions_repo = AsyncMock()
    permissions_repo.get_distinct_active_granted_node_ids = AsyncMock(return_value=ids)
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    result = await service.list_nodes_shared_by_me(user_id=user_id)

    assert result == ids
    permissions_repo.get_distinct_active_granted_node_ids.assert_awaited_once_with(
        granted_by=user_id
    )


@pytest.mark.asyncio
async def test_list_shared_with_me_maps_node_and_permission():
    """list_shared_with_me собирает метаданные узла и параметры права."""
    user_id = uuid.uuid4()
    perm = make_permission_mock(user_id=user_id)
    _attach_shared_node(perm)

    permissions_repo = AsyncMock()
    permissions_repo.get_user_permissions = AsyncMock(return_value=[perm])
    permissions_repo.count_user_permissions = AsyncMock(return_value=1)
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    result = await service.list_shared_with_me(user_id=user_id, actor_id=user_id)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.name == "shared.pdf"
    assert item.file_mime_type == "application/pdf"
    assert item.file_size_bytes == 2048
    assert item.permission_id == perm.id
    assert item.granted_by_username == "alice"
    # active_only=True гарантирует только активные права.
    _, kwargs = permissions_repo.get_user_permissions.call_args
    assert kwargs["active_only"] is True


@pytest.mark.asyncio
async def test_list_shared_with_me_skips_deleted_nodes():
    """Узлы в корзине/удалённые не попадают в выдачу «Доступно мне»."""
    user_id = uuid.uuid4()
    alive = _attach_shared_node(make_permission_mock(user_id=user_id), name="ok.txt")
    dead = _attach_shared_node(
        make_permission_mock(user_id=user_id), name="gone.txt", is_deleted=True
    )

    permissions_repo = AsyncMock()
    permissions_repo.get_user_permissions = AsyncMock(return_value=[alive, dead])
    permissions_repo.count_user_permissions = AsyncMock(return_value=2)
    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    result = await service.list_shared_with_me(user_id=user_id, actor_id=user_id)

    assert [i.name for i in result.items] == ["ok.txt"]


@pytest.mark.asyncio
async def test_list_shared_with_me_other_user_raises_permission():
    """Нельзя запросить чужой «Доступно мне»."""
    uow = make_uow(permissions=AsyncMock())
    service = make_permissions_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.list_shared_with_me(
            user_id=uuid.uuid4(), actor_id=uuid.uuid4()
        )


# ---------------------------------------------------------------------------
# Тесты: list_user_permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_user_permissions_returns_page_for_self():
    """list_user_permissions возвращает PageResponse для собственных прав актора."""
    user_id = uuid.uuid4()
    perm = make_permission_mock(user_id=user_id)

    permissions_repo = AsyncMock()
    permissions_repo.get_user_permissions = AsyncMock(return_value=[perm])
    permissions_repo.count_user_permissions = AsyncMock(return_value=1)

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    result = await service.list_user_permissions(
        user_id=user_id, actor_id=user_id
    )

    assert result.meta.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_list_user_permissions_other_user_raises_permission():
    """list_user_permissions запрещает запрашивать права другого пользователя."""
    user_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    uow = make_uow(permissions=AsyncMock())
    service = make_permissions_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.list_user_permissions(user_id=user_id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_list_user_permissions_invalid_limit_raises():
    """list_user_permissions вызывает ValidationServiceError для limit < 1."""
    user_id = uuid.uuid4()
    uow = make_uow(permissions=AsyncMock())
    service = make_permissions_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.list_user_permissions(
            user_id=user_id, actor_id=user_id, limit=0
        )


@pytest.mark.asyncio
async def test_list_user_permissions_wraps_database_error():
    """list_user_permissions преобразует DatabaseError в ServiceError."""
    user_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_user_permissions = AsyncMock(
        side_effect=DatabaseError("db")
    )

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    with pytest.raises(ServiceError) as exc_info:
        await service.list_user_permissions(user_id=user_id, actor_id=user_id)
    assert exc_info.value.operation == "list_user_permissions"


@pytest.mark.asyncio
async def test_list_user_permissions_reraises_service_error():
    """list_user_permissions пробрасывает ServiceError из репозитория."""
    user_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_user_permissions = AsyncMock(
        side_effect=NotFoundServiceError(entity_name="NodePermission")
    )

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    with pytest.raises(NotFoundServiceError):
        await service.list_user_permissions(user_id=user_id, actor_id=user_id)


@pytest.mark.asyncio
async def test_list_user_permissions_wraps_unexpected_error():
    """list_user_permissions преобразует непредвиденную ошибку в ServiceError."""
    user_id = uuid.uuid4()

    permissions_repo = AsyncMock()
    permissions_repo.get_user_permissions = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    uow = make_uow(permissions=permissions_repo)
    service = make_permissions_service(uow)

    with pytest.raises(ServiceError) as exc_info:
        await service.list_user_permissions(user_id=user_id, actor_id=user_id)
    assert exc_info.value.operation == "list_user_permissions"


# ---------------------------------------------------------------------------
# Тесты: check_permission / get_effective_permissions delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_permission_delegates_to_access_service():
    """check_permission делегирует в AccessService.check_node_access."""
    node_id = uuid.uuid4()
    expected = PermissionCheckResponse(
        allowed=True, node_id=node_id, action=PermissionAction.READ
    )
    access = MagicMock()
    access.check_node_access = AsyncMock(return_value=expected)
    uow = make_uow()
    service = make_permissions_service(uow, access_svc=access)

    data = PermissionCheckRequest(node_id=node_id, action=PermissionAction.READ)
    result = await service.check_permission(data)

    assert result is expected
    access.check_node_access.assert_awaited_once_with(data)


@pytest.mark.asyncio
async def test_get_effective_permissions_delegates_to_access_service():
    """get_effective_permissions делегирует в AccessService."""
    node_id = uuid.uuid4()
    user_id = uuid.uuid4()
    expected = EffectivePermissionRead(node_id=node_id, user_id=user_id)
    access = MagicMock()
    access.get_effective_permissions = AsyncMock(return_value=expected)
    uow = make_uow()
    service = make_permissions_service(uow, access_svc=access)

    result = await service.get_effective_permissions(
        node_id=node_id, user_id=user_id
    )

    assert result is expected
    access.get_effective_permissions.assert_awaited_once()


# ---------------------------------------------------------------------------
# Тесты: _safe_log_permission_event swallows ServiceError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_log_permission_event_swallows_service_error():
    """Сбои аудита не ломают операцию выдачи права."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    target_user_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=uuid.uuid4())
    perm = make_permission_mock(node_id=node_id, user_id=target_user_id)

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(
        return_value=MagicMock(id=target_user_id)
    )
    permissions_repo = AsyncMock()
    permissions_repo.grant_permission = AsyncMock(return_value=perm)

    access = make_access(node=node)
    audit = make_audit()
    audit.log_event = AsyncMock(side_effect=ServiceError("audit down"))
    uow = make_uow(users=users_repo, permissions=permissions_repo)
    service = make_permissions_service(uow, access_svc=access, audit_svc=audit)

    data = PermissionGrantRequest(
        node_id=node_id, user_id=target_user_id, can_read=True
    )
    result = await service.grant_permission(data, actor_id=actor_id)

    assert result is not None
    audit.log_event.assert_awaited_once()


# ---------------------------------------------------------------------------
# Тесты: module-level helpers
# ---------------------------------------------------------------------------


def test_validate_limit_rejects_non_positive():
    """_validate_limit вызывает ValidationServiceError для limit < 1."""
    with pytest.raises(ValidationServiceError):
        _validate_limit(0)


def test_validate_limit_caps_at_max():
    """_validate_limit ограничивает запрошенный лимит значением MAX_PAGE_LIMIT."""
    assert _validate_limit(50) == 50
    assert _validate_limit(10_000) == 1000


def test_empty_result_error_returns_service_error():
    """_empty_result_error собирает ServiceError для заданной операции."""
    err = _empty_result_error("grant_permission")
    assert isinstance(err, ServiceError)
    assert err.operation == "grant_permission"


def test_apply_permission_update_syncs_level_from_flags():
    """_apply_permission_update синхронизирует уровень, когда он не задан."""
    perm = make_permission_mock()
    perm.sync_permission_level_from_flags = MagicMock()
    data = PermissionUpdateRequest(permission_id=uuid.uuid4(), can_read=True)

    _apply_permission_update(perm, data)

    perm.sync_permission_level_from_flags.assert_called_once()
    assert perm.revoked_at is None
    assert perm.revoke_reason is None


def test_apply_permission_update_empty_raises():
    """_apply_permission_update вызывает ошибку, когда ни один флаг не включён."""
    perm = make_permission_mock()
    perm.sync_permission_level_from_flags = MagicMock()
    data = PermissionUpdateRequest(
        permission_id=uuid.uuid4(),
        can_read=False,
        can_download=False,
        can_write=False,
        can_delete=False,
        can_share=False,
    )

    with pytest.raises(ValidationServiceError):
        _apply_permission_update(perm, data)


def test_jsonable_converts_supported_types():
    """_jsonable преобразует UUID, datetime, Enum и откатывается к str."""
    value = uuid.uuid4()
    assert _jsonable(value) == str(value)

    now = datetime.now(UTC)
    assert _jsonable(now) == now.isoformat()

    import enum

    class PlainEnum(enum.Enum):
        A = "alpha"

    assert _jsonable(PlainEnum.A) == "alpha"

    assert _jsonable(None) is None
    assert _jsonable("plain") == "plain"
    assert _jsonable(42) == 42

    class Weird:
        def __str__(self) -> str:
            return "weird"

    assert _jsonable(Weird()) == "weird"


def test_get_permissions_service_builds_instance():
    """get_permissions_service конструирует PermissionsService с зависимостями."""
    uow = make_uow()
    service = get_permissions_service(
        uow_factory=make_factory(uow),
        access_service=make_access(),
        audit_service=make_audit(),
    )
    assert isinstance(service, PermissionsService)
