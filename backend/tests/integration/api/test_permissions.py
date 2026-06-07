"""Интеграционные тесты эндпоинтов /api/v1/permissions (права доступа)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_permissions_service_dependency
from api.v1.permissions import RequireShareNodeDependency
from security.dependencies.users import get_current_active_user
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _permission_read_dict(perm_id: uuid.UUID | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(perm_id or uuid.uuid4()),
        "node_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "subject_type": "user",
        "permission_level": "read",
        "granted_by": None,
        "can_read": True,
        "can_download": True,
        "can_write": False,
        "can_delete": False,
        "can_share": False,
        "created_at": now,
    }


def _permission_list_item_dict() -> dict[str, Any]:
    return _permission_read_dict()


def _page_response(items: list[Any]) -> dict[str, Any]:
    count = len(items)
    return {
        "items": items,
        "meta": {"limit": 50, "offset": 0, "total": count, "count": count},
    }


# ---------------------------------------------------------------------------
# GET /permissions/nodes/{node_id}
# ---------------------------------------------------------------------------


class TestListNodePermissions:
    def test_returns_200_for_authorized_user(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_svc = AsyncMock()
        mock_svc.list_node_permissions = AsyncMock(
            return_value=_page_response([_permission_list_item_dict()])
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[RequireShareNodeDependency.dependency] = lambda: None
        app.dependency_overrides[get_permissions_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/permissions/nodes/{node_id}")
            assert resp.status_code == 200
            mock_svc.list_node_permissions.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(RequireShareNodeDependency.dependency, None)
            app.dependency_overrides.pop(get_permissions_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/permissions/nodes/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /permissions/grant
# ---------------------------------------------------------------------------


class TestGrantPermission:
    def test_returns_201_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()

        mock_svc = AsyncMock()
        mock_svc.grant_permission = AsyncMock(return_value=_permission_read_dict())

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_permissions_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/permissions/grant",
                    json={
                        "node_id": str(uuid.uuid4()),
                        "user_id": str(uuid.uuid4()),
                    },
                )
            assert resp.status_code == 201
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_permissions_service_dependency, None)


# ---------------------------------------------------------------------------
# PATCH /permissions/{permission_id}
# ---------------------------------------------------------------------------


class TestUpdatePermission:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        perm_id = uuid.uuid4()

        mock_svc = AsyncMock()
        mock_svc.update_permission = AsyncMock(
            return_value=_permission_read_dict(perm_id)
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_permissions_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.patch(
                    f"{API_V1}/permissions/{perm_id}",
                    json={"can_write": True},
                )
            assert resp.status_code == 200
            mock_svc.update_permission.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_permissions_service_dependency, None)


# ---------------------------------------------------------------------------
# POST /permissions/revoke
# ---------------------------------------------------------------------------


class TestRevokePermission:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()

        mock_svc = AsyncMock()
        mock_svc.revoke_permission = AsyncMock(return_value=_permission_read_dict())

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_permissions_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/permissions/revoke",
                    json={"permission_id": str(uuid.uuid4())},
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_permissions_service_dependency, None)


# ---------------------------------------------------------------------------
# POST /permissions/check
# ---------------------------------------------------------------------------


class TestCheckPermission:
    def test_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_svc = AsyncMock()
        mock_svc.check_permission = AsyncMock(
            return_value={
                "allowed": True,
                "node_id": str(node_id),
                "action": "read",
            }
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_permissions_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/permissions/check",
                    json={"node_id": str(node_id), "action": "read"},
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_permissions_service_dependency, None)


# ---------------------------------------------------------------------------
# GET /permissions/nodes/{node_id}/effective
# ---------------------------------------------------------------------------


class TestGetEffectivePermissions:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_svc = AsyncMock()
        mock_svc.get_effective_permissions = AsyncMock(
            return_value={"node_id": str(node_id)}
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_permissions_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/permissions/nodes/{node_id}/effective")
            assert resp.status_code == 200
            mock_svc.get_effective_permissions.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_permissions_service_dependency, None)
