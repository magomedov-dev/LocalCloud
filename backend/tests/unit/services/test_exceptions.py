"""Юнит-тесты для иерархии и преобразователей исключений сервисного слоя."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from http import HTTPStatus
from typing import Any

import pytest

from database.exceptions import (
    ConstraintViolationError,
    DatabaseConnectionError,
    DatabaseError,
    DatabaseTimeoutError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidPaginationError,
    InvalidQueryError,
    TransactionError,
    UnitOfWorkError,
)
from security.jwt.exceptions import JwtExpiredError, JwtInvalidClaimsError, JwtTokenError
from security.permissions.exceptions import PermissionDeniedError
from services.exceptions import (
    AuthenticationServiceError,
    AuthorizationServiceError,
    BackgroundTaskServiceError,
    ConflictServiceError,
    NotFoundServiceError,
    PermissionServiceError,
    QuotaExceededServiceError,
    RegistrationServiceError,
    ServiceError,
    ServiceErrorCategory,
    ServiceErrorCode,
    StorageServiceError,
    UploadServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
    service_error_from_security,
    service_error_to_response,
)
from storage.exceptions import (
    StorageBucketNotFoundError,
    StorageConnectionError,
    StorageObjectNotFoundError,
    StoragePermissionDeniedError,
)


class TestServiceError:
    def test_default_message_used_when_none(self) -> None:
        err = ServiceError()
        assert err.message == ServiceError.default_message

    def test_custom_message_stored(self) -> None:
        err = ServiceError("custom error")
        assert err.message == "custom error"

    def test_default_code(self) -> None:
        err = ServiceError()
        assert err.code == ServiceErrorCode.SERVICE_ERROR.value

    def test_default_category(self) -> None:
        err = ServiceError()
        assert err.category == ServiceErrorCategory.INTERNAL

    def test_default_status_code(self) -> None:
        err = ServiceError()
        assert err.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_default_not_retryable(self) -> None:
        err = ServiceError()
        assert err.retryable is False

    def test_custom_retryable_stored(self) -> None:
        err = ServiceError(retryable=True)
        assert err.retryable is True

    def test_service_and_operation_added_to_details(self) -> None:
        err = ServiceError("msg", service="svc", operation="op")
        assert err.details["service"] == "svc"
        assert err.details["operation"] == "op"

    def test_cause_stored(self) -> None:
        cause = ValueError("root")
        err = ServiceError(cause=cause)
        assert err.cause is cause
        assert err.__cause__ is cause

    def test_str_without_details(self) -> None:
        err = ServiceError("msg")
        err.details.clear()
        assert str(err) == "msg"

    def test_str_with_details(self) -> None:
        err = ServiceError("msg", service="svc")
        assert "msg" in str(err)
        assert "Details" in str(err)

    def test_is_client_error_for_4xx(self) -> None:
        err = ServiceError(status_code=404)
        assert err.is_client_error is True
        assert err.is_server_error is False

    def test_is_server_error_for_5xx(self) -> None:
        err = ServiceError(status_code=500)
        assert err.is_server_error is True
        assert err.is_client_error is False

    def test_is_neither_for_3xx(self) -> None:
        err = ServiceError(status_code=302)
        assert err.is_client_error is False
        assert err.is_server_error is False

    def test_to_dict_required_keys(self) -> None:
        err = ServiceError("test")
        d = err.to_dict()
        for key in ("error", "code", "category", "message", "status_code", "retryable"):
            assert key in d

    def test_to_dict_includes_cause_class(self) -> None:
        cause = RuntimeError("root")
        err = ServiceError(cause=cause)
        assert err.to_dict()["cause"] == "RuntimeError"

    def test_to_dict_omits_cause_when_none(self) -> None:
        err = ServiceError()
        assert "cause" not in err.to_dict()

    def test_to_dict_include_cause_false(self) -> None:
        err = ServiceError(cause=ValueError())
        assert "cause" not in err.to_dict(include_cause=False)

    def test_to_error_response_has_correct_fields(self) -> None:
        err = ServiceError("test message")
        resp = err.to_error_response()
        assert resp.success is False
        assert resp.message == "test message"
        assert resp.error == err.code

    def test_to_error_response_includes_request_id(self) -> None:
        err = ServiceError("test")
        resp = err.to_error_response(request_id="req-123")
        assert resp.request_id == "req-123"

    def test_is_exception_subclass(self) -> None:
        assert issubclass(ServiceError, Exception)


class TestSpecializedServiceErrors:
    def test_validation_error_has_422_status(self) -> None:
        err = ValidationServiceError()
        assert err.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_validation_error_field_in_details(self) -> None:
        err = ValidationServiceError(field="email", value="bad@", reason="format")
        assert err.details.get("field") == "email"
        assert err.details.get("value") == "bad@"
        assert err.details.get("reason") == "format"

    def test_conflict_error_has_409_status(self) -> None:
        err = ConflictServiceError()
        assert err.status_code == HTTPStatus.CONFLICT

    def test_conflict_error_entity_in_details(self) -> None:
        err = ConflictServiceError(entity_name="User", field="email")
        assert err.details.get("entity") == "User"
        assert err.details.get("field") == "email"

    def test_not_found_error_has_404_status(self) -> None:
        err = NotFoundServiceError()
        assert err.status_code == HTTPStatus.NOT_FOUND

    def test_not_found_error_auto_message_with_entity_name(self) -> None:
        err = NotFoundServiceError(entity_name="User")
        assert "User" in err.message

    def test_not_found_error_custom_message_overrides_auto(self) -> None:
        err = NotFoundServiceError("explicit message", entity_name="User")
        assert err.message == "explicit message"

    def test_not_found_entity_and_id_in_details(self) -> None:
        uid = uuid.uuid4()
        err = NotFoundServiceError(entity_name="User", entity_id=uid)
        assert err.details.get("entity") == "User"
        assert err.details.get("entity_id") == str(uid)

    def test_auth_error_has_401_status(self) -> None:
        err = AuthenticationServiceError()
        assert err.status_code == HTTPStatus.UNAUTHORIZED

    def test_auth_error_user_id_in_details(self) -> None:
        uid = uuid.uuid4()
        err = AuthenticationServiceError(user_id=uid, reason="expired")
        assert err.details.get("user_id") == str(uid)
        assert err.details.get("reason") == "expired"

    def test_authz_error_has_403_status(self) -> None:
        err = AuthorizationServiceError()
        assert err.status_code == HTTPStatus.FORBIDDEN

    def test_permission_error_has_403_status(self) -> None:
        err = PermissionServiceError()
        assert err.status_code == HTTPStatus.FORBIDDEN

    def test_quota_error_has_413_status(self) -> None:
        err = QuotaExceededServiceError()
        assert err.status_code == 413

    def test_quota_error_quota_fields_in_details(self) -> None:
        uid = uuid.uuid4()
        err = QuotaExceededServiceError(
            user_id=uid, requested=100, used=90, limit=100, available=10
        )
        assert err.details.get("requested") == 100
        assert err.details.get("used") == 90
        assert err.details.get("limit") == 100

    def test_storage_service_error_is_retryable(self) -> None:
        err = StorageServiceError()
        assert err.retryable is True

    def test_storage_service_error_bucket_and_key_in_details(self) -> None:
        err = StorageServiceError(bucket="my-bucket", object_key="path/to/file")
        assert err.details.get("bucket") == "my-bucket"
        assert err.details.get("object_key") == "path/to/file"

    def test_upload_error_has_conflict_status(self) -> None:
        err = UploadServiceError()
        assert err.status_code == HTTPStatus.CONFLICT

    def test_upload_error_fields_in_details(self) -> None:
        uid = uuid.uuid4()
        session_id = uuid.uuid4()
        err = UploadServiceError(upload_session_id=session_id, user_id=uid, part_number=3)
        assert err.details.get("upload_session_id") == str(session_id)
        assert err.details.get("part_number") == 3

    def test_background_task_error_has_conflict_status(self) -> None:
        err = BackgroundTaskServiceError()
        assert err.status_code == HTTPStatus.CONFLICT

    def test_registration_error_has_conflict_status(self) -> None:
        err = RegistrationServiceError()
        assert err.status_code == HTTPStatus.CONFLICT

    def test_registration_error_fields_in_details(self) -> None:
        err = RegistrationServiceError(email="a@b.com", reason="duplicate")
        assert err.details.get("email") == "a@b.com"
        assert err.details.get("reason") == "duplicate"


class TestServiceErrorFromDatabase:
    def test_entity_not_found_produces_not_found_error(self) -> None:
        exc = EntityNotFoundError("User", entity_id=uuid.uuid4())
        result = service_error_from_database(exc)
        assert isinstance(result, NotFoundServiceError)

    def test_duplicate_entity_produces_conflict_error(self) -> None:
        exc = DuplicateEntityError("User", field="email", value="a@b.com")
        result = service_error_from_database(exc)
        assert isinstance(result, ConflictServiceError)

    def test_constraint_violation_produces_conflict_error(self) -> None:
        exc = ConstraintViolationError(constraint_name="uq_users_email")
        result = service_error_from_database(exc)
        assert isinstance(result, ConflictServiceError)

    def test_invalid_pagination_produces_validation_error(self) -> None:
        exc = InvalidPaginationError(limit=-1)
        result = service_error_from_database(exc)
        assert isinstance(result, ValidationServiceError)

    def test_invalid_query_produces_validation_error(self) -> None:
        exc = InvalidQueryError("bad query")
        result = service_error_from_database(exc)
        assert isinstance(result, ValidationServiceError)

    def test_connection_error_is_retryable(self) -> None:
        exc = DatabaseConnectionError()
        result = service_error_from_database(exc)
        assert result.retryable is True

    def test_connection_error_has_503_status(self) -> None:
        exc = DatabaseConnectionError()
        result = service_error_from_database(exc)
        assert result.status_code == HTTPStatus.SERVICE_UNAVAILABLE

    def test_timeout_error_is_retryable(self) -> None:
        exc = DatabaseTimeoutError()
        result = service_error_from_database(exc)
        assert result.retryable is True

    def test_transaction_error_is_retryable(self) -> None:
        exc = TransactionError()
        result = service_error_from_database(exc)
        assert result.retryable is True

    def test_uow_error_is_retryable(self) -> None:
        exc = UnitOfWorkError()
        result = service_error_from_database(exc)
        assert result.retryable is True

    def test_custom_message_used(self) -> None:
        exc = EntityNotFoundError("Role")
        result = service_error_from_database(exc, message="Role not found in service")
        assert result.message == "Role not found in service"

    def test_service_and_operation_in_details(self) -> None:
        exc = DatabaseError()
        result = service_error_from_database(exc, service="auth", operation="login")
        assert result.details.get("service") == "auth"
        assert result.details.get("operation") == "login"

    def test_original_exception_stored_as_cause(self) -> None:
        exc = EntityNotFoundError("User")
        result = service_error_from_database(exc)
        assert result.cause is exc


class TestServiceErrorFromStorage:
    def test_object_not_found_produces_not_found_error(self) -> None:
        from services.exceptions import service_error_from_storage
        exc = StorageObjectNotFoundError(bucket="my-bucket", object_key="path/to/file.txt")
        result = service_error_from_storage(exc)
        assert isinstance(result, NotFoundServiceError)

    def test_bucket_not_found_produces_not_found_error(self) -> None:
        from services.exceptions import service_error_from_storage
        exc = StorageBucketNotFoundError("my-bucket")
        result = service_error_from_storage(exc)
        assert isinstance(result, NotFoundServiceError)

    def test_permission_denied_not_retryable(self) -> None:
        from services.exceptions import service_error_from_storage
        exc = StoragePermissionDeniedError()
        result = service_error_from_storage(exc)
        assert result.retryable is False

    def test_connection_error_is_retryable(self) -> None:
        from services.exceptions import service_error_from_storage
        exc = StorageConnectionError()
        result = service_error_from_storage(exc)
        assert result.retryable is True


class TestServiceErrorFromSecurity:
    def test_jwt_expired_error_produces_auth_error(self) -> None:
        exc = JwtExpiredError()
        result = service_error_from_security(exc)
        assert isinstance(result, AuthenticationServiceError)
        assert result.details.get("reason") == "expired_token"

    def test_jwt_token_error_produces_auth_error(self) -> None:
        exc = JwtTokenError("invalid")
        result = service_error_from_security(exc)
        assert isinstance(result, AuthenticationServiceError)

    def test_jwt_invalid_claims_produces_auth_error(self) -> None:
        exc = JwtInvalidClaimsError()
        result = service_error_from_security(exc)
        assert isinstance(result, AuthenticationServiceError)

    def test_permission_denied_produces_permission_error(self) -> None:
        exc = PermissionDeniedError()
        result = service_error_from_security(exc)
        assert isinstance(result, PermissionServiceError)

    def test_custom_message_used(self) -> None:
        exc = JwtExpiredError()
        result = service_error_from_security(exc, message="Token has expired")
        assert result.message == "Token has expired"

    def test_unknown_exception_produces_base_service_error(self) -> None:
        exc = RuntimeError("unknown security issue")
        result = service_error_from_security(exc)
        assert isinstance(result, ServiceError)
        assert result.status_code == HTTPStatus.UNAUTHORIZED


class TestServiceErrorFromException:
    def test_service_error_passed_through_unchanged(self) -> None:
        original = NotFoundServiceError("entity not found")
        result = service_error_from_exception(original)
        assert result is original

    def test_database_error_converted(self) -> None:
        exc = EntityNotFoundError("User")
        result = service_error_from_exception(exc)
        assert isinstance(result, ServiceError)
        assert not isinstance(result, type(exc))

    def test_jwt_token_error_converted(self) -> None:
        exc = JwtTokenError("invalid token")
        result = service_error_from_exception(exc)
        assert isinstance(result, ServiceError)

    def test_unknown_exception_becomes_unexpected_error(self) -> None:
        exc = RuntimeError("something weird")
        result = service_error_from_exception(exc)
        assert result.code == ServiceErrorCode.UNEXPECTED_ERROR.value
        assert result.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_original_exception_is_cause(self) -> None:
        exc = RuntimeError("original")
        result = service_error_from_exception(exc)
        assert result.cause is exc


class TestServiceErrorToResponse:
    def test_returns_error_response(self) -> None:
        err = NotFoundServiceError("not found")
        resp = service_error_to_response(err)
        assert resp.success is False
        assert resp.message == "not found"

    def test_request_id_passed_to_response(self) -> None:
        err = ServiceError("error")
        resp = service_error_to_response(err, request_id="req-xyz")
        assert resp.request_id == "req-xyz"


class TestJsonableHelper:
    """Тесты для _jsonable через вывод to_dict, который его задействует."""

    def test_uuid_in_details_serialized_as_string(self) -> None:
        uid = uuid.uuid4()
        err = NotFoundServiceError(entity_name="X", entity_id=uid)
        d = err.to_dict()
        assert isinstance(d["details"]["entity_id"], str)
        assert d["details"]["entity_id"] == str(uid)

    def test_datetime_in_details_serialized_as_isoformat(self) -> None:
        now = datetime(2024, 1, 15, 10, 30, 0)
        err = ServiceError("msg", details={"ts": now})
        d = err.to_dict()
        assert "2024-01-15" in d["details"]["ts"]

    def test_enum_in_details_serialized_as_value(self) -> None:
        class Color(Enum):
            RED = "red"
        err = ServiceError("msg", details={"color": Color.RED})
        d = err.to_dict()
        assert d["details"]["color"] == "red"
