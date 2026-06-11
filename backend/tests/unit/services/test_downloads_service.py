"""Юнит-тесты для DownloadsService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.exceptions import DatabaseError
from database.models.enums import (
    AuditAction,
    BackgroundTaskStatus,
    BackgroundTaskType,
    FilePreviewStatus,
    FileProcessingStatus,
    NodeType,
    NodeVisibility,
    StorageObjectStatus,
)
from schemas.files import FileDownloadRequest, FileDownloadResponse
from schemas.folders import (
    BulkArchiveRequest,
    FolderArchiveRequest,
    FolderArchiveResponse,
)
from services.downloads import (
    DownloadsService,
    _archive_filename,
    _empty_result_error,
    _download_response_headers,
    _ensure_archive_task_downloadable,
    _ensure_file_downloadable,
    _ensure_folder_node,
    _jsonable,
    _mapping_or_empty,
    _normalize_datetime,
    _optional_int,
    _optional_str,
    _presigned_expires_at,
    _require_file_node,
    get_downloads_service,
)
from services.exceptions import (
    DownloadServiceError,
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
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
    return svc


def make_presigned_url_result():
    result = MagicMock()
    result.url = "https://example.com/file"
    result.expires_at = datetime.now(UTC) + timedelta(hours=1)
    result.expires_in_seconds = 3600
    result.method = MagicMock()
    result.method.value = "GET"
    result.headers = {}
    return result


def make_storage():
    svc = MagicMock()
    svc.generate_presigned_download_url = AsyncMock(return_value="https://example.com/file")
    svc.generate_presigned_upload_url = AsyncMock(return_value="https://example.com/upload")
    svc.create_download_url = AsyncMock(return_value=make_presigned_url_result())
    svc.build_archive_key = MagicMock(return_value="archive/key.zip")
    svc.default_archives_bucket = "archives"
    svc.default_files_bucket = "files"
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


def make_file_mock(file_id=None, node_id=None, owner_id=None):
    node = make_node_mock(node_id=node_id, owner_id=owner_id, node_type=NodeType.FILE)
    file = MagicMock()
    file.id = file_id or uuid.uuid4()
    file.node_id = node.id
    file.node = node
    file.size_bytes = 1024
    file.mime_type = "text/plain"
    file.extension = "txt"
    file.storage_status = StorageObjectStatus.AVAILABLE
    file.processing_status = FileProcessingStatus.READY
    file.preview_status = FilePreviewStatus.NOT_REQUIRED
    file.storage_bucket = "files"
    file.storage_key = "key/file.txt"
    file.preview_storage_key = None
    file.created_at = datetime.now(UTC)
    file.updated_at = datetime.now(UTC)
    return file


def make_folder_mock(node_id=None, owner_id=None):
    folder = MagicMock()
    folder.id = uuid.uuid4()
    folder.node_id = node_id or uuid.uuid4()
    folder.node = make_node_mock(node_id=folder.node_id, owner_id=owner_id, node_type=NodeType.FOLDER, name="my-folder")
    return folder


def make_task_mock(task_id=None, status=BackgroundTaskStatus.PENDING):
    task = MagicMock()
    task.id = task_id or uuid.uuid4()
    task.task_type = BackgroundTaskType.CREATE_FOLDER_ARCHIVE
    task.status = status
    task.priority = "normal"
    task.created_by = uuid.uuid4()
    task.related_entity_type = "folder"
    task.related_entity_id = uuid.uuid4()
    task.progress_percent = 0
    task.payload = None
    task.result_data = None
    task.error_message = None
    task.error_code = None
    task.attempts_count = 0
    task.max_attempts = 3
    task.idempotency_key = None
    task.scheduled_at = None
    task.started_at = None
    task.finished_at = None
    task.locked_by = None
    task.locked_until = None
    task.created_at = datetime.now(UTC)
    task.updated_at = datetime.now(UTC)
    return task


def make_access(node=None):
    svc = MagicMock()
    svc.get_accessible_node = AsyncMock(return_value=node or make_node_mock())
    svc.require_access = AsyncMock()
    return svc


def make_downloads_service(uow, access_svc=None, audit_svc=None, storage_svc=None):
    from core.config import get_settings
    return DownloadsService(
        settings=get_settings(),
        uow_factory=make_factory(uow),
        access_service=access_svc or make_access(),
        audit_service=audit_svc or make_audit(),
        storage_service=storage_svc or make_storage(),
    )


# ---------------------------------------------------------------------------
# Тесты: create_file_download_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_file_download_url_returns_response():
    """create_file_download_url возвращает FileDownloadResponse с presigned-URL."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    file = make_file_mock(file_id=file_id)

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)
    files_repo.get_required_version_by_id = AsyncMock(return_value=MagicMock())

    versions_repo = AsyncMock()
    versions_repo.get_current_version = AsyncMock(return_value=None)

    storage = make_storage()
    storage.generate_presigned_download_url = AsyncMock(
        return_value="https://example.com/file"
    )

    access = make_access(node=file.node)
    uow = make_uow(files=files_repo, versions=versions_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    data = FileDownloadRequest(file_id=file_id)
    result = await service.create_file_download_url(data, user_id=user_id)

    assert result is not None
    assert result.presigned_url == "https://example.com/file"


@pytest.mark.asyncio
async def test_create_file_download_url_permission_denied():
    """create_file_download_url вызывает PermissionServiceError для пользователей без доступа."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    file = make_file_mock(file_id=file_id)

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)

    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError(
            "Access denied",
            user_id=user_id,
            resource_type="file",
            resource_id=file_id,
            action="download",
        )
    )
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access)

    data = FileDownloadRequest(file_id=file_id)

    with pytest.raises(PermissionServiceError):
        await service.create_file_download_url(data, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: request_folder_archive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_folder_archive_returns_response():
    """request_folder_archive создаёт фоновую задачу и возвращает ответ."""
    user_id = uuid.uuid4()
    folder_node_id = uuid.uuid4()
    folder = make_folder_mock(node_id=folder_node_id, owner_id=user_id)
    folder_node = make_node_mock(
        node_id=folder_node_id, owner_id=user_id, node_type=NodeType.FOLDER, name="my-folder"
    )
    task = make_task_mock()
    updated_task = make_task_mock(task_id=task.id)
    updated_task.payload = {"folder_id": str(folder_node_id)}
    updated_task.result_data = {"archive_name": "my-folder.zip"}

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)

    tasks_repo = AsyncMock()
    tasks_repo.create_user_task = AsyncMock(return_value=task)
    tasks_repo.update = AsyncMock(return_value=updated_task)

    access = make_access(node=folder_node)
    storage = make_storage()
    uow = make_uow(folders=folders_repo, tasks=tasks_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    data = FolderArchiveRequest(folder_id=folder_node_id)
    result = await service.request_folder_archive(data, user_id=user_id)

    assert result is not None
    assert result.task_id is not None


@pytest.mark.asyncio
async def test_request_folder_archive_non_folder_raises_validation_error():
    """request_folder_archive вызывает ValidationServiceError, когда узел не папка."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file_node = make_node_mock(node_id=node_id, owner_id=user_id, node_type=NodeType.FILE)

    access = make_access(node=file_node)
    uow = make_uow()
    service = make_downloads_service(uow, access_svc=access)

    data = FolderArchiveRequest(folder_id=node_id)

    with pytest.raises((ServiceError,)):
        await service.request_folder_archive(data, user_id=user_id)


# ---------------------------------------------------------------------------
# Дополнительные хелперы
# ---------------------------------------------------------------------------


def make_completed_task_mock(task_id=None, related_entity_id=None, result_data=None):
    task = make_task_mock(task_id=task_id, status=BackgroundTaskStatus.COMPLETED)
    task.related_entity_id = related_entity_id
    task.result_data = result_data
    return task


# ---------------------------------------------------------------------------
# Тесты: create_file_download_url (extra branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_file_download_url_logs_audit_event():
    """create_file_download_url логирует событие аудита FILE_DOWNLOADED при успехе."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    file = make_file_mock(file_id=file_id)

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)

    audit = make_audit()
    audit.log_success = AsyncMock()
    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access, audit_svc=audit)

    data = FileDownloadRequest(file_id=file_id, filename="custom.txt")
    result = await service.create_file_download_url(data, user_id=user_id)

    assert isinstance(result, FileDownloadResponse)
    assert result.filename == "custom.txt"
    audit.log_success.assert_awaited_once()
    kwargs = audit.log_success.await_args.kwargs
    assert kwargs["action"] == AuditAction.FILE_DOWNLOADED


@pytest.mark.asyncio
async def test_create_file_download_url_unavailable_storage_raises_download_error():
    """create_file_download_url вызывает DownloadServiceError, когда объект недоступен."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    file = make_file_mock(file_id=file_id)
    file.storage_status = StorageObjectStatus.PENDING

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)

    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access)

    data = FileDownloadRequest(file_id=file_id)

    with pytest.raises(DownloadServiceError):
        await service.create_file_download_url(data, user_id=user_id)


