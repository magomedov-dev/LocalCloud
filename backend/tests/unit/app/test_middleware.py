"""Тесты middleware: контекст запроса и заголовки безопасности."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.dependencies import RequestContext
from app.middleware import RequestContextMiddleware, SecurityHeadersMiddleware


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _make_mock_app() -> ASGIApp:
    return MagicMock(spec=ASGIApp)


def _make_request(
    method: str = "GET",
    path: str = "/test",
    headers: dict | None = None,
    client_host: str | None = "127.0.0.1",
) -> MagicMock:
    req = MagicMock(spec=Request)
    req.method = method
    req.url = MagicMock()
    req.url.path = path
    req.headers = headers or {}
    req.client = MagicMock(host=client_host) if client_host else None
    req.state = MagicMock(spec=[])
    return req


def _make_response(status_code: int = 200) -> Response:
    response = Response(content=b"ok", status_code=status_code)
    return response


# ---------------------------------------------------------------------------
# RequestContextMiddleware
# ---------------------------------------------------------------------------


class TestRequestContextMiddleware:
    def _make_middleware(self) -> RequestContextMiddleware:
        app = _make_mock_app()
        return RequestContextMiddleware(app=app)

    @pytest.mark.asyncio
    async def test_exception_does_not_swallow_error(self) -> None:
        """Middleware должен повторно выбрасывать исключения следующего обработчика."""
        middleware = self._make_middleware()
        request = _make_request()

        async def call_next_raises(req):
            raise ValueError("unexpected")

        with pytest.raises(ValueError, match="unexpected"):
            await middleware.dispatch(request, call_next_raises)

    @pytest.mark.asyncio
    async def test_normal_request_passes_through(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()
        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_request_id_header_added_to_response(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()
        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert "X-Request-ID" in response.headers

    @pytest.mark.asyncio
    async def test_correlation_id_header_added_to_response(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()
        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert "X-Correlation-ID" in response.headers

    @pytest.mark.asyncio
    async def test_exception_is_reraised(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()

        async def call_next_raises(req):
            raise RuntimeError("handler error")

        with pytest.raises(RuntimeError, match="handler error"):
            await middleware.dispatch(request, call_next_raises)

    @pytest.mark.asyncio
    async def test_existing_context_is_reused(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()

        # Заранее помещаем в состояние запроса существующий контекст
        existing_context = RequestContext(
            request_id="existing-req-id",
            correlation_id="existing-corr-id",
        )
        request.state.request_context = existing_context

        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert response.headers["X-Request-ID"] == "existing-req-id"
        assert response.headers["X-Correlation-ID"] == "existing-corr-id"

    @pytest.mark.asyncio
    async def test_custom_request_id_from_header(self) -> None:
        middleware = self._make_middleware()
        request = _make_request(headers={"X-Request-ID": "custom-req-id"})
        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert response.headers["X-Request-ID"] == "custom-req-id"

    @pytest.mark.asyncio
    async def test_get_or_create_context_without_existing_returns_new(self) -> None:
        request = _make_request()
        ctx = RequestContextMiddleware._get_or_create_context(request)
        assert ctx is not None
        assert ctx.request_id

    @pytest.mark.asyncio
    async def test_get_or_create_context_with_existing_returns_same(self) -> None:
        request = _make_request()
        existing_context = RequestContext(
            request_id="req-123",
            correlation_id="corr-456",
        )
        request.state.request_context = existing_context
        ctx = RequestContextMiddleware._get_or_create_context(request)
        assert ctx is existing_context

    @pytest.mark.asyncio
    async def test_get_or_create_context_regenerates_empty_request_id(self) -> None:
        """Если build_request_context вернул пустой request_id, генерируется новый."""
        request = _make_request()
        request.state = MagicMock(spec=["request_context"])
        request.state.request_context = None

        empty_ctx = RequestContext(
            request_id="",
            correlation_id="",
            client_ip="10.0.0.1",
            user_agent="agent",
        )

        with patch(
            "app.middleware.build_request_context", return_value=empty_ctx
        ):
            ctx = RequestContextMiddleware._get_or_create_context(request)

        # Должен быть сгенерирован непустой request_id.
        assert ctx.request_id
        assert ctx.correlation_id
        # Данные клиента переносятся из исходного пустого контекста.
        assert ctx.client_ip == "10.0.0.1"
        assert ctx.user_agent == "agent"
        # А новый контекст сохранён обратно в request.state.
        assert request.state.request_context is ctx
        assert request.state.request_id == ctx.request_id
        assert request.state.correlation_id == ctx.correlation_id


class TestInstallMiddleware:
    def test_installs_all_middleware(self) -> None:
        from fastapi import FastAPI

        from app.middleware import (
            RequestContextMiddleware,
            SecurityHeadersMiddleware,
            install_middleware,
        )

        app = FastAPI()
        install_middleware(app)

        installed = {mw.cls for mw in app.user_middleware}
        assert RequestContextMiddleware in installed
        assert SecurityHeadersMiddleware in installed


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware
# ---------------------------------------------------------------------------


class TestSecurityHeadersMiddleware:
    def _make_middleware(self) -> SecurityHeadersMiddleware:
        app = _make_mock_app()
        return SecurityHeadersMiddleware(app=app)

    @pytest.mark.asyncio
    async def test_x_content_type_options_set(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()
        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options_set(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()
        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert response.headers.get("X-Frame-Options") == "DENY"

    @pytest.mark.asyncio
    async def test_referrer_policy_set(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()
        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_permissions_policy_set(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()
        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert "camera=()" in response.headers.get("Permissions-Policy", "")

    @pytest.mark.asyncio
    async def test_x_permitted_cross_domain_policies_set(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()
        mock_response = _make_response(200)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert response.headers.get("X-Permitted-Cross-Domain-Policies") == "none"

    @pytest.mark.asyncio
    async def test_existing_headers_not_overwritten(self) -> None:
        """setdefault означает, что уже заданные заголовки сохраняются."""
        middleware = self._make_middleware()
        request = _make_request()

        # Создаём ответ с уже заданным заголовком X-Frame-Options
        from starlette.responses import Response as StarletteResponse
        mock_response = StarletteResponse(content=b"ok", status_code=200)
        mock_response.headers["X-Frame-Options"] = "SAMEORIGIN"

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"

    @pytest.mark.asyncio
    async def test_response_passes_through_unchanged_status(self) -> None:
        middleware = self._make_middleware()
        request = _make_request()
        mock_response = _make_response(404)

        async def call_next(req):
            return mock_response

        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 404
