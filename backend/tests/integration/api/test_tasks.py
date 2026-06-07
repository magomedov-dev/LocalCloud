"""Интеграционные тесты эндпоинтов /api/v1/tasks (фоновые задачи)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_tasks_service_dependency
from security.dependencies.users import get_current_active_user
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _task_read_dict(task_id: uuid.UUID | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(task_id or uuid.uuid4()),
        "task_type": "create_folder_archive",
        "status": "pending",
        "priority": "normal",
        "created_by": str(uuid.uuid4()),
        "related_entity_type": None,
        "related_entity_id": None,
        "progress_percent": 0,
        "payload": None,
        "result_data": None,
        "error_message": None,
        "error_code": None,
        "attempts_count": 0,
        "max_attempts": 1,
        "idempotency_key": None,
        "scheduled_at": None,
        "started_at": None,
        "finished_at": None,
        "locked_by": None,
        "locked_until": None,
        "created_at": now,
        "updated_at": now,
    }


def _task_list_item_dict(task_id: uuid.UUID | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(task_id or uuid.uuid4()),
        "task_type": "create_folder_archive",
        "status": "pending",
        "priority": "normal",
        "created_by": None,
        "related_entity_type": None,
        "related_entity_id": None,
        "progress_percent": 0,
        "error_code": None,
        "attempts_count": 0,
        "max_attempts": 1,
        "scheduled_at": None,
        "started_at": None,
        "finished_at": None,
        "created_at": now,
        "updated_at": now,
    }


def _page_response(items: list[Any]) -> dict[str, Any]:
    count = len(items)
    return {
        "items": items,
        "meta": {"limit": 50, "offset": 0, "total": count, "count": count},
    }


# ---------------------------------------------------------------------------
# GET /tasks/
# ---------------------------------------------------------------------------


class TestListTasks:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        page = _page_response([_task_list_item_dict()])

        mock_svc = AsyncMock()
        mock_svc.list_tasks = AsyncMock(return_value=page)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_tasks_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/tasks/")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_tasks_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/tasks/")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}
# ---------------------------------------------------------------------------


class TestGetTask:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        task_id = uuid.uuid4()
        task = _task_read_dict(task_id)

        mock_svc = AsyncMock()
        mock_svc.get_task = AsyncMock(return_value=task)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_tasks_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/tasks/{task_id}")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_tasks_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/tasks/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/cancel
# ---------------------------------------------------------------------------


class TestCancelTask:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        task_id = uuid.uuid4()
        task = _task_read_dict(task_id)

        mock_svc = AsyncMock()
        mock_svc.cancel_task = AsyncMock(return_value=task)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_tasks_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/tasks/{task_id}/cancel",
                    json={"reason": "user requested"},
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_tasks_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                f"{API_V1}/tasks/{uuid.uuid4()}/cancel",
                json={"reason": None},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /tasks/ (create)
# ---------------------------------------------------------------------------


class TestCreateTask:
    def test_returns_201_for_allowed_task_type(self) -> None:
        mock_user = _make_mock_user()
        task = _task_read_dict()

        mock_svc = AsyncMock()
        mock_svc.create_task = AsyncMock(return_value=task)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_tasks_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/tasks/",
                    json={"task_type": "create_folder_archive"},
                )
            assert resp.status_code == 201
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_tasks_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                f"{API_V1}/tasks/",
                json={"task_type": "create_folder_archive"},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/result
# ---------------------------------------------------------------------------


class TestGetTaskResult:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        task_id = uuid.uuid4()
        now = datetime.now(tz=timezone.utc).isoformat()
        result = {
            "task_id": str(task_id),
            "task_type": "create_folder_archive",
            "status": "completed",
            "progress_percent": 100,
            "result_data": None,
            "error_message": None,
            "error_code": None,
            "started_at": now,
            "finished_at": now,
        }

        mock_svc = AsyncMock()
        mock_svc.get_task_result = AsyncMock(return_value=result)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_tasks_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/tasks/{task_id}/result")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_tasks_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/tasks/{uuid.uuid4()}/result")
        assert resp.status_code == 401
