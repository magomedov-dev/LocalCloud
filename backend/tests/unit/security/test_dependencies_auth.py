"""Юнит-тесты для security.dependencies.auth."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from security.dependencies.auth import (
    SecurityDependencyError,
    forbidden_exception,
    get_current_access_payload,
    get_current_refresh_payload,
    get_optional_access_payload,
    get_optional_refresh_payload,
    unauthorized_exception,
)
from security.cookies.exceptions import CookieError
from security.jwt.exceptions import (
    JwtExpiredError,
    JwtInvalidClaimsError,
    JwtInvalidTokenTypeError,
    JwtTokenError,
)


def make_invalid_token_type_error() -> JwtInvalidTokenTypeError:
    """Создать JwtInvalidTokenTypeError с обязательными именованными аргументами."""
    return JwtInvalidTokenTypeError(
        expected_type="access",
        actual_type="refresh",
    )


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def make_request(cookies: dict | None = None) -> MagicMock:
    """Создать минимальный mock-объект FastAPI Request."""
    req = MagicMock(spec=Request)
    req.cookies = cookies or {}
    req.state = MagicMock()
    req.headers = {}
    return req


def make_payload(user_id: uuid.UUID | None = None) -> MagicMock:
    payload = MagicMock()
    payload.user_id = user_id or uuid.uuid4()
    return payload


# ---------------------------------------------------------------------------
# unauthorized_exception / forbidden_exception
# ---------------------------------------------------------------------------


class TestUnauthorizedException:
    def test_returns_http_exception_with_401(self) -> None:
        exc = unauthorized_exception("bad creds")
        assert isinstance(exc, SecurityDependencyError)
        assert exc.status_code == 401
        assert exc.detail == "bad creds"

    def test_includes_www_authenticate_header(self) -> None:
        exc = unauthorized_exception()
        assert "WWW-Authenticate" in exc.headers

    def test_default_detail_is_not_empty(self) -> None:
        exc = unauthorized_exception()
        assert exc.detail


class TestForbiddenException:
    def test_returns_http_exception_with_403(self) -> None:
        exc = forbidden_exception("no perms")
        assert isinstance(exc, SecurityDependencyError)
        assert exc.status_code == 403
        assert exc.detail == "no perms"

    def test_default_detail_is_not_empty(self) -> None:
        exc = forbidden_exception()
        assert exc.detail


# ---------------------------------------------------------------------------
# get_current_access_payload
# ---------------------------------------------------------------------------


class TestGetCurrentAccessPayload:
    @pytest.mark.asyncio
    async def test_returns_payload_on_success(self) -> None:
        request = make_request()
        settings = MagicMock()
        payload = make_payload()

        with (
            patch(
                "security.dependencies.auth.require_access_token_from_cookies",
                return_value="fake_token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                return_value=payload,
            ),
        ):
            result = await get_current_access_payload(request, settings)

        assert result is payload

    @pytest.mark.asyncio
    async def test_cookie_error_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with patch(
            "security.dependencies.auth.require_access_token_from_cookies",
            side_effect=CookieError("missing"),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_access_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_expired_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.require_access_token_from_cookies",
                return_value="expired_token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                side_effect=JwtExpiredError("expired"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_access_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_invalid_token_type_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.require_access_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                side_effect=make_invalid_token_type_error(),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_access_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_invalid_claims_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.require_access_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                side_effect=JwtInvalidClaimsError("bad claims"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_access_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_token_error_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.require_access_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                side_effect=JwtTokenError("bad token"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_access_payload(request, settings)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_optional_access_payload
# ---------------------------------------------------------------------------


class TestGetOptionalAccessPayload:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_token(self) -> None:
        request = make_request()
        settings = MagicMock()

        with patch(
            "security.dependencies.auth.get_access_token_from_cookies",
            return_value=None,
        ):
            result = await get_optional_access_payload(request, settings)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_payload_for_valid_token(self) -> None:
        request = make_request()
        settings = MagicMock()
        payload = make_payload()

        with (
            patch(
                "security.dependencies.auth.get_access_token_from_cookies",
                return_value="valid_token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                return_value=payload,
            ),
        ):
            result = await get_optional_access_payload(request, settings)

        assert result is payload

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.get_access_token_from_cookies",
                return_value="expired_token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                side_effect=JwtExpiredError("expired"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_optional_access_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_type_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.get_access_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                side_effect=make_invalid_token_type_error(),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_optional_access_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_claims_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.get_access_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                side_effect=JwtInvalidClaimsError("bad claims"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_optional_access_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_generic_jwt_error_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.get_access_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_access_token",
                side_effect=JwtTokenError("bad token"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_optional_access_payload(request, settings)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_refresh_payload
# ---------------------------------------------------------------------------


class TestGetCurrentRefreshPayload:
    @pytest.mark.asyncio
    async def test_returns_payload_on_success(self) -> None:
        request = make_request()
        settings = MagicMock()
        payload = make_payload()

        with (
            patch(
                "security.dependencies.auth.require_refresh_token_from_cookies",
                return_value="fake_token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                return_value=payload,
            ),
        ):
            result = await get_current_refresh_payload(request, settings)

        assert result is payload

    @pytest.mark.asyncio
    async def test_cookie_error_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with patch(
            "security.dependencies.auth.require_refresh_token_from_cookies",
            side_effect=CookieError("missing"),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_refresh_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_expired_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.require_refresh_token_from_cookies",
                return_value="expired_token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                side_effect=JwtExpiredError("expired"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_refresh_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_invalid_token_type_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.require_refresh_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                side_effect=make_invalid_token_type_error(),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_refresh_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_invalid_claims_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.require_refresh_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                side_effect=JwtInvalidClaimsError("bad claims"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_refresh_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_token_error_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.require_refresh_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                side_effect=JwtTokenError("bad token"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_current_refresh_payload(request, settings)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_optional_refresh_payload
# ---------------------------------------------------------------------------


class TestGetOptionalRefreshPayload:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_token(self) -> None:
        request = make_request()
        settings = MagicMock()

        with patch(
            "security.dependencies.auth.get_refresh_token_from_cookies",
            return_value=None,
        ):
            result = await get_optional_refresh_payload(request, settings)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_payload_for_valid_token(self) -> None:
        request = make_request()
        settings = MagicMock()
        payload = make_payload()

        with (
            patch(
                "security.dependencies.auth.get_refresh_token_from_cookies",
                return_value="valid_token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                return_value=payload,
            ),
        ):
            result = await get_optional_refresh_payload(request, settings)

        assert result is payload

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.get_refresh_token_from_cookies",
                return_value="expired_token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                side_effect=JwtExpiredError("expired"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_optional_refresh_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_type_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.get_refresh_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                side_effect=make_invalid_token_type_error(),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_optional_refresh_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_claims_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.get_refresh_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                side_effect=JwtInvalidClaimsError("bad claims"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_optional_refresh_payload(request, settings)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_generic_jwt_error_raises_401(self) -> None:
        request = make_request()
        settings = MagicMock()

        with (
            patch(
                "security.dependencies.auth.get_refresh_token_from_cookies",
                return_value="token",
            ),
            patch(
                "security.dependencies.auth.decode_refresh_token",
                side_effect=JwtTokenError("bad token"),
            ),
        ):
            with pytest.raises(SecurityDependencyError) as exc_info:
                await get_optional_refresh_payload(request, settings)

        assert exc_info.value.status_code == 401
