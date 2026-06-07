"""Интеграционные тесты эндпоинтов проверки работоспособности (health)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_health_service_from_request_dependency
from database.models.enums import HealthStatus
from schemas.health import (
    DatabaseHealthRead,
    HealthCheckResponse,
    LivenessResponse,
    ReadinessResponse,
    StorageHealthRead,
)
from security.dependencies.users import get_current_active_user, get_current_admin_user
from tests.integration.conftest import API_V1, _make_mock_user


@pytest.fixture
def liveness_response() -> LivenessResponse:
    now = datetime.now(tz=timezone.utc)
    return LivenessResponse(
        app_name="LocalCloud",
        app_version="0.1.0",
        status=HealthStatus.OK,
        alive=True,
        checked_at=now,
    )


@pytest.fixture
def readiness_response() -> ReadinessResponse:
    now = datetime.now(tz=timezone.utc)
    return ReadinessResponse(
        app_name="LocalCloud",
        app_version="0.1.0",
        status=HealthStatus.OK,
        ready=True,
        checked_at=now,
    )


@pytest.fixture
def health_check_response() -> HealthCheckResponse:
    now = datetime.now(tz=timezone.utc)
    return HealthCheckResponse(
        app_name="LocalCloud",
        app_version="0.1.0",
        status=HealthStatus.OK,
        checked_at=now,
    )


class TestHealthLiveness:
    def test_get_liveness_returns_200(
        self,
        liveness_response: LivenessResponse,
    ) -> None:
        mock_svc = AsyncMock()
        mock_svc.get_liveness = AsyncMock(return_value=liveness_response)

        app.dependency_overrides[get_health_service_from_request_dependency] = (
            lambda: mock_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/live")
            assert response.status_code == 200
            data = response.json()
            assert data["alive"] is True
            assert data["app_name"] == "LocalCloud"
        finally:
            app.dependency_overrides.pop(
                get_health_service_from_request_dependency, None
            )


class TestHealthReadiness:
    def test_get_readiness_returns_200_when_ready(
        self,
        readiness_response: ReadinessResponse,
    ) -> None:
        mock_svc = AsyncMock()
        mock_svc.get_readiness = AsyncMock(return_value=readiness_response)

        app.dependency_overrides[get_health_service_from_request_dependency] = (
            lambda: mock_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["ready"] is True
        finally:
            app.dependency_overrides.pop(
                get_health_service_from_request_dependency, None
            )

    def test_get_readiness_returns_503_when_not_ready(self) -> None:
        now = datetime.now(tz=timezone.utc)
        not_ready = ReadinessResponse(
            app_name="LocalCloud",
            app_version="0.1.0",
            status=HealthStatus.UNAVAILABLE,
            ready=False,
            checked_at=now,
        )
        mock_svc = AsyncMock()
        mock_svc.get_readiness = AsyncMock(return_value=not_ready)

        app.dependency_overrides[get_health_service_from_request_dependency] = (
            lambda: mock_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["ready"] is False
        finally:
            app.dependency_overrides.pop(
                get_health_service_from_request_dependency, None
            )


class TestHealthCheck:
    def test_get_health_check_returns_200(
        self,
        health_check_response: HealthCheckResponse,
    ) -> None:
        mock_svc = AsyncMock()
        mock_svc.get_health_check = AsyncMock(return_value=health_check_response)

        app.dependency_overrides[get_health_service_from_request_dependency] = (
            lambda: mock_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
        finally:
            app.dependency_overrides.pop(
                get_health_service_from_request_dependency, None
            )

    def test_get_health_check_returns_503_on_degraded(self) -> None:
        now = datetime.now(tz=timezone.utc)
        degraded = HealthCheckResponse(
            app_name="LocalCloud",
            app_version="0.1.0",
            status=HealthStatus.UNAVAILABLE,
            checked_at=now,
        )
        mock_svc = AsyncMock()
        mock_svc.get_health_check = AsyncMock(return_value=degraded)

        app.dependency_overrides[get_health_service_from_request_dependency] = (
            lambda: mock_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/")
            assert response.status_code == 503
        finally:
            app.dependency_overrides.pop(
                get_health_service_from_request_dependency, None
            )


def _override_admin(mock_svc: AsyncMock) -> None:
    admin = _make_mock_user()
    app.dependency_overrides[get_current_active_user] = lambda: admin
    app.dependency_overrides[get_current_admin_user] = lambda: admin
    app.dependency_overrides[get_health_service_from_request_dependency] = (
        lambda: mock_svc
    )


def _clear_admin_overrides() -> None:
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(get_current_admin_user, None)
    app.dependency_overrides.pop(get_health_service_from_request_dependency, None)


def _health_with_database(status_value: HealthStatus) -> HealthCheckResponse:
    now = datetime.now(tz=timezone.utc)
    return HealthCheckResponse(
        app_name="LocalCloud",
        app_version="0.1.0",
        status=HealthStatus.OK,
        checked_at=now,
        database=DatabaseHealthRead(
            component="database",
            status=status_value,
            connection=status_value == HealthStatus.OK,
        ),
    )


def _health_with_storage(status_value: HealthStatus) -> HealthCheckResponse:
    now = datetime.now(tz=timezone.utc)
    return HealthCheckResponse(
        app_name="LocalCloud",
        app_version="0.1.0",
        status=HealthStatus.OK,
        checked_at=now,
        storage=StorageHealthRead(
            component="storage",
            status=status_value,
            connection_ok=status_value == HealthStatus.OK,
        ),
    )


class TestDatabaseHealth:
    def test_returns_200_when_database_ok(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.get_health_check = AsyncMock(
            return_value=_health_with_database(HealthStatus.OK)
        )
        _override_admin(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/database")
            assert response.status_code == 200
            data = response.json()
            assert data["component"] == "database"
            assert data["status"] == "ok"
        finally:
            _clear_admin_overrides()

    def test_returns_503_when_database_unavailable(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.get_health_check = AsyncMock(
            return_value=_health_with_database(HealthStatus.UNAVAILABLE)
        )
        _override_admin(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/database")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unavailable"
        finally:
            _clear_admin_overrides()

    def test_returns_503_when_database_missing(self) -> None:
        now = datetime.now(tz=timezone.utc)
        health = HealthCheckResponse(
            app_name="LocalCloud",
            app_version="0.1.0",
            status=HealthStatus.OK,
            checked_at=now,
            database=None,
        )
        mock_svc = AsyncMock()
        mock_svc.get_health_check = AsyncMock(return_value=health)
        _override_admin(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/database")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unavailable"
            assert data["connection"] is False
        finally:
            _clear_admin_overrides()

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/health/database")
        assert response.status_code == 401


class TestStorageHealth:
    def test_returns_200_when_storage_ok(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.get_health_check = AsyncMock(
            return_value=_health_with_storage(HealthStatus.OK)
        )
        _override_admin(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/storage")
            assert response.status_code == 200
            data = response.json()
            assert data["component"] == "storage"
            assert data["status"] == "ok"
        finally:
            _clear_admin_overrides()

    def test_returns_503_when_storage_unavailable(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.get_health_check = AsyncMock(
            return_value=_health_with_storage(HealthStatus.UNAVAILABLE)
        )
        _override_admin(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/storage")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unavailable"
        finally:
            _clear_admin_overrides()

    def test_returns_503_when_storage_missing(self) -> None:
        now = datetime.now(tz=timezone.utc)
        health = HealthCheckResponse(
            app_name="LocalCloud",
            app_version="0.1.0",
            status=HealthStatus.OK,
            checked_at=now,
            storage=None,
        )
        mock_svc = AsyncMock()
        mock_svc.get_health_check = AsyncMock(return_value=health)
        _override_admin(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/health/storage")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unavailable"
            assert data["connection_ok"] is False
        finally:
            _clear_admin_overrides()

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/health/storage")
        assert response.status_code == 401


class TestRoot:
    def test_root_returns_200(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "backend is running" in data["message"]
