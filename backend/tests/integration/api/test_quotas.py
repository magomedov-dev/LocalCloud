"""Интеграционные тесты эндпоинтов /api/v1/quotas (квоты пользователей)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_quotas_service_dependency
from services.exceptions import NotFoundServiceError
from security.dependencies.users import get_current_active_user, get_current_admin_user
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _quota_usage_dict(user_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Минимальный словарь, совместимый с QuotaUsageRead."""
    now = datetime.now(tz=timezone.utc).isoformat()
    uid = str(user_id or uuid.uuid4())
    return {
        "user_id": uid,
        "storage_limit_bytes": 10 * 1024 ** 3,
        "storage_used_bytes": 1024,
        "max_file_size_bytes": 1 * 1024 ** 3,
        "files_limit": 10000,
        "files_used": 5,
        "public_links_limit": 100,
        "public_links_used": 0,
        "active_upload_sessions_limit": 10,
        "active_upload_sessions_used": 0,
        "updated_at": now,
    }


def _user_quota_dict(user_id: uuid.UUID | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "user_id": str(user_id or uuid.uuid4()),
        "storage_limit_bytes": 10 * 1024 ** 3,
        "storage_used_bytes": 1024,
        "max_file_size_bytes": 1 * 1024 ** 3,
        "files_limit": 10000,
        "files_used": 5,
        "public_links_limit": 100,
        "public_links_used": 0,
        "active_upload_sessions_limit": 10,
        "active_upload_sessions_used": 0,
        "available_storage_bytes": 10 * 1024 ** 3 - 1024,
        "usage_percent": 0.0,
        "is_storage_full": False,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# GET /quotas/me
# ---------------------------------------------------------------------------


class TestGetMyQuotaUsage:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        usage = _quota_usage_dict(mock_user.id)

        mock_svc = AsyncMock()
        mock_svc.get_usage = AsyncMock(return_value=usage)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/quotas/me")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/quotas/me")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /quotas/users/{user_id}
# ---------------------------------------------------------------------------


class TestGetUserQuotaUsage:
    def test_returns_200_for_admin(self) -> None:
        admin = _make_mock_user()
        target_id = uuid.uuid4()
        usage = _quota_usage_dict(target_id)

        mock_svc = AsyncMock()
        mock_svc.get_usage = AsyncMock(return_value=usage)

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/quotas/users/{target_id}")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/quotas/users/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /quotas/server/capacity
# ---------------------------------------------------------------------------


def _server_capacity_dict() -> dict[str, Any]:
    """Минимальный словарь, совместимый с ServerCapacityRead."""
    return {
        "pool_bytes": 100 * 1024 ** 3,
        "allocated_bytes": 30 * 1024 ** 3,
        "available_bytes": 70 * 1024 ** 3,
        "physical_total_bytes": 120 * 1024 ** 3,
        "physical_available_bytes": 90 * 1024 ** 3,
        "source": "auto",
        "is_overcommitted": False,
        "minio_reachable": True,
    }


class TestGetServerCapacity:
    def test_returns_200_for_admin(self) -> None:
        admin = _make_mock_user()

        mock_svc = AsyncMock()
        mock_svc.get_server_capacity = AsyncMock(
            return_value=_server_capacity_dict(),
        )

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/quotas/server/capacity")
            assert resp.status_code == 200
            body = resp.json()
            assert body["pool_bytes"] == 100 * 1024 ** 3
            assert body["available_bytes"] == 70 * 1024 ** 3
            assert body["is_overcommitted"] is False
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/quotas/server/capacity")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /quotas/check
# ---------------------------------------------------------------------------


class TestCheckQuota:
    def test_returns_200_for_authenticated_user(self) -> None:
        mock_user = _make_mock_user()
        check_result = {
            "allowed": True,
            "user_id": str(mock_user.id),
            "resource_type": "storage_bytes",
            "requested_amount": 1024,
            "limit": 10 * 1024 ** 3,
            "used": 0,
            "available": 10 * 1024 ** 3,
            "reason": None,
        }

        mock_svc = AsyncMock()
        mock_svc.check_quota = AsyncMock(return_value=check_result)

        app.dependency_overrides[get_current_active_user] = lambda: mock_user
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/quotas/check",
                    json={
                        "user_id": str(mock_user.id),
                        "resource_type": "storage_bytes",
                        "requested_amount": 1024,
                    },
                )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                f"{API_V1}/quotas/check",
                json={"user_id": str(uuid.uuid4()), "storage_required_bytes": 1024},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /quotas/users/{user_id}
