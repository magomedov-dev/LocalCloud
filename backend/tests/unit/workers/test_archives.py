"""Unit-тесты для воркера создания архивов (workers/archives.py)."""
from __future__ import annotations

import uuid
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.exceptions import DatabaseConnectionError
from database.models.enums import NodeType, StorageObjectStatus
from services.exceptions import ServiceError
from storage.exceptions import StorageConnectionError, StorageError
from workers import archives
from workers.archives import (
    _dedupe_member,
    _file_row_dict,
    _normalize_fs_path,
    _payload_uuid_alias,
    _resolve_folder_node_id,
    _resolve_requested_by,
    _safe_archive_member_path,
    _safe_close_response,
    _write_stream_to_zip,
    create_folder_archive_handler,
)
from workers.exceptions import WorkerTaskHandlerError
from workers.types import WorkerTaskExecutionResult


# ---------------------------------------------------------------------------
# Вспомогательные функции / фикстуры
# ---------------------------------------------------------------------------

def make_node(node_id, node_type, *, path="", name=""):
    node = MagicMock()
    node.id = node_id
    node.node_type = node_type
    node.path = path
    node.name = name
    return node


def make_file_row(node_id, *, status=StorageObjectStatus.AVAILABLE,
                  bucket="files", key="objects/key", file_id=None):
    row = MagicMock()
    row.id = file_id or uuid.uuid4()
    row.node_id = node_id
    row.storage_status = status
    row.storage_bucket = bucket
    row.storage_key = key
    return row


def make_uow():
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)

    uow.tasks = AsyncMock()
    task_row = MagicMock()
    task_row.id = uuid.uuid4()
    task_row.related_entity_id = None
    task_row.created_by = uuid.uuid4()
    uow.tasks.get_required_by_id = AsyncMock(return_value=task_row)
    uow._task_row = task_row

    uow.nodes = AsyncMock()
    uow.nodes.get_required_by_id = AsyncMock()
    uow.nodes.get_descendants = AsyncMock(return_value=[])
    uow.nodes.get_nodes_by_ids = AsyncMock(return_value=[])

    uow.files = AsyncMock()
    uow.files.list_by_node_ids = AsyncMock(return_value=[])
    return uow


class _FakeStream:
    """Имитация потокового ответа storage с методом read."""

    def __init__(self, payload: bytes):
        self._chunks = [payload] if payload else []
        self.closed = False
        self.released = False

    def read(self, _size):
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


def make_ctx(payload=None, *, uow=None, with_downloads=False):
    ctx = MagicMock()
    ctx.task_id = uuid.uuid4()
    ctx.payload = payload if payload is not None else {}
    ctx.worker_id = "w-001"
    ctx.settings = MagicMock()
    ctx.worker_settings = MagicMock()

    uow = uow or make_uow()
    ctx.uow_factory = MagicMock(return_value=uow)

    storage = MagicMock()
    storage.default_archives_bucket = "archives"
    storage.build_archive_key = MagicMock(return_value="archives/user/task.zip")
    storage.objects = MagicMock()
    storage.objects.get_object_stream = AsyncMock(
        return_value=_FakeStream(b"file-content")
    )
    storage.objects.put_object = AsyncMock(return_value=MagicMock())
    ctx.storage_service = storage

    # сервис доступа: по умолчанию разрешает всё
    services = MagicMock()
    services.access = MagicMock()
    services.access.can_read_node = AsyncMock(return_value=True)
    services.access.can_download_node = AsyncMock(return_value=True)
    if with_downloads:
        services.downloads = MagicMock()
    else:
        services.downloads = None
    ctx.services = services

    return ctx, uow


# ---------------------------------------------------------------------------
# Чистые вспомогательные функции
# ---------------------------------------------------------------------------

class TestNormalizeFsPath:
    def test_backslashes_and_trailing_slash(self) -> None:
        assert _normalize_fs_path("a\\b\\c/") == "a/b/c"

    def test_double_slashes_collapsed(self) -> None:
        assert _normalize_fs_path("a//b///c") == "a/b/c"

    def test_whitespace_stripped(self) -> None:
        assert _normalize_fs_path("  /root/  ") == "/root"


