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
    _extract_video_frame_from_file,
    _media_source_limit,
    _pdf_to_webp_from_path,
    _resolve_owner_id,
    generate_file_preview_handler,
)
from workers.types import WorkerTaskExecutionResult


# ---------------------------------------------------------------------------
# Вспомогательные функции / фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _force_preview_generation_enabled(monkeypatch):
    """Форсирует включённую генерацию превью независимо от локального .env.

    ``workers.previews`` читает мастер-флаг на импорте модуля, поэтому без этого
    тесты подхватывали бы PREVIEW_GENERATION_ENABLED разработчика (например,
    false на слабом хосте) и падали бы вхолостую. Тест выключенной генерации
    переопределяет флаг у себя.
    """

    monkeypatch.setattr(previews, "_PREVIEW_GENERATION_ENABLED", True)


def make_file_row(
    *,
    file_id=None,
    owner_id=None,
    mime_type="image/png",
    preview_status=FilePreviewStatus.PENDING,
    preview_storage_key=None,
    bucket="files",
    key="objects/key",
    size_bytes=1024,
):
    row = MagicMock()
    row.id = file_id or uuid.uuid4()
    row.mime_type = mime_type
    row.preview_status = preview_status
    row.preview_storage_key = preview_storage_key
    row.storage_bucket = bucket
    row.storage_key = key
    row.size_bytes = size_bytes
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
    # Медиа теперь скачивается потоково во временный файл, а не в память.
    storage.objects.download_object_to_file = AsyncMock(return_value=1024)
    # Текстовое превью читает только первые N байт диапазоном.
    storage.objects.get_object_range_bytes = AsyncMock(return_value=b"text-bytes")
    storage.objects.get_object_bytes = AsyncMock(
        return_value=_Downloaded(b"raw-image-bytes")
    )
    storage.objects.put_object = AsyncMock(return_value=MagicMock())
    ctx.storage_service = storage

    return ctx, uow


# ---------------------------------------------------------------------------
# Чистые вспомогательные функции
# ---------------------------------------------------------------------------

class TestMediaSourceLimit:
    def test_image_limit(self) -> None:
        assert (
            _media_source_limit("image/png")
            == previews._IMAGE_PREVIEW_MAX_SOURCE_BYTES
        )

    def test_pdf_limit(self) -> None:
        assert (
            _media_source_limit("application/pdf")
            == previews._PDF_PREVIEW_MAX_SOURCE_BYTES
        )

    def test_video_limit(self) -> None:
        assert (
            _media_source_limit("video/mp4")
            == previews._VIDEO_PREVIEW_MAX_SOURCE_BYTES
        )

    def test_text_has_no_limit(self) -> None:
        assert _media_source_limit("text/plain") is None


