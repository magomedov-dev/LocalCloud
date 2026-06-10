from __future__ import annotations

import asyncio
import io
import os
import subprocess
import tempfile
from typing import Any
from uuid import UUID

import fitz
from PIL import Image

from core.logging import get_logger
from core.preview_mime import (
    PREVIEW_IMAGE_CONTENT_TYPE,
    PREVIEW_TEXT_CONTENT_TYPE,
    is_image,
    is_pdf,
    is_video,
    preview_required,
)
from database.exceptions import DatabaseConnectionError
from database.models.enums import FilePreviewStatus
from services.exceptions import ServiceError
from storage.exceptions import StorageConnectionError, StorageError
from workers.tasks import (
    failure_result,
    optional_payload_value,
    payload_uuid,
    retry_result,
    success_result,
)
from workers.types import WorkerTaskExecutionContext, WorkerTaskExecutionResult

logger = get_logger(__name__)

_TEXT_PREVIEW_MAX_BYTES = 4096
_IMAGE_PREVIEW_QUALITY = 75
_IMAGE_PREVIEW_MAX_DIMENSION = 400

# Защита от чрезмерного потребления памяти и «decompression bomb».
# Превью всё равно ужимается до _IMAGE_PREVIEW_MAX_DIMENSION, поэтому исходные
# файлы, превышающие эти пороги, превью не получают (помечаются NOT_REQUIRED):
# это снимает пик RAM и класс DoS на worker-процессе.
_IMAGE_PREVIEW_MAX_SOURCE_BYTES = 25 * 1024 * 1024  # 25 МБ исходного файла
_PDF_PREVIEW_MAX_SOURCE_BYTES = 50 * 1024 * 1024  # 50 МБ исходного PDF
_VIDEO_PREVIEW_MAX_SOURCE_BYTES = 200 * 1024 * 1024  # 200 МБ исходного видео
_IMAGE_PREVIEW_MAX_PIXELS = 40_000_000  # 40 Мпикс (ширина × высота)

# Параметры рендера превью PDF и видео.
_PDF_RENDER_DPI = 120
_VIDEO_FRAME_TIMESTAMP = "00:00:01"
_VIDEO_FFMPEG_TIMEOUT_SECONDS = 30

# Глобальный предел Pillow на число пикселей растра: декодер сам прерывает
# распаковку изображений-«бомб», не выделяя память под полный растр.
Image.MAX_IMAGE_PIXELS = _IMAGE_PREVIEW_MAX_PIXELS


