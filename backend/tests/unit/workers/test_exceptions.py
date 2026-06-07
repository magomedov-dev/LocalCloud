"""Тесты исключений воркера: иерархия классов и сериализация."""

from __future__ import annotations

import uuid

import pytest

from workers.exceptions import (
    WorkerConfigurationError,
    WorkerError,
    WorkerLifecycleError,
    WorkerSchedulerError,
    WorkerShutdownError,
    WorkerTaskDispatchError,
    WorkerTaskError,
    WorkerTaskHandlerError,
    WorkerTaskLockError,
    WorkerTaskNotFoundError,
)


class TestWorkerError:
    def test_default_message(self) -> None:
        err = WorkerError()
        assert err.message
        assert isinstance(err.message, str)

    def test_custom_message_stored(self) -> None:
        err = WorkerError("custom message")
        assert err.message == "custom message"

    def test_details_copied(self) -> None:
        original = {"key": "value"}
        err = WorkerError(details=original)
        original["key"] = "modified"
        assert err.details["key"] == "value"

    def test_empty_details_default(self) -> None:
        err = WorkerError()
        assert err.details == {}

    def test_cause_stored(self) -> None:
        cause = ValueError("root cause")
        err = WorkerError(cause=cause)
        assert err.cause is cause
        assert err.__cause__ is cause

    def test_str_without_details(self) -> None:
        err = WorkerError("simple")
        assert str(err) == "simple"

    def test_str_with_details(self) -> None:
        err = WorkerError("msg", details={"x": 1})
        assert "msg" in str(err)
        assert "Details" in str(err)

    def test_to_dict_required_keys(self) -> None:
        err = WorkerError("test")
        d = err.to_dict()
        assert d["error"] == "WorkerError"
        assert d["message"] == "test"

    def test_to_dict_includes_details(self) -> None:
        err = WorkerError("test", details={"key": "val"})
        assert err.to_dict()["details"]["key"] == "val"

    def test_to_dict_omits_empty_details(self) -> None:
        err = WorkerError("test")
        assert "details" not in err.to_dict()

    def test_to_dict_includes_cause_class(self) -> None:
        err = WorkerError("test", cause=RuntimeError("cause"))
        assert err.to_dict()["cause"] == "RuntimeError"

    def test_to_dict_omits_cause_when_none(self) -> None:
        err = WorkerError("test")
        assert "cause" not in err.to_dict()

    def test_is_exception(self) -> None:
        assert isinstance(WorkerError(), Exception)


class TestWorkerSubclasses:
    def test_configuration_error_is_worker_error(self) -> None:
        assert issubclass(WorkerConfigurationError, WorkerError)

    def test_lifecycle_error_is_worker_error(self) -> None:
        assert issubclass(WorkerLifecycleError, WorkerError)

    def test_scheduler_error_is_worker_error(self) -> None:
        assert issubclass(WorkerSchedulerError, WorkerError)

    def test_shutdown_error_is_lifecycle_error(self) -> None:
        assert issubclass(WorkerShutdownError, WorkerLifecycleError)

    def test_task_error_is_worker_error(self) -> None:
        assert issubclass(WorkerTaskError, WorkerError)

    def test_task_not_found_is_task_error(self) -> None:
        assert issubclass(WorkerTaskNotFoundError, WorkerTaskError)

    def test_task_lock_error_is_task_error(self) -> None:
        assert issubclass(WorkerTaskLockError, WorkerTaskError)

    def test_task_dispatch_error_is_task_error(self) -> None:
        assert issubclass(WorkerTaskDispatchError, WorkerTaskError)

    def test_task_handler_error_is_task_error(self) -> None:
        assert issubclass(WorkerTaskHandlerError, WorkerTaskError)

    def test_configuration_error_custom_message(self) -> None:
        err = WorkerConfigurationError("bad config")
        assert err.message == "bad config"

    def test_scheduler_error_default_message(self) -> None:
        err = WorkerSchedulerError()
        assert err.message

    def test_shutdown_error_details(self) -> None:
        err = WorkerShutdownError(details={"reason": "timeout"})
        assert err.details["reason"] == "timeout"


class TestWorkerTaskError:
    def test_task_id_added_to_details(self) -> None:
        tid = uuid.uuid4()
        err = WorkerTaskError(task_id=tid)
        assert err.details["task_id"] == str(tid)

    def test_task_type_added_to_details(self) -> None:
        err = WorkerTaskError(task_type="archive")
        assert err.details["task_type"] == "archive"

    def test_operation_added_to_details(self) -> None:
        err = WorkerTaskError(operation="process")
        assert err.details["operation"] == "process"

    def test_all_fields_in_details(self) -> None:
        tid = uuid.uuid4()
        err = WorkerTaskError(
            "test",
            task_id=tid,
            task_type="cleanup",
            operation="run",
        )
        assert err.details["task_id"] == str(tid)
        assert err.details["task_type"] == "cleanup"
        assert err.details["operation"] == "run"

    def test_none_fields_not_in_details(self) -> None:
        err = WorkerTaskError("test")
        assert "task_id" not in err.details
        assert "task_type" not in err.details
        assert "operation" not in err.details

    def test_not_found_inherits_task_fields(self) -> None:
        tid = uuid.uuid4()
        err = WorkerTaskNotFoundError(task_id=tid, task_type="upload")
        assert err.details["task_id"] == str(tid)
        assert err.details["task_type"] == "upload"

    def test_lock_error_custom_message(self) -> None:
        err = WorkerTaskLockError("lock failed")
        assert err.message == "lock failed"

    def test_dispatch_error_with_cause(self) -> None:
        cause = RuntimeError("dispatch failed")
        err = WorkerTaskDispatchError(cause=cause)
        assert err.cause is cause

    def test_handler_error_to_dict(self) -> None:
        err = WorkerTaskHandlerError("handler error", task_type="preview")
        d = err.to_dict()
        assert d["error"] == "WorkerTaskHandlerError"
        assert d["details"]["task_type"] == "preview"