class TestRenderHelpers:
    def test_pdf_to_webp_from_path_returns_webp(self, tmp_path) -> None:
        import fitz

        doc = fitz.open()
        doc.new_page(width=200, height=200)
        pdf_file = tmp_path / "doc.pdf"
        doc.save(str(pdf_file))
        doc.close()

        webp = _pdf_to_webp_from_path(str(pdf_file))
        with Image.open(io.BytesIO(webp)) as img:
            assert img.format == "WEBP"

    def test_pdf_to_webp_invalid_raises(self, tmp_path) -> None:
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"not-a-pdf")
        with pytest.raises(Exception):
            _pdf_to_webp_from_path(str(bad))

    def test_extract_video_frame_returns_ffmpeg_stdout(self, monkeypatch) -> None:
        def fake_run(args, **kwargs):
            return MagicMock(returncode=0, stdout=b"frame-png", stderr=b"")

        monkeypatch.setattr(previews.subprocess, "run", fake_run)
        assert _extract_video_frame_from_file("/tmp/x.video") == b"frame-png"

    def test_extract_video_frame_uses_single_thread(self, monkeypatch) -> None:
        captured: dict[str, list] = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            return MagicMock(returncode=0, stdout=b"frame-png", stderr=b"")

        monkeypatch.setattr(previews.subprocess, "run", fake_run)
        _extract_video_frame_from_file("/tmp/x.video")
        # ffmpeg вызывается с ограничением потоков (память/CPU).
        assert "-threads" in captured["args"]
        assert captured["args"][captured["args"].index("-threads") + 1] == "1"

    def test_extract_video_frame_failure_raises(self, monkeypatch) -> None:
        def fake_run(args, **kwargs):
            return MagicMock(returncode=1, stdout=b"", stderr=b"boom")

        monkeypatch.setattr(previews.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError):
            _extract_video_frame_from_file("/tmp/x.video")


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
    def test_rgb_image_compressed_and_resized(self, monkeypatch) -> None:
        # Лимит фиксируется явно: модульная константа читается из настроек и
        # может быть переопределена локальным .env разработчика.
        monkeypatch.setattr(previews, "_IMAGE_PREVIEW_MAX_DIMENSION", 400)
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

    def test_too_many_pixels_raises_bomb_error(self, monkeypatch) -> None:
        # Число пикселей сверх лимита отклоняется ДО декодирования растра.
        monkeypatch.setattr(previews, "_IMAGE_PREVIEW_MAX_PIXELS", 100)
        with pytest.raises(Image.DecompressionBombError):
            _compress_to_webp(_png_bytes("RGB", (100, 100)))


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
    async def test_generation_disabled_marks_not_required(self, monkeypatch) -> None:
        # При выключенном мастер-флаге даже поддерживаемый тип (image) не
        # генерирует превью: файл помечается NOT_REQUIRED без скачивания.
        monkeypatch.setattr(previews, "_PREVIEW_GENERATION_ENABLED", False)
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="image/png")
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
        ctx.storage_service.objects.download_object_to_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_oversized_pdf_skipped(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(
            file_id=file_id,
            mime_type="application/pdf",
            size_bytes=previews._PDF_PREVIEW_MAX_SOURCE_BYTES + 1,
        )
        uow.files.get_by_id = AsyncMock(return_value=row)

        result = await generate_file_preview_handler(ctx)

        assert (
            result.result_data["preview_status"]
            == FilePreviewStatus.NOT_REQUIRED.value
        )
        ctx.storage_service.objects.download_object_to_file.assert_not_awaited()


# ---------------------------------------------------------------------------
# Превью PDF и видео
# ---------------------------------------------------------------------------

class TestPdfVideoPreview:
    @pytest.mark.asyncio
    async def test_pdf_preview_generated_as_webp(self, monkeypatch) -> None:
        file_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(
            file_id=file_id, owner_id=owner_id, mime_type="application/pdf"
        )
        uow.files.get_by_id = AsyncMock(return_value=row)
        monkeypatch.setattr(previews, "_pdf_to_webp_from_path", lambda path: b"webp")

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert result.result_data["preview_status"] == FilePreviewStatus.READY.value
        ctx.storage_service.build_preview_key.assert_called_once_with(
            user_id=owner_id, file_id=file_id, extension="webp"
        )
        # Источник скачивается потоково во временный файл.
        ctx.storage_service.objects.download_object_to_file.assert_awaited_once()
        put_kwargs = ctx.storage_service.objects.put_object.await_args.kwargs
        assert put_kwargs["content_type"] == "image/webp"
        uow.files.update_preview.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_video_preview_generated_as_webp(self, monkeypatch) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="video/mp4")
        uow.files.get_by_id = AsyncMock(return_value=row)
        monkeypatch.setattr(
            previews, "_video_to_webp_from_path", lambda path: b"webp"
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert result.result_data["preview_status"] == FilePreviewStatus.READY.value
        ctx.storage_service.objects.download_object_to_file.assert_awaited_once()
        put_kwargs = ctx.storage_service.objects.put_object.await_args.kwargs
        assert put_kwargs["content_type"] == "image/webp"

    @pytest.mark.asyncio
    async def test_render_failure_marks_not_required(self, monkeypatch) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="application/pdf")
        uow.files.get_by_id = AsyncMock(return_value=row)

        def boom(_path):
            raise RuntimeError("corrupt pdf")

        monkeypatch.setattr(previews, "_pdf_to_webp_from_path", boom)

        result = await generate_file_preview_handler(ctx)

        # Сбой рендера не валит задачу: превью просто помечается NOT_REQUIRED.
        assert result.success is True
        assert (
            result.result_data["preview_status"]
            == FilePreviewStatus.NOT_REQUIRED.value
        )
        uow.files.mark_preview_not_required.assert_awaited()
        ctx.storage_service.objects.put_object.assert_not_awaited()


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
            previews, "_image_to_webp_from_path", lambda path: b"webp-bytes"
        )

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert result.progress_percent == 100
        assert result.result_data["preview_status"] == FilePreviewStatus.READY.value
        assert result.result_data["preview_storage_key"] == "previews/user/file.webp"

        ctx.storage_service.build_preview_key.assert_called_once_with(
            user_id=owner_id, file_id=file_id, extension="webp"
        )
        ctx.storage_service.objects.download_object_to_file.assert_awaited_once()
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

    @pytest.mark.asyncio
    async def test_oversized_image_skipped_without_download(self) -> None:
        # Изображение сверх лимита размера помечается NOT_REQUIRED, и тяжёлый
        # файл вообще не скачивается в память.
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(
            file_id=file_id,
            mime_type="image/png",
            size_bytes=previews._IMAGE_PREVIEW_MAX_SOURCE_BYTES + 1,
        )
        uow.files.get_by_id = AsyncMock(return_value=row)

        result = await generate_file_preview_handler(ctx)

        assert result.success is True
        assert (
            result.result_data["preview_status"]
            == FilePreviewStatus.NOT_REQUIRED.value
        )
        ctx.storage_service.objects.download_object_to_file.assert_not_awaited()
        ctx.storage_service.objects.put_object.assert_not_awaited()
        uow.files.mark_preview_not_required.assert_awaited()
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
        # Диапазонное чтение возвращает уже не больше N байт.
        ctx.storage_service.objects.get_object_range_bytes = AsyncMock(
            return_value=b"x" * 4096
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
        # Прочитан только диапазон первых байт, а не весь файл.
        range_kwargs = (
            ctx.storage_service.objects.get_object_range_bytes.await_args.kwargs
        )
        assert range_kwargs["length"] == 4096
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
        ctx.storage_service.objects.get_object_range_bytes = AsyncMock(
            return_value=b'{"a": 1}'
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

        monkeypatch.setattr(previews, "_image_to_webp_from_path", boom)

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

        monkeypatch.setattr(previews, "_image_to_webp_from_path", boom)

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.error_code == "image_too_large"

    @pytest.mark.asyncio
    async def test_decompression_bomb_marks_not_required_and_fails(
        self, monkeypatch
    ) -> None:
        # «Бомба» обрабатывается тем же путём, что и MemoryError.
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="image/png")
        uow.files.get_by_id = AsyncMock(return_value=row)

        def bomb(_data):
            raise Image.DecompressionBombError("too many pixels")

        monkeypatch.setattr(previews, "_image_to_webp_from_path", bomb)

        result = await generate_file_preview_handler(ctx)

        assert result.success is False
        assert result.error_code == "image_too_large"
        assert result.retry is False
        uow.files.mark_preview_not_required.assert_awaited()

    @pytest.mark.asyncio
    async def test_storage_connection_error_retries(self) -> None:
        file_id = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(file_id)})
        row = make_file_row(file_id=file_id, mime_type="image/png")
        uow.files.get_by_id = AsyncMock(return_value=row)
        ctx.storage_service.objects.download_object_to_file = AsyncMock(
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
        ctx.storage_service.objects.get_object_range_bytes = AsyncMock(
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
        ctx.storage_service.objects.get_object_range_bytes = AsyncMock(
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


# ---------------------------------------------------------------------------
# finalize_failed_preview_task — доводка статуса после финального провала
# ---------------------------------------------------------------------------

class TestFinalizeFailedPreviewTask:
    @pytest.mark.asyncio
    async def test_marks_pending_file_as_failed(self) -> None:
        """Файл в PENDING помечается FAILED после финального провала задачи."""
        file_row = make_file_row(preview_status=FilePreviewStatus.PENDING)
        uow = make_uow()
        uow.files.get_by_id = AsyncMock(return_value=file_row)
        uow.files.mark_preview_failed = AsyncMock(return_value=file_row)

        result = await previews.finalize_failed_preview_task(
            uow_factory=MagicMock(return_value=uow),
            payload={"file_id": str(file_row.id)},
        )

        assert result is True
        uow.files.mark_preview_failed.assert_awaited_once()
        uow.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_marks_generating_file_as_failed(self) -> None:
        """Файл, зависший в GENERATING, тоже помечается FAILED."""
        file_row = make_file_row(preview_status=FilePreviewStatus.GENERATING)
        uow = make_uow()
        uow.files.get_by_id = AsyncMock(return_value=file_row)
        uow.files.mark_preview_failed = AsyncMock(return_value=file_row)

        result = await previews.finalize_failed_preview_task(
            uow_factory=MagicMock(return_value=uow),
            payload={"file_id": file_row.id},
        )

        assert result is True
        uow.files.mark_preview_failed.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [
            FilePreviewStatus.READY,
            FilePreviewStatus.NOT_REQUIRED,
            FilePreviewStatus.FAILED,
        ],
    )
    async def test_terminal_statuses_not_overwritten(self, status) -> None:
        """Терминальные статусы (READY/NOT_REQUIRED/FAILED) не перезаписываются."""
        file_row = make_file_row(preview_status=status)
        uow = make_uow()
        uow.files.get_by_id = AsyncMock(return_value=file_row)
        uow.files.mark_preview_failed = AsyncMock()

        result = await previews.finalize_failed_preview_task(
            uow_factory=MagicMock(return_value=uow),
            payload={"file_id": str(file_row.id)},
        )

        assert result is False
        uow.files.mark_preview_failed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_file_returns_false(self) -> None:
        """Отсутствующий файл — False без ошибок."""
        uow = make_uow()
        uow.files.get_by_id = AsyncMock(return_value=None)

        result = await previews.finalize_failed_preview_task(
            uow_factory=MagicMock(return_value=uow),
            payload={"file_id": str(uuid.uuid4())},
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_invalid_payload_returns_false(self) -> None:
        """Некорректный file_id в payload — False без обращения к БД."""
        factory = MagicMock()

        result = await previews.finalize_failed_preview_task(
            uow_factory=factory,
            payload={"file_id": "not-a-uuid"},
        )

        assert result is False
        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_database_error_swallowed(self) -> None:
        """Ошибка БД глотается (best-effort), результат False."""
        uow = make_uow()
        uow.files.get_by_id = AsyncMock(side_effect=DatabaseConnectionError("db down"))

        result = await previews.finalize_failed_preview_task(
            uow_factory=MagicMock(return_value=uow),
            payload={"file_id": str(uuid.uuid4())},
        )

        assert result is False
