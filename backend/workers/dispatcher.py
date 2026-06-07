from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from core.logging import get_logger
from database.models.enums import BackgroundTaskStatus
from database.models.tasks import BackgroundTask
from workers.context import WorkerContext
from workers.exceptions import WorkerTaskDispatchError, WorkerTaskHandlerError
from workers.registry import WorkerTaskRegistry
from workers.tasks import failure_result, jsonable, retry_result
from workers.types import (
    WorkerRuntimeStats,
    WorkerTaskExecutionContext,
    WorkerTaskExecutionResult,
)

logger = get_logger(__name__)


class WorkerDispatcher:
    """Исполнитель фоновых задач worker-процесса.

    Выбирает готовые к выполнению фоновые задачи, блокирует их за текущим
    worker, запускает соответствующие обработчики и обновляет итоговый статус
    задач в базе данных.

    Dispatcher также освобождает зависшие RUNNING-задачи с истёкшей
    блокировкой перед каждым циклом обработки.

    Attributes:
        context: Контекст worker-процесса с настройками, идентификатором
            worker, фабрикой unit of work и сервисами приложения.
        registry: Реестр обработчиков фоновых задач.
    """

    def __init__(
        self,
        context: WorkerContext,
        registry: WorkerTaskRegistry,
    ) -> None:
        """Инициализирует dispatcher фоновых задач.

        Args:
            context: Контекст worker-процесса.
            registry: Реестр обработчиков задач, используемый для выбора
                обработчика по типу фоновой задачи.
        """

        self.context = context
        self.registry = registry

    async def run_once(self) -> WorkerRuntimeStats:
        """Выполняет один цикл обработки фоновых задач.

        Освобождает зависшие RUNNING-задачи, выбирает и блокирует доступные
        задачи, выполняет их обработчики и обновляет статус каждой задачи в
        зависимости от результата выполнения.

        Returns:
            Статистика одного цикла работы worker-процесса.
        """

        stats = WorkerRuntimeStats()
        await self.mark_stale_running_tasks()

        tasks = await self.fetch_and_lock_tasks(
            limit=self.context.worker_settings.worker_batch_size,
        )
        stats.fetched_count = len(tasks)
        stats.started_count = len(tasks)

        for task in tasks:
            if task.status == BackgroundTaskStatus.CANCELLED:
                stats.skipped_count += 1
                continue

            result = await self.execute_task(task)

            if result.success:
                await self.complete_task(task.id, result)
                stats.completed_count += 1
                continue

            if result.retry and task.attempts_count < task.max_attempts:
                await self.release_task_for_retry(task.id, result)
                stats.retried_count += 1
                continue

            await self.fail_task(task.id, result)
            stats.failed_count += 1

        return stats

    async def fetch_and_lock_tasks(self, limit: int) -> list[BackgroundTask]:
        """Выбирает и блокирует задачи для текущего worker.

        Args:
            limit: Максимальное количество задач, которое нужно выбрать и
                заблокировать за один цикл.

        Returns:
            Список заблокированных фоновых задач, готовых к выполнению.
        """

        tasks: list[BackgroundTask] = []
        async with self.context.uow_factory() as uow:
            tasks = await uow.tasks.lock_due_tasks(
                worker_id=self.context.worker_id,
                lock_ttl_seconds=self.context.worker_settings.worker_task_lock_ttl_seconds,
                limit=limit,
            )
            await uow.commit()
        return tasks

    async def execute_task(
        self,
        task: BackgroundTask,
    ) -> WorkerTaskExecutionResult:
        """Выполняет обработчик одной фоновой задачи.

        Получает обработчик из реестра, формирует контекст выполнения задачи,
        запускает обработчик и нормализует результат. Ошибки обработчика
        преобразуются в результат выполнения с ошибкой или повторной попыткой.

        Args:
            task: Фоновая задача, которую нужно выполнить.

        Returns:
            Результат выполнения фоновой задачи.
        """

        try:
            handler = self.registry.get_handler(task.task_type)
        except WorkerTaskDispatchError as exc:
            logger.warning(
                "Обработчик задачи не найден",
                extra={
                    "task_id": str(task.id),
                    "task_type": task.task_type.value,
                    "worker_id": self.context.worker_id,
                },
            )
            return failure_result(
                "Для типа фоновой задачи не найден обработчик.",
                error_code="handler_not_found",
                result_data={"details": jsonable(exc.to_dict())},
                retry=False,
            )

        payload: Mapping[str, Any]
        if isinstance(task.payload, Mapping):
            payload = task.payload
        else:
            payload = {}

        execution_context = WorkerTaskExecutionContext(
            task_id=task.id,
            task_type=task.task_type,
            payload=payload,
            worker_id=self.context.worker_id,
            settings=self.context.settings,
            worker_settings=self.context.worker_settings,
            uow_factory=self.context.uow_factory,
            storage_service=self.context.storage_service,
            services=self.context.services,
        )

        try:
            result = await handler(execution_context)
            return WorkerTaskExecutionResult(
                success=bool(result.success),
                progress_percent=max(0, min(100, int(result.progress_percent))),
                result_data=(
                    None if result.result_data is None else jsonable(result.result_data)
                ),
                error_message=result.error_message,
                error_code=result.error_code,
                retry=bool(result.retry),
            )
        except WorkerTaskHandlerError as exc:
            logger.warning(
                "Ошибка валидации/исполнения обработчика",
                extra={
                    "task_id": str(task.id),
                    "task_type": task.task_type.value,
                    "worker_id": self.context.worker_id,
                    "error": exc.to_dict(),
                },
            )
            return failure_result(
                error_message=str(exc),
                error_code="handler_error",
                result_data={"details": jsonable(exc.to_dict())},
                retry=False,
            )
        except Exception as exc:
            logger.exception(
                "Непредвиденная ошибка обработчика фоновой задачи",
                extra={
                    "task_id": str(task.id),
                    "task_type": task.task_type.value,
                    "worker_id": self.context.worker_id,
                    "error_type": exc.__class__.__name__,
                },
            )
            return retry_result(
                error_message="Обработчик задачи завершился с непредвиденной ошибкой.",
                error_code="handler_exception",
                result_data={"error_type": exc.__class__.__name__},
            )

    async def complete_task(
        self,
        task_id: UUID,
        result: WorkerTaskExecutionResult,
    ) -> None:
        """Помечает фоновую задачу как успешно завершённую.

        Args:
            task_id: Идентификатор задачи, которую нужно завершить.
            result: Результат успешного выполнения задачи.
        """

        async with self.context.uow_factory() as uow:
            task = await uow.tasks.get_required_by_id(task_id)
            await uow.tasks.update(
                task,
                {
                    "status": BackgroundTaskStatus.COMPLETED,
                    "progress_percent": 100,
                    "result_data": (
                        None
                        if result.result_data is None
                        else jsonable(result.result_data)
                    ),
                    "error_message": None,
                    "error_code": None,
                    "finished_at": datetime.now(UTC),
                    "locked_by": None,
                    "locked_until": None,
                },
                flush=True,
                refresh=False,
            )
            await uow.commit()

    async def fail_task(
        self,
        task_id: UUID,
        result: WorkerTaskExecutionResult,
    ) -> None:
        """Помечает фоновую задачу как завершённую с ошибкой.

        Args:
            task_id: Идентификатор задачи, которую нужно пометить как
                завершённую с ошибкой.
            result: Результат выполнения задачи с информацией об ошибке.
        """

        async with self.context.uow_factory() as uow:
            task = await uow.tasks.get_required_by_id(task_id)
            await uow.tasks.update(
                task,
                {
                    "status": BackgroundTaskStatus.FAILED,
                    "progress_percent": max(0, min(100, int(result.progress_percent))),
                    "result_data": (
                        None
                        if result.result_data is None
                        else jsonable(result.result_data)
                    ),
                    "error_message": (
                        result.error_message or "Фоновая задача завершилась с ошибкой."
                    ),
                    "error_code": result.error_code,
                    "finished_at": datetime.now(UTC),
                    "locked_by": None,
                    "locked_until": None,
                },
                flush=True,
                refresh=False,
            )
            await uow.commit()

    async def release_task_for_retry(
        self,
        task_id: UUID,
        result: WorkerTaskExecutionResult,
    ) -> None:
        """Возвращает фоновую задачу в очередь для повторного выполнения.

        Вычисляет время следующей попытки с учётом настроек worker и переводит
        задачу обратно в статус `PENDING`.

        Args:
            task_id: Идентификатор задачи, которую нужно вернуть в очередь.
            result: Результат выполнения задачи с информацией о причине
                повторной попытки.
        """

        retry_delay_seconds = min(
            self.context.worker_settings.worker_retry_delay_seconds,
            self.context.worker_settings.worker_max_retry_delay_seconds,
        )
        next_attempt_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)

        async with self.context.uow_factory() as uow:
            task = await uow.tasks.get_required_by_id(task_id)
            await uow.tasks.update(
                task,
                {
                    "status": BackgroundTaskStatus.PENDING,
                    "scheduled_at": next_attempt_at,
                    "progress_percent": max(0, min(100, int(result.progress_percent))),
                    "result_data": (
                        None
                        if result.result_data is None
                        else jsonable(result.result_data)
                    ),
                    "error_message": (
                        result.error_message
                        or "Фоновая задача будет повторена автоматически."
                    ),
                    "error_code": result.error_code,
                    "finished_at": None,
                    "locked_by": None,
                    "locked_until": None,
                },
                flush=True,
                refresh=False,
            )
            await uow.commit()

    async def mark_stale_running_tasks(self) -> None:
        """Освобождает зависшие RUNNING-задачи с истёкшей блокировкой.

        Находит задачи, которые остались в статусе `RUNNING` после истечения
        времени блокировки, и возвращает их в очередь для повторного выполнения.
        Если были освобождены задачи, записывает предупреждение в лог.
        """

        stale_before = datetime.now(UTC)
        released_count = 0

        async with self.context.uow_factory() as uow:
            released_count = await uow.tasks.release_stale_running_tasks(
                stale_before=stale_before,
                retry_delay_seconds=self.context.worker_settings.worker_retry_delay_seconds,
                error_message="Блокировка задачи протухла. Задача возвращена в очередь.",
            )
            await uow.commit()

        if released_count > 0:
            logger.warning(
                "Освобождены зависшие фоновые задачи",
                extra={
                    "released_count": released_count,
                    "worker_id": self.context.worker_id,
                },
            )
