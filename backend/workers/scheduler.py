from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.logging import get_logger
from database.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    TaskPriority,
)
from workers.context import WorkerContext
from workers.tasks import jsonable

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _ScheduleSpec:
    """Описание расписания для создания системной фоновой задачи.

    Attributes:
        task_type: Тип фоновой задачи, которую нужно создать.
        interval_seconds: Интервал запуска задачи в секундах.
        key_prefix: Префикс idempotency key для защиты от дублей.
        priority: Приоритет создаваемой фоновой задачи.
        payload: Дополнительные данные, которые будут добавлены в payload
            задачи.
        key_format: Формат даты и времени для генерации idempotency key.
    """

    task_type: BackgroundTaskType
    interval_seconds: int
    key_prefix: str
    priority: TaskPriority
    payload: dict[str, Any]
    key_format: str


class WorkerScheduler:
    """Планировщик системных фоновых задач.

    Проверяет активные расписания worker-процесса и создаёт системные фоновые
    задачи, если для текущего временного интервала они ещё не были созданы.

    Attributes:
        context: Контекст worker-процесса с настройками, идентификатором
            worker, фабрикой unit of work и сервисами приложения.
    """

    def __init__(self, context: WorkerContext) -> None:
        """Инициализирует планировщик фоновых задач.

        Args:
            context: Контекст worker-процесса.
        """

        self.context = context
        # Кэш последнего обработанного временного слота на каждое расписание.
        # Планировщик опрашивается каждый worker-тик (секунды), а слоты длятся
        # часы/сутки — без кэша каждый тик делал бы лишний SELECT по
        # idempotency_key. Запомнив обработанный слот, в его пределах вообще не
        # ходим в БД. На рестарте кэш пуст → один SELECT на слот, дальше тихо.
        self._handled_slots: dict[str, datetime] = {}

    async def run_due_schedules(self) -> int:
        """Создаёт задачи для всех активных расписаний.

        Если scheduler отключён в настройках worker, метод ничего не создаёт.

        Returns:
            Количество системных фоновых задач, созданных за текущий запуск.
        """

        if not self.context.worker_settings.worker_scheduler_enabled:
            return 0

        created_count = 0
        created_count += await self.schedule_clean_trash()
        created_count += await self.schedule_clean_expired_uploads()
        created_count += await self.schedule_clean_expired_public_links()
        created_count += await self.schedule_recalculate_user_quotas()
        created_count += await self.schedule_storage_integrity_check()
        return created_count

    async def schedule_clean_trash(self) -> int:
        """Планирует системную задачу очистки корзины.

        Returns:
            `1`, если задача была создана, иначе `0`.
        """

        spec = _ScheduleSpec(
            task_type=BackgroundTaskType.CLEAN_TRASH,
            interval_seconds=self.context.worker_settings.worker_clean_trash_interval_seconds,
            key_prefix="system:clean_trash",
            priority=TaskPriority.NORMAL,
            payload={},
            key_format="%Y-%m-%dT%H",
        )
        return await self._create_scheduled_task(spec)

    async def schedule_clean_expired_uploads(self) -> int:
        """Планирует системную задачу очистки просроченных upload-сессий.

        Returns:
            `1`, если задача была создана, иначе `0`.
        """

        spec = _ScheduleSpec(
            task_type=BackgroundTaskType.CLEAN_EXPIRED_UPLOADS,
            interval_seconds=(
                self.context.worker_settings.worker_clean_expired_uploads_interval_seconds
            ),
            key_prefix="system:clean_expired_uploads",
            priority=TaskPriority.NORMAL,
            payload={},
            key_format="%Y-%m-%dT%H:%M",
        )
        return await self._create_scheduled_task(spec)

    async def schedule_clean_expired_public_links(self) -> int:
        """Планирует системную задачу деактивации просроченных публичных ссылок.

        Returns:
            `1`, если задача была создана, иначе `0`.
        """

        spec = _ScheduleSpec(
            task_type=BackgroundTaskType.CLEAN_EXPIRED_PUBLIC_LINKS,
            interval_seconds=(
                self.context.worker_settings.worker_clean_expired_public_links_interval_seconds
            ),
            key_prefix="system:clean_expired_public_links",
            priority=TaskPriority.NORMAL,
            payload={},
            key_format="%Y-%m-%dT%H",
        )
        return await self._create_scheduled_task(spec)

    async def schedule_recalculate_user_quotas(self) -> int:
        """Планирует системную задачу пересчёта пользовательских квот.

        Returns:
            `1`, если задача была создана, иначе `0`.
        """

        spec = _ScheduleSpec(
            task_type=BackgroundTaskType.RECALCULATE_USER_QUOTA,
            interval_seconds=(
                self.context.worker_settings.worker_recalculate_quotas_interval_seconds
            ),
            key_prefix="system:recalculate_user_quota",
            priority=TaskPriority.LOW,
            payload={"limit": self.context.worker_settings.worker_quota_batch_size},
            key_format="%Y-%m-%d",
        )
        return await self._create_scheduled_task(spec)

    async def schedule_storage_integrity_check(self) -> int:
        """Планирует системную задачу проверки целостности storage-объектов.

        Returns:
            `1`, если задача была создана, иначе `0`.
        """

        spec = _ScheduleSpec(
            task_type=BackgroundTaskType.CHECK_STORAGE_INTEGRITY,
            interval_seconds=(
                self.context.worker_settings.worker_storage_integrity_interval_seconds
            ),
            key_prefix="system:check_storage_integrity",
            priority=TaskPriority.LOW,
            payload={"limit": self.context.worker_settings.worker_integrity_batch_size},
            key_format="%Y-%m-%d",
        )
        return await self._create_scheduled_task(spec)

    async def _create_scheduled_task(self, spec: _ScheduleSpec) -> int:
        """Создаёт системную фоновую задачу по описанию расписания.

        Вычисляет временной слот расписания, формирует idempotency key и
        создаёт задачу только если задача с таким ключом ещё не существует.

        Args:
            spec: Описание расписания создаваемой системной задачи.

        Returns:
            `1`, если задача была создана, иначе `0`.
        """

        now = datetime.now(UTC)
        scheduled_at = _floor_to_interval(now, spec.interval_seconds)

        # Этот слот уже обработан в текущем процессе — не ходим в БД повторно.
        if self._handled_slots.get(spec.key_prefix) == scheduled_at:
            return 0

        idempotency_key = f"{spec.key_prefix}:{scheduled_at.strftime(spec.key_format)}"

        payload: dict[str, Any] = {
            "scheduled_for": scheduled_at.isoformat(),
            **spec.payload,
        }

        async with self.context.uow_factory() as uow:
            existing = await uow.tasks.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                # Слот закрыт (задачу создал другой воркер) — запоминаем, чтобы
                # больше не опрашивать БД до следующего слота.
                self._handled_slots[spec.key_prefix] = scheduled_at
                return 0

            task = await uow.tasks.create_task(
                task_type=spec.task_type,
                created_by=None,
                related_entity_type="system",
                related_entity_id=None,
                status=BackgroundTaskStatus.PENDING,
                progress_percent=0,
                result_data=None,
                error_message=None,
                started_at=None,
                finished_at=None,
                flush=False,
                refresh=False,
            )
            task.priority = spec.priority
            task.payload = jsonable(payload)
            task.error_code = None
            task.attempts_count = 0
            task.max_attempts = 3
            task.idempotency_key = idempotency_key
            task.scheduled_at = scheduled_at
            task.locked_by = None
            task.locked_until = None

            await uow.flush()
            await uow.commit()

        # Слот обработан этим процессом — дальнейшие тики в его пределах пропускаем.
        self._handled_slots[spec.key_prefix] = scheduled_at

        logger.info(
            "Создана системная фоновая задача scheduler",
            extra={
                "task_type": spec.task_type.value,
                "idempotency_key": idempotency_key,
                "scheduled_at": scheduled_at.isoformat(),
                "worker_id": self.context.worker_id,
            },
        )
        return 1


def _floor_to_interval(moment: datetime, interval_seconds: int) -> datetime:
    """Округляет момент времени вниз до ближайшей границы интервала.

    Args:
        moment: Момент времени, который нужно округлить.
        interval_seconds: Размер интервала в секундах. Если значение меньше
            или равно нулю, исходный момент времени возвращается без изменений.

    Returns:
        Момент времени, округлённый вниз до ближайшей границы интервала.
    """

    if interval_seconds <= 0:
        return moment

    epoch = int(moment.timestamp())
    floored_epoch = epoch - (epoch % interval_seconds)
    return datetime.fromtimestamp(floored_epoch, tz=UTC)