class TestSafeArchiveMemberPath:
    def test_relative_under_root(self) -> None:
        member = _safe_archive_member_path(
            folder_root_path="/root/folder",
            file_node_path="/root/folder/sub/file.txt",
            fallback_name="file.txt",
        )
        assert member == "sub/file.txt"

    def test_file_equals_root_uses_fallback(self) -> None:
        member = _safe_archive_member_path(
            folder_root_path="/root/folder",
            file_node_path="/root/folder",
            fallback_name="fb.txt",
        )
        assert member == "fb.txt"

    def test_unrelated_path_uses_basename(self) -> None:
        member = _safe_archive_member_path(
            folder_root_path="/root/folder",
            file_node_path="/other/place/doc.pdf",
            fallback_name="fb",
        )
        assert member == "doc.pdf"

    def test_traversal_raises(self) -> None:
        # корень совпадает с префиксом, поэтому в относительной части остаются сегменты `..`
        with pytest.raises(ValueError):
            _safe_archive_member_path(
                folder_root_path="/root",
                file_node_path="/root/../../etc/passwd",
                fallback_name="x",
            )

    def test_empty_relative_raises(self) -> None:
        with pytest.raises(ValueError):
            _safe_archive_member_path(
                folder_root_path="/root",
                file_node_path="/root",
                fallback_name="",
            )


class TestDedupeMember:
    def test_unique_returned_as_is(self) -> None:
        seen: set[str] = set()
        assert _dedupe_member("a/b.txt", seen) == "a/b.txt"
        assert "a/b.txt" in seen

    def test_duplicate_with_extension_gets_suffix(self) -> None:
        seen = {"file.txt"}
        result = _dedupe_member("file.txt", seen)
        assert result == "file (1).txt"

    def test_duplicate_without_extension_gets_suffix(self) -> None:
        seen = {"README"}
        result = _dedupe_member("README", seen)
        assert result == "README (1)"

    def test_multiple_collisions_increment_counter(self) -> None:
        seen = {"f.txt", "f (1).txt"}
        result = _dedupe_member("f.txt", seen)
        assert result == "f (2).txt"


class TestFileRowDict:
    def test_extracts_storage_fields(self) -> None:
        nid = uuid.uuid4()
        row = make_file_row(nid, bucket="b", key="k")
        d = _file_row_dict(row)
        assert d["node_id"] == nid
        assert d["storage_bucket"] == "b"
        assert d["storage_key"] == "k"
        assert d["storage_status"] == StorageObjectStatus.AVAILABLE


class TestPayloadUuidAlias:
    def test_returns_uuid_value(self) -> None:
        nid = uuid.uuid4()
        assert _payload_uuid_alias({"folder_node_id": nid}, "folder_node_id") == nid

    def test_returns_uuid_from_string(self) -> None:
        nid = uuid.uuid4()
        assert _payload_uuid_alias({"k": str(nid)}, "k") == nid

    def test_missing_key_raises(self) -> None:
        with pytest.raises(WorkerTaskHandlerError):
            _payload_uuid_alias({}, "k")

    def test_payload_without_get_raises(self) -> None:
        with pytest.raises(WorkerTaskHandlerError):
            _payload_uuid_alias(object(), "k")

    def test_invalid_uuid_string_raises(self) -> None:
        with pytest.raises(WorkerTaskHandlerError):
            _payload_uuid_alias({"k": "not-a-uuid"}, "k")


class TestResolveFolderNodeId:
    def test_from_payload(self) -> None:
        nid = uuid.uuid4()
        assert _resolve_folder_node_id({"folder_id": nid}, task_meta=None) == nid

    def test_falls_back_to_related_entity_id(self) -> None:
        nid = uuid.uuid4()
        result = _resolve_folder_node_id({}, task_meta={"related_entity_id": nid})
        assert result == nid

    def test_raises_when_nothing_found(self) -> None:
        with pytest.raises(WorkerTaskHandlerError):
            _resolve_folder_node_id({}, task_meta={"related_entity_id": "nope"})


class TestResolveRequestedBy:
    def test_from_payload_requested_by(self) -> None:
        uid = uuid.uuid4()
        assert _resolve_requested_by({"requested_by": uid}, task_meta=None) == uid

    def test_from_payload_user_id_string(self) -> None:
        uid = uuid.uuid4()
        assert _resolve_requested_by({"user_id": str(uid)}, task_meta=None) == uid

    def test_invalid_uuid_raises(self) -> None:
        with pytest.raises(WorkerTaskHandlerError):
            _resolve_requested_by({"requested_by": "bad"}, task_meta=None)

    def test_falls_back_to_created_by(self) -> None:
        uid = uuid.uuid4()
        result = _resolve_requested_by({}, task_meta={"created_by": uid})
        assert result == uid

    def test_raises_when_no_user(self) -> None:
        with pytest.raises(WorkerTaskHandlerError):
            _resolve_requested_by({}, task_meta={"id": "t"})