# ---------------------------------------------------------------------------


class TestUpsertUserQuota:
    def test_create_quota_returns_200_for_admin(self) -> None:
        admin = _make_mock_user()
        target_id = uuid.uuid4()
        quota = _user_quota_dict(target_id)

        mock_svc = AsyncMock()
        mock_svc.create_quota = AsyncMock(return_value=quota)

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.put(
                    f"{API_V1}/quotas/users/{target_id}",
                    json={
                        "user_id": str(target_id),
                        "storage_limit_bytes": 10 * 1024 ** 3,
                        "max_file_size_bytes": 1 * 1024 ** 3,
                    },
                )
            assert resp.status_code == 200
            mock_svc.create_quota.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_create_quota_mismatched_user_id_returns_400(self) -> None:
        admin = _make_mock_user()
        path_id = uuid.uuid4()
        body_id = uuid.uuid4()

        mock_svc = AsyncMock()

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.put(
                    f"{API_V1}/quotas/users/{path_id}",
                    json={
                        "user_id": str(body_id),
                        "storage_limit_bytes": 10 * 1024 ** 3,
                        "max_file_size_bytes": 1 * 1024 ** 3,
                    },
                )
            assert resp.status_code == 400
            mock_svc.create_quota.assert_not_awaited()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_update_quota_returns_200_for_admin(self) -> None:
        admin = _make_mock_user()
        target_id = uuid.uuid4()
        quota = _user_quota_dict(target_id)

        mock_svc = AsyncMock()
        mock_svc.update_quota = AsyncMock(return_value=quota)

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.put(
                    f"{API_V1}/quotas/users/{target_id}",
                    json={"files_limit": 5000},
                )
            assert resp.status_code == 200
            mock_svc.update_quota.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_update_quota_not_found_returns_404(self) -> None:
        admin = _make_mock_user()
        target_id = uuid.uuid4()

        mock_svc = AsyncMock()
        mock_svc.update_quota = AsyncMock(
            side_effect=NotFoundServiceError(entity_name="UserQuota")
        )

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.put(
                    f"{API_V1}/quotas/users/{target_id}",
                    json={"files_limit": 5000},
                )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.put(
                f"{API_V1}/quotas/users/{uuid.uuid4()}",
                json={"files_limit": 5000},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /quotas/recalculate
# ---------------------------------------------------------------------------


class TestRecalculateQuota:
    def test_returns_200_for_admin(self) -> None:
        admin = _make_mock_user()
        target_id = uuid.uuid4()
        quota = _user_quota_dict(target_id)

        mock_svc = AsyncMock()
        mock_svc.recalculate_quota = AsyncMock(return_value=quota)

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/quotas/recalculate",
                    json={"user_id": str(target_id)},
                )
            assert resp.status_code == 200
            mock_svc.recalculate_quota.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_not_found_returns_404(self) -> None:
        admin = _make_mock_user()
        target_id = uuid.uuid4()

        mock_svc = AsyncMock()
        mock_svc.recalculate_quota = AsyncMock(
            side_effect=NotFoundServiceError(entity_name="UserQuota")
        )

        app.dependency_overrides[get_current_active_user] = lambda: admin
        app.dependency_overrides[get_current_admin_user] = lambda: admin
        app.dependency_overrides[get_quotas_service_dependency] = lambda: mock_svc
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    f"{API_V1}/quotas/recalculate",
                    json={"user_id": str(target_id)},
                )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_current_admin_user, None)
            app.dependency_overrides.pop(get_quotas_service_dependency, None)

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                f"{API_V1}/quotas/recalculate",
                json={"user_id": str(uuid.uuid4())},
            )
        assert resp.status_code == 401
