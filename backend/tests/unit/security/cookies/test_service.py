"""Тесты сервиса cookie: чтение, установка и очистка auth-cookie."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from core.config import CookieSettings, Settings
from security.cookies.dto import AuthCookieNames, CookieOptions
from security.cookies.exceptions import CookieError
from security.cookies.service import (
    build_cookie_expires,
    clear_auth_cookies,
    get_access_token_from_cookies,
    get_auth_cookie_names,
    get_cookie_options,
    get_cookie_value,
    get_refresh_token_from_cookies,
    require_access_token_from_cookies,
    require_refresh_token_from_cookies,
    set_auth_cookie,
)


def _make_settings(
    access_cookie_name: str = "localcloud_access",
    refresh_cookie_name: str = "localcloud_refresh",
    cookie_secure: bool = False,
    cookie_httponly: bool = True,
    cookie_samesite: str = "lax",
    cookie_domain: str | None = None,
    cookie_path: str = "/",
) -> Settings:
    """Собрать минимальный объект Settings с заданной конфигурацией cookie."""
    from core.config import (
        ApplicationSettings,
        DatabaseSettings,
        LoggingSettings,
        SecuritySettings,
        StorageSettings,
        WorkerSettings,
    )

    cookies = CookieSettings(
        ACCESS_COOKIE_NAME=access_cookie_name,
        REFRESH_COOKIE_NAME=refresh_cookie_name,
        COOKIE_SECURE=cookie_secure,
        COOKIE_HTTPONLY=cookie_httponly,
        COOKIE_SAMESITE=cookie_samesite,
        COOKIE_DOMAIN=cookie_domain,
        COOKIE_PATH=cookie_path,
    )
    return Settings(
        app=ApplicationSettings(),
        logging=LoggingSettings(),
        security=SecuritySettings(
            SECRET_KEY="test-secret-key-for-pytest-only-1234",
            JWT_ALGORITHM="HS256",
            JWT_ISSUER="test-issuer",
            JWT_AUDIENCE="test-audience",
        ),
        cookies=cookies,
        database=DatabaseSettings(),
        storage=StorageSettings(),
        workers=WorkerSettings(),
    )


def _make_request(cookies: dict[str, str] | None = None) -> MagicMock:
    request = MagicMock()
    request.cookies = cookies or {}
    return request


def _make_response() -> MagicMock:
    return MagicMock()


class TestGetAuthCookieNames:
    def test_returns_auth_cookie_names_instance(self) -> None:
        settings = _make_settings()
        result = get_auth_cookie_names(settings)
        assert isinstance(result, AuthCookieNames)

    def test_access_name_from_settings(self) -> None:
        settings = _make_settings(access_cookie_name="my_access")
        result = get_auth_cookie_names(settings)
        assert result.access == "my_access"

    def test_refresh_name_from_settings(self) -> None:
        settings = _make_settings(refresh_cookie_name="my_refresh")
        result = get_auth_cookie_names(settings)
        assert result.refresh == "my_refresh"


class TestGetCookieOptions:
    def test_returns_cookie_options_instance(self) -> None:
        settings = _make_settings()
        result = get_cookie_options(settings)
        assert isinstance(result, CookieOptions)

    def test_secure_from_settings(self) -> None:
        settings = _make_settings(cookie_secure=True)
        result = get_cookie_options(settings)
        assert result.secure is True

    def test_httponly_from_settings(self) -> None:
        settings = _make_settings(cookie_httponly=False)
        result = get_cookie_options(settings)
        assert result.httponly is False

    def test_samesite_from_settings(self) -> None:
        settings = _make_settings(cookie_samesite="strict")
        result = get_cookie_options(settings)
        assert result.samesite == "strict"

    def test_path_from_settings(self) -> None:
        settings = _make_settings(cookie_path="/api")
        result = get_cookie_options(settings)
        assert result.path == "/api"

    def test_domain_none_from_settings(self) -> None:
        settings = _make_settings(cookie_domain=None)
        result = get_cookie_options(settings)
        assert result.domain is None


class TestBuildCookieExpires:
    def test_returns_future_datetime(self) -> None:
        before = datetime.now(UTC)
        result = build_cookie_expires(3600)
        after = datetime.now(UTC)
        assert before < result <= after + timedelta(seconds=3600)

    def test_result_is_timezone_aware(self) -> None:
        result = build_cookie_expires(60)
        assert result.tzinfo is not None

    def test_approximately_correct_offset(self) -> None:
        before = datetime.now(UTC)
        result = build_cookie_expires(7200)
        expected = before + timedelta(seconds=7200)
        # допускаем погрешность в 2 секунды
        assert abs((result - expected).total_seconds()) < 2


class TestSetAuthCookie:
    def test_calls_set_cookie_on_response(self) -> None:
        settings = _make_settings()
        response = _make_response()
        set_auth_cookie(response, name="access_token", value="tok123", max_age_seconds=300, settings=settings)
        response.set_cookie.assert_called_once()

    def test_set_cookie_called_with_correct_key(self) -> None:
        settings = _make_settings()
        response = _make_response()
        set_auth_cookie(response, name="mykey", value="myval", max_age_seconds=60, settings=settings)
        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["key"] == "mykey"

    def test_set_cookie_called_with_correct_value(self) -> None:
        settings = _make_settings()
        response = _make_response()
        set_auth_cookie(response, name="mykey", value="secret_token", max_age_seconds=60, settings=settings)
        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["value"] == "secret_token"

    def test_set_cookie_called_with_correct_max_age(self) -> None:
        settings = _make_settings()
        response = _make_response()
        set_auth_cookie(response, name="mykey", value="val", max_age_seconds=1800, settings=settings)
        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["max_age"] == 1800

    def test_set_cookie_has_httponly(self) -> None:
        settings = _make_settings(cookie_httponly=True)
        response = _make_response()
        set_auth_cookie(response, name="k", value="v", max_age_seconds=60, settings=settings)
        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["httponly"] is True

    def test_set_cookie_has_secure(self) -> None:
        settings = _make_settings(cookie_secure=True)
        response = _make_response()
        set_auth_cookie(response, name="k", value="v", max_age_seconds=60, settings=settings)
        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["secure"] is True


class TestClearAuthCookies:
    def test_delete_cookie_called_twice(self) -> None:
        settings = _make_settings()
        response = _make_response()
        clear_auth_cookies(response, settings=settings)
        assert response.delete_cookie.call_count == 2

    def test_delete_cookie_called_with_access_name(self) -> None:
        settings = _make_settings(access_cookie_name="my_access")
        response = _make_response()
        clear_auth_cookies(response, settings=settings)
        called_keys = [call[1]["key"] for call in response.delete_cookie.call_args_list]
        assert "my_access" in called_keys

    def test_delete_cookie_called_with_refresh_name(self) -> None:
        settings = _make_settings(refresh_cookie_name="my_refresh")
        response = _make_response()
        clear_auth_cookies(response, settings=settings)
        called_keys = [call[1]["key"] for call in response.delete_cookie.call_args_list]
        assert "my_refresh" in called_keys


class TestGetAccessTokenFromCookies:
    def test_returns_token_when_present(self) -> None:
        settings = _make_settings(access_cookie_name="localcloud_access")
        request = _make_request({"localcloud_access": "mytoken"})
        result = get_access_token_from_cookies(request, settings=settings)
        assert result == "mytoken"

    def test_returns_none_when_missing(self) -> None:
        settings = _make_settings(access_cookie_name="localcloud_access")
        request = _make_request({})
        result = get_access_token_from_cookies(request, settings=settings)
        assert result is None


class TestGetRefreshTokenFromCookies:
    def test_returns_token_when_present(self) -> None:
        settings = _make_settings(refresh_cookie_name="localcloud_refresh")
        request = _make_request({"localcloud_refresh": "refresh_tok"})
        result = get_refresh_token_from_cookies(request, settings=settings)
        assert result == "refresh_tok"

    def test_returns_none_when_missing(self) -> None:
        settings = _make_settings(refresh_cookie_name="localcloud_refresh")
        request = _make_request({})
        result = get_refresh_token_from_cookies(request, settings=settings)
        assert result is None


class TestRequireAccessTokenFromCookies:
    def test_returns_token_when_present(self) -> None:
        settings = _make_settings(access_cookie_name="localcloud_access")
        request = _make_request({"localcloud_access": "tok"})
        result = require_access_token_from_cookies(request, settings=settings)
        assert result == "tok"

    def test_raises_cookie_error_when_missing(self) -> None:
        settings = _make_settings(access_cookie_name="localcloud_access")
        request = _make_request({})
        with pytest.raises(CookieError):
            require_access_token_from_cookies(request, settings=settings)


class TestRequireRefreshTokenFromCookies:
    def test_returns_token_when_present(self) -> None:
        settings = _make_settings(refresh_cookie_name="localcloud_refresh")
        request = _make_request({"localcloud_refresh": "rtok"})
        result = require_refresh_token_from_cookies(request, settings=settings)
        assert result == "rtok"

    def test_raises_cookie_error_when_missing(self) -> None:
        settings = _make_settings(refresh_cookie_name="localcloud_refresh")
        request = _make_request({})
        with pytest.raises(CookieError):
            require_refresh_token_from_cookies(request, settings=settings)


class TestGetCookieValue:
    def test_returns_stripped_value(self) -> None:
        request = _make_request({"session": "  myvalue  "})
        result = get_cookie_value(request, "session")
        assert result == "myvalue"

    def test_returns_none_when_cookie_not_in_request(self) -> None:
        request = _make_request({})
        result = get_cookie_value(request, "missing_cookie")
        assert result is None

    def test_returns_none_for_empty_value(self) -> None:
        request = _make_request({"empty": "   "})
        result = get_cookie_value(request, "empty")
        assert result is None

    def test_returns_value_for_present_cookie(self) -> None:
        request = _make_request({"token": "abc"})
        result = get_cookie_value(request, "token")
        assert result == "abc"