class TestWriteStreamAndClose:
    def test_write_stream_to_zip(self, tmp_path) -> None:
        zip_path = tmp_path / "out.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            _write_stream_to_zip(zf, _FakeStream(b"hello world"), "a/b.txt")
        with zipfile.ZipFile(zip_path) as zf:
            assert zf.read("a/b.txt") == b"hello world"

    def test_safe_close_response_calls_methods(self) -> None:
        stream = _FakeStream(b"")
        _safe_close_response(stream)
        assert stream.closed is True
        assert stream.released is True

    def test_safe_close_response_swallows_errors(self) -> None:
        bad = MagicMock()
        bad.close = MagicMock(side_effect=RuntimeError("boom"))
        bad.release_conn = MagicMock(side_effect=RuntimeError("boom2"))
        # Не должно выбрасывать исключение
        _safe_close_response(bad)

    def test_safe_close_response_no_methods(self) -> None:
        # Объект без close/release_conn — ничего не происходит
        _safe_close_response(object())


class TestTempFileCleanup:
    @pytest.mark.asyncio
    async def test_temp_zip_remove_oserror_swallowed(self, monkeypatch) -> None:
        # OSError из os.remove в блоке finally не должен ломать обработчик
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[])

        real_remove = archives.os.remove

        def boom(path):
            raise OSError("cannot remove")

        monkeypatch.setattr(archives.os, "remove", boom)
        try:
            result = await create_folder_archive_handler(ctx)
        finally:
            monkeypatch.setattr(archives.os, "remove", real_remove)

        assert result.success is True


# ---------------------------------------------------------------------------
# Архив одной папки: успешный сценарий
# ---------------------------------------------------------------------------

class TestSingleFolderArchiveSuccess:
    @pytest.mark.asyncio
    async def test_success_builds_and_stores_zip(self) -> None:
        folder_id = uuid.uuid4()
        file_node_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })

        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        file_node = make_node(file_node_id, NodeType.FILE,
                              path="/root/a.txt", name="a.txt")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[file_node])
        uow.files.list_by_node_ids = AsyncMock(
            return_value=[make_file_row(file_node_id)]
        )

        result = await create_folder_archive_handler(ctx)

        assert isinstance(result, WorkerTaskExecutionResult)
        assert result.success is True
        assert result.progress_percent == 100
        assert result.result_data["folder_node_id"] == str(folder_id)
        assert result.result_data["files_count"] == 1
        assert result.result_data["archive_bucket"] == "archives"
        ctx.storage_service.objects.put_object.assert_awaited_once()
        ctx.storage_service.objects.get_object_stream.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_folder_zero_files(self) -> None:
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[])
        uow.files.list_by_node_ids = AsyncMock(return_value=[])

        result = await create_folder_archive_handler(ctx)

        assert result.success is True
        assert result.result_data["files_count"] == 0
        ctx.storage_service.objects.get_object_stream.assert_not_called()
        # Объект архива всё равно загружается (пустой zip)
        ctx.storage_service.objects.put_object.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unavailable_file_skipped(self) -> None:
        folder_id = uuid.uuid4()
        file_node_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        file_node = make_node(file_node_id, NodeType.FILE,
                              path="/root/a.txt", name="a.txt")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[file_node])
        uow.files.list_by_node_ids = AsyncMock(return_value=[
            make_file_row(file_node_id, status=StorageObjectStatus.PENDING),
        ])

        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        assert result.result_data["files_count"] == 0
        ctx.storage_service.objects.get_object_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_without_storage_key_skipped(self) -> None:
        folder_id = uuid.uuid4()
        file_node_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        file_node = make_node(file_node_id, NodeType.FILE,
                              path="/root/a.txt", name="a.txt")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[file_node])
        uow.files.list_by_node_ids = AsyncMock(return_value=[
            make_file_row(file_node_id, key=""),
        ])

        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        assert result.result_data["files_count"] == 0

    @pytest.mark.asyncio
    async def test_file_row_without_uuid_node_id_skipped(self) -> None:
        folder_id = uuid.uuid4()
        file_node_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        file_node = make_node(file_node_id, NodeType.FILE,
                              path="/root/a.txt", name="a.txt")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[file_node])
        # file_row.node_id не UUID → запись пропускается при формировании
        bad_row = make_file_row(file_node_id)
        bad_row.node_id = "not-a-uuid"
        uow.files.list_by_node_ids = AsyncMock(return_value=[bad_row])

        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        assert result.result_data["files_count"] == 0

    @pytest.mark.asyncio
    async def test_file_row_node_id_not_in_node_map_skipped(self) -> None:
        # у file_row валидный UUID node_id, но нет соответствующего снимка файла
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        # Среди потомков нет файловых узлов, но есть лишняя файловая строка
        uow.nodes.get_descendants = AsyncMock(return_value=[])
        stray_row = make_file_row(uuid.uuid4())
        uow.files.list_by_node_ids = AsyncMock(return_value=[stray_row])

        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        assert result.result_data["files_count"] == 0


