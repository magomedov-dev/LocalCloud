"""Тесты типов воркера: перечисления, результаты задач и структуры данных."""

from __future__ import annotations


import pytest

from workers.types import (
    WorkerIdentity,
    WorkerRunMode,
    WorkerRuntimeStats,
    WorkerScheduleDefinition,
    WorkerState,
    WorkerTaskExecutionResult,
)


class TestWorkerState:
    def test_values(self) -> None:
        assert WorkerState.STARTING == "starting"
        assert WorkerState.RUNNING == "running"
        assert WorkerState.STOPPING == "stopping"
        assert WorkerState.STOPPED == "stopped"
        assert WorkerState.FAILED == "failed"

    def test_is_str_enum(self) -> None:
        assert isinstance(WorkerState.RUNNING, str)


class TestWorkerRunMode:
    def test_values(self) -> None:
        assert WorkerRunMode.ONCE == "once"
        assert WorkerRunMode.LOOP == "loop"
        assert WorkerRunMode.SCHEDULER == "scheduler"


class TestWorkerIdentity:
    def test_fields_stored(self) -> None:
        identity = WorkerIdentity(
            worker_id="w-001",
            worker_name="test-worker",
            run_mode=WorkerRunMode.LOOP,
        )
        assert identity.worker_id == "w-001"
        assert identity.worker_name == "test-worker"
        assert identity.run_mode == WorkerRunMode.LOOP

    def test_is_frozen(self) -> None:
        identity = WorkerIdentity("w-001", "test", WorkerRunMode.ONCE)
        with pytest.raises((AttributeError, TypeError)):
            identity.worker_id = "other"  # type: ignore[misc]


class TestWorkerTaskExecutionResult:
    def test_success_result(self) -> None:
        result = WorkerTaskExecutionResult(success=True)
        assert result.success is True
        assert result.progress_percent == 100
        assert result.result_data is None
        assert result.error_message is None
        assert result.retry is False

    def test_failure_result(self) -> None:
        result = WorkerTaskExecutionResult(
            success=False,
            error_message="Something went wrong",
            error_code="processing_failed",
            retry=True,
        )
        assert result.success is False
        assert result.error_message == "Something went wrong"
        assert result.error_code == "processing_failed"
        assert result.retry is True

    def test_with_result_data(self) -> None:
        data = {"files_processed": 5}
        result = WorkerTaskExecutionResult(success=True, result_data=data)
        assert result.result_data == data

    def test_partial_progress(self) -> None:
        result = WorkerTaskExecutionResult(success=False, progress_percent=50)
        assert result.progress_percent == 50

    def test_is_frozen(self) -> None:
        result = WorkerTaskExecutionResult(success=True)
        with pytest.raises((AttributeError, TypeError)):
            result.success = False  # type: ignore[misc]


class TestWorkerScheduleDefinition:
    def test_required_fields(self) -> None:
        from database.models.enums import BackgroundTaskType
        sched = WorkerScheduleDefinition(
            schedule_name="cleanup",
            task_type=BackgroundTaskType.CLEAN_TRASH,
            interval_seconds=3600,
        )
        assert sched.schedule_name == "cleanup"
        assert sched.interval_seconds == 3600
        assert sched.enabled is True
        assert sched.payload == {}

    def test_custom_payload(self) -> None:
        from database.models.enums import BackgroundTaskType
        sched = WorkerScheduleDefinition(
            schedule_name="test",
            task_type=BackgroundTaskType.CLEAN_TRASH,
            interval_seconds=60,
            payload={"batch_size": 10},
        )
        assert sched.payload["batch_size"] == 10

    def test_disabled(self) -> None:
        from database.models.enums import BackgroundTaskType
        sched = WorkerScheduleDefinition(
            schedule_name="test",
            task_type=BackgroundTaskType.CLEAN_TRASH,
            interval_seconds=60,
            enabled=False,
        )
        assert sched.enabled is False

    def test_is_frozen(self) -> None:
        from database.models.enums import BackgroundTaskType
        sched = WorkerScheduleDefinition(
            schedule_name="test",
            task_type=BackgroundTaskType.CLEAN_TRASH,
            interval_seconds=60,
        )
        with pytest.raises((AttributeError, TypeError)):
            sched.schedule_name = "other"  # type: ignore[misc]


class TestWorkerRuntimeStats:
    def test_default_values_are_zero(self) -> None:
        stats = WorkerRuntimeStats()
        assert stats.fetched_count == 0
        assert stats.started_count == 0
        assert stats.completed_count == 0
        assert stats.failed_count == 0
        assert stats.retried_count == 0
        assert stats.skipped_count == 0
        assert stats.created_scheduled_count == 0

    def test_mutable(self) -> None:
        stats = WorkerRuntimeStats()
        stats.completed_count += 5
        assert stats.completed_count == 5

    def test_can_set_initial_values(self) -> None:
        stats = WorkerRuntimeStats(fetched_count=10, completed_count=8, failed_count=2)
        assert stats.fetched_count == 10
        assert stats.completed_count == 8
        assert stats.failed_count == 2
