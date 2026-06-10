"""Интеграционные тесты эндпоинтов узлов файловой системы (nodes)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import (
    get_nodes_service_dependency,
    get_folders_service_dependency,
    get_downloads_service_dependency,
    get_files_service_dependency,
)
from security.dependencies.users import get_current_active_user
from security.dependencies.nodes import (
    RequireReadNodeDependency,
    RequireWriteNodeDependency,
    RequireDeleteNodeDependency,
)
from services.exceptions import (
    ConflictServiceError,
    NotFoundServiceError,
    PermissionServiceError,
)
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _node_list_item_dict(
    node_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(node_id or uuid.uuid4()),
        "name": "test-node",
        "node_type": "folder",
        "owner_id": str(owner_id or uuid.uuid4()),
        "parent_id": None,
        "path": "/test-node",
        "visibility": "private",
        "is_deleted": False,
        "depth": 0,
        "created_at": now,
        "updated_at": now,
    }


def _page_response(items: list[Any]) -> dict[str, Any]:
    count = len(items)
    return {
        "items": items,
        "meta": {
            "limit": 50,
            "offset": 0,
            "total": count,
            "count": count,
        },
    }


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestListNodes:
    def test_list_nodes_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node = _node_list_item_dict(owner_id=mock_user.id)
        page = _page_response([node])

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.list_nodes = AsyncMock(return_value=page)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = (
            lambda: mock_nodes_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/")
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert data["meta"]["total"] == 1
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)

    def test_list_nodes_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/nodes/")
        assert response.status_code == 401

    def test_list_nodes_empty_returns_200(self) -> None:
        mock_user = _make_mock_user()
        page = _page_response([])

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.list_nodes = AsyncMock(return_value=page)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = (
            lambda: mock_nodes_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/")
            assert response.status_code == 200
            data = response.json()
            assert data["meta"]["total"] == 0
            assert data["items"] == []
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)


class TestSearchNodes:
    def test_search_nodes_returns_200(self) -> None:
        mock_user = _make_mock_user()
        page = _page_response([])

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.search_nodes = AsyncMock(return_value=page)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = (
            lambda: mock_nodes_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/search?query=test")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)

    def test_search_nodes_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/nodes/search?query=test")
        assert response.status_code == 401


class TestGetNodesTree:
    def test_get_tree_returns_200(self) -> None:
        mock_user = _make_mock_user()
        root_id = uuid.uuid4()
        now = datetime.now(tz=timezone.utc).isoformat()
        tree = {
            "id": str(root_id),
            "name": "root",
            "node_type": "folder",
            "owner_id": str(mock_user.id),
            "parent_id": None,
            "path": "/root",
            "visibility": "private",
            "is_deleted": False,
            "depth": 0,
            "created_at": now,
            "updated_at": now,
            "children": [],
        }

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.get_tree = AsyncMock(return_value=tree)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = (
            lambda: mock_nodes_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(
                    f"{API_V1}/nodes/tree",
                    params={"root_node_id": str(root_id)},
                )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)

    def test_get_tree_missing_root_returns_422(self) -> None:
        mock_user = _make_mock_user()
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/tree")
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_tree_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        root_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(
                f"{API_V1}/nodes/tree",
                params={"root_node_id": str(root_id)},
            )
        assert response.status_code == 401


class TestGetNode:
    def test_get_node_returns_200(self) -> None:
        from security.dependencies.nodes import RequireReadNodeDependency
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        now = datetime.now(tz=timezone.utc).isoformat()
        node_read = {
            "id": str(node_id),
            "name": "test-node",
            "node_type": "folder",
            "owner_id": str(mock_user.id),
            "parent_id": None,
            "path": "/test-node",
            "visibility": "private",
            "is_deleted": False,
            "depth": 0,
            "created_at": now,
            "updated_at": now,
        }

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.get_node = AsyncMock(return_value=node_read)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        # Подменяем сам внутренний вызываемый объект зависимости, а не фабрику
        app.dependency_overrides[RequireReadNodeDependency.dependency] = lambda: None
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            app.dependency_overrides.pop(RequireReadNodeDependency.dependency, None)

    def test_get_node_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        node_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/nodes/{node_id}")
        assert response.status_code == 401


class TestDeleteNode:
    def test_delete_node_returns_200(self) -> None:
        from security.dependencies.nodes import RequireDeleteNodeDependency
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        op_response = {
            "node_id": str(node_id),
            "success": True,
            "message": "Node deleted.",
        }

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.delete_node = AsyncMock(return_value=op_response)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        app.dependency_overrides[RequireDeleteNodeDependency.dependency] = lambda: None
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.delete(f"{API_V1}/nodes/{node_id}")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            app.dependency_overrides.pop(RequireDeleteNodeDependency.dependency, None)

    def test_delete_node_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        node_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.delete(f"{API_V1}/nodes/{node_id}")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Дополнительные вспомогательные функции
# ---------------------------------------------------------------------------


def _node_read_dict(
    node_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(node_id or uuid.uuid4()),
        "owner_id": str(owner_id or uuid.uuid4()),
        "parent_id": None,
        "name": "test-node",
        "node_type": "folder",
        "visibility": "private",
        "path": "/test-node",
        "depth": 0,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }


def _op_response(node: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "success": True,
        "node": node,
        "message": "Operation completed.",
    }


def _file_download_response_dict() -> dict[str, Any]:
    expires = datetime.now(tz=timezone.utc).isoformat()
    return {
        "presigned_url": "https://example.com/file?sig=abc",
        "expires_at": expires,
        "method": "GET",
        "headers": {},
        "file_id": str(uuid.uuid4()),
        "filename": "file.bin",
        "size_bytes": 10,
        "mime_type": "application/octet-stream",
    }


def _override_read() -> None:
    app.dependency_overrides[RequireReadNodeDependency.dependency] = lambda: None


def _override_write() -> None:
    app.dependency_overrides[RequireWriteNodeDependency.dependency] = lambda: None


def _clear_node_perm_overrides() -> None:
    app.dependency_overrides.pop(RequireReadNodeDependency.dependency, None)
    app.dependency_overrides.pop(RequireWriteNodeDependency.dependency, None)
    app.dependency_overrides.pop(RequireDeleteNodeDependency.dependency, None)


# ---------------------------------------------------------------------------
# Ветви ошибок get_node
# ---------------------------------------------------------------------------


class TestGetNodeErrors:
    def test_get_node_not_found_returns_404(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.get_node = AsyncMock(
            side_effect=NotFoundServiceError("Node missing.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}")
            assert response.status_code == 404
            assert response.json()["error"] == "not_found"
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_get_node_forbidden_returns_403(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.get_node = AsyncMock(
            side_effect=PermissionServiceError("Denied.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()


# ---------------------------------------------------------------------------
# Обновление узла (update_node)
# ---------------------------------------------------------------------------


class TestUpdateNode:
    def test_update_node_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        node = _node_read_dict(node_id=node_id, owner_id=mock_user.id)

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.update_node = AsyncMock(return_value=_op_response(node))

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.patch(
                    f"{API_V1}/nodes/{node_id}",
                    json={"name": "renamed"},
                )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["node"]["id"] == str(node_id)
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_update_node_recursive_visibility_query(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.update_node = AsyncMock(return_value=_op_response(None))

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.patch(
                    f"{API_V1}/nodes/{node_id}?recursive_visibility=true",
                    json={"visibility": "public"},
                )
            assert response.status_code == 200
            mock_nodes_svc.update_node.assert_awaited_once()
            _, kwargs = mock_nodes_svc.update_node.call_args
            assert kwargs["recursive_visibility"] is True
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_update_node_conflict_returns_409(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.update_node = AsyncMock(
            side_effect=ConflictServiceError("Name taken.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.patch(
                    f"{API_V1}/nodes/{node_id}",
                    json={"name": "dup"},
                )
            assert response.status_code == 409
            assert response.json()["error"] == "conflict_error"
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_update_node_invalid_name_returns_422(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.patch(
                    f"{API_V1}/nodes/{node_id}",
                    json={"name": "bad/name"},
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            _clear_node_perm_overrides()

    def test_update_node_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        node_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.patch(f"{API_V1}/nodes/{node_id}", json={"name": "x"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Переименование узла (rename_node)
# ---------------------------------------------------------------------------


class TestRenameNode:
    def test_rename_node_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        node = _node_read_dict(node_id=node_id, owner_id=mock_user.id)

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.rename_node = AsyncMock(return_value=_op_response(node))

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/nodes/{node_id}/rename",
                    json={"name": "new-name"},
                )
            assert response.status_code == 200
            assert response.json()["success"] is True
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_rename_node_not_found_returns_404(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.rename_node = AsyncMock(
            side_effect=NotFoundServiceError("Missing.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/nodes/{node_id}/rename",
                    json={"name": "new-name"},
                )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_rename_node_invalid_name_returns_422(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/nodes/{node_id}/rename",
                    json={"name": ""},
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            _clear_node_perm_overrides()


# ---------------------------------------------------------------------------
# Перемещение узла (move_node)
# ---------------------------------------------------------------------------


class TestMoveNode:
    def test_move_node_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        target_id = uuid.uuid4()
        node = _node_read_dict(node_id=node_id, owner_id=mock_user.id)

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.move_node = AsyncMock(return_value=_op_response(node))

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/nodes/{node_id}/move",
                    json={"target_parent_id": str(target_id)},
                )
            assert response.status_code == 200
            assert response.json()["success"] is True
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_move_node_to_root_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.move_node = AsyncMock(return_value=_op_response(None))

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/nodes/{node_id}/move",
                    json={},
                )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_move_node_conflict_returns_409(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.move_node = AsyncMock(
            side_effect=ConflictServiceError("Cannot move into descendant.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_write()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/nodes/{node_id}/move",
                    json={"target_parent_id": str(uuid.uuid4())},
                )
            assert response.status_code == 409
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()


# ---------------------------------------------------------------------------
# Ветви ошибок delete_node
# ---------------------------------------------------------------------------


class TestDeleteNodeErrors:
    def test_delete_node_not_found_returns_404(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.delete_node = AsyncMock(
            side_effect=NotFoundServiceError("Missing.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        app.dependency_overrides[RequireDeleteNodeDependency.dependency] = lambda: None
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.delete(f"{API_V1}/nodes/{node_id}?recursive=false")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()


# ---------------------------------------------------------------------------
# Хлебные крошки (breadcrumbs)
# ---------------------------------------------------------------------------


class TestGetNodeBreadcrumbs:
    def test_breadcrumbs_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        crumb = {
            "id": str(node_id),
            "name": "test-node",
            "node_type": "folder",
            "path": "/test-node",
            "depth": 0,
        }

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.get_breadcrumbs = AsyncMock(return_value=[crumb])

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}/breadcrumbs")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert data[0]["id"] == str(node_id)
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_breadcrumbs_include_deleted_query(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.get_breadcrumbs = AsyncMock(return_value=[])

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(
                    f"{API_V1}/nodes/{node_id}/breadcrumbs?include_deleted=true"
                )
            assert response.status_code == 200
            _, kwargs = mock_nodes_svc.get_breadcrumbs.call_args
            assert kwargs["allow_deleted"] is True
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()

    def test_breadcrumbs_not_found_returns_404(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_nodes_svc = AsyncMock()
        mock_nodes_svc.get_breadcrumbs = AsyncMock(
            side_effect=NotFoundServiceError("Missing.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_nodes_service_dependency] = lambda: mock_nodes_svc
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}/breadcrumbs")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_nodes_service_dependency, None)
            _clear_node_perm_overrides()


# ---------------------------------------------------------------------------
# Содержимое папки по узлу
# ---------------------------------------------------------------------------


class TestGetFolderContentByNode:
    def test_content_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        folder_id = uuid.uuid4()
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
        mock_folders_svc.get_folder_content = AsyncMock(return_value=content)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_folders_service_dependency] = (
            lambda: mock_folders_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}/content?limit=10&offset=0")
            assert response.status_code == 200
            assert response.json()["total"] == 0
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_folders_service_dependency, None)
            _clear_node_perm_overrides()

    def test_content_invalid_limit_returns_422(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}/content?limit=0")
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            _clear_node_perm_overrides()

    def test_content_not_found_returns_404(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_folders_svc = AsyncMock()
        mock_folders_svc.get_folder_content = AsyncMock(
            side_effect=NotFoundServiceError("Missing.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_folders_service_dependency] = (
            lambda: mock_folders_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}/content")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_folders_service_dependency, None)
            _clear_node_perm_overrides()


# ---------------------------------------------------------------------------
# Пакетное получение миниатюр
# ---------------------------------------------------------------------------


class TestThumbnailsBatch:
    def test_thumbnails_batch_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.create_thumbnail_urls_batch = AsyncMock(
            return_value={str(node_id): "https://example.com/thumb"}
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/nodes/thumbnails/batch",
                    json={"node_ids": [str(node_id)]},
                )
            assert response.status_code == 200
            data = response.json()
            assert data["thumbnails"][str(node_id)] == "https://example.com/thumb"
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)

    def test_thumbnails_batch_empty_list_returns_422(self) -> None:
        mock_user = _make_mock_user()
        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/nodes/thumbnails/batch",
                    json={"node_ids": []},
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    def test_thumbnails_batch_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(
                f"{API_V1}/nodes/thumbnails/batch",
                json={"node_ids": [str(uuid.uuid4())]},
            )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Одиночная миниатюра
# ---------------------------------------------------------------------------


class TestGetNodeThumbnail:
    def test_thumbnail_returns_200_with_cache_header(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.create_thumbnail_url = AsyncMock(
            return_value=_file_download_response_dict()
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}/thumbnail")
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "private, max-age=240"
            assert response.json()["presigned_url"].startswith("https://")
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)
            _clear_node_perm_overrides()

    def test_thumbnail_not_found_returns_404(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.create_thumbnail_url = AsyncMock(
            side_effect=NotFoundServiceError("Missing.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}/thumbnail")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)
            _clear_node_perm_overrides()


# ---------------------------------------------------------------------------
# Скачивание узла (download_node)
# ---------------------------------------------------------------------------


class TestDownloadNode:
    def test_download_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        file_id = uuid.uuid4()

        mock_files_svc = AsyncMock()
        file_read = MagicMock()
        file_read.id = file_id
        mock_files_svc.get_file = AsyncMock(return_value=file_read)

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.create_file_download_url = AsyncMock(
            return_value=_file_download_response_dict()
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_files_service_dependency] = lambda: mock_files_svc
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/nodes/{node_id}/download")
            assert response.status_code == 200
            assert response.json()["presigned_url"].startswith("https://")
            mock_files_svc.get_file.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_files_service_dependency, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)
            _clear_node_perm_overrides()

    def test_download_not_found_returns_404(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()

        mock_files_svc = AsyncMock()
        mock_files_svc.get_file = AsyncMock(
            side_effect=NotFoundServiceError("Missing.")
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_files_service_dependency] = lambda: mock_files_svc
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/nodes/{node_id}/download")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_files_service_dependency, None)
            _clear_node_perm_overrides()


# ---------------------------------------------------------------------------
# Потоковая отдача узла (stream_node)
# ---------------------------------------------------------------------------


class _FakeStream:
    """Минимальный итерируемый поток, эмулирующий объект HTTPResponse MinIO."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self._chunks)

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        pass


