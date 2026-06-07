"""Юнит-тесты для TasksService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from database import DatabaseError
from database.models.enums import BackgroundTaskStatus, BackgroundTaskType, TaskPriority
from schemas.tasks import (
    BackgroundTaskCancelRequest,
    BackgroundTaskCreate,
    BackgroundTaskProgressUpdate,
    BackgroundTaskQueryParams,
    BackgroundTaskRetryRequest,
)
from services.exceptions import (
    BackgroundTaskServiceError,
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
)
from services.tasks import (
    TasksService,
    _jsonable,
    _limit,
    _matches_extra_query_filters,
    _normalize_datetime,
    _normalize_sort_by,
    _snapshot_uuid,
    _task_snapshot,
    _validate_task_type,
    get_tasks_service,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def make_uow(**repos):
    uow = AsyncMock()
    uow.commit = AsyncMock()
    uow.flush = AsyncMock()
    uow.refresh = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    for name, repo in repos.items():
        setattr(uow, name, repo)
    return uow


def make_factory(uow):
    return MagicMock(return_value=uow)


def make_audit():
    svc = MagicMock()
    svc.log_user_event = AsyncMock()
    svc.log_system_event = AsyncMock()
    svc.log_event = AsyncMock()
    return svc


def make_task_mock(
    task_id=None,
    created_by=None,
    task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
    status=BackgroundTaskStatus.PENDING,
):
    task = MagicMock()
    task.id = task_id or uuid.uuid4()
    task.task_type = task_type
    task.status = status
    task.priority = TaskPriority.NORMAL
    task.created_by = created_by or uuid.uuid4()
    task.related_entity_type = "folder"
    task.related_entity_id = uuid.uuid4()
    task.progress_percent = 0
    task.payload = None
    task.result_data = None
    task.error_message = None
    task.error_code = None
    task.attempts_count = 0
    task.max_attempts = 3
    task.idempotency_key = None
    task.scheduled_at = None
    task.started_at = None
    task.finished_at = None
    task.locked_by = None
    task.locked_until = None
    task.created_at = datetime.now(UTC)
    task.updated_at = datetime.now(UTC)
    task.can_retry = True
    return task


def make_role_mock(code="user"):
    role = MagicMock()
    role.code = code
    return role


def make_user_mock(roles=("user",)):
    user = MagicMock()
    user.roles = [make_role_mock(code) for code in roles]
    return user


def make_users_repo(roles=("user",)):
    repo = AsyncMock()
    repo.get_required_user_by_id = AsyncMock(return_value=make_user_mock(roles))
    return repo


def make_tasks_service(uow, audit_svc=None):
    return TasksService(
        uow_factory=make_factory(uow),
        audit_service=audit_svc or make_audit(),
    )


# ---------------------------------------------------------------------------
# Тесты: create_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_returns_background_task_read():
    """create_task создаёт задачу и возвращает BackgroundTaskRead."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id)

    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(return_value=task)

    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    data = BackgroundTaskCreate(
        task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
        created_by=actor_id,
        related_entity_type="folder",
        related_entity_id=uuid.uuid4(),
    )
    result = await service.create_task(data, actor_id=actor_id)

    assert result is not None
    assert str(result.task_type) == str(BackgroundTaskType.CREATE_FOLDER_ARCHIVE)
    tasks_repo.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_create_task_uses_actor_id_over_data_created_by():
    """create_task использует actor_id, когда он задан, а не data.created_by."""
    actor_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id)

    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(return_value=task)

    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    data = BackgroundTaskCreate(
        task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
        created_by=other_user_id,
        related_entity_type="folder",
        related_entity_id=uuid.uuid4(),
    )
    await service.create_task(data, actor_id=actor_id)

    call_kwargs = tasks_repo.create_task.call_args.kwargs
    assert call_kwargs["created_by"] == actor_id


@pytest.mark.asyncio
async def test_create_system_task_passes_actor_as_none():
    """create_system_task передаёт actor_id=None."""
    task = make_task_mock()

    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(return_value=task)

    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    data = BackgroundTaskCreate(
        task_type=BackgroundTaskType.CLEAN_TRASH,
        created_by=None,
        related_entity_type="trash",
        related_entity_id=None,
    )
    result = await service.create_system_task(data)

    assert result is not None
    # created_by в вызове create_task должен быть data.created_by (None), когда actor_id None
    call_kwargs = tasks_repo.create_task.call_args.kwargs
    assert call_kwargs["created_by"] is None


