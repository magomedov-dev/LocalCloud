from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import String, case, cast, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database.exceptions import EntityNotFoundError, InvalidQueryError
from database.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    TaskPriority,
)
from database.models.tasks import BackgroundTask
from database.repositories.base import BaseRepository

TaskSortField = Literal[
    "created_at",
    "started_at",
    "finished_at",
    "updated_at",
    "progress_percent",
    "status",
    "task_type",
]

SortDirection = Literal["asc", "desc"]


class BackgroundTasksRepository(BaseRepository[BackgroundTask]):
    """Репозиторий для работы с фоновыми задачами.

    Инкапсулирует операции создания, получения, поиска, фильтрации,
    обновления статуса, изменения прогресса, сохранения результата,
    обработки ошибок, массовой отмены, очистки и подсчёта фоновых задач.

    Работает с моделью ``BackgroundTask`` через асинхронную SQLAlchemy-сессию.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий фоновых задач.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=BackgroundTask)

    # ------------------------------------------------------------------
    # Получение по идентификатору
    # ------------------------------------------------------------------

    async def get_task_by_id(
        self,
        task_id: uuid.UUID,
    ) -> BackgroundTask | None:
        """Возвращает фоновую задачу по идентификатору.

        Args:
            task_id: Идентификатор фоновой задачи.

        Returns:
            Фоновая задача, если она найдена, иначе ``None``.
        """

        return await self.get_by_id(task_id)

    async def get_required_task_by_id(
        self,
        task_id: uuid.UUID,
    ) -> BackgroundTask:
        """Возвращает фоновую задачу по идентификатору.

        Args:
            task_id: Идентификатор фоновой задачи.

        Returns:
            Найденная фоновая задача.

        Raises:
            EntityNotFoundError: Если фоновая задача не найдена.
        """

        return await self.get_required_by_id(task_id)

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> BackgroundTask | None:
        """Возвращает фоновую задачу по ключу идемпотентности.

        Args:
            idempotency_key: Ключ идемпотентности фоновой задачи.

        Returns:
            Фоновая задача, если она найдена, иначе ``None``.

        Raises:
            InvalidQueryError: Если ключ идемпотентности пустой.
        """

        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise InvalidQueryError(
                "Ключ идемпотентности не должен быть пустым.",
                repository=self.repository_name,
                operation="get_by_idempotency_key",
            )

        statement = select(BackgroundTask).where(
            BackgroundTask.idempotency_key == normalized_key
        )
        return await self.scalar_one_or_none(
            statement,
            operation="get_by_idempotency_key",
        )

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> BackgroundTask | None:
        """Возвращает фоновую задачу по идентификатору.

        Args:
            entity_id: Идентификатор фоновой задачи.

        Returns:
            Фоновая задача, если она найдена, иначе ``None``.
        """

        return await super().get_by_id(entity_id)

    async def get_required_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> BackgroundTask:
        """Возвращает фоновую задачу по идентификатору.

        Args:
            entity_id: Идентификатор фоновой задачи.

        Returns:
            Найденная фоновая задача.

        Raises:
            EntityNotFoundError: Если фоновая задача не найдена.
        """

        task = await super().get_by_id(entity_id)

        if task is None:
            raise EntityNotFoundError(
                "BackgroundTask",
                entity_id=entity_id,
                repository=self.repository_name,
            )

        return task

    # ------------------------------------------------------------------
    # Создание задач
    # ------------------------------------------------------------------

    async def create_task(
        self,
        *,
        task_type: BackgroundTaskType,
        created_by: uuid.UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        status: BackgroundTaskStatus = BackgroundTaskStatus.PENDING,
        progress_percent: int = 0,
        result_data: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Создаёт фоновую задачу.

        Перед созданием валидирует процент выполнения и согласованность статуса
        с датами начала, завершения и прогрессом.

        Args:
            task_type: Тип фоновой задачи.
            created_by: Идентификатор пользователя, создавшего задачу.
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            status: Начальный статус задачи.
            progress_percent: Начальный процент выполнения.
            result_data: Данные результата задачи.
            error_message: Сообщение об ошибке.
            started_at: Дата начала выполнения.
            finished_at: Дата завершения.
            flush: Выполнить ли ``flush`` после создания.
            refresh: Выполнить ли ``refresh`` после создания.

        Returns:
            Созданная фоновая задача.

        Raises:
            InvalidQueryError: Если прогресс, статус, даты или тип связанной сущности некорректны.
        """

        self._validate_progress_percent(progress_percent)
        self._validate_status_timestamps(
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            progress_percent=progress_percent,
        )

        task = BackgroundTask(
            task_type=task_type,
            status=status,
            created_by=created_by,
            related_entity_type=self._normalize_related_entity_type(
                related_entity_type,
            ),
            related_entity_id=related_entity_id,
            progress_percent=progress_percent,
            result_data=result_data,
            error_message=self._normalize_error_message(error_message),
            started_at=started_at,
            finished_at=finished_at,
        )

        return await self.create(
            task,
            flush=flush,
            refresh=refresh,
        )

    async def create_system_task(
        self,
        *,
        task_type: BackgroundTaskType,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Создаёт системную фоновую задачу.

        Системная задача не связана с конкретным пользователем, поэтому
        поле ``created_by`` устанавливается в ``None``.

        Args:
            task_type: Тип фоновой задачи.
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            flush: Выполнить ли ``flush`` после создания.
            refresh: Выполнить ли ``refresh`` после создания.

        Returns:
            Созданная системная фоновая задача.
        """

        return await self.create_task(
            task_type=task_type,
            created_by=None,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            flush=flush,
            refresh=refresh,
        )

    async def create_user_task(
        self,
        *,
        task_type: BackgroundTaskType,
        created_by: uuid.UUID,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Создаёт пользовательскую фоновую задачу.

        Args:
            task_type: Тип фоновой задачи.
            created_by: Идентификатор пользователя, создавшего задачу.
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            flush: Выполнить ли ``flush`` после создания.
            refresh: Выполнить ли ``refresh`` после создания.

        Returns:
            Созданная пользовательская фоновая задача.
        """

        return await self.create_task(
            task_type=task_type,
            created_by=created_by,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Списки и фильтрация
    # ------------------------------------------------------------------

    async def list_tasks(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        task_types: Sequence[BackgroundTaskType] | None = None,
        status: BackgroundTaskStatus | None = None,
        statuses: Sequence[BackgroundTaskStatus] | None = None,
        created_by: uuid.UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
        finished_from: datetime | None = None,
        finished_to: datetime | None = None,
        system_only: bool | None = None,
        result_data_contains: dict[str, Any] | None = None,
        sort_by: TaskSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[BackgroundTask]:
        """Возвращает список фоновых задач с фильтрацией, сортировкой и пагинацией.

        Поддерживает фильтрацию по типу, статусу, пользователю, связанной сущности,
        периодам создания, запуска и завершения, системным задачам и содержимому
        ``result_data``.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Один тип задачи для фильтрации.
            task_types: Набор типов задач для фильтрации.
            status: Один статус задачи для фильтрации.
            statuses: Набор статусов задач для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачу.
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            created_from: Нижняя граница даты создания.
            created_to: Верхняя граница даты создания.
            started_from: Нижняя граница даты запуска.
            started_to: Верхняя граница даты запуска.
            finished_from: Нижняя граница даты завершения.
            finished_to: Верхняя граница даты завершения.
            system_only: ``True`` — только системные задачи, ``False`` — только пользовательские.
            result_data_contains: JSON-фрагмент, который должен содержаться в ``result_data``.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список фоновых задач.

        Raises:
            InvalidQueryError: Если параметры пагинации, сортировки, периодов
                или фильтров некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions = self._build_conditions(
            task_type=task_type,
            task_types=task_types,
            status=status,
            statuses=statuses,
            created_by=created_by,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            created_from=created_from,
            created_to=created_to,
            started_from=started_from,
            started_to=started_to,
            finished_from=finished_from,
            finished_to=finished_to,
            system_only=system_only,
            result_data_contains=result_data_contains,
        )

        statement = select(BackgroundTask)

        if conditions:
            statement = statement.where(*conditions)

        statement = (
            statement.order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(statement, operation="list_tasks")

    async def list_user_tasks(
        self,
        created_by: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        task_types: Sequence[BackgroundTaskType] | None = None,
        status: BackgroundTaskStatus | None = None,
        statuses: Sequence[BackgroundTaskStatus] | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        sort_by: TaskSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[BackgroundTask]:
        """Возвращает фоновые задачи конкретного пользователя.

        Args:
            created_by: Идентификатор пользователя, создавшего задачи.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Один тип задачи для фильтрации.
            task_types: Набор типов задач для фильтрации.
            status: Один статус задачи для фильтрации.
            statuses: Набор статусов задач для фильтрации.
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список фоновых задач пользователя.
        """

        return await self.list_tasks(
            offset=offset,
            limit=limit,
            task_type=task_type,
            task_types=task_types,
            status=status,
            statuses=statuses,
            created_by=created_by,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_system_tasks(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        status: BackgroundTaskStatus | None = None,
        sort_by: TaskSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[BackgroundTask]:
        """Возвращает системные фоновые задачи.

        Системными считаются задачи без значения `created_by`.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Тип задачи для фильтрации.
            status: Статус задачи для фильтрации.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список системных фоновых задач.
        """

        return await self.list_tasks(
            offset=offset,
            limit=limit,
            task_type=task_type,
            status=status,
            system_only=True,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_by_status(
        self,
        status: BackgroundTaskStatus,
        *,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        created_by: uuid.UUID | None = None,
        sort_by: TaskSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[BackgroundTask]:
        """Возвращает фоновые задачи с указанным статусом.

        Args:
            status: Статус задач.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Тип задачи для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачи.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список задач с указанным статусом.
        """

        return await self.list_tasks(
            offset=offset,
            limit=limit,
            task_type=task_type,
            status=status,
            created_by=created_by,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_by_type(
        self,
        task_type: BackgroundTaskType,
        *,
        offset: int = 0,
        limit: int = 100,
        status: BackgroundTaskStatus | None = None,
        statuses: Sequence[BackgroundTaskStatus] | None = None,
        created_by: uuid.UUID | None = None,
        sort_by: TaskSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[BackgroundTask]:
        """Возвращает фоновые задачи указанного типа.

        Args:
            task_type: Тип задач.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            status: Один статус задачи для фильтрации.
            statuses: Набор статусов задач для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачи.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список задач указанного типа.
        """

        return await self.list_tasks(
            offset=offset,
            limit=limit,
            task_type=task_type,
            status=status,
            statuses=statuses,
            created_by=created_by,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def find_pending_tasks(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        task_types: Sequence[BackgroundTaskType] | None = None,
        oldest_first: bool = True,
    ) -> list[BackgroundTask]:
        """Возвращает задачи, ожидающие выполнения.

        При ``oldest_first=True`` задачи сортируются от старых к новым, что удобно
        для очереди выполнения.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Один тип задачи для фильтрации.
            task_types: Набор типов задач для фильтрации.
            oldest_first: Сортировать ли сначала самые старые задачи.

        Returns:
            Список задач со статусом ``PENDING``.
        """

        return await self.list_tasks(
            offset=offset,
            limit=limit,
            task_type=task_type,
            task_types=task_types,
            status=BackgroundTaskStatus.PENDING,
            sort_by="created_at",
            sort_direction="asc" if oldest_first else "desc",
        )

    async def list_due_tasks(
        self,
        *,
        limit: int = 100,
        task_types: Sequence[BackgroundTaskType] | None = None,
        now: datetime | None = None,
    ) -> list[BackgroundTask]:
        """Возвращает задачи, готовые к запуску, без установки блокировки.

        В выборку попадают ожидающие задачи, у которых наступило время
        ``scheduled_at``, не исчерпано количество попыток и отсутствует
        активная блокировка. Результат сортируется по приоритету, времени
        планирования и времени создания.

        Args:
            limit: Максимальное количество задач.
            task_types: Типы задач для фильтрации.
            now: Момент времени для проверки готовности. Если не передан,
                используется текущее UTC-время.

        Returns:
            Список задач, готовых к запуску.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=0, limit=limit)
        current_moment = now or self._utc_now()

        priority_rank = case(
            (BackgroundTask.priority == TaskPriority.CRITICAL, 0),
            (BackgroundTask.priority == TaskPriority.HIGH, 1),
            (BackgroundTask.priority == TaskPriority.NORMAL, 2),
            (BackgroundTask.priority == TaskPriority.LOW, 3),
            else_=99,
        )

        conditions: list[Any] = [
            BackgroundTask.status == BackgroundTaskStatus.PENDING,
            or_(
                BackgroundTask.scheduled_at.is_(None),
                BackgroundTask.scheduled_at <= current_moment,
            ),
            BackgroundTask.attempts_count < BackgroundTask.max_attempts,
            or_(
                BackgroundTask.locked_until.is_(None),
                BackgroundTask.locked_until < current_moment,
            ),
        ]

        if task_types:
            conditions.append(BackgroundTask.task_type.in_(task_types))

        statement = (
            select(BackgroundTask)
            .where(*conditions)
            .order_by(
                priority_rank.asc(),
                BackgroundTask.scheduled_at.asc().nullsfirst(),
                BackgroundTask.created_at.asc(),
            )
            .limit(limit)
        )

        return await self.scalars_all(statement, operation="list_due_tasks")

    async def lock_due_tasks(
        self,
        *,
        worker_id: str,
        lock_ttl_seconds: int,
        limit: int,
        task_types: Sequence[BackgroundTaskType] | None = None,
        now: datetime | None = None,
        flush: bool = True,
    ) -> list[BackgroundTask]:
        """Атомарно выбирает и блокирует задачи, готовые к выполнению.

        Использует ``SELECT FOR UPDATE SKIP LOCKED``, чтобы несколько воркеров
        могли параллельно забирать задачи без конфликтов. Для выбранных задач
        устанавливаются ``RUNNING``, ``worker_id`` и ``locked_until``.

        Args:
            worker_id: Идентификатор воркера, который забирает задачи.
            lock_ttl_seconds: Время жизни блокировки в секундах.
            limit: Максимальное количество задач для блокировки.
            task_types: Типы задач для фильтрации.
            now: Момент времени для проверки готовности. Если не передан,
                используется текущее UTC-время.
            flush: Выполнить ``flush`` после установки блокировок.

        Returns:
            Список заблокированных задач.

        Raises:
            InvalidQueryError: Если ``worker_id`` пустой, ``lock_ttl_seconds``
                не положительный или параметры пагинации некорректны.
        """

        if not worker_id.strip():
            raise InvalidQueryError(
                "Идентификатор worker не должен быть пустым.",
                repository=self.repository_name,
                operation="lock_due_tasks",
            )

        if lock_ttl_seconds <= 0:
            raise InvalidQueryError(
                "Параметр lock_ttl_seconds должен быть больше нуля.",
                repository=self.repository_name,
                operation="lock_due_tasks",
                details={"lock_ttl_seconds": lock_ttl_seconds},
            )

        self._validate_pagination(offset=0, limit=limit)
        current_moment = now or self._utc_now()
        lock_until = current_moment + timedelta(seconds=lock_ttl_seconds)

        priority_rank = case(
            (BackgroundTask.priority == TaskPriority.CRITICAL, 0),
            (BackgroundTask.priority == TaskPriority.HIGH, 1),
            (BackgroundTask.priority == TaskPriority.NORMAL, 2),
            (BackgroundTask.priority == TaskPriority.LOW, 3),
            else_=99,
        )

        conditions: list[Any] = [
            BackgroundTask.status == BackgroundTaskStatus.PENDING,
            or_(
                BackgroundTask.scheduled_at.is_(None),
                BackgroundTask.scheduled_at <= current_moment,
            ),
            BackgroundTask.attempts_count < BackgroundTask.max_attempts,
            or_(
                BackgroundTask.locked_until.is_(None),
                BackgroundTask.locked_until < current_moment,
            ),
        ]

        if task_types:
            conditions.append(BackgroundTask.task_type.in_(task_types))

        statement = (
            select(BackgroundTask)
            .where(*conditions)
            .order_by(
                priority_rank.asc(),
                BackgroundTask.scheduled_at.asc().nullsfirst(),
                BackgroundTask.created_at.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

        tasks = await self.scalars_all(statement, operation="lock_due_tasks")

        for task in tasks:
            task.start(
                started_at=current_moment,
                worker_id=worker_id,
                locked_until=lock_until,
            )

        if flush and tasks:
            await self.flush()

        return tasks

    async def find_running_tasks(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        task_types: Sequence[BackgroundTaskType] | None = None,
        oldest_first: bool = True,
    ) -> list[BackgroundTask]:
        """Возвращает выполняющиеся фоновые задачи.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Один тип задачи для фильтрации.
            task_types: Набор типов задач для фильтрации.
            oldest_first: Сортировать ли сначала самые давно запущенные задачи.

        Returns:
            Список задач со статусом `RUNNING`.

        Raises:
            InvalidQueryError: Если параметры пагинации или фильтров некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions = self._build_conditions(
            task_type=task_type,
            task_types=task_types,
            status=BackgroundTaskStatus.RUNNING,
        )

        statement = select(BackgroundTask)

        if conditions:
            statement = statement.where(*conditions)

        if oldest_first:
            statement = statement.order_by(
                BackgroundTask.started_at.asc().nullslast(),
                BackgroundTask.created_at.asc(),
            )
        else:
            statement = statement.order_by(
                BackgroundTask.started_at.desc().nullslast(),
                BackgroundTask.created_at.desc(),
            )

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="find_running_tasks",
        )

    async def find_unfinished_tasks(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        task_types: Sequence[BackgroundTaskType] | None = None,
        created_by: uuid.UUID | None = None,
        oldest_first: bool = True,
    ) -> list[BackgroundTask]:
        """Возвращает незавершённые фоновые задачи.

        Незавершёнными считаются задачи со статусами ``PENDING`` и ``RUNNING``.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Один тип задачи для фильтрации.
            task_types: Набор типов задач для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачи.
            oldest_first: Сортировать ли сначала самые старые задачи.

        Returns:
            Список незавершённых задач.
        """

        return await self.list_tasks(
            offset=offset,
            limit=limit,
            task_type=task_type,
            task_types=task_types,
            statuses=[
                BackgroundTaskStatus.PENDING,
                BackgroundTaskStatus.RUNNING,
            ],
            created_by=created_by,
            sort_by="created_at",
            sort_direction="asc" if oldest_first else "desc",
        )

    async def find_finished_tasks(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        task_types: Sequence[BackgroundTaskType] | None = None,
        created_by: uuid.UUID | None = None,
        newest_first: bool = True,
    ) -> list[BackgroundTask]:
        """Возвращает завершённые фоновые задачи.

        Завершёнными считаются задачи со статусами ``COMPLETED``, ``FAILED``
        и ``CANCELLED``.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Один тип задачи для фильтрации.
            task_types: Набор типов задач для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачи.
            newest_first: Сортировать ли сначала самые новые завершённые задачи.

        Returns:
            Список завершённых задач.
        """

        return await self.list_tasks(
            offset=offset,
            limit=limit,
            task_type=task_type,
            task_types=task_types,
            statuses=[
                BackgroundTaskStatus.COMPLETED,
                BackgroundTaskStatus.FAILED,
                BackgroundTaskStatus.CANCELLED,
            ],
            created_by=created_by,
            sort_by="finished_at",
            sort_direction="desc" if newest_first else "asc",
        )

    async def get_related_entity_tasks(
        self,
        *,
        related_entity_type: str,
        related_entity_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        status: BackgroundTaskStatus | None = None,
        sort_by: TaskSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[BackgroundTask]:
        """Возвращает задачи, связанные с конкретной сущностью.

        Args:
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Тип задачи для фильтрации.
            status: Статус задачи для фильтрации.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список задач, связанных с указанной сущностью.
        """

        return await self.list_tasks(
            offset=offset,
            limit=limit,
            task_type=task_type,
            status=status,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def get_latest_related_entity_task(
        self,
        *,
        related_entity_type: str,
        related_entity_id: uuid.UUID,
        task_type: BackgroundTaskType | None = None,
        statuses: Sequence[BackgroundTaskStatus] | None = None,
    ) -> BackgroundTask | None:
        """Возвращает последнюю задачу, связанную с конкретной сущностью.

        Args:
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            task_type: Тип задачи для фильтрации.
            statuses: Набор статусов задач для фильтрации.

        Returns:
            Последняя найденная задача или ``None``.
        """

        tasks = await self.list_tasks(
            offset=0,
            limit=1,
            task_type=task_type,
            statuses=statuses,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            sort_by="created_at",
            sort_direction="desc",
        )

        return tasks[0] if tasks else None

    # ------------------------------------------------------------------
    # Поиск
    # ------------------------------------------------------------------

    async def search_tasks(
        self,
        *,
        query: str | None = None,
        offset: int = 0,
        limit: int = 100,
        task_type: BackgroundTaskType | None = None,
        task_types: Sequence[BackgroundTaskType] | None = None,
        status: BackgroundTaskStatus | None = None,
        statuses: Sequence[BackgroundTaskStatus] | None = None,
        created_by: uuid.UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        system_only: bool | None = None,
        sort_by: TaskSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[BackgroundTask]:
        """Выполняет поиск фоновых задач.

        Поисковая строка применяется к ``task_type``, ``status``,
        ``related_entity_type`` и ``error_message``.

        Args:
            query: Поисковая строка.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            task_type: Один тип задачи для фильтрации.
            task_types: Набор типов задач для фильтрации.
            status: Один статус задачи для фильтрации.
            statuses: Набор статусов задач для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачи.
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            system_only: ``True`` — только системные задачи, ``False`` — только пользовательские.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список найденных фоновых задач.

        Raises:
            InvalidQueryError: Если параметры пагинации, сортировки или фильтров некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions = self._build_conditions(
            task_type=task_type,
            task_types=task_types,
            status=status,
            statuses=statuses,
            created_by=created_by,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            system_only=system_only,
        )

        normalized_query = self._normalize_search_query(query)

        if normalized_query is not None:
            pattern = f"%{normalized_query}%"

            conditions.append(
                or_(
                    cast(BackgroundTask.task_type, String).ilike(pattern),
                    cast(BackgroundTask.status, String).ilike(pattern),
                    BackgroundTask.related_entity_type.ilike(pattern),
                    BackgroundTask.error_message.ilike(pattern),
                )
            )

        statement = select(BackgroundTask)

        if conditions:
            statement = statement.where(*conditions)

        statement = (
            statement.order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(statement, operation="search_tasks")

    # ------------------------------------------------------------------
    # Обновление статуса
    # ------------------------------------------------------------------

    async def update_status(
        self,
        task: BackgroundTask,
        status: BackgroundTaskStatus,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        progress_percent: int | None = None,
        result_data: dict[str, Any] | None = None,
        error_message: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Обновляет статус фоновой задачи и связанные поля.

        Args:
            task: ORM-объект фоновой задачи.
            status: Новый статус задачи.
            started_at: Дата начала выполнения.
            finished_at: Дата завершения.
            progress_percent: Новый процент выполнения.
            result_data: Данные результата задачи.
            error_message: Сообщение об ошибке.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.

        Raises:
            InvalidQueryError: Если процент выполнения некорректен.
        """

        values: dict[str, Any] = {"status": status}

        if started_at is not None:
            values["started_at"] = started_at

        if finished_at is not None:
            values["finished_at"] = finished_at

        if progress_percent is not None:
            self._validate_progress_percent(progress_percent)
            values["progress_percent"] = progress_percent

        if result_data is not None:
            values["result_data"] = result_data

        if error_message is not None:
            values["error_message"] = self._normalize_error_message(error_message)

        return await self.update(
            task,
            values,
            flush=flush,
            refresh=refresh,
        )

    async def update_status_by_id(
        self,
        task_id: uuid.UUID,
        status: BackgroundTaskStatus,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        progress_percent: int | None = None,
        result_data: dict[str, Any] | None = None,
        error_message: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Обновляет статус фоновой задачи по идентификатору.

        Args:
            task_id: Идентификатор фоновой задачи.
            status: Новый статус задачи.
            started_at: Дата начала выполнения.
            finished_at: Дата завершения.
            progress_percent: Новый процент выполнения.
            result_data: Данные результата задачи.
            error_message: Сообщение об ошибке.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.

        Raises:
            EntityNotFoundError: Если фоновая задача не найдена.
            InvalidQueryError: Если процент выполнения некорректен.
        """

        task = await self.get_required_by_id(task_id)

        return await self.update_status(
            task,
            status,
            started_at=started_at,
            finished_at=finished_at,
            progress_percent=progress_percent,
            result_data=result_data,
            error_message=error_message,
            flush=flush,
            refresh=refresh,
        )

    async def mark_pending(
        self,
        task: BackgroundTask,
        *,
        reset_progress: bool = False,
        clear_result: bool = False,
        clear_error: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Возвращает задачу в состояние ожидания.

        При необходимости сбрасывает прогресс, очищает результат и сообщение об ошибке.

        Args:
            task: ORM-объект фоновой задачи.
            reset_progress: Сбросить ли прогресс до `0`.
            clear_result: Очистить ли данные результата.
            clear_error: Очистить ли сообщение об ошибке.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``PENDING``.
        """

        values: dict[str, Any] = {
            "status": BackgroundTaskStatus.PENDING,
            "started_at": None,
            "finished_at": None,
        }

        if reset_progress:
            values["progress_percent"] = 0

        if clear_result:
            values["result_data"] = None

        if clear_error:
            values["error_message"] = None

        return await self.update(
            task,
            values,
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "status",
                "started_at",
                "finished_at",
                "progress_percent",
                "result_data",
                "error_message",
            },
        )

    async def mark_pending_by_id(
        self,
        task_id: uuid.UUID,
        *,
        reset_progress: bool = False,
        clear_result: bool = False,
        clear_error: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Возвращает задачу в состояние ожидания  по id.

        При необходимости сбрасывает прогресс, очищает результат и сообщение об ошибке.

        Args:
            task_id: Идентификатор фоновой задачи.
            reset_progress: Сбросить ли прогресс до `0`.
            clear_result: Очистить ли данные результата.
            clear_error: Очистить ли сообщение об ошибке.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``PENDING``.
        """

        task = await self.get_required_by_id(task_id)

        return await self.mark_pending(
            task,
            reset_progress=reset_progress,
            clear_result=clear_result,
            clear_error=clear_error,
            flush=flush,
            refresh=refresh,
        )

    async def mark_running(
        self,
        task: BackgroundTask,
        *,
        started_at: datetime | None = None,
        reset_progress: bool = False,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Помечает задачу как выполняющуюся.

        Устанавливает статус ``RUNNING``, дату старта, очищает дату завершения
        и сообщение об ошибке.

        Args:
            task: ORM-объект фоновой задачи.
            started_at: Дата начала выполнения. Если не передана, используется текущее UTC-время.
            reset_progress: Сбросить ли прогресс до `0`.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``RUNNING``.
        """

        values: dict[str, Any] = {
            "status": BackgroundTaskStatus.RUNNING,
            "started_at": started_at or self._utc_now(),
            "finished_at": None,
            "error_message": None,
        }

        if reset_progress:
            values["progress_percent"] = 0

        return await self.update(
            task,
            values,
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "status",
                "started_at",
                "finished_at",
                "error_message",
                "progress_percent",
            },
        )

    async def mark_running_by_id(
        self,
        task_id: uuid.UUID,
        *,
        started_at: datetime | None = None,
        reset_progress: bool = False,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Помечает задачу как выполняющуюся по id.

        Устанавливает статус ``RUNNING``, дату старта, очищает дату завершения
        и сообщение об ошибке.

        Args:
            task_id: Идентификатор фоновой задачи.
            started_at: Дата начала выполнения. Если не передана, используется текущее UTC-время.
            reset_progress: Сбросить ли прогресс до `0`.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``RUNNING``.
        """

        task = await self.get_required_by_id(task_id)

        return await self.mark_running(
            task,
            started_at=started_at,
            reset_progress=reset_progress,
            flush=flush,
            refresh=refresh,
        )

    async def mark_completed(
        self,
        task: BackgroundTask,
        *,
        result_data: dict[str, Any] | None = None,
        finished_at: datetime | None = None,
        progress_percent: int = 100,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Помечает задачу как успешно завершённую.

        Args:
            task: ORM-объект фоновой задачи.
            result_data: Данные результата задачи.
            finished_at: Дата завершения. Если не передана, используется текущее UTC-время.
            progress_percent: Итоговый процент выполнения.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``COMPLETED``.

        Raises:
            InvalidQueryError: Если процент выполнения некорректен.
        """

        self._validate_progress_percent(progress_percent)

        return await self.update(
            task,
            {
                "status": BackgroundTaskStatus.COMPLETED,
                "progress_percent": progress_percent,
                "result_data": result_data,
                "error_message": None,
                "finished_at": finished_at or self._utc_now(),
            },
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "status",
                "progress_percent",
                "result_data",
                "error_message",
                "finished_at",
            },
        )

    async def mark_completed_by_id(
        self,
        task_id: uuid.UUID,
        *,
        result_data: dict[str, Any] | None = None,
        finished_at: datetime | None = None,
        progress_percent: int = 100,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Помечает задачу как успешно завершённую по id.

        Args:
            task_id: Идентификатор фоновой задачи.
            result_data: Данные результата задачи.
            finished_at: Дата завершения. Если не передана, используется текущее UTC-время.
            progress_percent: Итоговый процент выполнения.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``COMPLETED``.

        Raises:
            InvalidQueryError: Если процент выполнения некорректен.
        """

        task = await self.get_required_by_id(task_id)

        return await self.mark_completed(
            task,
            result_data=result_data,
            finished_at=finished_at,
            progress_percent=progress_percent,
            flush=flush,
            refresh=refresh,
        )

    async def mark_failed(
        self,
        task: BackgroundTask,
        *,
        error_message: str,
        finished_at: datetime | None = None,
        result_data: dict[str, Any] | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Помечает задачу как завершённую с ошибкой.

        Сообщение об ошибке обязательно и не может быть пустым.

        Args:
            task: ORM-объект фоновой задачи.
            error_message: Сообщение об ошибке.
            finished_at: Дата завершения. Если не передана, используется текущее UTC-время.
            result_data: Дополнительные данные результата или диагностики.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``FAILED``.

        Raises:
            InvalidQueryError: Если сообщение об ошибке пустое.
        """

        normalized_error = self._normalize_error_message(error_message)

        if not normalized_error:
            raise InvalidQueryError(
                "Сообщение об ошибке фоновой задачи не может быть пустым.",
                repository=self.repository_name,
                operation="mark_failed",
            )

        return await self.update(
            task,
            {
                "status": BackgroundTaskStatus.FAILED,
                "error_message": normalized_error,
                "result_data": result_data,
                "finished_at": finished_at or self._utc_now(),
            },
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "status",
                "error_message",
                "result_data",
                "finished_at",
            },
        )

    async def mark_failed_by_id(
        self,
        task_id: uuid.UUID,
        *,
        error_message: str,
        finished_at: datetime | None = None,
        result_data: dict[str, Any] | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Помечает задачу как завершённую с ошибкой по id.

        Сообщение об ошибке обязательно и не может быть пустым.

        Args:
            task_id: Идентификатор фоновой задачи.
            error_message: Сообщение об ошибке.
            finished_at: Дата завершения. Если не передана, используется текущее UTC-время.
            result_data: Дополнительные данные результата или диагностики.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``FAILED``.

        Raises:
            InvalidQueryError: Если сообщение об ошибке пустое.
        """

        task = await self.get_required_by_id(task_id)

        return await self.mark_failed(
            task,
            error_message=error_message,
            finished_at=finished_at,
            result_data=result_data,
            flush=flush,
            refresh=refresh,
        )

    async def release_for_retry(
        self,
        task: BackgroundTask,
        *,
        retry_delay_seconds: int,
        error_message: str | None = None,
        error_code: str | None = None,
        result_data: dict[str, Any] | None = None,
        progress_percent: int = 0,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Возвращает задачу в очередь ``PENDING`` для повторной попытки.

        Метод очищает блокировку, сбрасывает дату завершения, обновляет
        ``scheduled_at`` с учётом задержки повтора и сохраняет диагностические
        данные последней ошибки.

        Args:
            task: ORM-объект фоновой задачи.
            retry_delay_seconds: Задержка перед повторной попыткой в секундах.
            error_message: Сообщение об ошибке предыдущей попытки.
            error_code: Код ошибки предыдущей попытки.
            result_data: Дополнительные данные результата или диагностики.
            progress_percent: Процент выполнения после возврата в очередь.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``PENDING``.

        Raises:
            InvalidQueryError: Если задержка отрицательная или процент выполнения
                некорректен.
        """

        if retry_delay_seconds < 0:
            raise InvalidQueryError(
                "retry_delay_seconds не может быть отрицательным.",
                repository=self.repository_name,
                operation="release_for_retry",
                details={"retry_delay_seconds": retry_delay_seconds},
            )

        self._validate_progress_percent(progress_percent)
        retry_at = self._utc_now() + timedelta(seconds=retry_delay_seconds)

        return await self.update(
            task,
            {
                "status": BackgroundTaskStatus.PENDING,
                "scheduled_at": retry_at,
                "progress_percent": progress_percent,
                "result_data": result_data,
                "error_message": self._normalize_error_message(error_message),
                "error_code": error_code,
                "finished_at": None,
                "locked_by": None,
                "locked_until": None,
            },
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "status",
                "scheduled_at",
                "progress_percent",
                "result_data",
                "error_message",
                "error_code",
                "finished_at",
                "locked_by",
                "locked_until",
            },
        )

    async def release_for_retry_by_id(
        self,
        task_id: uuid.UUID,
        *,
        retry_delay_seconds: int,
        error_message: str | None = None,
        error_code: str | None = None,
        result_data: dict[str, Any] | None = None,
        progress_percent: int = 0,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Возвращает задачу в очередь ``PENDING`` для повторной попытки по ID.

        Args:
            task_id: Идентификатор фоновой задачи.
            retry_delay_seconds: Задержка перед повторной попыткой в секундах.
            error_message: Сообщение об ошибке предыдущей попытки.
            error_code: Код ошибки предыдущей попытки.
            result_data: Дополнительные данные результата или диагностики.
            progress_percent: Процент выполнения после возврата в очередь.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``PENDING``.

        Raises:
            EntityNotFoundError: Если фоновая задача не найдена.
            InvalidQueryError: Если задержка отрицательная или процент выполнения
                некорректен.
        """

        task = await self.get_required_by_id(task_id)
        return await self.release_for_retry(
            task,
            retry_delay_seconds=retry_delay_seconds,
            error_message=error_message,
            error_code=error_code,
            result_data=result_data,
            progress_percent=progress_percent,
            flush=flush,
            refresh=refresh,
        )

    async def mark_cancelled(
        self,
        task: BackgroundTask,
        *,
        finished_at: datetime | None = None,
        reason: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Помечает задачу как отменённую.

        Args:
            task: ORM-объект фоновой задачи.
            finished_at: Дата отмены. Если не передана, используется текущее UTC-время.
            reason: Причина отмены.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``CANCELLED``.
        """

        return await self.update(
            task,
            {
                "status": BackgroundTaskStatus.CANCELLED,
                "error_message": self._normalize_error_message(reason),
                "finished_at": finished_at or self._utc_now(),
            },
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "status",
                "error_message",
                "finished_at",
            },
        )

    async def mark_cancelled_by_id(
        self,
        task_id: uuid.UUID,
        *,
        finished_at: datetime | None = None,
        reason: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Помечает задачу как отменённую по id.

        Args:
            task_id: Идентификатор фоновой задачи.
            finished_at: Дата отмены. Если не передана, используется текущее UTC-время.
            reason: Причина отмены.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая задача со статусом ``CANCELLED``.
        """

        task = await self.get_required_by_id(task_id)

        return await self.mark_cancelled(
            task,
            finished_at=finished_at,
            reason=reason,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Обновление прогресса, результата и ошибки
    # ------------------------------------------------------------------

    async def update_progress(
        self,
        task: BackgroundTask,
        progress_percent: int,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Обновляет процент выполнения фоновой задачи.

        Args:
            task: ORM-объект фоновой задачи.
            progress_percent: Новый процент выполнения от 0 до 100.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.

        Raises:
            InvalidQueryError: Если процент выполнения вне диапазона от 0 до 100.
        """

        self._validate_progress_percent(progress_percent)

        return await self.update(
            task,
            {"progress_percent": progress_percent},
            flush=flush,
            refresh=refresh,
            allowed_fields={"progress_percent"},
        )

    async def update_progress_by_id(
        self,
        task_id: uuid.UUID,
        progress_percent: int,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Обновляет процент выполнения фоновой задачи по id.

        Args:
            task_id: Идентификатор фоновой задачи.
            progress_percent: Новый процент выполнения от 0 до 100.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.

        Raises:
            InvalidQueryError: Если процент выполнения вне диапазона от 0 до 100.
        """

        task = await self.get_required_by_id(task_id)

        return await self.update_progress(
            task,
            progress_percent,
            flush=flush,
            refresh=refresh,
        )

    async def increment_progress(
        self,
        task: BackgroundTask,
        *,
        increment_by: int,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Увеличивает прогресс задачи на указанное значение.

        Итоговое значение не превышает ``100``.

        Args:
            task: ORM-объект фоновой задачи.
            increment_by: Значение, на которое нужно увеличить прогресс.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.
        """

        progress_percent = min(task.progress_percent + increment_by, 100)

        return await self.update_progress(
            task,
            progress_percent,
            flush=flush,
            refresh=refresh,
        )

    async def increment_progress_by_id(
        self,
        task_id: uuid.UUID,
        *,
        increment_by: int,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Увеличивает прогресс задачи на указанное значение по id.

        Итоговое значение не превышает ``100``.

        Args:
            task_id: Идентификатор фоновой задачи.
            increment_by: Значение, на которое нужно увеличить прогресс.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.
        """

        task = await self.get_required_by_id(task_id)

        return await self.increment_progress(
            task,
            increment_by=increment_by,
            flush=flush,
            refresh=refresh,
        )

    async def set_result_data(
        self,
        task: BackgroundTask,
        result_data: dict[str, Any] | None,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Устанавливает данные результата фоновой задачи.

        Args:
            task: ORM-объект фоновой задачи.
            result_data: Данные результата или ``None``.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.
        """

        return await self.update(
            task,
            {"result_data": result_data},
            flush=flush,
            refresh=refresh,
            allowed_fields={"result_data"},
        )

    async def set_result_data_by_id(
        self,
        task_id: uuid.UUID,
        result_data: dict[str, Any] | None,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Устанавливает данные результата фоновой задачи по id.

        Args:
            task_id: Идентификатор фоновой задачи.
            result_data: Данные результата или ``None``.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.
        """

        task = await self.get_required_by_id(task_id)

        return await self.set_result_data(
            task,
            result_data,
            flush=flush,
            refresh=refresh,
        )

    async def set_error_message(
        self,
        task: BackgroundTask,
        error_message: str | None,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Устанавливает сообщение об ошибке фоновой задачи.

        Пустая строка после нормализации сохраняется как ``None``.

        Args:
            task: ORM-объект фоновой задачи.
            error_message: Сообщение об ошибке или ``None``.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.
        """

        return await self.update(
            task,
            {"error_message": self._normalize_error_message(error_message)},
            flush=flush,
            refresh=refresh,
            allowed_fields={"error_message"},
        )

    async def set_error_message_by_id(
        self,
        task_id: uuid.UUID,
        error_message: str | None,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Устанавливает сообщение об ошибке фоновой задачи по id.

        Пустая строка после нормализации сохраняется как ``None``.

        Args:
            task_id: Идентификатор фоновой задачи.
            error_message: Сообщение об ошибке или ``None``.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.
        """

        task = await self.get_required_by_id(task_id)

        return await self.set_error_message(
            task,
            error_message,
            flush=flush,
            refresh=refresh,
        )

    async def clear_error_message(
        self,
        task: BackgroundTask,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """Очищает сообщение об ошибке фоновой задачи.

        Args:
            task: ORM-объект фоновой задачи.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.
        """

        return await self.set_error_message(
            task,
            None,
            flush=flush,
            refresh=refresh,
        )

    async def clear_error_message_by_id(
        self,
        task_id: uuid.UUID,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> BackgroundTask:
        """
        Очищает сообщение об ошибке фоновой задачи по id.

        Args:
            task_id: Идентификатор фоновой задачи.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая фоновая задача.
        """

        task = await self.get_required_by_id(task_id)

        return await self.clear_error_message(
            task,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Массовые операции
    # ------------------------------------------------------------------

    async def cancel_pending_tasks(
        self,
        *,
        task_type: BackgroundTaskType | None = None,
        created_by: uuid.UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        reason: str | None = None,
        finished_at: datetime | None = None,
        flush: bool = True,
    ) -> int:
        """Массово отменяет ожидающие задачи по фильтрам.

        Обновляются только задачи со статусом ``PENDING``.

        Args:
            task_type: Тип задач для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачи.
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            reason: Причина отмены.
            finished_at: Дата отмены. Если не передана, используется текущее UTC-время.
            flush: Выполнить ли ``flush`` после массового обновления.

        Returns:
            Количество отменённых задач.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        conditions = self._build_conditions(
            task_type=task_type,
            status=BackgroundTaskStatus.PENDING,
            created_by=created_by,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )

        return await self._bulk_update(
            conditions=conditions,
            values={
                "status": BackgroundTaskStatus.CANCELLED,
                "error_message": self._normalize_error_message(reason),
                "finished_at": finished_at or self._utc_now(),
            },
            operation="cancel_pending_tasks",
            flush=flush,
        )

    async def mark_stale_running_tasks_failed(
        self,
        *,
        started_before: datetime,
        task_type: BackgroundTaskType | None = None,
        error_message: str = "Task execution timeout",
        flush: bool = True,
    ) -> int:
        """Помечает зависшие выполняющиеся задачи как завершённые с ошибкой.

        Зависшими считаются задачи со статусом ``RUNNING``, которые были запущены
        не позже ``started_before``.

        Args:
            started_before: Верхняя граница даты запуска.
            task_type: Тип задач для фильтрации.
            error_message: Сообщение об ошибке для зависших задач.
            flush: Выполнить ли ``flush`` после массового обновления.

        Returns:
            Количество задач, помеченных как ``FAILED``.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        conditions = self._build_conditions(
            task_type=task_type,
            status=BackgroundTaskStatus.RUNNING,
            started_to=started_before,
        )

        return await self._bulk_update(
            conditions=conditions,
            values={
                "status": BackgroundTaskStatus.FAILED,
                "error_message": self._normalize_error_message(error_message),
                "finished_at": self._utc_now(),
            },
            operation="mark_stale_running_tasks_failed",
            flush=flush,
        )

    async def release_stale_running_tasks(
        self,
        *,
        stale_before: datetime | None = None,
        retry_delay_seconds: int | None = None,
        error_message: str | None = None,
        flush: bool = True,
    ) -> int:
        """Возвращает протухшие ``RUNNING``-задачи обратно в ``PENDING``.

        Протухшими считаются выполняющиеся задачи с истёкшим ``locked_until``.
        Метод очищает поля блокировки и планирует повторный запуск задачи.

        Args:
            stale_before: Момент времени для проверки истечения блокировки.
                Если не передан, используется текущее UTC-время.
            retry_delay_seconds: Дополнительная задержка перед повторным запуском.
            error_message: Сообщение об ошибке, которое нужно сохранить.
            flush: Выполнить ``flush`` после массового обновления.

        Returns:
            Количество обновлённых задач.

        Raises:
            InvalidQueryError: Если задержка повторной попытки отрицательная.
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        current_moment = stale_before or self._utc_now()
        next_schedule = current_moment

        if retry_delay_seconds is not None:
            if retry_delay_seconds < 0:
                raise InvalidQueryError(
                    "retry_delay_seconds не может быть отрицательным.",
                    repository=self.repository_name,
                    operation="release_stale_running_tasks",
                    details={"retry_delay_seconds": retry_delay_seconds},
                )
            next_schedule = current_moment + timedelta(seconds=retry_delay_seconds)

        conditions: list[Any] = [
            BackgroundTask.status == BackgroundTaskStatus.RUNNING,
            BackgroundTask.locked_until.is_not(None),
            BackgroundTask.locked_until < current_moment,
        ]

        values: dict[str, Any] = {
            "status": BackgroundTaskStatus.PENDING,
            "scheduled_at": next_schedule,
            "locked_by": None,
            "locked_until": None,
            "started_at": None,
            "finished_at": None,
        }

        normalized_error = self._normalize_error_message(error_message)
        if normalized_error:
            values["error_message"] = normalized_error

        return await self._bulk_update(
            conditions=conditions,
            values=values,
            operation="release_stale_running_tasks",
            flush=flush,
        )

    async def clear_expired_locks(
        self,
        *,
        stale_before: datetime | None = None,
        retry_delay_seconds: int | None = None,
        error_message: str | None = None,
        flush: bool = True,
    ) -> int:
        """Очищает истёкшие блокировки выполняющихся задач.

        Метод является обёрткой над ``release_stale_running_tasks`` и возвращает
        задачи с истёкшим ``locked_until`` обратно в состояние ``PENDING``.

        Args:
            stale_before: Момент времени для проверки истечения блокировки.
            retry_delay_seconds: Дополнительная задержка перед повторным запуском.
            error_message: Сообщение об ошибке, которое нужно сохранить.
            flush: Выполнить ``flush`` после массового обновления.

        Returns:
            Количество обновлённых задач.

        Raises:
            InvalidQueryError: Если задержка повторной попытки отрицательная.
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        return await self.release_stale_running_tasks(
            stale_before=stale_before,
            retry_delay_seconds=retry_delay_seconds,
            error_message=error_message,
            flush=flush,
        )

    async def delete_finished_tasks(
        self,
        *,
        finished_before: datetime | None = None,
        statuses: Sequence[BackgroundTaskStatus] | None = None,
        task_type: BackgroundTaskType | None = None,
        created_by: uuid.UUID | None = None,
        flush: bool = True,
    ) -> int:
        """Физически удаляет завершённые фоновые задачи.

        По умолчанию удаляются задачи со статусами ``COMPLETED``, ``FAILED``
        и ``CANCELLED``.

        Args:
            finished_before: Удалять только задачи, завершённые не позже указанной даты.
            statuses: Статусы задач для удаления.
            task_type: Тип задач для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачи.
            flush: Выполнить ли ``flush`` после удаления.

        Returns:
            Количество удалённых задач.

        Raises:
            RepositoryError: Если произошла ошибка при удалении.
        """

        checked_statuses = list(
            statuses
            or [
                BackgroundTaskStatus.COMPLETED,
                BackgroundTaskStatus.FAILED,
                BackgroundTaskStatus.CANCELLED,
            ]
        )

        conditions = self._build_conditions(
            task_type=task_type,
            statuses=checked_statuses,
            created_by=created_by,
            finished_to=finished_before,
        )

        try:
            statement = delete(BackgroundTask).where(*conditions)
            result = await self.session.execute(statement)

            if flush:
                await self.flush()

            rowcount = getattr(result, "rowcount", None)
            return int(rowcount or 0)

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="delete_finished_tasks",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="delete_finished_tasks",
                reason=str(exc),
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Подсчёт
    # ------------------------------------------------------------------

    async def count_tasks(
        self,
        *,
        task_type: BackgroundTaskType | None = None,
        task_types: Sequence[BackgroundTaskType] | None = None,
        status: BackgroundTaskStatus | None = None,
        statuses: Sequence[BackgroundTaskStatus] | None = None,
        created_by: uuid.UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        system_only: bool | None = None,
    ) -> int:
        """Возвращает количество фоновых задач с учётом фильтров.

        Args:
            task_type: Один тип задачи для фильтрации.
            task_types: Набор типов задач для фильтрации.
            status: Один статус задачи для фильтрации.
            statuses: Набор статусов задач для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачи.
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            system_only: ``True`` — только системные задачи, ``False`` — только пользовательские.

        Returns:
            Количество фоновых задач.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        conditions = self._build_conditions(
            task_type=task_type,
            task_types=task_types,
            status=status,
            statuses=statuses,
            created_by=created_by,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            system_only=system_only,
        )

        try:
            statement = select(func.count()).select_from(BackgroundTask)

            if conditions:
                statement = statement.where(*conditions)

            result = await self.session.execute(statement)

            return int(result.scalar_one())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count_tasks",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def count_by_status(
        self,
        status: BackgroundTaskStatus,
    ) -> int:
        """Возвращает количество задач с указанным статусом.

        Args:
            status: Статус задач.

        Returns:
            Количество задач с указанным статусом.
        """

        return await self.count(BackgroundTask.status == status)

    async def count_pending_tasks(self) -> int:
        """Возвращает количество ожидающих задач.

        Returns:
            Количество ожидающих задач.
        """

        return await self.count_by_status(BackgroundTaskStatus.PENDING)

    async def count_running_tasks(self) -> int:
        """Возвращает количество выполняющихся задач.

        Returns:
            Количество выполняющихся задач.
        """

        return await self.count_by_status(BackgroundTaskStatus.RUNNING)

    async def count_failed_tasks(self) -> int:
        """Возвращает количество задач с ошибкой.

        Returns:
            Количество задач с ошибкой.
        """

        return await self.count_by_status(BackgroundTaskStatus.FAILED)

    async def count_completed_tasks(self) -> int:
        """Возвращает количество успешно завершённых задач.

        Returns:
            Количество успешно завершённых задач.
        """

        return await self.count_by_status(BackgroundTaskStatus.COMPLETED)

    async def get_status_counts(self) -> dict[BackgroundTaskStatus, int]:
        """Возвращает количество задач по статусам.

        Returns:
            Словарь, где ключ — статус задачи, значение — количество задач.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            statement = select(
                BackgroundTask.status, func.count(BackgroundTask.id)
            ).group_by(BackgroundTask.status)

            result = await self.session.execute(statement)

            return {status: int(count) for status, count in result.all()}

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_status_counts",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def get_type_counts(self) -> dict[BackgroundTaskType, int]:
        """Возвращает количество задач по типам.

        Returns:
            Словарь, где ключ — тип задачи, значение — количество задач.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            statement = select(
                BackgroundTask.task_type, func.count(BackgroundTask.id)
            ).group_by(BackgroundTask.task_type)

            result = await self.session.execute(statement)

            return {task_type: int(count) for task_type, count in result.all()}

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_type_counts",
                reason=str(exc),
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Вспомогательные методы построения условий
    # ------------------------------------------------------------------

    def _build_conditions(
        self,
        *,
        task_type: BackgroundTaskType | None = None,
        task_types: Sequence[BackgroundTaskType] | None = None,
        status: BackgroundTaskStatus | None = None,
        statuses: Sequence[BackgroundTaskStatus] | None = None,
        created_by: uuid.UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
        finished_from: datetime | None = None,
        finished_to: datetime | None = None,
        system_only: bool | None = None,
        result_data_contains: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Формирует SQLAlchemy-условия для фильтрации фоновых задач.

        Args:
            task_type: Один тип задачи для фильтрации.
            task_types: Набор типов задач для фильтрации.
            status: Один статус задачи для фильтрации.
            statuses: Набор статусов задач для фильтрации.
            created_by: Идентификатор пользователя, создавшего задачи.
            related_entity_type: Тип связанной сущности.
            related_entity_id: Идентификатор связанной сущности.
            created_from: Нижняя граница даты создания.
            created_to: Верхняя граница даты создания.
            started_from: Нижняя граница даты запуска.
            started_to: Верхняя граница даты запуска.
            finished_from: Нижняя граница даты завершения.
            finished_to: Верхняя граница даты завершения.
            system_only: Фильтр системных или пользовательских задач.
            result_data_contains: JSON-фрагмент для поиска в ``result_data``.

        Returns:
            Список SQLAlchemy-условий.

        Raises:
            InvalidQueryError: Если периоды или списки фильтров некорректны.
        """

        self._validate_period(
            field_name="created_at",
            date_from=created_from,
            date_to=created_to,
        )
        self._validate_period(
            field_name="started_at",
            date_from=started_from,
            date_to=started_to,
        )
        self._validate_period(
            field_name="finished_at",
            date_from=finished_from,
            date_to=finished_to,
        )

        normalized_task_types = self._normalize_task_types(
            task_type=task_type,
            task_types=task_types,
        )
        normalized_statuses = self._normalize_statuses(
            status=status,
            statuses=statuses,
        )

        conditions: list[Any] = []

        if normalized_task_types:
            if len(normalized_task_types) == 1:
                conditions.append(BackgroundTask.task_type == normalized_task_types[0])
            else:
                conditions.append(BackgroundTask.task_type.in_(normalized_task_types))

        if normalized_statuses:
            if len(normalized_statuses) == 1:
                conditions.append(BackgroundTask.status == normalized_statuses[0])
            else:
                conditions.append(BackgroundTask.status.in_(normalized_statuses))

        if created_by is not None:
            conditions.append(BackgroundTask.created_by == created_by)

        if system_only is True:
            conditions.append(BackgroundTask.created_by.is_(None))
        elif system_only is False:
            conditions.append(BackgroundTask.created_by.is_not(None))

        if related_entity_type is not None:
            conditions.append(
                BackgroundTask.related_entity_type
                == self._normalize_related_entity_type(related_entity_type),
            )

        if related_entity_id is not None:
            conditions.append(BackgroundTask.related_entity_id == related_entity_id)

        if created_from is not None:
            conditions.append(BackgroundTask.created_at >= created_from)

        if created_to is not None:
            conditions.append(BackgroundTask.created_at <= created_to)

        if started_from is not None:
            conditions.append(BackgroundTask.started_at >= started_from)

        if started_to is not None:
            conditions.append(BackgroundTask.started_at <= started_to)

        if finished_from is not None:
            conditions.append(BackgroundTask.finished_at >= finished_from)

        if finished_to is not None:
            conditions.append(BackgroundTask.finished_at <= finished_to)

        if result_data_contains is not None:
            conditions.append(
                BackgroundTask.result_data.contains(result_data_contains),
            )

        return conditions

    def _normalize_task_types(
        self,
        *,
        task_type: BackgroundTaskType | None,
        task_types: Sequence[BackgroundTaskType] | None,
    ) -> list[BackgroundTaskType]:
        """Нормализует фильтр типов фоновых задач.

        Объединяет одиночный ``task_type`` и список ``task_types``, проверяет, что
        переданный список не пустой, и удаляет повторяющиеся значения с сохранением
        исходного порядка.

        Args:
            task_type: Один тип задачи для фильтрации.
            task_types: Последовательность типов задач для фильтрации.

        Returns:
            Список уникальных типов задач.

        Raises:
            InvalidQueryError: Если ``task_types`` передан как пустая последовательность.
        """

        normalized: list[BackgroundTaskType] = []

        if task_type is not None:
            normalized.append(task_type)

        if task_types is not None:
            if len(task_types) == 0:
                raise InvalidQueryError(
                    "Список task_types не должен быть пустым.",
                    repository=self.repository_name,
                    operation="_normalize_task_types",
                    details={
                        "model": self.model_name,
                        "field": "task_types",
                    },
                )

            normalized.extend(task_types)

        unique_task_types: list[BackgroundTaskType] = []

        for item in normalized:
            if item not in unique_task_types:
                unique_task_types.append(item)

        return unique_task_types

    def _normalize_statuses(
        self,
        *,
        status: BackgroundTaskStatus | None,
        statuses: Sequence[BackgroundTaskStatus] | None,
    ) -> list[BackgroundTaskStatus]:
        """Нормализует фильтр статусов фоновых задач.

        Объединяет одиночный ``status`` и список ``statuses``, проверяет, что
        переданный список не пустой, и удаляет повторяющиеся значения с сохранением
        исходного порядка.

        Args:
            status: Один статус задачи для фильтрации.
            statuses: Последовательность статусов задач для фильтрации.

        Returns:
            Список уникальных статусов задач.

        Raises:
            InvalidQueryError: Если ``statuses`` передан как пустая последовательность.
        """

        normalized: list[BackgroundTaskStatus] = []

        if status is not None:
            normalized.append(status)

        if statuses is not None:
            if len(statuses) == 0:
                raise InvalidQueryError(
                    "Список statuses не должен быть пустым.",
                    repository=self.repository_name,
                    operation="_normalize_statuses",
                    details={
                        "model": self.model_name,
                        "field": "statuses",
                    },
                )

            normalized.extend(statuses)

        unique_statuses: list[BackgroundTaskStatus] = []

        for item in normalized:
            if item not in unique_statuses:
                unique_statuses.append(item)

        return unique_statuses

    def _validate_period(
        self,
        *,
        field_name: str,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> None:
        """Проверяет корректность периода фильтрации.

        Если обе границы периода переданы, нижняя граница не должна быть позже
        верхней границы.

        Args:
            field_name: Название поля даты, для которого проверяется период.
            date_from: Нижняя граница периода.
            date_to: Верхняя граница периода.

        Raises:
            InvalidQueryError: Если нижняя граница периода больше верхней.
        """

        if date_from is not None and date_to is not None and date_from > date_to:
            raise InvalidQueryError(
                "Нижняя граница периода не может быть больше верхней.",
                repository=self.repository_name,
                operation="_validate_period",
                details={
                    "model": self.model_name,
                    "field": field_name,
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                },
            )

    def _validate_progress_percent(
        self,
        progress_percent: int,
    ) -> None:
        """Проверяет процент выполнения задачи.

        Args:
            progress_percent: Процент выполнения задачи.

        Raises:
            InvalidQueryError: Если значение не является `int`
                или находится вне диапазона от 0 до 100.
        """

        if not isinstance(progress_percent, int):
            raise InvalidQueryError(
                "Процент выполнения задачи должен быть целым числом.",
                repository=self.repository_name,
                operation="_validate_progress_percent",
                details={
                    "model": self.model_name,
                    "progress_percent": progress_percent,
                    "value_type": type(progress_percent).__name__,
                },
            )

        if progress_percent < 0 or progress_percent > 100:
            raise InvalidQueryError(
                "Процент выполнения задачи должен быть в диапазоне от 0 до 100.",
                repository=self.repository_name,
                operation="_validate_progress_percent",
                details={
                    "model": self.model_name,
                    "progress_percent": progress_percent,
                },
            )

    def _validate_status_timestamps(
        self,
        *,
        status: BackgroundTaskStatus,
        started_at: datetime | None,
        finished_at: datetime | None,
        progress_percent: int,
    ) -> None:
        """Проверяет согласованность статуса, дат и прогресса задачи.

        Args:
            status: Статус задачи.
            started_at: Дата начала выполнения.
            finished_at: Дата завершения.
            progress_percent: Процент выполнения.

        Raises:
            InvalidQueryError: Если статус противоречит датам или прогрессу.
        """

        if status == BackgroundTaskStatus.PENDING:
            if finished_at is not None:
                raise InvalidQueryError(
                    "Ожидающая задача не может иметь finished_at.",
                    repository=self.repository_name,
                    operation="_validate_status_timestamps",
                )

        if status == BackgroundTaskStatus.RUNNING:
            if finished_at is not None:
                raise InvalidQueryError(
                    "Выполняющаяся задача не может иметь finished_at.",
                    repository=self.repository_name,
                    operation="_validate_status_timestamps",
                )

        if status in {
            BackgroundTaskStatus.COMPLETED,
            BackgroundTaskStatus.FAILED,
            BackgroundTaskStatus.CANCELLED,
        }:
            if progress_percent < 0 or progress_percent > 100:
                raise InvalidQueryError(
                    "Завершённая задача должна иметь корректный progress_percent.",
                    repository=self.repository_name,
                    operation="_validate_status_timestamps",
                )

    def _normalize_related_entity_type(
        self,
        related_entity_type: str | None,
    ) -> str | None:
        """Нормализует тип связанной сущности.

        Удаляет пробелы по краям строки. Пустая строка возвращается как ``None``.

        Args:
            related_entity_type: Тип связанной сущности.

        Returns:
            Нормализованный тип связанной сущности или ``None``.

        Raises:
            InvalidQueryError: Если значение превышает допустимую длину.
        """

        if related_entity_type is None:
            return None

        normalized = related_entity_type.strip()

        if not normalized:
            return None

        if len(normalized) > 128:
            raise InvalidQueryError(
                "Тип связанной сущности не должен превышать 128 символов.",
                repository=self.repository_name,
                operation="_normalize_related_entity_type",
                details={
                    "field": "related_entity_type",
                    "length": len(normalized),
                    "max_length": 128,
                },
            )

        return normalized

    def _normalize_error_message(
        self,
        error_message: str | None,
    ) -> str | None:
        """Нормализует сообщение об ошибке.

        Args:
            error_message: Сообщение об ошибке.

        Returns:
            Нормализованное сообщение или ``None``.
        """

        if error_message is None:
            return None

        normalized = error_message.strip()

        return normalized or None

    def _normalize_search_query(
        self,
        query: str | None,
    ) -> str | None:
        """Нормализует поисковую строку.

        Удаляет пробелы по краям строки. Если строка отсутствует или после
        нормализации становится пустой, возвращает ``None``.

        Args:
            query: Исходная поисковая строка.

        Returns:
            Нормализованная поисковая строка или ``None``.
        """

        if query is None:
            return None

        normalized = query.strip()

        return normalized or None

    def _get_order_by(
        self,
        sort_by: TaskSortField,
        sort_direction: SortDirection,
    ) -> Any:
        """Возвращает SQLAlchemy-выражение сортировки фоновых задач.

        Args:
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки: `asc` или `desc`.

        Returns:
            SQLAlchemy-выражение для `order_by`.

        Raises:
            InvalidQueryError: Если поле или направление сортировки недопустимы.
        """

        allowed_fields: dict[str, Any] = {
            "created_at": BackgroundTask.created_at,
            "started_at": BackgroundTask.started_at,
            "finished_at": BackgroundTask.finished_at,
            "updated_at": BackgroundTask.updated_at,
            "progress_percent": BackgroundTask.progress_percent,
            "status": BackgroundTask.status,
            "task_type": BackgroundTask.task_type,
        }

        if sort_by not in allowed_fields:
            raise InvalidQueryError(
                "Недопустимое поле сортировки фоновых задач.",
                repository=self.repository_name,
                operation="_get_order_by",
                details={
                    "sort_by": sort_by,
                    "allowed_fields": list(allowed_fields.keys()),
                },
            )

        if sort_direction not in {"asc", "desc"}:
            raise InvalidQueryError(
                "Недопустимое направление сортировки.",
                repository=self.repository_name,
                operation="_get_order_by",
                details={
                    "sort_direction": sort_direction,
                    "allowed_directions": ["asc", "desc"],
                },
            )

        column = allowed_fields[sort_by]

        if sort_direction == "desc":
            return column.desc().nullslast()

        return column.asc().nullslast()

    async def _bulk_update(
        self,
        *,
        conditions: list[Any],
        values: dict[str, Any],
        operation: str,
        flush: bool,
    ) -> int:
        """Выполняет массовое обновление фоновых задач.

        Args:
            conditions: SQLAlchemy-условия для выбора задач.
            values: Значения для обновления.
            operation: Название операции для сообщений об ошибках.
            flush: Выполнить ли ``flush`` после массового обновления.

        Returns:
            Количество обновлённых задач.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        try:
            statement = update(BackgroundTask).where(*conditions).values(**values)
            result = await self.session.execute(statement)

            if flush:
                await self.flush()

            rowcount = getattr(result, "rowcount", None)
            return int(rowcount or 0)

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation=operation,
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation=operation,
                reason=str(exc),
                cause=exc,
            ) from exc

    def _utc_now(self) -> datetime:
        """Возвращает текущее время в UTC.

        Returns:
            Текущая дата и время с timezone UTC.
        """

        return datetime.now(UTC)
