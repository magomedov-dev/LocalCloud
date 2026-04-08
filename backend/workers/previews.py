from __future__ import annotations

import asyncio
import io
import os
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from uuid import UUID

import fitz
from PIL import Image

from core.config import get_settings
from core.constants import PreviewConstants
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


# Значения генерации превью читаются из единой конфигурации (core.config):
# дефолты-литералы лежат в core.constants.PreviewConstants и подобраны под
# маленький хост (1 ГБ ОЗУ), а через .env (см. .env.example, секция «Preview
# generation») их можно переопределить под более мощный сервер.
_preview_settings = get_settings().previews

# Мастер-флаг генерации: при выключении worker помечает файлы NOT_REQUIRED и
# не тратит RAM/CPU на рендеры (для совсем слабых серверов).
_PREVIEW_GENERATION_ENABLED = _preview_settings.generation_enabled

_TEXT_PREVIEW_MAX_BYTES = PreviewConstants.TEXT_PREVIEW_MAX_BYTES
_IMAGE_PREVIEW_QUALITY = _preview_settings.image_quality
_IMAGE_PREVIEW_MAX_DIMENSION = _preview_settings.image_max_dimension
_DOWNLOAD_CHUNK_BYTES = PreviewConstants.DOWNLOAD_CHUNK_BYTES

# Защита от чрезмерного потребления памяти и «decompression bomb». Источники
# крупнее порога превью не получают (помечаются NOT_REQUIRED): это снимает пик
# RAM/CPU и класс DoS на worker'е.
_IMAGE_PREVIEW_MAX_SOURCE_BYTES = _preview_settings.image_max_source_bytes
_PDF_PREVIEW_MAX_SOURCE_BYTES = _preview_settings.pdf_max_source_bytes
_VIDEO_PREVIEW_MAX_SOURCE_BYTES = _preview_settings.video_max_source_bytes
_IMAGE_PREVIEW_MAX_PIXELS = _preview_settings.image_max_pixels  # ширина × высота

# Параметры рендера превью PDF и видео.
_PDF_RENDER_DPI = _preview_settings.pdf_render_dpi
_PDF_RENDER_MAX_DIM = _preview_settings.pdf_render_max_dim  # потолок длинной стороны
_VIDEO_FRAME_TIMESTAMP = PreviewConstants.VIDEO_FRAME_TIMESTAMP
_VIDEO_FFMPEG_TIMEOUT_SECONDS = _preview_settings.video_ffmpeg_timeout_seconds

# Параллелизм тяжёлых рендеров. Декод PDF/видео/картинок память- и CPU-затратен,
# поэтому ограничиваем число одновременных рендеров отдельно от общего числа
# worker-задач — иначе «два тяжёлых рендера сразу» приводят к OOM. По умолчанию
# 1: на 1 ядре параллельные рендеры всё равно бессмысленны.
_RENDER_MAX_CONCURRENCY = _preview_settings.render_concurrency
_render_semaphore = asyncio.Semaphore(_RENDER_MAX_CONCURRENCY)
# Выделенный пул потоков под рендеры, чтобы они не конкурировали с дефолтным
# пулом asyncio (storage I/O и пр.) за потоки на единственном ядре. Создаётся
# лениво и пересоздаётся после shutdown — чтобы остановка пула на завершении
# worker'а не делала модуль непригодным навсегда.
_render_executor: ThreadPoolExecutor | None = None
_render_executor_lock = threading.Lock()

# Глобальный предел Pillow на число пикселей растра: декодер сам прерывает
# распаковку изображений-«бомб», не выделяя память под полный растр.
Image.MAX_IMAGE_PIXELS = _IMAGE_PREVIEW_MAX_PIXELS


def _get_render_executor() -> ThreadPoolExecutor:
    """Возвращает пул потоков рендеров, создавая его при необходимости."""

    global _render_executor
    if _render_executor is None:
        with _render_executor_lock:
            if _render_executor is None:
                _render_executor = ThreadPoolExecutor(
                    max_workers=_RENDER_MAX_CONCURRENCY,
                    thread_name_prefix="preview-render",
                )
    return _render_executor


async def _run_render(func: Callable[..., bytes], *args: Any) -> bytes:
    """Запускает блокирующий рендер в выделенном пуле потоков рендеров."""

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_render_executor(), func, *args)


