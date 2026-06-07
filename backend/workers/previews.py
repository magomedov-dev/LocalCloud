from __future__ import annotations

import io
from typing import Any
from uuid import UUID

from PIL import Image

from core.logging import get_logger
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

_PREVIEW_SUPPORTED_MIME_PREFIXES: tuple[str, ...] = (
    "image/",
    "text/",
)
_PREVIEW_SUPPORTED_MIME_TYPES: tuple[str, ...] = (
    "application/pdf",
    "application/json",
)

_TEXT_MIME_PREFIXES: tuple[str, ...] = ("text/",)
_TEXT_MIME_TYPES: tuple[str, ...] = ("application/json",)


async def generate_file_preview_handler(
    context: WorkerTaskExecutionContext,
) -> WorkerTaskExecutionResult:
    """Генерирует preview для файла.

    Для изображений создаёт сжатое WebP-превью. Для текстовых файлов и JSON
    создаёт текстовый сниппет ограниченного размера. PDF и неподдерживаемые
    MIME-типы помечаются как `NOT_REQUIRED`.

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

            if not _mime_requires_preview(mime_type):
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

            if _mime_is_pdf(mime_type):
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

        if _mime_is_image(_mime):
            preview_key = context.storage_service.build_preview_key(
                user_id=_owner_id,
                file_id=_file_id,
                extension="webp",
            )
            downloaded = await context.storage_service.objects.get_object_bytes(
                bucket=file_snapshot["storage_bucket"],
                object_key=file_snapshot["storage_key"],
            )
            webp_bytes = _compress_to_webp(downloaded.data)
            await context.storage_service.objects.put_object(
                bucket=context.storage_service.default_files_bucket,
                object_key=preview_key,
                data=io.BytesIO(webp_bytes),
                length=len(webp_bytes),
                content_type="image/webp",
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
            content_type="text/plain; charset=utf-8",
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

    except MemoryError:
        logger.warning(
            "generate_file_preview: image too large for in-memory compression",
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
    """

    with Image.open(io.BytesIO(data)) as img:
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


def _mime_requires_preview(mime_type: str) -> bool:
    """Проверяет, требуется ли preview для MIME-типа.

    Args:
        mime_type: Нормализованный MIME-тип файла.

    Returns:
        `True`, если MIME-тип поддерживает preview, иначе `False`.
    """

    if not mime_type:
        return False
    if mime_type in _PREVIEW_SUPPORTED_MIME_TYPES:
        return True
    return any(
        mime_type.startswith(prefix) for prefix in _PREVIEW_SUPPORTED_MIME_PREFIXES
    )


def _mime_is_image(mime_type: str) -> bool:
    """Проверяет, является ли MIME-тип изображением.

    Args:
        mime_type: Нормализованный MIME-тип файла.

    Returns:
        `True`, если MIME-тип относится к изображениям, иначе `False`.
    """

    return mime_type.startswith("image/")


def _mime_is_pdf(mime_type: str) -> bool:
    """Проверяет, является ли MIME-тип PDF-документом.

    Args:
        mime_type: Нормализованный MIME-тип файла.

    Returns:
        `True`, если MIME-тип равен `application/pdf`, иначе `False`.
    """

    return mime_type == "application/pdf"


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
