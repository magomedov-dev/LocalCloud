from __future__ import annotations

from inspect import isawaitable
from typing import Any

from core.config import get_settings
from core.logging import (
    configure_root_exception_logging,
    get_logger,
    setup_logging,
    silence_noisy_loggers,
)
from database import close_db_client, init_db_client
from workers.context import WorkerContext, build_worker_context
from workers.exceptions import WorkerLifecycleError

logger = get_logger("workers.lifecycle")


async def startup_worker(worker_id: str | None = None) -> WorkerContext:
    """Инициализирует worker-процесс и возвращает рабочий контекст.

    Настраивает логирование, инициализирует клиент базы данных, создаёт
    `WorkerContext` и проверяет готовность storage-bucket'ов.

    Args:
        worker_id: Идентификатор worker-процесса. Если не передан,
            идентификатор будет создан внутри `build_worker_context`.

    Returns:
        Инициализированный контекст worker-процесса.

    Raises:
        WorkerLifecycleError: Если не удалось выполнить запуск worker-процесса.
    """

    try:
        settings = get_settings()
        setup_logging(settings.logging)
        silence_noisy_loggers()
        configure_root_exception_logging()

        init_db_client(settings.database)

        context = build_worker_context(worker_id=worker_id)
        await context.storage_service.ensure_buckets_ready(create_missing=True)

        logger.info(
            "Worker успешно запущен.",
            extra={"worker_id": context.worker_id},
        )
        return context

    except WorkerLifecycleError:
        raise
    except Exception as exc:
        raise WorkerLifecycleError(
            "Не удалось выполнить запуск worker-процесса.",
            details={"operation": "startup_worker"},
            cause=exc,
        ) from exc


async def shutdown_worker(context: WorkerContext | None) -> None:
    """Корректно завершает работу worker-процесса.

    Закрывает storage-клиент, если он предоставляет метод `close`, затем
    закрывает клиент базы данных. Если один или несколько ресурсов не удалось
    закрыть, поднимает `WorkerLifecycleError` с деталями ошибок.

    Args:
        context: Контекст worker-процесса. Может быть `None`, если завершение
            выполняется после частично неуспешного запуска.

    Raises:
        WorkerLifecycleError: Если storage-клиент или клиент базы данных не
            удалось корректно закрыть.
    """

    worker_id: str | None = context.worker_id if context is not None else None
    storage_error: BaseException | None = None
    db_error: BaseException | None = None

    # Останавливаем пул потоков рендеров превью: иначе его потоки переживают
    # завершение event loop, удерживая дескрипторы временных файлов, и процесс
    # не завершается чисто. Импорт локальный — модуль previews тянет тяжёлые
    # зависимости (PyMuPDF/Pillow), не нужные на пути запуска без рендеров.
    try:
        from workers.previews import shutdown_render_executor

        shutdown_render_executor(wait=True)
    except Exception as exc:
        logger.warning(
            "Ошибка при остановке пула рендеров превью.",
            extra={
                "worker_id": worker_id,
                "error_type": exc.__class__.__name__,
                "reason": str(exc),
            },
        )

    if context is not None:
        try:
            close_candidate: Any = getattr(context.storage_service, "close", None)
            if callable(close_candidate):
                close_result = close_candidate()
                if isawaitable(close_result):
                    await close_result
        except Exception as exc:
            storage_error = exc
            logger.warning(
                "Ошибка при закрытии storage-клиента worker-процесса.",
                extra={
                    "worker_id": worker_id,
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )

    try:
        await close_db_client()
    except Exception as exc:
        db_error = exc
        logger.warning(
            "Ошибка при закрытии клиента базы данных worker-процесса.",
            extra={
                "worker_id": worker_id,
                "error_type": exc.__class__.__name__,
                "reason": str(exc),
            },
        )

    if storage_error is not None or db_error is not None:
        cause = db_error if db_error is not None else storage_error
        details = {
            "operation": "shutdown_worker",
            "storage_error": None if storage_error is None else str(storage_error),
            "db_error": None if db_error is None else str(db_error),
            "worker_id": worker_id,
        }
        raise WorkerLifecycleError(
            "Не удалось корректно завершить worker-процесс.",
            details=details,
            cause=cause,
        ) from cause

    logger.info(
        "Worker корректно завершён.",
        extra={"worker_id": worker_id},
    )
