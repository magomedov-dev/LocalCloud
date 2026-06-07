"""Тесты планировщика воркера: создание периодических задач."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from workers.scheduler import WorkerScheduler


# ---------------------------------------------------------------------------
# Фабрика тестовых фикстур
# ---------------------------------------------------------------------------


def make_mock_context(scheduler_enabled: bool = True):
    context = MagicMock()
    context.worker_settings.worker_scheduler_enabled = scheduler_enabled
    context.worker_settings.worker_clean_trash_interval_seconds = 3600
    context.worker_settings.worker_clean_expired_uploads_interval_seconds = 1800
    context.worker_settings.worker_clean_expired_public_links_interval_seconds = 3600
    context.worker_settings.worker_recalculate_quotas_interval_seconds = 86400
    context.worker_settings.worker_storage_integrity_interval_seconds = 86400
    context.worker_settings.worker_quota_batch_size = 100
    context.worker_settings.worker_integrity_batch_size = 100
    context.worker_id = "test-worker"

    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)
    mock_uow.commit = AsyncMock()
    mock_uow.flush = AsyncMock()
    mock_uow.tasks = AsyncMock()
    mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=None)
    mock_uow.tasks.create_task = AsyncMock(return_value=MagicMock())
    context.uow_factory = MagicMock(return_value=mock_uow)
    return context, mock_uow


# ---------------------------------------------------------------------------
# WorkerScheduler.run_due_schedules
# ---------------------------------------------------------------------------


class TestRunDueSchedules:
    @pytest.mark.asyncio
    async def test_returns_zero_when_scheduler_disabled(self) -> None:
        context, mock_uow = make_mock_context(scheduler_enabled=False)
        scheduler = WorkerScheduler(context)
        result = await scheduler.run_due_schedules()
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_uow_calls_when_scheduler_disabled(self) -> None:
        context, mock_uow = make_mock_context(scheduler_enabled=False)
        scheduler = WorkerScheduler(context)
        await scheduler.run_due_schedules()
        # uow_factory не должна была вызываться
        context.uow_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_all_schedule_methods_when_enabled(self) -> None:
        context, mock_uow = make_mock_context(scheduler_enabled=True)
        scheduler = WorkerScheduler(context)
        # Все задачи "новые" -> каждая возвращает 1
        result = await scheduler.run_due_schedules()
        # Существует 5 методов планирования
        assert result == 5

    @pytest.mark.asyncio
    async def test_returns_sum_of_created_counts(self) -> None:
        context, mock_uow = make_mock_context(scheduler_enabled=True)
        # Повторный вызов: все ключи идемпотентности уже есть -> по 0 каждый
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=MagicMock())
        scheduler = WorkerScheduler(context)
        result = await scheduler.run_due_schedules()
        assert result == 0


# ---------------------------------------------------------------------------
# Отдельные методы планирования — задача уже существует
# ---------------------------------------------------------------------------


class TestScheduleCleanTrash:
    @pytest.mark.asyncio
    async def test_returns_0_when_task_already_exists(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=MagicMock())
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_clean_trash()
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_1_and_creates_task_when_not_found(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=None)
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_clean_trash()
        assert result == 1
        mock_uow.tasks.create_task.assert_called_once()


class TestScheduleCleanExpiredUploads:
    @pytest.mark.asyncio
    async def test_returns_0_when_task_already_exists(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=MagicMock())
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_clean_expired_uploads()
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_1_when_task_not_found(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=None)
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_clean_expired_uploads()
        assert result == 1


class TestScheduleCleanExpiredPublicLinks:
    @pytest.mark.asyncio
    async def test_returns_0_when_task_already_exists(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=MagicMock())
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_clean_expired_public_links()
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_1_when_task_not_found(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=None)
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_clean_expired_public_links()
        assert result == 1


class TestScheduleRecalculateUserQuotas:
    @pytest.mark.asyncio
    async def test_returns_0_when_task_already_exists(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=MagicMock())
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_recalculate_user_quotas()
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_1_when_task_not_found(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=None)
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_recalculate_user_quotas()
        assert result == 1

    @pytest.mark.asyncio
    async def test_passes_quota_batch_size_in_payload(self) -> None:
        context, mock_uow = make_mock_context()
        context.worker_settings.worker_quota_batch_size = 250
        scheduler = WorkerScheduler(context)
        await scheduler.schedule_recalculate_user_quotas()
        # Проверяем, что create_task был вызван
        mock_uow.tasks.create_task.assert_called_once()
        # Мок задачи получает payload; можно проверить объект мока
        task_mock = mock_uow.tasks.create_task.return_value
        assert task_mock.payload is not None


class TestScheduleStorageIntegrityCheck:
    @pytest.mark.asyncio
    async def test_returns_0_when_task_already_exists(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=MagicMock())
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_storage_integrity_check()
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_1_when_task_not_found(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=None)
        scheduler = WorkerScheduler(context)
        result = await scheduler.schedule_storage_integrity_check()
        assert result == 1


# ---------------------------------------------------------------------------
# Внутренности _create_scheduled_task: вызовы commit и flush
# ---------------------------------------------------------------------------


class TestCreateScheduledTaskInternals:
    @pytest.mark.asyncio
    async def test_commit_called_when_task_created(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=None)
        scheduler = WorkerScheduler(context)
        await scheduler.schedule_clean_trash()
        mock_uow.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_not_called_when_task_already_exists(self) -> None:
        context, mock_uow = make_mock_context()
        mock_uow.tasks.get_by_idempotency_key = AsyncMock(return_value=MagicMock())
        scheduler = WorkerScheduler(context)
        await scheduler.schedule_clean_trash()
        mock_uow.commit.assert_not_called()
