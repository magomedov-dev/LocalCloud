"""Юнит-тесты для TrashService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from database import DatabaseError
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    NodeType,
    NodeVisibility,
    TrashItemStatus,
)
from schemas.trash import (
    TrashCleanupRequest,
    TrashEmptyRequest,
    TrashPurgeRequest,
    TrashQueryParams,
    TrashRestoreRequest,
)
from services.exceptions import (
    NotFoundServiceError,
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
)
from services.trash import (
    StorageObjectRef,
    TrashService,
    _audit_trash,
    _build_purge_plan,
    _deleted_action_from_node_snapshot,
    _ensure_restorable,
    _file_storage_objects,
    _get_trash_item_for_request,
    _jsonable,
    _normalize_datetime,
    _purged_action,
    _resource_type,
    _resource_type_from_node_snapshot,
    _restored_action_from_node_snapshot,
    _validate_sort_field,
)
from storage import StorageError


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


def make_storage():
    svc = MagicMock()
    svc.delete_file = AsyncMock()
    svc.file_exists = AsyncMock(return_value=True)
    return svc


def make_node_mock(
    node_id=None,
    owner_id=None,
    node_type=NodeType.FOLDER,
    is_deleted=False,
    name="test-node",
):
    node = MagicMock()
    node.id = node_id or uuid.uuid4()
    node.owner_id = owner_id or uuid.uuid4()
    node.parent_id = None
    node.name = name
    node.node_type = node_type
    node.visibility = NodeVisibility.PRIVATE
    node.path = f"/{name}"
    node.depth = 1
    node.created_by = node.owner_id
    node.updated_by = node.owner_id
    node.deleted_by = None
    node.created_at = datetime.now(UTC)
    node.updated_at = datetime.now(UTC)
    node.is_deleted = is_deleted
    node.deleted_at = None
    return node


def make_trash_item_mock(
    trash_id=None,
    node_id=None,
    owner_id=None,
    status=TrashItemStatus.IN_TRASH,
):
    owner = owner_id or uuid.uuid4()
    nid = node_id or uuid.uuid4()
    node = make_node_mock(node_id=nid, owner_id=owner, is_deleted=True)

    item = MagicMock()
    item.id = trash_id or uuid.uuid4()
    item.node_id = nid
    item.node = node
    item.owner_id = owner
    item.deleted_by = owner
    item.original_parent_id = None
    item.original_path = "/test-node"
    item.status = status
    item.deleted_at = datetime.now(UTC)
    item.expires_at = None
    item.restore_available = True
    item.purged_at = None
    return item


def make_access(node=None):
    svc = MagicMock()
    svc.get_accessible_node = AsyncMock(return_value=node or make_node_mock())
    svc.require_access = AsyncMock()
    return svc


def make_storage_full():
    """Мок хранилища с методом delete_file_object, используемым сервисом."""
    svc = MagicMock()
    svc.delete_file_object = AsyncMock()
    return svc


def make_file_mock(
    node_id=None,
    size_bytes=100,
    storage_key="files/f1",
    storage_bucket="bucket",
):
    file = MagicMock()
    file.node_id = node_id or uuid.uuid4()
    file.size_bytes = size_bytes
    file.storage_key = storage_key
    file.storage_bucket = storage_bucket
    return file


def make_trash_service(uow, access_svc=None, audit_svc=None, storage_svc=None):
    from core.config import get_settings
    return TrashService(
        settings=get_settings(),
        uow_factory=make_factory(uow),
        access_service=access_svc or make_access(),
        audit_service=audit_svc or make_audit(),
        storage_service=storage_svc or make_storage(),
    )


# ---------------------------------------------------------------------------
# Тесты: move_to_trash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_to_trash_returns_trash_item_read():
    """move_to_trash возвращает TrashItemRead при успехе."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id, is_deleted=False)
    trash_item = make_trash_item_mock(node_id=node_id, owner_id=actor_id)

    trash_repo = AsyncMock()
    trash_repo.create_trash_item = AsyncMock(return_value=trash_item)

    access = make_access(node=node)
    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow, access_svc=access)

    result = await service.move_to_trash(node_id=node_id, actor_id=actor_id)

    assert result is not None
    assert str(result.node_id) == str(node_id)
    trash_repo.create_trash_item.assert_called_once()


