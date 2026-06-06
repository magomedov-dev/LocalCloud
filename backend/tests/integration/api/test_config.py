"""Интеграционные тесты публичного endpoint конфигурации клиента."""

from __future__ import annotations

from fastapi.testclient import TestClient

import api.v1.config as config_endpoint
from app.main import app
from core.config import FeatureSettings, Settings
from tests.integration.conftest import API_V1


class TestClientConfigEndpoint:
    def test_returns_200_and_feature_flags(self) -> None:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/config")
        assert response.status_code == 200
        features = response.json()["features"]
        assert set(features.keys()) == {
            "previews_enabled",
            "file_viewer_enabled",
            "media_playback_enabled",
            "file_editing_enabled",
        }
        assert all(isinstance(value, bool) for value in features.values())

    def test_requires_no_authentication(self) -> None:
        # Запрос без cookie/токена должен возвращать конфигурацию, а не 401.
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/config")
        assert response.status_code == 200

    def test_reflects_disabled_flags(self, monkeypatch) -> None:
        disabled = Settings(
            features=FeatureSettings(
                FEATURE_PREVIEWS_ENABLED=False,
                FEATURE_FILE_VIEWER_ENABLED=False,
                FEATURE_MEDIA_PLAYBACK_ENABLED=False,
                FEATURE_FILE_EDITING_ENABLED=False,
            )
        )
        # Endpoint читает настройки через get_settings(); подменяем эту функцию
        # в модуле endpoint-а, чтобы вернуть конфигурацию с отключёнными флагами.
        monkeypatch.setattr(config_endpoint, "get_settings", lambda: disabled)

        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get(f"{API_V1}/config")
        assert response.status_code == 200
        features = response.json()["features"]
        assert features == {
            "previews_enabled": False,
            "file_viewer_enabled": False,
            "media_playback_enabled": False,
            "file_editing_enabled": False,
        }
