"""Юнит-тесты для HealthService."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.health import DatabaseHealthStatus
from database.models.enums import HealthStatus
from schemas.health import (
    HealthCheckResponse,
    LivenessResponse,
    ReadinessResponse,
)
from services import health as health_module
from services.exceptions import ServiceError
from services.health import (
    DATABASE_DEFAULT_LATENCY_THRESHOLD_MS,
    HealthService,
    _aggregate_status,
    _database_health_to_schema,
    _normalize_datetime,
    _normalize_health_value,
    _storage_health_to_schema,
    get_health_service,
)
from storage import StorageError
from storage.types import StorageHealthState, StorageHealthStatus


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def make_settings(app_name="LocalCloud", app_version="0.1.0", debug=False):
    settings = MagicMock()
    settings.app.app_name = app_name
    settings.app.app_version = app_version
    settings.app.debug = debug
    settings.storage = MagicMock()
    return settings


def make_storage_service(status=None, *, error=None):
    """Собрать мок StorageService, чей health-check возвращает результат или бросает ошибку."""
    svc = MagicMock()
    svc.default_files_bucket = "files"
    health = MagicMock()
    if error is not None:
        health.check_storage_health = AsyncMock(side_effect=error)
    else:
        health.check_storage_health = AsyncMock(
            return_value=status or make_storage_status()
        )
    svc.health = health
    return svc


def make_storage_status(
    state=StorageHealthState.HEALTHY,
    *,
    connection_ok=True,
    bucket_access_ok=True,
    read_write_ok=True,
    latency_ms=10.0,
    latency_threshold_ms=2000.0,
):
    return StorageHealthStatus(
        state=state,
        checked_at=datetime.now(UTC),
        connection_ok=connection_ok,
        bucket_access_ok=bucket_access_ok,
        read_write_ok=read_write_ok,
        latency_ms=latency_ms,
        latency_threshold_ms=latency_threshold_ms,
        details={},
    )


def make_db_status(
    status="healthy",
    *,
    connection=True,
    latency_ms=5.0,
    latency_threshold_ms=1000.0,
    error=None,
    message=None,
):
    return DatabaseHealthStatus(
        component="database",
        status=status,
        connection=connection,
        latency_ms=latency_ms,
        latency_threshold_ms=latency_threshold_ms,
        error=error,
        message=message,
        details={},
    )


def make_service(*, settings=None, storage_status=None, storage_error=None, started_at=None):
    storage = make_storage_service(status=storage_status, error=storage_error)
    return HealthService(
        settings=settings or make_settings(),
        storage_service=storage,
        started_at=started_at,
    ), storage


# ---------------------------------------------------------------------------
# Тесты: get_liveness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_liveness_returns_alive_ok():
    service, _ = make_service()
    result = await service.get_liveness()

    assert isinstance(result, LivenessResponse)
    assert result.alive is True
    assert result.status == HealthStatus.OK
    assert result.app_name == "LocalCloud"
    assert result.app_version == "0.1.0"
    assert result.uptime_seconds >= 0
    assert result.details == {"service": "health"}


@pytest.mark.asyncio
async def test_get_liveness_does_not_touch_dependencies():
    service, storage = make_service()
    await service.get_liveness()
    storage.health.check_storage_health.assert_not_called()


# ---------------------------------------------------------------------------
# Тесты: get_readiness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_readiness_all_healthy(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, storage = make_service(storage_status=make_storage_status())
    result = await service.get_readiness()

    assert isinstance(result, ReadinessResponse)
    assert result.status == HealthStatus.OK
    assert result.ready is True
    assert result.database is not None
    assert result.database.status == HealthStatus.OK
    assert result.storage is not None
    assert result.storage.status == HealthStatus.OK
    db_report.assert_awaited_once()
    storage.health.check_storage_health.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_readiness_database_degraded(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status(status="degraded"))
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, _ = make_service(storage_status=make_storage_status())
    result = await service.get_readiness()

    assert result.status == HealthStatus.DEGRADED
    assert result.ready is False
    assert result.database.status == HealthStatus.DEGRADED


@pytest.mark.asyncio
async def test_get_readiness_storage_unhealthy_is_unavailable(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    status = make_storage_status(
        state=StorageHealthState.UNHEALTHY,
        connection_ok=False,
        bucket_access_ok=False,
        read_write_ok=False,
    )
    service, _ = make_service(storage_status=status)
    result = await service.get_readiness()

    assert result.status == HealthStatus.UNAVAILABLE
    assert result.ready is False
    assert result.storage.status == HealthStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_get_readiness_skip_database_and_storage(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, storage = make_service()
    result = await service.get_readiness(check_database=False, check_storage=False)

    # Нет компонентов -> агрегат в порядке.
    assert result.status == HealthStatus.OK
    assert result.ready is True
    assert result.database is None
    assert result.storage is None
    db_report.assert_not_awaited()
    storage.health.check_storage_health.assert_not_called()
    assert result.details["check_database"] is False
    assert result.details["check_storage"] is False


@pytest.mark.asyncio
async def test_get_readiness_storage_only(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, storage = make_service(storage_status=make_storage_status())
    result = await service.get_readiness(check_database=False)

    assert result.database is None
    assert result.storage is not None
    db_report.assert_not_awaited()
    storage.health.check_storage_health.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_readiness_storage_error_wrapped(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, _ = make_service(storage_error=StorageError("storage down"))

    with pytest.raises(ServiceError):
        await service.get_readiness()


@pytest.mark.asyncio
async def test_get_readiness_database_error_wrapped(monkeypatch):
    db_report = AsyncMock(side_effect=RuntimeError("db exploded"))
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, _ = make_service(storage_status=make_storage_status())

    with pytest.raises(ServiceError):
        await service.get_readiness()


@pytest.mark.asyncio
async def test_get_readiness_service_error_passthrough(monkeypatch):
    err = ServiceError("already wrapped", service="health", operation="x")
    db_report = AsyncMock(side_effect=err)
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, _ = make_service(storage_status=make_storage_status())

    with pytest.raises(ServiceError) as exc_info:
        await service.get_readiness()
    assert exc_info.value is err


@pytest.mark.asyncio
async def test_get_readiness_passes_read_write_flag(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, storage = make_service(storage_status=make_storage_status())
    await service.get_readiness(check_storage_read_write=True)

    _, kwargs = storage.health.check_storage_health.call_args
    assert kwargs["check_read_write"] is True


# ---------------------------------------------------------------------------
# Тесты: get_health_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_health_check_all_healthy(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, storage = make_service(storage_status=make_storage_status())
    result = await service.get_health_check()

    assert isinstance(result, HealthCheckResponse)
    assert result.status == HealthStatus.OK
    assert result.application is not None
    assert result.application.status == HealthStatus.OK
    assert result.database is not None
    assert result.storage is not None
    # компоненты application + database + storage
    assert len(result.components) == 2
    storage.health.check_storage_health.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_health_check_database_unavailable(monkeypatch):
    db_report = AsyncMock(
        return_value=make_db_status(status="unavailable", connection=False)
    )
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, _ = make_service(storage_status=make_storage_status())
    result = await service.get_health_check()

    assert result.status == HealthStatus.UNAVAILABLE
    assert result.database.status == HealthStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_get_health_check_storage_degraded(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    status = make_storage_status(state=StorageHealthState.DEGRADED)
    service, _ = make_service(storage_status=status)
    result = await service.get_health_check()

    assert result.status == HealthStatus.DEGRADED
    assert result.storage.status == HealthStatus.DEGRADED


@pytest.mark.asyncio
async def test_get_health_check_application_only(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, storage = make_service()
    result = await service.get_health_check(check_database=False, check_storage=False)

    assert result.status == HealthStatus.OK
    assert result.database is None
    assert result.storage is None
    assert result.components == []
    db_report.assert_not_awaited()
    storage.health.check_storage_health.assert_not_called()


@pytest.mark.asyncio
async def test_get_health_check_storage_error_wrapped(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, _ = make_service(storage_error=StorageError("boom"))

    with pytest.raises(ServiceError):
        await service.get_health_check()


@pytest.mark.asyncio
async def test_get_health_check_database_error_wrapped(monkeypatch):
    db_report = AsyncMock(side_effect=RuntimeError("kaboom"))
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, _ = make_service(storage_status=make_storage_status())

    with pytest.raises(ServiceError):
        await service.get_health_check()


@pytest.mark.asyncio
async def test_get_health_check_service_error_passthrough(monkeypatch):
    err = ServiceError("already wrapped", service="health", operation="x")
    db_report = AsyncMock(side_effect=err)
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, _ = make_service(storage_status=make_storage_status())

    with pytest.raises(ServiceError) as exc_info:
        await service.get_health_check()
    assert exc_info.value is err


# ---------------------------------------------------------------------------
# Тесты: _get_storage_health / _get_storage_service (lazy creation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_error_logged_and_reraised(monkeypatch):
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service, storage = make_service(storage_error=StorageError("nope"))

    with pytest.raises(ServiceError):
        await service.get_readiness()
    storage.health.check_storage_health.assert_awaited_once()


@pytest.mark.asyncio
async def test_lazy_storage_service_created_when_none(monkeypatch):
    created = make_storage_service(status=make_storage_status())
    get_storage = MagicMock(return_value=created)
    monkeypatch.setattr(health_module, "get_storage_service", get_storage)
    db_report = AsyncMock(return_value=make_db_status())
    monkeypatch.setattr(health_module, "get_database_health_report", db_report)

    service = HealthService(settings=make_settings(), storage_service=None)
    result = await service.get_readiness()

    assert result.storage is not None
    get_storage.assert_called_once()
    # Второй вызов переиспользует кешированный экземпляр.
    await service.get_readiness()
    get_storage.assert_called_once()


# ---------------------------------------------------------------------------
# Тесты: __init__ / uptime
# ---------------------------------------------------------------------------


def test_init_defaults_use_get_settings(monkeypatch):
    fake_settings = make_settings()
    monkeypatch.setattr(health_module, "get_settings", lambda: fake_settings)
    service = HealthService()
    assert service.settings is fake_settings
    assert service._storage_service is None
    assert service.started_at.tzinfo is UTC


def test_uptime_seconds_positive():
    started = datetime.now(UTC) - timedelta(seconds=42)
    service = HealthService(settings=make_settings(), started_at=started)
    uptime = service._uptime_seconds(datetime.now(UTC))
    assert uptime >= 42.0


def test_uptime_seconds_negative_clamped_to_zero():
    started = datetime.now(UTC) + timedelta(seconds=100)
    service = HealthService(settings=make_settings(), started_at=started)
    uptime = service._uptime_seconds(datetime.now(UTC))
    assert uptime == 0.0


def test_init_naive_started_at_normalized_to_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    service = HealthService(settings=make_settings(), started_at=naive)
    assert service.started_at.tzinfo is UTC


# ---------------------------------------------------------------------------
# Тесты: module-level helpers
# ---------------------------------------------------------------------------


def test_aggregate_status_empty_returns_ok():
    assert _aggregate_status([]) == HealthStatus.OK


def test_aggregate_status_ignores_none():
    assert _aggregate_status([None, None]) == HealthStatus.OK
    assert _aggregate_status([None, HealthStatus.OK]) == HealthStatus.OK


def test_aggregate_status_degraded_priority():
    assert (
        _aggregate_status([HealthStatus.OK, HealthStatus.DEGRADED])
        == HealthStatus.DEGRADED
    )


def test_aggregate_status_unavailable_priority():
    assert (
        _aggregate_status(
            [HealthStatus.DEGRADED, HealthStatus.UNAVAILABLE, HealthStatus.OK]
        )
        == HealthStatus.UNAVAILABLE
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        (HealthStatus.OK, HealthStatus.OK),
        ("ok", HealthStatus.OK),
        ("healthy", HealthStatus.OK),
        ("success", HealthStatus.OK),
        ("available", HealthStatus.OK),
        ("degraded", HealthStatus.DEGRADED),
        ("warning", HealthStatus.DEGRADED),
        ("slow", HealthStatus.DEGRADED),
        ("unhealthy", HealthStatus.UNAVAILABLE),
        ("anything-else", HealthStatus.UNAVAILABLE),
    ],
)
def test_normalize_health_value(value, expected):
    assert _normalize_health_value(value) == expected


def test_normalize_datetime_naive():
    naive = datetime(2026, 1, 1, 0, 0, 0)
    result = _normalize_datetime(naive)
    assert result.tzinfo is UTC


def test_normalize_datetime_aware():
    aware = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    result = _normalize_datetime(aware)
    assert result.tzinfo is UTC


def test_database_health_to_schema_uses_fallback_threshold():
    status = make_db_status(status="degraded", latency_threshold_ms=None)
    schema = _database_health_to_schema(status, latency_threshold_ms=777.0)
    assert schema.component == "database"
    assert schema.status == HealthStatus.DEGRADED
    assert schema.latency_threshold_ms == 777.0


def test_database_health_to_schema_keeps_existing_threshold():
    status = make_db_status(latency_threshold_ms=1234.0)
    schema = _database_health_to_schema(status, latency_threshold_ms=999.0)
    assert schema.latency_threshold_ms == 1234.0


def test_database_health_to_schema_empty_details_becomes_none():
    status = make_db_status()
    schema = _database_health_to_schema(
        status, latency_threshold_ms=DATABASE_DEFAULT_LATENCY_THRESHOLD_MS
    )
    assert schema.details is None


def test_storage_health_to_schema():
    status = make_storage_status(state=StorageHealthState.DEGRADED)
    schema = _storage_health_to_schema(status)
    assert schema.component == "storage"
    assert schema.status == HealthStatus.DEGRADED
    assert schema.connection_ok is True


# ---------------------------------------------------------------------------
# Тесты: get_health_service factory
# ---------------------------------------------------------------------------


def test_get_health_service_returns_singleton(monkeypatch):
    monkeypatch.setattr(health_module, "_health_service", None)
    monkeypatch.setattr(health_module, "get_settings", lambda: make_settings())
    first = get_health_service()
    second = get_health_service()
    assert first is second


def test_get_health_service_with_settings_returns_new_instance(monkeypatch):
    monkeypatch.setattr(health_module, "_health_service", None)
    settings = make_settings()
    service = get_health_service(settings=settings)
    assert isinstance(service, HealthService)
    assert service.settings is settings
    # Синглтон не был заполнен.
    assert health_module._health_service is None


def test_get_health_service_with_storage_returns_new_instance(monkeypatch):
    monkeypatch.setattr(health_module, "_health_service", None)
    monkeypatch.setattr(health_module, "get_settings", lambda: make_settings())
    storage = make_storage_service()
    service = get_health_service(storage_service=storage)
    assert service._storage_service is storage
    assert health_module._health_service is None
