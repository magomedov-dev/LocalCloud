from __future__ import annotations

from datetime import UTC, datetime
from inspect import isawaitable
from uuid import UUID

from database.exceptions import DatabaseConnectionError
from database.models.enums import AuditAction, AuditResourceType
from services.exceptions import ServiceError
from storage.exceptions import StorageConnectionError, StorageError
from workers.tasks import (
    failure_result,
    payload_datetime,
    payload_int,
    retry_result,
    success_result,
)
from workers.types import WorkerTaskExecutionContext, WorkerTaskExecutionResult


async def clean_expired_public_links_handler(
    context: WorkerTaskExecutionContext,
) -> WorkerTaskExecutionResult:
    """Помечает истёкшие публичные ссылки статусом EXPIRED.

    Загружает batch активных публичных ссылок, срок действия которых истёк до
    указанного момента, помечает каждую ссылку как истёкшую и логирует событие
    аудита, если audit-сервис доступен.

    Args:
        context: Контекст выполнения фоновой задачи.

    Returns:
        Результат выполнения задачи со статистикой обработки ссылок или
        информацией об ошибке.
    """

    try:
        payload = context.payload
        expired_before = (
            payload_datetime(payload, "expired_before")
            if payload.get("expired_before") is not None
            else datetime.now(UTC)
        )
        limit = payload_int(payload, "limit", default=500, min_value=1, max_value=5000)
        if limit is None:
            limit = 500

        scanned_count = 0
        expired_count = 0
        failed_count = 0

        links = []
        async with context.uow_factory() as uow:
            links = await uow.links.find_expired_links(
                moment=expired_before,
                active_only=True,
                offset=0,
                limit=limit,
            )

        scanned_count = len(links)

        for link in links:
            updated_link = None
            try:
                async with context.uow_factory() as uow:
                    updated_link = await uow.links.mark_link_expired_by_id(
                        link.id,
                        flush=True,
                        refresh=False,
                    )
                    await uow.commit()

                expired_count += 1
                if updated_link is not None:
                    await _log_public_link_expired(
                        context, updated_link.id, updated_link.node_id
                    )
            except Exception:
                failed_count += 1

        return success_result(
            result_data={
                "scanned_count": scanned_count,
                "expired_count": expired_count,
                "failed_count": failed_count,
            },
            progress_percent=100,
        )

    except (StorageConnectionError, DatabaseConnectionError) as exc:
        return retry_result(
            error_message="Временная ошибка подключения при очистке истёкших публичных ссылок.",
            error_code="temporary_unavailable",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
        )
    except (ServiceError, StorageError) as exc:
        return failure_result(
            error_message="Ошибка очистки истёкших публичных ссылок.",
            error_code="cleanup_expired_public_links_failed",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
    except Exception as exc:
        return failure_result(
            error_message="Непредвиденная ошибка очистки истёкших публичных ссылок.",
            error_code="unexpected_cleanup_expired_public_links_error",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )


async def _log_public_link_expired(
    context: WorkerTaskExecutionContext,
    link_id: UUID,
    node_id: UUID | None,
) -> None:
    """Пишет событие аудита об истечении публичной ссылки.

    Если audit-сервис или метод `log_success` недоступны, функция ничего не
    делает. Ошибки аудита намеренно подавляются, чтобы сбой логирования не
    ломал обработку batch-задачи.

    Args:
        context: Контекст выполнения фоновой задачи.
        link_id: Идентификатор публичной ссылки.
        node_id: Идентификатор узла, связанного с публичной ссылкой.
    """

    audit_service = getattr(context.services, "audit", None)
    if audit_service is None:
        return

    log_success = getattr(audit_service, "log_success", None)
    if not callable(log_success):
        return

    try:
        maybe_result = log_success(
            action=AuditAction.PUBLIC_LINK_EXPIRED,
            resource_type=AuditResourceType.PUBLIC_LINK,
            entity_type="public_link",
            entity_id=link_id,
            metadata={
                "node_id": str(node_id) if node_id is not None else None,
                "expired_by_worker_id": context.worker_id,
            },
        )
        if isawaitable(maybe_result):
            await maybe_result
    except Exception:
        # Сбой аудита не должен ломать обработку batch-задачи.
        return
