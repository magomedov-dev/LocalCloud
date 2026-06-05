"""Unit-тесты для WorkerDispatcher."""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.models.enums import BackgroundTaskStatus, BackgroundTaskType
from workers.dispatcher import WorkerDispatcher
from workers.registry import WorkerTaskRegistry
from workers.types import WorkerTaskExecutionResult


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
    uow.tasks.get_required_by_id = AsyncMock(
        return_value=MagicMock(attempts_count=1)
    )
    uow.tasks.update = AsyncMock()
    return uow


def make_context(uow=None):
    if uow is None:
        uow = make_uow()

    ctx = MagicMock()
    ctx.worker_id = "w-001"
    ctx.worker_settings = MagicMock()
    ctx.worker_settings.worker_batch_size = 5
    ctx.worker_settings.worker_max_concurrent_tasks = 4
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


# ---------------------------------------------------------------------------
# process_tasks — параллелизм batch-а
# ---------------------------------------------------------------------------

class TestProcessTasksConcurrency:
    @pytest.mark.asyncio
    async def test_respects_max_concurrency_limit(self) -> None:
        ctx, uow = make_context()
        ctx.worker_settings.worker_max_concurrent_tasks = 2
        dispatcher, _ = make_dispatcher(ctx=ctx)

        active = 0
        max_active = 0

        async def fake_execute(task):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)  # имитируем I/O-ожидание
            active -= 1
            return WorkerTaskExecutionResult(success=True, progress_percent=100)

        dispatcher.execute_task = fake_execute
        dispatcher.complete_task = AsyncMock()

        tasks = [make_task() for _ in range(6)]
        outcomes = await dispatcher.process_tasks(tasks)

        assert outcomes == ["completed"] * 6
        # Параллелизм реально используется, но не превышает лимит.
        assert max_active == 2
        assert dispatcher.complete_task.await_count == 6

    @pytest.mark.asyncio
    async def test_concurrency_one_is_sequential(self) -> None:
        ctx, uow = make_context()
        ctx.worker_settings.worker_max_concurrent_tasks = 1
        dispatcher, _ = make_dispatcher(ctx=ctx)

        active = 0
        max_active = 0

        async def fake_execute(task):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.005)
            active -= 1
            return WorkerTaskExecutionResult(success=True, progress_percent=100)

        dispatcher.execute_task = fake_execute
        dispatcher.complete_task = AsyncMock()

        outcomes = await dispatcher.process_tasks([make_task() for _ in range(4)])

        assert outcomes == ["completed"] * 4
        assert max_active == 1

    @pytest.mark.asyncio
    async def test_one_task_failure_does_not_cancel_others(self) -> None:
        ctx, uow = make_context()
        dispatcher, _ = make_dispatcher(ctx=ctx)

        dispatcher.execute_task = AsyncMock(
            return_value=WorkerTaskExecutionResult(success=True, progress_percent=100)
        )

        calls = 0

        async def flaky_complete(task_id, result):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("сбой записи статуса в БД")

        dispatcher.complete_task = flaky_complete

        outcomes = await dispatcher.process_tasks([make_task() for _ in range(3)])

        # Сбой одной задачи не отменяет остальные.
        assert len(outcomes) == 3
        assert outcomes.count("completed") == 2
        assert outcomes.count("failed") == 1

    @pytest.mark.asyncio
    async def test_empty_batch_returns_empty(self) -> None:
        dispatcher, _ = make_dispatcher()
        assert await dispatcher.process_tasks([]) == []

    @pytest.mark.asyncio
    async def test_run_once_aggregates_mixed_batch(self) -> None:
        ctx, uow = make_context()
        dispatcher, _ = make_dispatcher(ctx=ctx)

        cancelled = make_task(status=BackgroundTaskStatus.CANCELLED)
        uow.tasks.lock_due_tasks = AsyncMock(
            return_value=[make_task(), make_task(), cancelled]
        )
        dispatcher.execute_task = AsyncMock(
            return_value=WorkerTaskExecutionResult(success=True, progress_percent=100)
        )
        dispatcher.complete_task = AsyncMock()

        stats = await dispatcher.run_once()

        assert stats.fetched_count == 3
        assert stats.completed_count == 2
        assert stats.skipped_count == 1
        assert dispatcher.execute_task.await_count == 2  # отменённая не исполняется


# ---------------------------------------------------------------------------
# Экспоненциальный backoff повторных попыток
# ---------------------------------------------------------------------------