@pytest.mark.asyncio
async def test_create_file_download_url_deleted_node_raises_download_error():
    """create_file_download_url вызывает DownloadServiceError для удалённого узла."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    file = make_file_mock(file_id=file_id)
    file.node.is_deleted = True

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)

    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access)

    data = FileDownloadRequest(file_id=file_id)

    with pytest.raises(DownloadServiceError):
        await service.create_file_download_url(data, user_id=user_id)


@pytest.mark.asyncio
async def test_create_file_download_url_missing_node_raises_download_error():
    """create_file_download_url вызывает DownloadServiceError, когда узел отсутствует."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    file = make_file_mock(file_id=file_id)
    file.node = None

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)

    access = make_access()
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access)

    data = FileDownloadRequest(file_id=file_id)

    with pytest.raises(DownloadServiceError):
        await service.create_file_download_url(data, user_id=user_id)


@pytest.mark.asyncio
async def test_create_file_download_url_storage_error_wrapped():
    """create_file_download_url оборачивает StorageError в ServiceError."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    file = make_file_mock(file_id=file_id)

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)

    storage = make_storage()
    storage.create_download_url = AsyncMock(side_effect=StorageError("boom"))
    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    data = FileDownloadRequest(file_id=file_id)

    with pytest.raises(ServiceError) as excinfo:
        await service.create_file_download_url(data, user_id=user_id)
    assert excinfo.value.cause is not None


@pytest.mark.asyncio
async def test_create_file_download_url_database_error_wrapped():
    """create_file_download_url оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("db down"))

    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow)

    data = FileDownloadRequest(file_id=file_id)

    with pytest.raises(ServiceError):
        await service.create_file_download_url(data, user_id=user_id)


