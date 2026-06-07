"""Unit-тесты для воркера генерации preview (workers/previews.py)."""
from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from database.exceptions import DatabaseConnectionError
from database.models.enums import FilePreviewStatus
from services.exceptions import ServiceError
from storage.exceptions import StorageConnectionError, StorageError
from workers import previews
from workers.previews import (
    _compress_to_webp,
    _mime_is_image,
    _mime_is_pdf,
    _mime_requires_preview,
    _resolve_owner_id,
    generate_file_preview_handler,
)
from workers.types import WorkerTaskExecutionResult


# ---------------------------------------------------------------------------
# Вспомогательные функции / фикстуры
# ---------------------------------------------------------------------------

def make_file_row(
    *,
    file_id=None,
    owner_id=None,
    mime_type="image/png",
    preview_status=FilePreviewStatus.PENDING,
    preview_storage_key=None,
    bucket="files",
    key="objects/key",
):
    row = MagicMock()
    row.id = file_id or uuid.uuid4()
    row.mime_type = mime_type
    row.preview_status = preview_status
    row.preview_storage_key = preview_storage_key
    row.storage_bucket = bucket
    row.storage_key = key
    node = MagicMock()
    node.owner_id = owner_id or uuid.uuid4()
    row.node = node
    return row


def make_uow():
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()

    uow.files = AsyncMock()
    uow.files.get_by_id = AsyncMock(return_value=None)
    uow.files.mark_preview_not_required = AsyncMock(
        return_value=MagicMock(preview_storage_key=None)
    )
    uow.files.update_preview = AsyncMock(return_value=None)
    return uow


class _Downloaded:
    def __init__(self, data: bytes):
        self.data = data


def make_ctx(payload=None, *, uow=None):
    ctx = MagicMock()
    ctx.task_id = uuid.uuid4()
    ctx.payload = payload if payload is not None else {}
    ctx.worker_id = "w-001"
    ctx.settings = MagicMock()
    ctx.worker_settings = MagicMock()

    uow = uow or make_uow()
    ctx.uow_factory = MagicMock(return_value=uow)

    storage = MagicMock()
    storage.default_files_bucket = "files"
    storage.build_preview_key = MagicMock(return_value="previews/user/file.webp")
    storage.objects = MagicMock()
    storage.objects.get_object_bytes = AsyncMock(
        return_value=_Downloaded(b"raw-image-bytes")
    )
    storage.objects.put_object = AsyncMock(return_value=MagicMock())
    ctx.storage_service = storage

    return ctx, uow


# ---------------------------------------------------------------------------
# Чистые вспомогательные функции
# ---------------------------------------------------------------------------

class TestMimeHelpers:
    def test_requires_preview_empty(self) -> None:
        assert _mime_requires_preview("") is False

    def test_requires_preview_image_prefix(self) -> None:
        assert _mime_requires_preview("image/png") is True

    def test_requires_preview_text_prefix(self) -> None:
        assert _mime_requires_preview("text/plain") is True

    def test_requires_preview_exact_pdf(self) -> None:
        assert _mime_requires_preview("application/pdf") is True

    def test_requires_preview_exact_json(self) -> None:
        assert _mime_requires_preview("application/json") is True

    def test_requires_preview_unsupported(self) -> None:
        assert _mime_requires_preview("application/zip") is False

    def test_is_image_true(self) -> None:
        assert _mime_is_image("image/jpeg") is True

    def test_is_image_false(self) -> None:
        assert _mime_is_image("text/plain") is False

    def test_is_pdf_true(self) -> None:
        assert _mime_is_pdf("application/pdf") is True

    def test_is_pdf_false(self) -> None:
        assert _mime_is_pdf("image/png") is False


class TestResolveOwnerId:
    def test_returns_owner_id(self) -> None:
        oid = uuid.uuid4()
        row = make_file_row(owner_id=oid)
        assert _resolve_owner_id(row) == oid

    def test_no_node_raises(self) -> None:
        row = MagicMock()
        row.node = None
        with pytest.raises(ValueError):
            _resolve_owner_id(row)

    def test_non_uuid_owner_raises(self) -> None:
        row = MagicMock()
        row.node = MagicMock()
        row.node.owner_id = "not-a-uuid"
        with pytest.raises(ValueError):
            _resolve_owner_id(row)


def _png_bytes(mode: str = "RGB", size=(800, 600)) -> bytes:
    img = Image.new(mode, size)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class TestCompressToWebp:
    def test_rgb_image_compressed_and_resized(self) -> None:
        webp = _compress_to_webp(_png_bytes("RGB", (800, 600)))
        with Image.open(io.BytesIO(webp)) as img:
            assert img.format == "WEBP"
            # Уменьшено до максимум 400 по большей стороне.
            assert max(img.size) <= 400

    def test_rgba_image_preserves_alpha_channel_path(self) -> None:
        webp = _compress_to_webp(_png_bytes("RGBA", (100, 100)))
        with Image.open(io.BytesIO(webp)) as img:
            assert img.format == "WEBP"

    def test_palette_image_converted(self) -> None:
        # Режим "P" задействует ветку convert("RGB") (не RGB и не alpha).
        webp = _compress_to_webp(_png_bytes("P", (50, 50)))
        with Image.open(io.BytesIO(webp)) as img:
            assert img.format == "WEBP"

    def test_invalid_image_raises(self) -> None:
        with pytest.raises(Exception):
            _compress_to_webp(b"not-an-image")


