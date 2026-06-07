"""Интеграционные тесты эндпоинтов заявок на регистрацию."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_registration_service_dependency
from security.dependencies.users import get_current_active_user, get_current_admin_user
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _registration_request_dict(request_id: uuid.UUID | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(request_id or uuid.uuid4()),
        "email": "newuser@example.com",
        "username": "newuser",
        "status": "pending",
        "review_note": None,
        "reviewed_by": None,
        "reviewed_at": None,
        "created_user_id": None,
        "created_at": now,
        "updated_at": now,
    }


def _decision_response_dict() -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "request": {
            "id": str(uuid.uuid4()),
            "email": "user@example.com",
            "username": "testuser",
            "status": "approved",
            "comment": None,
            "rejection_reason": None,
            "reviewed_at": None,
            "reviewed_by": None,
            "created_user_id": None,
            "created_at": now,
        },
        "created_user_id": None,
        "message": "Request approved.",
    }


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestCreateRegistrationRequest:
    def test_create_registration_request_returns_201(self) -> None:
        reg = _registration_request_dict()

        mock_reg_svc = AsyncMock()
        mock_reg_svc.submit_request = AsyncMock(return_value=reg)

        app.dependency_overrides[get_registration_service_dependency] = (
            lambda: mock_reg_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/registration/requests",
                    json={
                        "email": "newuser@example.com",
                        "username": "newuser",
                        "password": "SecurePass123!",
                    },
                )
            assert response.status_code == 201
        finally:
            app.dependency_overrides.pop(get_registration_service_dependency, None)

    def test_create_registration_request_missing_fields_returns_422(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(
                f"{API_V1}/registration/requests",
                json={"email": "newuser@example.com"},
            )
        assert response.status_code == 422

    def test_create_registration_request_empty_body_returns_422(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(f"{API_V1}/registration/requests", json={})
        assert response.status_code == 422

    def test_create_registration_request_short_password_returns_422(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(
                f"{API_V1}/registration/requests",
                json={
                    "email": "newuser@example.com",
                    "username": "newuser",
                    "password": "short",
                },
            )
        assert response.status_code == 422


class TestListRegistrationRequests:
    def test_list_registration_requests_admin_returns_200(self) -> None:
        mock_admin = _make_mock_user()
        page = {"items": [], "meta": {"limit": 50, "offset": 0, "total": 0, "count": 0}}

        mock_reg_svc = AsyncMock()
        mock_reg_svc.list_requests = AsyncMock(return_value=page)

        app.dependency_overrides[get_current_admin_user] = lambda: mock_admin
        app.dependency_overrides[get_registration_service_dependency] = (
            lambda: mock_reg_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/registration/requests")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_registration_service_dependency, None)

    def test_list_registration_requests_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/registration/requests")
        assert response.status_code == 401


class TestGetRegistrationRequest:
    def test_get_registration_request_admin_returns_200(self) -> None:
        mock_admin = _make_mock_user()
        request_id = uuid.uuid4()
        reg = _registration_request_dict(request_id=request_id)

        mock_reg_svc = AsyncMock()
        mock_reg_svc.get_request = AsyncMock(return_value=reg)

        app.dependency_overrides[get_current_admin_user] = lambda: mock_admin
        app.dependency_overrides[get_registration_service_dependency] = (
            lambda: mock_reg_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(
                    f"{API_V1}/registration/requests/{request_id}"
                )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_registration_service_dependency, None)

    def test_get_registration_request_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        request_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/registration/requests/{request_id}")
        assert response.status_code == 401


class TestApproveRegistrationRequest:
    def test_approve_registration_request_returns_200(self) -> None:
        mock_admin = _make_mock_user()
        request_id = uuid.uuid4()
        decision = _decision_response_dict()
        decision["status"] = "approved"

        mock_reg_svc = AsyncMock()
        mock_reg_svc.approve_request = AsyncMock(return_value=decision)

        app.dependency_overrides[get_current_admin_user] = lambda: mock_admin
        app.dependency_overrides[get_registration_service_dependency] = (
            lambda: mock_reg_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/registration/requests/{request_id}/approve",
                    json={"review_note": "Approved."},
                )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_registration_service_dependency, None)

    def test_approve_registration_request_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        request_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(
                f"{API_V1}/registration/requests/{request_id}/approve",
                json={"review_note": "Approved."},
            )
        assert response.status_code == 401


class TestRejectRegistrationRequest:
    def test_reject_registration_request_returns_200(self) -> None:
        mock_admin = _make_mock_user()
        request_id = uuid.uuid4()
        decision = _decision_response_dict()
        decision["status"] = "rejected"

        mock_reg_svc = AsyncMock()
        mock_reg_svc.reject_request = AsyncMock(return_value=decision)

        app.dependency_overrides[get_current_admin_user] = lambda: mock_admin
        app.dependency_overrides[get_registration_service_dependency] = (
            lambda: mock_reg_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/registration/requests/{request_id}/reject",
                    json={"rejection_reason": "Not eligible."},
                )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_registration_service_dependency, None)


class TestCancelRegistrationRequest:
    def test_cancel_registration_request_returns_200(self) -> None:
        request_id = uuid.uuid4()
        decision = _decision_response_dict()
        decision["status"] = "cancelled"

        mock_reg_svc = AsyncMock()
        mock_reg_svc.cancel_request = AsyncMock(return_value=decision)

        app.dependency_overrides[get_registration_service_dependency] = (
            lambda: mock_reg_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/registration/requests/{request_id}/cancel",
                    json={"reason": "Changed my mind."},
                )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_registration_service_dependency, None)
