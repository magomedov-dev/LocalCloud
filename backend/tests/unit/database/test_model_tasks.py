"""Модульные тесты ORM-модели BackgroundTask.

Все экземпляры создаются через ``model_construct``, поэтому сессия БД не нужна.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from database.models.enums import BackgroundTaskStatus, BackgroundTaskType, TaskPriority
from database.models.tasks import BackgroundTask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(**kwargs: object) -> BackgroundTask:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        task_type=BackgroundTaskType.CLEAN_TRASH,
        status=BackgroundTaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
        created_by=None,
        related_entity_type=None,
        related_entity_id=None,
        progress_percent=0,
        payload=None,
        result_data=None,
        error_message=None,
        error_code=None,
        attempts_count=0,
        max_attempts=3,
        idempotency_key=None,
        scheduled_at=None,
        started_at=None,
        finished_at=None,
        locked_by=None,
        locked_until=None,
    )
    defaults.update(kwargs)
    return BackgroundTask(**defaults)


# ---------------------------------------------------------------------------
# Status properties
# ---------------------------------------------------------------------------

class TestIsPending:
    def test_pending_status_returns_true(self) -> None:
        task = make_task(status=BackgroundTaskStatus.PENDING)
        assert task.is_pending is True

    def test_running_status_returns_false(self) -> None:
        task = make_task(status=BackgroundTaskStatus.RUNNING)
        assert task.is_pending is False


class TestIsRunning:
    def test_running_status_returns_true(self) -> None:
        task = make_task(status=BackgroundTaskStatus.RUNNING)
        assert task.is_running is True

    def test_pending_status_returns_false(self) -> None:
        task = make_task(status=BackgroundTaskStatus.PENDING)
        assert task.is_running is False


class TestIsCompleted:
    def test_completed_status_returns_true(self) -> None:
        task = make_task(status=BackgroundTaskStatus.COMPLETED)
        assert task.is_completed is True

    def test_failed_status_returns_false(self) -> None:
        task = make_task(status=BackgroundTaskStatus.FAILED)
        assert task.is_completed is False


class TestIsFailed:
    def test_failed_status_returns_true(self) -> None:
        task = make_task(status=BackgroundTaskStatus.FAILED)
        assert task.is_failed is True

    def test_completed_status_returns_false(self) -> None:
        task = make_task(status=BackgroundTaskStatus.COMPLETED)
        assert task.is_failed is False


class TestIsCancelled:
    def test_cancelled_status_returns_true(self) -> None:
        task = make_task(status=BackgroundTaskStatus.CANCELLED)
        assert task.is_cancelled is True

    def test_pending_status_returns_false(self) -> None:
        task = make_task(status=BackgroundTaskStatus.PENDING)
        assert task.is_cancelled is False


class TestIsFinished:
    def test_completed_is_finished(self) -> None:
        task = make_task(status=BackgroundTaskStatus.COMPLETED)
        assert task.is_finished is True

    def test_failed_is_finished(self) -> None:
        task = make_task(status=BackgroundTaskStatus.FAILED)
        assert task.is_finished is True

    def test_cancelled_is_finished(self) -> None:
        task = make_task(status=BackgroundTaskStatus.CANCELLED)
        assert task.is_finished is True

    def test_pending_not_finished(self) -> None:
        task = make_task(status=BackgroundTaskStatus.PENDING)
        assert task.is_finished is False

    def test_running_not_finished(self) -> None:
        task = make_task(status=BackgroundTaskStatus.RUNNING)
        assert task.is_finished is False


# ---------------------------------------------------------------------------
# is_system_task
# ---------------------------------------------------------------------------

class TestIsSystemTask:
    def test_no_created_by_is_system_task(self) -> None:
        task = make_task(created_by=None)
        assert task.is_system_task is True

    def test_with_created_by_not_system_task(self) -> None:
        task = make_task(created_by=uuid.uuid4())
        assert task.is_system_task is False


# ---------------------------------------------------------------------------
# can_retry
# ---------------------------------------------------------------------------

class TestCanRetry:
    def test_attempts_below_max_can_retry(self) -> None:
        task = make_task(attempts_count=1, max_attempts=3)
        assert task.can_retry is True

    def test_attempts_equal_max_cannot_retry(self) -> None:
        task = make_task(attempts_count=3, max_attempts=3)
        assert task.can_retry is False

    def test_attempts_exceed_max_cannot_retry(self) -> None:
        task = make_task(attempts_count=4, max_attempts=3)
        assert task.can_retry is False


# ---------------------------------------------------------------------------
# has_error
# ---------------------------------------------------------------------------

class TestHasError:
    def test_error_message_set_returns_true(self) -> None:
        task = make_task(error_message="something went wrong")
        assert task.has_error is True

    def test_error_code_set_returns_true(self) -> None:
        task = make_task(error_code="E_TIMEOUT")
        assert task.has_error is True

    def test_no_error_info_returns_false(self) -> None:
        task = make_task(error_message=None, error_code=None)
        assert task.has_error is False


# ---------------------------------------------------------------------------
# has_related_entity
# ---------------------------------------------------------------------------

class TestHasRelatedEntity:
    def test_both_set_returns_true(self) -> None:
        task = make_task(
            related_entity_type="file",
            related_entity_id=uuid.uuid4(),
        )
        assert task.has_related_entity is True

    def test_only_type_set_returns_false(self) -> None:
        task = make_task(related_entity_type="file", related_entity_id=None)
        assert task.has_related_entity is False

    def test_neither_set_returns_false(self) -> None:
        task = make_task(related_entity_type=None, related_entity_id=None)
        assert task.has_related_entity is False


# ---------------------------------------------------------------------------
# duration_seconds
# ---------------------------------------------------------------------------

class TestDurationSeconds:
    def test_both_timestamps_set_returns_float(self) -> None:
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
        task = make_task(started_at=start, finished_at=end)
        assert task.duration_seconds == pytest.approx(30.0)

    def test_started_at_none_returns_none(self) -> None:
        task = make_task(started_at=None, finished_at=datetime.now(UTC))
        assert task.duration_seconds is None

    def test_finished_at_none_returns_none(self) -> None:
        task = make_task(started_at=datetime.now(UTC), finished_at=None)
        assert task.duration_seconds is None


# ---------------------------------------------------------------------------
# is_scheduled_for_at
# ---------------------------------------------------------------------------

class TestIsScheduledForAt:
    def test_no_scheduled_at_returns_true(self) -> None:
        task = make_task(scheduled_at=None)
        assert task.is_scheduled_for_at(datetime.now(UTC)) is True

    def test_scheduled_in_past_returns_true(self) -> None:
        task = make_task(scheduled_at=datetime.now(UTC) - timedelta(hours=1))
        assert task.is_scheduled_for_at(datetime.now(UTC)) is True

    def test_scheduled_in_future_returns_false(self) -> None:
        task = make_task(scheduled_at=datetime.now(UTC) + timedelta(hours=1))
        assert task.is_scheduled_for_at(datetime.now(UTC)) is False


# ---------------------------------------------------------------------------
# is_locked_at
# ---------------------------------------------------------------------------

class TestIsLockedAt:
    def test_locked_until_in_future_returns_true(self) -> None:
        task = make_task(locked_until=datetime.now(UTC) + timedelta(minutes=5))
        assert task.is_locked_at(datetime.now(UTC)) is True

    def test_locked_until_in_past_returns_false(self) -> None:
        task = make_task(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        assert task.is_locked_at(datetime.now(UTC)) is False

    def test_locked_until_none_returns_false(self) -> None:
        task = make_task(locked_until=None)
        assert task.is_locked_at(datetime.now(UTC)) is False


# ---------------------------------------------------------------------------
# can_start_at
# ---------------------------------------------------------------------------

class TestCanStartAt:
    def test_pending_unscheduled_unlocked_with_retries_can_start(self) -> None:
        task = make_task(
            status=BackgroundTaskStatus.PENDING,
            scheduled_at=None,
            locked_until=None,
            attempts_count=0,
            max_attempts=3,
        )
        assert task.can_start_at(datetime.now(UTC)) is True

    def test_running_task_cannot_start(self) -> None:
        task = make_task(status=BackgroundTaskStatus.RUNNING)
        assert task.can_start_at(datetime.now(UTC)) is False

    def test_scheduled_in_future_cannot_start(self) -> None:
        task = make_task(
            status=BackgroundTaskStatus.PENDING,
            scheduled_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert task.can_start_at(datetime.now(UTC)) is False

    def test_locked_task_cannot_start(self) -> None:
        task = make_task(
            status=BackgroundTaskStatus.PENDING,
            locked_until=datetime.now(UTC) + timedelta(minutes=1),
        )
        assert task.can_start_at(datetime.now(UTC)) is False

    def test_exhausted_attempts_cannot_start(self) -> None:
        task = make_task(
            status=BackgroundTaskStatus.PENDING,
            attempts_count=3,
            max_attempts=3,
        )
        assert task.can_start_at(datetime.now(UTC)) is False


# ---------------------------------------------------------------------------
# lock()
# ---------------------------------------------------------------------------

class TestLock:
    def test_sets_locked_by(self) -> None:
        task = make_task()
        task.lock("worker-1", datetime.now(UTC) + timedelta(minutes=5))
        assert task.locked_by == "worker-1"

    def test_sets_locked_until(self) -> None:
        until = datetime.now(UTC) + timedelta(minutes=10)
        task = make_task()
        task.lock("worker-1", until)
        assert task.locked_until == until

    def test_empty_worker_id_raises(self) -> None:
        task = make_task()
        with pytest.raises(ValueError):
            task.lock("", datetime.now(UTC) + timedelta(minutes=5))


# ---------------------------------------------------------------------------
# unlock()
# ---------------------------------------------------------------------------

class TestUnlock:
    def test_clears_locked_by(self) -> None:
        task = make_task(locked_by="worker-1", locked_until=datetime.now(UTC))
        task.unlock()
        assert task.locked_by is None

    def test_clears_locked_until(self) -> None:
        task = make_task(locked_by="worker-1", locked_until=datetime.now(UTC))
        task.unlock()
        assert task.locked_until is None


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------

class TestStart:
    def test_sets_status_to_running(self) -> None:
        task = make_task(status=BackgroundTaskStatus.PENDING, attempts_count=0)
        task.start()
        assert task.status == BackgroundTaskStatus.RUNNING

    def test_increments_attempts_count(self) -> None:
        task = make_task(attempts_count=1)
        task.start()
        assert task.attempts_count == 2

    def test_sets_started_at(self) -> None:
        task = make_task(started_at=None, attempts_count=0)
        task.start()
        assert task.started_at is not None

    def test_clears_error_message(self) -> None:
        task = make_task(error_message="old error", attempts_count=0)
        task.start()
        assert task.error_message is None

    def test_clears_finished_at(self) -> None:
        task = make_task(finished_at=datetime.now(UTC), attempts_count=0)
        task.start()
        assert task.finished_at is None

    def test_start_with_worker_and_lock_locks_task(self) -> None:
        locked_until = datetime.now(UTC) + timedelta(minutes=5)
        task = make_task(attempts_count=0, locked_by=None, locked_until=None)
        task.start(worker_id="worker-1", locked_until=locked_until)
        assert task.locked_by == "worker-1"
        assert task.locked_until == locked_until


# ---------------------------------------------------------------------------
# Factory methods
# ---------------------------------------------------------------------------

class TestCreateSystemTask:
    def test_creates_pending_task_without_creator(self) -> None:
        task = BackgroundTask.create_system_task(
            task_type=BackgroundTaskType.CLEAN_TRASH,
        )
        assert task.status == BackgroundTaskStatus.PENDING
        assert task.created_by is None
        assert task.task_type == BackgroundTaskType.CLEAN_TRASH


class TestCreateUserTask:
    def test_creates_pending_task_with_creator(self) -> None:
        user_id = uuid.uuid4()
        task = BackgroundTask.create_user_task(
            task_type=BackgroundTaskType.CLEAN_TRASH,
            created_by=user_id,
        )
        assert task.status == BackgroundTaskStatus.PENDING
        assert task.created_by == user_id


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------

class TestComplete:
    def test_sets_status_to_completed(self) -> None:
        task = make_task(status=BackgroundTaskStatus.RUNNING)
        task.complete()
        assert task.status == BackgroundTaskStatus.COMPLETED

    def test_sets_progress_to_100(self) -> None:
        task = make_task(progress_percent=50)
        task.complete()
        assert task.progress_percent == 100

    def test_stores_result_data(self) -> None:
        task = make_task()
        task.complete(result_data={"files": 5})
        assert task.result_data == {"files": 5}

    def test_sets_finished_at(self) -> None:
        task = make_task(finished_at=None)
        task.complete()
        assert task.finished_at is not None

    def test_clears_error_message(self) -> None:
        task = make_task(error_message="stale error")
        task.complete()
        assert task.error_message is None

    def test_unlocks_task(self) -> None:
        task = make_task(locked_by="worker-1", locked_until=datetime.now(UTC))
        task.complete()
        assert task.locked_by is None
        assert task.locked_until is None


# ---------------------------------------------------------------------------
# fail()
# ---------------------------------------------------------------------------

class TestFail:
    def test_sets_status_to_failed(self) -> None:
        task = make_task(status=BackgroundTaskStatus.RUNNING)
        task.fail()
        assert task.status == BackgroundTaskStatus.FAILED

    def test_stores_error_message(self) -> None:
        task = make_task()
        task.fail(error_message="disk full")
        assert task.error_message == "disk full"

    def test_stores_error_code(self) -> None:
        task = make_task()
        task.fail(error_code="E_DISK_FULL")
        assert task.error_code == "E_DISK_FULL"

    def test_sets_finished_at(self) -> None:
        task = make_task(finished_at=None)
        task.fail()
        assert task.finished_at is not None

    def test_unlocks_task(self) -> None:
        task = make_task(locked_by="worker-1", locked_until=datetime.now(UTC))
        task.fail()
        assert task.locked_by is None


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------

class TestCancel:
    def test_sets_status_to_cancelled(self) -> None:
        task = make_task(status=BackgroundTaskStatus.PENDING)
        task.cancel()
        assert task.status == BackgroundTaskStatus.CANCELLED

    def test_stores_reason_in_error_message(self) -> None:
        task = make_task()
        task.cancel(reason="no longer needed")
        assert task.error_message == "no longer needed"

    def test_sets_finished_at(self) -> None:
        task = make_task(finished_at=None)
        task.cancel()
        assert task.finished_at is not None

    def test_unlocks_task(self) -> None:
        task = make_task(locked_by="worker-1", locked_until=datetime.now(UTC))
        task.cancel()
        assert task.locked_by is None


# ---------------------------------------------------------------------------
# retry()
# ---------------------------------------------------------------------------

class TestRetry:
    def test_sets_status_to_pending(self) -> None:
        task = make_task(
            status=BackgroundTaskStatus.FAILED,
            attempts_count=1,
            max_attempts=3,
        )
        task.retry()
        assert task.status == BackgroundTaskStatus.PENDING

    def test_clears_error_info(self) -> None:
        task = make_task(
            error_message="old error",
            error_code="E_OLD",
            attempts_count=1,
            max_attempts=3,
        )
        task.retry()
        assert task.error_message is None
        assert task.error_code is None

    def test_raises_when_retries_exhausted(self) -> None:
        task = make_task(attempts_count=3, max_attempts=3)
        with pytest.raises(ValueError):
            task.retry()

    def test_scheduled_at_updated(self) -> None:
        future = datetime.now(UTC) + timedelta(minutes=30)
        task = make_task(attempts_count=1, max_attempts=3)
        task.retry(scheduled_at=future)
        assert task.scheduled_at == future


# ---------------------------------------------------------------------------
# update_progress()
# ---------------------------------------------------------------------------

class TestUpdateProgress:
    def test_valid_progress_stored(self) -> None:
        task = make_task(progress_percent=0)
        task.update_progress(50)
        assert task.progress_percent == 50

    def test_negative_progress_raises(self) -> None:
        task = make_task()
        with pytest.raises(ValueError):
            task.update_progress(-1)

    def test_over_100_raises(self) -> None:
        task = make_task()
        with pytest.raises(ValueError):
            task.update_progress(101)

    def test_exactly_100_is_valid(self) -> None:
        task = make_task()
        task.update_progress(100)
        assert task.progress_percent == 100

    def test_exactly_0_is_valid(self) -> None:
        task = make_task()
        task.update_progress(0)
        assert task.progress_percent == 0


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------

class TestRepr:
    def test_repr_non_empty(self) -> None:
        task = make_task()
        assert isinstance(repr(task), str) and len(repr(task)) > 0

    def test_repr_contains_class_name(self) -> None:
        task = make_task()
        assert "BackgroundTask" in repr(task)
