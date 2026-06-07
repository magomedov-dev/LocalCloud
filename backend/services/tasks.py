from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal, cast
from uuid import UUID

from core.logging import get_logger
from database import (
    DatabaseError,
    UnitOfWorkFactory,
    create_unit_of_work_factory,
)
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    BackgroundTaskStatus,
    BackgroundTaskType,
    TaskPriority,
)
from schemas.common import PageMeta, PageResponse
from schemas.tasks import (
    BackgroundTaskCancelRequest,
    BackgroundTaskCreate,
    BackgroundTaskListItem,
    BackgroundTaskProgressUpdate,
    BackgroundTaskQueryParams,
    BackgroundTaskRead,
    BackgroundTaskRetryRequest,
    TaskResultRead,
)
from security.permissions import is_admin_user
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    BackgroundTaskServiceError,
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
)

logger = get_logger("services.tasks")

SERVICE_NAME = "tasks"
MAX_PAGE_LIMIT = 200
TASK_SORT_FIELDS: set[str] = {
    "created_at",
    "started_at",
    "finished_at",
    "updated_at",
    "progress_percent",
    "status",
    "task_type",
}


class TasksService:
    """Сервис бизнес-логики для фоновых задач.

    Управляет жизненным циклом BackgroundTask: создает задачи, планирует
    типовые операции, проверяет доступ к задачам, отменяет и перезапускает
    задачи, обновляет прогресс и фиксирует итог выполнения. Значимые операции
    записываются в аудит.

    Attributes:
        uow_factory: Фабрика Unit of Work для работы с базой данных.
        audit_service: Сервис записи событий аудита.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        """Инициализирует сервис фоновых задач.

        Если зависимости не переданы явно, создает их через стандартные фабрики
        и функции получения сервисов.

        Args:
            uow_factory: Фабрика Unit of Work. Если None, создается стандартная
                фабрика.
            audit_service: Сервис аудита. Если None, создается стандартный сервис
                аудита.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory
        )

    async def create_task(
        self,
        data: BackgroundTaskCreate,
        *,
        actor_id: UUID | None,
    ) -> BackgroundTaskRead:
        """Создает фоновую задачу.

        Проверяет, что тип задачи поддерживается сервисом, создает задачу в статусе
        PENDING, заполняет приоритет, payload, настройки повторов, idempotency key
        и время планирования. После создания записывает событие аудита.

        Args:
            data: Данные для создания фоновой задачи.
            actor_id: Идентификатор пользователя, создающего задачу. Если None,
                используется created_by из data.

        Returns:
            Данные созданной фоновой задачи.

        Raises:
            ValidationServiceError: Если тип задачи не поддерживается.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "create_task"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                _validate_task_type(data.task_type, operation=operation)
                created = await uow.tasks.create_task(
                    task_type=data.task_type,
                    created_by=actor_id if actor_id is not None else data.created_by,
                    related_entity_type=data.related_entity_type,
                    related_entity_id=data.related_entity_id,
                    status=BackgroundTaskStatus.PENDING,
                    progress_percent=0,
                    result_data=None,
                    error_message=None,
                    started_at=None,
                    finished_at=None,
                    flush=False,
                    refresh=False,
                )
                created.priority = data.priority
                created.payload = cast(dict[str, Any] | None, _jsonable(data.payload))
                created.error_code = None
                created.attempts_count = 0
                created.max_attempts = data.max_attempts
                created.idempotency_key = data.idempotency_key
                created.scheduled_at = data.scheduled_at
                created.locked_by = None
                created.locked_until = None
                await uow.flush()
                await uow.refresh(created)
                snapshot = _task_snapshot(created)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_event(
                action=AuditAction.BACKGROUND_TASK_CREATED,
                actor_id=actor_id,
                task_snapshot=snapshot,
                message="Фоновая задача была создана.",
            )
            return BackgroundTaskRead.model_validate(snapshot)

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def create_system_task(
        self,
        data: BackgroundTaskCreate,
    ) -> BackgroundTaskRead:
        """Создаёт системную фоновую задачу.

        Это тонкая обёртка над `create_task`, фиксирующая отсутствие `actor_id`.

        Args:
            data: Данные для создания фоновой задачи.

        Returns:
            Данные созданной фоновой задачи.
        """

        return await self.create_task(data, actor_id=None)

    async def schedule_folder_archive_task(
        self,
        *,
        folder_id: UUID,
        actor_id: UUID,
        payload: Mapping[str, Any] | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        idempotency_key: str | None = None,
    ) -> BackgroundTaskRead:
        """Планирует задачу создания архива папки.

        Создает задачу типа CREATE_FOLDER_ARCHIVE, связанную с указанной папкой.

        Args:
            folder_id: Идентификатор папки, для которой нужно создать архив.
            actor_id: Идентификатор пользователя, создающего задачу.
            payload: Дополнительные параметры задачи. Если None, payload не
                задается.
            priority: Приоритет фоновой задачи.
            idempotency_key: Ключ идемпотентности задачи.

        Returns:
            Данные созданной фоновой задачи.

        Raises:
            ServiceError: Если создание задачи завершилось ошибкой.
        """

        return await self.create_task(
            BackgroundTaskCreate(
                task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
                priority=priority,
                created_by=actor_id,
                related_entity_type="folder",
                related_entity_id=folder_id,
                payload=dict(payload) if payload else None,
                idempotency_key=idempotency_key,
            ),
            actor_id=actor_id,
        )

    async def schedule_trash_cleanup_task(
        self,
        *,
        actor_id: UUID | None,
        payload: Mapping[str, Any] | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> BackgroundTaskRead:
        """Планирует задачу очистки корзины.

        Создает задачу типа CLEAN_TRASH.

        Args:
            actor_id: Идентификатор пользователя или системы, создающей задачу.
            payload: Дополнительные параметры задачи.
            priority: Приоритет фоновой задачи.

        Returns:
            Данные созданной фоновой задачи.

        Raises:
            ServiceError: Если создание задачи завершилось ошибкой.
        """

        return await self.create_task(
            BackgroundTaskCreate(
                task_type=BackgroundTaskType.CLEAN_TRASH,
                priority=priority,
                created_by=actor_id,
                related_entity_type="trash",
                related_entity_id=None,
                payload=dict(payload) if payload else None,
            ),
            actor_id=actor_id,
        )

    async def schedule_uploads_cleanup_task(
        self,
        *,
        actor_id: UUID | None,
        payload: Mapping[str, Any] | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> BackgroundTaskRead:
        """Планирует задачу очистки истекших upload-сессий.

        Создает задачу типа CLEAN_EXPIRED_UPLOADS.

        Args:
            actor_id: Идентификатор пользователя или системы, создающей задачу.
            payload: Дополнительные параметры задачи.
            priority: Приоритет фоновой задачи.

        Returns:
            Данные созданной фоновой задачи.

        Raises:
            ServiceError: Если создание задачи завершилось ошибкой.
        """

        return await self.create_task(
            BackgroundTaskCreate(
                task_type=BackgroundTaskType.CLEAN_EXPIRED_UPLOADS,
                priority=priority,
                created_by=actor_id,
                related_entity_type="upload_session",
                related_entity_id=None,
                payload=dict(payload) if payload else None,
            ),
            actor_id=actor_id,
        )

    async def schedule_quota_recalculation_task(
        self,
        *,
        target_user_id: UUID,
        actor_id: UUID | None,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> BackgroundTaskRead:
        """Планирует задачу пересчета квоты пользователя.

        Создает задачу типа RECALCULATE_USER_QUOTA и сохраняет target_user_id
        в payload.

        Args:
            target_user_id: Идентификатор пользователя, чью квоту нужно пересчитать.
            actor_id: Идентификатор пользователя или системы, создающей задачу.
            priority: Приоритет фоновой задачи.

        Returns:
            Данные созданной фоновой задачи.

        Raises:
            ServiceError: Если создание задачи завершилось ошибкой.
        """

        return await self.create_task(
            BackgroundTaskCreate(
                task_type=BackgroundTaskType.RECALCULATE_USER_QUOTA,
                priority=priority,
                created_by=actor_id,
                related_entity_type="user",
                related_entity_id=target_user_id,
                payload={"target_user_id": str(target_user_id)},
            ),
            actor_id=actor_id,
        )

    async def get_task(self, task_id: UUID, *, actor_id: UUID) -> BackgroundTaskRead:
        """Возвращает фоновую задачу по идентификатору.

        Загружает задачу и проверяет, что actor_id является владельцем задачи или
        администратором.

        Args:
            task_id: Идентификатор фоновой задачи.
            actor_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Данные фоновой задачи.

        Raises:
            PermissionServiceError: Если пользователь не имеет доступа к задаче.
            ServiceError: Если задача не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "get_task"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                task = await uow.tasks.get_required_by_id(task_id)
                await self._require_task_access(uow=uow, task=task, actor_id=actor_id)
                snapshot = _task_snapshot(task)
            if snapshot is None:
                raise _empty_result_error(operation)
            return BackgroundTaskRead.model_validate(snapshot)
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def list_tasks(
        self,
        params: BackgroundTaskQueryParams,
        *,
        actor_id: UUID,
    ) -> PageResponse[BackgroundTaskListItem]:
        """Возвращает список фоновых задач.

        Администратор может просматривать задачи других пользователей. Обычный
        пользователь может просматривать только собственные задачи. Результат
        загружается из репозитория с основными фильтрами и дополнительно фильтруется
        по приоритету, idempotency key, lock-полям и диапазонам дат.

        Args:
            params: Параметры фильтрации, сортировки и пагинации задач.
            actor_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Страница фоновых задач и метаданные пагинации.

        Raises:
            PermissionServiceError: Если пользователь пытается просмотреть задачи
                другого пользователя без прав администратора.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_tasks"
        limit = _limit(params.limit)
        offset = max(0, params.offset)
        sort_by = _normalize_sort_by(params.sort_by)
        sort_direction: Literal["asc", "desc"] = "desc" if params.sort_desc else "asc"
        snapshots: list[dict[str, Any]] = []
        total = 0

        try:
            async with self.uow_factory() as uow:
                is_admin = await self._is_admin(uow, actor_id)
                if not is_admin and params.created_by not in (None, actor_id):
                    raise PermissionServiceError(
                        "Пользователь может просматривать только собственные фоновые задачи.",
                        user_id=actor_id,
                        resource_type="background_task",
                        action="list",
                        reason="insufficient_scope",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                created_by = params.created_by if is_admin else actor_id
                tasks = await uow.tasks.search_tasks(
                    query=None,
                    offset=offset,
                    limit=limit,
                    task_type=params.task_type,
                    status=params.status,
                    created_by=created_by,
                    related_entity_type=params.related_entity_type,
                    related_entity_id=params.related_entity_id,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                )
                total = await uow.tasks.count_tasks(
                    task_type=params.task_type,
                    status=params.status,
                    created_by=created_by,
                    related_entity_type=params.related_entity_type,
                    related_entity_id=params.related_entity_id,
                )
                snapshots = [
                    _task_snapshot(task)
                    for task in tasks
                    if _matches_extra_query_filters(task, params=params)
                ]

            items = [
                BackgroundTaskListItem.model_validate(snapshot)
                for snapshot in snapshots
            ]
            return PageResponse(
                items=items,
                meta=PageMeta(
                    total=total,
                    offset=offset,
                    limit=limit,
                    count=len(items),
                ),
            )

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def cancel_task(
        self,
        task_id: UUID,
        data: BackgroundTaskCancelRequest,
        *,
        actor_id: UUID,
    ) -> BackgroundTaskRead:
        """Отменяет фоновую задачу.

        Проверяет доступ пользователя к задаче, переводит задачу в состояние
        CANCELLED и записывает событие аудита.

        Args:
            task_id: Идентификатор отменяемой задачи.
            data: Данные отмены задачи.
            actor_id: Идентификатор пользователя, выполняющего отмену.

        Returns:
            Данные отмененной фоновой задачи.

        Raises:
            PermissionServiceError: Если пользователь не имеет доступа к задаче.
            ServiceError: Если задача не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "cancel_task"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                task = await uow.tasks.get_required_by_id(task_id)
                await self._require_task_access(uow=uow, task=task, actor_id=actor_id)
                cancelled = await uow.tasks.mark_cancelled(
                    task,
                    reason=data.reason,
                    flush=True,
                    refresh=True,
                )
                snapshot = _task_snapshot(cancelled)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_event(
                action=AuditAction.BACKGROUND_TASK_CANCELLED,
                actor_id=actor_id,
                task_snapshot=snapshot,
                message="Фоновая задача была отменена.",
                metadata={"reason": data.reason},
            )
            return BackgroundTaskRead.model_validate(snapshot)

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def retry_task(
        self,
        task_id: UUID,
        data: BackgroundTaskRetryRequest,
        *,
        actor_id: UUID,
    ) -> BackgroundTaskRead:
        """Повторно запускает завершенную фоновую задачу.

        Проверяет доступ пользователя к задаче, убеждается, что задача находится
        в одном из завершенных статусов, проверяет лимит повторов и переводит
        задачу обратно в PENDING. При необходимости сбрасывает attempts_count,
        обновляет приоритет и время планирования.

        Args:
            task_id: Идентификатор задачи для повторного запуска.
            data: Данные повторного запуска задачи.
            actor_id: Идентификатор пользователя, выполняющего операцию.

        Returns:
            Данные задачи, переведенной в PENDING.

        Raises:
            PermissionServiceError: Если пользователь не имеет доступа к задаче.
            ValidationServiceError: Если задача еще не завершена.
            BackgroundTaskServiceError: Если лимит повторов исчерпан и reset_attempts
                не указан.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "retry_task"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                task = await uow.tasks.get_required_by_id(task_id)
                await self._require_task_access(uow=uow, task=task, actor_id=actor_id)
                if task.status not in {
                    BackgroundTaskStatus.FAILED,
                    BackgroundTaskStatus.CANCELLED,
                    BackgroundTaskStatus.COMPLETED,
                }:
                    raise ValidationServiceError(
                        "Только завершенные задания могут быть повторены.",
                        field="status",
                        value=task.status.value,
                        reason="task_not_finished",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                if not task.can_retry and not data.reset_attempts:
                    raise BackgroundTaskServiceError(
                        "Достигнут лимит повторных попыток задания.",
                        task_id=task.id,
                        task_type=task.task_type,
                        status=task.status,
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                if data.reset_attempts:
                    task.attempts_count = 0
                if data.priority is not None:
                    task.priority = data.priority
                task.scheduled_at = data.scheduled_at
                retried = await uow.tasks.mark_pending(
                    task,
                    reset_progress=True,
                    clear_result=False,
                    clear_error=True,
                    flush=True,
                    refresh=True,
                )
                snapshot = _task_snapshot(retried)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)
            return BackgroundTaskRead.model_validate(snapshot)

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def update_progress(
        self,
        task_id: UUID,
        data: BackgroundTaskProgressUpdate,
    ) -> BackgroundTaskRead:
        """Обновляет прогресс фоновой задачи.

        Обновляет progress_percent через репозиторий. Если переданы message или
        result_data, сохраняет их в задаче.

        Args:
            task_id: Идентификатор фоновой задачи.
            data: Данные обновления прогресса.

        Returns:
            Данные обновленной фоновой задачи.

        Raises:
            ServiceError: Если задача не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "update_progress"
        snapshot: dict[str, Any] | None = None
        started_snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                task = await uow.tasks.get_required_by_id(task_id)
                should_mark_started = task.status == BackgroundTaskStatus.PENDING
                if should_mark_started:
                    started = await uow.tasks.mark_running(
                        task,
                        flush=False,
                        refresh=False,
                    )
                    started_snapshot = _task_snapshot(started)
                updated = await uow.tasks.update_progress(
                    task,
                    progress_percent=data.progress_percent,
                    flush=True,
                    refresh=True,
                )
                if data.message is not None:
                    updated.error_message = data.message
                if data.result_data is not None:
                    updated.result_data = cast(
                        dict[str, Any] | None, _jsonable(data.result_data)
                    )
                await uow.flush()
                await uow.refresh(updated)
                snapshot = _task_snapshot(updated)
                await uow.commit()
            if snapshot is None:
                raise _empty_result_error(operation)
            if started_snapshot is not None:
                await self._safe_log_event(
                    action=AuditAction.BACKGROUND_TASK_STARTED,
                    actor_id=_snapshot_uuid(started_snapshot, "created_by"),
                    task_snapshot=started_snapshot,
                    message="Запущена фоновая задача.",
                )
            return BackgroundTaskRead.model_validate(snapshot)
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def mark_task_completed(
        self,
        *,
        task_id: UUID,
        result_data: Mapping[str, Any] | None = None,
    ) -> TaskResultRead:
        """Помечает фоновую задачу как успешно завершенную.

        Переводит задачу в статус COMPLETED, сохраняет result_data и записывает
        событие аудита.

        Args:
            task_id: Идентификатор завершаемой задачи.
            result_data: Данные результата задачи.

        Returns:
            Результат фоновой задачи.

        Raises:
            ServiceError: Если задача не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "mark_task_completed"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                task = await uow.tasks.get_required_by_id(task_id)
                updated = await uow.tasks.mark_completed(
                    task,
                    result_data=cast(
                        dict[str, Any] | None,
                        _jsonable(dict(result_data) if result_data else None),
                    ),
                    flush=True,
                    refresh=True,
                )
                snapshot = _task_snapshot(updated)
                await uow.commit()
            if snapshot is None:
                raise _empty_result_error(operation)
            await self._safe_log_event(
                action=AuditAction.BACKGROUND_TASK_COMPLETED,
                actor_id=snapshot.get("created_by")
                if isinstance(snapshot.get("created_by"), UUID)
                else None,
                task_snapshot=snapshot,
                message="Фоновая задача выполнена.",
            )
            return _task_result(snapshot)
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def mark_task_failed(
        self,
        *,
        task_id: UUID,
        error_message: str,
        result_data: Mapping[str, Any] | None = None,
    ) -> TaskResultRead:
        """Помечает фоновую задачу как завершенную с ошибкой.

        Переводит задачу в статус FAILED, сохраняет сообщение об ошибке,
        опциональные result_data и записывает событие аудита.

        Args:
            task_id: Идентификатор задачи.
            error_message: Сообщение об ошибке выполнения.
            result_data: Дополнительные данные результата или диагностики.

        Returns:
            Результат фоновой задачи.

        Raises:
            ServiceError: Если задача не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "mark_task_failed"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                task = await uow.tasks.get_required_by_id(task_id)
                updated = await uow.tasks.mark_failed(
                    task,
                    error_message=error_message,
                    result_data=cast(
                        dict[str, Any] | None,
                        _jsonable(dict(result_data) if result_data else None),
                    ),
                    flush=True,
                    refresh=True,
                )
                snapshot = _task_snapshot(updated)
                await uow.commit()
            if snapshot is None:
                raise _empty_result_error(operation)
            await self._safe_log_event(
                action=AuditAction.BACKGROUND_TASK_FAILED,
                actor_id=snapshot.get("created_by")
                if isinstance(snapshot.get("created_by"), UUID)
                else None,
                task_snapshot=snapshot,
                message="Фоновая задача не выполнена.",
            )
            return _task_result(snapshot)
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def release_task_for_retry(
        self,
        *,
        task_id: UUID,
        retry_delay_seconds: int,
        error_message: str | None = None,
        error_code: str | None = None,
        result_data: Mapping[str, Any] | None = None,
        progress_percent: int = 0,
    ) -> TaskResultRead:
        """Возвращает задачу в очередь для повторной попытки.

        Используется worker-процессом после неуспешного выполнения, когда задачу
        нужно повторить позже. Метод сохраняет диагностические данные ошибки,
        задаёт задержку перед повтором и возвращает результат обновлённой задачи.

        Args:
            task_id: Идентификатор фоновой задачи.
            retry_delay_seconds: Задержка перед повторной попыткой в секундах.
            error_message: Сообщение об ошибке последней попытки.
            error_code: Машинно-читаемый код ошибки последней попытки.
            result_data: Дополнительные данные результата или диагностики.
            progress_percent: Прогресс, который нужно сохранить перед повтором.

        Returns:
            Результат фоновой задачи после перевода в состояние ожидания повтора.

        Raises:
            ServiceError: Если задача не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "release_task_for_retry"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                task = await uow.tasks.get_required_by_id(task_id)
                released = await uow.tasks.release_for_retry(
                    task,
                    retry_delay_seconds=retry_delay_seconds,
                    error_message=error_message,
                    error_code=error_code,
                    result_data=cast(
                        dict[str, Any] | None,
                        _jsonable(dict(result_data) if result_data else None),
                    ),
                    progress_percent=progress_percent,
                    flush=True,
                    refresh=True,
                )
                snapshot = _task_snapshot(released)
                await uow.commit()
            if snapshot is None:
                raise _empty_result_error(operation)
            return _task_result(snapshot)
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def get_task_result(self, task_id: UUID, *, actor_id: UUID) -> TaskResultRead:
        """Возвращает результат фоновой задачи.

        Сначала получает задачу с проверкой доступа, затем формирует TaskResultRead
        из данных задачи.

        Args:
            task_id: Идентификатор фоновой задачи.
            actor_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Результат задачи с типом, статусом, прогрессом, result_data, ошибкой
            и временными метками выполнения.

        Raises:
            PermissionServiceError: Если пользователь не имеет доступа к задаче.
            ServiceError: Если задача не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        task = await self.get_task(task_id, actor_id=actor_id)
        return TaskResultRead(
            task_id=task.id,
            task_type=task.task_type,
            status=task.status,
            progress_percent=task.progress_percent,
            result_data=task.result_data,
            error_message=task.error_message,
            error_code=task.error_code,
            started_at=task.started_at,
            finished_at=task.finished_at,
        )

    async def mark_stale_running_tasks_failed(
        self,
        *,
        started_before: datetime,
        task_type: BackgroundTaskType | None = None,
        error_message: str = "Task execution timeout",
    ) -> int:
        """Помечает зависшие running-задачи как завершенные с ошибкой.

        Делегирует репозиторию массовое обновление задач, которые были запущены
        раньше указанного времени и все еще считаются выполняющимися.

        Args:
            started_before: Верхняя граница времени запуска задачи.
            task_type: Тип задач для фильтрации. Если None, обрабатываются все
                подходящие типы.
            error_message: Сообщение ошибки, которое будет записано в задачи.

        Returns:
            Количество обновленных задач.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "mark_stale_running_tasks_failed"
        count: int | None = None
        try:
            async with self.uow_factory() as uow:
                count = await uow.tasks.mark_stale_running_tasks_failed(
                    started_before=started_before,
                    task_type=task_type,
                    error_message=error_message,
                    flush=True,
                )
                await uow.commit()
            if count is None:
                raise _empty_result_error(operation)
            return count
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def delete_finished_tasks(
        self,
        *,
        finished_before: datetime | None = None,
        statuses: list[BackgroundTaskStatus] | None = None,
        task_type: BackgroundTaskType | None = None,
        created_by: UUID | None = None,
    ) -> int:
        """Удаляет завершенные фоновые задачи по фильтрам.

        Args:
            finished_before: Удалять задачи, завершенные раньше этой даты.
            statuses: Список статусов задач для удаления. Если None, фильтр по
                статусам определяется репозиторием.
            task_type: Тип задач для фильтрации.
            created_by: Идентификатор создателя задач для фильтрации.

        Returns:
            Количество удаленных задач.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "delete_finished_tasks"
        count: int | None = None
        try:
            async with self.uow_factory() as uow:
                count = await uow.tasks.delete_finished_tasks(
                    finished_before=finished_before,
                    statuses=statuses,
                    task_type=task_type,
                    created_by=created_by,
                    flush=True,
                )
                await uow.commit()
            if count is None:
                raise _empty_result_error(operation)
            return count
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def get_status_counts(
        self, *, actor_id: UUID
    ) -> dict[BackgroundTaskStatus, int]:
        """Возвращает количество задач по статусам.

        Для администратора возвращает глобальную статистику по всем задачам.
        Для обычного пользователя считает только его собственные задачи.

        Args:
            actor_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Словарь, где ключ — статус задачи, а значение — количество задач.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "get_status_counts"
        resolved_counts: dict[BackgroundTaskStatus, int] | None = None
        try:
            async with self.uow_factory() as uow:
                if await self._is_admin(uow, actor_id):
                    resolved_counts = await uow.tasks.get_status_counts()
                else:
                    counts: dict[BackgroundTaskStatus, int] = {
                        status: 0 for status in BackgroundTaskStatus
                    }
                    for status in BackgroundTaskStatus:
                        counts[status] = await uow.tasks.count_tasks(
                            created_by=actor_id,
                            status=status,
                        )
                    resolved_counts = counts
            if resolved_counts is None:
                raise _empty_result_error(operation)
            return resolved_counts
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def _require_task_access(
        self, *, uow: Any, task: Any, actor_id: UUID
    ) -> None:
        """Проверяет доступ пользователя к фоновой задаче.

        Доступ разрешен создателю задачи или администратору.

        Args:
            uow: Unit of Work с репозиторием пользователей.
            task: ORM-модель фоновой задачи.
            actor_id: Идентификатор пользователя, выполняющего операцию.

        Raises:
            PermissionServiceError: Если пользователь не является владельцем задачи
                и не является администратором.
        """

        if task.created_by == actor_id:
            return
        if await self._is_admin(uow, actor_id):
            return
        raise PermissionServiceError(
            "Нет доступа к этой фоновой задаче.",
            user_id=actor_id,
            resource_type="background_task",
            resource_id=task.id,
            action="read",
            reason="not_owner",
            details={"service": SERVICE_NAME, "operation": "_require_task_access"},
        )

    async def _is_admin(self, uow: Any, actor_id: UUID) -> bool:
        """Проверяет, является ли пользователь администратором.

        Args:
            uow: Unit of Work с репозиторием пользователей.
            actor_id: Идентификатор пользователя.

        Returns:
            True, если пользователь является администратором, иначе False.

        Raises:
            ServiceError: Если пользователь не найден или не может быть загружен.
        """

        user = await uow.users.get_required_user_by_id(actor_id)
        return bool(is_admin_user(user))

    async def _safe_log_event(
        self,
        *,
        action: AuditAction,
        actor_id: UUID | None,
        task_snapshot: Mapping[str, Any],
        message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Безопасно записывает событие фоновой задачи в аудит.

        Формирует audit payload из снимка задачи, добавляет дополнительные
        метаданные и записывает событие успешной операции. Ошибки аудита не
        пробрасываются выше.

        Args:
            action: Действие аудита.
            actor_id: Идентификатор пользователя, связанного с событием.
            task_snapshot: Снимок фоновой задачи.
            message: Сообщение события аудита.
            metadata: Дополнительные метаданные события.
        """

        try:
            payload = _audit_payload(task_snapshot)
            if metadata:
                payload.update({str(k): _jsonable(v) for k, v in metadata.items()})
            await self.audit_service.log_success(
                action=action,
                user_id=actor_id,
                entity_type=AuditResourceType.BACKGROUND_TASK.value,
                entity_id=_snapshot_uuid(task_snapshot, "id"),
                resource_type=AuditResourceType.BACKGROUND_TASK,
                message=message,
                metadata=payload,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита фоновой задачи.",
                extra={
                    "action": action.value,
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )


def _validate_task_type(task_type: BackgroundTaskType, *, operation: str) -> None:
    """Проверяет, что тип фоновой задачи поддерживается сервисом.

    Args:
        task_type: Тип фоновой задачи.
        operation: Название операции для контекста ошибок.

    Raises:
        ValidationServiceError: Если тип задачи не поддерживается.
    """

    allowed = {
        BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
        BackgroundTaskType.CLEAN_TRASH,
        BackgroundTaskType.CLEAN_EXPIRED_UPLOADS,
        BackgroundTaskType.RECALCULATE_USER_QUOTA,
    }
    if task_type in allowed:
        return
    raise ValidationServiceError(
        "Неподдерживаемый тип задачи для службы задач.",
        field="task_type",
        value=task_type.value,
        reason="unsupported_task_type",
        details={"service": SERVICE_NAME, "operation": operation},
    )


def _normalize_sort_by(
    value: str,
) -> Literal[
    "created_at",
    "started_at",
    "finished_at",
    "updated_at",
    "progress_percent",
    "status",
    "task_type",
]:
    """Нормализует поле сортировки фоновых задач.

    Если поле сортировки неизвестно, возвращает created_at.

    Args:
        value: Исходное поле сортировки.

    Returns:
        Нормализованное поле сортировки задач.
    """

    normalized = value.strip().lower()
    if normalized not in TASK_SORT_FIELDS:
        return "created_at"
    return cast(
        Literal[
            "created_at",
            "started_at",
            "finished_at",
            "updated_at",
            "progress_percent",
            "status",
            "task_type",
        ],
        normalized,
    )


def _limit(value: int) -> int:
    """Нормализует размер страницы.

    Значения меньше 1 заменяются на 1, значения больше MAX_PAGE_LIMIT
    ограничиваются MAX_PAGE_LIMIT.

    Args:
        value: Запрошенный размер страницы.

    Returns:
        Нормализованный размер страницы.
    """

    if value < 1:
        return 1
    return min(value, MAX_PAGE_LIMIT)


def _matches_extra_query_filters(
    task: Any, *, params: BackgroundTaskQueryParams
) -> bool:
    """Проверяет соответствие задачи дополнительным фильтрам запроса.

    Применяет фильтры по приоритету, idempotency key, locked_by, датам создания,
    scheduled_before и состоянию lock.

    Args:
        task: ORM-модель фоновой задачи.
        params: Параметры запроса списка задач.

    Returns:
        True, если задача соответствует дополнительным фильтрам.
    """

    if params.priority is not None and task.priority != params.priority:
        return False
    if (
        params.idempotency_key is not None
        and task.idempotency_key != params.idempotency_key
    ):
        return False
    if params.locked_by is not None and task.locked_by != params.locked_by:
        return False
    if params.created_from is not None and task.created_at < params.created_from:
        return False
    if params.created_to is not None and task.created_at > params.created_to:
        return False
    if params.scheduled_before is not None:
        if task.scheduled_at is None or task.scheduled_at > params.scheduled_before:
            return False
    if params.only_locked is True and task.locked_until is None:
        return False
    if params.only_locked is False and task.locked_until is not None:
        return False
    return True


def _task_snapshot(task: Any) -> dict[str, Any]:
    """Создает снимок фоновой задачи.

    Args:
        task: ORM-модель фоновой задачи.

    Returns:
        Словарь с идентификатором, типом, статусом, приоритетом, владельцем,
        связанной сущностью, прогрессом, payload, result_data, ошибками,
        попытками, планированием, lock-полями и временными метками.
    """

    return {
        "id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "priority": task.priority,
        "created_by": task.created_by,
        "related_entity_type": task.related_entity_type,
        "related_entity_id": task.related_entity_id,
        "progress_percent": task.progress_percent,
        "payload": task.payload,
        "result_data": task.result_data,
        "error_message": task.error_message,
        "error_code": task.error_code,
        "attempts_count": task.attempts_count,
        "max_attempts": task.max_attempts,
        "idempotency_key": task.idempotency_key,
        "scheduled_at": task.scheduled_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "locked_by": task.locked_by,
        "locked_until": task.locked_until,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _task_result(snapshot: Mapping[str, Any]) -> TaskResultRead:
    """Преобразует снимок задачи в схему результата.

    Args:
        snapshot: Снимок фоновой задачи.

    Returns:
        Результат выполнения фоновой задачи.
    """

    return TaskResultRead(
        task_id=cast(UUID, snapshot["id"]),
        task_type=cast(BackgroundTaskType, snapshot["task_type"]),
        status=cast(BackgroundTaskStatus, snapshot["status"]),
        progress_percent=cast(int, snapshot["progress_percent"]),
        result_data=cast(dict[str, Any] | None, snapshot.get("result_data")),
        error_message=cast(str | None, snapshot.get("error_message")),
        error_code=cast(str | None, snapshot.get("error_code")),
        started_at=cast(datetime | None, snapshot.get("started_at")),
        finished_at=cast(datetime | None, snapshot.get("finished_at")),
    )


def _audit_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует метаданные фоновой задачи для аудита.

    Args:
        snapshot: Снимок фоновой задачи.

    Returns:
        Словарь с JSON-совместимыми метаданными задачи.
    """

    return {
        "task_id": _jsonable(snapshot.get("id")),
        "task_type": _jsonable(snapshot.get("task_type")),
        "status": _jsonable(snapshot.get("status")),
        "priority": _jsonable(snapshot.get("priority")),
        "created_by": _jsonable(snapshot.get("created_by")),
        "related_entity_type": _jsonable(snapshot.get("related_entity_type")),
        "related_entity_id": _jsonable(snapshot.get("related_entity_id")),
        "progress_percent": _jsonable(snapshot.get("progress_percent")),
        "attempts_count": _jsonable(snapshot.get("attempts_count")),
        "max_attempts": _jsonable(snapshot.get("max_attempts")),
    }


def _snapshot_uuid(snapshot: Mapping[str, Any], field: str) -> UUID | None:
    """Возвращает UUID из снимка по имени поля.

    Args:
        snapshot: Снимок данных.
        field: Имя поля, значение которого нужно получить.

    Returns:
        UUID-значение поля или None, если значение отсутствует либо не является
        UUID.
    """

    value = snapshot.get(field)
    return value if isinstance(value, UUID) else None


def _jsonable(value: Any) -> Any:
    """Преобразует значение в JSON-совместимый формат.

    Поддерживает примитивы, UUID, datetime, Enum, Mapping, list, tuple и set.
    Для остальных объектов возвращает строковое представление.

    Args:
        value: Значение для преобразования.

    Returns:
        JSON-совместимое представление значения.
    """

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _normalize_datetime(value).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return str(value)


def _normalize_datetime(value: datetime) -> datetime:
    """Нормализует дату и время к UTC.

    Если значение не содержит timezone, считает его временем UTC. Если timezone
    указан, переводит значение в UTC.

    Args:
        value: Дата и время для нормализации.

    Returns:
        Дата и время с timezone UTC.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _empty_result_error(operation: str) -> ServiceError:
    """Создает ошибку пустого результата сервисной операции.

    Args:
        operation: Название операции, завершившейся без результата.

    Returns:
        Ошибка сервиса с описанием отсутствующего результата.
    """

    return ServiceError(
        "Сервисная операция завершена без полезной нагрузки результата.",
        service=SERVICE_NAME,
        operation=operation,
    )


# Глобальный singleton-экземпляр сервиса фоновых задач.
_tasks_service: TasksService | None = None


def get_tasks_service(
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    audit_service: AuditService | None = None,
) -> TasksService:
    """Возвращает экземпляр сервиса фоновых задач.

    Если передана хотя бы одна зависимость, создает новый экземпляр сервиса
    с указанными зависимостями. Если зависимости не переданы, возвращает
    глобальный singleton-экземпляр, создавая его при первом обращении.

    Args:
        uow_factory: Фабрика Unit of Work для нового экземпляра сервиса.
        audit_service: Сервис аудита для нового экземпляра сервиса.

    Returns:
        Экземпляр TasksService.
    """

    global _tasks_service
    if uow_factory is not None or audit_service is not None:
        return TasksService(uow_factory=uow_factory, audit_service=audit_service)
    if _tasks_service is None:
        _tasks_service = TasksService()
    return _tasks_service