@pytest.mark.asyncio
async def test_create_file_download_url_unexpected_error_wrapped():
    """create_file_download_url оборачивает непредвиденные ошибки в ServiceError."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("oops"))

    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow)

    data = FileDownloadRequest(file_id=file_id)

    with pytest.raises(ServiceError):
        await service.create_file_download_url(data, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: create_thumbnail_url / batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_thumbnail_url_uses_main_file_when_no_preview():
    """create_thumbnail_url возвращает presigned-URL для основного объекта файла."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file = make_file_mock()
    file.preview_available = False
    file.preview_storage_key = None

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access)

    result = await service.create_thumbnail_url(node_id=node_id, user_id=user_id)
    assert result.filename is None
    assert result.presigned_url == "https://example.com/file"


@pytest.mark.asyncio
async def test_create_thumbnail_url_uses_preview_object():
    """create_thumbnail_url использует объект превью, когда превью готово."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file = make_file_mock()
    file.preview_available = True
    file.preview_storage_key = "key/preview.jpg"

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    storage = make_storage()
    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    result = await service.create_thumbnail_url(node_id=node_id, user_id=user_id)
    assert result.presigned_url == "https://example.com/file"
    call_kwargs = storage.create_download_url.await_args.kwargs
    assert call_kwargs["object_key"] == "key/preview.jpg"


@pytest.mark.asyncio
async def test_create_thumbnail_url_storage_error_wrapped():
    """create_thumbnail_url оборачивает StorageError в ServiceError."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file = make_file_mock()

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    storage = make_storage()
    storage.create_download_url = AsyncMock(side_effect=StorageError("boom"))
    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    with pytest.raises(ServiceError):
        await service.create_thumbnail_url(node_id=node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_thumbnail_url_database_error_wrapped():
    """create_thumbnail_url оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=DatabaseError("db"))

    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow)

    with pytest.raises(ServiceError):
        await service.create_thumbnail_url(node_id=node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_thumbnail_url_unexpected_error_wrapped():
    """create_thumbnail_url оборачивает непредвиденные ошибки в ServiceError."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("x"))

    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow)

    with pytest.raises(ServiceError):
        await service.create_thumbnail_url(node_id=node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_thumbnail_url_permission_denied_reraised():
    """create_thumbnail_url пробрасывает PermissionServiceError без изменений."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file = make_file_mock()

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", user_id=user_id)
    )
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.create_thumbnail_url(node_id=node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_thumbnail_urls_batch_mixes_success_and_failure():
    """create_thumbnail_urls_batch сопоставляет URL и None для узлов с ошибкой."""
    user_id = uuid.uuid4()
    ok_node = uuid.uuid4()
    bad_node = uuid.uuid4()

    service = make_downloads_service(make_uow())

    async def fake(node_id, user_id):
        if node_id == bad_node:
            raise DownloadServiceError("nope")
        resp = MagicMock()
        resp.presigned_url = "https://example.com/thumb"
        return resp

    service.create_thumbnail_url = AsyncMock(side_effect=fake)

    result = await service.create_thumbnail_urls_batch(
        node_ids=[ok_node, bad_node], user_id=user_id
    )
    assert result[str(ok_node)] == "https://example.com/thumb"
    assert result[str(bad_node)] is None


@pytest.mark.asyncio
async def test_create_thumbnail_urls_batch_bounds_concurrency(monkeypatch):
    """Батч не запускает все per-node операции разом — конкурентность ограничена."""
    import asyncio as _asyncio

    from services import downloads as downloads_module

    # Уменьшаем семафор до 3, чтобы проверка была наглядной и быстрой.
    monkeypatch.setattr(
        downloads_module, "_thumbnail_batch_semaphore", _asyncio.Semaphore(3)
    )

    service = make_downloads_service(make_uow())
    node_ids = [uuid.uuid4() for _ in range(30)]

    in_flight = 0
    peak = 0

    async def fake(node_id, user_id):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await _asyncio.sleep(0.005)  # удерживаем слот, чтобы росла конкурентность
        in_flight -= 1
        resp = MagicMock()
        resp.presigned_url = "https://example.com/thumb"
        return resp

    service.create_thumbnail_url = AsyncMock(side_effect=fake)

    result = await service.create_thumbnail_urls_batch(
        node_ids=node_ids, user_id=uuid.uuid4()
    )

    assert len(result) == 30
    # Одновременно работало не больше, чем разрешает семафор.
    assert peak <= 3


# ---------------------------------------------------------------------------
# Тесты: stream_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_file_returns_stream_tuple():
    """stream_file возвращает (stream, mime_type, filename, size_bytes)."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file = make_file_mock()

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    storage = make_storage()
    sentinel_stream = MagicMock()
    storage.get_file_object_stream = AsyncMock(return_value=sentinel_stream)
    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    stream, mime_type, filename, size_bytes = await service.stream_file(
        node_id=node_id, user_id=user_id, offset=10, length=20
    )
    assert stream is sentinel_stream
    assert mime_type == "text/plain"
    assert filename == "test.txt"
    assert size_bytes == 1024
    storage.get_file_object_stream.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_file_falls_back_to_octet_stream():
    """stream_file откатывается к application/octet-stream для неизвестного mime."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file = make_file_mock()
    file.mime_type = None
    file.node.name = "data.unknownext"

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    storage = make_storage()
    storage.get_file_object_stream = AsyncMock(return_value=MagicMock())
    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    _, mime_type, _, _ = await service.stream_file(node_id=node_id, user_id=user_id)
    assert mime_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_stream_file_uses_mime_fallback_table():
    """stream_file разрешает mime-тип через _MIME_FALLBACKS для mkv-файлов."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file = make_file_mock()
    file.mime_type = None
    file.node.name = "movie.mkv"

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    storage = make_storage()
    storage.get_file_object_stream = AsyncMock(return_value=MagicMock())
    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    _, mime_type, _, _ = await service.stream_file(node_id=node_id, user_id=user_id)
    assert mime_type == "video/x-matroska"


@pytest.mark.asyncio
async def test_stream_file_permission_denied_reraised():
    """stream_file пробрасывает PermissionServiceError без изменений."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file = make_file_mock()

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", user_id=user_id)
    )
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.stream_file(node_id=node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_stream_file_storage_error_wrapped():
    """stream_file оборачивает StorageError в ServiceError."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    file = make_file_mock()

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    storage = make_storage()
    storage.get_file_object_stream = AsyncMock(side_effect=StorageError("boom"))
    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    with pytest.raises(ServiceError):
        await service.stream_file(node_id=node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_stream_file_database_error_wrapped():
    """stream_file оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=DatabaseError("db"))

    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow)

    with pytest.raises(ServiceError):
        await service.stream_file(node_id=node_id, user_id=user_id)


@pytest.mark.asyncio
async def test_stream_file_unexpected_error_wrapped():
    """stream_file оборачивает непредвиденные ошибки в ServiceError."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()

    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("x"))

    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow)

    with pytest.raises(ServiceError):
        await service.stream_file(node_id=node_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: request_folder_archive (extra branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_folder_archive_logs_audit_and_commits():
    """request_folder_archive фиксирует транзакцию и логирует FOLDER_ARCHIVE_REQUESTED."""
    user_id = uuid.uuid4()
    folder_node_id = uuid.uuid4()
    folder = make_folder_mock(node_id=folder_node_id, owner_id=user_id)
    folder_node = make_node_mock(
        node_id=folder_node_id,
        owner_id=user_id,
        node_type=NodeType.FOLDER,
        name="my-folder",
    )
    task = make_task_mock()
    updated_task = make_task_mock(task_id=task.id)

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(return_value=folder)
    tasks_repo = AsyncMock()
    tasks_repo.create_user_task = AsyncMock(return_value=task)
    tasks_repo.update = AsyncMock(return_value=updated_task)

    audit = make_audit()
    audit.log_success = AsyncMock()
    access = make_access(node=folder_node)
    uow = make_uow(folders=folders_repo, tasks=tasks_repo)
    service = make_downloads_service(uow, access_svc=access, audit_svc=audit)

    data = FolderArchiveRequest(
        folder_id=folder_node_id, archive_name="export", password="secret"
    )
    result = await service.request_folder_archive(data, user_id=user_id)

    assert isinstance(result, FolderArchiveResponse)
    uow.commit.assert_awaited_once()
    audit.log_success.assert_awaited_once()
    # Payload, переданный в update, должен содержать пароль и имя с суффиксом zip.
    update_call = tasks_repo.update.await_args
    payload = update_call.args[1]["payload"]
    assert payload["archive_name"] == "export.zip"
    assert payload["password"] == "secret"
    result_data = update_call.args[1]["result_data"]
    assert result_data["password_protected"] is True


@pytest.mark.asyncio
async def test_request_folder_archive_permission_denied():
    """request_folder_archive пробрасывает PermissionServiceError от сервиса доступа."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()

    access = MagicMock()
    access.get_accessible_node = AsyncMock(
        side_effect=PermissionServiceError("denied", user_id=user_id)
    )
    uow = make_uow()
    service = make_downloads_service(uow, access_svc=access)

    data = FolderArchiveRequest(folder_id=node_id)

    with pytest.raises(PermissionServiceError):
        await service.request_folder_archive(data, user_id=user_id)


@pytest.mark.asyncio
async def test_request_folder_archive_database_error_wrapped():
    """request_folder_archive оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    folder_node_id = uuid.uuid4()
    folder_node = make_node_mock(
        node_id=folder_node_id, owner_id=user_id, node_type=NodeType.FOLDER
    )

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(
        side_effect=DatabaseError("db")
    )
    access = make_access(node=folder_node)
    uow = make_uow(folders=folders_repo)
    service = make_downloads_service(uow, access_svc=access)

    data = FolderArchiveRequest(folder_id=folder_node_id)

    with pytest.raises(ServiceError):
        await service.request_folder_archive(data, user_id=user_id)


@pytest.mark.asyncio
async def test_request_folder_archive_unexpected_error_wrapped():
    """request_folder_archive оборачивает непредвиденные ошибки в ServiceError."""
    user_id = uuid.uuid4()
    folder_node_id = uuid.uuid4()
    folder_node = make_node_mock(
        node_id=folder_node_id, owner_id=user_id, node_type=NodeType.FOLDER
    )

    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(side_effect=RuntimeError("x"))
    access = make_access(node=folder_node)
    uow = make_uow(folders=folders_repo)
    service = make_downloads_service(uow, access_svc=access)

    data = FolderArchiveRequest(folder_id=folder_node_id)

    with pytest.raises(ServiceError):
        await service.request_folder_archive(data, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: request_bulk_archive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_bulk_archive_returns_response():
    """request_bulk_archive проверяет каждый узел и ставит в очередь задачу архивации."""
    user_id = uuid.uuid4()
    node_ids = [uuid.uuid4(), uuid.uuid4()]
    task = make_task_mock()
    updated_task = make_task_mock(task_id=task.id)

    tasks_repo = AsyncMock()
    tasks_repo.create_user_task = AsyncMock(return_value=task)
    tasks_repo.update = AsyncMock(return_value=updated_task)

    access = make_access()
    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow, access_svc=access)

    data = BulkArchiveRequest(node_ids=node_ids, archive_name="bundle")
    result = await service.request_bulk_archive(data, user_id=user_id)

    assert isinstance(result, FolderArchiveResponse)
    assert result.message == "Задача создания архива поставлена в очередь."
    assert access.require_access.await_count == 2
    uow.commit.assert_awaited_once()
    payload = tasks_repo.update.await_args.args[1]["payload"]
    assert payload["node_ids"] == [str(n) for n in node_ids]
    assert payload["archive_name"] == "bundle.zip"


@pytest.mark.asyncio
async def test_request_bulk_archive_permission_denied():
    """request_bulk_archive пробрасывает PermissionServiceError по каждому узлу."""
    user_id = uuid.uuid4()
    node_ids = [uuid.uuid4()]

    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", user_id=user_id)
    )
    uow = make_uow(tasks=AsyncMock())
    service = make_downloads_service(uow, access_svc=access)

    data = BulkArchiveRequest(node_ids=node_ids)

    with pytest.raises(PermissionServiceError):
        await service.request_bulk_archive(data, user_id=user_id)


@pytest.mark.asyncio
async def test_request_bulk_archive_database_error_wrapped():
    """request_bulk_archive оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    node_ids = [uuid.uuid4()]

    tasks_repo = AsyncMock()
    tasks_repo.create_user_task = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access()
    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow, access_svc=access)

    data = BulkArchiveRequest(node_ids=node_ids)

    with pytest.raises(ServiceError):
        await service.request_bulk_archive(data, user_id=user_id)


@pytest.mark.asyncio
async def test_request_bulk_archive_unexpected_error_wrapped():
    """request_bulk_archive оборачивает непредвиденные ошибки в ServiceError."""
    user_id = uuid.uuid4()
    node_ids = [uuid.uuid4()]

    tasks_repo = AsyncMock()
    tasks_repo.create_user_task = AsyncMock(side_effect=RuntimeError("x"))
    access = make_access()
    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow, access_svc=access)

    data = BulkArchiveRequest(node_ids=node_ids)

    with pytest.raises(ServiceError):
        await service.request_bulk_archive(data, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: create_archive_download_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_archive_download_url_returns_response_with_result_data():
    """create_archive_download_url собирает URL из result_data задачи."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_completed_task_mock(
        task_id=task_id,
        related_entity_id=None,
        result_data={
            "archive_name": "report",
            "storage_bucket": "archives",
            "storage_key": "archives/report.zip",
            "size_bytes": 5000,
        },
    )
    task.created_by = user_id

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    audit = make_audit()
    audit.log_success = AsyncMock()
    access = make_access()
    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow, access_svc=access, audit_svc=audit)

    result = await service.create_archive_download_url(task_id=task_id, user_id=user_id)

    assert result.filename == "report.zip"
    assert result.size_bytes == 5000
    assert result.mime_type == "application/zip"
    # Нет связанной сущности -> проверка доступа пропущена.
    access.require_access.assert_not_awaited()
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_archive_download_url_checks_access_for_related_node():
    """create_archive_download_url требует право DOWNLOAD на связанном узле."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    related = uuid.uuid4()
    task = make_completed_task_mock(
        task_id=task_id, related_entity_id=related, result_data={}
    )
    task.created_by = user_id

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    access = make_access()
    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow, access_svc=access)

    result = await service.create_archive_download_url(
        task_id=task_id, user_id=user_id, force_download=False, filename="custom"
    )
    assert result.filename == "custom.zip"
    access.require_access.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_archive_download_url_default_storage_path():
    """create_archive_download_url откатывается к bucket/key/имени по умолчанию."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_completed_task_mock(
        task_id=task_id, related_entity_id=None, result_data={}
    )
    task.created_by = user_id

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    storage = make_storage()
    access = make_access()
    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow, access_svc=access, storage_svc=storage)

    result = await service.create_archive_download_url(task_id=task_id, user_id=user_id)
    assert result.filename == f"archive-{task_id}.zip"
    assert result.size_bytes is None
    call_kwargs = storage.create_download_url.await_args.kwargs
    assert call_kwargs["bucket"] == "archives"
    assert call_kwargs["object_key"] == "archive/key.zip"


