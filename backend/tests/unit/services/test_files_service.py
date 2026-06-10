"""Юнит-тесты для FilesService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.models.enums import (
    FilePreviewStatus,
    FileProcessingStatus,
    NodeType,
    NodeVisibility,
    StorageObjectStatus,
)
from database import DatabaseError
from database.models.enums import AuditAction
from schemas.files import (
    FileMoveRequest,
    FileRenameRequest,
    FileSearchQuery,
    FileUpdateRequest,
)
from services.exceptions import (
    NotFoundServiceError,
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
)
from services.files import (
    FileMetadataCreate,
    FilesService,
    _audit_metadata,
    _files_page,
    _jsonable,
    _preview_message,
    _validate_file_sort_field,
    _validate_pagination,
    get_files_service,
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
    return svc


def make_node_mock(node_id=None, owner_id=None, node_type=NodeType.FILE, name="test.txt"):
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
    node.is_deleted = False
    node.deleted_at = None
    return node


def make_file_mock(file_id=None, node_id=None, owner_id=None, size_bytes=1024):
    node = make_node_mock(node_id=node_id, owner_id=owner_id)
    file = MagicMock()
    file.id = file_id or uuid.uuid4()
    file.node_id = node.id
    file.node = node
    file.size_bytes = size_bytes
    file.mime_type = "text/plain"
    file.extension = "txt"
    file.checksum = "abc123"
    file.checksum_algorithm = "sha256"
    file.storage_status = StorageObjectStatus.AVAILABLE
    file.processing_status = FileProcessingStatus.READY
    file.preview_status = FilePreviewStatus.NOT_REQUIRED
    file.created_at = datetime.now(UTC)
    file.updated_at = datetime.now(UTC)
    file.storage_bucket = "files"
    file.storage_key = "key/file.txt"
    return file


def make_access(node=None):
    svc = MagicMock()
    svc.get_accessible_node = AsyncMock(return_value=node or make_node_mock())
    svc.require_access = AsyncMock()
    return svc


def make_files_service(uow, access_svc=None, audit_svc=None):
    return FilesService(
        uow_factory=make_factory(uow),
        access_service=access_svc or make_access(),
        audit_service=audit_svc or make_audit(),
    )


# ---------------------------------------------------------------------------
# Тесты: get_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_file_returns_file_read():
    """get_file возвращает FileRead для доступного узла-файла."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, node_type=NodeType.FILE)
    file = make_file_mock(node_id=node_id)

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    result = await service.get_file(node_id, user_id=user_id)

    assert result is not None
    assert str(result.node_id) == str(file.node_id)