# ---------------------------------------------------------------------------
# Отсутствующий файл / ранние выходы
# ---------------------------------------------------------------------------

class TestEarlyReturns:
    @pytest.mark.asyncio
    async def test_missing_file_returns_failure(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        uow.files.get_by_id = AsyncMock(return_value=None)

        result = await generate_file_preview_handler(ctx)

        assert isinstance(result, WorkerTaskExecutionResult)
        assert result.success is False
        assert result.error_code == "file_not_found"
        assert result.retry is False
        assert result.result_data["file_id"] == str(file_id)

    @pytest.mark.asyncio
    async def test_already_ready_without_force_short_circuits(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(
            file_id=file_id,
            preview_status=FilePreviewStatus.READY,
            preview_storage_key="previews/existing.webp",
        )
        uow.files.get_by_id = AsyncMock(return_value=row)

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert result.result_data["preview_status"] == FilePreviewStatus.READY.value
        assert result.result_data["preview_storage_key"] == "previews/existing.webp"
        # Никаких операций с хранилищем быть не должно.
        ctx.storage_service.objects.get_object_bytes.assert_not_called()
        uow.files.update_preview.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_regenerates_even_if_ready(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id), "force": True})
        row = make_file_row(
            file_id=file_id,
            mime_type="text/plain",
            preview_status=FilePreviewStatus.READY,
        )
        uow.files.get_by_id = AsyncMock(return_value=row)

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        # Force обходит ранний выход по READY и создаёт новое превью.
        ctx.storage_service.objects.put_object.assert_awaited_once()
        uow.files.update_preview.assert_awaited_once()


# ---------------------------------------------------------------------------
# Ветки NOT_REQUIRED / пропуска
# ---------------------------------------------------------------------------

