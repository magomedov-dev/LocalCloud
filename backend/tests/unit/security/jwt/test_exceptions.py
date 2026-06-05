"""Тесты исключений JWT: базовое JwtTokenError и его подклассы."""

from __future__ import annotations

import pytest

from security.jwt.enums import JwtErrorCode
from security.jwt.exceptions import (
    JwtExpiredError,
    JwtInvalidClaimsError,
    JwtInvalidTokenTypeError,
    JwtTokenError,
)


class TestJwtTokenError:
    def test_default_message(self) -> None:
        err = JwtTokenError()
        assert "JWT" in err.message

    def test_custom_message_stored(self) -> None:
        err = JwtTokenError("custom error")
        assert err.message == "custom error"

    def test_default_code(self) -> None:
        err = JwtTokenError()
        assert err.code == JwtErrorCode.INVALID_TOKEN

    def test_custom_code_stored(self) -> None:
        err = JwtTokenError(code=JwtErrorCode.EXPIRED_TOKEN)
        assert err.code == JwtErrorCode.EXPIRED_TOKEN

    def test_details_copied_not_shared(self) -> None:
        original = {"key": "value"}
        err = JwtTokenError(details=original)
        original["key"] = "modified"
        assert err.details["key"] == "value"

    def test_empty_details_default(self) -> None:
        err = JwtTokenError()
        assert err.details == {}

    def test_cause_stored(self) -> None:
        cause = ValueError("root cause")
        err = JwtTokenError(cause=cause)
        assert err.cause is cause
        assert err.__cause__ is cause

    def test_str_without_details(self) -> None:
        err = JwtTokenError("simple message")
        assert str(err) == "simple message"

    def test_str_with_details(self) -> None:
        err = JwtTokenError("msg", details={"field": "val"})
        result = str(err)
        assert "msg" in result
        assert "Details" in result

    def test_to_dict_contains_required_keys(self) -> None:
        err = JwtTokenError("test", code=JwtErrorCode.MISSING_SUBJECT)
        d = err.to_dict()
        assert d["error"] == "JwtTokenError"
        assert d["code"] == JwtErrorCode.MISSING_SUBJECT.value
        assert d["message"] == "test"

    def test_to_dict_includes_details(self) -> None:
        err = JwtTokenError("test", details={"x": 1})
        assert err.to_dict()["details"] == {"x": 1}

    def test_to_dict_omits_details_when_empty(self) -> None:
        err = JwtTokenError("test")
        assert "details" not in err.to_dict()

    def test_to_dict_includes_cause_class(self) -> None:
        cause = RuntimeError("oops")
        err = JwtTokenError("test", cause=cause)
        assert err.to_dict()["cause"] == "RuntimeError"

    def test_to_dict_omits_cause_when_none(self) -> None:
        err = JwtTokenError("test")
        assert "cause" not in err.to_dict()

    def test_is_exception_subclass(self) -> None:
        assert issubclass(JwtTokenError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(JwtTokenError):
            raise JwtTokenError("raised")


class TestJwtExpiredError:
    def test_is_subclass_of_jwt_token_error(self) -> None:
        assert issubclass(JwtExpiredError, JwtTokenError)

    def test_code_is_expired_token(self) -> None:
        err = JwtExpiredError()
        assert err.code == JwtErrorCode.EXPIRED_TOKEN

    def test_default_message_mentions_expiry(self) -> None:
        err = JwtExpiredError()
        assert "истёк" in err.message.lower() or "expired" in err.message.lower()

    def test_custom_message(self) -> None:
        err = JwtExpiredError("my expired message")
        assert err.message == "my expired message"

    def test_details_stored(self) -> None:
        err = JwtExpiredError(details={"exp": 123})
        assert err.details["exp"] == 123

    def test_cause_stored(self) -> None:
        cause = ValueError("exp")
        err = JwtExpiredError(cause=cause)
        assert err.cause is cause


class TestJwtInvalidClaimsError:
    def test_is_subclass_of_jwt_token_error(self) -> None:
        assert issubclass(JwtInvalidClaimsError, JwtTokenError)

    def test_code_is_invalid_claims(self) -> None:
        err = JwtInvalidClaimsError()
        assert err.code == JwtErrorCode.INVALID_CLAIMS

    def test_default_message(self) -> None:
        err = JwtInvalidClaimsError()
        assert err.message

    def test_details_stored(self) -> None:
        err = JwtInvalidClaimsError(details={"claim": "sub"})
        assert err.details["claim"] == "sub"

    def test_to_dict_code(self) -> None:
        err = JwtInvalidClaimsError()
        assert err.to_dict()["code"] == JwtErrorCode.INVALID_CLAIMS.value


class TestJwtInvalidTokenTypeError:
    def test_is_subclass_of_jwt_token_error(self) -> None:
        assert issubclass(JwtInvalidTokenTypeError, JwtTokenError)

    def test_code_is_invalid_token_type(self) -> None:
        err = JwtInvalidTokenTypeError(expected_type="access", actual_type="refresh")
        assert err.code == JwtErrorCode.INVALID_TOKEN_TYPE

    def test_details_store_expected_and_actual_type(self) -> None:
        err = JwtInvalidTokenTypeError(expected_type="access", actual_type="refresh")
        assert err.details["expected_type"] == "access"
        assert err.details["actual_type"] == "refresh"

    def test_actual_type_can_be_none(self) -> None:
        err = JwtInvalidTokenTypeError(expected_type="refresh", actual_type=None)
        assert err.details["actual_type"] is None

    def test_default_message_used_when_none(self) -> None:
        err = JwtInvalidTokenTypeError(expected_type="access", actual_type="refresh")
        assert err.message

    def test_custom_message(self) -> None:
        err = JwtInvalidTokenTypeError(
            expected_type="access",
            actual_type="refresh",
            message="wrong type",
        )
        assert err.message == "wrong type"
