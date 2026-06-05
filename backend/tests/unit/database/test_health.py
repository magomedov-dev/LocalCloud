"""Модульные тесты проверки состояния БД: соединение, задержка, агрегированный
статус здоровья и формирование отчёта."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.exceptions import (
    DatabaseConnectionError,
    DatabaseHealthCheckError,
    DatabaseTimeoutError,
)
from database.health import (
    DatabaseHealthStatus,
    check_database_connection,
    check_database_health,
    check_database_latency,
    get_database_health_report,
)


class TestDatabaseHealthStatus:
    def test_defaults(self) -> None:
        status = DatabaseHealthStatus()
        assert status.component == "database"
        assert status.status == "healthy"
        assert status.connection is True
        assert status.is_success is True

    def test_is_success_true_for_healthy_with_connection(self) -> None:
        status = DatabaseHealthStatus(status="healthy", connection=True)
        assert status.is_success is True

    def test_is_success_false_for_degraded(self) -> None:
        status = DatabaseHealthStatus(status="degraded", connection=True)
        assert status.is_success is False

    def test_is_success_false_for_no_connection(self) -> None:
        status = DatabaseHealthStatus(status="healthy", connection=False)
        assert status.is_success is False

    def test_is_success_false_for_unavailable_no_connection(self) -> None:
        status = DatabaseHealthStatus(status="unavailable", connection=False)
        assert status.is_success is False

    def test_custom_fields(self) -> None:
        status = DatabaseHealthStatus(
            status="degraded",
            connection=True,
            latency_ms=250.5,
            latency_threshold_ms=500.0,
            error="DatabaseTimeoutError",
            message="Latency exceeded threshold",
        )
        assert status.latency_ms == 250.5
        assert status.latency_threshold_ms == 500.0
        assert status.error == "DatabaseTimeoutError"

    def test_is_frozen(self) -> None:
        status = DatabaseHealthStatus()
        with pytest.raises((AttributeError, TypeError)):
            status.status = "degraded"  # type: ignore[misc]


class TestCheckDatabaseConnection:
    @pytest.mark.asyncio
    async def test_success_returns_true(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one = MagicMock(return_value=1)
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with patch("database.health.get_async_session_factory", return_value=mock_factory):
            result = await check_database_connection()

        assert result is True

    @pytest.mark.asyncio
    async def test_unexpected_result_raises_connection_error(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one = MagicMock(return_value=2)  # неожиданное значение
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with patch("database.health.get_async_session_factory", return_value=mock_factory):
            with pytest.raises(DatabaseConnectionError):
                await check_database_connection()

    @pytest.mark.asyncio
    async def test_sqlalchemy_timeout_raises_timeout_error(self) -> None:
        from sqlalchemy.exc import TimeoutError as SATimeout

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=SATimeout())

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with patch("database.health.get_async_session_factory", return_value=mock_factory):
            with pytest.raises(DatabaseTimeoutError):
                await check_database_connection()

    @pytest.mark.asyncio
    async def test_sqlalchemy_error_raises_connection_error(self) -> None:
        from sqlalchemy.exc import SQLAlchemyError
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with patch("database.health.get_async_session_factory", return_value=mock_factory):
            with pytest.raises(DatabaseConnectionError):
                await check_database_connection()

    @pytest.mark.asyncio
    async def test_dbapi_error_raises_connection_error(self) -> None:
        from sqlalchemy.exc import DBAPIError

        exc = DBAPIError("stmt", {}, Exception("boom"), connection_invalidated=True)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=exc)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with patch("database.health.get_async_session_factory", return_value=mock_factory):
            with pytest.raises(DatabaseConnectionError) as exc_info:
                await check_database_connection()

        assert exc_info.value.details["connection_invalidated"] is True


class TestCheckDatabaseLatency:
    @pytest.mark.asyncio
    async def test_returns_float_milliseconds(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with patch("database.health.get_async_session_factory", return_value=mock_factory):
            latency = await check_database_latency()

        assert isinstance(latency, float)
        assert latency >= 0

    @pytest.mark.asyncio
    async def test_sqlalchemy_error_raises_health_check_error(self) -> None:
        from sqlalchemy.exc import SQLAlchemyError
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("fail"))

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with patch("database.health.get_async_session_factory", return_value=mock_factory):
            with pytest.raises(DatabaseHealthCheckError):
                await check_database_latency()

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self) -> None:
        from sqlalchemy.exc import TimeoutError as SATimeout

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=SATimeout())

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with patch("database.health.get_async_session_factory", return_value=mock_factory):
            with pytest.raises(DatabaseTimeoutError):
                await check_database_latency()

    @pytest.mark.asyncio
    async def test_dbapi_error_raises_health_check_error(self) -> None:
        from sqlalchemy.exc import DBAPIError

        exc = DBAPIError("stmt", {}, Exception("boom"), connection_invalidated=False)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=exc)

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with patch("database.health.get_async_session_factory", return_value=mock_factory):
            with pytest.raises(DatabaseHealthCheckError) as exc_info:
                await check_database_latency()

        assert exc_info.value.details["connection_invalidated"] is False


class TestCheckDatabaseHealth:
    @pytest.mark.asyncio
    async def test_healthy_status_returned(self) -> None:
        with (
            patch("database.health.check_database_connection", AsyncMock(return_value=True)),
            patch("database.health.check_database_latency", AsyncMock(return_value=50.0)),
        ):
            result = await check_database_health(latency_threshold_ms=500.0)

        assert result.status == "healthy"
        assert result.connection is True
        assert result.latency_ms == 50.0

    @pytest.mark.asyncio
    async def test_latency_above_threshold_raises_timeout(self) -> None:
        with (
            patch("database.health.check_database_connection", AsyncMock(return_value=True)),
            patch("database.health.check_database_latency", AsyncMock(return_value=600.0)),
        ):
            with pytest.raises(DatabaseTimeoutError):
                await check_database_health(latency_threshold_ms=500.0)

    @pytest.mark.asyncio
    async def test_no_threshold_does_not_raise(self) -> None:
        with (
            patch("database.health.check_database_connection", AsyncMock(return_value=True)),
            patch("database.health.check_database_latency", AsyncMock(return_value=9999.0)),
        ):
            result = await check_database_health(latency_threshold_ms=None)

        assert result.status == "healthy"

    @pytest.mark.asyncio
    async def test_connection_error_raises_health_check_error(self) -> None:
        with patch(
            "database.health.check_database_connection",
            AsyncMock(side_effect=DatabaseConnectionError("no connection")),
        ):
            with pytest.raises(DatabaseHealthCheckError):
                await check_database_health()

    @pytest.mark.asyncio
    async def test_health_check_error_is_reraised(self) -> None:
        exc = DatabaseHealthCheckError("latency failed")
        with (
            patch("database.health.check_database_connection", AsyncMock(return_value=True)),
            patch("database.health.check_database_latency", AsyncMock(side_effect=exc)),
        ):
            with pytest.raises(DatabaseHealthCheckError) as exc_info:
                await check_database_health()

        assert exc_info.value is exc

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped_in_health_check_error(self) -> None:
        with (
            patch("database.health.check_database_connection", AsyncMock(return_value=True)),
            patch(
                "database.health.check_database_latency",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            with pytest.raises(DatabaseHealthCheckError) as exc_info:
                await check_database_health()

        assert exc_info.value.details["error_type"] == "RuntimeError"


class TestGetDatabaseHealthReport:
    @pytest.mark.asyncio
    async def test_healthy_returns_healthy_status(self) -> None:
        healthy = DatabaseHealthStatus(status="healthy", connection=True, latency_ms=10.0)
        with patch("database.health.check_database_health", AsyncMock(return_value=healthy)):
            result = await get_database_health_report()

        assert result.status == "healthy"
        assert result.is_success is True

    @pytest.mark.asyncio
    async def test_timeout_returns_degraded_when_not_raise(self) -> None:
        exc = DatabaseTimeoutError(
            "Latency too high",
            details={"latency_ms": 600.0, "latency_threshold_ms": 500.0},
        )
        with patch("database.health.check_database_health", AsyncMock(side_effect=exc)):
            result = await get_database_health_report(raise_on_error=False)

        assert result.status == "degraded"
        assert result.connection is True

    @pytest.mark.asyncio
    async def test_timeout_raises_when_raise_on_error(self) -> None:
        exc = DatabaseTimeoutError("latency")
        with patch("database.health.check_database_health", AsyncMock(side_effect=exc)):
            with pytest.raises(DatabaseTimeoutError):
                await get_database_health_report(raise_on_error=True)

    @pytest.mark.asyncio
    async def test_connection_error_returns_unavailable(self) -> None:
        exc = DatabaseConnectionError("no connection")
        with patch("database.health.check_database_health", AsyncMock(side_effect=exc)):
            result = await get_database_health_report(raise_on_error=False)

        assert result.status == "unavailable"
        assert result.connection is False

    @pytest.mark.asyncio
    async def test_health_check_error_returns_unavailable(self) -> None:
        exc = DatabaseHealthCheckError("check failed")
        with patch("database.health.check_database_health", AsyncMock(side_effect=exc)):
            result = await get_database_health_report(raise_on_error=False)

        assert result.status == "unavailable"
        assert result.connection is False

    @pytest.mark.asyncio
    async def test_health_check_error_raises_when_raise_on_error(self) -> None:
        exc = DatabaseHealthCheckError("check failed")
        with patch("database.health.check_database_health", AsyncMock(side_effect=exc)):
            with pytest.raises(DatabaseHealthCheckError):
                await get_database_health_report(raise_on_error=True)

    @pytest.mark.asyncio
    async def test_connection_error_raises_when_raise_on_error(self) -> None:
        exc = DatabaseConnectionError("no connection")
        with patch("database.health.check_database_health", AsyncMock(side_effect=exc)):
            with pytest.raises(DatabaseConnectionError):
                await get_database_health_report(raise_on_error=True)