@pytest.mark.asyncio
async def test_create_archive_download_url_wrong_task_type_raises_validation():
    """create_archive_download_url вызывает ValidationServiceError для неверного типа."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_completed_task_mock(task_id=task_id)
    task.created_by = user_id
    task.task_type = BackgroundTaskType.CLEAN_TRASH

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.create_archive_download_url(task_id=task_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_archive_download_url_not_owner_raises_permission():
    """create_archive_download_url вызывает PermissionServiceError для не-владельца."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_completed_task_mock(task_id=task_id)
    task.created_by = uuid.uuid4()  # другой владелец

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.create_archive_download_url(task_id=task_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_archive_download_url_not_completed_raises_download_error():
    """create_archive_download_url вызывает DownloadServiceError, когда задача не завершена."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_task_mock(task_id=task_id, status=BackgroundTaskStatus.PENDING)
    task.created_by = user_id

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow)

    with pytest.raises(DownloadServiceError):
        await service.create_archive_download_url(task_id=task_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_archive_download_url_invalid_result_data_raises_download_error():
    """create_archive_download_url вызывает DownloadServiceError при некорректных данных результата."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_completed_task_mock(task_id=task_id, result_data="not-a-mapping")
    task.created_by = user_id

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow)

    with pytest.raises(DownloadServiceError):
        await service.create_archive_download_url(task_id=task_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_archive_download_url_storage_error_wrapped():
    """create_archive_download_url оборачивает StorageError в ServiceError."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_completed_task_mock(
        task_id=task_id, related_entity_id=None, result_data={}
    )
    task.created_by = user_id

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    storage = make_storage()
    storage.create_download_url = AsyncMock(side_effect=StorageError("boom"))
    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow, storage_svc=storage)

    with pytest.raises(ServiceError):
        await service.create_archive_download_url(task_id=task_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_archive_download_url_database_error_wrapped():
    """create_archive_download_url оборачивает DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("db"))

    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow)

    with pytest.raises(ServiceError):
        await service.create_archive_download_url(task_id=task_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_archive_download_url_unexpected_error_wrapped():
    """create_archive_download_url оборачивает непредвиденные ошибки в ServiceError."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("x"))

    uow = make_uow(tasks=tasks_repo)
    service = make_downloads_service(uow)

    with pytest.raises(ServiceError):
        await service.create_archive_download_url(task_id=task_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: логирование аудита никогда не ломает операцию
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_log_download_event_swallows_errors():
    """_safe_log_download_event не должен бросать исключение при сбое аудита."""
    audit = make_audit()
    audit.log_success = AsyncMock(side_effect=RuntimeError("audit down"))
    service = make_downloads_service(make_uow(), audit_svc=audit)

    # Не должно бросать исключение, несмотря на сбой сервиса аудита.
    await service._safe_log_download_event(
        user_id=uuid.uuid4(),
        action=AuditAction.FILE_DOWNLOADED,
        entity_id=uuid.uuid4(),
        resource_type=__import__(
            "database.models.enums", fromlist=["AuditResourceType"]
        ).AuditResourceType.FILE,
        message="msg",
        metadata={"k": "v"},
    )
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_file_download_url_succeeds_even_if_audit_fails():
    """create_file_download_url всё равно возвращает ответ при сбое аудита."""
    user_id = uuid.uuid4()
    file_id = uuid.uuid4()
    file = make_file_mock(file_id=file_id)

    files_repo = AsyncMock()
    files_repo.get_required_by_id = AsyncMock(return_value=file)

    audit = make_audit()
    audit.log_success = AsyncMock(side_effect=RuntimeError("audit down"))
    access = make_access(node=file.node)
    uow = make_uow(files=files_repo)
    service = make_downloads_service(uow, access_svc=access, audit_svc=audit)

    data = FileDownloadRequest(file_id=file_id)
    result = await service.create_file_download_url(data, user_id=user_id)
    assert isinstance(result, FileDownloadResponse)


# ---------------------------------------------------------------------------
# Тесты: module-level helper functions
# ---------------------------------------------------------------------------


def test_archive_filename_normalizes():
    assert _archive_filename("  report ") == "report.zip"
    assert _archive_filename("data.zip") == "data.zip"
    assert _archive_filename("   ") == "archive.zip"


def test_download_response_headers_attachment_and_inline():
    attach = _download_response_headers(
        filename='a"b.txt', mime_type="text/plain", force_download=True
    )
    assert attach["response-content-disposition"].startswith("attachment;")
    assert "a'b.txt" in attach["response-content-disposition"]
    assert attach["response-content-type"] == "text/plain"

    inline = _download_response_headers(
        filename="image.png", mime_type=None, force_download=False
    )
    assert inline["response-content-disposition"].startswith("inline;")
    # mime угадан по расширению
    assert inline["response-content-type"] == "image/png"

    nomime = _download_response_headers(
        filename="noext", mime_type=None, force_download=True
    )
    assert "response-content-type" not in nomime


def test_presigned_expires_at_explicit_and_computed():
    explicit = datetime(2030, 1, 1, 12, 0, 0)
    result = _presigned_expires_at(explicit, expires_in_seconds=60)
    assert result.tzinfo == UTC

    computed = _presigned_expires_at(None, expires_in_seconds=120)
    assert computed > datetime.now(UTC)


def test_normalize_datetime_naive_and_aware():
    naive = datetime(2030, 1, 1, 12, 0, 0)
    assert _normalize_datetime(naive).tzinfo == UTC
    aware = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert _normalize_datetime(aware).tzinfo == UTC


def test_mapping_optional_helpers():
    assert _mapping_or_empty({"a": 1}) == {"a": 1}
    assert _mapping_or_empty("nope") == {}
    assert _optional_str("  x ") == "x"
    assert _optional_str("   ") is None
    assert _optional_str(5) is None
    assert _optional_int(7) == 7
    assert _optional_int(True) is None
    assert _optional_int("7") is None


def test_jsonable_handles_various_types():
    assert _jsonable(None) is None
    assert _jsonable("s") == "s"
    uid = uuid.uuid4()
    assert _jsonable(uid) == str(uid)
    dt = datetime(2030, 1, 1, tzinfo=UTC)
    assert _jsonable(dt) == dt.isoformat()
    import enum

    class Plain(enum.Enum):
        A = "plain-a"

    assert _jsonable(Plain.A) == "plain-a"
    assert _jsonable({"k": uid}) == {"k": str(uid)}
    assert _jsonable([uid]) == [str(uid)]
    assert _jsonable((uid,)) == [str(uid)]

    class Weird:
        def __str__(self):
            return "weird"

    assert _jsonable(Weird()) == "weird"


def test_empty_result_error_builds_service_error():
    err = _empty_result_error("some_operation")
    assert isinstance(err, ServiceError)
    assert err.service == "downloads"
    assert err.operation == "some_operation"


def test_require_file_node_rejects_non_file():
    file = make_file_mock()
    file.node.node_type = NodeType.FOLDER
    with pytest.raises(DownloadServiceError):
        _require_file_node(file, operation="op")


def test_require_file_node_returns_node():
    file = make_file_mock()
    assert _require_file_node(file, operation="op") is file.node


def test_ensure_folder_node_accepts_and_rejects():
    folder_node = make_node_mock(node_type=NodeType.FOLDER)
    _ensure_folder_node(folder_node, operation="op")  # без исключения
    file_node = make_node_mock(node_type=NodeType.FILE)
    with pytest.raises(ValidationServiceError):
        _ensure_folder_node(file_node, operation="op")


def test_ensure_file_downloadable_ok():
    file = make_file_mock()
    _ensure_file_downloadable(file, operation="op")  # без исключения


def test_ensure_archive_task_downloadable_ok():
    user_id = uuid.uuid4()
    task = make_completed_task_mock(result_data={"k": "v"})
    task.created_by = user_id
    _ensure_archive_task_downloadable(task, user_id=user_id, operation="op")


# ---------------------------------------------------------------------------
# Тесты: get_downloads_service factory
# ---------------------------------------------------------------------------


def test_get_downloads_service_returns_new_instance_with_overrides():
    storage = make_storage()
    svc1 = get_downloads_service(storage_service=storage)
    assert isinstance(svc1, DownloadsService)
    assert svc1.storage_service is storage


def test_get_downloads_service_singleton_without_overrides():
    a = get_downloads_service()
    b = get_downloads_service()
    assert a is b
