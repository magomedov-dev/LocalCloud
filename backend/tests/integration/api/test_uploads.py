"""Интеграционные тесты эндпоинтов /api/v1/uploads (загрузка файлов)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_uploads_service_dependency
from database.models.enums import UploadPartStatus, UploadSessionStatus
from schemas.uploads import UploadPartRead
from security.dependencies.users import get_current_active_user
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _session_read_dict(
    session_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(session_id or uuid.uuid4()),
        "user_id": str(user_id or uuid.uuid4()),
        "parent_node_id": str(uuid.uuid4()),
        "file_name": "file.bin",
        "file_size_bytes": 1024,
        "part_size_bytes": 512,
        "status": UploadSessionStatus.CREATED.value,
        "parts_count": 2,
        "uploaded_parts_count": 0,
        "uploaded_bytes": 0,
        "expires_at": now,
        "created_at": now,
    }


def _session_list_item_dict() -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "parent_node_id": str(uuid.uuid4()),
        "file_name": "file.bin",
        "file_size_bytes": 1024,
        "status": UploadSessionStatus.CREATED.value,
        "parts_count": 2,
        "uploaded_parts_count": 0,
        "uploaded_bytes": 0,
        "expires_at": now,
        "created_at": now,
    }


def _page_response(items: list[Any]) -> dict[str, Any]:
    count = len(items)
    return {
        "items": items,
        "meta": {"limit": 50, "offset": 0, "total": count, "count": count},
    }


def _part_read(part_number: int, session_id: uuid.UUID) -> UploadPartRead:
    now = datetime.now(tz=timezone.utc)
    return UploadPartRead(
        id=uuid.uuid4(),
        upload_session_id=session_id,
        part_number=part_number,
        size_bytes=512,
        etag="etag-value",
        status=UploadPartStatus.UPLOADED,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# POST /uploads/  (create session)
# ---------------------------------------------------------------------------


class TestCreateUploadSession:
    def test_returns_201_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        session = _session_read_dict(user_id=mock_user.id)

        mock_svc = AsyncMock()
        mock_svc.initiate_upload = AsyncMock(return_value=(session, None))

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_uploads_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/uploads/",
                    json={
                        "parent_node_id": str(uuid.uuid4()),
                        "filename": "file.bin",
                        "file_size_bytes": 1024,
                        "parts_count": 2,
                    },
                )
            assert resp.status_code == 201
            mock_svc.initiate_upload.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_uploads_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                f"{API_V1}/uploads/",
                json={
                    "parent_node_id": str(uuid.uuid4()),
                    "filename": "file.bin",
                    "file_size_bytes": 1024,
                    "parts_count": 2,
                },
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /uploads/  (list)
# ---------------------------------------------------------------------------


class TestListUploadSessions:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        page = _page_response([_session_list_item_dict()])

        mock_svc = AsyncMock()
        mock_svc.list_uploads = AsyncMock(return_value=page)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_uploads_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/uploads/")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_uploads_service_dependency, None)


# ---------------------------------------------------------------------------
# GET /uploads/{upload_id}
# ---------------------------------------------------------------------------


class TestGetUploadSession:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        upload_id = uuid.uuid4()
        session = _session_read_dict(session_id=upload_id, user_id=mock_user.id)

        mock_svc = AsyncMock()
        mock_svc.get_upload_session = AsyncMock(return_value=session)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_uploads_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/uploads/{upload_id}")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_uploads_service_dependency, None)


# ---------------------------------------------------------------------------
# POST /uploads/{upload_id}/parts/presigned
# ---------------------------------------------------------------------------


class TestCreatePartUrls:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        upload_id = uuid.uuid4()
        now = datetime.now(tz=timezone.utc).isoformat()
        result = {
            "upload_session_id": str(upload_id),
            "status": UploadSessionStatus.CREATED.value,
            "parts": [],
            "expires_at": now,
        }

        mock_svc = AsyncMock()
        mock_svc.create_part_urls = AsyncMock(return_value=result)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_uploads_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(f"{API_V1}/uploads/{upload_id}/parts/presigned")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_uploads_service_dependency, None)


# ---------------------------------------------------------------------------
# POST /uploads/{upload_id}/parts/{part_number}/complete
# ---------------------------------------------------------------------------


class TestCompleteUploadPart:
    def test_returns_matching_part(self) -> None:
        mock_user = _make_mock_user()
        upload_id = uuid.uuid4()

        mock_svc = AsyncMock()
        mock_svc.confirm_part = AsyncMock(return_value=None)
        mock_svc.get_upload_parts = AsyncMock(
            return_value=[_part_read(1, upload_id), _part_read(2, upload_id)]
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_uploads_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/uploads/{upload_id}/parts/2/complete",
                    json={
                        "part_number": 2,
                        "etag": "etag-value",
                        "size_bytes": 512,
                    },
                )
            assert resp.status_code == 200
            assert resp.json()["part_number"] == 2
            mock_svc.confirm_part.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_uploads_service_dependency, None)

    def test_missing_part_raises_value_error(self) -> None:
        mock_user = _make_mock_user()
        upload_id = uuid.uuid4()

        mock_svc = AsyncMock()
        mock_svc.confirm_part = AsyncMock(return_value=None)
        # Возвращаемые части не содержат запрошенный номер части.
        mock_svc.get_upload_parts = AsyncMock(
            return_value=[_part_read(1, upload_id)]
        )

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_uploads_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/uploads/{upload_id}/parts/2/complete",
                    json={
                        "part_number": 2,
                        "etag": "etag-value",
                        "size_bytes": 512,
                    },
                )
            # Эндпоинт бросает ValueError -> FastAPI обрабатывает как 500.
            assert resp.status_code == 500
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_uploads_service_dependency, None)


# ---------------------------------------------------------------------------
# POST /uploads/{upload_id}/complete
# ---------------------------------------------------------------------------


class TestCompleteUpload:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        upload_id = uuid.uuid4()
        result = {
            "upload_session": _session_read_dict(
                session_id=upload_id, user_id=mock_user.id
            ),
            "file_id": None,
            "node_id": None,
        }

        mock_svc = AsyncMock()
        mock_svc.complete_upload = AsyncMock(return_value=result)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_uploads_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/uploads/{upload_id}/complete",
                    json={
                        "upload_session_id": str(upload_id),
                        "parts": [
                            {
                                "part_number": 1,
                                "etag": "etag-value",
                                "size_bytes": 512,
                            }
                        ],
                    },
                )
            assert resp.status_code == 200
            mock_svc.complete_upload.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_uploads_service_dependency, None)


# ---------------------------------------------------------------------------
# POST /uploads/{upload_id}/abort
# ---------------------------------------------------------------------------


class TestAbortUpload:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        upload_id = uuid.uuid4()
        session = _session_read_dict(session_id=upload_id, user_id=mock_user.id)

        mock_svc = AsyncMock()
        mock_svc.abort_upload = AsyncMock(return_value=session)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_uploads_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/uploads/{upload_id}/abort",
                    json={"upload_session_id": str(upload_id)},
                )
            assert resp.status_code == 200
            mock_svc.abort_upload.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_uploads_service_dependency, None)


# ---------------------------------------------------------------------------
# GET /uploads/{upload_id}/progress
# ---------------------------------------------------------------------------


class TestGetUploadProgress:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        upload_id = uuid.uuid4()
        progress = {
            "upload_session_id": str(upload_id),
            "status": UploadSessionStatus.UPLOADING.value,
            "file_size_bytes": 1024,
            "parts_count": 2,
            "uploaded_parts_count": 1,
            "uploaded_bytes": 512,
        }

        mock_svc = AsyncMock()
        mock_svc.get_progress = AsyncMock(return_value=progress)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_uploads_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/uploads/{upload_id}/progress")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_uploads_service_dependency, None)
