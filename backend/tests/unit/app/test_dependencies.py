"""Тесты зависимостей приложения: контекст запроса и нормализация данных."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.dependencies import (
    RequestContext,
    _extract_client_ip,
    _is_valid_ip_address,
    _normalize_identifier,
    _normalize_optional_text,
    build_request_context,
    get_request_context,
    get_request_id,
)


def _make_request(
    headers: dict | None = None,
    client_host: str | None = "127.0.0.1",
    state: dict | None = None,
) -> MagicMock:
    request = MagicMock()
    request.headers = headers or {}
    request.client = MagicMock(host=client_host) if client_host else None
    request.state = MagicMock(spec=[])
    if state:
        for k, v in state.items():
            setattr(request.state, k, v)
    return request


class TestIsValidIpAddress:
    def test_valid_ipv4(self) -> None:
        assert _is_valid_ip_address("127.0.0.1") is True
        assert _is_valid_ip_address("192.168.1.100") is True

    def test_valid_ipv6(self) -> None:
        assert _is_valid_ip_address("::1") is True
        assert _is_valid_ip_address("2001:db8::1") is True

    def test_invalid_ip(self) -> None:
        assert _is_valid_ip_address("not-an-ip") is False
        assert _is_valid_ip_address("999.999.999.999") is False

    def test_none_returns_false(self) -> None:
        assert _is_valid_ip_address(None) is False  # type: ignore[arg-type]

    def test_empty_string_returns_false(self) -> None:
        assert _is_valid_ip_address("") is False


class TestNormalizeOptionalText:
    def test_valid_string_returned(self) -> None:
        assert _normalize_optional_text("hello") == "hello"

    def test_strips_whitespace(self) -> None:
        assert _normalize_optional_text("  hello  ") == "hello"

    def test_none_returns_none(self) -> None:
        assert _normalize_optional_text(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _normalize_optional_text("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _normalize_optional_text("   ") is None


class TestNormalizeIdentifier:
    def test_valid_string_returned(self) -> None:
        assert _normalize_identifier("abc123", fallback="default") == "abc123"

    def test_none_returns_fallback(self) -> None:
        assert _normalize_identifier(None, fallback="fallback-id") == "fallback-id"

    def test_empty_string_returns_fallback(self) -> None:
        assert _normalize_identifier("", fallback="fb") == "fb"

    def test_whitespace_returns_fallback(self) -> None:
        assert _normalize_identifier("   ", fallback="fb") == "fb"


class TestExtractClientIp:
    def test_extracts_forwarded_for(self) -> None:
        request = _make_request(headers={"X-Forwarded-For": "10.0.0.1, 10.0.0.2"})
        ip = _extract_client_ip(request)
        assert ip == "10.0.0.1"

    def test_falls_back_to_client_host(self) -> None:
        request = _make_request(client_host="192.168.1.50")
        ip = _extract_client_ip(request)
        assert ip == "192.168.1.50"

    def test_invalid_forwarded_for_falls_back(self) -> None:
        request = _make_request(
            headers={"X-Forwarded-For": "not-an-ip"},
            client_host="10.0.0.5",
        )
        ip = _extract_client_ip(request)
        assert ip == "10.0.0.5"

    def test_no_client_returns_none(self) -> None:
        request = _make_request(client_host=None)
        ip = _extract_client_ip(request)
        assert ip is None

    def test_invalid_client_host_returns_none(self) -> None:
        # Нет заголовка X-Forwarded-For, а request.client.host не валидный IP.
        request = _make_request(client_host="not-an-ip")
        ip = _extract_client_ip(request)
        assert ip is None


class TestGetRequestContext:
    def test_returns_built_context(self) -> None:
        request = _make_request()
        ctx = get_request_context(request)
        assert isinstance(ctx, RequestContext)

    def test_returns_cached_context(self) -> None:
        request = _make_request()
        existing = RequestContext(request_id="r-1", correlation_id="c-1")
        request.state.request_context = existing
        assert get_request_context(request) is existing


class TestGetRequestId:
    def test_returns_request_id_from_context(self) -> None:
        ctx = RequestContext(request_id="the-id", correlation_id="c")
        assert get_request_id(ctx) == "the-id"


class TestBuildRequestContext:
    def test_returns_request_context(self) -> None:
        request = _make_request()
        ctx = build_request_context(request)
        assert isinstance(ctx, RequestContext)

    def test_request_id_generated(self) -> None:
        request = _make_request()
        ctx = build_request_context(request)
        assert ctx.request_id
        assert len(ctx.request_id) > 0

    def test_custom_request_id_from_header(self) -> None:
        request = _make_request(headers={"X-Request-ID": "my-request-id"})
        ctx = build_request_context(request)
        assert ctx.request_id == "my-request-id"

    def test_correlation_id_defaults_to_request_id(self) -> None:
        request = _make_request()
        ctx = build_request_context(request)
        assert ctx.correlation_id == ctx.request_id

    def test_custom_correlation_id(self) -> None:
        request = _make_request(headers={
            "X-Request-ID": "req-123",
            "X-Correlation-ID": "corr-456",
        })
        ctx = build_request_context(request)
        assert ctx.request_id == "req-123"
        assert ctx.correlation_id == "corr-456"

    def test_client_ip_extracted(self) -> None:
        request = _make_request(client_host="10.10.10.10")
        ctx = build_request_context(request)
        assert ctx.client_ip == "10.10.10.10"

    def test_user_agent_extracted(self) -> None:
        request = _make_request(headers={"User-Agent": "TestClient/1.0"})
        ctx = build_request_context(request)
        assert ctx.user_agent == "TestClient/1.0"

    def test_cached_context_returned_on_second_call(self) -> None:
        request = _make_request()
        ctx1 = build_request_context(request)
        # Имитируем закэшированный контекст
        request.state.request_context = ctx1
        ctx2 = build_request_context(request)
        assert ctx1 is ctx2

    def test_context_saved_to_request_state(self) -> None:
        request = _make_request()
        ctx = build_request_context(request)
        assert request.state.request_context is ctx
        assert request.state.request_id == ctx.request_id


class TestRequestContext:
    def test_is_frozen(self) -> None:
        ctx = RequestContext(request_id="r", correlation_id="c")
        with pytest.raises((AttributeError, TypeError)):
            ctx.request_id = "other"  # type: ignore[misc]

    def test_optional_fields_default_none(self) -> None:
        ctx = RequestContext(request_id="r", correlation_id="c")
        assert ctx.client_ip is None
        assert ctx.user_agent is None

    def test_all_fields_stored(self) -> None:
        ctx = RequestContext(
            request_id="req-1",
            correlation_id="corr-1",
            client_ip="1.2.3.4",
            user_agent="Browser/1.0",
        )
        assert ctx.request_id == "req-1"
        assert ctx.correlation_id == "corr-1"
        assert ctx.client_ip == "1.2.3.4"
        assert ctx.user_agent == "Browser/1.0"
