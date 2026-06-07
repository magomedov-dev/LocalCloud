"""Юнит-тесты для FoldersService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from database import DatabaseError
from database.models.enums import (
    BackgroundTaskStatus,
    NodeType,
    NodeVisibility,
)
from schemas.folders import (
    FolderArchiveRequest,
    FolderCreateRequest,
    FolderUpdateRequest,
)
from services.exceptions import (
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
)
from services.folders import FoldersService


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
    return svc


def make_node_mock(
    node_id=None,
    owner_id=None,
    node_type=NodeType.FOLDER,
    is_deleted=False,
    name="test-folder",
    parent_id=None,
):
    node = MagicMock()
    node.id = node_id or uuid.uuid4()
    node.owner_id = owner_id or uuid.uuid4()
    node.parent_id = parent_id
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
    node.file = None
    return node


def make_folder_mock(folder_id=None, node_id=None, owner_id=None, node=None):
    if node is None:
        node = make_node_mock(node_id=node_id, owner_id=owner_id)
    folder = MagicMock()
    folder.id = folder_id or uuid.uuid4()
    folder.node_id = node.id
    folder.node = node
    folder.description = "a folder"
    folder.color = "#3b82f6"
    folder.created_at = datetime.now(UTC)
    folder.updated_at = datetime.now(UTC)
    return folder


def make_task_mock(task_id=None, status=BackgroundTaskStatus.PENDING):
    task = MagicMock()
    task.id = task_id or uuid.uuid4()
    task.status = status
    return task


def make_access(node=None):
    svc = MagicMock()
    svc.get_accessible_node = AsyncMock(return_value=node or make_node_mock())
    svc.require_access = AsyncMock()
    return svc


def make_service(uow, access_svc=None, audit_svc=None):
    return FoldersService(
        uow_factory=make_factory(uow),
        access_service=access_svc or make_access(),
        audit_service=audit_svc or make_audit(),
    )


# ---------------------------------------------------------------------------
# Тесты: create_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_folder_root_success():
    """create_folder создаёт корневую папку для владельца и пишет аудит."""
    owner_id = uuid.uuid4()
    folder = make_folder_mock(owner_id=owner_id)

    folders_repo = AsyncMock()
    folders_repo.create_folder = AsyncMock(return_value=folder)
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)

    audit = make_audit()
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, audit_svc=audit)

    data = FolderCreateRequest(name="Documents")
    result = await service.create_folder(data, owner_id=owner_id)

    assert str(result.node_id) == str(folder.node_id)
    folders_repo.create_folder.assert_called_once()
    uow.commit.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_folder_with_parent_success():
    """create_folder успешно отрабатывает с родителем того же владельца."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id)
    folder = make_folder_mock(owner_id=owner_id)

    folders_repo = AsyncMock()
    folders_repo.create_folder = AsyncMock(return_value=folder)
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)

    access = make_access(node=parent)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    data = FolderCreateRequest(name="Sub", parent_id=parent_id)
    result = await service.create_folder(data, owner_id=owner_id, actor_id=owner_id)

    assert result is not None
    access.get_accessible_node.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_folder_parent_not_folder_raises_validation():
    """create_folder вызывает ValidationServiceError, когда родитель не папка."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id, node_type=NodeType.FILE)

    access = make_access(node=parent)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    data = FolderCreateRequest(name="Sub", parent_id=parent_id)
    with pytest.raises(ValidationServiceError):
        await service.create_folder(data, owner_id=owner_id)


@pytest.mark.asyncio
async def test_create_folder_parent_owner_mismatch_raises_validation():
    """create_folder вызывает ValidationServiceError, когда владелец родителя отличается."""
    owner_id = uuid.uuid4()
    other_owner = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=other_owner)

    access = make_access(node=parent)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    data = FolderCreateRequest(name="Sub", parent_id=parent_id)
    with pytest.raises(ValidationServiceError):
        await service.create_folder(data, owner_id=owner_id)


@pytest.mark.asyncio
async def test_create_folder_root_non_owner_raises_permission():
    """create_folder вызывает PermissionServiceError, когда не-владелец создаёт корневую папку."""
    owner_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    uow = make_uow()
    service = make_service(uow)

    data = FolderCreateRequest(name="Documents")
    with pytest.raises(PermissionServiceError):
        await service.create_folder(data, owner_id=owner_id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_create_folder_database_error_wrapped():
    """create_folder оборачивает DatabaseError в ServiceError."""
    owner_id = uuid.uuid4()

    folders_repo = AsyncMock()
    folders_repo.create_folder = AsyncMock(side_effect=DatabaseError("boom"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    data = FolderCreateRequest(name="Documents")
    with pytest.raises(ServiceError):
        await service.create_folder(data, owner_id=owner_id)


@pytest.mark.asyncio
async def test_create_folder_unexpected_error_wrapped():
    """create_folder оборачивает непредвиденное исключение в ServiceError."""
    owner_id = uuid.uuid4()

    folders_repo = AsyncMock()
    folders_repo.create_folder = AsyncMock(side_effect=RuntimeError("kaboom"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    data = FolderCreateRequest(name="Documents")
    with pytest.raises(ServiceError):
        await service.create_folder(data, owner_id=owner_id)


# ---------------------------------------------------------------------------
# Тесты: get_folder_node_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_folder_node_id_success():
    """get_folder_node_id возвращает id узла папки."""
    folder_id = uuid.uuid4()
    node_id = uuid.uuid4()
    folder = make_folder_mock(folder_id=folder_id, node_id=node_id)

    folders_repo = AsyncMock()
    folders_repo.get_required_folder_by_id = AsyncMock(return_value=folder)

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    result = await service.get_folder_node_id(folder_id)
    assert str(result) == str(folder.node_id)


@pytest.mark.asyncio
async def test_get_folder_node_id_none_raises_empty_result():
    """get_folder_node_id вызывает ServiceError, когда у папки нет id узла."""
    folder = make_folder_mock()
    folder.node_id = None

    folders_repo = AsyncMock()
    folders_repo.get_required_folder_by_id = AsyncMock(return_value=folder)

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_folder_node_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_folder_node_id_database_error_wrapped():
    """get_folder_node_id оборачивает DatabaseError в ServiceError."""
    folders_repo = AsyncMock()
    folders_repo.get_required_folder_by_id = AsyncMock(side_effect=DatabaseError("x"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_folder_node_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_folder_node_id_unexpected_error_wrapped():
    """get_folder_node_id оборачивает непредвиденное исключение в ServiceError."""
    folders_repo = AsyncMock()
    folders_repo.get_required_folder_by_id = AsyncMock(side_effect=RuntimeError("x"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_folder_node_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_folder_success():
    """get_folder возвращает FolderRead для доступного узла-папки."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=user_id)
    folder = make_folder_mock(node_id=node_id, owner_id=user_id, node=node)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    result = await service.get_folder(node_id, user_id=user_id)
    assert str(result.node_id) == str(folder.node_id)


