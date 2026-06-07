"""Тесты DTO cookie: параметры CookieOptions и имена AuthCookieNames."""

from __future__ import annotations

import pytest

from security.cookies.dto import AuthCookieNames, CookieOptions


class TestCookieOptionsToSetCookieKwargs:
    def _make_options(
        self,
        *,
        secure: bool = True,
        httponly: bool = True,
        samesite: str = "lax",
        domain: str | None = None,
        path: str = "/",
    ) -> CookieOptions:
        return CookieOptions(
            secure=secure,
            httponly=httponly,
            samesite=samesite,  # type: ignore[arg-type]
            domain=domain,
            path=path,
        )

    def test_contains_secure(self) -> None:
        opts = self._make_options(secure=True)
        assert opts.to_set_cookie_kwargs()["secure"] is True

    def test_contains_httponly(self) -> None:
        opts = self._make_options(httponly=True)
        assert opts.to_set_cookie_kwargs()["httponly"] is True

    def test_contains_samesite(self) -> None:
        opts = self._make_options(samesite="strict")
        assert opts.to_set_cookie_kwargs()["samesite"] == "strict"

    def test_contains_path(self) -> None:
        opts = self._make_options(path="/api")
        assert opts.to_set_cookie_kwargs()["path"] == "/api"

    def test_omits_domain_if_none(self) -> None:
        opts = self._make_options(domain=None)
        assert "domain" not in opts.to_set_cookie_kwargs()

    def test_includes_domain_if_set(self) -> None:
        opts = self._make_options(domain="example.com")
        assert opts.to_set_cookie_kwargs()["domain"] == "example.com"

    def test_secure_false(self) -> None:
        opts = self._make_options(secure=False)
        assert opts.to_set_cookie_kwargs()["secure"] is False

    def test_httponly_false(self) -> None:
        opts = self._make_options(httponly=False)
        assert opts.to_set_cookie_kwargs()["httponly"] is False


class TestCookieOptionsToDeleteCookieKwargs:
    def test_returns_same_as_set_cookie_kwargs(self) -> None:
        opts = CookieOptions(
            secure=True,
            httponly=True,
            samesite="lax",  # type: ignore[arg-type]
            domain=None,
            path="/",
        )
        assert opts.to_delete_cookie_kwargs() == opts.to_set_cookie_kwargs()

    def test_with_domain(self) -> None:
        opts = CookieOptions(
            secure=False,
            httponly=False,
            samesite="none",  # type: ignore[arg-type]
            domain="test.com",
            path="/app",
        )
        result = opts.to_delete_cookie_kwargs()
        assert result["domain"] == "test.com"
        assert result["path"] == "/app"


class TestAuthCookieNames:
    def test_stores_access_name(self) -> None:
        names = AuthCookieNames(access="access_token", refresh="refresh_token")
        assert names.access == "access_token"

    def test_stores_refresh_name(self) -> None:
        names = AuthCookieNames(access="access_token", refresh="refresh_token")
        assert names.refresh == "refresh_token"

    def test_is_frozen(self) -> None:
        names = AuthCookieNames(access="at", refresh="rt")
        with pytest.raises((AttributeError, TypeError)):
            names.access = "changed"  # type: ignore[misc]
