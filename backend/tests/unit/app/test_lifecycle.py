"""Тесты жизненного цикла приложения: запуск, остановка и очистка ресурсов."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.lifecycle import _get_state_value, get_app_settings


class TestGetStateValue:
    def test_returns_attribute_when_present(self) -> None:
        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()
        app.state.my_attr = "value"
        assert _get_state_value(app, "my_attr") == "value"

    def test_returns_none_when_missing(self) -> None:
        app = MagicMock(spec=FastAPI)
        app.state = MagicMock(spec=[])
        assert _get_state_value(app, "nonexistent") is None

    def test_returns_none_for_none_value(self) -> None:
        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()
        app.state.my_attr = None
        assert _get_state_value(app, "my_attr") is None


class TestGetAppSettings:
    def test_returns_settings_from_state(self) -> None:
        from core.config import Settings
        app = MagicMock(spec=FastAPI)
        mock_settings = MagicMock(spec=Settings)
        app.state = MagicMock()
        app.state.settings = mock_settings
        result = get_app_settings(app)
        assert result is mock_settings

    def test_falls_back_to_get_settings_when_state_is_wrong_type(self) -> None:
        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()
        app.state.settings = "not-a-settings-object"
        with patch("app.lifecycle.get_settings") as mock_get:
            mock_get.return_value = MagicMock()
            result = get_app_settings(app)
        mock_get.assert_called_once()
        assert result is mock_get.return_value

    def test_falls_back_when_state_has_no_settings(self) -> None:
        app = MagicMock(spec=FastAPI)
        app.state = MagicMock(spec=[])
        with patch("app.lifecycle.get_settings") as mock_get:
            mock_get.return_value = MagicMock()
            get_app_settings(app)
        mock_get.assert_called_once()


class TestStartupBackend:
    @pytest.mark.asyncio
    async def test_startup_initializes_state(self) -> None:
        from app.lifecycle import startup_backend
        from core.config import Settings

        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()

        mock_settings = MagicMock()
        mock_settings.logging = MagicMock()
        mock_settings.database = MagicMock()
        mock_settings.storage = MagicMock()
        mock_settings.app = MagicMock()
        mock_settings.app.app_name = "TestApp"
        mock_settings.app.app_version = "1.0"
        mock_settings.app.debug = False

        mock_storage = AsyncMock()
        mock_storage.ensure_buckets_ready = AsyncMock()
        mock_storage.client = AsyncMock()

        with (
            patch("app.lifecycle.get_settings", return_value=mock_settings),
            patch("app.lifecycle.setup_logging"),
            patch("app.lifecycle.silence_noisy_loggers"),
            patch("app.lifecycle.configure_root_exception_logging"),
            patch("app.lifecycle.is_db_client_initialized", return_value=False),
            patch("app.lifecycle.init_db_client"),
            patch("app.lifecycle.ping_database", new_callable=AsyncMock),
            patch("app.lifecycle.get_storage_service", return_value=mock_storage),
            patch("app.lifecycle.get_health_service", return_value=MagicMock()),
        ):
            await startup_backend(app)

        assert app.state.settings is mock_settings
        assert app.state.started_at is not None
        assert app.state.storage_service is mock_storage

    @pytest.mark.asyncio
    async def test_startup_skips_db_init_if_already_initialized(self) -> None:
        from app.lifecycle import startup_backend

        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()

        mock_storage = AsyncMock()
        mock_storage.ensure_buckets_ready = AsyncMock()
        mock_storage.client = AsyncMock()

        with (
            patch("app.lifecycle.get_settings", return_value=MagicMock(
                logging=MagicMock(), database=MagicMock(), storage=MagicMock(),
                app=MagicMock(app_name="App", app_version="1", debug=False),
            )),
            patch("app.lifecycle.setup_logging"),
            patch("app.lifecycle.silence_noisy_loggers"),
            patch("app.lifecycle.configure_root_exception_logging"),
            patch("app.lifecycle.is_db_client_initialized", return_value=True),
            patch("app.lifecycle.init_db_client") as mock_init,
            patch("app.lifecycle.ping_database", new_callable=AsyncMock),
            patch("app.lifecycle.get_storage_service", return_value=mock_storage),
            patch("app.lifecycle.get_health_service", return_value=MagicMock()),
        ):
            await startup_backend(app)

        mock_init.assert_not_called()

    @pytest.mark.asyncio
    async def test_startup_failure_cleans_up(self) -> None:
        from app.lifecycle import startup_backend

        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()

        with (
            patch("app.lifecycle.get_settings", return_value=MagicMock(
                logging=MagicMock(), database=MagicMock(), storage=MagicMock(),
                app=MagicMock(app_name="App", app_version="1", debug=False),
            )),
            patch("app.lifecycle.setup_logging"),
            patch("app.lifecycle.silence_noisy_loggers"),
            patch("app.lifecycle.configure_root_exception_logging"),
            patch("app.lifecycle.is_db_client_initialized", return_value=False),
            patch("app.lifecycle.init_db_client"),
            patch("app.lifecycle.ping_database", new_callable=AsyncMock, side_effect=RuntimeError("DB unavailable")),
            patch("app.lifecycle.shutdown_storage_executor"),
            patch("app.lifecycle.is_db_client_initialized", return_value=False),
        ):
            with pytest.raises(RuntimeError, match="DB unavailable"):
                await startup_backend(app)


class TestShutdownBackend:
    @pytest.mark.asyncio
    async def test_shutdown_clears_state(self) -> None:
        from app.lifecycle import shutdown_backend

        app = MagicMock(spec=FastAPI)
        app.state = MagicMock()

        mock_storage = AsyncMock()
        mock_storage.client = AsyncMock()
        mock_storage.client.close = AsyncMock()
        app.state.storage_service = mock_storage
        app.state.health_service = MagicMock()

        with (
            patch("app.lifecycle.shutdown_storage_executor"),
            patch("app.lifecycle.is_db_client_initialized", return_value=False),
        ):
            await shutdown_backend(app)

        assert app.state.storage_service is None
        assert app.state.health_service is None

    @pytest.mark.asyncio
    async def test_shutdown_with_no_storage(self) -> None:
        from app.lifecycle import shutdown_backend

        app = MagicMock(spec=FastAPI)
        app.state = MagicMock(spec=[])

        with (
            patch("app.lifecycle.shutdown_storage_executor"),
            patch("app.lifecycle.is_db_client_initialized", return_value=False),
        ):
            await shutdown_backend(app)  # Не должно выбрасывать исключение


class TestSafeShutdownResources:
    @pytest.mark.asyncio
    async def test_storage_close_error_is_logged_not_raised(self) -> None:
        from app.lifecycle import _safe_shutdown_resources

        mock_storage = AsyncMock()
        mock_storage.client = AsyncMock()
        mock_storage.client.close = AsyncMock(
            side_effect=RuntimeError("storage boom")
        )

        with (
            patch("app.lifecycle.shutdown_storage_executor"),
            patch("app.lifecycle.is_db_client_initialized", return_value=False),
            patch("app.lifecycle.logger") as mock_logger,
        ):
            # Не должно выбрасывать исключение, даже если закрытие хранилища упало.
            await _safe_shutdown_resources(mock_storage)

        mock_storage.client.close.assert_awaited_once()
        mock_logger.warning.assert_called_once()
        call = mock_logger.warning.call_args
        assert "storage client" in call.args[0]
        assert call.kwargs["extra"]["reason"] == "storage boom"
        assert call.kwargs["extra"]["error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_executor_shutdown_error_is_logged_not_raised(self) -> None:
        from app.lifecycle import _safe_shutdown_resources

        with (
            patch(
                "app.lifecycle.shutdown_storage_executor",
                side_effect=ValueError("executor boom"),
            ),
            patch("app.lifecycle.is_db_client_initialized", return_value=False),
            patch("app.lifecycle.logger") as mock_logger,
        ):
            await _safe_shutdown_resources(None)

        mock_logger.warning.assert_called_once()
        call = mock_logger.warning.call_args
        assert "пул потоков" in call.args[0]
        assert call.kwargs["extra"]["reason"] == "executor boom"
        assert call.kwargs["extra"]["error_type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_db_close_called_when_initialized(self) -> None:
        from app.lifecycle import _safe_shutdown_resources

        with (
            patch("app.lifecycle.shutdown_storage_executor"),
            patch("app.lifecycle.is_db_client_initialized", return_value=True),
            patch(
                "app.lifecycle.close_db_client", new_callable=AsyncMock
            ) as mock_close,
        ):
            await _safe_shutdown_resources(None)

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_db_close_error_is_logged_not_raised(self) -> None:
        from app.lifecycle import _safe_shutdown_resources

        with (
            patch("app.lifecycle.shutdown_storage_executor"),
            patch("app.lifecycle.is_db_client_initialized", return_value=True),
            patch(
                "app.lifecycle.close_db_client",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db boom"),
            ),
            patch("app.lifecycle.logger") as mock_logger,
        ):
            await _safe_shutdown_resources(None)

        mock_logger.warning.assert_called_once()
        call = mock_logger.warning.call_args
        assert "клиент базы данных" in call.args[0]
        assert call.kwargs["extra"]["reason"] == "db boom"
        assert call.kwargs["extra"]["error_type"] == "RuntimeError"