class TestNotRequired:
    @pytest.mark.asyncio
    async def test_unsupported_mime_marked_not_required(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="application/zip")
        uow.files.get_by_id = AsyncMock(return_value=row)
        uow.files.mark_preview_not_required = AsyncMock(
            return_value=MagicMock(preview_storage_key=None)
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert (
            result.result_data["preview_status"]
            == FilePreviewStatus.NOT_REQUIRED.value
        )
        uow.files.mark_preview_not_required.assert_awaited_once()
        uow.commit.assert_awaited_once()
        ctx.storage_service.objects.get_object_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_mime_marked_not_required(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type=None)
        uow.files.get_by_id = AsyncMock(return_value=row)

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert (
            result.result_data["preview_status"]
            == FilePreviewStatus.NOT_REQUIRED.value
        )

    @pytest.mark.asyncio
    async def test_pdf_marked_not_required(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="application/pdf")
        uow.files.get_by_id = AsyncMock(return_value=row)
        uow.files.mark_preview_not_required = AsyncMock(
            return_value=MagicMock(preview_storage_key=None)
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert (
            result.result_data["preview_status"]
            == FilePreviewStatus.NOT_REQUIRED.value
        )
        uow.files.mark_preview_not_required.assert_awaited_once()
        ctx.storage_service.objects.get_object_bytes.assert_not_called()


# ---------------------------------------------------------------------------
# Успешное превью изображения
# ---------------------------------------------------------------------------

class TestImagePreviewSuccess:
    @pytest.mark.asyncio
    async def test_image_preview_generated_and_stored(self, monkeypatch) -> None:
        file_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(
            file_id=file_id, owner_id=owner_id, mime_type="image/png"
        )
        uow.files.get_by_id = AsyncMock(return_value=row)

        monkeypatch.setattr(
            previews, "_compress_to_webp", lambda data: b"webp-bytes"
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert result.progress_percent == 100
        assert result.result_data["preview_status"] == FilePreviewStatus.READY.value
        assert result.result_data["preview_storage_key"] == "previews/user/file.webp"

        ctx.storage_service.build_preview_key.assert_called_once_with(
            user_id=owner_id, file_id=file_id, extension="webp"
        )
        ctx.storage_service.objects.get_object_bytes.assert_awaited_once()
        ctx.storage_service.objects.put_object.assert_awaited_once()
        put_kwargs = ctx.storage_service.objects.put_object.await_args.kwargs
        assert put_kwargs["content_type"] == "image/webp"
        assert put_kwargs["object_key"] == "previews/user/file.webp"
        assert put_kwargs["length"] == len(b"webp-bytes")

        uow.files.update_preview.assert_awaited_once()
        upd_kwargs = uow.files.update_preview.await_args.kwargs
        assert upd_kwargs["preview_status"] == FilePreviewStatus.READY
        assert upd_kwargs["preview_storage_key"] == "previews/user/file.webp"
        uow.commit.assert_awaited()


# ---------------------------------------------------------------------------
# Успешное превью текста / JSON
# ---------------------------------------------------------------------------

class TestTextPreviewSuccess:
    @pytest.mark.asyncio
    async def test_text_preview_generated_and_truncated(self) -> None:
        file_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(
            file_id=file_id, owner_id=owner_id, mime_type="text/plain"
        )
        uow.files.get_by_id = AsyncMock(return_value=row)
        big = b"x" * 10000
        ctx.storage_service.objects.get_object_bytes = AsyncMock(
            return_value=_Downloaded(big)
        )
        ctx.storage_service.build_preview_key = MagicMock(
            return_value="previews/user/file.txt"
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert result.result_data["preview_status"] == FilePreviewStatus.READY.value
        assert result.result_data["preview_storage_key"] == "previews/user/file.txt"

        ctx.storage_service.build_preview_key.assert_called_once_with(
            user_id=owner_id, file_id=file_id, extension="txt"
        )
        put_kwargs = ctx.storage_service.objects.put_object.await_args.kwargs
        # Обрезано до _TEXT_PREVIEW_MAX_BYTES (4096).
        assert put_kwargs["length"] == 4096
        assert put_kwargs["content_type"] == "text/plain; charset=utf-8"
        uow.files.update_preview.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_json_preview_uses_text_branch(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="application/json")
        uow.files.get_by_id = AsyncMock(return_value=row)
        ctx.storage_service.objects.get_object_bytes = AsyncMock(
            return_value=_Downloaded(b'{"a": 1}')
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert result.result_data["preview_status"] == FilePreviewStatus.READY.value
        # extension txt -> текстовая ветка
        assert ctx.storage_service.build_preview_key.call_args.kwargs[
            "extension"
        ] == "txt"


# ---------------------------------------------------------------------------
# Ветки ошибок
# ---------------------------------------------------------------------------

class TestErrorBranches:
    @pytest.mark.asyncio
    async def test_memory_error_marks_not_required_and_fails(
        self, monkeypatch
    ) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="image/png")
        uow.files.get_by_id = AsyncMock(return_value=row)

        def boom(_data):
            raise MemoryError("too big")

        monkeypatch.setattr(previews, "_compress_to_webp", boom)

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.error_code == "image_too_large"
        assert result.retry is False
        # Путь восстановления помечает файл как NOT_REQUIRED.
        uow.files.mark_preview_not_required.assert_awaited()

    @pytest.mark.asyncio
    async def test_memory_error_swallows_recovery_failure(
        self, monkeypatch
    ) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="image/png")
        uow.files.get_by_id = AsyncMock(return_value=row)
        # UoW восстановления тоже падает -> поглощается внутренним try/except.
        uow.files.mark_preview_not_required = AsyncMock(
            side_effect=RuntimeError("recovery failed")
        )

        def boom(_data):
            raise MemoryError("too big")

        monkeypatch.setattr(previews, "_compress_to_webp", boom)

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.error_code == "image_too_large"

    @pytest.mark.asyncio
    async def test_storage_connection_error_retries(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="image/png")
        uow.files.get_by_id = AsyncMock(return_value=row)
        ctx.storage_service.objects.get_object_bytes = AsyncMock(
            side_effect=StorageConnectionError("down")
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.retry is True
        assert result.error_code == "temporary_unavailable"

    @pytest.mark.asyncio
    async def test_database_connection_error_retries(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        uow.files.get_by_id = AsyncMock(
            side_effect=DatabaseConnectionError("db down")
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.retry is True
        assert result.error_code == "temporary_unavailable"

    @pytest.mark.asyncio
    async def test_storage_error_returns_failure(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="text/plain")
        uow.files.get_by_id = AsyncMock(return_value=row)
        ctx.storage_service.objects.put_object = AsyncMock(
            side_effect=StorageError("write failed")
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.retry is False
        assert result.error_code == "storage_error"

    @pytest.mark.asyncio
    async def test_service_error_returns_failure(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="text/plain")
        uow.files.get_by_id = AsyncMock(return_value=row)
        ctx.storage_service.objects.get_object_bytes = AsyncMock(
            side_effect=ServiceError("svc")
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.retry is False
        assert result.error_code == "preview_processing_failed"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_failure(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="text/plain")
        uow.files.get_by_id = AsyncMock(return_value=row)
        ctx.storage_service.objects.get_object_bytes = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.error_code == "unexpected_preview_processing_error"

    @pytest.mark.asyncio
    async def test_missing_file_id_payload_unexpected(self) -> None:
        # Нет file_id в payload -> payload_uuid выбрасывает WorkerTaskHandlerError,
        # которое перехватывается общим обработчиком Exception.
        ctx, uow = make_ctx(payload={})

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.error_code == "unexpected_preview_processing_error"

    @pytest.mark.asyncio
    async def test_resolve_owner_id_failure_is_unexpected(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="image/png")
        row.node = None  # _resolve_owner_id выбросит ValueError
        uow.files.get_by_id = AsyncMock(return_value=row)

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.error_code == "unexpected_preview_processing_error"
