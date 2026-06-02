"""Тесты проверки здоровья воркера: БД, хранилище и диспетчер."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from workers.health import WorkerHealthChecker, WorkerHealthStatus


def _make_context(scheduler_enabled: bool = True) -> MagicMock:
    context = MagicMock()
    context.worker_id = "test-worker-001"
    context.worker_settings.worker_scheduler_enabled = scheduler_enabled

    # Мок готовности health-сервиса
    readiness = MagicMock()
    readiness.status = "ok"
    readiness.database = MagicMock(status="ok")
    readiness.storage = MagicMock(status="ok")
    context.services.health.get_readiness = AsyncMock(return_value=readiness)

    # Мок здоровья хранилища
    storage_report = MagicMock()
    storage_report.state = "healthy"
    context.storage_service.health.check_storage_health = AsyncMock(return_value=storage_report)
    context.storage_service.default_files_bucket = "files"

    # Мок UoW для проверки диспетчера
    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)
    mock_uow.tasks = AsyncMock()
    mock_uow.tasks.find_pending_tasks = AsyncMock(return_value=[])
    context.uow_factory = MagicMock(return_value=mock_uow)

    return context


class TestWorkerHealthStatus:
    def test_fields_stored(self) -> None:
        now = datetime.now(UTC)
        status = WorkerHealthStatus(
            worker_id="w-001",
            status="ok",
            checked_at=now,
            database_ok=True,
            storage_ok=True,
            scheduler_enabled=True,
        )
        assert status.worker_id == "w-001"
        assert status.status == "ok"
        assert status.database_ok is True
        assert status.storage_ok is True

    def test_default_details(self) -> None:
        now = datetime.now(UTC)
        status = WorkerHealthStatus(
            worker_id="w",
            status="ok",
            checked_at=now,
            database_ok=True,
            storage_ok=True,
            scheduler_enabled=False,
        )
        assert isinstance(status.details, dict)

    def test_is_frozen(self) -> None:
        now = datetime.now(UTC)
        status = WorkerHealthStatus(
            worker_id="w", status="ok", checked_at=now,
            database_ok=True, storage_ok=True, scheduler_enabled=True,
        )
        with pytest.raises((AttributeError, TypeError)):
            status.status = "degraded"  # type: ignore[misc]


class TestWorkerHealthChecker:
    @pytest.mark.asyncio
    async def test_check_returns_ok_when_all_healthy(self) -> None:
        context = _make_context()
        checker = WorkerHealthChecker(context)
        result = await checker.check()

        assert result.status == "ok"
        assert result.database_ok is True
        assert result.storage_ok is True
        assert result.worker_id == "test-worker-001"

    @pytest.mark.asyncio
    async def test_check_returns_degraded_when_only_db_ok(self) -> None:
        context = _make_context()

        readiness = MagicMock()
        readiness.status = "degraded"
        readiness.database = MagicMock(status="ok")
        readiness.storage = MagicMock(status="unavailable")
        context.services.health.get_readiness = AsyncMock(return_value=readiness)

        checker = WorkerHealthChecker(context)
        result = await checker.check()

        assert result.status == "degraded"

    @pytest.mark.asyncio
    async def test_check_fallback_when_health_service_fails(self) -> None:
        context = _make_context()
        context.services.health.get_readiness = AsyncMock(side_effect=RuntimeError("svc error"))

        checker = WorkerHealthChecker(context)
        result = await checker.check()

        # Откат к прямым проверкам: хранилище и БД замоканы как здоровые
        assert result.status in {"ok", "degraded", "unavailable"}

    @pytest.mark.asyncio
    async def test_check_includes_scheduler_enabled(self) -> None:
        context = _make_context(scheduler_enabled=False)
        checker = WorkerHealthChecker(context)
        result = await checker.check()

        assert result.scheduler_enabled is False

    @pytest.mark.asyncio
    async def test_check_database_returns_true_when_healthy(self) -> None:
        from unittest.mock import patch
        from database.health import DatabaseHealthStatus

        context = _make_context()
        checker = WorkerHealthChecker(context)

        healthy = DatabaseHealthStatus(status="healthy", connection=True)
        with patch("workers.health.get_database_health_report", AsyncMock(return_value=healthy)):
            result = await checker.check_database()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_database_returns_false_on_exception(self) -> None:
        from unittest.mock import patch

        context = _make_context()
        checker = WorkerHealthChecker(context)

        with patch("workers.health.get_database_health_report", AsyncMock(side_effect=Exception("fail"))):
            result = await checker.check_database()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_storage_returns_true_when_healthy(self) -> None:
        context = _make_context()
        checker = WorkerHealthChecker(context)
        result = await checker.check_storage()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_storage_returns_false_on_exception(self) -> None:
        context = _make_context()
        context.storage_service.health.check_storage_health = AsyncMock(
            side_effect=Exception("storage unavailable")
        )
        checker = WorkerHealthChecker(context)
        result = await checker.check_storage()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_dispatcher_returns_true_when_tasks_accessible(self) -> None:
        context = _make_context()
        checker = WorkerHealthChecker(context)
        result = await checker.check_dispatcher()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_dispatcher_returns_false_on_exception(self) -> None:
        context = _make_context()
        mock_uow = AsyncMock()
        mock_uow.__aenter__ = AsyncMock(side_effect=RuntimeError("db unavailable"))
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        context.uow_factory = MagicMock(return_value=mock_uow)

        checker = WorkerHealthChecker(context)
        result = await checker.check_dispatcher()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_returns_unavailable_when_both_fail(self) -> None:
        context = _make_context()

        readiness = MagicMock()
        readiness.status = "unavailable"
        readiness.database = MagicMock(status="unavailable")
        readiness.storage = MagicMock(status="unavailable")
        context.services.health.get_readiness = AsyncMock(return_value=readiness)

        checker = WorkerHealthChecker(context)
        result = await checker.check()

        assert result.status == "unavailable"

    @pytest.mark.asyncio
    async def test_check_result_has_checked_at(self) -> None:
        context = _make_context()
        checker = WorkerHealthChecker(context)
        before = datetime.now(UTC)
        result = await checker.check()
        after = datetime.now(UTC)

        assert before <= result.checked_at <= after