def shutdown_render_executor(*, wait: bool = True) -> None:
    """Останавливает пул потоков рендеров превью.

    Вызывается при штатном завершении worker-процесса, чтобы потоки рендеров
    не оставались висеть (удерживая файловые дескрипторы временных файлов) и
    процесс мог чисто завершиться. Пул сбрасывается в ``None`` и будет создан
    заново при следующем рендере.

    Args:
        wait: Дождаться ли завершения уже выполняющихся рендеров.
    """

    global _render_executor
    executor = _render_executor
    _render_executor = None
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=True)


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

            # Мастер-флаг отключён: на слабом хосте превью не генерируем вовсе —
            # помечаем NOT_REQUIRED, не тратя RAM/CPU на скачивание и рендер.
            if not _PREVIEW_GENERATION_ENABLED:
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
            tmp_path: str | None = None
            try:
                # Потоково скачиваем источник во временный файл — без загрузки
                # целиком в RAM (раньше 200 МБ видео висели в памяти).
                fd, tmp_path = tempfile.mkstemp(suffix=".preview-src")
                os.close(fd)
                await context.storage_service.objects.download_object_to_file(
                    bucket=file_snapshot["storage_bucket"],
                    object_key=file_snapshot["storage_key"],
                    file_path=tmp_path,
                    chunk_size=_DOWNLOAD_CHUNK_BYTES,
                )
                # Рендер — под семафором (не более N одновременно) на выделенном
                # пуле потоков: исключает «два тяжёлых рендера = OOM».
                async with _render_semaphore:
                    if is_image(_mime):
                        webp_bytes = await _run_render(
                            _image_to_webp_from_path, tmp_path
                        )
                    elif is_pdf(_mime):
                        webp_bytes = await _run_render(
                            _pdf_to_webp_from_path, tmp_path
                        )
                    else:  # video
                        webp_bytes = await _run_render(
                            _video_to_webp_from_path, tmp_path
                        )
            except (MemoryError, Image.DecompressionBombError):
                raise
            except (
                DatabaseConnectionError,
                StorageConnectionError,
                StorageError,
                ServiceError,
            ):
                # Инфраструктурные ошибки (например, обрыв связи при скачивании
                # источника) обрабатывает внешний handler: временные → retry,
                # storage/service → failure. Их нельзя глушить как «нет превью».
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
            finally:
                if tmp_path is not None:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
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
        # Читаем только первые N байт диапазоном — не загружаем весь файл в RAM.
        preview_bytes = await context.storage_service.objects.get_object_range_bytes(
            bucket=file_snapshot["storage_bucket"],
            object_key=file_snapshot["storage_key"],
            offset=0,
            length=_TEXT_PREVIEW_MAX_BYTES,
        )
        preview_bytes = preview_bytes[:_TEXT_PREVIEW_MAX_BYTES]
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


async def finalize_failed_preview_task(
    *,
    uow_factory: Any,
    payload: Mapping[str, Any],
) -> bool:
    """Помечает превью файла FAILED после финального провала задачи генерации.

    Вызывается диспетчером, когда задача ``GENERATE_FILE_PREVIEW`` исчерпала
    попытки или завершилась невосстановимой ошибкой, не успев обновить статус
    файла. Без этого файл навсегда остаётся в ``PENDING``/``GENERATING``, и
    клиенты бесконечно опрашивают его миниатюру. Терминальные статусы
    (``READY``, ``NOT_REQUIRED``), выставленные ветками самого обработчика,
    не перезаписываются.

    Метод best-effort: любые ошибки логируются и не пробрасываются — доводка
    статуса не должна влиять на обработку остальных задач.

    Args:
        uow_factory: Фабрика UnitOfWork.
        payload: Payload провалившейся задачи (ожидается поле ``file_id``).

    Returns:
        ``True``, если статус файла переведён в ``FAILED``, иначе ``False``.
    """

    raw_file_id = payload.get("file_id")
    try:
        file_id = raw_file_id if isinstance(raw_file_id, UUID) else UUID(str(raw_file_id))
    except (TypeError, ValueError):
        logger.warning(
            "finalize_failed_preview_task: некорректный file_id в payload",
            extra={"file_id": repr(raw_file_id)},
        )
        return False

    try:
        async with uow_factory() as uow:
            file_row = await uow.files.get_by_id(file_id)
            if file_row is None:
                return False
            if file_row.preview_status not in (
                FilePreviewStatus.PENDING,
                FilePreviewStatus.GENERATING,
            ):
                return False
            await uow.files.mark_preview_failed(
                file_id=file_id,
                flush=True,
                refresh=False,
            )
            await uow.commit()
    except Exception:
        logger.exception(
            "finalize_failed_preview_task: не удалось пометить превью FAILED",
            extra={"file_id": str(file_id)},
        )
        return False

    logger.info(
        "finalize_failed_preview_task: превью помечено FAILED после провала задачи",
        extra={"file_id": str(file_id)},
    )
    return True