@pytest.mark.asyncio
async def test_move_to_trash_already_deleted_raises_validation_error():
    """move_to_trash вызывает ValidationServiceError, когда узел уже удалён."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    # Узел уже помечен как удалённый
    deleted_node = make_node_mock(node_id=node_id, owner_id=actor_id, is_deleted=True)

    access = make_access(node=deleted_node)
    uow = make_uow()
    service = make_trash_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.move_to_trash(node_id=node_id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_move_to_trash_access_denied_raises_permission_error():
    """move_to_trash вызывает PermissionServiceError, когда пользователь не может удалять."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()

    access = MagicMock()
    access.get_accessible_node = AsyncMock(
        side_effect=PermissionServiceError(
            "No delete access",
            user_id=actor_id,
            resource_type="node",
            resource_id=node_id,
            action="delete",
        )
    )
    uow = make_uow()
    service = make_trash_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.move_to_trash(node_id=node_id, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: get_trash_item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trash_item_returns_trash_item_read():
    """get_trash_item возвращает TrashItemRead для существующего элемента корзины."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    trash_item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=trash_item)

    access = make_access()
    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow, access_svc=access)

    result = await service.get_trash_item(trash_id, actor_id=actor_id)

    assert result is not None
    assert str(result.id) == str(trash_id)


@pytest.mark.asyncio
async def test_get_trash_item_raises_not_found_when_missing():
    """get_trash_item вызывает NotFoundServiceError, когда элемента корзины не существует."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=None)

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    with pytest.raises(NotFoundServiceError):
        await service.get_trash_item(trash_id, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: list_trash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_trash_returns_page_response():
    """list_trash возвращает PageResponse с TrashItemListItem."""
    actor_id = uuid.uuid4()
    trash_item = make_trash_item_mock(owner_id=actor_id)

    trash_repo = AsyncMock()
    trash_repo.count_user_trash_filtered = AsyncMock(return_value=1)
    trash_repo.search_user_trash = AsyncMock(return_value=[trash_item])

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    params = TrashQueryParams(owner_id=actor_id)
    result = await service.list_trash(params, actor_id=actor_id)

    assert result is not None
    assert result.meta.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_list_trash_other_owner_raises_permission_error():
    """list_trash вызывает PermissionServiceError, когда актор пытается посмотреть чужую корзину."""
    actor_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    uow = make_uow()
    service = make_trash_service(uow)

    params = TrashQueryParams(owner_id=other_user_id)

    with pytest.raises(PermissionServiceError):
        await service.list_trash(params, actor_id=actor_id)


@pytest.mark.asyncio
async def test_list_trash_empty_returns_empty_page():
    """list_trash возвращает пустую страницу, когда в корзине нет элементов."""
    actor_id = uuid.uuid4()

    trash_repo = AsyncMock()
    trash_repo.count_user_trash_filtered = AsyncMock(return_value=0)
    trash_repo.search_user_trash = AsyncMock(return_value=[])

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    params = TrashQueryParams()
    result = await service.list_trash(params, actor_id=actor_id)

    assert result.items == []
    assert result.meta.total == 0


@pytest.mark.asyncio
async def test_list_trash_invalid_sort_raises_validation_error():
    """list_trash вызывает ValidationServiceError для неподдерживаемого поля сортировки."""
    actor_id = uuid.uuid4()
    uow = make_uow(trash=AsyncMock())
    service = make_trash_service(uow)

    params = TrashQueryParams(sort_by="not_a_field")
    with pytest.raises(ValidationServiceError):
        await service.list_trash(params, actor_id=actor_id)


@pytest.mark.asyncio
async def test_list_trash_wraps_database_error():
    """list_trash преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    trash_repo = AsyncMock()
    trash_repo.count_user_trash_filtered = AsyncMock(side_effect=DatabaseError("boom"))

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    with pytest.raises(ServiceError):
        await service.list_trash(TrashQueryParams(), actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: move_to_trash — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_to_trash_wraps_database_error():
    """move_to_trash преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id, is_deleted=False)

    trash_repo = AsyncMock()
    trash_repo.create_trash_item = AsyncMock(side_effect=DatabaseError("boom"))

    access = make_access(node=node)
    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.move_to_trash(node_id=node_id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_move_to_trash_wraps_unexpected_error():
    """move_to_trash преобразует непредвиденное исключение в ServiceError."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id, is_deleted=False)

    trash_repo = AsyncMock()
    trash_repo.create_trash_item = AsyncMock(side_effect=RuntimeError("kaboom"))

    access = make_access(node=node)
    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.move_to_trash(node_id=node_id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_move_to_trash_logs_audit_event():
    """move_to_trash записывает событие аудита для удалённого файла."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(
        node_id=node_id, owner_id=actor_id, is_deleted=False, node_type=NodeType.FILE
    )
    trash_item = make_trash_item_mock(node_id=node_id, owner_id=actor_id)
    trash_item.node.node_type = NodeType.FILE

    trash_repo = AsyncMock()
    trash_repo.create_trash_item = AsyncMock(return_value=trash_item)

    audit = make_audit()
    access = make_access(node=node)
    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow, access_svc=access, audit_svc=audit)

    await service.move_to_trash(node_id=node_id, actor_id=actor_id)

    audit.log_event.assert_awaited_once()
    kwargs = audit.log_event.call_args.kwargs
    assert kwargs["action"] == AuditAction.FILE_DELETED
    assert kwargs["resource_type"] == AuditResourceType.FILE


