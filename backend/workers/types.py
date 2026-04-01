from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeAlias
from uuid import UUID

from core.config import Settings, WorkerSettings
from database import UnitOfWorkFactory
from database.models.enums import BackgroundTaskStatus, BackgroundTaskType
from storage import StorageService


class WorkerState(StrEnum):
    """Состояние worker-процесса.

    Attributes:
        STARTING: Worker инициализируется.
        RUNNING: Worker запущен и может выполнять задачи.
        STOPPING: Worker завершает работу и больше не должен брать новые задачи.
        STOPPED: Worker штатно остановлен.
        FAILED: Worker завершился с ошибкой.
    """

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class WorkerRunMode(StrEnum):
    """Режим запуска worker-процесса.

    Attributes:
        ONCE: Выполнить одну итерацию получения и обработки задач.
        LOOP: Запустить непрерывный цикл обработки задач.
        SCHEDULER: Запустить планировщик периодических задач.
    """

    ONCE = "once"
    LOOP = "loop"
    SCHEDULER = "scheduler"


@dataclass(frozen=True, slots=True)
class WorkerIdentity:
    """Идентификационные данные worker-процесса.

    Attributes:
        worker_id: Уникальный идентификатор экземпляра worker-процесса.
        worker_name: Человекочитаемое имя worker-процесса.
        run_mode: Режим запуска worker-процесса.
    """

    worker_id: str
    worker_name: str
    run_mode: WorkerRunMode


@dataclass(frozen=True, slots=True)
class WorkerTaskExecutionContext:
    """Контекст выполнения фоновой задачи.

    Attributes:
        task_id: Идентификатор фоновой задачи.
        task_type: Тип фоновой задачи.
        payload: Входные данные задачи.
        worker_id: Идентификатор worker-процесса, выполняющего задачу.
        settings: Общие настройки приложения.
        worker_settings: Настройки worker-процесса.
        uow_factory: Фабрика UnitOfWork для операций с базой данных.
        storage_service: Сервис объектного хранилища.
        services: Контейнер или набор сервисов, доступных обработчику задачи.
    """

    task_id: UUID
    task_type: BackgroundTaskType
    payload: Mapping[str, Any]
    worker_id: str
    settings: Settings
    worker_settings: WorkerSettings
    uow_factory: UnitOfWorkFactory
    storage_service: StorageService
    services: Any


@dataclass(frozen=True, slots=True)
class WorkerTaskExecutionResult:
    """Результат выполнения фоновой задачи.

    Attributes:
        success: Успешно ли завершилась задача.
        progress_percent: Итоговый процент выполнения задачи.
        result_data: JSON-совместимые данные результата задачи.
        error_message: Сообщение об ошибке, если задача завершилась неуспешно.
        error_code: Машинно-читаемый код ошибки.
        retry: Нужно ли вернуть задачу в очередь для повторной попытки.
    """

    success: bool
    progress_percent: int = 100
    result_data: dict[str, Any] | None = None
    error_message: str | None = None
    error_code: str | None = None
    retry: bool = False


@dataclass(frozen=True, slots=True)
class WorkerScheduleDefinition:
    """Определение периодической задачи планировщика.

    Attributes:
        schedule_name: Уникальное имя расписания.
        task_type: Тип фоновой задачи, которую нужно создавать по расписанию.
        interval_seconds: Интервал между созданиями задач в секундах.
        payload: Входные данные для создаваемой фоновой задачи.
        enabled: Включено ли расписание.
        initial_status: Начальный статус создаваемой задачи.
    """

    schedule_name: str
    task_type: BackgroundTaskType
    interval_seconds: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    initial_status: BackgroundTaskStatus = BackgroundTaskStatus.PENDING


@dataclass(slots=True)
class WorkerRuntimeStats:
    """Статистика выполнения задач worker-процесса.

    Attributes:
        fetched_count: Количество задач, полученных worker-процессом.
        started_count: Количество задач, запущенных в обработку.
        completed_count: Количество успешно завершённых задач.
        failed_count: Количество задач, завершённых с ошибкой.
        retried_count: Количество задач, возвращённых на повторную попытку.
        skipped_count: Количество пропущенных задач.
        created_scheduled_count: Количество задач, созданных планировщиком.
    """

    fetched_count: int = 0
    started_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    retried_count: int = 0
    skipped_count: int = 0
    created_scheduled_count: int = 0


# Асинхронный обработчик фоновой задачи worker-процесса.
WorkerTaskHandler: TypeAlias = Callable[
    [WorkerTaskExecutionContext],
    Awaitable[WorkerTaskExecutionResult],
]