@pytest.mark.asyncio
async def test_get_folder_not_folder_raises_validation():
    """get_folder вызывает ValidationServiceError, когда узел не папка."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, node_type=NodeType.FILE)

    access = make_access(node=node)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.get_folder(node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_folder_permission_error_propagates():
    """get_folder пробрасывает PermissionServiceError от сервиса доступа."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()

    access = MagicMock()
    access.get_accessible_node = AsyncMock(
        side_effect=PermissionServiceError("denied", action="read")
    )
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.get_folder(node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_folder_database_error_wrapped():
    """get_folder оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    node = make_node_mock(owner_id=user_id)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(side_effect=DatabaseError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_folder(node.id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_folder_unexpected_error_wrapped():
    """get_folder оборачивает непредвиденное исключение в ServiceError."""
    user_id = uuid.uuid4()
    node = make_node_mock(owner_id=user_id)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_folder(node.id, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: get_folder_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_folder_content_success():
    """get_folder_content возвращает папку, хлебные крошки, элементы и общее количество."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=user_id)
    folder = make_folder_mock(node_id=node_id, owner_id=user_id, node=node)
    child = make_node_mock(owner_id=user_id, name="child")

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)

    nodes_repo = AsyncMock()
    nodes_repo.get_children = AsyncMock(return_value=[child])
    nodes_repo.count_children = AsyncMock(return_value=1)
    nodes_repo.get_breadcrumbs = AsyncMock(return_value=[node])

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo, nodes=nodes_repo)
    service = make_service(uow, access_svc=access)

    result = await service.get_folder_content(node_id, user_id=user_id)
    assert result.total == 1
    assert len(result.items) == 1
    assert len(result.breadcrumbs) == 1