# ---------------------------------------------------------------------------
# Тесты: get_trash_item — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trash_item_wraps_database_error():
    """get_trash_item преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(side_effect=DatabaseError("boom"))

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    with pytest.raises(ServiceError):
        await service.get_trash_item(uuid.uuid4(), actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_returns_response_on_success():
    """restore восстанавливает узел и возвращает успешный ответ."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_restored = AsyncMock()

    nodes_repo = AsyncMock()
    access = make_access()
    audit = make_audit()
    uow = make_uow(trash=trash_repo, nodes=nodes_repo)
    service = make_trash_service(uow, access_svc=access, audit_svc=audit)

    result = await service.restore(
        TrashRestoreRequest(trash_item_id=trash_id), actor_id=actor_id
    )

    assert result.success is True
    assert result.trash_item is not None
    assert result.node is not None
    trash_repo.mark_restored.assert_awaited_once()
    access.require_access.assert_awaited()
    audit.log_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_with_target_parent_moves_node():
    """restore с target_parent_id проверяет право WRITE и перемещает узел."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    target_parent = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_restored = AsyncMock()

    nodes_repo = AsyncMock()
    nodes_repo.move_node = AsyncMock()

    access = make_access()
    uow = make_uow(trash=trash_repo, nodes=nodes_repo)
    service = make_trash_service(uow, access_svc=access)

    result = await service.restore(
        TrashRestoreRequest(trash_item_id=trash_id, target_parent_id=target_parent),
        actor_id=actor_id,
    )

    assert result.success is True
    nodes_repo.move_node.assert_awaited_once()
    # Выполнены проверки доступа READ/RESTORE + WRITE
    assert access.require_access.await_count >= 2


@pytest.mark.asyncio
async def test_restore_by_node_id_lookup():
    """restore разрешает элемент корзины по node_id, когда trash_item_id отсутствует."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    item = make_trash_item_mock(node_id=node_id, owner_id=actor_id)

    trash_repo = AsyncMock()
    trash_repo.get_active_by_node_id = AsyncMock(return_value=item)
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_restored = AsyncMock()

    uow = make_uow(trash=trash_repo, nodes=AsyncMock())
    service = make_trash_service(uow)

    result = await service.restore(
        TrashRestoreRequest(node_id=node_id), actor_id=actor_id
    )

    assert result.success is True
    trash_repo.get_active_by_node_id.assert_awaited_with(node_id)