@pytest.mark.asyncio
async def test_get_file_raises_permission_error_when_access_denied():
    """get_file вызывает PermissionServiceError, когда у пользователя нет доступа к узлу."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()

    access = MagicMock()
    access.get_accessible_node = AsyncMock(
        side_effect=PermissionServiceError(
            "Access denied",
            user_id=user_id,
            resource_type="node",
            resource_id=node_id,
            action="read",
        )
    )
    uow = make_uow()
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.get_file(node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_file_raises_validation_error_for_non_file_node():
    """get_file вызывает ValidationServiceError, когда узел не файл."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    folder_node = make_node_mock(node_id=node_id, node_type=NodeType.FOLDER)

    access = make_access(node=folder_node)
    uow = make_uow()
    service = make_files_service(uow, access_svc=access)

    with pytest.raises((ValidationServiceError, ServiceError)):
        await service.get_file(node_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: get_file_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_file_by_id_returns_file_read():
    """get_file_by_id возвращает FileRead для доступного файла."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    file = make_file_mock(file_id=file_id)

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)

    access = MagicMock()
    access.require_access = AsyncMock()

    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    result = await service.get_file_by_id(file_id, user_id=user_id)

    assert result is not None
    assert str(result.id) == str(file_id)


# ---------------------------------------------------------------------------
# Тесты: create_file_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_file_metadata_success():
    """create_file_metadata создаёт и возвращает FileRead."""
    owner_id = uuid.uuid4()
    file_id = uuid.uuid4()
    node_id = uuid.uuid4()

    file = make_file_mock(file_id=file_id, node_id=node_id, owner_id=owner_id)

    files_repo = AsyncMock()
    files_repo.create_file_with_node = AsyncMock(return_value=file)
    files_repo.get_required_by_id = AsyncMock(return_value=file)

    uow = make_uow(files=files_repo)
    service = make_files_service(uow)

    data = FileMetadataCreate(
        name="test.txt",
        storage_bucket="files",
        storage_key="uploads/test.txt",
        size_bytes=1024,
        mime_type="text/plain",
        extension="txt",
    )

    result = await service.create_file_metadata(data, owner_id=owner_id)

    assert result is not None
    files_repo.create_file_with_node.assert_called_once()


@pytest.mark.asyncio
async def test_create_file_metadata_non_owner_without_parent_raises_permission_error():
    """create_file_metadata вызывает PermissionServiceError, когда не-владелец создаёт файл в корне."""
    owner_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    uow = make_uow()
    service = make_files_service(uow)

    data = FileMetadataCreate(
        name="test.txt",
        storage_bucket="files",
        storage_key="uploads/test.txt",
        size_bytes=1024,
    )

    with pytest.raises(PermissionServiceError):
        await service.create_file_metadata(data, owner_id=owner_id, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: create_file_metadata (additional branches)
# ---------------------------------------------------------------------------


def make_files_repo(file=None):
    repo = AsyncMock()
    if file is not None:
        repo.create_file_with_node = AsyncMock(return_value=file)
        repo.get_required_by_id = AsyncMock(return_value=file)
        repo.get_required_by_node_id = AsyncMock(return_value=file)
        repo.update_metadata = AsyncMock(return_value=file)
        repo.set_preview_ready = AsyncMock(return_value=file)
        repo.update_preview = AsyncMock(return_value=file)
    repo.update_storage_info = AsyncMock()
    repo.delete_by_node_id = AsyncMock()
    return repo


@pytest.mark.asyncio
async def test_create_file_metadata_with_parent_success():
    """create_file_metadata создаёт файл внутри папки, принадлежащей владельцу."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id, node_type=NodeType.FOLDER)
    file = make_file_mock(owner_id=owner_id)

    files_repo = make_files_repo(file)
    access = make_access(node=parent)
    uow = make_uow(files=files_repo)
    audit = make_audit()
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    data = FileMetadataCreate(
        name="x.txt",
        storage_bucket="files",
        storage_key="k/x.txt",
        size_bytes=10,
        parent_id=parent_id,
    )
    result = await service.create_file_metadata(data, owner_id=owner_id)

    assert result is not None
    files_repo.create_file_with_node.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_file_metadata_parent_not_folder_raises_validation():
    """create_file_metadata вызывает ValidationServiceError, когда родитель не папка."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id, node_type=NodeType.FILE)
    access = make_access(node=parent)
    uow = make_uow()
    service = make_files_service(uow, access_svc=access)

    data = FileMetadataCreate(
        name="x.txt", storage_bucket="b", storage_key="k", size_bytes=1, parent_id=parent_id
    )
    with pytest.raises(ValidationServiceError):
        await service.create_file_metadata(data, owner_id=owner_id)


@pytest.mark.asyncio
async def test_create_file_metadata_parent_owner_mismatch_raises_validation():
    """create_file_metadata вызывает ValidationServiceError, когда владелец родителя отличается."""
    owner_id = uuid.uuid4()
    other_owner = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=other_owner, node_type=NodeType.FOLDER)
    access = make_access(node=parent)
    uow = make_uow()
    service = make_files_service(uow, access_svc=access)

    data = FileMetadataCreate(
        name="x.txt", storage_bucket="b", storage_key="k", size_bytes=1, parent_id=parent_id
    )
    with pytest.raises(ValidationServiceError):
        await service.create_file_metadata(data, owner_id=owner_id)


@pytest.mark.asyncio
async def test_create_file_metadata_database_error_wrapped():
    """create_file_metadata преобразует DatabaseError в ServiceError."""
    owner_id = uuid.uuid4()
    files_repo = make_files_repo()
    files_repo.create_file_with_node = AsyncMock(side_effect=DatabaseError("boom"))
    uow = make_uow(files=files_repo)
    service = make_files_service(uow)

    data = FileMetadataCreate(name="x", storage_bucket="b", storage_key="k", size_bytes=1)
    with pytest.raises(ServiceError):
        await service.create_file_metadata(data, owner_id=owner_id)


@pytest.mark.asyncio
async def test_create_file_metadata_unexpected_error_wrapped():
    """create_file_metadata преобразует непредвиденную ошибку в ServiceError."""
    owner_id = uuid.uuid4()
    files_repo = make_files_repo()
    files_repo.create_file_with_node = AsyncMock(side_effect=RuntimeError("kaboom"))
    uow = make_uow(files=files_repo)
    service = make_files_service(uow)

    data = FileMetadataCreate(name="x", storage_bucket="b", storage_key="k", size_bytes=1)
    with pytest.raises(ServiceError):
        await service.create_file_metadata(data, owner_id=owner_id)


# ---------------------------------------------------------------------------
# Тесты: пути ошибок get_file / get_file_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_file_database_error_wrapped():
    """get_file преобразует DatabaseError в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_file(node.id, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_file_by_id_non_file_node_raises_validation():
    """get_file_by_id вызывает ValidationServiceError, когда связанный узел не файл."""
    file = make_file_mock()
    file.node.node_type = NodeType.FOLDER
    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)
    access = MagicMock()
    access.require_access = AsyncMock()
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.get_file_by_id(file.id, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_file_by_id_node_none_skips_check():
    """get_file_by_id возвращает файл, даже когда связь с узлом не загружена."""
    file = make_file_mock()
    file.node = None
    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)
    access = MagicMock()
    access.require_access = AsyncMock()
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    result = await service.get_file_by_id(file.id, user_id=uuid.uuid4())
    assert str(result.id) == str(file.id)


@pytest.mark.asyncio
async def test_get_file_by_id_database_error_wrapped():
    """get_file_by_id преобразует DatabaseError в ServiceError."""
    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("db"))
    access = MagicMock()
    access.require_access = AsyncMock()
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_file_by_id(uuid.uuid4(), user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: update_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_file_success():
    """update_file обновляет метаданные, пишет аудит и возвращает FileRead."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    data = FileUpdateRequest(mime_type="image/png", extension="png")
    result = await service.update_file(node.id, data, actor_id=uuid.uuid4())

    assert result is not None
    files_repo.update_metadata.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_file_non_file_node_raises_validation():
    """update_file вызывает ValidationServiceError для узла-папки."""
    node = make_node_mock(node_type=NodeType.FOLDER)
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo())
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.update_file(node.id, FileUpdateRequest(), actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_file_unexpected_error_wrapped():
    """update_file преобразует непредвиденную ошибку в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = make_files_repo()
    files_repo.update_metadata = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.update_file(node.id, FileUpdateRequest(), actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_rename_file_database_error_wrapped():
    """rename_file преобразует DatabaseError в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    nodes_repo = AsyncMock()
    nodes_repo.rename_node = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.rename_file(node.id, FileRenameRequest(name="n.txt"), actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_rename_file_validation_passthrough():
    """rename_file пробрасывает ValidationServiceError для узла, не являющегося файлом."""
    node = make_node_mock(node_type=NodeType.FOLDER)
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=AsyncMock())
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ValidationServiceError):
        await service.rename_file(node.id, FileRenameRequest(name="n.txt"), actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_move_file_database_error_wrapped():
    """move_file преобразует DatabaseError в ServiceError."""
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id, node_type=NodeType.FILE)
    nodes_repo = AsyncMock()
    nodes_repo.move_node = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.move_file(node.id, FileMoveRequest(target_parent_id=None), actor_id=owner_id)


@pytest.mark.asyncio
async def test_restore_file_database_error_wrapped():
    """restore_file преобразует DatabaseError в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    nodes_repo = AsyncMock()
    nodes_repo.restore_node = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.restore_file(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_file_validation_passthrough():
    """delete_file пробрасывает ValidationServiceError для узла, не являющегося файлом."""
    node = make_node_mock(node_type=NodeType.FOLDER)
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=AsyncMock())
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ValidationServiceError):
        await service.delete_file(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_purge_file_validation_passthrough():
    """purge_file пробрасывает ValidationServiceError для узла, не являющегося файлом."""
    node = make_node_mock(node_type=NodeType.FOLDER)
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=AsyncMock())
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ValidationServiceError):
        await service.purge_file(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_file_database_error_wrapped():
    """update_file преобразует DatabaseError в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = make_files_repo()
    files_repo.update_metadata = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.update_file(node.id, FileUpdateRequest(), actor_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: rename_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_file_success():
    """rename_file переименовывает узел, пишет аудит, возвращает FileRead."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    nodes_repo = AsyncMock()
    nodes_repo.rename_node = AsyncMock()
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(files=files_repo, nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    result = await service.rename_file(node.id, FileRenameRequest(name="new.txt"), actor_id=uuid.uuid4())

    assert result is not None
    nodes_repo.rename_node.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_rename_file_unexpected_error_wrapped():
    """rename_file преобразует непредвиденную ошибку в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    nodes_repo = AsyncMock()
    nodes_repo.rename_node = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.rename_file(node.id, FileRenameRequest(name="new.txt"), actor_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: move_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_file_to_folder_success():
    """move_file перемещает файл в папку того же владельца."""
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id, node_type=NodeType.FILE)
    parent = make_node_mock(owner_id=owner_id, node_type=NodeType.FOLDER)
    file = make_file_mock(node_id=node.id, owner_id=owner_id)
    files_repo = make_files_repo(file)
    nodes_repo = AsyncMock()
    nodes_repo.move_node = AsyncMock()
    access = MagicMock()
    access.get_accessible_node = AsyncMock(side_effect=[node, parent])
    audit = make_audit()
    uow = make_uow(files=files_repo, nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    data = FileMoveRequest(target_parent_id=parent.id)
    result = await service.move_file(node.id, data, actor_id=owner_id)

    assert result is not None
    nodes_repo.move_node.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_move_file_to_root_by_owner_success():
    """move_file в корень успешно отрабатывает, когда актор — владелец."""
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id, node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id, owner_id=owner_id)
    files_repo = make_files_repo(file)
    nodes_repo = AsyncMock()
    nodes_repo.move_node = AsyncMock()
    access = make_access(node=node)
    uow = make_uow(files=files_repo, nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access)

    result = await service.move_file(node.id, FileMoveRequest(target_parent_id=None), actor_id=owner_id)
    assert result is not None
    nodes_repo.move_node.assert_called_once()


@pytest.mark.asyncio
async def test_move_file_target_not_folder_raises_validation():
    """move_file вызывает ValidationServiceError, когда цель не папка."""
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id, node_type=NodeType.FILE)
    target = make_node_mock(owner_id=owner_id, node_type=NodeType.FILE)
    access = MagicMock()
    access.get_accessible_node = AsyncMock(side_effect=[node, target])
    uow = make_uow(files=make_files_repo(), nodes=AsyncMock())
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.move_file(node.id, FileMoveRequest(target_parent_id=target.id), actor_id=owner_id)


@pytest.mark.asyncio
async def test_move_file_target_owner_mismatch_raises_validation():
    """move_file вызывает ValidationServiceError, когда владелец цели отличается."""
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id, node_type=NodeType.FILE)
    target = make_node_mock(owner_id=uuid.uuid4(), node_type=NodeType.FOLDER)
    access = MagicMock()
    access.get_accessible_node = AsyncMock(side_effect=[node, target])
    uow = make_uow(files=make_files_repo(), nodes=AsyncMock())
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.move_file(node.id, FileMoveRequest(target_parent_id=target.id), actor_id=owner_id)


@pytest.mark.asyncio
async def test_move_file_to_root_non_owner_raises_permission():
    """move_file в корень не-владельцем вызывает PermissionServiceError."""
    owner_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id, node_type=NodeType.FILE)
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=AsyncMock())
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.move_file(node.id, FileMoveRequest(target_parent_id=None), actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: delete_file / restore_file / purge_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_file_success():
    """delete_file мягко удаляет узел и пишет аудит."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    nodes_repo = AsyncMock()
    nodes_repo.soft_delete_node = AsyncMock()
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(files=files_repo, nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    result = await service.delete_file(node.id, actor_id=uuid.uuid4())
    assert result is not None
    nodes_repo.soft_delete_node.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_file_database_error_wrapped():
    """delete_file преобразует DatabaseError в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    nodes_repo = AsyncMock()
    nodes_repo.soft_delete_node = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.delete_file(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_restore_file_success():
    """restore_file восстанавливает узел и пишет аудит."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    nodes_repo = AsyncMock()
    nodes_repo.restore_node = AsyncMock()
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(files=files_repo, nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    result = await service.restore_file(node.id, actor_id=uuid.uuid4())
    assert result is not None
    nodes_repo.restore_node.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_file_non_file_node_raises_validation():
    """restore_file вызывает ValidationServiceError для узла-папки."""
    node = make_node_mock(node_type=NodeType.FOLDER)
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=AsyncMock())
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.restore_file(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_purge_file_success():
    """purge_file удаляет строку файла, помечает узел purged и пишет аудит."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    nodes_repo = AsyncMock()
    nodes_repo.mark_purged = AsyncMock()
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(files=files_repo, nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    result = await service.purge_file(node.id, actor_id=uuid.uuid4())
    assert result is None
    files_repo.delete_by_node_id.assert_called_once()
    nodes_repo.mark_purged.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_file_database_error_wrapped():
    """purge_file преобразует DatabaseError в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = make_files_repo()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo, nodes=AsyncMock())
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.purge_file(node.id, actor_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: search_files
# ---------------------------------------------------------------------------


def make_search_files_repo(files=None, total=0):
    repo = AsyncMock()
    repo.count_user_files_filtered = AsyncMock(return_value=total)
    repo.search_user_files = AsyncMock(return_value=files or [])
    return repo


@pytest.mark.asyncio
async def test_search_files_root_owner_success():
    """search_files в корне возвращает страницу для владельца."""
    user_id = uuid.uuid4()
    file = make_file_mock(owner_id=user_id)
    files_repo = make_search_files_repo(files=[file], total=1)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow)

    params = FileSearchQuery(limit=10, offset=0)
    page = await service.search_files(params, user_id=user_id)

    assert page.meta.total == 1
    assert page.meta.count == 1
    assert len(page.items) == 1


@pytest.mark.asyncio
async def test_search_files_anonymous_root_raises_permission():
    """search_files в корне без владельца вызывает PermissionServiceError."""
    files_repo = make_search_files_repo()
    uow = make_uow(files=files_repo)
    service = make_files_service(uow)

    params = FileSearchQuery(limit=10, offset=0)
    with pytest.raises(PermissionServiceError):
        await service.search_files(params, user_id=None)


@pytest.mark.asyncio
async def test_search_files_root_not_owner_raises_permission():
    """search_files в корне с несовпадающим фильтром владельца вызывает PermissionServiceError."""
    files_repo = make_search_files_repo()
    uow = make_uow(files=files_repo)
    service = make_files_service(uow)

    params = FileSearchQuery(limit=10, offset=0, owner_id=uuid.uuid4())
    with pytest.raises(PermissionServiceError):
        await service.search_files(params, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_search_files_in_folder_success():
    """search_files внутри папки проверяет доступ к родителю и выводит владельца."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id, node_type=NodeType.FOLDER)
    file = make_file_mock(owner_id=owner_id)
    files_repo = make_search_files_repo(files=[file], total=1)
    access = make_access(node=parent)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    params = FileSearchQuery(limit=10, offset=0, parent_id=parent_id)
    page = await service.search_files(params, user_id=owner_id)
    assert page.meta.total == 1


@pytest.mark.asyncio
async def test_search_files_folder_owner_mismatch_raises_validation():
    """search_files вызывает ValidationServiceError, когда фильтр владельца отличается от владельца папки."""
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=uuid.uuid4(), node_type=NodeType.FOLDER)
    access = make_access(node=parent)
    uow = make_uow(files=make_search_files_repo())
    service = make_files_service(uow, access_svc=access)

    params = FileSearchQuery(limit=10, offset=0, parent_id=parent_id, owner_id=uuid.uuid4())
    with pytest.raises(ValidationServiceError):
        await service.search_files(params, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_search_files_parent_not_folder_raises_validation():
    """search_files вызывает ValidationServiceError, когда родитель не папка."""
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, node_type=NodeType.FILE)
    access = make_access(node=parent)
    uow = make_uow(files=make_search_files_repo())
    service = make_files_service(uow, access_svc=access)

    params = FileSearchQuery(limit=10, offset=0, parent_id=parent_id)
    with pytest.raises(ValidationServiceError):
        await service.search_files(params, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_search_files_in_folder_anonymous_owner_from_parent():
    """search_files в папке выводит владельца из родителя для анонимного пользователя."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id, node_type=NodeType.FOLDER)
    file = make_file_mock(owner_id=owner_id)
    files_repo = make_search_files_repo(files=[file], total=1)
    access = make_access(node=parent)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    params = FileSearchQuery(limit=10, offset=0, parent_id=parent_id)
    page = await service.search_files(params, user_id=None)
    assert page.meta.total == 1
    # owner_id, переданный в репозиторий, должен быть владельцем родителя.
    _, kwargs = files_repo.count_user_files_filtered.call_args
    assert kwargs["owner_id"] == owner_id


@pytest.mark.asyncio
async def test_search_files_unexpected_error_wrapped():
    """search_files преобразует непредвиденную ошибку в ServiceError."""
    files_repo = make_search_files_repo()
    files_repo.count_user_files_filtered = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(files=files_repo)
    service = make_files_service(uow)

    params = FileSearchQuery(limit=10, offset=0)
    with pytest.raises(ServiceError):
        await service.search_files(params, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_search_files_database_error_wrapped():
    """search_files преобразует DatabaseError в ServiceError."""
    files_repo = make_search_files_repo()
    files_repo.count_user_files_filtered = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(files=files_repo)
    service = make_files_service(uow)

    params = FileSearchQuery(limit=10, offset=0)
    with pytest.raises(ServiceError):
        await service.search_files(params, user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        FilePreviewStatus.NOT_REQUIRED,
        FilePreviewStatus.PENDING,
        FilePreviewStatus.GENERATING,
        FilePreviewStatus.READY,
        FilePreviewStatus.FAILED,
    ],
)
async def test_get_preview_success_all_statuses(status):
    """get_preview возвращает FilePreviewRead для каждого статуса превью."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    file.preview_status = status
    file.preview_available = status == FilePreviewStatus.READY
    files_repo = make_files_repo(file)
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    preview = await service.get_preview(node.id, user_id=uuid.uuid4())
    assert preview.preview_status == status
    assert preview.message


@pytest.mark.asyncio
async def test_get_preview_non_file_raises_validation():
    """get_preview вызывает ValidationServiceError для узла-папки."""
    node = make_node_mock(node_type=NodeType.FOLDER)
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo())
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.get_preview(node.id, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_preview_database_error_wrapped():
    """get_preview преобразует DatabaseError в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = make_files_repo()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_preview(node.id, user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: preview state transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_preview_pending_success():
    """mark_preview_pending обновляет статус превью через update_preview."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    result = await service.mark_preview_pending(node.id, actor_id=uuid.uuid4())
    assert result is not None
    files_repo.update_preview.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_preview_generating_success():
    """mark_preview_generating обновляет статус превью через update_preview."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    result = await service.mark_preview_generating(node.id, actor_id=uuid.uuid4())
    assert result is not None
    files_repo.update_preview.assert_called_once()


@pytest.mark.asyncio
async def test_mark_preview_failed_success():
    """mark_preview_failed обновляет статус превью через update_preview."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    result = await service.mark_preview_failed(node.id, actor_id=uuid.uuid4())
    assert result is not None
    files_repo.update_preview.assert_called_once()


@pytest.mark.asyncio
async def test_set_preview_ready_success():
    """set_preview_ready использует метод репозитория set_preview_ready."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    result = await service.set_preview_ready(
        node.id, preview_storage_key="preview/key.jpg", actor_id=uuid.uuid4()
    )
    assert result is not None
    files_repo.set_preview_ready.assert_called_once()
    files_repo.update_preview.assert_not_called()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_preview_state_non_file_raises_validation():
    """Обновление статуса превью вызывает ValidationServiceError для узла-папки."""
    node = make_node_mock(node_type=NodeType.FOLDER)
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo())
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.mark_preview_pending(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_preview_state_database_error_wrapped():
    """Обновление статуса превью преобразует DatabaseError в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = make_files_repo()
    files_repo.update_preview = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.mark_preview_pending(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_preview_state_unexpected_error_wrapped():
    """Обновление статуса превью преобразует непредвиденную ошибку в ServiceError."""
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = make_files_repo()
    files_repo.update_preview = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.mark_preview_failed(node.id, actor_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: _safe_log_file_event resilience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_log_file_event_swallows_audit_errors():
    """Сбой сервиса аудита не ломает файловую операцию."""
    node = make_node_mock(node_type=NodeType.FILE)
    file = make_file_mock(node_id=node.id)
    files_repo = make_files_repo(file)
    access = make_access(node=node)
    audit = make_audit()
    audit.log_user_event = AsyncMock(side_effect=RuntimeError("audit down"))
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access, audit_svc=audit)

    # Не должно бросать исключение, хотя аудит падает.
    result = await service.update_file(node.id, FileUpdateRequest(), actor_id=uuid.uuid4())
    assert result is not None


@pytest.mark.asyncio
async def test_safe_log_file_event_with_metadata():
    """_safe_log_file_event объединяет дополнительные метаданные в полезную нагрузку аудита."""
    audit = make_audit()
    service = FilesService(
        uow_factory=make_factory(make_uow()),
        access_service=make_access(),
        audit_service=audit,
    )
    file = make_file_mock()
    snapshot = {
        "id": file.id,
        "node_id": file.node_id,
        "size_bytes": file.size_bytes,
        "mime_type": file.mime_type,
        "extension": file.extension,
        "checksum_algorithm": file.checksum_algorithm,
        "storage_status": file.storage_status,
        "processing_status": file.processing_status,
        "preview_status": file.preview_status,
        "node": {
            "name": "f.txt",
            "path": "/f.txt",
            "parent_id": None,
            "owner_id": file.node.owner_id,
            "is_deleted": False,
        },
    }
    await service._safe_log_file_event(
        user_id=uuid.uuid4(),
        action=AuditAction.FILE_UPDATED,
        snapshot=snapshot,
        message="msg",
        metadata={"extra": "value"},
    )
    audit.log_user_event.assert_awaited_once()
    _, kwargs = audit.log_user_event.call_args
    assert kwargs["metadata"]["extra"] == "value"
    assert kwargs["metadata"]["name"] == "f.txt"


# ---------------------------------------------------------------------------
# Тесты: module-level helpers
# ---------------------------------------------------------------------------


def test_validate_file_sort_field_normalizes():
    assert _validate_file_sort_field("  NAME ") == "name"


def test_validate_file_sort_field_invalid_raises():
    with pytest.raises(ValidationServiceError):
        _validate_file_sort_field("not_a_field")


def test_validate_pagination_ok():
    _validate_pagination(limit=10, offset=0)


def test_validate_pagination_bad_limit():
    with pytest.raises(ValidationServiceError):
        _validate_pagination(limit=0, offset=0)
    with pytest.raises(ValidationServiceError):
        _validate_pagination(limit=10_000, offset=0)


def test_validate_pagination_bad_offset():
    with pytest.raises(ValidationServiceError):
        _validate_pagination(limit=10, offset=-1)


def test_preview_message_all_statuses():
    for status in FilePreviewStatus:
        file = MagicMock()
        file.preview_status = status
        assert _preview_message(file)


def test_jsonable_handles_types():
    assert _jsonable(None) is None
    assert _jsonable(5) == 5
    assert _jsonable("x") == "x"
    uid = uuid.uuid4()
    assert _jsonable(uid) == str(uid)
    now = datetime.now(UTC)
    assert _jsonable(now) == now.isoformat()
    # StrEnum попадает в ветку str; для ветки Enum используем обычный Enum.
    import enum as _enum

    class _Plain(_enum.Enum):
        A = "a"

    assert _jsonable(_Plain.A) == "a"
    assert _jsonable(FilePreviewStatus.READY) == FilePreviewStatus.READY.value
    assert _jsonable({"a": uid})["a"] == str(uid)
    assert _jsonable([uid])[0] == str(uid)
    assert _jsonable(object()) is not None


def test_audit_metadata_without_node():
    snapshot = {
        "id": uuid.uuid4(),
        "node_id": uuid.uuid4(),
        "size_bytes": 1,
        "mime_type": "text/plain",
        "extension": "txt",
        "checksum_algorithm": "sha256",
        "storage_status": StorageObjectStatus.AVAILABLE,
        "processing_status": FileProcessingStatus.READY,
        "preview_status": FilePreviewStatus.READY,
        "node": None,
    }
    metadata = _audit_metadata(snapshot)
    assert "name" not in metadata
    assert metadata["storage_status"] == StorageObjectStatus.AVAILABLE.value


def test_files_page_slices_results():
    files = [make_file_mock() for _ in range(5)]
    page = _files_page(files, limit=2, offset=1)
    assert page.meta.total == 5
    assert page.meta.count == 2
    assert page.meta.limit == 2
    assert page.meta.offset == 1


# ---------------------------------------------------------------------------
# Тесты: get_files_service factory
# ---------------------------------------------------------------------------


def test_empty_result_error():
    from services.files import _empty_result_error

    err = _empty_result_error("op")
    assert isinstance(err, ServiceError)
    assert err.operation == "op"


@pytest.mark.asyncio
async def test_query_files_helper_invokes_repo():
    from services.files import _query_files

    file = make_file_mock()
    files_repo = AsyncMock()
    files_repo.search_user_files = AsyncMock(return_value=[file])
    uow = make_uow(files=files_repo)
    params = FileSearchQuery(limit=10, offset=0)
    result = await _query_files(uow, params=params, owner_id=uuid.uuid4())
    assert result == [file]
    files_repo.search_user_files.assert_called_once()


# ---------------------------------------------------------------------------
# Тесты: unexpected-error wrappers across read/version/preview methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_file_unexpected_error_wrapped():
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.get_file(node.id, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_file_by_id_unexpected_error_wrapped():
    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    access = MagicMock()
    access.require_access = AsyncMock()
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.get_file_by_id(uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_move_file_unexpected_error_wrapped():
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id, node_type=NodeType.FILE)
    nodes_repo = AsyncMock()
    nodes_repo.move_node = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.move_file(node.id, FileMoveRequest(target_parent_id=None), actor_id=owner_id)


@pytest.mark.asyncio
async def test_delete_file_unexpected_error_wrapped():
    node = make_node_mock(node_type=NodeType.FILE)
    nodes_repo = AsyncMock()
    nodes_repo.soft_delete_node = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.delete_file(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_restore_file_unexpected_error_wrapped():
    node = make_node_mock(node_type=NodeType.FILE)
    nodes_repo = AsyncMock()
    nodes_repo.restore_node = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(files=make_files_repo(), nodes=nodes_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.restore_file(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_purge_file_unexpected_error_wrapped():
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = make_files_repo()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo, nodes=AsyncMock())
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.purge_file(node.id, actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_preview_unexpected_error_wrapped():
    node = make_node_mock(node_type=NodeType.FILE)
    files_repo = make_files_repo()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(files=files_repo)
    service = make_files_service(uow, access_svc=access)
    with pytest.raises(ServiceError):
        await service.get_preview(node.id, user_id=uuid.uuid4())


def test_get_files_service_with_dependency_returns_new_instance():
    audit = make_audit()
    svc = get_files_service(audit_service=audit)
    assert isinstance(svc, FilesService)
    assert svc.audit_service is audit


def test_get_files_service_singleton(monkeypatch):
    import services.files as files_module

    monkeypatch.setattr(files_module, "_files_service", None)
    monkeypatch.setattr(files_module, "create_unit_of_work_factory", lambda: MagicMock())
    monkeypatch.setattr(files_module, "get_access_service", lambda **_: MagicMock())
    monkeypatch.setattr(files_module, "get_audit_service", lambda **_: MagicMock())

    first = get_files_service()
    second = get_files_service()
    assert first is second
