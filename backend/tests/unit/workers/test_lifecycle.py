"""Тесты функций жизненного цикла воркера: запуск и остановка."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workers.exceptions import WorkerLifecycleError


# ---------------------------------------------------------------------------
# startup_worker
# ---------------------------------------------------------------------------

class TestStartupWorker:
    @pytest.mark.asyncio
    async def test_startup_success_returns_context(self) -> None:
        mock_context = MagicMock()
        mock_context.worker_id = "w-test-001"
        mock_context.storage_service = MagicMock()
        mock_context.storage_service.ensure_buckets_ready = AsyncMock(return_value={})

        with (
            patch("workers.lifecycle.get_settings", return_value=MagicMock()),
            patch("workers.lifecycle.setup_logging"),
            patch("workers.lifecycle.silence_noisy_loggers"),
            patch("workers.lifecycle.configure_root_exception_logging"),
            patch("workers.lifecycle.init_db_client"),
            patch("workers.lifecycle.build_worker_context", return_value=mock_context),
        ):
            from workers.lifecycle import startup_worker
            context = await startup_worker(worker_id="w-test-001")

        assert context is mock_context

    @pytest.mark.asyncio
    async def test_startup_with_none_worker_id(self) -> None:
        mock_context = MagicMock()
        mock_context.worker_id = "w-auto-generated"
        mock_context.storage_service = MagicMock()
        mock_context.storage_service.ensure_buckets_ready = AsyncMock(return_value={})

        with (
            patch("workers.lifecycle.get_settings", return_value=MagicMock()),
            patch("workers.lifecycle.setup_logging"),
            patch("workers.lifecycle.silence_noisy_loggers"),
            patch("workers.lifecycle.configure_root_exception_logging"),
            patch("workers.lifecycle.init_db_client"),
            patch("workers.lifecycle.build_worker_context", return_value=mock_context),
        ):
            from workers.lifecycle import startup_worker
            context = await startup_worker(worker_id=None)

        assert context is mock_context

    @pytest.mark.asyncio
    async def test_startup_propagates_lifecycle_error(self) -> None:
        with (
            patch("workers.lifecycle.get_settings", return_value=MagicMock()),
            patch("workers.lifecycle.setup_logging"),
            patch("workers.lifecycle.silence_noisy_loggers"),
            patch("workers.lifecycle.configure_root_exception_logging"),
            patch("workers.lifecycle.init_db_client"),
            patch(
                "workers.lifecycle.build_worker_context",
                side_effect=WorkerLifecycleError("config failed"),
            ),
        ):
            from workers.lifecycle import startup_worker
            with pytest.raises(WorkerLifecycleError, match="config failed"):
                await startup_worker()

    @pytest.mark.asyncio
    async def test_startup_wraps_generic_exception_as_lifecycle_error(self) -> None:
        with (
            patch("workers.lifecycle.get_settings", return_value=MagicMock()),
            patch("workers.lifecycle.setup_logging"),
            patch("workers.lifecycle.silence_noisy_loggers"),
            patch("workers.lifecycle.configure_root_exception_logging"),
            patch("workers.lifecycle.init_db_client"),
            patch(
                "workers.lifecycle.build_worker_context",
                side_effect=RuntimeError("unexpected"),
            ),
        ):
            from workers.lifecycle import startup_worker
            with pytest.raises(WorkerLifecycleError):
                await startup_worker()

    @pytest.mark.asyncio
    async def test_startup_calls_ensure_buckets_ready(self) -> None:
        mock_context = MagicMock()
        mock_context.worker_id = "w-001"
        mock_context.storage_service = MagicMock()
        mock_context.storage_service.ensure_buckets_ready = AsyncMock(return_value={})

        with (
            patch("workers.lifecycle.get_settings", return_value=MagicMock()),
            patch("workers.lifecycle.setup_logging"),
            patch("workers.lifecycle.silence_noisy_loggers"),
            patch("workers.lifecycle.configure_root_exception_logging"),
            patch("workers.lifecycle.init_db_client"),
            patch("workers.lifecycle.build_worker_context", return_value=mock_context),
        ):
            from workers.lifecycle import startup_worker
            await startup_worker()

        mock_context.storage_service.ensure_buckets_ready.assert_called_once_with(
            create_missing=True
        )


# ---------------------------------------------------------------------------
# shutdown_worker
# ---------------------------------------------------------------------------

class TestShutdownWorker:
    @pytest.mark.asyncio
    async def test_shutdown_none_context_no_exception(self) -> None:
        with patch("workers.lifecycle.close_db_client", new_callable=AsyncMock):
            from workers.lifecycle import shutdown_worker
            await shutdown_worker(None)  # не должно выбрасывать исключение

    @pytest.mark.asyncio
    async def test_shutdown_stops_render_executor(self) -> None:
        """Останов worker'а закрывает пул потоков рендеров превью."""
        with (
            patch("workers.lifecycle.close_db_client", new_callable=AsyncMock),
            patch(
                "workers.previews.shutdown_render_executor"
            ) as mock_shutdown,
        ):
            from workers.lifecycle import shutdown_worker

            await shutdown_worker(None)

        mock_shutdown.assert_called_once_with(wait=True)

    @pytest.mark.asyncio
    async def test_shutdown_render_executor_failure_is_swallowed(self) -> None:
        """Сбой остановки пула рендеров не роняет shutdown_worker."""
        with (
            patch("workers.lifecycle.close_db_client", new_callable=AsyncMock),
            patch(
                "workers.previews.shutdown_render_executor",
                side_effect=RuntimeError("boom"),
            ),
        ):
            from workers.lifecycle import shutdown_worker

            await shutdown_worker(None)  # не должно выбрасывать исключение

    @pytest.mark.asyncio
    async def test_shutdown_closes_storage_if_has_close(self) -> None:
        mock_context = MagicMock()
        mock_context.worker_id = "w-001"

        close_called = False

        def close_fn():
            nonlocal close_called
            close_called = True

        mock_context.storage_service = MagicMock()
        mock_context.storage_service.close = close_fn

        with patch("workers.lifecycle.close_db_client", new_callable=AsyncMock):
            from workers.lifecycle import shutdown_worker
            await shutdown_worker(mock_context)

        assert close_called

    @pytest.mark.asyncio
    async def test_shutdown_context_without_close_method_no_exception(self) -> None:
        mock_context = MagicMock()
        mock_context.worker_id = "w-001"
        # у storage_service нет метода close
        mock_context.storage_service = MagicMock(spec=[])

        with patch("workers.lifecycle.close_db_client", new_callable=AsyncMock):
            from workers.lifecycle import shutdown_worker
            await shutdown_worker(mock_context)

    @pytest.mark.asyncio
    async def test_shutdown_raises_lifecycle_error_on_db_close_failure(self) -> None:
        mock_context = MagicMock()
        mock_context.worker_id = "w-001"
        mock_context.storage_service = MagicMock(spec=[])

        async def failing_close():
            raise RuntimeError("db connection lost")

        with patch("workers.lifecycle.close_db_client", side_effect=failing_close):
            from workers.lifecycle import shutdown_worker
            with pytest.raises(WorkerLifecycleError):
                await shutdown_worker(mock_context)

    @pytest.mark.asyncio
    async def test_shutdown_raises_lifecycle_error_on_storage_close_failure(self) -> None:
        mock_context = MagicMock()
        mock_context.worker_id = "w-001"

        def bad_close():
            raise RuntimeError("storage close error")

        mock_context.storage_service = MagicMock()
        mock_context.storage_service.close = bad_close

        with patch("workers.lifecycle.close_db_client", new_callable=AsyncMock):
            from workers.lifecycle import shutdown_worker
            with pytest.raises(WorkerLifecycleError):
                await shutdown_worker(mock_context)

    @pytest.mark.asyncio
    async def test_shutdown_awaits_async_close(self) -> None:
        mock_context = MagicMock()
        mock_context.worker_id = "w-001"

        async_close_called = False

        async def async_close():
            nonlocal async_close_called
            async_close_called = True

        mock_context.storage_service = MagicMock()
        mock_context.storage_service.close = async_close

        with patch("workers.lifecycle.close_db_client", new_callable=AsyncMock):
            from workers.lifecycle import shutdown_worker
            await shutdown_worker(mock_context)

        assert async_close_called