class TestStreamNode:
    def test_stream_full_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        payload = b"hello world"

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.stream_file = AsyncMock(
            return_value=(_FakeStream([payload]), "text/plain", "f.txt", len(payload))
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}/stream")
            assert response.status_code == 200
            assert response.content == payload
            assert response.headers["Accept-Ranges"] == "bytes"
            assert 'inline; filename="f.txt"' in response.headers["Content-Disposition"]
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)
            _clear_node_perm_overrides()

    def test_stream_non_ascii_filename_does_not_crash(self) -> None:
        """Кириллическое имя файла не должно ронять stream (latin-1 заголовки)."""
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        payload = b"data"
        cyrillic = "Книга — Имран.pdf"

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.stream_file = AsyncMock(
            return_value=(_FakeStream([payload]), "application/pdf", cyrillic, len(payload))
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(f"{API_V1}/nodes/{node_id}/stream")
            assert response.status_code == 200
            assert response.content == payload
            disposition = response.headers["Content-Disposition"]
            # ASCII-fallback + RFC 5987 кодирование UTF-8 имени.
            assert "filename=" in disposition
            assert "filename*=UTF-8''" in disposition
            # Заголовок должен быть полностью latin-1-кодируемым.
            disposition.encode("latin-1")
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)
            _clear_node_perm_overrides()

    def test_stream_range_from_zero_returns_206(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        payload = b"0123456789"

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.stream_file = AsyncMock(
            return_value=(_FakeStream([payload]), "video/mp4", "v.mp4", len(payload))
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(
                    f"{API_V1}/nodes/{node_id}/stream",
                    headers={"Range": "bytes=0-4"},
                )
            assert response.status_code == 206
            assert response.headers["Content-Range"] == f"bytes 0-4/{len(payload)}"
            assert response.content == b"01234"
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)
            _clear_node_perm_overrides()

    def test_stream_range_with_offset_reopens_stream(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        full = b"0123456789"

        first_stream = _FakeStream([full])
        second_stream = _FakeStream([b"56789"])

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.stream_file = AsyncMock(
            side_effect=[
                (first_stream, "video/mp4", "v.mp4", len(full)),
                (second_stream, "video/mp4", "v.mp4", len(full)),
            ]
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(
                    f"{API_V1}/nodes/{node_id}/stream",
                    headers={"Range": "bytes=5-9"},
                )
            assert response.status_code == 206
            assert response.headers["Content-Range"] == f"bytes 5-9/{len(full)}"
            assert response.content == b"56789"
            assert first_stream.closed is True
            assert mock_downloads_svc.stream_file.await_count == 2
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)
            _clear_node_perm_overrides()

    def test_stream_range_zero_multichunk_returns_206(self) -> None:
        # Ветка gen_limit: поток отдаёт несколько чанков меньше запрошенной
        # длины, что проверяет ветку `remaining -= len(chunk)`.
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        total = 10
        chunks = [b"01", b"23", b"45", b"67", b"89"]

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.stream_file = AsyncMock(
            return_value=(_FakeStream(chunks), "video/mp4", "v.mp4", total)
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(
                    f"{API_V1}/nodes/{node_id}/stream",
                    headers={"Range": "bytes=0-4"},
                )
            assert response.status_code == 206
            assert response.headers["Content-Range"] == f"bytes 0-4/{total}"
            assert response.content == b"01234"
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)
            _clear_node_perm_overrides()

    def test_stream_malformed_range_ignored_returns_200(self) -> None:
        mock_user = _make_mock_user()
        node_id = uuid.uuid4()
        payload = b"abcdef"

        mock_downloads_svc = AsyncMock()
        mock_downloads_svc.stream_file = AsyncMock(
            return_value=(_FakeStream([payload]), "text/plain", "f.txt", len(payload))
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_downloads_service_dependency] = (
            lambda: mock_downloads_svc
        )
        _override_read()
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.get(
                    f"{API_V1}/nodes/{node_id}/stream",
                    headers={"Range": "bytes=abc-def"},
                )
            assert response.status_code == 200
            assert response.content == payload
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_downloads_service_dependency, None)
            _clear_node_perm_overrides()
