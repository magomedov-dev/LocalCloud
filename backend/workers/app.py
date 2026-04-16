from __future__ import annotations

import argparse
import asyncio
import signal
from dataclasses import dataclass

from core.logging import get_logger
from workers.dispatcher import WorkerDispatcher
from workers.lifecycle import shutdown_worker, startup_worker
from workers.registry import build_default_registry
from workers.scheduler import WorkerScheduler

logger = get_logger("workers.app")


@dataclass(frozen=True, slots=True)
class WorkerCliArgs:
    """Аргументы командной строки для запуска worker-процесса.

    Attributes:
        once: Если `True`, worker выполнит один цикл и завершится.
        scheduler_only: Если `True`, worker будет запускать только scheduler
            без выполнения задач через dispatcher.
        no_scheduler: Если `True`, scheduler не будет запускаться.
        worker_id: Явный идентификатор worker-процесса.
        poll_interval: Интервал polling-цикла в секундах. Если не задан,
            используется значение из настроек worker.
    """

    once: bool
    scheduler_only: bool
    no_scheduler: bool
    worker_id: str | None
    poll_interval: float | None


def _build_arg_parser() -> argparse.ArgumentParser:
    """Создаёт parser аргументов командной строки worker-процесса.

    Returns:
        Настроенный экземпляр `argparse.ArgumentParser`.
    """

    parser = argparse.ArgumentParser(
        prog="python -m workers.app",
        description="Запуск worker-процесса LocalCloud.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Выполнить один цикл и завершиться.",
    )
    parser.add_argument(
        "--scheduler-only",
        action="store_true",
        help="Запускать только scheduler без исполнения задач dispatcher.",
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="Не запускать scheduler.",
    )
    parser.add_argument(
        "--worker-id",
        type=str,
        default=None,
        help="Явный идентификатор worker-процесса.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Интервал цикла polling в секундах.",
    )
    return parser


def _parse_args() -> WorkerCliArgs:
    """Разбирает и валидирует аргументы командной строки.

    Returns:
        Валидированные аргументы запуска worker-процесса.

    Raises:
        SystemExit: Если переданы несовместимые или некорректные аргументы.
    """

    parser = _build_arg_parser()
    namespace = parser.parse_args()

    if namespace.scheduler_only and namespace.no_scheduler:
        parser.error(
            "Флаги --scheduler-only и --no-scheduler нельзя использовать вместе."
        )

    if namespace.poll_interval is not None and namespace.poll_interval <= 0:
        parser.error("Значение --poll-interval должно быть больше нуля.")

    return WorkerCliArgs(
        once=bool(namespace.once),
        scheduler_only=bool(namespace.scheduler_only),
        no_scheduler=bool(namespace.no_scheduler),
        worker_id=namespace.worker_id,
        poll_interval=namespace.poll_interval,
    )


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Устанавливает обработчики сигналов завершения worker-процесса.

    При получении `SIGINT` или `SIGTERM` обработчик выставляет `stop_event`,
    чтобы основной цикл worker-процесса мог завершиться корректно.

    Args:
        stop_event: Событие, которое будет установлено при запросе остановки.
    """

    def _request_stop(signame: str) -> None:
        """Запрашивает остановку worker-процесса.

        Args:
            signame: Имя полученного сигнала.
        """

        if not stop_event.is_set():
            logger.info(
                "Получен сигнал завершения worker-процесса.", extra={"signal": signame}
            )
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop, sig.name)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda _s, _f, signame=sig.name: _request_stop(signame))


async def main() -> None:
    """Запускает основной цикл worker-процесса.

    Инициализирует контекст worker, registry, dispatcher и scheduler. Затем
    выполняет polling-цикл до получения сигнала остановки или до завершения
    одного цикла, если передан флаг `--once`.

    Raises:
        WorkerLifecycleError: Если запуск или завершение worker-процесса
            завершились ошибкой.
    """

    args = _parse_args()
    context = None
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    try:
        context = await startup_worker(worker_id=args.worker_id)
        registry = build_default_registry()
        dispatcher = WorkerDispatcher(context=context, registry=registry)
        scheduler = WorkerScheduler(context=context)

        scheduler_enabled = (
            context.worker_settings.worker_scheduler_enabled and not args.no_scheduler
        )
        poll_interval = (
            args.poll_interval
            if args.poll_interval is not None
            else float(context.worker_settings.worker_poll_interval_seconds)
        )

        logger.info(
            "Worker-процесс запущен.",
            extra={
                "worker_id": context.worker_id,
                "once": args.once,
                "scheduler_only": args.scheduler_only,
                "scheduler_enabled": scheduler_enabled,
                "poll_interval_seconds": poll_interval,
            },
        )

        while not stop_event.is_set():
            if scheduler_enabled:
                try:
                    created_count = await scheduler.run_due_schedules()
                    logger.info(
                        "Scheduler cycle завершён.",
                        extra={
                            "worker_id": context.worker_id,
                            "created_tasks_count": created_count,
                        },
                    )
                except Exception as exc:
                    logger.exception(
                        "Ошибка scheduler-цикла worker-процесса.",
                        extra={
                            "worker_id": context.worker_id,
                            "error_type": exc.__class__.__name__,
                        },
                    )

            if not args.scheduler_only:
                try:
                    stats = await dispatcher.run_once()
                    logger.info(
                        "Dispatcher cycle завершён.",
                        extra={
                            "worker_id": context.worker_id,
                            "fetched_count": stats.fetched_count,
                            "started_count": stats.started_count,
                            "completed_count": stats.completed_count,
                            "failed_count": stats.failed_count,
                            "retried_count": stats.retried_count,
                            "skipped_count": stats.skipped_count,
                        },
                    )
                except Exception as exc:
                    logger.exception(
                        "Ошибка dispatcher-цикла worker-процесса.",
                        extra={
                            "worker_id": context.worker_id,
                            "error_type": exc.__class__.__name__,
                        },
                    )

            if args.once:
                break

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except TimeoutError:
                continue

    finally:
        try:
            await shutdown_worker(context)
        finally:
            worker_id: str | None = None
            if context is not None:
                worker_id = context.worker_id
            logger.info("Worker-процесс остановлен.", extra={"worker_id": worker_id})


if __name__ == "__main__":
    asyncio.run(main())
