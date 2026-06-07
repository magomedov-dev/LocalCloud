"""Интеграционные тесты эндпоинтов скачивания (архивы, массовая выгрузка)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_downloads_service_dependency
from security.dependencies.users import get_current_active_user
from services.exceptions import (
    DownloadServiceError,
    NotFoundServiceError,
    PermissionServiceError,
)
from tests.integration.conftest import API_V1, _make_mock_user


def _file_download_dict() -> dict[str, Any]:
    return {
        "presigned_url": "https://example.com/archive.zip?sig=abc",
        "expires_at": datetime.now(tz=timezone.utc).isoformat(),
        "method": "GET",
        "headers": {},
        "file_id": str(uuid.uuid4()),
        "version_id": None,
        "filename": "archive.zip",
        "size_bytes": 100,
        "mime_type": "application/zip",
    }


def _folder_archive_dict() -> dict[str, Any]:
    return {
        "task_id": str(uuid.uuid4()),
        "status": "pending",
        "message": "Archive task queued.",
    }


def _set_user(user: Any) -> None:
    app.dependency_overrides[get_current_active_user] = lambda: user


def _set_svc(svc: Any) -> None:
    app.dependency_overrides[get_downloads_service_dependency] = lambda: svc


def _clear() -> None:
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(get_downloads_service_dependency, None)


class TestGetArchiveDownloadUrl:
    def test_returns_200(self) -> None:
        user = _make_mock_user()
        task_id = uuid.uuid4()
        svc = AsyncMock()
        svc.create_archive_download_url = AsyncMock(return_value=_file_download_dict())

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/downloads/archive/{task_id}")
            assert response.status_code == 200
            assert response.json()["presigned_url"].startswith("https://")
            _, kwargs = svc.create_archive_download_url.call_args
            assert kwargs["force_download"] is True
        finally:
            _clear()

    def test_query_params_passed(self) -> None:
        user = _make_mock_user()
        task_id = uuid.uuid4()
        svc = AsyncMock()
        svc.create_archive_download_url = AsyncMock(return_value=_file_download_dict())

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/downloads/archive/{task_id}"
                    "?force_download=false&filename=custom.zip"
                )
            assert response.status_code == 200
            _, kwargs = svc.create_archive_download_url.call_args
            assert kwargs["force_download"] is False
            assert kwargs["filename"] == "custom.zip"
        finally:
            _clear()

    def test_not_found_returns_404(self) -> None:
        user = _make_mock_user()
        task_id = uuid.uuid4()
        svc = AsyncMock()
        svc.create_archive_download_url = AsyncMock(
            side_effect=NotFoundServiceError("Task missing.")
        )

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/downloads/archive/{task_id}")
            assert response.status_code == 404
            assert response.json()["error"] == "not_found"
        finally:
            _clear()

    def test_forbidden_returns_403(self) -> None:
        user = _make_mock_user()
        task_id = uuid.uuid4()
        svc = AsyncMock()
        svc.create_archive_download_url = AsyncMock(
            side_effect=PermissionServiceError("Denied.")
        )

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(f"{API_V1}/downloads/archive/{task_id}")
            assert response.status_code == 403
        finally:
            _clear()

    def test_filename_too_long_returns_422(self) -> None:
        user = _make_mock_user()
        task_id = uuid.uuid4()
        _set_user(user)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/downloads/archive/{task_id}?filename={'a' * 256}"
                )
            assert response.status_code == 422
        finally:
            _clear()

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        task_id = uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(f"{API_V1}/downloads/archive/{task_id}")
        assert response.status_code == 401


class TestRequestBulkArchive:
    def test_returns_202(self) -> None:
        user = _make_mock_user()
        svc = AsyncMock()
        svc.request_bulk_archive = AsyncMock(return_value=_folder_archive_dict())

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/downloads/bulk-archive",
                    json={"node_ids": [str(uuid.uuid4())], "archive_name": "a.zip"},
                )
            assert response.status_code == 202
            assert response.json()["status"] == "pending"
        finally:
            _clear()

    def test_forbidden_returns_403(self) -> None:
        user = _make_mock_user()
        svc = AsyncMock()
        svc.request_bulk_archive = AsyncMock(
            side_effect=PermissionServiceError("Denied.")
        )

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/downloads/bulk-archive",
                    json={"node_ids": [str(uuid.uuid4())]},
                )
            assert response.status_code == 403
        finally:
            _clear()

    def test_download_error_returns_502(self) -> None:
        user = _make_mock_user()
        svc = AsyncMock()
        svc.request_bulk_archive = AsyncMock(
            side_effect=DownloadServiceError("Cannot queue.")
        )

        _set_user(user)
        _set_svc(svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/downloads/bulk-archive",
                    json={"node_ids": [str(uuid.uuid4())]},
                )
            assert response.status_code == 502
        finally:
            _clear()

    def test_invalid_body_returns_422(self) -> None:
        user = _make_mock_user()
        _set_user(user)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                response = c.post(
                    f"{API_V1}/downloads/bulk-archive",
                    json={"node_ids": "not-a-list"},
                )
            assert response.status_code == 422
        finally:
            _clear()

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.post(
                f"{API_V1}/downloads/bulk-archive",
                json={"node_ids": [str(uuid.uuid4())]},
            )
        assert response.status_code == 401
