"""Модульные тесты схем проверки здоровья сервиса."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from database.models.enums import HealthStatus
from schemas.health import (
    ApplicationHealthRead,
    ComponentHealthRead,
    DatabaseHealthRead,
    HealthCheckResponse,
    LivenessResponse,
    ReadinessResponse,
    StorageHealthRead,
    normalize_health_status,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestNormalizeHealthStatus:
    """Тесты нормализации статуса здоровья."""

    def test_passthrough_enum(self):
        assert normalize_health_status(HealthStatus.OK) is HealthStatus.OK

    @pytest.mark.parametrize("value", ["ok", "healthy", "success", "available", " OK "])
    def test_ok_synonyms(self, value):
        assert normalize_health_status(value) == HealthStatus.OK

    @pytest.mark.parametrize("value", ["degraded", "warning", "slow"])
    def test_degraded_synonyms(self, value):
        assert normalize_health_status(value) == HealthStatus.DEGRADED

    @pytest.mark.parametrize(
        "value", ["unavailable", "unhealthy", "failed", "failure", "error"]
    )
    def test_unavailable_synonyms(self, value):
        assert normalize_health_status(value) == HealthStatus.UNAVAILABLE

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            normalize_health_status("bogus")


class TestComponentHealthRead:
    """Тесты схемы здоровья компонента."""

    def test_valid_minimal(self):
        r = ComponentHealthRead(component="database", status="ok")
        assert r.status == HealthStatus.OK
        assert r.connection is None

    def test_status_normalized_from_synonym(self):
        r = ComponentHealthRead(component="db", status="healthy")
        assert r.status == HealthStatus.OK

    def test_text_fields_normalized(self):
        r = ComponentHealthRead(
            component="  db  ", status="ok", error="  err  ", message="  msg  "
        )
        assert r.component == "db"
        assert r.error == "err"
        assert r.message == "msg"

    def test_text_blank_becomes_none(self):
        r = ComponentHealthRead(component="db", status="ok", error="   ")
        assert r.error is None

    def test_negative_latency_raises(self):
        with pytest.raises(ValidationError):
            ComponentHealthRead(component="db", status="ok", latency_ms=-1)

    def test_zero_threshold_raises(self):
        with pytest.raises(ValidationError):
            ComponentHealthRead(component="db", status="ok", latency_threshold_ms=0)

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            ComponentHealthRead(component="db", status="weird")

    def test_component_too_long_raises(self):
        with pytest.raises(ValidationError):
            ComponentHealthRead(component="a" * 129, status="ok")


class TestDatabaseHealthRead:
    """Тесты схемы здоровья базы данных."""

    def test_default_component(self):
        r = DatabaseHealthRead(status="ok")
        assert r.component == "database"
        assert r.connection is None

    def test_status_normalized(self):
        r = DatabaseHealthRead(status="error")
        assert r.status == HealthStatus.UNAVAILABLE


class TestStorageHealthRead:
    """Тесты схемы здоровья хранилища."""

    def test_valid(self):
        r = StorageHealthRead(status="ok", connection_ok=True)
        assert r.component == "storage"
        assert r.bucket_access_ok is None

    def test_state_dict_shape(self):
        r = StorageHealthRead.model_validate(
            {"state": "degraded", "connection_ok": True}
        )
        assert r.status == HealthStatus.DEGRADED
        assert r.component == "storage"

    def test_state_object_shape(self):
        obj = SimpleNamespace(
            state="ok",
            checked_at=NOW,
            connection_ok=True,
            bucket_access_ok=True,
            read_write_ok=True,
            latency_ms=1.5,
            latency_threshold_ms=None,
            details=None,
        )
        r = StorageHealthRead.model_validate(obj)
        assert r.status == HealthStatus.OK
        assert r.connection_ok is True
        assert r.read_write_ok is True

    def test_object_without_state_falls_back(self):
        obj = SimpleNamespace(status="ok", connection_ok=False)
        r = StorageHealthRead.model_validate(obj)
        assert r.status == HealthStatus.OK
        assert r.connection_ok is False

    def test_status_key_dict_passthrough(self):
        r = StorageHealthRead.model_validate(
            {"status": "ok", "connection_ok": True, "component": "storage"}
        )
        assert r.status == HealthStatus.OK

    def test_connection_ok_required(self):
        with pytest.raises(ValidationError):
            StorageHealthRead(status="ok")


class TestApplicationHealthRead:
    """Тесты схемы здоровья приложения."""

    def test_valid_defaults(self):
        r = ApplicationHealthRead(app_name="LocalCloud", app_version="0.1.0", checked_at=NOW)
        assert r.component == "application"
        assert r.status == HealthStatus.OK

    def test_status_normalized(self):
        r = ApplicationHealthRead(
            app_name="X", app_version="1", checked_at=NOW, status="degraded"
        )
        assert r.status == HealthStatus.DEGRADED

    def test_app_name_required(self):
        with pytest.raises(ValidationError):
            ApplicationHealthRead(app_version="1", checked_at=NOW)

    def test_empty_app_name_raises(self):
        with pytest.raises(ValidationError):
            ApplicationHealthRead(app_name="", app_version="1", checked_at=NOW)

    def test_negative_uptime_raises(self):
        with pytest.raises(ValidationError):
            ApplicationHealthRead(
                app_name="X", app_version="1", checked_at=NOW, uptime_seconds=-1
            )


class TestHealthCheckResponse:
    """Тесты схемы общего ответа проверки здоровья."""

    def test_valid_minimal(self):
        r = HealthCheckResponse(
            app_name="LocalCloud", app_version="0.1.0", status="ok", checked_at=NOW
        )
        assert r.status == HealthStatus.OK
        assert r.components == []
        assert r.application is None

    def test_status_normalized(self):
        r = HealthCheckResponse(
            app_name="X", app_version="1", status="unhealthy", checked_at=NOW
        )
        assert r.status == HealthStatus.UNAVAILABLE

    def test_nested_components(self):
        r = HealthCheckResponse(
            app_name="X",
            app_version="1",
            status="ok",
            checked_at=NOW,
            database=DatabaseHealthRead(status="ok"),
            storage=StorageHealthRead(status="ok", connection_ok=True),
            components=[ComponentHealthRead(component="cache", status="ok")],
        )
        assert r.database.component == "database"
        assert len(r.components) == 1

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            HealthCheckResponse(
                app_name="X", app_version="1", status="weird", checked_at=NOW
            )


class TestReadinessResponse:
    """Тесты схемы ответа о готовности."""

    def test_valid(self):
        r = ReadinessResponse(
            app_name="X", app_version="1", status="ok", ready=True, checked_at=NOW
        )
        assert r.ready is True
        assert r.status == HealthStatus.OK

    def test_status_normalized(self):
        r = ReadinessResponse(
            app_name="X", app_version="1", status="degraded", ready=False, checked_at=NOW
        )
        assert r.status == HealthStatus.DEGRADED

    def test_ready_required(self):
        with pytest.raises(ValidationError):
            ReadinessResponse(app_name="X", app_version="1", status="ok", checked_at=NOW)


class TestLivenessResponse:
    """Тесты схемы ответа о жизнеспособности."""

    def test_valid(self):
        r = LivenessResponse(
            app_name="X", app_version="1", status="ok", alive=True, checked_at=NOW
        )
        assert r.alive is True

    def test_status_normalized(self):
        r = LivenessResponse(
            app_name="X", app_version="1", status="failed", alive=False, checked_at=NOW
        )
        assert r.status == HealthStatus.UNAVAILABLE

    def test_negative_uptime_raises(self):
        with pytest.raises(ValidationError):
            LivenessResponse(
                app_name="X",
                app_version="1",
                status="ok",
                alive=True,
                checked_at=NOW,
                uptime_seconds=-1,
            )
