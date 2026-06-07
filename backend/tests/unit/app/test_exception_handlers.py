"""Тесты обработчиков исключений: маппинг ошибок в HTTP-ответы."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exception_handlers import (
    cookie_error_handler,
    database_error_handler,
    http_exception_handler,
    jwt_error_handler,
    permission_check_handler,
    permission_denied_handler,
    pydantic_validation_error_handler,
    request_validation_error_handler,
    service_error_handler,
    storage_error_handler,
    unexpected_exception_handler,
)
from database.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    DatabaseTimeoutError,
)
from security.cookies.exceptions import CookieError
from security.jwt.exceptions import (
    JwtExpiredError,
    JwtInvalidClaimsError,
    JwtInvalidTokenTypeError,
    JwtTokenError,
)
from security.jwt.enums import JwtTokenType
from security.permissions.exceptions import PermissionCheckError, PermissionDeniedError
from services.exceptions import (
    AuthenticationServiceError,
    NotFoundServiceError,
    ServiceError,
    ValidationServiceError,
)
from storage.exceptions import (
    StorageConnectionError,
    StorageError,
    StorageTimeoutError,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _make_request(request_id: str | None = "test-request-id") -> MagicMock:
    req = MagicMock(spec=Request)
    req.state = MagicMock()
    # Убираем request_context, чтобы _get_request_id брал id из state
    del req.state.request_context
    req.state.request_id = request_id
    req.headers = {}
    return req


def _body(response) -> dict:
    """Разбирает JSON-тело ответа JSONResponse."""
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# service_error_handler
# ---------------------------------------------------------------------------


class TestServiceErrorHandler:
    @pytest.mark.asyncio
    async def test_base_service_error_returns_500(self) -> None:
        exc = ServiceError("Something went wrong.")
        response = await service_error_handler(_make_request(), exc)
        assert response.status_code == 500
        body = _body(response)
        assert body["error"] == "service_error"
        assert body["message"] == "Something went wrong."

    @pytest.mark.asyncio
    async def test_authentication_service_error_returns_401(self) -> None:
        exc = AuthenticationServiceError("Auth failed.")
        response = await service_error_handler(_make_request(), exc)
        assert response.status_code == 401
        body = _body(response)
        assert body["error"] == "authentication_error"

    @pytest.mark.asyncio
    async def test_not_found_service_error_returns_404(self) -> None:
        exc = NotFoundServiceError("User not found.")
        response = await service_error_handler(_make_request(), exc)
        assert response.status_code == 404
        body = _body(response)
        assert body["error"] == "not_found"
        assert body["message"] == "User not found."

    @pytest.mark.asyncio
    async def test_validation_service_error_returns_422(self) -> None:
        exc = ValidationServiceError("Invalid data.")
        response = await service_error_handler(_make_request(), exc)
        assert response.status_code == 422
        body = _body(response)
        assert body["error"] == "validation_error"

    @pytest.mark.asyncio
    async def test_response_contains_request_id(self) -> None:
        exc = ServiceError("Error.")
        response = await service_error_handler(_make_request("my-req-id"), exc)
        body = _body(response)
        assert body["request_id"] == "my-req-id"

    @pytest.mark.asyncio
    async def test_response_contains_message(self) -> None:
        exc = ServiceError("Specific message.")
        response = await service_error_handler(_make_request(), exc)
        body = _body(response)
        assert "message" in body
        assert body["message"] == "Specific message."

    @pytest.mark.asyncio
    async def test_request_id_none_when_not_set(self) -> None:
        exc = ServiceError("Error.")
        response = await service_error_handler(_make_request(request_id=None), exc)
        body = _body(response)
        assert body["request_id"] is None


# ---------------------------------------------------------------------------
# database_error_handler
# ---------------------------------------------------------------------------


class TestDatabaseErrorHandler:
    @pytest.mark.asyncio
    async def test_database_connection_error_returns_503(self) -> None:
        exc = DatabaseConnectionError("DB unreachable.")
        response = await database_error_handler(_make_request(), exc)
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_database_timeout_error_returns_503(self) -> None:
        exc = DatabaseTimeoutError("DB timeout.")
        response = await database_error_handler(_make_request(), exc)
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_generic_database_error_returns_500(self) -> None:
        exc = DatabaseError("DB error.")
        response = await database_error_handler(_make_request(), exc)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_response_body_has_error_and_message(self) -> None:
        exc = DatabaseError("DB error.")
        response = await database_error_handler(_make_request(), exc)
        body = _body(response)
        assert "error" in body
        assert "message" in body


# ---------------------------------------------------------------------------
# storage_error_handler
# ---------------------------------------------------------------------------


class TestStorageErrorHandler:
    @pytest.mark.asyncio
    async def test_storage_connection_error_returns_503(self) -> None:
        exc = StorageConnectionError("Storage unreachable.")
        response = await storage_error_handler(_make_request(), exc)
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_storage_timeout_error_returns_503(self) -> None:
        exc = StorageTimeoutError("Storage timeout.")
        response = await storage_error_handler(_make_request(), exc)
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_generic_storage_error_returns_500(self) -> None:
        exc = StorageError("Storage error.")
        response = await storage_error_handler(_make_request(), exc)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_response_body_has_error(self) -> None:
        exc = StorageError("Storage error.")
        response = await storage_error_handler(_make_request(), exc)
        body = _body(response)
        assert "error" in body


# ---------------------------------------------------------------------------
# cookie_error_handler
# ---------------------------------------------------------------------------


class TestCookieErrorHandler:
    @pytest.mark.asyncio
    async def test_returns_401(self) -> None:
        exc = CookieError("Missing cookie.")
        response = await cookie_error_handler(_make_request(), exc)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_body_has_error_and_message(self) -> None:
        exc = CookieError("Missing cookie.")
        response = await cookie_error_handler(_make_request(), exc)
        body = _body(response)
        assert body["error"] == "CookieError"
        assert body["message"] == "Missing cookie."

    @pytest.mark.asyncio
    async def test_body_contains_request_id(self) -> None:
        exc = CookieError("Missing cookie.")
        response = await cookie_error_handler(_make_request("req-abc"), exc)
        body = _body(response)
        assert body["request_id"] == "req-abc"


# ---------------------------------------------------------------------------
# jwt_error_handler
# ---------------------------------------------------------------------------


class TestJwtErrorHandler:
    @pytest.mark.asyncio
    async def test_jwt_token_error_returns_401(self) -> None:
        exc = JwtTokenError("Invalid token.")
        response = await jwt_error_handler(_make_request(), exc)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_expired_error_returns_401(self) -> None:
        exc = JwtExpiredError("Token expired.")
        response = await jwt_error_handler(_make_request(), exc)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_invalid_claims_error_returns_401(self) -> None:
        exc = JwtInvalidClaimsError("Bad claims.")
        response = await jwt_error_handler(_make_request(), exc)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_invalid_token_type_error_returns_401(self) -> None:
        exc = JwtInvalidTokenTypeError(
            expected_type="access",
            actual_type="refresh",
        )
        response = await jwt_error_handler(_make_request(), exc)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_body_has_error_field(self) -> None:
        exc = JwtExpiredError()
        response = await jwt_error_handler(_make_request(), exc)
        body = _body(response)
        assert "error" in body
        assert "message" in body


# ---------------------------------------------------------------------------
# permission_denied_handler
# ---------------------------------------------------------------------------


class TestPermissionDeniedHandler:
    @pytest.mark.asyncio
    async def test_returns_403(self) -> None:
        exc = PermissionDeniedError("Not allowed.")
        response = await permission_denied_handler(_make_request(), exc)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_body_has_error_and_message(self) -> None:
        exc = PermissionDeniedError("Not allowed.")
        response = await permission_denied_handler(_make_request(), exc)
        body = _body(response)
        assert body["error"] == "PermissionDeniedError"
        assert body["message"] == "Not allowed."


# ---------------------------------------------------------------------------
# permission_check_handler
# ---------------------------------------------------------------------------


class TestPermissionCheckHandler:
    @pytest.mark.asyncio
    async def test_returns_403(self) -> None:
        exc = PermissionCheckError("Check failed.")
        response = await permission_check_handler(_make_request(), exc)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_body_has_error(self) -> None:
        exc = PermissionCheckError("Check failed.")
        response = await permission_check_handler(_make_request(), exc)
        body = _body(response)
        assert "error" in body


# ---------------------------------------------------------------------------
# request_validation_error_handler
# ---------------------------------------------------------------------------


class TestRequestValidationErrorHandler:
    @pytest.mark.asyncio
    async def test_returns_422(self) -> None:
        raw_errors = [
            {"loc": ("body", "field_name"), "msg": "Field required", "type": "missing", "input": None}
        ]
        exc = RequestValidationError(errors=raw_errors)
        response = await request_validation_error_handler(_make_request(), exc)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_body_has_errors_list(self) -> None:
        raw_errors = [
            {"loc": ("body", "email"), "msg": "Invalid email", "type": "value_error", "input": "bad"}
        ]
        exc = RequestValidationError(errors=raw_errors)
        response = await request_validation_error_handler(_make_request(), exc)
        body = _body(response)
        assert "errors" in body
        assert isinstance(body["errors"], list)
        assert len(body["errors"]) == 1

    @pytest.mark.asyncio
    async def test_error_item_has_field_and_message(self) -> None:
        raw_errors = [
            {"loc": ("body", "username"), "msg": "Field required", "type": "missing", "input": None}
        ]
        exc = RequestValidationError(errors=raw_errors)
        response = await request_validation_error_handler(_make_request(), exc)
        body = _body(response)
        item = body["errors"][0]
        assert "field" in item
        assert "message" in item

    @pytest.mark.asyncio
    async def test_body_contains_request_id(self) -> None:
        raw_errors = [
            {"loc": ("body", "x"), "msg": "error", "type": "missing", "input": None}
        ]
        exc = RequestValidationError(errors=raw_errors)
        response = await request_validation_error_handler(_make_request("req-123"), exc)
        body = _body(response)
        assert body["request_id"] == "req-123"


# ---------------------------------------------------------------------------
# pydantic_validation_error_handler
# ---------------------------------------------------------------------------


class TestPydanticValidationErrorHandler:
    @pytest.mark.asyncio
    async def test_returns_422(self) -> None:
        from pydantic import BaseModel

        class SampleModel(BaseModel):
            age: int

        try:
            SampleModel(age="not-a-number")
        except ValidationError as exc:
            response = await pydantic_validation_error_handler(_make_request(), exc)
            assert response.status_code == 422
        else:
            pytest.fail("ValidationError not raised")

    @pytest.mark.asyncio
    async def test_body_has_errors_list(self) -> None:
        from pydantic import BaseModel

        class SampleModel(BaseModel):
            name: str

        try:
            SampleModel(name=123)  # type: ignore[arg-type]
            # name=123 приводится pydantic к "123"; используем None вместо этого
            SampleModel(name=None)  # type: ignore[arg-type]
        except ValidationError as exc:
            response = await pydantic_validation_error_handler(_make_request(), exc)
            body = _body(response)
            assert "errors" in body
        else:
            # Если исключение не возникло, провоцируем его принудительно
            class StrictModel(BaseModel):
                model_config = {"strict": True}
                value: int

            try:
                StrictModel(value="not-int")
            except ValidationError as exc:
                response = await pydantic_validation_error_handler(_make_request(), exc)
                body = _body(response)
                assert "errors" in body


# ---------------------------------------------------------------------------
# http_exception_handler
# ---------------------------------------------------------------------------


class TestHttpExceptionHandler:
    @pytest.mark.asyncio
    async def test_passes_through_status_code(self) -> None:
        exc = StarletteHTTPException(status_code=404, detail="Not found")
        response = await http_exception_handler(_make_request(), exc)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_403_passes_through(self) -> None:
        exc = StarletteHTTPException(status_code=403, detail="Forbidden")
        response = await http_exception_handler(_make_request(), exc)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_body_has_error_field_http_exception(self) -> None:
        exc = StarletteHTTPException(status_code=400, detail="Bad request")
        response = await http_exception_handler(_make_request(), exc)
        body = _body(response)
        assert body["error"] == "HTTPException"

    @pytest.mark.asyncio
    async def test_string_detail_used_as_message(self) -> None:
        exc = StarletteHTTPException(status_code=404, detail="Resource not found")
        response = await http_exception_handler(_make_request(), exc)
        body = _body(response)
        assert body["message"] == "Resource not found"

    @pytest.mark.asyncio
    async def test_dict_detail_used_as_details(self) -> None:
        exc = StarletteHTTPException(
            status_code=400,
            detail={"message": "Custom msg", "extra": "data"},
        )
        response = await http_exception_handler(_make_request(), exc)
        body = _body(response)
        assert body["message"] == "Custom msg"
        assert body["details"] is not None

    @pytest.mark.asyncio
    async def test_headers_propagated(self) -> None:
        exc = StarletteHTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
        response = await http_exception_handler(_make_request(), exc)
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    @pytest.mark.asyncio
    async def test_body_contains_request_id(self) -> None:
        exc = StarletteHTTPException(status_code=404, detail="Not found")
        response = await http_exception_handler(_make_request("rid-xyz"), exc)
        body = _body(response)
        assert body["request_id"] == "rid-xyz"


# ---------------------------------------------------------------------------
# unexpected_exception_handler
# ---------------------------------------------------------------------------


class TestUnexpectedExceptionHandler:
    @pytest.mark.asyncio
    async def test_returns_500(self) -> None:
        exc = RuntimeError("Boom!")
        response = await unexpected_exception_handler(_make_request(), exc)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_body_has_error_class_name(self) -> None:
        exc = ValueError("Bad value")
        response = await unexpected_exception_handler(_make_request(), exc)
        body = _body(response)
        assert body["error"] == "ValueError"

    @pytest.mark.asyncio
    async def test_body_contains_internal_error_message(self) -> None:
        exc = RuntimeError("Boom!")
        response = await unexpected_exception_handler(_make_request(), exc)
        body = _body(response)
        assert "message" in body
        assert "ошибка" in body["message"].lower() or "error" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_body_contains_request_id(self) -> None:
        exc = Exception("generic")
        response = await unexpected_exception_handler(_make_request("req-500"), exc)
        body = _body(response)
        assert body["request_id"] == "req-500"

    @pytest.mark.asyncio
    async def test_body_details_contains_reason(self) -> None:
        exc = RuntimeError("original cause")
        response = await unexpected_exception_handler(_make_request(), exc)
        body = _body(response)
        assert body["details"]["reason"] == "original cause"


# ---------------------------------------------------------------------------
# Хелпер _get_request_id — проверяется косвенно через ответы обработчиков
# ---------------------------------------------------------------------------


class TestGetRequestId:
    @pytest.mark.asyncio
    async def test_request_id_from_state(self) -> None:
        """state.request_id корректно считывается."""
        req = MagicMock(spec=Request)
        req.state = MagicMock()
        del req.state.request_context
        req.state.request_id = "state-id"
        req.headers = {}

        exc = ServiceError("err")
        response = await service_error_handler(req, exc)
        body = _body(response)
        assert body["request_id"] == "state-id"

    @pytest.mark.asyncio
    async def test_request_id_from_header(self) -> None:
        """При отсутствии id в state берётся заголовок X-Request-ID."""
        req = MagicMock(spec=Request)
        req.state = MagicMock(spec=[])  # без атрибутов
        req.headers = {"X-Request-ID": "header-id"}

        exc = ServiceError("err")
        response = await service_error_handler(req, exc)
        body = _body(response)
        assert body["request_id"] == "header-id"

    @pytest.mark.asyncio
    async def test_request_id_none_when_absent(self) -> None:
        """Возвращает None, когда id нет ни в state, ни в заголовке."""
        req = MagicMock(spec=Request)
        req.state = MagicMock(spec=[])
        req.headers = {}

        exc = ServiceError("err")
        response = await service_error_handler(req, exc)
        body = _body(response)
        assert body["request_id"] is None

    @pytest.mark.asyncio
    async def test_request_id_from_request_context(self) -> None:
        """request_context.request_id приоритетнее state/заголовка."""
        from app.exception_handlers import _get_request_id

        req = MagicMock(spec=Request)
        req.state = MagicMock()
        req.state.request_context = MagicMock(request_id="  ctx-id  ")
        req.state.request_id = "state-id"
        req.headers = {"X-Request-ID": "header-id"}

        assert _get_request_id(req) == "ctx-id"


# ---------------------------------------------------------------------------
# register_exception_handlers
# ---------------------------------------------------------------------------


class TestRegisterExceptionHandlers:
    def test_registers_all_handlers(self) -> None:
        from fastapi import FastAPI

        from app.exception_handlers import register_exception_handlers

        app = FastAPI()
        register_exception_handlers(app)

        registered = set(app.exception_handlers.keys())
        for exc_type in (
            ServiceError,
            DatabaseError,
            StorageError,
            CookieError,
            JwtTokenError,
            PermissionDeniedError,
            PermissionCheckError,
            RequestValidationError,
            ValidationError,
            StarletteHTTPException,
            Exception,
        ):
            assert exc_type in registered


# ---------------------------------------------------------------------------
# _http_exception_message / _normalize_optional_str fallbacks
# ---------------------------------------------------------------------------


class TestHelperFallbacks:
    def test_http_exception_message_fallback_for_non_string_detail(self) -> None:
        from app.exception_handlers import _http_exception_message

        # detail-список не str и не dict -> сообщение по умолчанию.
        assert _http_exception_message([1, 2, 3]) == "HTTP-ошибка."

    def test_http_exception_message_blank_string_falls_back(self) -> None:
        from app.exception_handlers import _http_exception_message

        assert _http_exception_message("   ") == "HTTP-ошибка."

    def test_normalize_optional_str_returns_none_for_none(self) -> None:
        from app.exception_handlers import _normalize_optional_str

        assert _normalize_optional_str(None) is None

    def test_normalize_optional_str_strips_value(self) -> None:
        from app.exception_handlers import _normalize_optional_str

        assert _normalize_optional_str("  missing  ") == "missing"
