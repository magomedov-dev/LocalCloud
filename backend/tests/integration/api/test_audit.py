"""Интеграционные тесты эндпоинтов /api/v1/audit (журнал аудита)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from api.dependencies import get_audit_service_dependency
from security.dependencies.users import get_current_active_user, get_current_admin_user
from tests.integration.conftest import API_V1, _make_mock_user


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _audit_log_item_dict(log_id: uuid.UUID | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(log_id or uuid.uuid4()),
        "user_id": None,
        "action": "user.login",
        "result": "success",
        "entity_type": None,
        "entity_id": None,
        "resource_type": None,
        "ip_address": None,
        "message": None,
        "error_code": None,
        "created_at": now,
    }


def _audit_log_read_dict(log_id: uuid.UUID | None = None) -> dict[str, Any]:
    now = datetime.now(tz=timezone.utc).isoformat()
    return {
        "id": str(log_id or uuid.uuid4()),
        "user_id": None,
        "action": "user.login",
        "result": "success",
        "entity_type": None,
        "entity_id": None,
        "resource_type": None,
        "request_id": None,
        "correlation_id": None,
        "ip_address": None,
        "user_agent": None,
        "message": None,
        "error_code": None,
        "metadata": None,
        "created_at": now,
    }


def _summary_dict() -> dict[str, Any]:
    return {"total_count": 0}


def _page_response(items: list[Any]) -> dict[str, Any]:
    count = len(items)
    return {
        "items": items,
        "meta": {"limit": 50, "offset": 0, "total": count, "count": count},
    }


def _admin_overrides(mock_svc: AsyncMock) -> Any:
    admin = _make_mock_user()
    app.dependency_overrides[get_current_active_user] = lambda: admin
    app.dependency_overrides[get_current_admin_user] = lambda: admin
    app.dependency_overrides[get_audit_service_dependency] = lambda: mock_svc


def _clear() -> None:
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(get_current_admin_user, None)
    app.dependency_overrides.pop(get_audit_service_dependency, None)


# ---------------------------------------------------------------------------
# GET /audit/logs
# ---------------------------------------------------------------------------


class TestListAuditLogs:
    def test_returns_200_for_admin(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.list_logs = AsyncMock(
            return_value=_page_response([_audit_log_item_dict()])
        )
        _admin_overrides(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/audit/logs")
            assert resp.status_code == 200
        finally:
            _clear()

    def test_unauthenticated_returns_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"{API_V1}/audit/logs")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /audit/logs/{log_id}
# ---------------------------------------------------------------------------


class TestGetAuditLog:
    def test_returns_200_for_admin(self) -> None:
        log_id = uuid.uuid4()
        mock_svc = AsyncMock()
        mock_svc.get_log = AsyncMock(return_value=_audit_log_read_dict(log_id))
        _admin_overrides(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/audit/logs/{log_id}")
            assert resp.status_code == 200
        finally:
            _clear()


# ---------------------------------------------------------------------------
# GET /audit/summary
# ---------------------------------------------------------------------------


class TestGetAuditSummary:
    def test_returns_200_for_admin(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.get_summary = AsyncMock(return_value=_summary_dict())
        _admin_overrides(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/audit/summary")
            assert resp.status_code == 200
        finally:
            _clear()


# ---------------------------------------------------------------------------
# POST /audit/export
# ---------------------------------------------------------------------------


class TestExportAuditLogs:
    def test_export_json(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.export_logs = AsyncMock(
            return_value={
                "content": json.dumps([{"a": 1}]),
                "filename": "audit.json",
                "content_type": "application/json",
                "format": "json",
            }
        )
        _admin_overrides(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(f"{API_V1}/audit/export", json={"format": "json"})
            assert resp.status_code == 200
            assert resp.json() == [{"a": 1}]
            assert "attachment" in resp.headers["content-disposition"]
        finally:
            _clear()

    def test_export_json_empty_content(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.export_logs = AsyncMock(
            return_value={
                "content": "",
                "filename": "audit.json",
                "format": "json",
            }
        )
        _admin_overrides(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(f"{API_V1}/audit/export", json={"format": "json"})
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            _clear()

    def test_export_csv(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.export_logs = AsyncMock(
            return_value={
                "content": "a,b\n1,2\n",
                "filename": "audit.csv",
                "format": "csv",
            }
        )
        _admin_overrides(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(f"{API_V1}/audit/export", json={"format": "csv"})
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/csv")
        finally:
            _clear()

    def test_export_other_format_uses_content_type(self) -> None:
        mock_svc = AsyncMock()
        mock_svc.export_logs = AsyncMock(
            return_value={
                "content": "raw-bytes",
                "filename": "audit.bin",
                "content_type": "application/octet-stream",
                "format": "binary",
            }
        )
        _admin_overrides(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(f"{API_V1}/audit/export", json={})
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("application/octet-stream")
        finally:
            _clear()


# ---------------------------------------------------------------------------
# GET /audit/users/{user_id}/latest
# ---------------------------------------------------------------------------


class TestGetLatestUserAuditLogs:
    def test_returns_200_for_admin(self) -> None:
        user_id = uuid.uuid4()
        mock_svc = AsyncMock()
        mock_svc.get_latest_user_logs = AsyncMock(
            return_value=[_audit_log_item_dict()]
        )
        _admin_overrides(mock_svc)
        try:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get(f"{API_V1}/audit/users/{user_id}/latest")
            assert resp.status_code == 200
        finally:
            _clear()
