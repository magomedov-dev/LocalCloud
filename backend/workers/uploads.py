from __future__ import annotations

from datetime import UTC, datetime
from inspect import isawaitable

from database.exceptions import DatabaseConnectionError
from database.models.enums import UploadSessionStatus
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


async def clean_expired_uploads_handler(
    context: WorkerTaskExecutionContext,
) -> WorkerTaskExecutionResult:
    """Очищает зависшие и просроченные multipart upload-сессии.

    Если сервис uploads предоставляет метод `clean_expired_uploads`, обработчик
    сначала пытается выполнить очистку через него. Если метод недоступен или
    имеет несовместимую сигнатуру, используется fallback-логика: поиск
    просроченных сессий, отмена multipart upload в storage, перевод сессий в
    статус expired и освобождение quota-слотов.

    Args:
        context: Контекст выполнения фоновой задачи.

    Returns:
        Результат выполнения задачи со статистикой очистки upload-сессий или
        информацией об ошибке.
    """

    try:
        payload = context.payload
        expired_before = (
            payload_datetime(payload, "expired_before")
            if payload.get("expired_before") is not None
            else datetime.now(UTC)
        )
        limit = payload_int(
            payload,
            "limit",
            default=context.worker_settings.worker_cleanup_batch_size,
            min_value=1,
            max_value=5000,
        )
        if limit is None:
            limit = context.worker_settings.worker_cleanup_batch_size

        ready_method = getattr(context.services.uploads, "clean_expired_uploads", None)
        if callable(ready_method):
            try:
                maybe_result = ready_method(
                    expired_before=expired_before,
                    limit=limit,
                )
                service_result = (
                    await maybe_result if isawaitable(maybe_result) else maybe_result
                )
                if isinstance(service_result, dict):
                    return success_result(
                        result_data={
                            "scanned_count": int(
                                service_result.get("scanned_count", 0)
                            ),
                            "expired_count": int(
                                service_result.get("expired_count", 0)
                            ),
                            "aborted_storage_uploads_count": int(
                                service_result.get("aborted_storage_uploads_count", 0)
                            ),
                            "failed_count": int(service_result.get("failed_count", 0)),
                        },
                        progress_percent=100,
                    )
            except TypeError:
                # Сигнатура сервиса может отличаться; переходим к fallback-пути.
                pass

        scanned_count = 0
        expired_count = 0
        aborted_storage_uploads_count = 0
        failed_count = 0
        sessions = []

        async with context.uow_factory() as uow:
            sessions = await uow.upload_sessions.find_expired_sessions(
                moment=expired_before,
                statuses=[
                    UploadSessionStatus.CREATED,
                    UploadSessionStatus.UPLOADING,
                ],
                offset=0,
                limit=limit,
            )

        scanned_count = len(sessions)

        for session in sessions:
            session_failed = False

            try:
                storage_aborted = await context.storage_service.abort_multipart_upload(
                    bucket=session.storage_bucket,
                    object_key=session.storage_key,
                    upload_id=session.upload_id,
                    missing_ok=True,
                )
                if storage_aborted:
                    aborted_storage_uploads_count += 1
            except Exception:
                session_failed = True

            try:
                async with context.uow_factory() as uow:
                    await uow.upload_sessions.mark_expired(
                        session.id,
                        expired_at=expired_before,
                        flush=True,
                        refresh=False,
                    )
                    # Освободите интервал квоты, занимаемый этим сеансом, — в противном случае счетчик
                    # кэшированных активных сеансов будет увеличиваться при каждом истечении срока действия.
                    try:
                        await uow.quotas.decrease_active_upload_sessions_used(
                            user_id=session.user_id,
                            count=1,
                            flush=True,
                            refresh=False,
                        )
                    except Exception:
                        # Повторная синхронизация счетчика при следующей загрузке исправит любые отклонения.
                        pass
                    await uow.commit()
                expired_count += 1
            except Exception:
                session_failed = True

            if session_failed:
                failed_count += 1

        return success_result(
            result_data={
                "scanned_count": scanned_count,
                "expired_count": expired_count,
                "aborted_storage_uploads_count": aborted_storage_uploads_count,
                "failed_count": failed_count,
            },
            progress_percent=100,
        )

    except (StorageConnectionError, DatabaseConnectionError) as exc:
        return retry_result(
            error_message="Временная ошибка подключения при очистке upload-сессий.",
            error_code="temporary_unavailable",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
        )
    except (ServiceError, StorageError) as exc:
        return failure_result(
            error_message="Ошибка очистки upload-сессий.",
            error_code="cleanup_uploads_failed",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
    except Exception as exc:
        return failure_result(
            error_message="Непредвиденная ошибка очистки upload-сессий.",
            error_code="unexpected_cleanup_uploads_error",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
