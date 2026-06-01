"""Юнит-тесты репозитория фоновых задач (BackgroundTasksRepository)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.exceptions import (
    EntityNotFoundError,
    InvalidQueryError,
    RepositoryError,
)
from database.models.enums import BackgroundTaskStatus, BackgroundTaskType
from database.repositories.tasks import BackgroundTasksRepository


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

def make_session():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.scalar_one = MagicMock(return_value=0)
    result.rowcount = 0
    result.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session, result


def make_repo():
    session, result = make_session()
    return BackgroundTasksRepository(session=session), session, result


def make_task(**kwargs):
    task = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        task_type=BackgroundTaskType.CLEAN_TRASH,
        status=BackgroundTaskStatus.PENDING,
        progress_percent=0,
        created_by=None,
        related_entity_type=None,
        related_entity_id=None,
        error_message=None,
        result_data=None,
        started_at=None,
        finished_at=None,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(task, k, v)
    task.start = MagicMock()
    return task


# ---------------------------------------------------------------------------
# Тесты: get_task_by_id / get_required_task_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_task_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    res = await repo.get_task_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_task_by_id_returns_task_when_found():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    res = await repo.get_task_by_id(task.id)
    assert res is task


@pytest.mark.asyncio
async def test_get_required_task_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_task_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_by_idempotency_key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_idempotency_key_raises_for_empty_key():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.get_by_idempotency_key("  ")


@pytest.mark.asyncio
async def test_get_by_idempotency_key_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_idempotency_key("some-key")
    assert res is None


@pytest.mark.asyncio
async def test_get_by_idempotency_key_returns_task_when_found():
    repo, session, result = make_repo()
    task = make_task()
    result.scalar_one_or_none = MagicMock(return_value=task)
    res = await repo.get_by_idempotency_key("some-key")
    assert res is task


# ---------------------------------------------------------------------------
# Тесты: create_task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_task_raises_for_invalid_progress():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_task(
            task_type=BackgroundTaskType.CLEAN_TRASH,
            progress_percent=150,
        )


@pytest.mark.asyncio
async def test_create_task_success():
    repo, session, result = make_repo()
    task = make_task()
    session.add = MagicMock()
    session.flush = AsyncMock()

    async def fake_create(entity, flush=True, refresh=False):
        return task

    repo.create = fake_create  # type: ignore
    res = await repo.create_task(task_type=BackgroundTaskType.CLEAN_TRASH)
    assert res is task


@pytest.mark.asyncio
async def test_create_system_task_success():
    repo, session, result = make_repo()
    task = make_task()

    async def fake_create(entity, flush=True, refresh=False):
        return task

    repo.create = fake_create  # type: ignore
    res = await repo.create_system_task(task_type=BackgroundTaskType.CLEAN_TRASH)
    assert res is task


@pytest.mark.asyncio
async def test_create_user_task_success():
    repo, session, result = make_repo()
    task = make_task()
    user_id = uuid.uuid4()

    async def fake_create(entity, flush=True, refresh=False):
        return task

    repo.create = fake_create  # type: ignore
    res = await repo.create_user_task(
        task_type=BackgroundTaskType.CLEAN_TRASH,
        created_by=user_id,
    )
    assert res is task


# ---------------------------------------------------------------------------
# Тесты: list_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tasks_returns_empty_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_tasks()
    assert res == []


@pytest.mark.asyncio
async def test_list_tasks_with_status_filter():
    repo, session, result = make_repo()
    task = make_task(status=BackgroundTaskStatus.PENDING)
    result.scalars.return_value.all.return_value = [task]
    res = await repo.list_tasks(status=BackgroundTaskStatus.PENDING)
    assert len(res) == 1


@pytest.mark.asyncio
async def test_list_tasks_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.list_tasks(offset=-1)


# ---------------------------------------------------------------------------
# Тесты: list_user_tasks / list_system_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_tasks_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_user_tasks(uuid.uuid4())
    assert res == []


@pytest.mark.asyncio
async def test_list_system_tasks_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_system_tasks()
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: find_pending_tasks / find_running_tasks / find_unfinished_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_pending_tasks_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_pending_tasks()
    assert res == []


@pytest.mark.asyncio
async def test_find_running_tasks_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_running_tasks()
    assert res == []


@pytest.mark.asyncio
async def test_find_unfinished_tasks_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_unfinished_tasks()
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: update_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_raises_for_invalid_progress():
    repo, session, result = make_repo()
    task = make_task()
    with pytest.raises(InvalidQueryError):
        await repo.update_status(task, BackgroundTaskStatus.RUNNING, progress_percent=200)


@pytest.mark.asyncio
async def test_update_status_success():
    repo, session, result = make_repo()
    task = make_task()

    async def fake_update(entity, values, flush=True, refresh=False, **kw):
        for k, v in values.items():
            setattr(entity, k, v)
        return entity

    repo.update = fake_update  # type: ignore
    res = await repo.update_status(task, BackgroundTaskStatus.RUNNING)
    assert res.status == BackgroundTaskStatus.RUNNING


# ---------------------------------------------------------------------------
# Тесты: update_status_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_status_by_id(uuid.uuid4(), BackgroundTaskStatus.RUNNING)


# ---------------------------------------------------------------------------
# Тесты: mark_running / mark_completed / mark_failed / mark_cancelled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_running_success():
    repo, session, result = make_repo()
    task = make_task()

    async def fake_update(entity, values, flush=True, refresh=False, **kw):
        for k, v in values.items():
            setattr(entity, k, v)
        return entity

    repo.update = fake_update  # type: ignore
    res = await repo.mark_running(task)
    assert res.status == BackgroundTaskStatus.RUNNING


@pytest.mark.asyncio
async def test_mark_completed_success():
    repo, session, result = make_repo()
    task = make_task()

    async def fake_update(entity, values, flush=True, refresh=False, **kw):
        for k, v in values.items():
            setattr(entity, k, v)
        return entity

    repo.update = fake_update  # type: ignore
    res = await repo.mark_completed(task)
    assert res.status == BackgroundTaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_mark_failed_raises_for_empty_message():
    repo, session, result = make_repo()
    task = make_task()
    with pytest.raises(InvalidQueryError):
        await repo.mark_failed(task, error_message="   ")


@pytest.mark.asyncio
async def test_mark_failed_success():
    repo, session, result = make_repo()
    task = make_task()

    async def fake_update(entity, values, flush=True, refresh=False, **kw):
        for k, v in values.items():
            setattr(entity, k, v)
        return entity

    repo.update = fake_update  # type: ignore
    res = await repo.mark_failed(task, error_message="something failed")
    assert res.status == BackgroundTaskStatus.FAILED


@pytest.mark.asyncio
async def test_mark_cancelled_success():
    repo, session, result = make_repo()
    task = make_task()

    async def fake_update(entity, values, flush=True, refresh=False, **kw):
        for k, v in values.items():
            setattr(entity, k, v)
        return entity

    repo.update = fake_update  # type: ignore
    res = await repo.mark_cancelled(task)
    assert res.status == BackgroundTaskStatus.CANCELLED


# ---------------------------------------------------------------------------
# Тесты: update_progress
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_progress_raises_for_invalid_percent():
    repo, session, result = make_repo()
    task = make_task()
    with pytest.raises(InvalidQueryError):
        await repo.update_progress(task, -1)


@pytest.mark.asyncio
async def test_update_progress_success():
    repo, session, result = make_repo()
    task = make_task(progress_percent=0)

    async def fake_update(entity, values, flush=True, refresh=False, **kw):
        for k, v in values.items():
            setattr(entity, k, v)
        return entity

    repo.update = fake_update  # type: ignore
    res = await repo.update_progress(task, 50)
    assert res.progress_percent == 50


# ---------------------------------------------------------------------------
# Тесты: release_for_retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_release_for_retry_raises_for_negative_delay():
    repo, session, result = make_repo()
    task = make_task()
    with pytest.raises(InvalidQueryError):
        await repo.release_for_retry(task, retry_delay_seconds=-1)


@pytest.mark.asyncio
async def test_release_for_retry_success():
    repo, session, result = make_repo()
    task = make_task()

    async def fake_update(entity, values, flush=True, refresh=False, **kw):
        for k, v in values.items():
            setattr(entity, k, v)
        return entity

    repo.update = fake_update  # type: ignore
    res = await repo.release_for_retry(task, retry_delay_seconds=60)
    assert res.status == BackgroundTaskStatus.PENDING


# ---------------------------------------------------------------------------
# Тесты: cancel_pending_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_pending_tasks_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 3
    session.execute = AsyncMock(return_value=result)
    # Подменяем _bulk_update
    async def fake_bulk_update(conditions, values, operation, flush=True):
        return 3

    repo._bulk_update = fake_bulk_update  # type: ignore
    count = await repo.cancel_pending_tasks()
    assert count == 3


# ---------------------------------------------------------------------------
# Тесты: mark_stale_running_tasks_failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_stale_running_tasks_failed_returns_count():
    repo, session, result = make_repo()
    async def fake_bulk_update(conditions, values, operation, flush=True):
        return 2

    repo._bulk_update = fake_bulk_update  # type: ignore
    count = await repo.mark_stale_running_tasks_failed(
        started_before=datetime.now(UTC) - timedelta(hours=1)
    )
    assert count == 2


# ---------------------------------------------------------------------------
# Тесты: release_stale_running_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_release_stale_running_tasks_raises_for_negative_delay():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.release_stale_running_tasks(retry_delay_seconds=-1)


@pytest.mark.asyncio
async def test_release_stale_running_tasks_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 1
    async def fake_bulk_update(conditions, values, operation, flush=True):
        return 1

    repo._bulk_update = fake_bulk_update  # type: ignore
    count = await repo.release_stale_running_tasks()
    assert count == 1


# ---------------------------------------------------------------------------
# Тесты: lock_due_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lock_due_tasks_raises_for_empty_worker_id():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.lock_due_tasks(worker_id="  ", lock_ttl_seconds=30, limit=10)


@pytest.mark.asyncio
async def test_lock_due_tasks_raises_for_zero_ttl():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.lock_due_tasks(worker_id="worker-1", lock_ttl_seconds=0, limit=10)


@pytest.mark.asyncio
async def test_lock_due_tasks_returns_empty_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.lock_due_tasks(worker_id="worker-1", lock_ttl_seconds=30, limit=10)
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: get_related_entity_tasks / get_latest_related_entity_task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_related_entity_tasks_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_related_entity_tasks(
        related_entity_type="File",
        related_entity_id=uuid.uuid4(),
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_latest_related_entity_task_returns_none():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_latest_related_entity_task(
        related_entity_type="File",
        related_entity_id=uuid.uuid4(),
    )
    assert res is None


@pytest.mark.asyncio
async def test_get_latest_related_entity_task_returns_task():
    repo, session, result = make_repo()
    task = make_task()
    result.scalars.return_value.all.return_value = [task]
    res = await repo.get_latest_related_entity_task(
        related_entity_type="File",
        related_entity_id=uuid.uuid4(),
    )
    assert res is task


# ---------------------------------------------------------------------------
# Тесты: search_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_tasks_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_tasks()
    assert res == []


@pytest.mark.asyncio
async def test_search_tasks_with_query():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_tasks(query="upload")
    assert res == []


# ---------------------------------------------------------------------------
# Дополнительные хелперы
# ---------------------------------------------------------------------------

from database.exceptions import DuplicateEntityError  # noqa: E402


def make_integrity_error(sqlstate="23505", constraint="uq_tasks"):
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = constraint
    orig.table_name = "background_tasks"
    orig.column_name = None
    err = IntegrityError("stmt", {}, orig)
    err.orig = orig
    return err


def passthrough_update():
    async def fake_update(entity, values, flush=True, refresh=False, **kw):
        for k, v in values.items():
            setattr(entity, k, v)
        return entity

    return fake_update


def install_update(repo):
    repo.update = passthrough_update()  # type: ignore


# ---------------------------------------------------------------------------
# get_required_task_by_id / get_required_by_id (ветка найдено)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_task_by_id_returns_task():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    res = await repo.get_required_task_by_id(task.id)
    assert res is task


# ---------------------------------------------------------------------------
# list_by_status / list_by_type
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_by_status_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_by_status(BackgroundTaskStatus.PENDING)
    assert res == []


@pytest.mark.asyncio
async def test_list_by_type_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_by_type(BackgroundTaskType.CLEAN_TRASH)
    assert res == []


@pytest.mark.asyncio
async def test_find_pending_tasks_newest_first():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_pending_tasks(oldest_first=False)
    assert res == []


@pytest.mark.asyncio
async def test_find_running_tasks_newest_first():
    repo, session, result = make_repo()
    task = make_task(status=BackgroundTaskStatus.RUNNING)
    result.scalars.return_value.all.return_value = [task]
    res = await repo.find_running_tasks(oldest_first=False)
    assert res == [task]


@pytest.mark.asyncio
async def test_find_finished_tasks_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_finished_tasks(newest_first=False)
    assert res == []


# ---------------------------------------------------------------------------
# list_due_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_due_tasks_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_due_tasks(limit=10)
    assert res == []


@pytest.mark.asyncio
async def test_list_due_tasks_with_task_types_and_now():
    repo, session, result = make_repo()
    task = make_task()
    result.scalars.return_value.all.return_value = [task]
    res = await repo.list_due_tasks(
        limit=5,
        task_types=[BackgroundTaskType.CLEAN_TRASH],
        now=datetime.now(UTC),
    )
    assert res == [task]


@pytest.mark.asyncio
async def test_list_due_tasks_invalid_limit():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_due_tasks(limit=0)


# ---------------------------------------------------------------------------
# lock_due_tasks (блокировка/запуск задач + ветка flush + task_types)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lock_due_tasks_locks_and_starts_tasks():
    repo, session, result = make_repo()
    task = make_task()
    result.scalars.return_value.all.return_value = [task]
    res = await repo.lock_due_tasks(
        worker_id="worker-1",
        lock_ttl_seconds=30,
        limit=10,
        task_types=[BackgroundTaskType.CLEAN_TRASH],
        now=datetime.now(UTC),
    )
    assert res == [task]
    task.start.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_lock_due_tasks_invalid_limit():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.lock_due_tasks(worker_id="w", lock_ttl_seconds=30, limit=-1)


# ---------------------------------------------------------------------------
# update_status со всеми необязательными полями
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_with_all_fields():
    repo, session, result = make_repo()
    task = make_task()
    install_update(repo)
    now = datetime.now(UTC)
    res = await repo.update_status(
        task,
        BackgroundTaskStatus.COMPLETED,
        started_at=now,
        finished_at=now,
        progress_percent=100,
        result_data={"ok": True},
        error_message="  oops  ",
    )
    assert res.status == BackgroundTaskStatus.COMPLETED
    assert res.started_at == now
    assert res.finished_at == now
    assert res.progress_percent == 100
    assert res.result_data == {"ok": True}
    assert res.error_message == "oops"


@pytest.mark.asyncio
async def test_update_status_by_id_success():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.update_status_by_id(task.id, BackgroundTaskStatus.RUNNING)
    assert res.status == BackgroundTaskStatus.RUNNING


# ---------------------------------------------------------------------------
# mark_pending / mark_running / mark_completed / mark_failed / mark_cancelled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_pending_resets_everything():
    repo, session, result = make_repo()
    task = make_task(status=BackgroundTaskStatus.FAILED, progress_percent=50)
    install_update(repo)
    res = await repo.mark_pending(
        task,
        reset_progress=True,
        clear_result=True,
        clear_error=True,
    )
    assert res.status == BackgroundTaskStatus.PENDING
    assert res.progress_percent == 0
    assert res.result_data is None
    assert res.error_message is None


@pytest.mark.asyncio
async def test_mark_running_with_reset_progress():
    repo, session, result = make_repo()
    task = make_task(progress_percent=70)
    install_update(repo)
    res = await repo.mark_running(task, reset_progress=True)
    assert res.status == BackgroundTaskStatus.RUNNING
    assert res.progress_percent == 0


# ---------------------------------------------------------------------------
# обёртки *_by_id (покрывают get_required_by_id + делегирование)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_pending_by_id_success():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.mark_pending_by_id(task.id)
    assert res.status == BackgroundTaskStatus.PENDING


@pytest.mark.asyncio
async def test_mark_running_by_id_success():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.mark_running_by_id(task.id)
    assert res.status == BackgroundTaskStatus.RUNNING


@pytest.mark.asyncio
async def test_mark_completed_by_id_success():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.mark_completed_by_id(task.id, result_data={"x": 1})
    assert res.status == BackgroundTaskStatus.COMPLETED
    assert res.progress_percent == 100


@pytest.mark.asyncio
async def test_mark_failed_by_id_success():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.mark_failed_by_id(task.id, error_message="boom")
    assert res.status == BackgroundTaskStatus.FAILED
    assert res.error_message == "boom"


@pytest.mark.asyncio
async def test_mark_cancelled_by_id_success():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.mark_cancelled_by_id(task.id, reason="user cancelled")
    assert res.status == BackgroundTaskStatus.CANCELLED
    assert res.error_message == "user cancelled"


# ---------------------------------------------------------------------------
# release_for_retry (+ by_id) с диагностикой
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_release_for_retry_raises_for_invalid_progress():
    repo, session, result = make_repo()
    task = make_task()
    with pytest.raises(InvalidQueryError):
        await repo.release_for_retry(task, retry_delay_seconds=10, progress_percent=200)


@pytest.mark.asyncio
async def test_release_for_retry_sets_diagnostics():
    repo, session, result = make_repo()
    task = make_task()
    install_update(repo)
    res = await repo.release_for_retry(
        task,
        retry_delay_seconds=60,
        error_message="timeout",
        error_code="E_TIMEOUT",
        result_data={"attempt": 1},
    )
    assert res.status == BackgroundTaskStatus.PENDING
    assert res.error_message == "timeout"
    assert res.error_code == "E_TIMEOUT"
    assert res.locked_by is None
    assert res.locked_until is None


@pytest.mark.asyncio
async def test_release_for_retry_by_id_success():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.release_for_retry_by_id(task.id, retry_delay_seconds=5)
    assert res.status == BackgroundTaskStatus.PENDING


# ---------------------------------------------------------------------------
# update_progress_by_id / increment_progress (+ by_id, ограничение 100)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_progress_by_id_success():
    repo, session, result = make_repo()
    task = make_task(progress_percent=0)
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.update_progress_by_id(task.id, 42)
    assert res.progress_percent == 42


@pytest.mark.asyncio
async def test_increment_progress_caps_at_100():
    repo, session, result = make_repo()
    task = make_task(progress_percent=90)
    install_update(repo)
    res = await repo.increment_progress(task, increment_by=50)
    assert res.progress_percent == 100


@pytest.mark.asyncio
async def test_increment_progress_by_id_success():
    repo, session, result = make_repo()
    task = make_task(progress_percent=10)
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.increment_progress_by_id(task.id, increment_by=15)
    assert res.progress_percent == 25


# ---------------------------------------------------------------------------
# set_result_data / set_error_message / clear_error_message (+ by_id)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_result_data_success():
    repo, session, result = make_repo()
    task = make_task()
    install_update(repo)
    res = await repo.set_result_data(task, {"k": "v"})
    assert res.result_data == {"k": "v"}


@pytest.mark.asyncio
async def test_set_result_data_by_id_success():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.set_result_data_by_id(task.id, {"k": "v"})
    assert res.result_data == {"k": "v"}


@pytest.mark.asyncio
async def test_set_error_message_normalizes_empty_to_none():
    repo, session, result = make_repo()
    task = make_task()
    install_update(repo)
    res = await repo.set_error_message(task, "   ")
    assert res.error_message is None


@pytest.mark.asyncio
async def test_set_error_message_by_id_success():
    repo, session, result = make_repo()
    task = make_task()
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.set_error_message_by_id(task.id, "broken")
    assert res.error_message == "broken"


@pytest.mark.asyncio
async def test_clear_error_message_success():
    repo, session, result = make_repo()
    task = make_task(error_message="old")
    install_update(repo)
    res = await repo.clear_error_message(task)
    assert res.error_message is None


@pytest.mark.asyncio
async def test_clear_error_message_by_id_success():
    repo, session, result = make_repo()
    task = make_task(error_message="old")
    session.get = AsyncMock(return_value=task)
    install_update(repo)
    res = await repo.clear_error_message_by_id(task.id)
    assert res.error_message is None


# ---------------------------------------------------------------------------
# Массовые операции: реальный путь _bulk_update + маппинг ошибок
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_pending_tasks_real_bulk_update():
    repo, session, result = make_repo()
    result.rowcount = 4
    session.execute = AsyncMock(return_value=result)
    count = await repo.cancel_pending_tasks(reason="shutdown")
    assert count == 4
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_update_integrity_error_maps_to_duplicate():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo.cancel_pending_tasks()


@pytest.mark.asyncio
async def test_bulk_update_sqlalchemy_error_maps_to_repository_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.cancel_pending_tasks()


@pytest.mark.asyncio
async def test_mark_stale_running_tasks_failed_real_bulk():
    repo, session, result = make_repo()
    result.rowcount = 2
    session.execute = AsyncMock(return_value=result)
    count = await repo.mark_stale_running_tasks_failed(
        started_before=datetime.now(UTC) - timedelta(hours=2),
    )
    assert count == 2


@pytest.mark.asyncio
async def test_release_stale_running_tasks_with_delay_and_error():
    repo, session, result = make_repo()
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)
    count = await repo.release_stale_running_tasks(
        retry_delay_seconds=30,
        error_message="stale",
    )
    assert count == 1


@pytest.mark.asyncio
async def test_clear_expired_locks_delegates():
    repo, session, result = make_repo()
    result.rowcount = 5
    session.execute = AsyncMock(return_value=result)
    count = await repo.clear_expired_locks()
    assert count == 5


# ---------------------------------------------------------------------------
# delete_finished_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_finished_tasks_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 7
    session.execute = AsyncMock(return_value=result)
    count = await repo.delete_finished_tasks(
        finished_before=datetime.now(UTC),
        statuses=[BackgroundTaskStatus.COMPLETED],
        task_type=BackgroundTaskType.CLEAN_TRASH,
    )
    assert count == 7
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_finished_tasks_default_statuses():
    repo, session, result = make_repo()
    result.rowcount = 0
    session.execute = AsyncMock(return_value=result)
    count = await repo.delete_finished_tasks()
    assert count == 0


@pytest.mark.asyncio
async def test_delete_finished_tasks_integrity_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23503"))
    with pytest.raises(RepositoryError):
        await repo.delete_finished_tasks()


@pytest.mark.asyncio
async def test_delete_finished_tasks_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.delete_finished_tasks()


# ---------------------------------------------------------------------------
# count_tasks / count_by_status helpers / get_status_counts / get_type_counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_tasks_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=9)
    session.execute = AsyncMock(return_value=result)
    count = await repo.count_tasks(status=BackgroundTaskStatus.PENDING)
    assert count == 9


@pytest.mark.asyncio
async def test_count_tasks_no_conditions():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    session.execute = AsyncMock(return_value=result)
    count = await repo.count_tasks()
    assert count == 3


@pytest.mark.asyncio
async def test_count_tasks_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.count_tasks()


@pytest.mark.asyncio
async def test_count_by_status_helpers():
    repo, session, result = make_repo()

    async def fake_count(*conditions):
        return 11

    repo.count = fake_count  # type: ignore
    assert await repo.count_by_status(BackgroundTaskStatus.PENDING) == 11
    assert await repo.count_pending_tasks() == 11
    assert await repo.count_running_tasks() == 11
    assert await repo.count_failed_tasks() == 11
    assert await repo.count_completed_tasks() == 11


@pytest.mark.asyncio
async def test_get_status_counts_returns_dict():
    repo, session, result = make_repo()
    result.all = MagicMock(
        return_value=[
            (BackgroundTaskStatus.PENDING, 2),
            (BackgroundTaskStatus.RUNNING, 1),
        ]
    )
    session.execute = AsyncMock(return_value=result)
    counts = await repo.get_status_counts()
    assert counts == {
        BackgroundTaskStatus.PENDING: 2,
        BackgroundTaskStatus.RUNNING: 1,
    }


@pytest.mark.asyncio
async def test_get_status_counts_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_status_counts()


@pytest.mark.asyncio
async def test_get_type_counts_returns_dict():
    repo, session, result = make_repo()
    result.all = MagicMock(
        return_value=[(BackgroundTaskType.CLEAN_TRASH, 4)]
    )
    session.execute = AsyncMock(return_value=result)
    counts = await repo.get_type_counts()
    assert counts == {BackgroundTaskType.CLEAN_TRASH: 4}


@pytest.mark.asyncio
async def test_get_type_counts_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_type_counts()


# ---------------------------------------------------------------------------
# _build_conditions: — ветки фильтров, normalization, validation
# ---------------------------------------------------------------------------

def test_build_conditions_many_filters():
    repo, session, result = make_repo()
    conditions = repo._build_conditions(
        task_types=[BackgroundTaskType.CLEAN_TRASH],
        statuses=[BackgroundTaskStatus.PENDING, BackgroundTaskStatus.RUNNING],
        created_by=uuid.uuid4(),
        related_entity_type="File",
        related_entity_id=uuid.uuid4(),
        created_from=datetime.now(UTC) - timedelta(days=1),
        created_to=datetime.now(UTC),
        started_from=datetime.now(UTC) - timedelta(days=1),
        started_to=datetime.now(UTC),
        finished_from=datetime.now(UTC) - timedelta(days=1),
        finished_to=datetime.now(UTC),
        result_data_contains={"k": "v"},
    )
    assert len(conditions) >= 10


def test_build_conditions_multiple_task_types_uses_in():
    repo, session, result = make_repo()
    conditions = repo._build_conditions(
        task_types=[
            BackgroundTaskType.CLEAN_TRASH,
            BackgroundTaskType.CLEAN_EXPIRED_UPLOADS,
        ],
    )
    assert len(conditions) == 1


def test_build_conditions_system_only_true_and_false():
    repo, session, result = make_repo()
    assert repo._build_conditions(system_only=True)
    assert repo._build_conditions(system_only=False)


def test_build_conditions_empty_task_types_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._build_conditions(task_types=[])


def test_build_conditions_empty_statuses_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._build_conditions(statuses=[])


def test_build_conditions_invalid_period_raises():
    repo, session, result = make_repo()
    now = datetime.now(UTC)
    with pytest.raises(InvalidQueryError):
        repo._build_conditions(created_from=now, created_to=now - timedelta(days=1))


def test_normalize_task_types_dedup():
    repo, session, result = make_repo()
    res = repo._normalize_task_types(
        task_type=BackgroundTaskType.CLEAN_TRASH,
        task_types=[BackgroundTaskType.CLEAN_TRASH],
    )
    assert res == [BackgroundTaskType.CLEAN_TRASH]


def test_normalize_statuses_dedup():
    repo, session, result = make_repo()
    res = repo._normalize_statuses(
        status=BackgroundTaskStatus.PENDING,
        statuses=[BackgroundTaskStatus.PENDING, BackgroundTaskStatus.RUNNING],
    )
    assert res == [BackgroundTaskStatus.PENDING, BackgroundTaskStatus.RUNNING]


# ---------------------------------------------------------------------------
# _validate_progress_percent / _validate_status_timestamps
# ---------------------------------------------------------------------------

def test_validate_progress_percent_non_int_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_progress_percent("50")  # type: ignore


def test_validate_status_timestamps_pending_with_finished_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_status_timestamps(
            status=BackgroundTaskStatus.PENDING,
            started_at=None,
            finished_at=datetime.now(UTC),
            progress_percent=0,
        )


def test_validate_status_timestamps_running_with_finished_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_status_timestamps(
            status=BackgroundTaskStatus.RUNNING,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            progress_percent=0,
        )


def test_validate_status_timestamps_completed_bad_progress_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_status_timestamps(
            status=BackgroundTaskStatus.COMPLETED,
            started_at=None,
            finished_at=None,
            progress_percent=200,
        )


def test_validate_status_timestamps_ok():
    repo, session, result = make_repo()
    # Не должно выбрасывать исключений.
    repo._validate_status_timestamps(
        status=BackgroundTaskStatus.RUNNING,
        started_at=datetime.now(UTC),
        finished_at=None,
        progress_percent=50,
    )


# ---------------------------------------------------------------------------
# _normalize_related_entity_type
# ---------------------------------------------------------------------------

def test_normalize_related_entity_type_strips_and_empty_to_none():
    repo, session, result = make_repo()
    assert repo._normalize_related_entity_type("  File  ") == "File"
    assert repo._normalize_related_entity_type("   ") is None
    assert repo._normalize_related_entity_type(None) is None


def test_normalize_related_entity_type_too_long_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_related_entity_type("x" * 129)


# ---------------------------------------------------------------------------
# _get_order_by validation branches
# ---------------------------------------------------------------------------

def test_get_order_by_invalid_field_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_order_by("nope", "asc")  # type: ignore


def test_get_order_by_invalid_direction_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_order_by("created_at", "sideways")  # type: ignore


def test_get_order_by_asc_and_desc():
    repo, session, result = make_repo()
    assert repo._get_order_by("created_at", "asc") is not None
    assert repo._get_order_by("status", "desc") is not None


# ---------------------------------------------------------------------------
# create_task со связанной сущностью + валидация меток времени статуса
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_task_with_related_entity():
    repo, session, result = make_repo()
    task = make_task()

    async def fake_create(entity, flush=True, refresh=False):
        return task

    repo.create = fake_create  # type: ignore
    res = await repo.create_task(
        task_type=BackgroundTaskType.CLEAN_TRASH,
        related_entity_type="  File  ",
        related_entity_id=uuid.uuid4(),
        error_message="  oops  ",
    )
    assert res is task


@pytest.mark.asyncio
async def test_create_task_invalid_status_timestamps():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_task(
            task_type=BackgroundTaskType.CLEAN_TRASH,
            status=BackgroundTaskStatus.PENDING,
            finished_at=datetime.now(UTC),
        )
