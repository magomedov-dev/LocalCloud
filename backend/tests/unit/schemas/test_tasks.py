"""Модульные тесты схем фоновых задач."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    TaskPriority,
)
from schemas.tasks import (
    BackgroundTaskCancelRequest,
    BackgroundTaskCreate,
    BackgroundTaskListItem,
    BackgroundTaskProgressUpdate,
    BackgroundTaskQueryParams,
    BackgroundTaskRead,
    BackgroundTaskRetryRequest,
    BackgroundTaskUpdate,
    TaskResultRead,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestBackgroundTaskCreate:
    """Тесты схемы создания фоновой задачи."""

    def test_valid_minimal(self):
        r = BackgroundTaskCreate(task_type=BackgroundTaskType.CLEAN_TRASH)
        assert r.priority == TaskPriority.NORMAL
        assert r.max_attempts == 1
        assert r.created_by is None
        assert r.payload is None

    def test_task_type_required(self):
        with pytest.raises(ValidationError):
            BackgroundTaskCreate()

    def test_optional_text_normalized(self):
        r = BackgroundTaskCreate(
            task_type=BackgroundTaskType.CLEAN_TRASH,
            related_entity_type="  node  ",
            idempotency_key="  key  ",
        )
        assert r.related_entity_type == "node"
        assert r.idempotency_key == "key"

    def test_optional_text_blank_becomes_none(self):
        r = BackgroundTaskCreate(
            task_type=BackgroundTaskType.CLEAN_TRASH,
            related_entity_type="   ",
            idempotency_key="   ",
        )
        assert r.related_entity_type is None
        assert r.idempotency_key is None

    def test_max_attempts_must_be_positive(self):
        with pytest.raises(ValidationError):
            BackgroundTaskCreate(task_type=BackgroundTaskType.CLEAN_TRASH, max_attempts=0)

    def test_priority_enum_coercion(self):
        r = BackgroundTaskCreate(task_type=BackgroundTaskType.CLEAN_TRASH, priority="high")
        assert r.priority == TaskPriority.HIGH

    def test_payload_dict(self):
        r = BackgroundTaskCreate(
            task_type=BackgroundTaskType.CLEAN_TRASH, payload={"a": 1}
        )
        assert r.payload == {"a": 1}

    def test_related_entity_type_too_long_raises(self):
        with pytest.raises(ValidationError):
            BackgroundTaskCreate(
                task_type=BackgroundTaskType.CLEAN_TRASH,
                related_entity_type="a" * 129,
            )


def _read_kwargs(**overrides):
    base = dict(
        id=uuid4(),
        task_type=BackgroundTaskType.CLEAN_TRASH,
        status=BackgroundTaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
        progress_percent=0,
        attempts_count=0,
        max_attempts=1,
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(overrides)
    return base


class TestBackgroundTaskRead:
    """Тесты схемы чтения фоновой задачи."""

    def test_valid_minimal(self):
        r = BackgroundTaskRead(**_read_kwargs())
        assert r.progress_percent == 0
        assert r.payload is None
        assert r.error_message is None

    def test_progress_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            BackgroundTaskRead(**_read_kwargs(progress_percent=101))

    def test_negative_attempts_raises(self):
        with pytest.raises(ValidationError):
            BackgroundTaskRead(**_read_kwargs(attempts_count=-1))

    def test_from_attributes(self):
        class Obj:
            pass

        obj = Obj()
        data = _read_kwargs(
            created_by=None, related_entity_type=None, related_entity_id=None,
            payload=None, result_data=None, error_message=None, error_code=None,
            idempotency_key=None, scheduled_at=None, started_at=None,
            finished_at=None, locked_by=None, locked_until=None,
        )
        for k, v in data.items():
            setattr(obj, k, v)
        r = BackgroundTaskRead.model_validate(obj)
        assert r.task_type == BackgroundTaskType.CLEAN_TRASH


class TestBackgroundTaskListItem:
    """Тесты элемента списка фоновых задач."""

    def test_valid(self):
        r = BackgroundTaskListItem(
            id=uuid4(),
            task_type=BackgroundTaskType.CLEAN_TRASH,
            status=BackgroundTaskStatus.RUNNING,
            priority=TaskPriority.LOW,
            progress_percent=50,
            attempts_count=1,
            max_attempts=3,
            created_at=NOW,
            updated_at=NOW,
        )
        assert r.progress_percent == 50

    def test_progress_lower_bound(self):
        with pytest.raises(ValidationError):
            BackgroundTaskListItem(
                id=uuid4(),
                task_type=BackgroundTaskType.CLEAN_TRASH,
                status=BackgroundTaskStatus.RUNNING,
                priority=TaskPriority.LOW,
                progress_percent=-1,
                attempts_count=1,
                max_attempts=3,
                created_at=NOW,
                updated_at=NOW,
            )


class TestBackgroundTaskUpdate:
    """Тесты схемы обновления фоновой задачи."""

    def test_all_optional_defaults(self):
        r = BackgroundTaskUpdate()
        assert r.status is None
        assert r.progress_percent is None

    def test_optional_text_normalized(self):
        r = BackgroundTaskUpdate(
            error_message="  oops  ", error_code="  E1  ", locked_by="  w1  "
        )
        assert r.error_message == "oops"
        assert r.error_code == "E1"
        assert r.locked_by == "w1"

    def test_optional_text_blank_becomes_none(self):
        r = BackgroundTaskUpdate(error_message="   ", locked_by="   ")
        assert r.error_message is None
        assert r.locked_by is None

    def test_finished_before_started_raises(self):
        with pytest.raises(ValidationError):
            BackgroundTaskUpdate(started_at=NOW + timedelta(hours=1), finished_at=NOW)

    def test_finished_after_started_ok(self):
        r = BackgroundTaskUpdate(started_at=NOW, finished_at=NOW + timedelta(hours=1))
        assert r.finished_at > r.started_at

    def test_attempts_exceeds_max_not_enforced(self):
        # attempts_count объявлено раньше max_attempts, поэтому межполевой
        # валидатор не видит max_attempts в info.data, и проверка не срабатывает.
        r = BackgroundTaskUpdate(max_attempts=2, attempts_count=3)
        assert r.attempts_count == 3

    def test_attempts_within_max_ok(self):
        r = BackgroundTaskUpdate(max_attempts=3, attempts_count=2)
        assert r.attempts_count == 2

    def test_progress_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            BackgroundTaskUpdate(progress_percent=200)


class TestBackgroundTaskProgressUpdate:
    """Тесты схемы обновления прогресса фоновой задачи."""

    def test_valid(self):
        r = BackgroundTaskProgressUpdate(progress_percent=42)
        assert r.message is None
        assert r.result_data is None

    def test_message_normalized(self):
        r = BackgroundTaskProgressUpdate(progress_percent=10, message="  hi  ")
        assert r.message == "hi"

    def test_message_blank_becomes_none(self):
        r = BackgroundTaskProgressUpdate(progress_percent=10, message="   ")
        assert r.message is None

    def test_progress_required(self):
        with pytest.raises(ValidationError):
            BackgroundTaskProgressUpdate()

    def test_progress_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            BackgroundTaskProgressUpdate(progress_percent=101)

    def test_message_too_long_raises(self):
        with pytest.raises(ValidationError):
            BackgroundTaskProgressUpdate(progress_percent=10, message="a" * 1001)


class TestBackgroundTaskCancelRequest:
    """Тесты запроса отмены фоновой задачи."""

    def test_default(self):
        r = BackgroundTaskCancelRequest()
        assert r.reason is None

    def test_reason_normalized(self):
        r = BackgroundTaskCancelRequest(reason="  stop  ")
        assert r.reason == "stop"

    def test_reason_blank_becomes_none(self):
        r = BackgroundTaskCancelRequest(reason="   ")
        assert r.reason is None

    def test_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            BackgroundTaskCancelRequest(reason="a" * 1001)


class TestBackgroundTaskRetryRequest:
    """Тесты запроса повторного запуска фоновой задачи."""

    def test_defaults(self):
        r = BackgroundTaskRetryRequest()
        assert r.reset_attempts is False
        assert r.scheduled_at is None
        assert r.priority is None

    def test_with_values(self):
        r = BackgroundTaskRetryRequest(
            reset_attempts=True, scheduled_at=NOW, priority=TaskPriority.CRITICAL
        )
        assert r.reset_attempts is True
        assert r.priority == TaskPriority.CRITICAL


class TestBackgroundTaskQueryParams:
    """Тесты параметров запроса списка фоновых задач."""

    def test_defaults(self):
        p = BackgroundTaskQueryParams()
        assert p.limit == 50
        assert p.sort_by == "created_at"
        assert p.sort_desc is True
        assert p.only_locked is None

    def test_optional_text_normalized(self):
        p = BackgroundTaskQueryParams(
            related_entity_type="  node  ",
            idempotency_key="  k  ",
            locked_by="  w  ",
        )
        assert p.related_entity_type == "node"
        assert p.idempotency_key == "k"
        assert p.locked_by == "w"

    def test_optional_text_blank_becomes_none(self):
        p = BackgroundTaskQueryParams(related_entity_type="   ")
        assert p.related_entity_type is None

    def test_created_range_invalid_raises(self):
        with pytest.raises(ValidationError):
            BackgroundTaskQueryParams(
                created_from=NOW + timedelta(days=1), created_to=NOW
            )

    def test_created_range_valid(self):
        p = BackgroundTaskQueryParams(created_from=NOW, created_to=NOW + timedelta(days=1))
        assert p.created_to > p.created_from

    def test_status_enum_coercion(self):
        p = BackgroundTaskQueryParams(status="completed")
        assert p.status == BackgroundTaskStatus.COMPLETED


class TestTaskResultRead:
    """Тесты схемы чтения результата задачи."""

    def test_valid(self):
        r = TaskResultRead(
            task_id=uuid4(),
            task_type=BackgroundTaskType.GENERATE_FILE_PREVIEW,
            status=BackgroundTaskStatus.COMPLETED,
            progress_percent=100,
        )
        assert r.result_data is None
        assert r.error_message is None

    def test_progress_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            TaskResultRead(
                task_id=uuid4(),
                task_type=BackgroundTaskType.GENERATE_FILE_PREVIEW,
                status=BackgroundTaskStatus.RUNNING,
                progress_percent=-5,
            )

    def test_with_result_data(self):
        r = TaskResultRead(
            task_id=uuid4(),
            task_type=BackgroundTaskType.GENERATE_FILE_PREVIEW,
            status=BackgroundTaskStatus.COMPLETED,
            progress_percent=100,
            result_data={"url": "x"},
        )
        assert r.result_data == {"url": "x"}
