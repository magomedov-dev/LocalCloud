"""Интеграционные тесты CRUD-эндпоинтов папок."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_folders_service_dependency
from security.dependencies.users import get_current_active_user
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _folder_read_dict(
    folder_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    node_id = uuid.uuid4()
    return {
        "id": str(folder_id or uuid.uuid4()),
        "node_id": str(node_id),
        "owner_id": str(owner_id or uuid.uuid4()),
        "name": "Test Folder",
        "description": None,
        "color": None,
        "parent_id": None,
        "path": "/Test Folder",
        "depth": 0,
        "visibility": "private",
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "size": 0,
        "items_count": 0,
    }


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestCreateFolder:
    def test_create_folder_returns_201(self) -> None:
        mock_user = _make_mock_user()
        folder = _folder_read_dict(owner_id=mock_user.id)

        mock_folders_svc = AsyncMock()
        mock_folders_svc.create_folder = AsyncMock(return_value=folder)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_folders_service_dependency] = (
            lambda: mock_folders_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/folders/",
                    json={"name": "Test Folder"},
                )
            assert response.status_code == 201
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_folders_service_dependency, None)

    def test_create_folder_empty_name_returns_422(self) -> None:
        mock_user = _make_mock_user()
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/folders/",
                    json={"name": ""},
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_folder_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(
                f"{API_V1}/folders/",
                json={"name": "My Folder"},
            )
        assert response.status_code == 401

    def test_create_folder_missing_body_returns_422(self) -> None:
        mock_user = _make_mock_user()
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/folders/", json={})
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)


class TestGetFolder:
    def test_get_folder_returns_200(self) -> None:
        mock_user = _make_mock_user()
        folder_id = uuid.uuid4()
        node_id = uuid.uuid4()
        folder = _folder_read_dict(folder_id=folder_id, owner_id=mock_user.id)

        mock_folders_svc = AsyncMock()
        mock_folders_svc.get_folder_node_id = AsyncMock(return_value=node_id)
        mock_folders_svc.get_folder = AsyncMock(return_value=folder)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_folders_service_dependency] = (
            lambda: mock_folders_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/folders/{folder_id}")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_folders_service_dependency, None)

    def test_get_folder_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        folder_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/folders/{folder_id}")
        assert response.status_code == 401


class TestUpdateFolder:
    def test_update_folder_returns_200(self) -> None:
        mock_user = _make_mock_user()
        folder_id = uuid.uuid4()
        node_id = uuid.uuid4()
        folder = _folder_read_dict(folder_id=folder_id, owner_id=mock_user.id)
        folder["name"] = "Updated Folder"

        mock_folders_svc = AsyncMock()
        mock_folders_svc.get_folder_node_id = AsyncMock(return_value=node_id)
        mock_folders_svc.update_folder = AsyncMock(return_value=folder)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_folders_service_dependency] = (
            lambda: mock_folders_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.patch(
                    f"{API_V1}/folders/{folder_id}",
                    json={"name": "Updated Folder"},
                )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_folders_service_dependency, None)

    def test_update_folder_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        folder_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.patch(
                f"{API_V1}/folders/{folder_id}",
                json={"name": "Updated"},
            )
        assert response.status_code == 401


class TestGetFolderContent:
    def test_get_folder_content_returns_200(self) -> None:
        mock_user = _make_mock_user()
        folder_id = uuid.uuid4()
        node_id = uuid.uuid4()
        now = datetime.now(tz=timezone.utc).isoformat()
        content = {
            "folder": {
                "id": str(folder_id),
                "node_id": str(node_id),
                "description": None,
                "color": None,
                "created_at": now,
                "updated_at": now,
                "node": None,
            },
            "items": [],
            "total": 0,
        }

        mock_folders_svc = AsyncMock()
        mock_folders_svc.get_folder_node_id = AsyncMock(return_value=node_id)
        mock_folders_svc.get_folder_content = AsyncMock(return_value=content)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_folders_service_dependency] = (
            lambda: mock_folders_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/folders/{folder_id}/content")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_folders_service_dependency, None)
