from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from database.exceptions import DatabaseConnectionError
from database.models.enums import NodeType
from schemas.trash import TrashCleanupRequest
from services.exceptions import ServiceError
from storage.exceptions import StorageConnectionError, StorageError
from workers.tasks import (
    failure_result,
    optional_payload_value,
    payload_datetime,
    payload_int,
    retry_result,
    success_result,
)
from workers.types import WorkerTaskExecutionContext, WorkerTaskExecutionResult


async def clean_trash_handler(
    context: WorkerTaskExecutionContext,
) -> WorkerTaskExecutionResult:
    """Очищает корзину и связанные объекты хранения.

    Использует сервисный метод `trash.cleanup_expired`, если он доступен.
    Если сервис не предоставляет этот метод, выполняет fallback-очистку:
    находит просроченные элементы корзины, удаляет связанные storage-объекты
    файлов и помечает элементы как окончательно удалённые.

    Args:
        context: Контекст выполнения фоновой задачи.

    Returns:
        Результат выполнения задачи со статистикой очистки или информацией об
        ошибке.
    """

    try:
        payload = context.payload
        owner_id = _optional_payload_uuid(payload, "owner_id")
        deleted_before = (
            payload_datetime(payload, "deleted_before")
            if payload.get("deleted_before") is not None
            else None
        )
        limit = payload_int(payload, "limit", default=100, min_value=1, max_value=5000)
        if limit is None:
            limit = 100

        trash_service = context.services.trash
        if hasattr(trash_service, "cleanup_expired"):
            request = TrashCleanupRequest(
                owner_id=owner_id,
                older_than=deleted_before,
                expired_before=None,
                limit=limit,
                dry_run=False,
            )
            response = await trash_service.cleanup_expired(request, actor_id=None)
            result_data = {
                "scanned_count": int(response.requested_count),
                "purged_count": int(response.purged_count),
                # Точное число удалённых storage-объектов сервис не возвращает.
                "deleted_storage_objects_count": int(response.purged_count),
                "failed_count": int(response.failed_count),
            }
            return success_result(result_data=result_data, progress_percent=100)

        fallback_result = await _fallback_cleanup(
            context=context,
            owner_id=owner_id,
            deleted_before=deleted_before,
            limit=limit,
        )
        return success_result(result_data=fallback_result, progress_percent=100)

    except (StorageConnectionError, DatabaseConnectionError) as exc:
        return retry_result(
            error_message="Временная ошибка подключения при очистке корзины.",
            error_code="temporary_unavailable",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
        )
    except (ServiceError, StorageError) as exc:
        return failure_result(
            error_message="Ошибка очистки корзины.",
            error_code="cleanup_failed",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
    except Exception as exc:
        return failure_result(
            error_message="Непредвиденная ошибка очистки корзины.",
            error_code="unexpected_cleanup_error",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )


async def delete_object_from_storage_handler(
    context: WorkerTaskExecutionContext,
) -> WorkerTaskExecutionResult:
    """Удаляет один объект из MinIO/S3.

    Извлекает из payload поля `bucket`, `object_key` и опциональный флаг
    `missing_ok`, валидирует обязательные значения и удаляет объект через
    storage-сервис.

    Args:
        context: Контекст выполнения фоновой задачи.

    Returns:
        Результат выполнения задачи со статистикой удаления или информацией об
        ошибке.
    """

    try:
        payload = context.payload
        bucket_raw = optional_payload_value(
            payload, "bucket", expected_type=str, default=""
        )
        object_key_raw = optional_payload_value(
            payload,
            "object_key",
            expected_type=str,
            default="",
        )
        missing_ok = bool(optional_payload_value(payload, "missing_ok", default=True))

        bucket = str(bucket_raw).strip()
        object_key = str(object_key_raw).strip()
        if not bucket:
            return failure_result(
                error_message="Не указан bucket для удаления объекта.",
                error_code="invalid_bucket",
                result_data={"bucket": bucket_raw},
            )
        if not object_key:
            return failure_result(
                error_message="Не указан object_key для удаления объекта.",
                error_code="invalid_object_key",
                result_data={"object_key": object_key_raw},
            )

        await context.storage_service.delete_file_object(
            bucket=bucket,
            object_key=object_key,
            missing_ok=missing_ok,
        )
        return success_result(
            result_data={
                "scanned_count": 1,
                "purged_count": 0,
                "deleted_storage_objects_count": 1,
                "failed_count": 0,
            },
            progress_percent=100,
        )

    except (StorageConnectionError, DatabaseConnectionError) as exc:
        return retry_result(
            error_message="Временная ошибка подключения при удалении объекта из storage.",
            error_code="temporary_unavailable",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
        )
    except (ServiceError, StorageError) as exc:
        return failure_result(
            error_message="Ошибка удаления объекта из storage.",
            error_code="storage_delete_failed",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
    except Exception as exc:
        return failure_result(
            error_message="Непредвиденная ошибка удаления объекта из storage.",
            error_code="unexpected_storage_delete_error",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )


async def _fallback_cleanup(
    *,
    context: WorkerTaskExecutionContext,
    owner_id: UUID | None,
    deleted_before: datetime | None,
    limit: int,
) -> dict[str, int]:
    """Выполняет fallback-очистку корзины без сервисного метода.

    Получает просроченные элементы корзины напрямую через unit of work,
    дополнительно фильтрует их по `deleted_before`, удаляет связанные
    storage-объекты файлов и их версий, затем помечает элементы корзины как
    окончательно удалённые.

    Args:
        context: Контекст выполнения фоновой задачи.
        owner_id: Идентификатор владельца, для которого нужно очистить корзину.
            Если `None`, очищаются элементы всех владельцев.
        deleted_before: Верхняя граница даты удаления элемента. Если указана,
            обрабатываются только элементы, удалённые не позже этой даты.
        limit: Максимальное количество элементов корзины для обработки.

    Returns:
        Статистика fallback-очистки: количество просмотренных, очищенных,
        удалённых storage-объектов и неуспешных элементов.
    """

    scanned_count = 0
    purged_count = 0
    deleted_storage_objects_count = 0
    failed_count = 0

    async with context.uow_factory() as uow:
        items = await uow.trash.get_expired_items(
            now=datetime.now(UTC),
            owner_id=owner_id,
            include_non_restorable=True,
            offset=0,
            limit=limit,
        )
        if deleted_before is not None:
            items = [item for item in items if item.deleted_at <= deleted_before]

        scanned_count = len(items)
        # Накапливаем освобождаемую квоту по владельцам и списываем её в той же
        # транзакции, что и purge — иначе удалённые из корзины файлы навсегда
        # оставались бы учтёнными в квоте (over-count). Файлы в корзине ещё
        # занимают квоту: декремент происходит именно при окончательном удалении.
        freed_bytes_by_owner: dict[UUID, int] = {}
        freed_files_by_owner: dict[UUID, int] = {}
        for item in items:
            try:
                # Освобождаемая квота этого файла; учитывается в накопителях
                # только после успешного mark_purged ниже.
                item_owner: UUID | None = None
                item_freed_bytes = 0
                node = item.node or await uow.nodes.get_by_id(item.node_id)
                if node is not None and node.node_type == NodeType.FILE:
                    file_row = await uow.files.get_by_node_id(
                        item.node_id,
                        include_deleted_node=True,
                    )
                    if file_row is not None:
                        if file_row.storage_key:
                            await context.storage_service.delete_file_object(
                                bucket=file_row.storage_bucket,
                                object_key=file_row.storage_key,
                                missing_ok=True,
                            )
                            deleted_storage_objects_count += 1
                        for version in file_row.versions:
                            if version.storage_key:
                                await context.storage_service.delete_file_object(
                                    bucket=version.storage_bucket,
                                    object_key=version.storage_key,
                                    missing_ok=True,
                                )
                                deleted_storage_objects_count += 1
                        item_owner = node.owner_id
                        item_freed_bytes = int(file_row.size_bytes or 0)

                await uow.trash.mark_purged(
                    trash_item_id=item.id,
                    purge_node=True,
                    flush=True,
                    refresh=False,
                )
                purged_count += 1
                if item_owner is not None:
                    freed_bytes_by_owner[item_owner] = (
                        freed_bytes_by_owner.get(item_owner, 0) + item_freed_bytes
                    )
                    freed_files_by_owner[item_owner] = (
                        freed_files_by_owner.get(item_owner, 0) + 1
                    )
            except Exception:
                failed_count += 1

        for owner, freed_bytes in freed_bytes_by_owner.items():
            if freed_bytes > 0:
                await uow.quotas.decrease_used_space(
                    user_id=owner,
                    size_bytes=freed_bytes,
                    flush=True,
                    refresh=False,
                )
        for owner, freed_files in freed_files_by_owner.items():
            if freed_files > 0:
                await uow.quotas.decrease_files_used(
                    user_id=owner,
                    count=freed_files,
                    flush=True,
                    refresh=False,
                )

        await uow.commit()

    return {
        "scanned_count": scanned_count,
        "purged_count": purged_count,
        "deleted_storage_objects_count": deleted_storage_objects_count,
        "failed_count": failed_count,
    }


def _optional_payload_uuid(payload: Any, key: str) -> UUID | None:
    """Извлекает опциональный UUID из payload.

    Args:
        payload: Payload задачи с данными для обработчика.
        key: Имя поля, из которого нужно получить UUID.

    Returns:
        UUID из payload или `None`, если значение отсутствует.

    Raises:
        ValueError: Если значение поля не является UUID и не может быть
            интерпретировано как строковое представление UUID.
    """

    value = optional_payload_value(payload, key, default=None)
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise ValueError(f"Поле payload '{key}' должно быть UUID или строкой UUID.")
