from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from database.exceptions import DatabaseConnectionError
from schemas.quotas import QuotaRecalculateRequest
from services.exceptions import ServiceError
from workers.tasks import (
    failure_result,
    optional_payload_value,
    payload_int,
    retry_result,
    success_result,
)
from workers.types import WorkerTaskExecutionContext, WorkerTaskExecutionResult


async def recalculate_user_quota_handler(
    context: WorkerTaskExecutionContext,
) -> WorkerTaskExecutionResult:
    """Пересчитывает квоты одного пользователя или batch пользователей.

    Если в payload передан `user_id`, пересчитывает квоту только этого
    пользователя. Если `user_id` отсутствует, загружает batch активных
    пользователей и пересчитывает квоту для каждого из них.

    Args:
        context: Контекст выполнения фоновой задачи.

    Returns:
        Результат выполнения задачи со статистикой пересчёта квот или
        информацией об ошибке.
    """

    try:
        payload = context.payload
        user_id = _optional_payload_uuid(payload, "user_id")
        limit = payload_int(
            payload,
            "limit",
            default=context.worker_settings.worker_quota_batch_size,
            min_value=1,
            max_value=5000,
        )
        if limit is None:
            limit = context.worker_settings.worker_quota_batch_size

        users_processed = 0
        recalculated_count = 0
        failed_count = 0
        users = []

        if user_id is not None:
            users_processed = 1
            success = await _recalculate_one_user(context, user_id)
            if success:
                recalculated_count = 1
            else:
                failed_count = 1
            return success_result(
                result_data={
                    "users_processed": users_processed,
                    "recalculated_count": recalculated_count,
                    "failed_count": failed_count,
                },
                progress_percent=100,
            )

        async with context.uow_factory() as uow:
            users = await uow.users.list_active_users(offset=0, limit=limit)

        users_processed = len(users)

        for user in users:
            success = await _recalculate_one_user(context, user.id)
            if success:
                recalculated_count += 1
            else:
                failed_count += 1

        return success_result(
            result_data={
                "users_processed": users_processed,
                "recalculated_count": recalculated_count,
                "failed_count": failed_count,
            },
            progress_percent=100,
        )

    except DatabaseConnectionError as exc:
        return retry_result(
            error_message="Временная ошибка подключения при пересчёте квот пользователей.",
            error_code="temporary_unavailable",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
        )
    except ServiceError as exc:
        return failure_result(
            error_message="Ошибка пересчёта квот пользователей.",
            error_code="recalculate_user_quota_failed",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
    except Exception as exc:
        return failure_result(
            error_message="Непредвиденная ошибка пересчёта квот пользователей.",
            error_code="unexpected_recalculate_user_quota_error",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )


async def _recalculate_one_user(
    context: WorkerTaskExecutionContext,
    user_id: UUID,
) -> bool:
    """Пересчитывает квоту конкретного пользователя.

    Args:
        context: Контекст выполнения фоновой задачи.
        user_id: Идентификатор пользователя, для которого нужно пересчитать
            квоту.

    Returns:
        `True`, если квота пользователя успешно пересчитана, иначе `False`.
    """

    try:
        await context.services.quotas.recalculate_quota(
            QuotaRecalculateRequest(user_id=user_id),
            actor_id=None,
        )
        return True
    except Exception:
        return False


def _optional_payload_uuid(payload: Mapping[str, Any], key: str) -> UUID | None:
    """Безопасно читает опциональный UUID из payload.

    Args:
        payload: Payload задачи.
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
