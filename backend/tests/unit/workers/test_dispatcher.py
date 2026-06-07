"""Unit-тесты для WorkerDispatcher."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.models.enums import BackgroundTaskStatus, BackgroundTaskType
from workers.dispatcher import WorkerDispatcher
from workers.registry import WorkerTaskRegistry
from workers.types import WorkerRuntimeStats, WorkerTaskExecutionResult


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_uow():
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.tasks = AsyncMock()
    uow.tasks.lock_due_tasks = AsyncMock(return_value=[])
    uow.tasks.release_stale_running_tasks = AsyncMock(return_value=0)
    uow.tasks.get_required_by_id = AsyncMock(return_value=MagicMock())
    uow.tasks.update = AsyncMock()
    return uow


def make_context(uow=None):
    if uow is None:
        uow = make_uow()

    ctx = MagicMock()
    ctx.worker_id = "w-001"
    ctx.worker_settings = MagicMock()
    ctx.worker_settings.worker_batch_size = 5
    ctx.worker_settings.worker_task_lock_ttl_seconds = 300
    ctx.worker_settings.worker_stale_task_lock_seconds = 900
    ctx.worker_settings.worker_retry_delay_seconds = 60
    ctx.worker_settings.worker_max_retry_delay_seconds = 3600
    ctx.settings = MagicMock()
    ctx.storage_service = MagicMock()
    ctx.services = MagicMock()
    ctx.uow_factory = MagicMock(return_value=uow)
    return ctx, uow


def make_task(
    status=BackgroundTaskStatus.PENDING,
    attempts=0,
    max_attempts=3,
    task_type=BackgroundTaskType.CLEAN_TRASH,
):
    task = MagicMock()
    task.id = uuid.uuid4()
    task.task_type = task_type
    task.status = status
    task.payload = {}
    task.attempts_count = attempts
    task.max_attempts = max_attempts
    return task


def make_registry():
    return WorkerTaskRegistry()


def make_dispatcher(ctx=None, registry=None):
    if ctx is None:
        ctx, _ = make_context()
    if registry is None:
        registry = make_registry()
    return WorkerDispatcher(context=ctx, registry=registry), ctx


# ---------------------------------------------------------------------------
# run_once — нет задач
# ---------------------------------------------------------------------------

class TestRunOnceNoTasks:
    @pytest.mark.asyncio
    async def test_no_tasks_returns_zero_stats(self) -> None:
        ctx, uow = make_context()
        uow.tasks.lock_due_tasks = AsyncMock(return_value=[])
        dispatcher, _ = make_dispatcher(ctx=ctx)

        stats = await dispatcher.run_once()

        assert stats.fetched_count == 0
        assert stats.completed_count == 0
        assert stats.failed_count == 0
        assert stats.retried_count == 0
        assert stats.skipped_count == 0


# ---------------------------------------------------------------------------
# run_once — успешная задача
# ---------------------------------------------------------------------------

class TestRunOnceSuccessfulTask:
    @pytest.mark.asyncio
    async def test_successful_task_increments_completed_count(self) -> None:
        ctx, uow = make_context()
        task = make_task()
        uow.tasks.lock_due_tasks = AsyncMock(return_value=[task])

        registry = make_registry()
        success_result = WorkerTaskExecutionResult(success=True, progress_percent=100)

        async def handler(context):
            return success_result

        registry.register(BackgroundTaskType.CLEAN_TRASH, handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        stats = await dispatcher.run_once()

        assert stats.fetched_count == 1
        assert stats.completed_count == 1
        assert stats.failed_count == 0


# ---------------------------------------------------------------------------
# run_once — задача с повтором
# ---------------------------------------------------------------------------

class TestRunOnceRetriedTask:
    @pytest.mark.asyncio
    async def test_retry_task_with_remaining_attempts_increments_retried(self) -> None:
        ctx, uow = make_context()
        task = make_task(attempts=0, max_attempts=3)
        uow.tasks.lock_due_tasks = AsyncMock(return_value=[task])

        registry = make_registry()
        retry_result = WorkerTaskExecutionResult(
            success=False, retry=True, error_message="transient error"
        )

        async def handler(context):
            return retry_result

        registry.register(BackgroundTaskType.CLEAN_TRASH, handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        stats = await dispatcher.run_once()

        assert stats.retried_count == 1
        assert stats.failed_count == 0
        assert stats.completed_count == 0


# ---------------------------------------------------------------------------
# run_once — проваленная задача (без повтора)
# ---------------------------------------------------------------------------

class TestRunOnceFailedTask:
    @pytest.mark.asyncio
    async def test_failed_task_no_retry_increments_failed(self) -> None:
        ctx, uow = make_context()
        task = make_task(attempts=2, max_attempts=3)
        uow.tasks.lock_due_tasks = AsyncMock(return_value=[task])

        registry = make_registry()
        fail_result = WorkerTaskExecutionResult(
            success=False, retry=False, error_message="hard failure"
        )

        async def handler(context):
            return fail_result

        registry.register(BackgroundTaskType.CLEAN_TRASH, handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        stats = await dispatcher.run_once()

        assert stats.failed_count == 1
        assert stats.retried_count == 0
        assert stats.completed_count == 0

    @pytest.mark.asyncio
    async def test_retry_task_exhausted_attempts_goes_to_failed(self) -> None:
        ctx, uow = make_context()
        # attempts == max_attempts означает, что повторов больше нет
        task = make_task(attempts=3, max_attempts=3)
        uow.tasks.lock_due_tasks = AsyncMock(return_value=[task])

        registry = make_registry()
        retry_result = WorkerTaskExecutionResult(
            success=False, retry=True, error_message="transient but exhausted"
        )

        async def handler(context):
            return retry_result

        registry.register(BackgroundTaskType.CLEAN_TRASH, handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        stats = await dispatcher.run_once()

        assert stats.failed_count == 1
        assert stats.retried_count == 0


# ---------------------------------------------------------------------------
# run_once — отменённая задача
# ---------------------------------------------------------------------------

class TestRunOnceCancelledTask:
    @pytest.mark.asyncio
    async def test_cancelled_task_increments_skipped(self) -> None:
        ctx, uow = make_context()
        task = make_task(status=BackgroundTaskStatus.CANCELLED)
        uow.tasks.lock_due_tasks = AsyncMock(return_value=[task])

        registry = make_registry()
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        stats = await dispatcher.run_once()

        assert stats.skipped_count == 1
        assert stats.completed_count == 0
        assert stats.failed_count == 0


# ---------------------------------------------------------------------------
# execute_task — обработчик не найден
# ---------------------------------------------------------------------------

class TestExecuteTaskHandlerNotFound:
    @pytest.mark.asyncio
    async def test_missing_handler_returns_failure_result(self) -> None:
        ctx, uow = make_context()
        task = make_task(task_type=BackgroundTaskType.CLEAN_TRASH)
        registry = make_registry()  # пустой реестр — обработчик не зарегистрирован
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        result = await dispatcher.execute_task(task)

        assert result.success is False
        assert result.retry is False
        assert result.error_code == "handler_not_found"


# ---------------------------------------------------------------------------
# execute_task — обработчик выбрасывает исключение
# ---------------------------------------------------------------------------

class TestExecuteTaskHandlerRaisesException:
    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_retry_result(self) -> None:
        ctx, uow = make_context()
        task = make_task(task_type=BackgroundTaskType.CLEAN_TRASH)

        registry = make_registry()

        async def broken_handler(context):
            raise RuntimeError("unexpected crash")

        registry.register(BackgroundTaskType.CLEAN_TRASH, broken_handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        result = await dispatcher.execute_task(task)

        assert result.success is False
        assert result.retry is True
        assert result.error_code == "handler_exception"

    @pytest.mark.asyncio
    async def test_handler_error_returns_failure_result(self) -> None:
        from workers.exceptions import WorkerTaskHandlerError
        ctx, uow = make_context()
        task = make_task(task_type=BackgroundTaskType.CLEAN_TRASH)

        registry = make_registry()

        async def error_handler(context):
            raise WorkerTaskHandlerError("validation failed")

        registry.register(BackgroundTaskType.CLEAN_TRASH, error_handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        result = await dispatcher.execute_task(task)

        assert result.success is False
        assert result.retry is False
        assert result.error_code == "handler_error"


# ---------------------------------------------------------------------------
# fetch_and_lock_tasks
# ---------------------------------------------------------------------------

class TestFetchAndLockTasks:
    @pytest.mark.asyncio
    async def test_calls_lock_due_tasks_with_limit(self) -> None:
        ctx, uow = make_context()
        tasks = [make_task(), make_task()]
        uow.tasks.lock_due_tasks = AsyncMock(return_value=tasks)
        dispatcher, _ = make_dispatcher(ctx=ctx)

        result = await dispatcher.fetch_and_lock_tasks(limit=10)

        assert len(result) == 2
        uow.tasks.lock_due_tasks.assert_called_once_with(
            worker_id="w-001",
            lock_ttl_seconds=300,
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_tasks(self) -> None:
        ctx, uow = make_context()
        uow.tasks.lock_due_tasks = AsyncMock(return_value=[])
        dispatcher, _ = make_dispatcher(ctx=ctx)

        result = await dispatcher.fetch_and_lock_tasks(limit=5)

        assert result == []


# ---------------------------------------------------------------------------
# mark_stale_running_tasks
# ---------------------------------------------------------------------------

class TestMarkStaleRunningTasks:
    @pytest.mark.asyncio
    async def test_calls_release_stale_running_tasks(self) -> None:
        ctx, uow = make_context()
        uow.tasks.release_stale_running_tasks = AsyncMock(return_value=0)
        dispatcher, _ = make_dispatcher(ctx=ctx)

        await dispatcher.mark_stale_running_tasks()

        uow.tasks.release_stale_running_tasks.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_zero_released_count_logged(self) -> None:
        ctx, uow = make_context()
        uow.tasks.release_stale_running_tasks = AsyncMock(return_value=3)
        dispatcher, _ = make_dispatcher(ctx=ctx)

        # Не должно выбрасывать исключение даже при освобождении задач
        await dispatcher.mark_stale_running_tasks()


# ---------------------------------------------------------------------------
# complete_task / fail_task / release_task_for_retry
# ---------------------------------------------------------------------------

class TestCompleteTask:
    @pytest.mark.asyncio
    async def test_complete_task_calls_update(self) -> None:
        ctx, uow = make_context()
        dispatcher, _ = make_dispatcher(ctx=ctx)
        task_id = uuid.uuid4()
        result = WorkerTaskExecutionResult(success=True, progress_percent=100)

        await dispatcher.complete_task(task_id, result)

        uow.tasks.update.assert_called_once()
        call_kwargs = uow.tasks.update.call_args[0]
        assert "status" in call_kwargs[1]
        assert call_kwargs[1]["status"] == BackgroundTaskStatus.COMPLETED


class TestFailTask:
    @pytest.mark.asyncio
    async def test_fail_task_calls_update_with_failed_status(self) -> None:
        ctx, uow = make_context()
        dispatcher, _ = make_dispatcher(ctx=ctx)
        task_id = uuid.uuid4()
        result = WorkerTaskExecutionResult(
            success=False, error_message="hard error", error_code="err"
        )

        await dispatcher.fail_task(task_id, result)

        uow.tasks.update.assert_called_once()
        call_kwargs = uow.tasks.update.call_args[0]
        assert call_kwargs[1]["status"] == BackgroundTaskStatus.FAILED


class TestReleaseTaskForRetry:
    @pytest.mark.asyncio
    async def test_release_for_retry_calls_update_with_pending_status(self) -> None:
        ctx, uow = make_context()
        dispatcher, _ = make_dispatcher(ctx=ctx)
        task_id = uuid.uuid4()
        result = WorkerTaskExecutionResult(
            success=False, retry=True, error_message="transient error"
        )

        await dispatcher.release_task_for_retry(task_id, result)

        uow.tasks.update.assert_called_once()
        call_kwargs = uow.tasks.update.call_args[0]
        assert call_kwargs[1]["status"] == BackgroundTaskStatus.PENDING