async def generate_file_preview_handler(
    context: WorkerTaskExecutionContext,
) -> WorkerTaskExecutionResult:
    """Генерирует preview для файла.

    Для изображений создаёт сжатое WebP-превью. Для текстовых файлов и JSON
    создаёт текстовый сниппет ограниченного размера. PDF и неподдерживаемые
    MIME-типы помечаются как `NOT_REQUIRED`. Изображения, превышающие лимит
    размера файла или числа пикселей, превью не получают и также помечаются
    как `NOT_REQUIRED` — это защищает worker от пиков памяти и «decompression
    bomb».

    Args:
        context: Контекст выполнения фоновой задачи.

    Returns:
        Результат выполнения задачи с данными preview или информацией об
        ошибке.
    """

    file_id: Any = None
    try:
        payload = context.payload
        file_id = payload_uuid(payload, "file_id")
        force = bool(
            optional_payload_value(payload, "force", expected_type=bool, default=False)
        )

        # Извлеките файл и сделайте снимок всех необходимых значений, пока сеанс активен.
        # При доступе к атрибутам отсоединенного (после UoW) объекта возникает ошибка
        # DetachedInstanceError, потому что при откате при выходе все данные истекают.
        file_snapshot: dict[str, Any] | None = None
        async with context.uow_factory() as uow:
            file_row = await uow.files.get_by_id(file_id)

            if file_row is None:
                return failure_result(
                    error_message="Файл для генерации preview не найден.",
                    error_code="file_not_found",
                    result_data={
                        "file_id": str(file_id),
                        "preview_status": None,
                        "preview_storage_key": None,
                    },
                    retry=False,
                    progress_percent=0,
                )

            if not force and file_row.preview_status == FilePreviewStatus.READY:
                return success_result(
                    result_data={
                        "file_id": str(file_row.id),
                        "preview_status": file_row.preview_status.value,
                        "preview_storage_key": file_row.preview_storage_key,
                    },
                    progress_percent=100,
                )

            mime_type = (file_row.mime_type or "").strip().lower()

            if not preview_required(mime_type):
                updated = await uow.files.mark_preview_not_required(
                    file_id=file_row.id,
                    flush=True,
                    refresh=True,
                )
                await uow.commit()
                return success_result(
                    result_data={
                        "file_id": str(file_row.id),
                        "preview_status": FilePreviewStatus.NOT_REQUIRED.value,
                        "preview_storage_key": getattr(
                            updated, "preview_storage_key", None
                        ),
                    },
                    progress_percent=100,
                )

            # Слишком большие медиа-файлы превью не получают: их обработка дала бы
            # пик RAM/CPU, способный уронить worker. Размер проверяется до
            # скачивания, поэтому тяжёлый файл вообще не попадает в память.
            source_limit = _media_source_limit(mime_type)
            if source_limit is not None and file_row.size_bytes > source_limit:
                logger.info(
                    "generate_file_preview: файл превышает лимит размера для превью",
                    extra={
                        "file_id": str(file_row.id),
                        "size_bytes": file_row.size_bytes,
                        "max_source_bytes": source_limit,
                        "mime_type": mime_type,
                    },
                )
                updated = await uow.files.mark_preview_not_required(
                    file_id=file_row.id,
                    flush=True,
                    refresh=True,
                )
                await uow.commit()
                return success_result(
                    result_data={
                        "file_id": str(file_row.id),
                        "preview_status": FilePreviewStatus.NOT_REQUIRED.value,
                        "preview_storage_key": getattr(
                            updated, "preview_storage_key", None
                        ),
                    },
                    progress_percent=100,
                )

            # Сделайте снимок всех скаляров, необходимых вне этого UoW.
            file_snapshot = {
                "id": file_row.id,
                "storage_bucket": file_row.storage_bucket,
                "storage_key": file_row.storage_key,
                "owner_id": _resolve_owner_id(file_row),
                "mime_type": mime_type,
            }

        # Операции с хранилищем — активный сеанс не требуется.
        assert file_snapshot is not None
        _file_id: UUID = file_snapshot["id"]
        _owner_id: UUID = file_snapshot["owner_id"]
        _mime: str = file_snapshot["mime_type"]

        if is_image(_mime) or is_pdf(_mime) or is_video(_mime):
            preview_key = context.storage_service.build_preview_key(
                user_id=_owner_id,
                file_id=_file_id,
                extension="webp",
            )
            downloaded = await context.storage_service.objects.get_object_bytes(
                bucket=file_snapshot["storage_bucket"],
                object_key=file_snapshot["storage_key"],
            )
            try:
                if is_image(_mime):
                    raster = downloaded.data
                elif is_pdf(_mime):
                    raster = await asyncio.to_thread(
                        _render_pdf_first_page, downloaded.data
                    )
                else:  # video
                    raster = await asyncio.to_thread(
                        _extract_video_frame, downloaded.data
                    )
                webp_bytes = _compress_to_webp(raster)
            except (MemoryError, Image.DecompressionBombError):
                raise
            except Exception as exc:  # noqa: BLE001 — рендер не удался, превью необязательно
                logger.info(
                    "generate_file_preview: не удалось отрендерить превью",
                    extra={
                        "file_id": str(_file_id),
                        "mime_type": _mime,
                        "reason": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                )
                async with context.uow_factory() as uow:
                    updated = await uow.files.mark_preview_not_required(
                        file_id=_file_id, flush=True, refresh=True
                    )
                    await uow.commit()
                return success_result(
                    result_data={
                        "file_id": str(_file_id),
                        "preview_status": FilePreviewStatus.NOT_REQUIRED.value,
                        "preview_storage_key": getattr(
                            updated, "preview_storage_key", None
                        ),
                    },
                    progress_percent=100,
                )
            await context.storage_service.objects.put_object(
                bucket=context.storage_service.default_files_bucket,
                object_key=preview_key,
                data=io.BytesIO(webp_bytes),
                length=len(webp_bytes),
                content_type=PREVIEW_IMAGE_CONTENT_TYPE,
            )
            async with context.uow_factory() as uow:
                await uow.files.update_preview(
                    file_id=_file_id,
                    preview_status=FilePreviewStatus.READY,
                    preview_storage_key=preview_key,
                    flush=True,
                    refresh=False,
                )
                await uow.commit()
            return success_result(
                result_data={
                    "file_id": str(_file_id),
                    "preview_status": FilePreviewStatus.READY.value,
                    "preview_storage_key": preview_key,
                },
                progress_percent=100,
            )

        # Text / JSON
        preview_key = context.storage_service.build_preview_key(
            user_id=_owner_id,
            file_id=_file_id,
            extension="txt",
        )
        downloaded = await context.storage_service.objects.get_object_bytes(
            bucket=file_snapshot["storage_bucket"],
            object_key=file_snapshot["storage_key"],
        )
        preview_bytes = downloaded.data[:_TEXT_PREVIEW_MAX_BYTES]
        await context.storage_service.objects.put_object(
            bucket=context.storage_service.default_files_bucket,
            object_key=preview_key,
            data=io.BytesIO(preview_bytes),
            length=len(preview_bytes),
            content_type=PREVIEW_TEXT_CONTENT_TYPE,
        )
        async with context.uow_factory() as uow:
            await uow.files.update_preview(
                file_id=_file_id,
                preview_status=FilePreviewStatus.READY,
                preview_storage_key=preview_key,
                flush=True,
                refresh=False,
            )
            await uow.commit()
        return success_result(
            result_data={
                "file_id": str(_file_id),
                "preview_status": FilePreviewStatus.READY.value,
                "preview_storage_key": preview_key,
            },
            progress_percent=100,
        )

    except (MemoryError, Image.DecompressionBombError):
        logger.warning(
            "generate_file_preview: изображение слишком большое для генерации preview",
            extra={"file_id": str(file_id)},
        )
        try:
            async with context.uow_factory() as uow:
                await uow.files.mark_preview_not_required(
                    file_id=file_id, flush=True, refresh=False
                )
                await uow.commit()
        except Exception:
            pass
        return failure_result(
            error_message="Изображение слишком большое для генерации preview.",
            error_code="image_too_large",
            result_data={"file_id": str(file_id)},
            retry=False,
            progress_percent=0,
        )
    except (DatabaseConnectionError, StorageConnectionError) as exc:
        return retry_result(
            error_message="Временная ошибка подключения при генерации preview.",
            error_code="temporary_unavailable",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
        )
    except StorageError as exc:
        return failure_result(
            error_message="Ошибка хранилища при генерации preview файла.",
            error_code="storage_error",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
    except ServiceError as exc:
        return failure_result(
            error_message="Ошибка обработки preview файла.",
            error_code="preview_processing_failed",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
    except Exception as exc:
        logger.exception(
            "generate_file_preview failed", extra={"file_id": str(file_id)}
        )
        return failure_result(
            error_message="Непредвиденная ошибка обработки preview файла.",
            error_code="unexpected_preview_processing_error",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )


def _compress_to_webp(data: bytes) -> bytes:
    """Сжимает изображение в WebP-превью.

    Открывает изображение из байтов, приводит цветовой режим к совместимому с
    WebP, уменьшает изображение до максимального размера preview и возвращает
    сжатые байты.

    Args:
        data: Исходные байты изображения.

    Returns:
        Байты изображения в формате WebP.

    Raises:
        PIL.UnidentifiedImageError: Если входные данные не являются
            поддерживаемым изображением.
        OSError: Если Pillow не смог прочитать или сохранить изображение.
        MemoryError: Если изображение слишком большое для обработки в памяти.
        PIL.Image.DecompressionBombError: Если число пикселей изображения
            превышает ``_IMAGE_PREVIEW_MAX_PIXELS``.
    """

    with Image.open(io.BytesIO(data)) as img:
        # Размер берётся из заголовка (декодирования ещё нет), поэтому проверка
        # отсекает «бомбы» до выделения памяти под полный растр.
        width, height = img.size
        if width * height > _IMAGE_PREVIEW_MAX_PIXELS:
            raise Image.DecompressionBombError(
                f"Изображение {width}x{height} превышает лимит "
                f"{_IMAGE_PREVIEW_MAX_PIXELS} пикселей для генерации preview."
            )

        if img.mode in ("RGBA", "LA", "PA"):
            img = img.convert("RGBA")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail(
            (_IMAGE_PREVIEW_MAX_DIMENSION, _IMAGE_PREVIEW_MAX_DIMENSION),
            Image.Resampling.LANCZOS,
        )

        out = io.BytesIO()
        img.save(out, format="webp", quality=_IMAGE_PREVIEW_QUALITY)
        return out.getvalue()


def _media_source_limit(mime_type: str) -> int | None:
    """Возвращает максимальный размер исходного файла для генерации превью.

    Args:
        mime_type: Нормализованный MIME-тип файла.

    Returns:
        Максимальный размер исходного файла в байтах для изображений, PDF и
        видео; ``None`` для остальных типов (текст усекается при чтении и не
        нуждается в ограничении размера источника).
    """

    if is_image(mime_type):
        return _IMAGE_PREVIEW_MAX_SOURCE_BYTES
    if is_pdf(mime_type):
        return _PDF_PREVIEW_MAX_SOURCE_BYTES
    if is_video(mime_type):
        return _VIDEO_PREVIEW_MAX_SOURCE_BYTES
    return None


def _render_pdf_first_page(data: bytes) -> bytes:
    """Рендерит первую страницу PDF в PNG-растр.

    Args:
        data: Байты PDF-документа.

    Returns:
        PNG-байты первой страницы.

    Raises:
        ValueError: Если документ не содержит страниц.
        Exception: Если PyMuPDF не смог открыть или отрендерить документ.
    """

    with fitz.open(stream=data, filetype="pdf") as doc:
        if doc.page_count < 1:
            raise ValueError("PDF не содержит страниц.")
        page = doc.load_page(0)
        pixmap = page.get_pixmap(dpi=_PDF_RENDER_DPI, alpha=False)
        return pixmap.tobytes("png")


def _extract_video_frame(data: bytes) -> bytes:
    """Извлекает кадр из видео через ffmpeg и возвращает его как PNG.

    Сначала пробует кадр на отметке ``_VIDEO_FRAME_TIMESTAMP``; для очень
    коротких видео откатывается к первому кадру.

    Args:
        data: Байты видеофайла.

    Returns:
        PNG-байты извлечённого кадра.

    Raises:
        RuntimeError: Если ffmpeg не смог извлечь кадр.
    """

    with tempfile.NamedTemporaryFile(suffix=".video", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        for timestamp in (_VIDEO_FRAME_TIMESTAMP, "00:00:00"):
            result = subprocess.run(  # noqa: S603 — фиксированный набор аргументов
                [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-ss",
                    timestamp,
                    "-i",
                    tmp_path,
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=_VIDEO_FFMPEG_TIMEOUT_SECONDS,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        raise RuntimeError(
            "ffmpeg не смог извлечь кадр из видео для генерации превью."
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _resolve_owner_id(file_row: Any) -> UUID:
    """Определяет владельца файла по связанному node.

    Args:
        file_row: Объект файла с загруженной связью `node`.

    Returns:
        UUID владельца файла.

    Raises:
        ValueError: Если у файла нет связанного node или у node отсутствует
            корректный `owner_id`.
    """

    node = getattr(file_row, "node", None)
    owner_id = getattr(node, "owner_id", None)
    if isinstance(owner_id, UUID):
        return owner_id
    raise ValueError(
        "Не удалось определить owner_id для файла при формировании preview key."
    )
