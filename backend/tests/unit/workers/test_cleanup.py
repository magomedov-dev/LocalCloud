"""Unit-тесты для cleanup worker handlers."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.models.enums import NodeType
from workers.cleanup import (
    _optional_payload_uuid,
    clean_trash_handler,
    delete_object_from_storage_handler,
)
from workers.types import WorkerTaskExecutionResult


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_uow():
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.trash = AsyncMock()
    uow.trash.get_expired_items = AsyncMock(return_value=[])
    uow.trash.mark_purged = AsyncMock()
    uow.nodes = AsyncMock()
    uow.nodes.get_by_id = AsyncMock(return_value=None)
    uow.files = AsyncMock()
    uow.files.get_by_node_id = AsyncMock(return_value=None)
    uow.links = AsyncMock()
    uow.links.find_expired_links = AsyncMock(return_value=[])
    uow.quotas = AsyncMock()
    uow.quotas.decrease_used_space = AsyncMock()
    uow.quotas.decrease_files_used = AsyncMock()
    return uow


def make_exec_context(payload=None):
    ctx = MagicMock()
    ctx.task_id = uuid.uuid4()
    ctx.payload = payload or {}
    ctx.worker_id = "w-001"
    ctx.settings = MagicMock()
    ctx.worker_settings = MagicMock()
    ctx.worker_settings.worker_cleanup_batch_size = 10
    ctx.worker_settings.worker_quota_batch_size = 10

    uow = make_uow()
    ctx.uow_factory = MagicMock(return_value=uow)

    storage_service = MagicMock()
    storage_service.delete_file_object = AsyncMock(return_value=True)
    ctx.storage_service = storage_service

    services = MagicMock()
    # По умолчанию метода cleanup_expired нет
    trash_service = MagicMock(spec=[])  # без методов
    services.trash = trash_service
    ctx.services = services

    return ctx, uow


# ---------------------------------------------------------------------------
# clean_trash_handler
# ---------------------------------------------------------------------------

class TestCleanTrashHandler:
    @pytest.mark.asyncio
    async def test_empty_trash_returns_success(self) -> None:
        ctx, uow = make_exec_context()
        result = await clean_trash_handler(ctx)

        assert isinstance(result, WorkerTaskExecutionResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_uses_cleanup_expired_if_available(self) -> None:
        ctx, uow = make_exec_context()
        # Добавляем метод cleanup_expired в сервис корзины
        cleanup_response = MagicMock()
        cleanup_response.requested_count = 5
        cleanup_response.purged_count = 4
        cleanup_response.failed_count = 1
        ctx.services.trash.cleanup_expired = AsyncMock(return_value=cleanup_response)

        result = await clean_trash_handler(ctx)

        assert result.success is True
        ctx.services.trash.cleanup_expired.assert_called_once()

    @pytest.mark.asyncio
    async def test_storage_error_on_cleanup_returns_failure(self) -> None:
        from storage.exceptions import StorageError
        ctx, uow = make_exec_context()
        # cleanup_expired выбрасывает StorageError
        ctx.services.trash.cleanup_expired = AsyncMock(
            side_effect=StorageError("storage down")
        )

        result = await clean_trash_handler(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_generic_exception_returns_failure(self) -> None:
        ctx, uow = make_exec_context()
        ctx.services.trash.cleanup_expired = AsyncMock(
            side_effect=RuntimeError("unexpected error")
        )

        result = await clean_trash_handler(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_with_owner_id_in_payload(self) -> None:
        owner_id = str(uuid.uuid4())
        ctx, uow = make_exec_context(payload={"owner_id": owner_id})
        result = await clean_trash_handler(ctx)

        assert isinstance(result, WorkerTaskExecutionResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_with_limit_in_payload(self) -> None:
        ctx, uow = make_exec_context(payload={"limit": 50})
        result = await clean_trash_handler(ctx)

        assert isinstance(result, WorkerTaskExecutionResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_storage_connection_error_returns_retry(self) -> None:
        from storage.exceptions import StorageConnectionError
        ctx, uow = make_exec_context()
        ctx.services.trash.cleanup_expired = AsyncMock(
            side_effect=StorageConnectionError("connection refused")
        )

        result = await clean_trash_handler(ctx)

        assert result.success is False
        assert result.retry is True


# ---------------------------------------------------------------------------
# delete_object_from_storage_handler
# ---------------------------------------------------------------------------

class TestDeleteObjectFromStorageHandler:
    @pytest.mark.asyncio
    async def test_valid_payload_returns_success(self) -> None:
        ctx, uow = make_exec_context(payload={
            "bucket": "localcloud-files",
            "object_key": "users/123/file.bin",
        })
        result = await delete_object_from_storage_handler(ctx)

        assert result.success is True
        ctx.storage_service.delete_file_object.assert_called_once_with(
            bucket="localcloud-files",
            object_key="users/123/file.bin",
            missing_ok=True,
        )

    @pytest.mark.asyncio
    async def test_missing_bucket_returns_failure(self) -> None:
        ctx, uow = make_exec_context(payload={
            "object_key": "users/123/file.bin",
            # без bucket
        })
        result = await delete_object_from_storage_handler(ctx)

        assert result.success is False
        assert result.error_code == "invalid_bucket"

    @pytest.mark.asyncio
    async def test_missing_object_key_returns_failure(self) -> None:
        ctx, uow = make_exec_context(payload={
            "bucket": "localcloud-files",
            # без object_key
        })
        result = await delete_object_from_storage_handler(ctx)

        assert result.success is False
        assert result.error_code == "invalid_object_key"

    @pytest.mark.asyncio
    async def test_empty_bucket_returns_failure(self) -> None:
        ctx, uow = make_exec_context(payload={
            "bucket": "   ",  # только пробелы
            "object_key": "file.bin",
        })
        result = await delete_object_from_storage_handler(ctx)

        assert result.success is False
        assert result.error_code == "invalid_bucket"

    @pytest.mark.asyncio
    async def test_empty_object_key_returns_failure(self) -> None:
        ctx, uow = make_exec_context(payload={
            "bucket": "localcloud-files",
            "object_key": "",
        })
        result = await delete_object_from_storage_handler(ctx)

        assert result.success is False
        assert result.error_code == "invalid_object_key"

    @pytest.mark.asyncio
    async def test_storage_error_returns_failure(self) -> None:
        from storage.exceptions import StorageError
        ctx, uow = make_exec_context(payload={
            "bucket": "localcloud-files",
            "object_key": "users/123/file.bin",
        })
        ctx.storage_service.delete_file_object = AsyncMock(
            side_effect=StorageError("delete failed")
        )

        result = await delete_object_from_storage_handler(ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_storage_connection_error_returns_retry(self) -> None:
        from storage.exceptions import StorageConnectionError
        ctx, uow = make_exec_context(payload={
            "bucket": "localcloud-files",
            "object_key": "users/123/file.bin",
        })
        ctx.storage_service.delete_file_object = AsyncMock(
            side_effect=StorageConnectionError("no connection")
        )

        result = await delete_object_from_storage_handler(ctx)

        assert result.success is False
        assert result.retry is True

    @pytest.mark.asyncio
    async def test_missing_ok_defaults_to_true(self) -> None:
        ctx, uow = make_exec_context(payload={
            "bucket": "localcloud-files",
            "object_key": "file.bin",
            # без missing_ok — по умолчанию должно быть True
        })
        result = await delete_object_from_storage_handler(ctx)

        assert result.success is True
        call_kwargs = ctx.storage_service.delete_file_object.call_args[1]
        assert call_kwargs["missing_ok"] is True

    @pytest.mark.asyncio
    async def test_missing_ok_false_overridden(self) -> None:
        ctx, uow = make_exec_context(payload={
            "bucket": "localcloud-files",
            "object_key": "file.bin",
            "missing_ok": False,
        })
        result = await delete_object_from_storage_handler(ctx)

        assert result.success is True
        call_kwargs = ctx.storage_service.delete_file_object.call_args[1]
        assert call_kwargs["missing_ok"] is False

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_failure(self) -> None:
        ctx, uow = make_exec_context(payload={
            "bucket": "localcloud-files",
            "object_key": "file.bin",
        })
        ctx.storage_service.delete_file_object = AsyncMock(
            side_effect=RuntimeError("unexpected crash")
        )

        result = await delete_object_from_storage_handler(ctx)

        assert result.success is False
        assert result.error_code == "unexpected_storage_delete_error"


# ---------------------------------------------------------------------------
# clean_trash_handler fallback path (_fallback_cleanup)
# ---------------------------------------------------------------------------


def make_trash_item(*, node_id=None, node=None, deleted_at=None):
    item = MagicMock()
    item.id = uuid.uuid4()
    item.node_id = node_id or uuid.uuid4()
    item.node = node
    item.deleted_at = deleted_at or datetime.now(UTC)
    return item


def make_file_node(*, owner_id=None):
    node = MagicMock()
    node.node_type = NodeType.FILE
    node.owner_id = owner_id or uuid.uuid4()
    return node


def make_folder_node():
    node = MagicMock()
    node.node_type = NodeType.FOLDER
    return node


def make_file_row(
    *,
    storage_key="files/obj",
    storage_bucket="bucket",
    versions=None,
    size_bytes=1024,
):
    file_row = MagicMock()
    file_row.storage_key = storage_key
    file_row.storage_bucket = storage_bucket
    file_row.versions = versions if versions is not None else []
    file_row.size_bytes = size_bytes
    return file_row


def make_version(*, storage_key="versions/v1", storage_bucket="bucket"):
    version = MagicMock()
    version.storage_key = storage_key
    version.storage_bucket = storage_bucket
    return version


class TestCleanTrashFallback:
    @pytest.mark.asyncio
    async def test_fallback_deletes_file_object_and_versions(self) -> None:
        ctx, uow = make_exec_context()
        node = make_file_node()
        item = make_trash_item(node=node)
        file_row = make_file_row(
            versions=[make_version(), make_version(storage_key="versions/v2")]
        )
        uow.trash.get_expired_items = AsyncMock(return_value=[item])
        uow.files.get_by_node_id = AsyncMock(return_value=file_row)

        result = await clean_trash_handler(ctx)

        assert result.success is True
        # основной объект + две версии = 3 удаления из хранилища
        assert ctx.storage_service.delete_file_object.await_count == 3
        assert result.result_data["scanned_count"] == 1
        assert result.result_data["purged_count"] == 1
        assert result.result_data["deleted_storage_objects_count"] == 3
        assert result.result_data["failed_count"] == 0
        uow.trash.mark_purged.assert_awaited_once()
        uow.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_resolves_node_via_repo_when_item_node_none(self) -> None:
        ctx, uow = make_exec_context()
        item = make_trash_item(node=None)
        uow.trash.get_expired_items = AsyncMock(return_value=[item])
        uow.nodes.get_by_id = AsyncMock(return_value=make_file_node())
        uow.files.get_by_node_id = AsyncMock(return_value=make_file_row())

        result = await clean_trash_handler(ctx)

        assert result.success is True
        uow.nodes.get_by_id.assert_awaited_once_with(item.node_id)
        assert result.result_data["deleted_storage_objects_count"] == 1

    @pytest.mark.asyncio
    async def test_fallback_skips_storage_for_folder_node(self) -> None:
        ctx, uow = make_exec_context()
        item = make_trash_item(node=make_folder_node())
        uow.trash.get_expired_items = AsyncMock(return_value=[item])

        result = await clean_trash_handler(ctx)

        assert result.success is True
        ctx.storage_service.delete_file_object.assert_not_called()
        uow.files.get_by_node_id.assert_not_called()
        assert result.result_data["purged_count"] == 1
        assert result.result_data["deleted_storage_objects_count"] == 0

    @pytest.mark.asyncio
    async def test_fallback_none_node_still_purged(self) -> None:
        ctx, uow = make_exec_context()
        item = make_trash_item(node=None)
        uow.trash.get_expired_items = AsyncMock(return_value=[item])
        uow.nodes.get_by_id = AsyncMock(return_value=None)

        result = await clean_trash_handler(ctx)

        assert result.success is True
        uow.files.get_by_node_id.assert_not_called()
        assert result.result_data["purged_count"] == 1

    @pytest.mark.asyncio
    async def test_fallback_file_row_none_no_storage_delete(self) -> None:
        ctx, uow = make_exec_context()
        item = make_trash_item(node=make_file_node())
        uow.trash.get_expired_items = AsyncMock(return_value=[item])
        uow.files.get_by_node_id = AsyncMock(return_value=None)

        result = await clean_trash_handler(ctx)

        assert result.success is True
        ctx.storage_service.delete_file_object.assert_not_called()
        assert result.result_data["deleted_storage_objects_count"] == 0

    @pytest.mark.asyncio
    async def test_fallback_empty_storage_key_skips_delete(self) -> None:
        ctx, uow = make_exec_context()
        item = make_trash_item(node=make_file_node())
        file_row = make_file_row(
            storage_key="", versions=[make_version(storage_key="")]
        )
        uow.trash.get_expired_items = AsyncMock(return_value=[item])
        uow.files.get_by_node_id = AsyncMock(return_value=file_row)

        result = await clean_trash_handler(ctx)

        assert result.success is True
        ctx.storage_service.delete_file_object.assert_not_called()
        assert result.result_data["deleted_storage_objects_count"] == 0

    @pytest.mark.asyncio
    async def test_fallback_decrements_quota_per_owner(self) -> None:
        """Purged-файлы освобождают квоту владельца (атомарно с purge)."""
        ctx, uow = make_exec_context()
        owner = uuid.uuid4()
        node1 = make_file_node(owner_id=owner)
        node2 = make_file_node(owner_id=owner)
        item1 = make_trash_item(node=node1)
        item2 = make_trash_item(node=node2)
        uow.trash.get_expired_items = AsyncMock(return_value=[item1, item2])
        uow.files.get_by_node_id = AsyncMock(
            side_effect=[
                make_file_row(size_bytes=1000, storage_key="f1"),
                make_file_row(size_bytes=500, storage_key="f2"),
            ]
        )

        result = await clean_trash_handler(ctx)

        assert result.success is True
        assert result.result_data["purged_count"] == 2
        # Два файла одного владельца агрегируются в один декремент.
        uow.quotas.decrease_used_space.assert_awaited_once_with(
            user_id=owner, size_bytes=1500, flush=True, refresh=False
        )
        uow.quotas.decrease_files_used.assert_awaited_once_with(
            user_id=owner, count=2, flush=True, refresh=False
        )

    @pytest.mark.asyncio
    async def test_fallback_no_quota_change_for_folder_only(self) -> None:
        """Папки не занимают квоту — декремента нет."""
        ctx, uow = make_exec_context()
        item = make_trash_item(node=make_folder_node())
        uow.trash.get_expired_items = AsyncMock(return_value=[item])

        result = await clean_trash_handler(ctx)

        assert result.success is True
        assert result.result_data["purged_count"] == 1
        uow.quotas.decrease_used_space.assert_not_awaited()
        uow.quotas.decrease_files_used.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fallback_failed_purge_does_not_decrement_quota(self) -> None:
        """Сбой mark_purged не списывает квоту за этот файл."""
        ctx, uow = make_exec_context()
        item = make_trash_item(node=make_file_node())
        uow.trash.get_expired_items = AsyncMock(return_value=[item])
        uow.files.get_by_node_id = AsyncMock(return_value=make_file_row())
        uow.trash.mark_purged = AsyncMock(side_effect=RuntimeError("boom"))

        result = await clean_trash_handler(ctx)

        assert result.success is True
        assert result.result_data["failed_count"] == 1
        assert result.result_data["purged_count"] == 0
        uow.quotas.decrease_used_space.assert_not_awaited()
        uow.quotas.decrease_files_used.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fallback_per_item_error_increments_failed(self) -> None:
        ctx, uow = make_exec_context()
        item = make_trash_item(node=make_file_node())
        uow.trash.get_expired_items = AsyncMock(return_value=[item])
        uow.files.get_by_node_id = AsyncMock(side_effect=RuntimeError("boom"))

        result = await clean_trash_handler(ctx)

        # Исключение по отдельному элементу перехвачено; обработчик успешен.
        assert result.success is True
        assert result.result_data["scanned_count"] == 1
        assert result.result_data["failed_count"] == 1
        assert result.result_data["purged_count"] == 0
        uow.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_filters_by_deleted_before(self) -> None:
        ctx, uow = make_exec_context(
            payload={"deleted_before": "2020-01-01T00:00:00+00:00"}
        )
        old_item = make_trash_item(
            node=make_folder_node(),
            deleted_at=datetime(2019, 1, 1, tzinfo=UTC),
        )
        new_item = make_trash_item(
            node=make_folder_node(),
            deleted_at=datetime(2021, 1, 1, tzinfo=UTC),
        )
        uow.trash.get_expired_items = AsyncMock(return_value=[old_item, new_item])

        result = await clean_trash_handler(ctx)

        assert result.success is True
        # Обрабатывается только старый элемент (<= 2020-01-01).
        assert result.result_data["scanned_count"] == 1
        assert result.result_data["purged_count"] == 1

    @pytest.mark.asyncio
    async def test_fallback_limit_explicit_none_defaults_to_100(self) -> None:
        # Явный None в limit -> payload_int возвращает значение по умолчанию (100),
        # которое передаётся напрямую в репозиторий.
        ctx, uow = make_exec_context(payload={"limit": None})
        uow.trash.get_expired_items = AsyncMock(return_value=[])

        result = await clean_trash_handler(ctx)

        assert result.success is True
        call_kwargs = uow.trash.get_expired_items.call_args[1]
        assert call_kwargs["limit"] == 100

    @pytest.mark.asyncio
    async def test_fallback_explicit_limit_passed_through(self) -> None:
        ctx, uow = make_exec_context(payload={"limit": 250})
        uow.trash.get_expired_items = AsyncMock(return_value=[])

        result = await clean_trash_handler(ctx)

        assert result.success is True
        call_kwargs = uow.trash.get_expired_items.call_args[1]
        assert call_kwargs["limit"] == 250


# ---------------------------------------------------------------------------
# _optional_payload_uuid
# ---------------------------------------------------------------------------


class TestOptionalPayloadUuid:
    def test_returns_none_when_missing(self) -> None:
        assert _optional_payload_uuid({}, "owner_id") is None

    def test_returns_uuid_when_uuid_instance(self) -> None:
        value = uuid.uuid4()
        assert _optional_payload_uuid({"owner_id": value}, "owner_id") is value

    def test_parses_uuid_string(self) -> None:
        value = uuid.uuid4()
        result = _optional_payload_uuid({"owner_id": str(value)}, "owner_id")
        assert result == value

    def test_raises_on_invalid_type(self) -> None:
        with pytest.raises(ValueError):
            _optional_payload_uuid({"owner_id": 12345}, "owner_id")