@pytest.mark.asyncio
async def test_restore_not_found_raises():
    """restore вызывает NotFoundServiceError, когда элемент корзины отсутствует."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=None)

    uow = make_uow(trash=trash_repo, nodes=AsyncMock())
    service = make_trash_service(uow)

    with pytest.raises(NotFoundServiceError):
        await service.restore(
            TrashRestoreRequest(trash_item_id=trash_id), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_restore_not_restorable_status_raises_validation():
    """restore вызывает ValidationServiceError, когда элемент не в корзине."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(
        trash_id=trash_id, owner_id=actor_id, status=TrashItemStatus.PURGED
    )

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=item)

    uow = make_uow(trash=trash_repo, nodes=AsyncMock())
    service = make_trash_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.restore(
            TrashRestoreRequest(trash_item_id=trash_id), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_restore_wraps_database_error():
    """restore преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_restored = AsyncMock(side_effect=DatabaseError("boom"))

    uow = make_uow(trash=trash_repo, nodes=AsyncMock())
    service = make_trash_service(uow)

    with pytest.raises(ServiceError):
        await service.restore(
            TrashRestoreRequest(trash_item_id=trash_id), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_restore_wraps_unexpected_error():
    """restore преобразует непредвиденное исключение в ServiceError."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_restored = AsyncMock(side_effect=RuntimeError("kaboom"))

    uow = make_uow(trash=trash_repo, nodes=AsyncMock())
    service = make_trash_service(uow)

    with pytest.raises(ServiceError):
        await service.restore(
            TrashRestoreRequest(trash_item_id=trash_id), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_restore_empty_after_mark_raises():
    """restore вызывает ошибку, когда повторно загруженный элемент отсутствует после mark_restored."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    trash_repo = AsyncMock()
    # Первый поиск возвращает элемент, повторная загрузка после mark возвращает None
    trash_repo.get_by_id = AsyncMock(side_effect=[item, None])
    trash_repo.mark_restored = AsyncMock()

    uow = make_uow(trash=trash_repo, nodes=AsyncMock())
    service = make_trash_service(uow)

    with pytest.raises(ServiceError):
        await service.restore(
            TrashRestoreRequest(trash_item_id=trash_id), actor_id=actor_id
        )


# ---------------------------------------------------------------------------
# Тесты: purge / _purge_one
# ---------------------------------------------------------------------------


def make_purge_service(item, *, file=None, access_svc=None, storage_svc=None):
    """Собрать сервис, настроенный на purge одного элемента — узла-файла."""
    node = item.node
    node.node_type = NodeType.FILE

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.get_active_by_node_id = AsyncMock(return_value=item)
    trash_repo.mark_purged = AsyncMock()

    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)

    files_repo = AsyncMock()
    files_repo.get_by_node_id = AsyncMock(
        return_value=file if file is not None else make_file_mock(node_id=item.node_id)
    )

    links_repo = AsyncMock()
    links_repo.delete_links_by_node = AsyncMock()

    quotas_repo = AsyncMock()
    quotas_repo.decrease_used_space = AsyncMock()
    quotas_repo.decrease_files_used = AsyncMock()

    uow = make_uow(
        trash=trash_repo,
        nodes=nodes_repo,
        files=files_repo,
        links=links_repo,
        quotas=quotas_repo,
    )
    service = make_trash_service(
        uow,
        access_svc=access_svc,
        storage_svc=storage_svc or make_storage_full(),
    )
    return service, uow


@pytest.mark.asyncio
async def test_purge_single_file_success():
    """purge удаляет объекты хранилища, помечает purged и уменьшает квоту."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)
    file = make_file_mock(node_id=item.node_id, size_bytes=500)
    storage = make_storage_full()

    service, uow = make_purge_service(item, file=file, storage_svc=storage)

    result = await service.purge(
        TrashPurgeRequest(trash_item_ids=[trash_id]), actor_id=actor_id
    )

    assert result.success is True
    assert result.purged_count == 1
    assert result.failed_count == 0
    assert result.purged_trash_item_ids == [trash_id]
    storage.delete_file_object.assert_awaited()
    uow.quotas.decrease_used_space.assert_awaited_once()
    uow.quotas.decrease_files_used.assert_awaited_once()
    uow.links.delete_links_by_node.assert_awaited_once()
    uow.trash.mark_purged.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_resolves_node_ids():
    """purge разрешает id элементов корзины из node_ids."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    item = make_trash_item_mock(node_id=node_id, owner_id=actor_id)

    service, uow = make_purge_service(item)

    result = await service.purge(
        TrashPurgeRequest(node_ids=[node_id]), actor_id=actor_id
    )

    assert result.purged_count == 1
    uow.trash.get_active_by_node_id.assert_awaited()


@pytest.mark.asyncio
async def test_purge_resolve_node_id_missing_raises_not_found():
    """purge вызывает NotFoundServiceError, когда у node_id нет активного элемента корзины."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()

    trash_repo = AsyncMock()
    trash_repo.get_active_by_node_id = AsyncMock(return_value=None)

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    with pytest.raises(NotFoundServiceError):
        await service.purge(
            TrashPurgeRequest(node_ids=[node_id]), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_purge_one_permission_denied_marks_failed():
    """purge записывает сбои, когда отказано в праве PURGE."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    access = make_access()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", user_id=actor_id)
    )

    service, _ = make_purge_service(item, access_svc=access)

    result = await service.purge(
        TrashPurgeRequest(trash_item_ids=[trash_id]), actor_id=actor_id
    )

    assert result.success is False
    assert result.failed_count == 1
    assert result.failed_trash_item_ids == [trash_id]


@pytest.mark.asyncio
async def test_purge_one_not_found_marks_failed():
    """purge записывает сбои, когда элемент корзины исчезает."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=None)

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    result = await service.purge(
        TrashPurgeRequest(trash_item_ids=[trash_id]), actor_id=actor_id
    )

    assert result.failed_count == 1
    assert result.purged_count == 0


@pytest.mark.asyncio
async def test_purge_one_storage_error_marks_failed():
    """purge записывает сбои, когда не удаётся удалить из хранилища."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    storage = make_storage_full()
    storage.delete_file_object = AsyncMock(side_effect=StorageError("boom"))

    service, _ = make_purge_service(item, storage_svc=storage)

    result = await service.purge(
        TrashPurgeRequest(trash_item_ids=[trash_id]), actor_id=actor_id
    )

    assert result.failed_count == 1


@pytest.mark.asyncio
async def test_purge_folder_collects_descendant_files():
    """purge папки собирает объекты хранилища из файлов-потомков."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)
    item.node.node_type = NodeType.FOLDER

    child_file_node = make_node_mock(node_type=NodeType.FILE)
    child_folder_node = make_node_mock(node_type=NodeType.FOLDER)

    file = make_file_mock(
        node_id=child_file_node.id,
        size_bytes=200,
    )

    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_purged = AsyncMock()

    nodes_repo = AsyncMock()
    nodes_repo.get_descendants = AsyncMock(
        return_value=[item.node, child_folder_node, child_file_node]
    )

    files_repo = AsyncMock()
    files_repo.get_by_node_id = AsyncMock(return_value=file)

    links_repo = AsyncMock()
    quotas_repo = AsyncMock()
    storage = make_storage_full()

    uow = make_uow(
        trash=trash_repo,
        nodes=nodes_repo,
        files=files_repo,
        links=links_repo,
        quotas=quotas_repo,
    )
    service = make_trash_service(uow, storage_svc=storage)

    result = await service.purge(
        TrashPurgeRequest(trash_item_ids=[trash_id]), actor_id=actor_id
    )

    assert result.purged_count == 1
    nodes_repo.get_descendants.assert_awaited_once()
    # удаляется объект файла
    assert storage.delete_file_object.await_count == 1


# ---------------------------------------------------------------------------
# Тесты: empty_trash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_trash_other_owner_raises_permission():
    """empty_trash вызывает PermissionServiceError для другого владельца."""
    actor_id = uuid.uuid4()
    uow = make_uow()
    service = make_trash_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.empty_trash(
            TrashEmptyRequest(owner_id=uuid.uuid4()), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_empty_trash_already_empty():
    """empty_trash возвращает ответ «уже пусто», когда элементов нет."""
    actor_id = uuid.uuid4()
    trash_repo = AsyncMock()
    trash_repo.get_user_active_trash = AsyncMock(return_value=[])

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    result = await service.empty_trash(TrashEmptyRequest(), actor_id=actor_id)

    assert result.requested_count == 0
    assert result.purged_count == 0
    assert "пуста" in result.message


@pytest.mark.asyncio
async def test_empty_trash_purges_all_active():
    """empty_trash удаляет все активные элементы корзины владельца."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)
    item.node.node_type = NodeType.FILE

    trash_repo = AsyncMock()
    trash_repo.get_user_active_trash = AsyncMock(return_value=[item])
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_purged = AsyncMock()

    nodes_repo = AsyncMock()
    files_repo = AsyncMock()
    files_repo.get_by_node_id = AsyncMock(
        return_value=make_file_mock(node_id=item.node_id)
    )
    links_repo = AsyncMock()
    quotas_repo = AsyncMock()

    uow = make_uow(
        trash=trash_repo,
        nodes=nodes_repo,
        files=files_repo,
        links=links_repo,
        quotas=quotas_repo,
    )
    service = make_trash_service(uow, storage_svc=make_storage_full())

    result = await service.empty_trash(TrashEmptyRequest(), actor_id=actor_id)

    assert result.purged_count == 1


@pytest.mark.asyncio
async def test_empty_trash_only_expired_uses_candidates():
    """empty_trash с only_expired удаляет просроченных кандидатов."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)
    item.node.node_type = NodeType.FILE

    trash_repo = AsyncMock()
    trash_repo.get_expired_items = AsyncMock(return_value=[item])
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_purged = AsyncMock()

    uow = make_uow(
        trash=trash_repo,
        nodes=AsyncMock(),
        files=AsyncMock(get_by_node_id=AsyncMock(return_value=make_file_mock())),
        links=AsyncMock(),
        quotas=AsyncMock(),
    )
    service = make_trash_service(uow, storage_svc=make_storage_full())

    result = await service.empty_trash(
        TrashEmptyRequest(only_expired=True), actor_id=actor_id
    )

    assert result.purged_count == 1
    trash_repo.get_expired_items.assert_awaited()


# ---------------------------------------------------------------------------
# Тесты: cleanup_expired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_expired_other_owner_raises_permission():
    """cleanup_expired вызывает PermissionServiceError при несовпадении владельца."""
    actor_id = uuid.uuid4()
    uow = make_uow()
    service = make_trash_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.cleanup_expired(
            TrashCleanupRequest(owner_id=uuid.uuid4()), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_cleanup_expired_dry_run():
    """cleanup_expired в режиме dry-run возвращает количество кандидатов без удаления."""
    item = make_trash_item_mock()

    trash_repo = AsyncMock()
    trash_repo.get_expired_items = AsyncMock(return_value=[item])

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    result = await service.cleanup_expired(TrashCleanupRequest(dry_run=True))

    assert result.requested_count == 1
    assert result.purged_count == 0
    trash_repo.mark_purged.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_expired_no_candidates():
    """cleanup_expired возвращает пустой ответ, когда нет кандидатов."""
    trash_repo = AsyncMock()
    trash_repo.get_expired_items = AsyncMock(return_value=[])

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    result = await service.cleanup_expired(TrashCleanupRequest())

    assert result.requested_count == 0
    assert result.purged_count == 0


@pytest.mark.asyncio
async def test_cleanup_expired_system_purge():
    """cleanup_expired без actor_id использует системный путь purge."""
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id)
    item.node.node_type = NodeType.FILE

    trash_repo = AsyncMock()
    trash_repo.get_expired_items = AsyncMock(return_value=[item])
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_purged = AsyncMock()

    files_repo = AsyncMock()
    files_repo.get_by_node_id = AsyncMock(
        return_value=make_file_mock(node_id=item.node_id, size_bytes=300)
    )

    uow = make_uow(
        trash=trash_repo,
        nodes=AsyncMock(),
        files=files_repo,
        links=AsyncMock(),
        quotas=AsyncMock(),
    )
    service = make_trash_service(uow, storage_svc=make_storage_full())

    result = await service.cleanup_expired(TrashCleanupRequest(), actor_id=None)

    assert result.purged_count == 1
    assert result.failed_count == 0


@pytest.mark.asyncio
async def test_cleanup_expired_system_purge_handles_failure():
    """Системный purge записывает сбой, когда элемент исчезает в процессе purge."""
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id)
    item.node.node_type = NodeType.FILE

    trash_repo = AsyncMock()
    trash_repo.get_expired_items = AsyncMock(return_value=[item])
    # _build_system_plan находит элемент, но повторная загрузка на этапе purge возвращает None
    trash_repo.get_by_id = AsyncMock(side_effect=[item, None])

    files_repo = AsyncMock()
    files_repo.get_by_node_id = AsyncMock(return_value=make_file_mock())

    uow = make_uow(
        trash=trash_repo,
        nodes=AsyncMock(),
        files=files_repo,
        links=AsyncMock(),
        quotas=AsyncMock(),
    )
    service = make_trash_service(uow, storage_svc=make_storage_full())

    result = await service.cleanup_expired(TrashCleanupRequest(), actor_id=None)

    assert result.failed_count == 1
    assert result.purged_count == 0


@pytest.mark.asyncio
async def test_cleanup_expired_with_actor_uses_purge():
    """cleanup_expired с actor_id использует пользовательский путь purge с проверками доступа."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)
    item.node.node_type = NodeType.FILE

    trash_repo = AsyncMock()
    trash_repo.get_expired_items = AsyncMock(return_value=[item])
    trash_repo.get_by_id = AsyncMock(return_value=item)
    trash_repo.mark_purged = AsyncMock()

    files_repo = AsyncMock()
    files_repo.get_by_node_id = AsyncMock(return_value=make_file_mock())

    uow = make_uow(
        trash=trash_repo,
        nodes=AsyncMock(),
        files=files_repo,
        links=AsyncMock(),
        quotas=AsyncMock(),
    )
    access = make_access()
    service = make_trash_service(
        uow, access_svc=access, storage_svc=make_storage_full()
    )

    result = await service.cleanup_expired(
        TrashCleanupRequest(owner_id=actor_id), actor_id=actor_id
    )

    assert result.purged_count == 1
    access.require_access.assert_awaited()


@pytest.mark.asyncio
async def test_cleanup_expired_older_than_filter():
    """cleanup_expired фильтрует кандидатов по older_than для deleted_at."""
    old = make_trash_item_mock()
    old.deleted_at = datetime.now(UTC) - timedelta(days=10)
    recent = make_trash_item_mock()
    recent.deleted_at = datetime.now(UTC)

    trash_repo = AsyncMock()
    trash_repo.get_expired_items = AsyncMock(return_value=[old, recent])

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    cutoff = datetime.now(UTC) - timedelta(days=5)
    result = await service.cleanup_expired(
        TrashCleanupRequest(older_than=cutoff, dry_run=True)
    )

    # Только старый элемент проходит фильтр older_than
    assert result.requested_count == 1


# ---------------------------------------------------------------------------
# Тесты: _find_all_active pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_all_active_paginates():
    """_find_all_active перебирает пакеты, пока не вернётся неполный пакет."""
    owner_id = uuid.uuid4()
    full_batch = [make_trash_item_mock() for _ in range(1000)]
    short_batch = [make_trash_item_mock() for _ in range(3)]

    trash_repo = AsyncMock()
    trash_repo.get_user_active_trash = AsyncMock(
        side_effect=[full_batch, short_batch]
    )

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    ids = await service._find_all_active(owner_id=owner_id)

    assert len(ids) == 1003
    assert trash_repo.get_user_active_trash.await_count == 2


# ---------------------------------------------------------------------------
# Тесты: module-level helpers
# ---------------------------------------------------------------------------


def test_validate_sort_field_normalizes():
    assert _validate_sort_field("  Deleted_At ") == "deleted_at"


def test_validate_sort_field_rejects_unknown():
    with pytest.raises(ValidationServiceError):
        _validate_sort_field("unknown")


def test_ensure_restorable_disabled_raises():
    item = make_trash_item_mock()
    item.restore_available = False
    with pytest.raises(ValidationServiceError):
        _ensure_restorable(item)


def test_ensure_restorable_expired_raises():
    item = make_trash_item_mock()
    item.expires_at = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(ValidationServiceError):
        _ensure_restorable(item)


def test_ensure_restorable_ok():
    item = make_trash_item_mock()
    item.expires_at = datetime.now(UTC) + timedelta(days=1)
    # Не должно бросать исключение
    _ensure_restorable(item)


@pytest.mark.asyncio
async def test_get_trash_item_for_request_no_identifiers_raises():
    uow = make_uow(trash=AsyncMock())
    with pytest.raises(NotFoundServiceError):
        await _get_trash_item_for_request(
            uow=uow, trash_item_id=None, node_id=None
        )


def test_file_storage_objects_returns_file_object():
    file = make_file_mock(storage_key="files/main", storage_bucket="buck")
    refs = _file_storage_objects(file)
    assert refs == [StorageObjectRef(bucket="buck", object_key="files/main")]


def test_file_storage_objects_no_storage_key():
    file = make_file_mock(storage_key=None)
    assert _file_storage_objects(file) == []


@pytest.mark.asyncio
async def test_build_purge_plan_fetches_node_when_missing():
    """_build_purge_plan загружает узел через репозиторий nodes, когда он не подгружен."""
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, node_type=NodeType.FILE)
    item = make_trash_item_mock(node_id=node_id)
    item.node = None

    files_repo = AsyncMock()
    files_repo.get_by_node_id = AsyncMock(
        return_value=make_file_mock(node_id=node_id, size_bytes=42)
    )
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)

    uow = make_uow(nodes=nodes_repo, files=files_repo)

    plan = await _build_purge_plan(uow=uow, trash_item=item)

    assert plan.node_type == NodeType.FILE
    assert plan.total_size_bytes == 42
    assert plan.file_count == 1
    nodes_repo.get_required_by_id.assert_awaited_once_with(node_id)


@pytest.mark.asyncio
async def test_build_purge_plan_skips_missing_file():
    """_build_purge_plan пропускает узлы-файлы без строки File."""
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, node_type=NodeType.FILE)
    item = make_trash_item_mock(node_id=node_id)
    item.node = node

    files_repo = AsyncMock()
    files_repo.get_by_node_id = AsyncMock(return_value=None)

    uow = make_uow(nodes=AsyncMock(), files=files_repo)

    plan = await _build_purge_plan(uow=uow, trash_item=item)

    assert plan.file_count == 0
    assert plan.storage_objects == ()


def test_audit_trash_jsonable_metadata():
    item = make_trash_item_mock()
    from services.trash import _trash_item_snapshot

    snapshot = _trash_item_snapshot(item)
    meta = _audit_trash(snapshot)
    assert meta["trash_item_id"] == str(item.id)
    assert meta["node_id"] == str(item.node_id)


def test_action_and_resource_helpers_for_folder_and_node():
    folder_snapshot = {"node": {"node_type": NodeType.FOLDER}}
    file_snapshot = {"node": {"node_type": NodeType.FILE}}
    none_snapshot = {"node": None}

    assert _deleted_action_from_node_snapshot(folder_snapshot) == (
        AuditAction.FOLDER_DELETED
    )
    assert _deleted_action_from_node_snapshot(file_snapshot) == AuditAction.FILE_DELETED
    assert _deleted_action_from_node_snapshot(none_snapshot) == AuditAction.NODE_DELETED

    assert _restored_action_from_node_snapshot(folder_snapshot) == (
        AuditAction.FOLDER_RESTORED
    )
    assert _restored_action_from_node_snapshot(file_snapshot) == (
        AuditAction.FILE_RESTORED
    )
    assert _restored_action_from_node_snapshot(none_snapshot) == (
        AuditAction.NODE_RESTORED
    )

    assert _resource_type_from_node_snapshot(folder_snapshot) == AuditResourceType.FOLDER
    assert _resource_type_from_node_snapshot(file_snapshot) == AuditResourceType.FILE
    assert _resource_type_from_node_snapshot(none_snapshot) == AuditResourceType.NODE

    assert _purged_action(NodeType.FILE) == AuditAction.FILE_PURGED
    assert _purged_action(NodeType.FOLDER) == AuditAction.FOLDER_PURGED
    # Запасная ветка для неизвестного типа узла
    assert _purged_action("other") == AuditAction.NODE_PURGED

    assert _resource_type(NodeType.FILE) == AuditResourceType.FILE
    assert _resource_type(NodeType.FOLDER) == AuditResourceType.FOLDER
    # Запасная ветка для неизвестного типа узла
    assert _resource_type("other") == AuditResourceType.NODE


def test_normalize_datetime_naive_and_aware():
    naive = datetime(2020, 1, 1, 12, 0, 0)
    normalized = _normalize_datetime(naive)
    assert normalized.tzinfo == UTC

    aware = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert _normalize_datetime(aware) == aware


def test_jsonable_supports_various_types():
    import enum

    class PlainEnum(enum.Enum):
        A = 1

    uid = uuid.uuid4()
    assert _jsonable(uid) == str(uid)
    # Обычный (не-строковый) Enum преобразуется через .value
    assert _jsonable(PlainEnum.A) == 1
    # Члены StrEnum возвращаются как есть через ветку примитивов
    assert _jsonable(NodeType.FILE) == NodeType.FILE
    assert _jsonable({"a": uid}) == {"a": str(uid)}
    assert _jsonable([uid]) == [str(uid)]
    assert _jsonable(datetime(2020, 1, 1, tzinfo=UTC)).startswith("2020-01-01")
    assert _jsonable(None) is None
    assert _jsonable(5) == 5

    class Weird:
        def __str__(self):
            return "weird"

    assert _jsonable(Weird()) == "weird"


@pytest.mark.asyncio
async def test_safe_log_trash_event_swallows_service_error():
    """_safe_log_trash_event логирует, но не бросает исключение при сбое аудита."""
    audit = make_audit()
    audit.log_event = AsyncMock(side_effect=ServiceError("audit down"))

    uow = make_uow()
    service = make_trash_service(uow, audit_svc=audit)

    # Не должно бросать исключение
    await service._safe_log_trash_event(
        actor_id=uuid.uuid4(),
        action=AuditAction.FILE_PURGED,
        resource_type=AuditResourceType.FILE,
        entity_id=uuid.uuid4(),
        message="msg",
        metadata={"k": "v"},
    )
    audit.log_event.assert_awaited_once()


def test_get_trash_service_factory_builds_instance():
    from core.config import get_settings
    from services.trash import get_trash_service

    uow = make_uow()
    service = get_trash_service(
        settings=get_settings(),
        uow_factory=make_factory(uow),
        storage_service=make_storage_full(),
        access_service=make_access(),
        audit_service=make_audit(),
    )
    assert isinstance(service, TrashService)


@pytest.mark.asyncio
async def test_get_trash_item_wraps_unexpected_error():
    """get_trash_item преобразует непредвиденное исключение в ServiceError."""
    actor_id = uuid.uuid4()
    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(side_effect=RuntimeError("kaboom"))

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    with pytest.raises(ServiceError):
        await service.get_trash_item(uuid.uuid4(), actor_id=actor_id)


@pytest.mark.asyncio
async def test_list_trash_wraps_unexpected_error():
    """list_trash преобразует непредвиденное исключение в ServiceError."""
    actor_id = uuid.uuid4()
    trash_repo = AsyncMock()
    trash_repo.count_user_trash_filtered = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    with pytest.raises(ServiceError):
        await service.list_trash(TrashQueryParams(), actor_id=actor_id)


@pytest.mark.asyncio
async def test_purge_one_database_error_in_second_phase():
    """_purge_one оборачивает DatabaseError, возникший после фазы удаления из хранилища."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    service, uow = make_purge_service(item)
    uow.trash.mark_purged = AsyncMock(side_effect=DatabaseError("boom"))

    result = await service.purge(
        TrashPurgeRequest(trash_item_ids=[trash_id]), actor_id=actor_id
    )

    assert result.failed_count == 1


@pytest.mark.asyncio
async def test_purge_one_refetch_none_marks_failed():
    """_purge_one завершается ошибкой, когда элемент исчезает до фазы записи purge."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)
    item.node.node_type = NodeType.FILE

    trash_repo = AsyncMock()
    # фаза построения плана получает элемент, повторная загрузка во второй фазе возвращает None
    trash_repo.get_by_id = AsyncMock(side_effect=[item, None])
    trash_repo.mark_purged = AsyncMock()

    files_repo = AsyncMock()
    files_repo.get_by_node_id = AsyncMock(return_value=make_file_mock())

    uow = make_uow(
        trash=trash_repo,
        nodes=AsyncMock(),
        files=files_repo,
        links=AsyncMock(),
        quotas=AsyncMock(),
    )
    service = make_trash_service(uow, storage_svc=make_storage_full())

    result = await service.purge(
        TrashPurgeRequest(trash_item_ids=[trash_id]), actor_id=actor_id
    )

    assert result.failed_count == 1


@pytest.mark.asyncio
async def test_purge_one_unexpected_error_in_second_phase():
    """_purge_one оборачивает обобщённое исключение, возникшее после фазы хранилища."""
    actor_id = uuid.uuid4()
    trash_id = uuid.uuid4()
    item = make_trash_item_mock(trash_id=trash_id, owner_id=actor_id)

    service, uow = make_purge_service(item)
    uow.links.delete_links_by_node = AsyncMock(side_effect=RuntimeError("kaboom"))

    result = await service.purge(
        TrashPurgeRequest(trash_item_ids=[trash_id]), actor_id=actor_id
    )

    assert result.failed_count == 1


@pytest.mark.asyncio
async def test_build_system_plan_not_found_raises():
    """_build_system_plan вызывает NotFoundServiceError, когда элемент отсутствует."""
    trash_repo = AsyncMock()
    trash_repo.get_by_id = AsyncMock(return_value=None)

    uow = make_uow(trash=trash_repo)
    service = make_trash_service(uow)

    with pytest.raises(NotFoundServiceError):
        await service._build_system_plan(uuid.uuid4())


@pytest.mark.asyncio
async def test_build_purge_plan_node_missing_after_fetch_raises():
    """_build_purge_plan вызывает ошибку, когда узел не удаётся загрузить."""
    item = make_trash_item_mock()
    item.node = None

    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=None)

    uow = make_uow(nodes=nodes_repo, files=AsyncMock())

    with pytest.raises(ServiceError):
        await _build_purge_plan(uow=uow, trash_item=item)


def test_node_snapshot_none_returns_none():
    from services.trash import _node_snapshot

    assert _node_snapshot(None) is None


@pytest.mark.asyncio
async def test_delete_storage_objects_deduplicates():
    """_delete_storage_objects пропускает дублирующиеся пары bucket/key."""
    storage = make_storage_full()
    uow = make_uow()
    service = make_trash_service(uow, storage_svc=storage)

    ref = StorageObjectRef(bucket="b", object_key="k")
    await service._delete_storage_objects([ref, ref, StorageObjectRef("b", "k2")])

    assert storage.delete_file_object.await_count == 2