# ---------------------------------------------------------------------------
# Архив одной папки: ветвления и сценарии ошибок
# ---------------------------------------------------------------------------

class TestSingleFolderArchiveFailures:
    @pytest.mark.asyncio
    async def test_node_not_folder_returns_failure(self) -> None:
        node_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": node_id,
            "requested_by": uuid.uuid4(),
        })
        not_folder = make_node(node_id, NodeType.FILE, path="/root/x", name="x")
        uow.nodes.get_required_by_id = AsyncMock(return_value=not_folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[])

        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.error_code == "node_is_not_folder"

    @pytest.mark.asyncio
    async def test_permission_denied(self) -> None:
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        ctx.services.access.can_download_node = AsyncMock(return_value=False)

        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.error_code == "permission_denied"

    @pytest.mark.asyncio
    async def test_storage_connection_error_retries(self) -> None:
        folder_id = uuid.uuid4()
        file_node_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        file_node = make_node(file_node_id, NodeType.FILE,
                              path="/root/a.txt", name="a.txt")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[file_node])
        uow.files.list_by_node_ids = AsyncMock(
            return_value=[make_file_row(file_node_id)]
        )
        ctx.storage_service.objects.get_object_stream = AsyncMock(
            side_effect=StorageConnectionError("down")
        )

        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.retry is True
        assert result.error_code == "temporary_unavailable"

    @pytest.mark.asyncio
    async def test_database_connection_error_retries(self) -> None:
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        uow.nodes.get_required_by_id = AsyncMock(
            side_effect=DatabaseConnectionError("db down")
        )
        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.retry is True
        assert result.error_code == "temporary_unavailable"

    @pytest.mark.asyncio
    async def test_storage_error_returns_failure(self) -> None:
        folder_id = uuid.uuid4()
        file_node_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        file_node = make_node(file_node_id, NodeType.FILE,
                              path="/root/a.txt", name="a.txt")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[file_node])
        uow.files.list_by_node_ids = AsyncMock(
            return_value=[make_file_row(file_node_id)]
        )
        ctx.storage_service.objects.put_object = AsyncMock(
            side_effect=StorageError("write failed")
        )
        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.retry is False
        assert result.error_code == "create_folder_archive_failed"

    @pytest.mark.asyncio
    async def test_service_error_returns_failure(self) -> None:
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        ctx.services.access.can_read_node = AsyncMock(
            side_effect=ServiceError("svc")
        )
        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.error_code == "create_folder_archive_failed"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_failure(self) -> None:
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "folder_node_id": folder_id,
            "requested_by": uuid.uuid4(),
        })
        uow.nodes.get_required_by_id = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.error_code == "unexpected_create_folder_archive_error"

    @pytest.mark.asyncio
    async def test_missing_user_raises_handled_as_unexpected(self) -> None:
        # Нет requested_by в payload и нет created_by в метаданных задачи
        folder_id = uuid.uuid4()
        uow = make_uow()
        uow._task_row.created_by = None
        ctx, uow = make_ctx(payload={"folder_node_id": folder_id}, uow=uow)

        result = await create_folder_archive_handler(ctx)
        # WorkerTaskHandlerError — обычное Exception → непредвиденный сбой
        assert result.success is False
        assert result.error_code == "unexpected_create_folder_archive_error"


