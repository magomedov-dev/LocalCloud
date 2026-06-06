"""Тесты middleware: контекст запроса и заголовки безопасности."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.dependencies import RequestContext
import asyncio

from app.middleware import (
    ConcurrencyLimitMiddleware,
    RequestContextMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
)


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


# ---------------------------------------------------------------------------
# ConcurrencyLimitMiddleware
# ---------------------------------------------------------------------------


class TestConcurrencyLimitMiddleware:
    @pytest.mark.asyncio
    async def test_under_limit_passes(self) -> None:
        mw = ConcurrencyLimitMiddleware(_make_mock_app(), max_concurrency=2)
        request = _make_request(path="/api/v1/nodes")

        async def call_next(req):
            return _make_response(200)

        response = await mw.dispatch(request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_over_limit_sheds_503(self) -> None:
        mw = ConcurrencyLimitMiddleware(_make_mock_app(), max_concurrency=1)
        gate = asyncio.Event()

        async def slow_call_next(req):
            await gate.wait()
            return _make_response(200)

        # Первый запрос занимает единственный слот и «висит».
        first = asyncio.create_task(
            mw.dispatch(_make_request(path="/api/v1/a"), slow_call_next)
        )
        await asyncio.sleep(0)  # дать первому запросу занять слот

        async def call_next(req):
            return _make_response(200)

        # Второй запрос сверх потолка → 503.
        second = await mw.dispatch(_make_request(path="/api/v1/b"), call_next)
        assert second.status_code == 503
        assert second.headers.get("Retry-After") == "2"

        gate.set()
        assert (await first).status_code == 200

    @pytest.mark.asyncio
    async def test_health_path_never_shed(self) -> None:
        mw = ConcurrencyLimitMiddleware(_make_mock_app(), max_concurrency=1)
        mw._inflight = 999  # имитируем перегрузку

        async def call_next(req):
            return _make_response(200)

        response = await mw.dispatch(_make_request(path="/"), call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_slot_released_after_request(self) -> None:
        mw = ConcurrencyLimitMiddleware(_make_mock_app(), max_concurrency=1)

        async def call_next(req):
            return _make_response(200)

        await mw.dispatch(_make_request(path="/api/v1/a"), call_next)
        await mw.dispatch(_make_request(path="/api/v1/b"), call_next)
        assert mw._inflight == 0

    @pytest.mark.asyncio
    async def test_slot_released_on_exception(self) -> None:
        mw = ConcurrencyLimitMiddleware(_make_mock_app(), max_concurrency=1)

        async def call_next(req):
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await mw.dispatch(_make_request(path="/api/v1/a"), call_next)
        assert mw._inflight == 0


# ---------------------------------------------------------------------------
# RequestTimeoutMiddleware
# ---------------------------------------------------------------------------


class TestRequestTimeoutMiddleware:
    @pytest.mark.asyncio
    async def test_fast_handler_passes(self) -> None:
        mw = RequestTimeoutMiddleware(_make_mock_app(), timeout_seconds=5.0)

        async def call_next(req):
            return _make_response(200)

        response = await mw.dispatch(_make_request(), call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_slow_handler_times_out_504(self) -> None:
        mw = RequestTimeoutMiddleware(_make_mock_app(), timeout_seconds=0.01)

        async def slow_call_next(req):
            await asyncio.sleep(1)
            return _make_response(200)

        response = await mw.dispatch(_make_request(), slow_call_next)
        assert response.status_code == 504