# ---------------------------------------------------------------------------
# Тесты: get_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_returns_background_task_read_for_owner():
    """get_task возвращает BackgroundTaskRead, когда актор — владелец задачи."""
    actor_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_task_mock(task_id=task_id, created_by=actor_id)

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    roles_repo = AsyncMock()
    roles_repo.get_user_roles = AsyncMock(return_value=[make_role_mock("user")])

    uow = make_uow(tasks=tasks_repo, roles=roles_repo)
    service = make_tasks_service(uow)

    result = await service.get_task(task_id, actor_id=actor_id)

    assert result is not None
    assert str(result.id) == str(task_id)


@pytest.mark.asyncio
async def test_get_task_raises_permission_error_for_non_owner():
    """get_task вызывает PermissionServiceError, когда актор не владелец задачи."""
    actor_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_task_mock(task_id=task_id, created_by=other_user_id)

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)

    roles_repo = AsyncMock()
    roles_repo.get_user_roles = AsyncMock(return_value=[make_role_mock("user")])

    uow = make_uow(tasks=tasks_repo, roles=roles_repo)
    service = make_tasks_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.get_task(task_id, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: cancel_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_task_returns_cancelled_task():
    """cancel_task помечает задачу отменённой и возвращает её."""
    actor_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_task_mock(task_id=task_id, created_by=actor_id, status=BackgroundTaskStatus.PENDING)
    cancelled_task = make_task_mock(task_id=task_id, created_by=actor_id, status=BackgroundTaskStatus.CANCELLED)

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_cancelled = AsyncMock(return_value=cancelled_task)

    roles_repo = AsyncMock()
    roles_repo.get_user_roles = AsyncMock(return_value=[make_role_mock("user")])

    uow = make_uow(tasks=tasks_repo, roles=roles_repo)
    service = make_tasks_service(uow)

    data = BackgroundTaskCancelRequest(reason="User requested cancellation")
    result = await service.cancel_task(task_id, data, actor_id=actor_id)

    assert result is not None
    assert result.status == BackgroundTaskStatus.CANCELLED
    tasks_repo.mark_cancelled.assert_called_once()


# ---------------------------------------------------------------------------
# Тесты: list_tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tasks_returns_page_for_owner():
    """list_tasks возвращает задачи, принадлежащие актору."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id)

    tasks_repo = AsyncMock()
    tasks_repo.search_tasks = AsyncMock(return_value=[task])
    tasks_repo.count_tasks = AsyncMock(return_value=1)

    roles_repo = AsyncMock()
    roles_repo.get_user_roles = AsyncMock(return_value=[make_role_mock("user")])

    uow = make_uow(tasks=tasks_repo, roles=roles_repo)
    service = make_tasks_service(uow)

    params = BackgroundTaskQueryParams()
    result = await service.list_tasks(params, actor_id=actor_id)

    assert result is not None
    assert result.meta.total == 1


@pytest.mark.asyncio
async def test_list_tasks_non_owner_filter_raises_permission_error():
    """list_tasks вызывает PermissionServiceError, когда не-админ фильтрует по другому пользователю."""
    actor_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    roles_repo = AsyncMock()
    roles_repo.get_user_roles = AsyncMock(return_value=[make_role_mock("user")])

    tasks_repo = AsyncMock()

    uow = make_uow(tasks=tasks_repo, roles=roles_repo)
    service = make_tasks_service(uow)

    params = BackgroundTaskQueryParams(created_by=other_user_id)

    with pytest.raises(PermissionServiceError):
        await service.list_tasks(params, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: schedule_folder_archive_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_folder_archive_task_returns_task():
    """schedule_folder_archive_task создаёт и возвращает задачу."""
    actor_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id, task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE)

    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(return_value=task)

    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    result = await service.schedule_folder_archive_task(
        folder_id=folder_id,
        actor_id=actor_id,
    )

    assert result is not None
    assert result.task_type == BackgroundTaskType.CREATE_FOLDER_ARCHIVE


# ---------------------------------------------------------------------------
# Тесты: create_task — валидация и оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_unsupported_type_raises_validation_error():
    """create_task вызывает ValidationServiceError для неподдерживаемого типа задачи."""
    actor_id = uuid.uuid4()
    tasks_repo = AsyncMock()
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    data = BackgroundTaskCreate(
        task_type=BackgroundTaskType.CLEAN_EXPIRED_PUBLIC_LINKS,
        created_by=actor_id,
    )
    with pytest.raises(ValidationServiceError):
        await service.create_task(data, actor_id=actor_id)
    tasks_repo.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_create_task_logs_audit_event():
    """create_task записывает событие аудита BACKGROUND_TASK_CREATED."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id)
    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(return_value=task)
    audit = make_audit()
    audit.log_success = AsyncMock()

    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow, audit_svc=audit)

    data = BackgroundTaskCreate(
        task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
        created_by=actor_id,
    )
    await service.create_task(data, actor_id=actor_id)
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_task_audit_failure_is_swallowed():
    """create_task не пробрасывает сбои аудита."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id)
    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(return_value=task)
    audit = make_audit()
    audit.log_success = AsyncMock(side_effect=RuntimeError("audit down"))

    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow, audit_svc=audit)

    data = BackgroundTaskCreate(
        task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
        created_by=actor_id,
    )
    result = await service.create_task(data, actor_id=actor_id)
    assert result is not None


@pytest.mark.asyncio
async def test_create_task_wraps_database_error():
    """create_task оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(side_effect=DatabaseError("boom"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    data = BackgroundTaskCreate(
        task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
        created_by=actor_id,
    )
    with pytest.raises(ServiceError):
        await service.create_task(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_create_task_wraps_unexpected_error():
    """create_task оборачивает непредвиденные исключения в ServiceError."""
    actor_id = uuid.uuid4()
    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(side_effect=RuntimeError("unexpected"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    data = BackgroundTaskCreate(
        task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
        created_by=actor_id,
    )
    with pytest.raises(ServiceError):
        await service.create_task(data, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: schedule_* wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_trash_cleanup_task_returns_task():
    """schedule_trash_cleanup_task создаёт задачу CLEAN_TRASH."""
    task = make_task_mock(task_type=BackgroundTaskType.CLEAN_TRASH)
    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(return_value=task)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    result = await service.schedule_trash_cleanup_task(
        actor_id=None, payload={"k": "v"}
    )
    assert result.task_type == BackgroundTaskType.CLEAN_TRASH
    assert tasks_repo.create_task.call_args.kwargs["task_type"] == (
        BackgroundTaskType.CLEAN_TRASH
    )


@pytest.mark.asyncio
async def test_schedule_uploads_cleanup_task_returns_task():
    """schedule_uploads_cleanup_task создаёт задачу CLEAN_EXPIRED_UPLOADS."""
    task = make_task_mock(task_type=BackgroundTaskType.CLEAN_EXPIRED_UPLOADS)
    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(return_value=task)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    result = await service.schedule_uploads_cleanup_task(actor_id=uuid.uuid4())
    assert result.task_type == BackgroundTaskType.CLEAN_EXPIRED_UPLOADS


@pytest.mark.asyncio
async def test_schedule_quota_recalculation_task_returns_task():
    """schedule_quota_recalculation_task создаёт задачу RECALCULATE_USER_QUOTA."""
    target_user_id = uuid.uuid4()
    task = make_task_mock(task_type=BackgroundTaskType.RECALCULATE_USER_QUOTA)
    tasks_repo = AsyncMock()
    tasks_repo.create_task = AsyncMock(return_value=task)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    result = await service.schedule_quota_recalculation_task(
        target_user_id=target_user_id, actor_id=None
    )
    assert result.task_type == BackgroundTaskType.RECALCULATE_USER_QUOTA


# ---------------------------------------------------------------------------
# Тесты: get_task — доступ админа + пути ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_allows_admin_for_other_user_task():
    """get_task позволяет админу обращаться к задаче другого пользователя."""
    actor_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_task_mock(task_id=task_id, created_by=other_user_id)

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    users_repo = make_users_repo(roles=("admin",))

    uow = make_uow(tasks=tasks_repo, users=users_repo)
    service = make_tasks_service(uow)

    result = await service.get_task(task_id, actor_id=actor_id)
    assert str(result.id) == str(task_id)


@pytest.mark.asyncio
async def test_get_task_wraps_database_error():
    """get_task оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.get_task(uuid.uuid4(), actor_id=actor_id)


@pytest.mark.asyncio
async def test_get_task_wraps_unexpected_error():
    """get_task оборачивает непредвиденные исключения в ServiceError."""
    actor_id = uuid.uuid4()
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.get_task(uuid.uuid4(), actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: get_task_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_result_returns_result():
    """get_task_result возвращает TaskResultRead для владельца."""
    actor_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = make_task_mock(task_id=task_id, created_by=actor_id)
    task.status = BackgroundTaskStatus.COMPLETED
    task.result_data = {"ok": True}
    task.progress_percent = 100

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    result = await service.get_task_result(task_id, actor_id=actor_id)
    assert str(result.task_id) == str(task_id)
    assert result.result_data == {"ok": True}
    assert result.progress_percent == 100


# ---------------------------------------------------------------------------
# Тесты: list_tasks — админ, фильтры, ошибки
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tasks_admin_can_filter_other_user():
    """list_tasks позволяет админу фильтровать по id другого пользователя."""
    actor_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    task = make_task_mock(created_by=other_user_id)

    tasks_repo = AsyncMock()
    tasks_repo.search_tasks = AsyncMock(return_value=[task])
    tasks_repo.count_tasks = AsyncMock(return_value=1)
    users_repo = make_users_repo(roles=("admin",))

    uow = make_uow(tasks=tasks_repo, users=users_repo)
    service = make_tasks_service(uow)

    params = BackgroundTaskQueryParams(created_by=other_user_id)
    result = await service.list_tasks(params, actor_id=actor_id)
    assert result.meta.total == 1
    assert tasks_repo.search_tasks.call_args.kwargs["created_by"] == other_user_id


@pytest.mark.asyncio
async def test_list_tasks_extra_filter_excludes_task():
    """list_tasks отбрасывает задачи, не прошедшие дополнительные фильтры в памяти (приоритет)."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id)
    task.priority = TaskPriority.LOW

    tasks_repo = AsyncMock()
    tasks_repo.search_tasks = AsyncMock(return_value=[task])
    tasks_repo.count_tasks = AsyncMock(return_value=1)
    users_repo = make_users_repo(roles=("user",))

    uow = make_uow(tasks=tasks_repo, users=users_repo)
    service = make_tasks_service(uow)

    params = BackgroundTaskQueryParams(priority=TaskPriority.HIGH)
    result = await service.list_tasks(params, actor_id=actor_id)
    assert result.meta.count == 0
    assert result.meta.total == 1


@pytest.mark.asyncio
async def test_list_tasks_wraps_database_error():
    """list_tasks оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    tasks_repo = AsyncMock()
    tasks_repo.search_tasks = AsyncMock(side_effect=DatabaseError("db"))
    users_repo = make_users_repo(roles=("user",))
    uow = make_uow(tasks=tasks_repo, users=users_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.list_tasks(BackgroundTaskQueryParams(), actor_id=actor_id)


@pytest.mark.asyncio
async def test_list_tasks_wraps_unexpected_error():
    """list_tasks оборачивает непредвиденные исключения в ServiceError."""
    actor_id = uuid.uuid4()
    tasks_repo = AsyncMock()
    tasks_repo.search_tasks = AsyncMock(side_effect=RuntimeError("x"))
    users_repo = make_users_repo(roles=("user",))
    uow = make_uow(tasks=tasks_repo, users=users_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.list_tasks(BackgroundTaskQueryParams(), actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: cancel_task - errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_task_permission_error_for_non_owner():
    """cancel_task вызывает PermissionServiceError для не-владельца и не-админа."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=uuid.uuid4())
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    users_repo = make_users_repo(roles=("user",))
    uow = make_uow(tasks=tasks_repo, users=users_repo)
    service = make_tasks_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.cancel_task(
            task.id, BackgroundTaskCancelRequest(reason="x"), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_cancel_task_wraps_database_error():
    """cancel_task оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id)
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_cancelled = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.cancel_task(
            task.id, BackgroundTaskCancelRequest(reason="x"), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_cancel_task_wraps_unexpected_error():
    """cancel_task оборачивает непредвиденные исключения в ServiceError."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id)
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_cancelled = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.cancel_task(
            task.id, BackgroundTaskCancelRequest(reason="x"), actor_id=actor_id
        )


# ---------------------------------------------------------------------------
# Тесты: retry_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_task_returns_pending_task():
    """retry_task возвращает завершённую задачу в статус PENDING."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id, status=BackgroundTaskStatus.FAILED)
    retried = make_task_mock(
        task_id=task.id, created_by=actor_id, status=BackgroundTaskStatus.PENDING
    )
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_pending = AsyncMock(return_value=retried)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    result = await service.retry_task(
        task.id, BackgroundTaskRetryRequest(), actor_id=actor_id
    )
    assert result.status == BackgroundTaskStatus.PENDING
    tasks_repo.mark_pending.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_task_reset_attempts_and_priority():
    """retry_task применяет reset_attempts и переопределения приоритета."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id, status=BackgroundTaskStatus.COMPLETED)
    task.attempts_count = 5
    task.can_retry = False
    retried = make_task_mock(
        task_id=task.id, created_by=actor_id, status=BackgroundTaskStatus.PENDING
    )
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_pending = AsyncMock(return_value=retried)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    scheduled = datetime.now(UTC) + timedelta(hours=1)
    data = BackgroundTaskRetryRequest(
        reset_attempts=True, priority=TaskPriority.HIGH, scheduled_at=scheduled
    )
    await service.retry_task(task.id, data, actor_id=actor_id)
    assert task.attempts_count == 0
    assert task.priority == TaskPriority.HIGH
    assert task.scheduled_at == scheduled


@pytest.mark.asyncio
async def test_retry_task_not_finished_raises_validation_error():
    """retry_task вызывает ValidationServiceError, когда задача не завершена."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id, status=BackgroundTaskStatus.RUNNING)
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.retry_task(
            task.id, BackgroundTaskRetryRequest(), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_retry_task_retry_limit_raises_background_task_error():
    """retry_task вызывает BackgroundTaskServiceError, когда попытки исчерпаны."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id, status=BackgroundTaskStatus.FAILED)
    task.can_retry = False
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(BackgroundTaskServiceError):
        await service.retry_task(
            task.id,
            BackgroundTaskRetryRequest(reset_attempts=False),
            actor_id=actor_id,
        )


@pytest.mark.asyncio
async def test_retry_task_wraps_database_error():
    """retry_task оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    task = make_task_mock(created_by=actor_id, status=BackgroundTaskStatus.FAILED)
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_pending = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.retry_task(
            task.id, BackgroundTaskRetryRequest(), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_retry_task_wraps_unexpected_error():
    """retry_task оборачивает непредвиденные исключения в ServiceError."""
    actor_id = uuid.uuid4()
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.retry_task(
            uuid.uuid4(), BackgroundTaskRetryRequest(), actor_id=actor_id
        )


# ---------------------------------------------------------------------------
# Тесты: update_progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_progress_marks_running_when_pending():
    """update_progress помечает задачу PENDING как running и логирует событие запуска."""
    task = make_task_mock(status=BackgroundTaskStatus.PENDING)
    started = make_task_mock(task_id=task.id, created_by=task.created_by,
                             status=BackgroundTaskStatus.RUNNING)
    updated = make_task_mock(task_id=task.id, created_by=task.created_by,
                             status=BackgroundTaskStatus.RUNNING)
    updated.progress_percent = 50

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_running = AsyncMock(return_value=started)
    tasks_repo.update_progress = AsyncMock(return_value=updated)
    audit = make_audit()
    audit.log_success = AsyncMock()
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow, audit_svc=audit)

    data = BackgroundTaskProgressUpdate(
        progress_percent=50, message="halfway", result_data={"partial": 1}
    )
    result = await service.update_progress(task.id, data)
    assert result.progress_percent == 50
    tasks_repo.mark_running.assert_awaited_once()
    audit.log_success.assert_awaited_once()
    assert updated.error_message == "halfway"
    assert updated.result_data == {"partial": 1}


@pytest.mark.asyncio
async def test_update_progress_skips_running_when_not_pending():
    """update_progress не помечает running уже запущенную задачу."""
    task = make_task_mock(status=BackgroundTaskStatus.RUNNING)
    updated = make_task_mock(task_id=task.id, created_by=task.created_by,
                             status=BackgroundTaskStatus.RUNNING)
    updated.progress_percent = 75

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.update_progress = AsyncMock(return_value=updated)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    data = BackgroundTaskProgressUpdate(progress_percent=75)
    result = await service.update_progress(task.id, data)
    assert result.progress_percent == 75
    tasks_repo.mark_running.assert_not_called()


@pytest.mark.asyncio
async def test_update_progress_wraps_database_error():
    """update_progress оборачивает DatabaseError в ServiceError."""
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.update_progress(
            uuid.uuid4(), BackgroundTaskProgressUpdate(progress_percent=10)
        )


@pytest.mark.asyncio
async def test_update_progress_wraps_unexpected_error():
    """update_progress оборачивает непредвиденные исключения в ServiceError."""
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.update_progress(
            uuid.uuid4(), BackgroundTaskProgressUpdate(progress_percent=10)
        )


# ---------------------------------------------------------------------------
# Тесты: mark_task_completed / mark_task_failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_task_completed_returns_result_and_logs():
    """mark_task_completed помечает задачу завершённой и логирует событие аудита."""
    created_by = uuid.uuid4()
    task = make_task_mock(created_by=created_by)
    completed = make_task_mock(task_id=task.id, created_by=created_by,
                               status=BackgroundTaskStatus.COMPLETED)
    completed.result_data = {"done": True}
    completed.progress_percent = 100

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_completed = AsyncMock(return_value=completed)
    audit = make_audit()
    audit.log_success = AsyncMock()
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow, audit_svc=audit)

    result = await service.mark_task_completed(
        task_id=task.id, result_data={"done": True}
    )
    assert result.status == BackgroundTaskStatus.COMPLETED
    assert result.result_data == {"done": True}
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_task_completed_wraps_unexpected_error():
    """mark_task_completed оборачивает непредвиденные исключения в ServiceError."""
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.mark_task_completed(task_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_mark_task_completed_wraps_database_error():
    """mark_task_completed оборачивает DatabaseError в ServiceError."""
    task = make_task_mock()
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_completed = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.mark_task_completed(task_id=task.id)


@pytest.mark.asyncio
async def test_mark_task_failed_returns_result_and_logs():
    """mark_task_failed помечает задачу проваленной и логирует событие аудита."""
    created_by = uuid.uuid4()
    task = make_task_mock(created_by=created_by)
    failed = make_task_mock(task_id=task.id, created_by=created_by,
                            status=BackgroundTaskStatus.FAILED)
    failed.error_message = "boom"

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_failed = AsyncMock(return_value=failed)
    audit = make_audit()
    audit.log_success = AsyncMock()
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow, audit_svc=audit)

    result = await service.mark_task_failed(
        task_id=task.id, error_message="boom", result_data={"trace": "..."}
    )
    assert result.status == BackgroundTaskStatus.FAILED
    assert result.error_message == "boom"
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_task_failed_wraps_database_error():
    """mark_task_failed оборачивает DatabaseError в ServiceError."""
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.mark_task_failed(task_id=uuid.uuid4(), error_message="e")


@pytest.mark.asyncio
async def test_mark_task_failed_wraps_unexpected_error():
    """mark_task_failed оборачивает непредвиденные исключения в ServiceError."""
    task = make_task_mock()
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.mark_failed = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.mark_task_failed(task_id=task.id, error_message="e")


# ---------------------------------------------------------------------------
# Тесты: release_task_for_retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_task_for_retry_returns_result():
    """release_task_for_retry возвращает обновлённый TaskResultRead."""
    task = make_task_mock()
    released = make_task_mock(task_id=task.id, status=BackgroundTaskStatus.PENDING)
    released.error_message = "retrying"
    released.error_code = "E_TMP"

    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.release_for_retry = AsyncMock(return_value=released)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    result = await service.release_task_for_retry(
        task_id=task.id,
        retry_delay_seconds=30,
        error_message="retrying",
        error_code="E_TMP",
        result_data={"x": 1},
        progress_percent=20,
    )
    assert result.error_message == "retrying"
    assert result.error_code == "E_TMP"
    tasks_repo.release_for_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_release_task_for_retry_wraps_unexpected_error():
    """release_task_for_retry оборачивает непредвиденные исключения в ServiceError."""
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.release_task_for_retry(
            task_id=uuid.uuid4(), retry_delay_seconds=10
        )


@pytest.mark.asyncio
async def test_release_task_for_retry_wraps_database_error():
    """release_task_for_retry оборачивает DatabaseError в ServiceError."""
    task = make_task_mock()
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    tasks_repo.release_for_retry = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.release_task_for_retry(
            task_id=task.id, retry_delay_seconds=10
        )


# ---------------------------------------------------------------------------
# Тесты: mark_stale_running_tasks_failed / delete_finished_tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_stale_running_tasks_failed_returns_count():
    """mark_stale_running_tasks_failed возвращает количество из репозитория."""
    tasks_repo = AsyncMock()
    tasks_repo.mark_stale_running_tasks_failed = AsyncMock(return_value=4)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    count = await service.mark_stale_running_tasks_failed(
        started_before=datetime.now(UTC)
    )
    assert count == 4


@pytest.mark.asyncio
async def test_mark_stale_running_tasks_failed_wraps_database_error():
    """mark_stale_running_tasks_failed оборачивает DatabaseError в ServiceError."""
    tasks_repo = AsyncMock()
    tasks_repo.mark_stale_running_tasks_failed = AsyncMock(
        side_effect=DatabaseError("db")
    )
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.mark_stale_running_tasks_failed(
            started_before=datetime.now(UTC)
        )


@pytest.mark.asyncio
async def test_mark_stale_running_tasks_failed_none_count_raises():
    """mark_stale_running_tasks_failed вызывает ошибку, когда репозиторий не возвращает количество."""
    tasks_repo = AsyncMock()
    tasks_repo.mark_stale_running_tasks_failed = AsyncMock(return_value=None)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.mark_stale_running_tasks_failed(
            started_before=datetime.now(UTC)
        )


@pytest.mark.asyncio
async def test_delete_finished_tasks_none_count_raises():
    """delete_finished_tasks вызывает ошибку, когда репозиторий не возвращает количество."""
    tasks_repo = AsyncMock()
    tasks_repo.delete_finished_tasks = AsyncMock(return_value=None)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.delete_finished_tasks()


@pytest.mark.asyncio
async def test_delete_finished_tasks_returns_count():
    """delete_finished_tasks возвращает количество из репозитория."""
    tasks_repo = AsyncMock()
    tasks_repo.delete_finished_tasks = AsyncMock(return_value=7)
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    count = await service.delete_finished_tasks(
        finished_before=datetime.now(UTC),
        statuses=[BackgroundTaskStatus.COMPLETED],
    )
    assert count == 7


@pytest.mark.asyncio
async def test_delete_finished_tasks_wraps_unexpected_error():
    """delete_finished_tasks оборачивает непредвиденные исключения в ServiceError."""
    tasks_repo = AsyncMock()
    tasks_repo.delete_finished_tasks = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(tasks=tasks_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.delete_finished_tasks()


# ---------------------------------------------------------------------------
# Тесты: get_status_counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_counts_admin_uses_global_counts():
    """get_status_counts возвращает глобальные счётчики для админа."""
    actor_id = uuid.uuid4()
    global_counts = {BackgroundTaskStatus.PENDING: 3}
    tasks_repo = AsyncMock()
    tasks_repo.get_status_counts = AsyncMock(return_value=global_counts)
    users_repo = make_users_repo(roles=("admin",))
    uow = make_uow(tasks=tasks_repo, users=users_repo)
    service = make_tasks_service(uow)

    result = await service.get_status_counts(actor_id=actor_id)
    assert result == global_counts
    tasks_repo.get_status_counts.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_status_counts_regular_user_counts_own():
    """get_status_counts считает только задачи актора для обычного пользователя."""
    actor_id = uuid.uuid4()
    tasks_repo = AsyncMock()
    tasks_repo.count_tasks = AsyncMock(return_value=2)
    users_repo = make_users_repo(roles=("user",))
    uow = make_uow(tasks=tasks_repo, users=users_repo)
    service = make_tasks_service(uow)

    result = await service.get_status_counts(actor_id=actor_id)
    assert all(v == 2 for v in result.values())
    assert set(result.keys()) == set(BackgroundTaskStatus)
    for call in tasks_repo.count_tasks.call_args_list:
        assert call.kwargs["created_by"] == actor_id


@pytest.mark.asyncio
async def test_get_status_counts_wraps_database_error():
    """get_status_counts оборачивает DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(users=users_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.get_status_counts(actor_id=actor_id)


@pytest.mark.asyncio
async def test_get_status_counts_wraps_unexpected_error():
    """get_status_counts оборачивает непредвиденные исключения в ServiceError."""
    actor_id = uuid.uuid4()
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(users=users_repo)
    service = make_tasks_service(uow)

    with pytest.raises(ServiceError):
        await service.get_status_counts(actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: module-level helpers
# ---------------------------------------------------------------------------


def test_validate_task_type_accepts_supported():
    """_validate_task_type принимает поддерживаемые типы задач без ошибок."""
    _validate_task_type(
        BackgroundTaskType.CLEAN_TRASH, operation="op"
    )


def test_validate_task_type_rejects_unsupported():
    """_validate_task_type вызывает ошибку для неподдерживаемых типов задач."""
    with pytest.raises(ValidationServiceError):
        _validate_task_type(BackgroundTaskType.CLEAN_EXPIRED_PUBLIC_LINKS, operation="op")


def test_normalize_sort_by_known_and_unknown():
    """_normalize_sort_by нормализует известные поля и откатывается к created_at."""
    assert _normalize_sort_by("  STATUS ") == "status"
    assert _normalize_sort_by("nonexistent") == "created_at"


def test_limit_clamps_bounds():
    """_limit ограничивает значения ниже 1 и выше максимального лимита страницы."""
    assert _limit(0) == 1
    assert _limit(-5) == 1
    assert _limit(10) == 10
    assert _limit(10_000) == 200


def test_matches_extra_query_filters_all_branches():
    """_matches_extra_query_filters задействует каждую ветку фильтра."""
    base = make_task_mock()
    base.priority = TaskPriority.NORMAL
    base.idempotency_key = "key"
    base.locked_by = "worker"
    base.created_at = datetime(2024, 1, 10, tzinfo=UTC)
    base.scheduled_at = datetime(2024, 1, 5, tzinfo=UTC)
    base.locked_until = datetime(2024, 1, 20, tzinfo=UTC)

    # Совпадает со всем.
    assert _matches_extra_query_filters(
        base,
        params=BackgroundTaskQueryParams(
            priority=TaskPriority.NORMAL,
            idempotency_key="key",
            locked_by="worker",
            created_from=datetime(2024, 1, 1, tzinfo=UTC),
            created_to=datetime(2024, 1, 31, tzinfo=UTC),
            scheduled_before=datetime(2024, 1, 6, tzinfo=UTC),
            only_locked=True,
        ),
    )
    # Несовпадение приоритета.
    assert not _matches_extra_query_filters(
        base, params=BackgroundTaskQueryParams(priority=TaskPriority.HIGH)
    )
    # несовпадение idempotency_key.
    assert not _matches_extra_query_filters(
        base, params=BackgroundTaskQueryParams(idempotency_key="other")
    )
    # несовпадение locked_by.
    assert not _matches_extra_query_filters(
        base, params=BackgroundTaskQueryParams(locked_by="other")
    )
    # created_from слишком поздно.
    assert not _matches_extra_query_filters(
        base,
        params=BackgroundTaskQueryParams(
            created_from=datetime(2024, 2, 1, tzinfo=UTC)
        ),
    )
    # created_to слишком рано.
    assert not _matches_extra_query_filters(
        base,
        params=BackgroundTaskQueryParams(
            created_to=datetime(2024, 1, 1, tzinfo=UTC)
        ),
    )
    # scheduled_before, scheduled_at слишком поздно.
    assert not _matches_extra_query_filters(
        base,
        params=BackgroundTaskQueryParams(
            scheduled_before=datetime(2024, 1, 1, tzinfo=UTC)
        ),
    )
    # only_locked True, но блокировки нет.
    unlocked = make_task_mock()
    unlocked.locked_until = None
    assert not _matches_extra_query_filters(
        unlocked, params=BackgroundTaskQueryParams(only_locked=True)
    )
    # only_locked False, но задача заблокирована.
    assert not _matches_extra_query_filters(
        base, params=BackgroundTaskQueryParams(only_locked=False)
    )


def test_matches_extra_query_filters_scheduled_before_no_schedule():
    """Фильтр scheduled_before отбрасывает задачи без scheduled_at."""
    task = make_task_mock()
    task.scheduled_at = None
    assert not _matches_extra_query_filters(
        task,
        params=BackgroundTaskQueryParams(
            scheduled_before=datetime(2024, 1, 1, tzinfo=UTC)
        ),
    )


def test_snapshot_uuid_returns_uuid_or_none():
    """_snapshot_uuid возвращает значение UUID или None для не-UUID полей."""
    value = uuid.uuid4()
    assert _snapshot_uuid({"id": value}, "id") == value
    assert _snapshot_uuid({"id": "not-a-uuid"}, "id") is None
    assert _snapshot_uuid({}, "missing") is None


def test_task_snapshot_collects_fields():
    """_task_snapshot переносит атрибуты ORM в словарь-снимок."""
    task = make_task_mock()
    snapshot = _task_snapshot(task)
    assert snapshot["id"] == task.id
    assert snapshot["task_type"] == task.task_type
    assert snapshot["status"] == task.status


def test_jsonable_handles_various_types():
    """_jsonable сериализует примитивы, UUID, enum, отображения и коллекции."""
    assert _jsonable(None) is None
    assert _jsonable("s") == "s"
    assert _jsonable(3) == 3
    uid = uuid.uuid4()
    assert _jsonable(uid) == str(uid)
    assert _jsonable(BackgroundTaskStatus.PENDING) == BackgroundTaskStatus.PENDING.value
    assert _jsonable(1.5) == 1.5

    import enum

    class _Color(enum.Enum):
        RED = "red"

    assert _jsonable(_Color.RED) == "red"
    assert _jsonable({"a": uid}) == {"a": str(uid)}
    assert _jsonable([uid, 1]) == [str(uid), 1]
    dt = datetime(2024, 1, 1, 12, 0, 0)
    assert _jsonable(dt) == dt.replace(tzinfo=UTC).isoformat()

    class _Weird:
        def __str__(self) -> str:
            return "weird"

    assert _jsonable(_Weird()) == "weird"


def test_normalize_datetime_naive_and_aware():
    """_normalize_datetime добавляет UTC к наивным значениям и преобразует значения с зоной."""
    naive = datetime(2024, 1, 1, 12, 0, 0)
    assert _normalize_datetime(naive).tzinfo == UTC
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert _normalize_datetime(aware) == aware


# ---------------------------------------------------------------------------
# Тесты: get_tasks_service factory
# ---------------------------------------------------------------------------


def test_get_tasks_service_with_dependencies_returns_new_instance():
    """get_tasks_service собирает новый экземпляр, когда переданы зависимости."""
    uow = make_uow()
    svc = get_tasks_service(uow_factory=make_factory(uow), audit_service=make_audit())
    assert isinstance(svc, TasksService)


def test_get_tasks_service_singleton_without_dependencies():
    """get_tasks_service возвращает кешированный синглтон без зависимостей."""
    first = get_tasks_service()
    second = get_tasks_service()
    assert first is second