def _image_to_webp(img: Image.Image) -> bytes:
    """Приводит открытое изображение к WebP-превью фиксированного размера.

    Args:
        img: Открытое (ещё не декодированное) изображение Pillow.

    Returns:
        Байты изображения в формате WebP.

    Raises:
        PIL.Image.DecompressionBombError: Если число пикселей изображения
            превышает ``_IMAGE_PREVIEW_MAX_PIXELS``.
        OSError: Если Pillow не смог обработать или сохранить изображение.
    """

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


def _compress_to_webp(data: bytes) -> bytes:
    """Сжимает изображение из байтов в WebP-превью.

    Используется для небольших промежуточных растров (PNG первой страницы PDF
    или кадра видео); сам исходник медиа в память целиком не грузится.

    Args:
        data: Исходные байты изображения.

    Returns:
        Байты изображения в формате WebP.
    """

    with Image.open(io.BytesIO(data)) as img:
        return _image_to_webp(img)


def _image_to_webp_from_path(path: str) -> bytes:
    """Создаёт WebP-превью изображения, открывая его с диска (ленивый декод).

    Args:
        path: Путь к исходному файлу изображения.

    Returns:
        Байты изображения в формате WebP.
    """

    with Image.open(path) as img:
        return _image_to_webp(img)


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


def _pdf_to_webp_from_path(path: str) -> bytes:
    """Рендерит первую страницу PDF в WebP-превью, открывая файл с диска.

    ``fitz.open(path)`` использует memory-mapping и не держит весь PDF в RAM.
    Масштаб рендера ограничен ``_PDF_RENDER_MAX_DIM`` по длинной стороне, чтобы
    растр огромной страницы не выел память.

    Args:
        path: Путь к исходному PDF-файлу.

    Returns:
        Байты WebP-превью первой страницы.

    Raises:
        ValueError: Если документ не содержит страниц.
        Exception: Если PyMuPDF не смог открыть или отрендерить документ.
    """

    with fitz.open(path, filetype="pdf") as doc:
        if doc.page_count < 1:
            raise ValueError("PDF не содержит страниц.")
        page = doc.load_page(0)
        scale = _PDF_RENDER_DPI / 72.0
        longest = max(page.rect.width, page.rect.height) * scale
        if longest > _PDF_RENDER_MAX_DIM:
            scale *= _PDF_RENDER_MAX_DIM / longest
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        png_bytes = pixmap.tobytes("png")
    return _compress_to_webp(png_bytes)


def _extract_video_frame_from_file(path: str) -> bytes:
    """Извлекает кадр из видеофайла через ffmpeg и возвращает PNG.

    Использует input-seek (``-ss`` до ``-i``) и ``-threads 1``: декодируется лишь
    кадр около отметки, без полного декода и многопоточных буферов — память не
    зависит от длины видео. Файл уже на диске (не держится в RAM).

    Args:
        path: Путь к исходному видеофайлу.

    Returns:
        PNG-байты извлечённого кадра.

    Raises:
        RuntimeError: Если ffmpeg не смог извлечь кадр.
    """

    for timestamp in (_VIDEO_FRAME_TIMESTAMP, "00:00:00"):
        result = subprocess.run(  # noqa: S603 — фиксированный набор аргументов
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-threads",
                "1",
                "-ss",
                timestamp,
                "-i",
                path,
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
    raise RuntimeError("ffmpeg не смог извлечь кадр из видео для генерации превью.")


def _video_to_webp_from_path(path: str) -> bytes:
    """Создаёт WebP-превью видео: извлекает кадр ffmpeg'ом и сжимает его.

    Args:
        path: Путь к исходному видеофайлу.

    Returns:
        Байты WebP-превью кадра.
    """

    png_bytes = _extract_video_frame_from_file(path)
    return _compress_to_webp(png_bytes)


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
