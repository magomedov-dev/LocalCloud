"""Интеграционные тесты эндпоинтов корзины (trash)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_trash_service_dependency
from security.dependencies.users import (
    get_current_active_user,
    get_current_admin_user,
)
from services.exceptions import (
    ConflictServiceError,
    NotFoundServiceError,
    PermissionServiceError,
)
from tests.integration.conftest import API_V1, _make_mock_user


def _page(items: list[Any]) -> dict[str, Any]:
    return {
        "items": items,
        "meta": {
            "limit": 50,
            "offset": 0,
            "total": len(items),
            "count": len(items),
        },
    }


def _restore_response() -> dict[str, Any]:
    return {
        "success": True,
        "trash_item": None,
        "node": None,
        "message": "Restored.",
    }


def _purge_response() -> dict[str, Any]:
    return {
        "success": True,
        "requested_count": 1,
        "purged_count": 1,
        "failed_count": 0,
        "purged_trash_item_ids": [str(uuid.uuid4())],
        "failed_trash_item_ids": [],
        "message": "Purged.",
    }


def _set_user(user: Any) -> None:
    app.dependency_overrides[get_current_active_user] = lambda: user


def _set_svc(svc: Any) -> None:
    app.dependency_overrides[get_trash_service_dependency] = lambda: svc


def _clear() -> None:
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(get_current_admin_user, None)
    app.dependency_overrides.pop(get_trash_service_dependency, None)


class TestListTrash:
    def test_returns_200(self) -> None:
        user = _make_mock_user()
        svc = AsyncMock()
        svc.list_trash = AsyncMock(return_value=_page([]))

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/trash/")
            assert response.status_code == 200
            assert response.json()["meta"]["total"] == 0
        finally:
            _clear()

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/trash/")
        assert response.status_code == 401


class TestRestoreTrashItem:
    def test_returns_200(self) -> None:
        user = _make_mock_user()
        item_id = uuid.uuid4()
        svc = AsyncMock()
        svc.restore = AsyncMock(return_value=_restore_response())

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/trash/{item_id}/restore",
                    json={"node_id": str(uuid.uuid4())},
                )
            assert response.status_code == 200
            assert response.json()["success"] is True
            args, kwargs = svc.restore.call_args
            assert args[0].trash_item_id == item_id
        finally:
            _clear()

    def test_missing_identifier_returns_422(self) -> None:
        user = _make_mock_user()
        item_id = uuid.uuid4()
        _set_user(user)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/trash/{item_id}/restore", json={})
            assert response.status_code == 422
        finally:
            _clear()

    def test_not_found_returns_404(self) -> None:
        user = _make_mock_user()
        item_id = uuid.uuid4()
        svc = AsyncMock()
        svc.restore = AsyncMock(side_effect=NotFoundServiceError("Missing."))

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/trash/{item_id}/restore",
                    json={"node_id": str(uuid.uuid4())},
                )
            assert response.status_code == 404
        finally:
            _clear()

    def test_conflict_returns_409(self) -> None:
        user = _make_mock_user()
        item_id = uuid.uuid4()
        svc = AsyncMock()
        svc.restore = AsyncMock(side_effect=ConflictServiceError("Name taken."))

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/trash/{item_id}/restore",
                    json={"node_id": str(uuid.uuid4())},
                )
            assert response.status_code == 409
        finally:
            _clear()


class TestPurgeTrashItem:
    def test_returns_200_no_body(self) -> None:
        user = _make_mock_user()
        item_id = uuid.uuid4()
        svc = AsyncMock()
        svc.purge = AsyncMock(return_value=_purge_response())

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/trash/{item_id}/purge")
            assert response.status_code == 200
            args, _ = svc.purge.call_args
            assert args[0].trash_item_ids == [item_id]
            assert args[0].reason is None
        finally:
            _clear()

    def test_returns_200_with_reason(self) -> None:
        user = _make_mock_user()
        item_id = uuid.uuid4()
        svc = AsyncMock()
        svc.purge = AsyncMock(return_value=_purge_response())

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/trash/{item_id}/purge", json={"reason": "spam"}
                )
            assert response.status_code == 200
            args, _ = svc.purge.call_args
            assert args[0].reason == "spam"
        finally:
            _clear()

    def test_forbidden_returns_403(self) -> None:
        user = _make_mock_user()
        item_id = uuid.uuid4()
        svc = AsyncMock()
        svc.purge = AsyncMock(side_effect=PermissionServiceError("Denied."))

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/trash/{item_id}/purge")
            assert response.status_code == 403
        finally:
            _clear()


class TestEmptyTrash:
    def test_returns_200(self) -> None:
        user = _make_mock_user()
        svc = AsyncMock()
        svc.empty_trash = AsyncMock(return_value=_purge_response())

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/trash/empty", json={"only_expired": False})
            assert response.status_code == 200
            assert response.json()["success"] is True
        finally:
            _clear()

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(f"{API_V1}/trash/empty", json={})
        assert response.status_code == 401


class TestCleanupTrash:
    def test_admin_returns_200(self) -> None:
        admin = _make_mock_user()
        svc = AsyncMock()
        svc.cleanup_expired = AsyncMock(return_value=_purge_response())

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/trash/cleanup", json={"dry_run": True})
            assert response.status_code == 200
            svc.cleanup_expired.assert_awaited_once()
        finally:
            _clear()

    def test_non_admin_denied(self) -> None:
        # Без подмены admin-зависимости реальная цепочка аутентификации
        # отклоняет запрос (нет учётных данных -> 401).
        user = _make_mock_user()
        _set_user(user)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/trash/cleanup", json={})
            assert response.status_code in (401, 403)
        finally:
            _clear()

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(f"{API_V1}/trash/cleanup", json={})
        assert response.status_code == 401
