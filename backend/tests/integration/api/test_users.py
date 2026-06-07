"""Интеграционные тесты эндпоинтов /api/v1/users (пользователи)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_users_service_dependency
from database.models.enums import UserStatus
from security.dependencies.users import get_current_active_user, get_current_admin_user
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _user_read_dict(user_id: uuid.UUID | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    uid = str(user_id or uuid.uuid4())
    return {
        "id": uid,
        "email": "user@example.com",
        "username": "testuser",
        "status": "active",
        "is_email_verified": True,
        "last_login_at": None,
        "approved_at": None,
        "blocked_at": None,
        "rejected_at": None,
        "deleted_at": None,
        "block_reason": None,
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
    }


def _user_with_roles_dict(user_id: uuid.UUID | None = None) -> dict[str, Any]:
    data = _user_read_dict(user_id)
    data["roles"] = []
    return data


def _page_response(items: list[Any]) -> dict[str, Any]:
    count = len(items)
    return {
        "items": items,
        "meta": {"limit": 50, "offset": 0, "total": count, "count": count},
    }


def _make_admin() -> Any:
    role = object.__new__(type("Role", (), {"code": "admin", "name": "admin"}))
    return _make_mock_user(roles=[role])


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------


class TestGetMe:
    def test_get_me_returns_200(self) -> None:
        mock_user = _make_mock_user()
        from schemas.users import CurrentUserRead

        user_read = CurrentUserRead(
            id=mock_user.id,
            email=mock_user.email,
            username=mock_user.username,
            status=UserStatus.ACTIVE,
            is_email_verified=True,
            roles=[],
        )

        mock_svc = AsyncMock()
        mock_svc.get_current_user_read = AsyncMock(return_value=user_read)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_users_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/users/me")
            assert resp.status_code == 200
            data = resp.json()
            assert data["email"] == mock_user.email
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_users_service_dependency, None)

    def test_get_me_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/users/me")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /users/ (admin list)
# ---------------------------------------------------------------------------


class TestListUsers:
    def test_list_users_returns_200_for_admin(self) -> None:
        admin = _make_mock_user()
        page = _page_response([_user_read_dict()])

        mock_svc = AsyncMock()
        mock_svc.list_users = AsyncMock(return_value=page)

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_users_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/users/")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_users_service_dependency, None)

    def test_list_users_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/users/")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /users/{user_id}
# ---------------------------------------------------------------------------


class TestGetUser:
    def test_get_user_returns_200(self) -> None:
        admin = _make_mock_user()
        target_id = uuid.uuid4()
        user_with_roles = _user_with_roles_dict(target_id)

        mock_svc = AsyncMock()
        mock_svc.get_user_with_roles = AsyncMock(return_value=user_with_roles)

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_users_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/users/{target_id}")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_users_service_dependency, None)

    def test_get_user_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/users/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /users/{user_id}
# ---------------------------------------------------------------------------


class TestAdminUpdateUser:
    def test_admin_update_returns_200(self) -> None:
        admin = _make_mock_user()
        target_id = uuid.uuid4()
        user_data = _user_read_dict(target_id)

        mock_svc = AsyncMock()
        mock_svc.admin_update_user = AsyncMock(return_value=user_data)

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_users_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.patch(f"{API_V1}/users/{target_id}", json={})
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_users_service_dependency, None)

    def test_admin_update_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.patch(f"{API_V1}/users/{uuid.uuid4()}", json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /users/{user_id}
# ---------------------------------------------------------------------------


class TestDeleteUser:
    def test_delete_user_returns_200(self) -> None:
        admin = _make_mock_user()
        target_id = uuid.uuid4()
        user_data = _user_read_dict(target_id)

        mock_svc = AsyncMock()
        mock_svc.delete_user = AsyncMock(return_value=user_data)

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_users_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.delete(f"{API_V1}/users/{target_id}")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_users_service_dependency, None)

    def test_delete_user_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.delete(f"{API_V1}/users/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /me
# ---------------------------------------------------------------------------


class TestUpdateMe:
    def test_update_me_returns_200(self) -> None:
        mock_user = _make_mock_user()
        now = datetime.now(tz=timezone.utc).isoformat()
        user_read = _user_read_dict(mock_user.id)

        mock_svc = AsyncMock()
        mock_svc.update_user = AsyncMock(return_value=user_read)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_users_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.patch(f"{API_V1}/users/me", json={})
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_users_service_dependency, None)

    def test_update_me_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.patch(f"{API_V1}/users/me", json={})
        assert resp.status_code == 401