class TestRetryBackoff:
    def test_first_retry_uses_base_delay(self) -> None:
        dispatcher, _ = make_dispatcher()
        # base=60, max=3600 (см. make_context).
        assert dispatcher._compute_retry_delay_seconds(1) == 60

    def test_delay_grows_exponentially(self) -> None:
        dispatcher, _ = make_dispatcher()
        assert dispatcher._compute_retry_delay_seconds(2) == 120
        assert dispatcher._compute_retry_delay_seconds(3) == 240
        assert dispatcher._compute_retry_delay_seconds(4) == 480

    def test_delay_capped_at_max(self) -> None:
        dispatcher, _ = make_dispatcher()
        # 60 * 2^(10-1) = 30720 > 3600 → потолок.
        assert dispatcher._compute_retry_delay_seconds(10) == 3600

    def test_zero_attempts_uses_base(self) -> None:
        dispatcher, _ = make_dispatcher()
        assert dispatcher._compute_retry_delay_seconds(0) == 60

    @pytest.mark.asyncio
    async def test_release_schedules_with_backoff(self) -> None:
        ctx, uow = make_context()
        uow.tasks.get_required_by_id = AsyncMock(
            return_value=MagicMock(attempts_count=3)
        )
        dispatcher, _ = make_dispatcher(ctx=ctx)

        before = datetime.now(UTC)
        await dispatcher.release_task_for_retry(
            uuid.uuid4(),
            WorkerTaskExecutionResult(success=False, retry=True),
        )

        values = uow.tasks.update.call_args[0][1]
        assert values["status"] == BackgroundTaskStatus.PENDING
        delay = (values["scheduled_at"] - before).total_seconds()
        # attempts_count=3 → 60 * 2^2 = 240 c.
        assert 235 <= delay <= 250


# ---------------------------------------------------------------------------
# process_task — финализация провала задачи превью
# ---------------------------------------------------------------------------

class TestFinalizeTerminalFailure:
    @pytest.mark.asyncio
    async def test_failed_preview_task_finalizes_file_status(self, monkeypatch) -> None:
        """Финальный провал задачи превью помечает превью файла FAILED."""
        from workers import dispatcher as dispatcher_module

        finalize = AsyncMock(return_value=True)
        monkeypatch.setattr(
            dispatcher_module, "finalize_failed_preview_task", finalize
        )

        ctx, uow = make_context()
        payload = {"file_id": str(uuid.uuid4())}
        task = make_task(task_type=BackgroundTaskType.GENERATE_FILE_PREVIEW)
        task.payload = payload

        registry = make_registry()

        async def failing_handler(context):
            return WorkerTaskExecutionResult(
                success=False,
                progress_percent=0,
                result_data=None,
                error_message="storage down",
                error_code="storage_error",
                retry=False,
            )

        registry.register(BackgroundTaskType.GENERATE_FILE_PREVIEW, failing_handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        outcome = await dispatcher.process_task(task)

        assert outcome == "failed"
        finalize.assert_awaited_once_with(
            uow_factory=ctx.uow_factory, payload=payload
        )

    @pytest.mark.asyncio
    async def test_retry_exhausted_preview_task_finalizes(self, monkeypatch) -> None:
        """Исчерпание попыток retry тоже приводит к финализации статуса файла."""
        from workers import dispatcher as dispatcher_module

        finalize = AsyncMock(return_value=True)
        monkeypatch.setattr(
            dispatcher_module, "finalize_failed_preview_task", finalize
        )

        ctx, uow = make_context()
        task = make_task(
            task_type=BackgroundTaskType.GENERATE_FILE_PREVIEW,
            attempts=3,
            max_attempts=3,
        )

        registry = make_registry()

        async def retrying_handler(context):
            return WorkerTaskExecutionResult(
                success=False,
                progress_percent=0,
                result_data=None,
                error_message="temporary",
                error_code="temporary_unavailable",
                retry=True,
            )

        registry.register(BackgroundTaskType.GENERATE_FILE_PREVIEW, retrying_handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        outcome = await dispatcher.process_task(task)

        assert outcome == "failed"
        finalize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retried_preview_task_not_finalized(self, monkeypatch) -> None:
        """Пока остаются попытки, файл не помечается FAILED."""
        from workers import dispatcher as dispatcher_module

        finalize = AsyncMock(return_value=True)
        monkeypatch.setattr(
            dispatcher_module, "finalize_failed_preview_task", finalize
        )

        ctx, uow = make_context()
        task = make_task(
            task_type=BackgroundTaskType.GENERATE_FILE_PREVIEW,
            attempts=1,
            max_attempts=3,
        )

        registry = make_registry()

        async def retrying_handler(context):
            return WorkerTaskExecutionResult(
                success=False,
                progress_percent=0,
                result_data=None,
                error_message="temporary",
                error_code="temporary_unavailable",
                retry=True,
            )

        registry.register(BackgroundTaskType.GENERATE_FILE_PREVIEW, retrying_handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        outcome = await dispatcher.process_task(task)

        assert outcome == "retried"
        finalize.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_non_preview_task_not_finalized(self, monkeypatch) -> None:
        """Провал задач других типов не трогает превью."""
        from workers import dispatcher as dispatcher_module

        finalize = AsyncMock(return_value=True)
        monkeypatch.setattr(
            dispatcher_module, "finalize_failed_preview_task", finalize
        )

        ctx, uow = make_context()
        task = make_task(task_type=BackgroundTaskType.CLEAN_TRASH)

        registry = make_registry()

        async def failing_handler(context):
            return WorkerTaskExecutionResult(
                success=False,
                progress_percent=0,
                result_data=None,
                error_message="boom",
                error_code="error",
                retry=False,
            )

        registry.register(BackgroundTaskType.CLEAN_TRASH, failing_handler)
        dispatcher = WorkerDispatcher(context=ctx, registry=registry)

        outcome = await dispatcher.process_task(task)

        assert outcome == "failed"
        finalize.assert_not_awaited()