# ---------------------------------------------------------------------------
# Интеграция _try_service_archive через обработчик
# ---------------------------------------------------------------------------

class TestServiceArchiveShortcut:
    @pytest.mark.asyncio
    async def test_downloads_service_dict_result_used(self) -> None:
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(
            payload={"folder_node_id": folder_id, "requested_by": uuid.uuid4()},
            with_downloads=True,
        )
        ctx.services.downloads.create_folder_archive = AsyncMock(return_value={
            "archive_bucket": "archives",
            "archive_key": "k.zip",
            "archive_size_bytes": 123,
            "files_count": 2,
        })

        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        assert result.result_data["archive_key"] == "k.zip"
        assert result.result_data["files_count"] == 2
        assert result.result_data["folder_node_id"] == str(folder_id)
        # Локальная сборка не должна была произойти
        ctx.storage_service.objects.put_object.assert_not_called()

    @pytest.mark.asyncio
    async def test_downloads_service_type_error_falls_through(self) -> None:
        folder_id = uuid.uuid4()
        file_node_id = uuid.uuid4()
        ctx, uow = make_ctx(
            payload={"folder_node_id": folder_id, "requested_by": uuid.uuid4()},
            with_downloads=True,
        )
        # Метод есть, но сигнатура несовместима → TypeError → продолжаем
        ctx.services.downloads = MagicMock(spec=["create_folder_archive"])
        ctx.services.downloads.create_folder_archive = MagicMock(
            side_effect=TypeError("bad signature")
        )

        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        file_node = make_node(file_node_id, NodeType.FILE,
                              path="/root/a.txt", name="a.txt")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[file_node])
        uow.files.list_by_node_ids = AsyncMock(
            return_value=[make_file_row(file_node_id)]
        )

        result = await create_folder_archive_handler(ctx)
        # Переходит к локальной сборке
        assert result.success is True
        ctx.storage_service.objects.put_object.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_downloads_service_non_dict_result_falls_through(self) -> None:
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(
            payload={"folder_node_id": folder_id, "requested_by": uuid.uuid4()},
            with_downloads=True,
        )
        ctx.services.downloads = MagicMock(spec=["create_folder_archive"])
        # Возвращает не-dict (синхронно) → переходим к локальной сборке
        ctx.services.downloads.create_folder_archive = MagicMock(return_value=None)

        folder = make_node(folder_id, NodeType.FOLDER, path="/root", name="root")
        uow.nodes.get_required_by_id = AsyncMock(return_value=folder)
        uow.nodes.get_descendants = AsyncMock(return_value=[])

        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        ctx.storage_service.objects.put_object.assert_awaited_once()


# ---------------------------------------------------------------------------
# Сценарий массового архивирования
# ---------------------------------------------------------------------------

