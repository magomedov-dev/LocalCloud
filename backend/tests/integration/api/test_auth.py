"""Интеграционные тесты эндпоинтов аутентификации (логин, сессии)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import (
    get_auth_service_dependency,
)
from database.models.enums import SystemRole, UserStatus
from schemas.auth import (
    LoginResponse,
    LogoutResponse,
    RefreshTokenResponse,
)
from schemas.users import CurrentUserRead
from security.cookies import get_auth_cookie_names
from security.dependencies.users import get_current_active_user
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _current_user_read_dict(user_id: uuid.UUID | None = None) -> dict[str, Any]:
    uid = str(user_id or uuid.uuid4())
    return {
        "id": uid,
        "email": "test@example.com",
        "username": "testuser",
        "status": "active",
        "last_login_at": None,
        "role": "user",
    }


def _session_dict(user_id: uuid.UUID | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    later = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "user_id": str(user_id or uuid.uuid4()),
        "status": "active",
        "expires_at": later,
        "revoked_at": None,
        "revoke_reason": None,
        "replaced_by_token_id": None,
        "parent_token_id": None,
        "ip_address": None,
        "user_agent": None,
        "device_name": None,
        "is_active": True,
        "created_at": now,
    }


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestLogin:
    def test_login_success(self) -> None:
        mock_user = _make_mock_user()
        user_read = CurrentUserRead(
            id=mock_user.id,
            email=mock_user.email,
            username=mock_user.username,
            status=UserStatus.ACTIVE,
            role=SystemRole.USER,
        )
        login_resp = LoginResponse(authenticated=True, user=user_read)

        mock_auth_svc = AsyncMock()
        mock_auth_svc.login = AsyncMock(return_value=login_resp)

        app.dependency_overrides[get_auth_service_dependency] = (
            lambda: mock_auth_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/auth/login",
                    json={
                        "email_or_username": "test@example.com",
                        "password": "Password123",
                    },
                )
            assert response.status_code == 200
            data = response.json()
            assert data["authenticated"] is True
            assert data["user"]["email"] == "test@example.com"
        finally:
            app.dependency_overrides.pop(get_auth_service_dependency, None)

    def test_login_empty_body_returns_422(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(f"{API_V1}/auth/login", json={})
        assert response.status_code == 422

    def test_login_missing_password_returns_422(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(
                f"{API_V1}/auth/login",
                json={"email_or_username": "test@example.com"},
            )
        assert response.status_code == 422

    def test_login_missing_email_or_username_returns_422(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(
                f"{API_V1}/auth/login",
                json={"password": "Password123"},
            )
        assert response.status_code == 422


class TestRefresh:
    def test_refresh_success(self) -> None:
        mock_user = _make_mock_user()
        user_read = CurrentUserRead(
            id=mock_user.id,
            email=mock_user.email,
            username=mock_user.username,
            status=UserStatus.ACTIVE,
            role=SystemRole.USER,
        )
        refresh_resp = RefreshTokenResponse(authenticated=True, user=user_read)

        mock_auth_svc = AsyncMock()
        mock_auth_svc.refresh_session = AsyncMock(return_value=refresh_resp)

        app.dependency_overrides[get_auth_service_dependency] = (
            lambda: mock_auth_svc
        )
        try:
            # Имя refresh-cookie берём из настроек (оно конфигурируется через
            # окружение), иначе эндпоинт не найдёт cookie и вернёт 401.
            refresh_cookie = get_auth_cookie_names().refresh
            with TestClient(app, raise_server_exceptions=False) as c:
                c.cookies.set(refresh_cookie, "fake-refresh-token")
                response = c.post(f"{API_V1}/auth/refresh")
            assert response.status_code == 200
            data = response.json()
            assert data["authenticated"] is True
        finally:
            app.dependency_overrides.pop(get_auth_service_dependency, None)

    def test_refresh_without_cookie_returns_401(self) -> None:
        # Нет cookie и нет подмены зависимости — ожидается 401
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(f"{API_V1}/auth/refresh")
        assert response.status_code == 401


class TestLogout:
    def test_logout_success(self) -> None:
        logout_resp = LogoutResponse(authenticated=False)

        mock_auth_svc = AsyncMock()
        mock_auth_svc.logout = AsyncMock(return_value=logout_resp)

        app.dependency_overrides[get_auth_service_dependency] = (
            lambda: mock_auth_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/auth/logout")
            assert response.status_code == 200
            data = response.json()
            assert data["authenticated"] is False
        finally:
            app.dependency_overrides.pop(get_auth_service_dependency, None)

    def test_logout_without_cookie_still_succeeds(self) -> None:
        """Выход успешен даже без refresh-cookie."""
        logout_resp = LogoutResponse(authenticated=False)

        mock_auth_svc = AsyncMock()
        mock_auth_svc.logout = AsyncMock(return_value=logout_resp)

        app.dependency_overrides[get_auth_service_dependency] = (
            lambda: mock_auth_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/auth/logout")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_auth_service_dependency, None)


class TestGetMe:
    def test_get_me_authenticated_returns_200(self) -> None:
        mock_user = _make_mock_user()

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/auth/me")
            assert response.status_code == 200
            data = response.json()
            assert data["email"] == "test@example.com"
            assert data["username"] == "testuser"
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_me_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/auth/me")
        assert response.status_code == 401


class TestListSessions:
    def test_list_sessions_returns_200(self) -> None:
        mock_user = _make_mock_user()
        session = _session_dict(mock_user.id)
        mock_auth_svc = AsyncMock()
        mock_auth_svc.list_sessions = AsyncMock(return_value=[session])

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_auth_service_dependency] = (
            lambda: mock_auth_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/auth/sessions")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_auth_service_dependency, None)

    def test_list_sessions_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/auth/sessions")
        assert response.status_code == 401


class TestRevokeSession:
    def test_revoke_session_returns_200(self) -> None:
        mock_user = _make_mock_user()
        session_id = uuid.uuid4()
        session = _session_dict(mock_user.id)
        session["id"] = str(session_id)

        mock_auth_svc = AsyncMock()
        mock_auth_svc.revoke_session = AsyncMock(return_value=session)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_auth_service_dependency] = (
            lambda: mock_auth_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.delete(f"{API_V1}/auth/sessions/{session_id}")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_auth_service_dependency, None)

    def test_revoke_session_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        session_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.delete(f"{API_V1}/auth/sessions/{session_id}")
        assert response.status_code == 401