@pytest.mark.asyncio
async def test_get_folder_content_invalid_sort_raises_validation():
    """get_folder_content вызывает ValidationServiceError при неподдерживаемом поле сортировки узла."""
    user_id = uuid.uuid4()
    node = make_node_mock(owner_id=user_id)
    folder = make_folder_mock(node=node)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.get_folder_content(node.id, user_id=user_id, sort_by="bogus")


@pytest.mark.asyncio
async def test_get_folder_content_not_folder_raises_validation():
    """get_folder_content вызывает ValidationServiceError, когда узел не папка."""
    user_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)

    access = make_access(node=node)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.get_folder_content(node.id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_folder_content_database_error_wrapped():
    """get_folder_content оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    node = make_node_mock(owner_id=user_id)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(side_effect=DatabaseError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_folder_content(node.id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_folder_content_unexpected_error_wrapped():
    """get_folder_content оборачивает непредвиденное исключение в ServiceError."""
    user_id = uuid.uuid4()
    node = make_node_mock(owner_id=user_id)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_folder_content(node.id, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: list_folders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_folders_root_success():
    """list_folders возвращает страницу корневых папок владельца."""
    user_id = uuid.uuid4()
    folder = make_folder_mock(owner_id=user_id)

    folders_repo = AsyncMock()
    folders_repo.list_user_folders = AsyncMock(return_value=[folder])
    folders_repo.count_user_folders_filtered = AsyncMock(return_value=1)

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    result = await service.list_folders(user_id=user_id)
    assert result.meta.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_list_folders_with_parent_success():
    """list_folders с родителем разрешает владельца из родительского узла."""
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=user_id)
    folder = make_folder_mock(owner_id=user_id)

    folders_repo = AsyncMock()
    folders_repo.list_user_folders = AsyncMock(return_value=[folder])
    folders_repo.count_user_folders_filtered = AsyncMock(return_value=1)

    access = make_access(node=parent)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    result = await service.list_folders(user_id=user_id, parent_id=parent_id)
    assert result.meta.total == 1


@pytest.mark.asyncio
async def test_list_folders_parent_not_folder_raises_validation():
    """list_folders вызывает ValidationServiceError, когда родитель не папка."""
    user_id = uuid.uuid4()
    parent = make_node_mock(node_type=NodeType.FILE)

    access = make_access(node=parent)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.list_folders(user_id=user_id, parent_id=parent.id)


@pytest.mark.asyncio
async def test_list_folders_parent_owner_mismatch_raises_validation():
    """list_folders вызывает ValidationServiceError, когда фильтр владельца != владельца родителя."""
    user_id = uuid.uuid4()
    other_owner = uuid.uuid4()
    parent = make_node_mock(owner_id=other_owner)

    access = make_access(node=parent)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.list_folders(
            user_id=user_id, owner_id=user_id, parent_id=parent.id
        )


@pytest.mark.asyncio
async def test_list_folders_anonymous_raises_permission():
    """list_folders без owner/user/parent вызывает PermissionServiceError."""
    uow = make_uow()
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.list_folders(user_id=None)


@pytest.mark.asyncio
async def test_list_folders_non_owner_raises_permission():
    """list_folders вызывает PermissionServiceError, когда user != разрешённого владельца."""
    user_id = uuid.uuid4()
    other = uuid.uuid4()

    uow = make_uow()
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.list_folders(user_id=user_id, owner_id=other)


@pytest.mark.asyncio
async def test_list_folders_invalid_sort_raises_validation():
    """list_folders вызывает ValidationServiceError при неподдерживаемом поле сортировки папок."""
    user_id = uuid.uuid4()

    uow = make_uow()
    service = make_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.list_folders(user_id=user_id, sort_by="nope")


@pytest.mark.asyncio
async def test_list_folders_database_error_wrapped():
    """list_folders оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()

    folders_repo = AsyncMock()
    folders_repo.list_user_folders = AsyncMock(side_effect=DatabaseError("x"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.list_folders(user_id=user_id)


@pytest.mark.asyncio
async def test_list_folders_unexpected_error_wrapped():
    """list_folders оборачивает непредвиденное исключение в ServiceError."""
    user_id = uuid.uuid4()

    folders_repo = AsyncMock()
    folders_repo.list_user_folders = AsyncMock(side_effect=RuntimeError("x"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.list_folders(user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: update_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_folder_success():
    """update_folder обновляет метаданные, фиксирует транзакцию и пишет аудит."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)
    folder = make_folder_mock(node=node)

    folders_repo = AsyncMock()
    folders_repo.update_metadata_by_node_id = AsyncMock(return_value=folder)

    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access, audit_svc=audit)

    data = FolderUpdateRequest(description="new", color="#22c55e")
    result = await service.update_folder(node.id, data, actor_id=actor_id)

    assert result is not None
    uow.commit.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_folder_not_folder_raises_validation():
    """update_folder вызывает ValidationServiceError, когда узел не папка."""
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)

    access = make_access(node=node)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    data = FolderUpdateRequest(description="new")
    with pytest.raises(ValidationServiceError):
        await service.update_folder(node.id, data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_update_folder_database_error_wrapped():
    """update_folder оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)

    folders_repo = AsyncMock()
    folders_repo.update_metadata_by_node_id = AsyncMock(side_effect=DatabaseError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    data = FolderUpdateRequest(description="new")
    with pytest.raises(ServiceError):
        await service.update_folder(node.id, data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_update_folder_unexpected_error_wrapped():
    """update_folder оборачивает непредвиденное исключение в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)

    folders_repo = AsyncMock()
    folders_repo.update_metadata_by_node_id = AsyncMock(side_effect=RuntimeError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    data = FolderUpdateRequest(description="new")
    with pytest.raises(ServiceError):
        await service.update_folder(node.id, data, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: rename_folder (через _mutate_folder)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_folder_success():
    """rename_folder переименовывает папку, фиксирует транзакцию и пишет аудит."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)
    folder = make_folder_mock(node=node)

    folders_repo = AsyncMock()
    folders_repo.rename_folder = AsyncMock(return_value=folder)

    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access, audit_svc=audit)

    result = await service.rename_folder(node.id, new_name="renamed", actor_id=actor_id)
    assert result is not None
    folders_repo.rename_folder.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_rename_folder_not_folder_raises_validation():
    """rename_folder вызывает ValidationServiceError, когда узел не папка."""
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)

    access = make_access(node=node)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.rename_folder(node.id, new_name="x", actor_id=actor_id)


@pytest.mark.asyncio
async def test_rename_folder_database_error_wrapped():
    """rename_folder оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)

    folders_repo = AsyncMock()
    folders_repo.rename_folder = AsyncMock(side_effect=DatabaseError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.rename_folder(node.id, new_name="x", actor_id=actor_id)


@pytest.mark.asyncio
async def test_rename_folder_unexpected_error_wrapped():
    """rename_folder оборачивает непредвиденное исключение в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)

    folders_repo = AsyncMock()
    folders_repo.rename_folder = AsyncMock(side_effect=RuntimeError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.rename_folder(node.id, new_name="x", actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: move_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_folder_to_root_success():
    """move_folder в корень (target_parent_id=None) успешно отрабатывает."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)
    folder = make_folder_mock(node=node)

    folders_repo = AsyncMock()
    folders_repo.move_folder = AsyncMock(return_value=folder)

    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access, audit_svc=audit)

    result = await service.move_folder(node.id, target_parent_id=None, actor_id=actor_id)
    assert result is not None
    folders_repo.move_folder.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_move_folder_to_target_success():
    """move_folder в целевую папку проверяет доступ к обоим узлам."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id, name="src")
    target = make_node_mock(owner_id=actor_id, name="dst")
    folder = make_folder_mock(node=node)

    folders_repo = AsyncMock()
    folders_repo.move_folder = AsyncMock(return_value=folder)

    access = MagicMock()
    access.get_accessible_node = AsyncMock(side_effect=[node, target])
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    result = await service.move_folder(
        node.id, target_parent_id=target.id, actor_id=actor_id
    )
    assert result is not None
    assert access.get_accessible_node.await_count == 2


@pytest.mark.asyncio
async def test_move_folder_target_not_folder_raises_validation():
    """move_folder вызывает ValidationServiceError, когда цель не папка."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id, name="src")
    target = make_node_mock(owner_id=actor_id, name="dst", node_type=NodeType.FILE)

    access = MagicMock()
    access.get_accessible_node = AsyncMock(side_effect=[node, target])
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.move_folder(node.id, target_parent_id=target.id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_move_folder_source_not_folder_raises_validation():
    """move_folder вызывает ValidationServiceError, когда источник не папка."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id, node_type=NodeType.FILE)

    access = make_access(node=node)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.move_folder(node.id, target_parent_id=None, actor_id=actor_id)


@pytest.mark.asyncio
async def test_move_folder_database_error_wrapped():
    """move_folder оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)

    folders_repo = AsyncMock()
    folders_repo.move_folder = AsyncMock(side_effect=DatabaseError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.move_folder(node.id, target_parent_id=None, actor_id=actor_id)


@pytest.mark.asyncio
async def test_move_folder_unexpected_error_wrapped():
    """move_folder оборачивает непредвиденное исключение в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)

    folders_repo = AsyncMock()
    folders_repo.move_folder = AsyncMock(side_effect=RuntimeError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.move_folder(node.id, target_parent_id=None, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: delete_folder / restore_folder (через _mutate_folder)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_folder_success():
    """delete_folder мягко удаляет папку и пишет аудит."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)
    folder = make_folder_mock(node=node)

    folders_repo = AsyncMock()
    folders_repo.soft_delete_folder = AsyncMock(return_value=folder)

    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access, audit_svc=audit)

    result = await service.delete_folder(node.id, actor_id=actor_id)
    assert result is not None
    folders_repo.soft_delete_folder.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_folder_success():
    """restore_folder восстанавливает папку и пишет аудит."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id, is_deleted=True)
    folder = make_folder_mock(node=node)

    folders_repo = AsyncMock()
    folders_repo.restore_folder = AsyncMock(return_value=folder)

    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access, audit_svc=audit)

    result = await service.restore_folder(node.id, actor_id=actor_id)
    assert result is not None
    folders_repo.restore_folder.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_folder_audit_failure_does_not_raise():
    """delete_folder всё равно отрабатывает при сбое аудита (безопасное логирование)."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)
    folder = make_folder_mock(node=node)

    folders_repo = AsyncMock()
    folders_repo.soft_delete_folder = AsyncMock(return_value=folder)

    access = make_access(node=node)
    audit = make_audit()
    audit.log_user_event = AsyncMock(side_effect=RuntimeError("audit down"))
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access, audit_svc=audit)

    result = await service.delete_folder(node.id, actor_id=actor_id)
    assert result is not None


# ---------------------------------------------------------------------------
# Тесты: purge_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_folder_success():
    """purge_folder помечает узел purged, фиксирует транзакцию и пишет аудит."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id, is_deleted=True)
    folder = make_folder_mock(node=node)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)

    nodes_repo = AsyncMock()
    nodes_repo.mark_purged = AsyncMock()

    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(folders=folders_repo, nodes=nodes_repo)
    service = make_service(uow, access_svc=access, audit_svc=audit)

    result = await service.purge_folder(node.id, actor_id=actor_id)
    assert result is None
    nodes_repo.mark_purged.assert_awaited_once()
    uow.commit.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_folder_not_folder_raises_validation():
    """purge_folder вызывает ValidationServiceError, когда узел не папка."""
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)

    access = make_access(node=node)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.purge_folder(node.id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_purge_folder_database_error_wrapped():
    """purge_folder оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id, is_deleted=True)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(side_effect=DatabaseError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.purge_folder(node.id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_purge_folder_unexpected_error_wrapped():
    """purge_folder оборачивает непредвиденное исключение в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id, is_deleted=True)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.purge_folder(node.id, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: search_folders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_folders_root_success():
    """search_folders возвращает страницу при поиске собственных корневых папок."""
    user_id = uuid.uuid4()
    folder = make_folder_mock(owner_id=user_id)

    folders_repo = AsyncMock()
    folders_repo.search_folders = AsyncMock(return_value=[folder])
    folders_repo.count_search_results = AsyncMock(return_value=1)

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    result = await service.search_folders(query="doc", user_id=user_id)
    assert result.meta.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_search_folders_with_parent_success():
    """search_folders с родителем разрешает владельца из родителя."""
    user_id = uuid.uuid4()
    parent = make_node_mock(owner_id=user_id)
    folder = make_folder_mock(owner_id=user_id)

    folders_repo = AsyncMock()
    folders_repo.search_folders = AsyncMock(return_value=[folder])
    folders_repo.count_search_results = AsyncMock(return_value=1)

    access = make_access(node=parent)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    result = await service.search_folders(
        query=None, user_id=user_id, parent_id=parent.id
    )
    assert result.meta.total == 1


@pytest.mark.asyncio
async def test_search_folders_parent_not_folder_raises_validation():
    """search_folders вызывает ValidationServiceError, когда родитель не папка."""
    user_id = uuid.uuid4()
    parent = make_node_mock(node_type=NodeType.FILE)

    access = make_access(node=parent)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.search_folders(query="x", user_id=user_id, parent_id=parent.id)


@pytest.mark.asyncio
async def test_search_folders_anonymous_raises_permission():
    """search_folders без владельца и родителя вызывает PermissionServiceError."""
    uow = make_uow()
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.search_folders(query="x", user_id=None)


@pytest.mark.asyncio
async def test_search_folders_non_owner_root_raises_permission():
    """search_folders вызывает PermissionServiceError при поиске чужих корневых папок."""
    user_id = uuid.uuid4()
    other = uuid.uuid4()

    uow = make_uow()
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.search_folders(query="x", user_id=user_id, owner_id=other)


@pytest.mark.asyncio
async def test_search_folders_invalid_sort_raises_validation():
    """search_folders вызывает ValidationServiceError при неподдерживаемом поле сортировки."""
    user_id = uuid.uuid4()

    uow = make_uow()
    service = make_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.search_folders(query="x", user_id=user_id, sort_by="bad")


@pytest.mark.asyncio
async def test_search_folders_database_error_wrapped():
    """search_folders оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()

    folders_repo = AsyncMock()
    folders_repo.search_folders = AsyncMock(side_effect=DatabaseError("x"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.search_folders(query="x", user_id=user_id)


@pytest.mark.asyncio
async def test_search_folders_unexpected_error_wrapped():
    """search_folders оборачивает непредвиденное исключение в ServiceError."""
    user_id = uuid.uuid4()

    folders_repo = AsyncMock()
    folders_repo.search_folders = AsyncMock(side_effect=RuntimeError("x"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.search_folders(query="x", user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: request_folder_archive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_folder_archive_success():
    """request_folder_archive создаёт фоновую задачу и возвращает её id/статус."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id, name="docs")
    folder = make_folder_mock(node=node)
    task = make_task_mock(status=BackgroundTaskStatus.PENDING)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)

    tasks_repo = AsyncMock()
    tasks_repo.create_user_task = AsyncMock(return_value=task)
    tasks_repo.update = AsyncMock(return_value=task)

    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(folders=folders_repo, tasks=tasks_repo)
    service = make_service(uow, access_svc=access, audit_svc=audit)

    data = FolderArchiveRequest(folder_id=node.id, archive_name="archive", password="pw")
    result = await service.request_folder_archive(data, actor_id=actor_id)

    assert str(result.task_id) == str(task.id)
    assert result.status == BackgroundTaskStatus.PENDING
    tasks_repo.create_user_task.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_folder_archive_default_name_no_password():
    """request_folder_archive использует имя узла, когда archive_name не задан."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id, name="docs")
    folder = make_folder_mock(node=node)
    task = make_task_mock()

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)

    tasks_repo = AsyncMock()
    tasks_repo.create_user_task = AsyncMock(return_value=task)
    tasks_repo.update = AsyncMock(return_value=task)

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo, tasks=tasks_repo)
    service = make_service(uow, access_svc=access)

    data = FolderArchiveRequest(folder_id=node.id)
    result = await service.request_folder_archive(data, actor_id=actor_id)
    assert result.task_id is not None


@pytest.mark.asyncio
async def test_request_folder_archive_not_folder_raises_validation():
    """request_folder_archive вызывает ValidationServiceError, когда узел не папка."""
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)

    access = make_access(node=node)
    uow = make_uow()
    service = make_service(uow, access_svc=access)

    data = FolderArchiveRequest(folder_id=node.id)
    with pytest.raises(ValidationServiceError):
        await service.request_folder_archive(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_request_folder_archive_database_error_wrapped():
    """request_folder_archive оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(side_effect=DatabaseError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    data = FolderArchiveRequest(folder_id=node.id)
    with pytest.raises(ServiceError):
        await service.request_folder_archive(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_request_folder_archive_unexpected_error_wrapped():
    """request_folder_archive оборачивает непредвиденное исключение в ServiceError."""
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=actor_id)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("x"))

    access = make_access(node=node)
    uow = make_uow(folders=folders_repo)
    service = make_service(uow, access_svc=access)

    data = FolderArchiveRequest(folder_id=node.id)
    with pytest.raises(ServiceError):
        await service.request_folder_archive(data, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: count_folders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_folders_success():
    """count_folders возвращает количество собственных папок."""
    user_id = uuid.uuid4()

    folders_repo = AsyncMock()
    folders_repo.count_user_folders = AsyncMock(return_value=7)

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    result = await service.count_folders(owner_id=user_id, user_id=user_id)
    assert result == 7


@pytest.mark.asyncio
async def test_count_folders_non_owner_raises_permission():
    """count_folders вызывает PermissionServiceError, когда owner != user."""
    uow = make_uow()
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.count_folders(owner_id=uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_count_folders_database_error_wrapped():
    """count_folders оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()

    folders_repo = AsyncMock()
    folders_repo.count_user_folders = AsyncMock(side_effect=DatabaseError("x"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.count_folders(owner_id=user_id, user_id=user_id)


@pytest.mark.asyncio
async def test_count_folders_unexpected_error_wrapped():
    """count_folders оборачивает непредвиденное исключение в ServiceError."""
    user_id = uuid.uuid4()

    folders_repo = AsyncMock()
    folders_repo.count_user_folders = AsyncMock(side_effect=RuntimeError("x"))

    uow = make_uow(folders=folders_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.count_folders(owner_id=user_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: get_folders_service factory
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Тесты: module-level helpers
# ---------------------------------------------------------------------------


def test_node_snapshot_handles_invalid_request_error_on_file():
    """_node_snapshot откатывается к None в полях файла при InvalidRequestError."""
    from sqlalchemy.exc import InvalidRequestError

    from services.folders import _node_snapshot

    node = make_node_mock()
    type(node).file = property(
        lambda self: (_ for _ in ()).throw(InvalidRequestError("no file"))
    )

    snapshot = _node_snapshot(node)
    assert snapshot["file_size_bytes"] is None
    assert snapshot["file_mime_type"] is None


def test_node_snapshot_includes_file_fields():
    """_node_snapshot включает size/mime из загруженного файла."""
    from services.folders import _node_snapshot

    node = make_node_mock()
    file = MagicMock()
    file.size_bytes = 2048
    file.mime_type = "image/png"
    node.file = file

    snapshot = _node_snapshot(node)
    assert snapshot["file_size_bytes"] == 2048
    assert snapshot["file_mime_type"] == "image/png"


def test_jsonable_converts_supported_types():
    """_jsonable обрабатывает примитивы, UUID, Enum и произвольные объекты."""
    from services.folders import _jsonable

    assert _jsonable(None) is None
    assert _jsonable("x") == "x"
    assert _jsonable(5) == 5
    value = uuid.uuid4()
    assert _jsonable(value) == str(value)
    import enum as _enum

    class _PlainEnum(_enum.Enum):
        A = 1

    assert _jsonable(_PlainEnum.A) == 1
    assert _jsonable(datetime.now(UTC)) is not None
    assert _jsonable(object()) is not None


def test_get_folders_service_with_overrides_returns_new_instance():
    """get_folders_service возвращает новый экземпляр, когда переданы зависимости."""
    from services.folders import get_folders_service

    uow = make_uow()
    svc = get_folders_service(
        uow_factory=make_factory(uow),
        access_service=make_access(),
        audit_service=make_audit(),
    )
    assert isinstance(svc, FoldersService)


def test_get_folders_service_singleton():
    """get_folders_service возвращает кешированный синглтон, когда зависимости не переданы."""
    import services.folders as folders_module

    folders_module._folders_service = None
    first = folders_module.get_folders_service()
    second = folders_module.get_folders_service()
    assert first is second