class TestBulkArchive:
    @pytest.mark.asyncio
    async def test_bulk_archive_files_and_folder(self) -> None:
        direct_file_id = uuid.uuid4()
        folder_id = uuid.uuid4()
        child_file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "node_ids": [str(direct_file_id), str(folder_id)],
            "requested_by": uuid.uuid4(),
        })

        direct_file = make_node(direct_file_id, NodeType.FILE,
                                path="/d.txt", name="d.txt")
        folder = make_node(folder_id, NodeType.FOLDER,
                           path="/myfolder", name="myfolder")
        child_file = make_node(child_file_id, NodeType.FILE,
                               path="/myfolder/sub/c.txt", name="c.txt")

        uow.nodes.get_nodes_by_ids = AsyncMock(return_value=[direct_file, folder])
        uow.nodes.get_descendants = AsyncMock(return_value=[child_file])
        uow.files.list_by_node_ids = AsyncMock(return_value=[
            make_file_row(direct_file_id, key="objects/d"),
            make_file_row(child_file_id, key="objects/c"),
        ])

        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        assert result.result_data["files_count"] == 2
        ctx.storage_service.objects.put_object.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_archive_missing_node_ids(self) -> None:
        ctx, uow = make_ctx(payload={
            "node_ids": ["not-a-uuid", "  "],
            "requested_by": uuid.uuid4(),
        })
        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.error_code == "missing_node_ids"

    @pytest.mark.asyncio
    async def test_bulk_archive_skips_duplicate_child(self) -> None:
        # Файл выбран и напрямую, и внутри выбранной папки → остаётся в корне
        file_id = uuid.uuid4()
        folder_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "node_ids": [file_id, folder_id],
            "requested_by": uuid.uuid4(),
        })
        the_file = make_node(file_id, NodeType.FILE,
                             path="/folder/f.txt", name="f.txt")
        folder = make_node(folder_id, NodeType.FOLDER,
                          path="/folder", name="folder")
        uow.nodes.get_nodes_by_ids = AsyncMock(return_value=[the_file, folder])
        # потомок возвращает тот же файл (уже выбран напрямую)
        uow.nodes.get_descendants = AsyncMock(return_value=[the_file])
        uow.files.list_by_node_ids = AsyncMock(return_value=[
            make_file_row(file_id, key="objects/f"),
        ])

        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        assert result.result_data["files_count"] == 1

    @pytest.mark.asyncio
    async def test_bulk_archive_folder_with_subfolder_descendant(self) -> None:
        # Потомок-папка (сам FOLDER) пропускается (continue)
        folder_id = uuid.uuid4()
        subfolder_id = uuid.uuid4()
        child_file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "node_ids": [folder_id],
            "requested_by": uuid.uuid4(),
        })
        folder = make_node(folder_id, NodeType.FOLDER, path="/f", name="f")
        subfolder = make_node(subfolder_id, NodeType.FOLDER,
                              path="/f/sub", name="sub")
        child_file = make_node(child_file_id, NodeType.FILE,
                               path="/f/sub/c.txt", name="c.txt")
        uow.nodes.get_nodes_by_ids = AsyncMock(return_value=[folder])
        uow.nodes.get_descendants = AsyncMock(
            return_value=[subfolder, child_file]
        )
        uow.files.list_by_node_ids = AsyncMock(return_value=[
            make_file_row(child_file_id, key="objects/c"),
        ])
        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        assert result.result_data["files_count"] == 1

    @pytest.mark.asyncio
    async def test_bulk_archive_storage_connection_error_retries(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "node_ids": [file_id],
            "requested_by": uuid.uuid4(),
        })
        the_file = make_node(file_id, NodeType.FILE, path="/f.txt", name="f.txt")
        uow.nodes.get_nodes_by_ids = AsyncMock(return_value=[the_file])
        uow.files.list_by_node_ids = AsyncMock(return_value=[
            make_file_row(file_id),
        ])
        ctx.storage_service.objects.get_object_stream = AsyncMock(
            side_effect=StorageConnectionError("down")
        )
        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.retry is True
        assert result.error_code == "temporary_unavailable"

    @pytest.mark.asyncio
    async def test_bulk_archive_storage_error_returns_failure(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "node_ids": [file_id],
            "requested_by": uuid.uuid4(),
        })
        the_file = make_node(file_id, NodeType.FILE, path="/f.txt", name="f.txt")
        uow.nodes.get_nodes_by_ids = AsyncMock(return_value=[the_file])
        uow.files.list_by_node_ids = AsyncMock(return_value=[
            make_file_row(file_id),
        ])
        ctx.storage_service.objects.put_object = AsyncMock(
            side_effect=StorageError("nope")
        )
        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.error_code == "create_bulk_archive_failed"

    @pytest.mark.asyncio
    async def test_bulk_archive_unexpected_error(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "node_ids": [file_id],
            "requested_by": uuid.uuid4(),
        })
        uow.nodes.get_nodes_by_ids = AsyncMock(side_effect=RuntimeError("boom"))
        result = await create_folder_archive_handler(ctx)
        assert result.success is False
        assert result.error_code == "unexpected_create_bulk_archive_error"

    @pytest.mark.asyncio
    async def test_bulk_archive_file_row_missing_skipped(self) -> None:
        # для узла вычислен member, но файловая строка не вернулась → пропуск
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={
            "node_ids": [file_id],
            "requested_by": uuid.uuid4(),
        })
        the_file = make_node(file_id, NodeType.FILE, path="/f.txt", name="f.txt")
        uow.nodes.get_nodes_by_ids = AsyncMock(return_value=[the_file])
        uow.files.list_by_node_ids = AsyncMock(return_value=[])  # нет строк
        result = await create_folder_archive_handler(ctx)
        assert result.success is True
        assert result.result_data["files_count"] == 0
