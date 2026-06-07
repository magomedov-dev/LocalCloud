"""Тесты валидаторов JWT: нормализация subject, типа, времени и проверка claims."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timezone

import pytest

from core.config import SecuritySettings, Settings
from security.jwt.enums import JwtClaimName, JwtErrorCode
from security.jwt.exceptions import JwtInvalidClaimsError, JwtTokenError
from security.jwt.validators import (
    claim_timestamp_to_datetime,
    normalize_datetime,
    normalize_subject,
    normalize_token_type,
    require_claims,
    validate_jwt_settings,
    validate_token_value,
)


class TestNormalizeSubject:
    def test_uuid_converted_to_string(self) -> None:
        uid = uuid.uuid4()
        result = normalize_subject(uid)
        assert result == str(uid)
        assert isinstance(result, str)

    def test_string_subject_returned_stripped(self) -> None:
        result = normalize_subject("  user-123  ")
        assert result == "user-123"

    def test_valid_string_returned_unchanged(self) -> None:
        subject = "some-subject"
        assert normalize_subject(subject) == subject

    def test_empty_string_raises_jwt_token_error(self) -> None:
        with pytest.raises(JwtTokenError) as exc_info:
            normalize_subject("")
        assert exc_info.value.code == JwtErrorCode.MISSING_SUBJECT

    def test_whitespace_only_string_raises_jwt_token_error(self) -> None:
        with pytest.raises(JwtTokenError) as exc_info:
            normalize_subject("   ")
        assert exc_info.value.code == JwtErrorCode.MISSING_SUBJECT

    def test_integer_raises_jwt_token_error(self) -> None:
        with pytest.raises(JwtTokenError) as exc_info:
            normalize_subject(42)  # type: ignore[arg-type]
        assert exc_info.value.code == JwtErrorCode.INVALID_SUBJECT

    def test_none_raises_jwt_token_error(self) -> None:
        with pytest.raises(JwtTokenError):
            normalize_subject(None)  # type: ignore[arg-type]


class TestNormalizeTokenType:
    def test_access_is_valid(self) -> None:
        assert normalize_token_type("access") == "access"

    def test_refresh_is_valid(self) -> None:
        assert normalize_token_type("refresh") == "refresh"

    def test_password_reset_is_valid(self) -> None:
        assert normalize_token_type("password_reset") == "password_reset"

    def test_uppercase_access_is_normalized(self) -> None:
        assert normalize_token_type("ACCESS") == "access"

    def test_mixed_case_refresh_is_normalized(self) -> None:
        assert normalize_token_type("Refresh") == "refresh"

    def test_whitespace_is_stripped(self) -> None:
        assert normalize_token_type("  access  ") == "access"

    def test_invalid_type_raises_invalid_claims_error(self) -> None:
        with pytest.raises(JwtInvalidClaimsError):
            normalize_token_type("invalid_type")

    def test_empty_string_raises_invalid_claims_error(self) -> None:
        with pytest.raises(JwtInvalidClaimsError):
            normalize_token_type("")

    def test_integer_raises_invalid_claims_error(self) -> None:
        with pytest.raises(JwtInvalidClaimsError):
            normalize_token_type(1)  # type: ignore[arg-type]

    def test_none_raises_invalid_claims_error(self) -> None:
        with pytest.raises(JwtInvalidClaimsError):
            normalize_token_type(None)  # type: ignore[arg-type]


class TestValidateTokenValue:
    def test_valid_token_returned_stripped(self) -> None:
        token = "  abc.def.ghi  "
        assert validate_token_value(token) == "abc.def.ghi"

    def test_valid_token_returned_unchanged(self) -> None:
        token = "header.payload.signature"
        assert validate_token_value(token) == token

    def test_empty_string_raises_jwt_token_error(self) -> None:
        with pytest.raises(JwtTokenError) as exc_info:
            validate_token_value("")
        assert exc_info.value.code == JwtErrorCode.INVALID_TOKEN

    def test_whitespace_only_raises_jwt_token_error(self) -> None:
        with pytest.raises(JwtTokenError):
            validate_token_value("   ")

    def test_integer_raises_jwt_token_error(self) -> None:
        with pytest.raises(JwtTokenError):
            validate_token_value(123)  # type: ignore[arg-type]

    def test_none_raises_jwt_token_error(self) -> None:
        with pytest.raises(JwtTokenError):
            validate_token_value(None)  # type: ignore[arg-type]

    def test_list_raises_jwt_token_error(self) -> None:
        with pytest.raises(JwtTokenError):
            validate_token_value(["token"])  # type: ignore[arg-type]


class TestValidateJwtSettings:
    def _make_settings(self, **overrides: object) -> Settings:
        defaults = dict(
            SECRET_KEY="valid-secret-key-at-least-sixteen-chars",
            JWT_ALGORITHM="HS256",
            JWT_ISSUER="issuer",
            JWT_AUDIENCE="audience",
            ACCESS_TOKEN_EXPIRE_MINUTES=15,
            REFRESH_TOKEN_EXPIRE_DAYS=7,
        )
        defaults.update(overrides)
        security = SecuritySettings(**defaults)  # type: ignore[arg-type]
        return Settings(security=security)

    def test_valid_settings_do_not_raise(self) -> None:
        settings = self._make_settings()
        validate_jwt_settings(settings)  # без исключения

    def test_short_secret_key_raises_jwt_token_error(self) -> None:
        settings = self._make_settings(SECRET_KEY="short")
        with pytest.raises(JwtTokenError) as exc_info:
            validate_jwt_settings(settings)
        assert exc_info.value.code == JwtErrorCode.INVALID_SETTINGS

    def test_secret_key_exactly_16_chars_is_valid(self) -> None:
        settings = self._make_settings(SECRET_KEY="1234567890123456")
        validate_jwt_settings(settings)  # без исключения

    def test_secret_key_15_chars_raises(self) -> None:
        settings = self._make_settings(SECRET_KEY="123456789012345")
        with pytest.raises(JwtTokenError):
            validate_jwt_settings(settings)

    def test_zero_access_expire_raises(self) -> None:
        settings = self._make_settings(ACCESS_TOKEN_EXPIRE_MINUTES=0)
        with pytest.raises(JwtTokenError) as exc_info:
            validate_jwt_settings(settings)
        assert exc_info.value.code == JwtErrorCode.INVALID_SETTINGS

    def test_negative_access_expire_raises(self) -> None:
        settings = self._make_settings(ACCESS_TOKEN_EXPIRE_MINUTES=-1)
        with pytest.raises(JwtTokenError):
            validate_jwt_settings(settings)

    def test_zero_refresh_expire_raises(self) -> None:
        settings = self._make_settings(REFRESH_TOKEN_EXPIRE_DAYS=0)
        with pytest.raises(JwtTokenError) as exc_info:
            validate_jwt_settings(settings)
        assert exc_info.value.code == JwtErrorCode.INVALID_SETTINGS

    def test_empty_algorithm_raises(self) -> None:
        settings = self._make_settings(JWT_ALGORITHM="  ")
        with pytest.raises(JwtTokenError):
            validate_jwt_settings(settings)

    def test_empty_issuer_raises(self) -> None:
        settings = self._make_settings(JWT_ISSUER="  ")
        with pytest.raises(JwtTokenError):
            validate_jwt_settings(settings)

    def test_empty_audience_raises(self) -> None:
        settings = self._make_settings(JWT_AUDIENCE="  ")
        with pytest.raises(JwtTokenError):
            validate_jwt_settings(settings)


class TestNormalizeDatetime:
    def test_naive_datetime_gets_utc_tzinfo(self) -> None:
        naive = datetime(2024, 1, 1, 12, 0, 0)
        result = normalize_datetime(naive)
        assert result.tzinfo is not None
        assert result.tzinfo == UTC

    def test_utc_aware_datetime_returned_as_utc(self) -> None:
        aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = normalize_datetime(aware)
        assert result.tzinfo == UTC
        assert result.hour == 12

    def test_non_utc_timezone_converted_to_utc(self) -> None:
        from datetime import timedelta
        plus2 = timezone(timedelta(hours=2))
        dt = datetime(2024, 1, 1, 14, 0, 0, tzinfo=plus2)
        result = normalize_datetime(dt)
        assert result.tzinfo == UTC
        assert result.hour == 12  # 14:00+02:00 == 12:00 UTC


class TestClaimTimestampToDatetime:
    def test_integer_timestamp_converted(self) -> None:
        ts = 1_700_000_000
        result = claim_timestamp_to_datetime(ts, claim_name="exp")
        assert isinstance(result, datetime)
        assert result.tzinfo == UTC

    def test_float_timestamp_converted(self) -> None:
        ts = 1_700_000_000.5
        result = claim_timestamp_to_datetime(ts, claim_name="exp")
        assert isinstance(result, datetime)
        assert result.tzinfo == UTC

    def test_datetime_object_normalized(self) -> None:
        dt = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
        result = claim_timestamp_to_datetime(dt, claim_name="iat")
        assert result == dt

    def test_naive_datetime_gets_utc(self) -> None:
        naive = datetime(2024, 6, 1, 10, 0, 0)
        result = claim_timestamp_to_datetime(naive, claim_name="nbf")
        assert result.tzinfo == UTC

    def test_string_raises_invalid_claims_error(self) -> None:
        with pytest.raises(JwtInvalidClaimsError):
            claim_timestamp_to_datetime("2024-01-01", claim_name="exp")

    def test_none_raises_invalid_claims_error(self) -> None:
        with pytest.raises(JwtInvalidClaimsError):
            claim_timestamp_to_datetime(None, claim_name="exp")

    def test_bool_raises_invalid_claims_error(self) -> None:
        with pytest.raises(JwtInvalidClaimsError):
            claim_timestamp_to_datetime(True, claim_name="exp")


class TestRequireClaims:
    def _all_claims(self) -> dict:
        now = datetime.now(UTC)
        return {
            JwtClaimName.SUBJECT.value: "user-id",
            JwtClaimName.JWT_ID.value: "jti-value",
            JwtClaimName.ISSUED_AT.value: now,
            JwtClaimName.NOT_BEFORE.value: now,
            JwtClaimName.EXPIRES_AT.value: now,
            JwtClaimName.ISSUER.value: "issuer",
            JwtClaimName.AUDIENCE.value: "audience",
        }

    def test_all_claims_present_no_error(self) -> None:
        require_claims(self._all_claims())  # без исключения

    def test_missing_subject_raises(self) -> None:
        claims = self._all_claims()
        del claims[JwtClaimName.SUBJECT.value]
        with pytest.raises(JwtInvalidClaimsError):
            require_claims(claims)

    def test_missing_jti_raises(self) -> None:
        claims = self._all_claims()
        del claims[JwtClaimName.JWT_ID.value]
        with pytest.raises(JwtInvalidClaimsError):
            require_claims(claims)

    def test_missing_iat_raises(self) -> None:
        claims = self._all_claims()
        del claims[JwtClaimName.ISSUED_AT.value]
        with pytest.raises(JwtInvalidClaimsError):
            require_claims(claims)

    def test_missing_exp_raises(self) -> None:
        claims = self._all_claims()
        del claims[JwtClaimName.EXPIRES_AT.value]
        with pytest.raises(JwtInvalidClaimsError):
            require_claims(claims)

    def test_missing_multiple_claims_raises_with_details(self) -> None:
        claims = self._all_claims()
        del claims[JwtClaimName.SUBJECT.value]
        del claims[JwtClaimName.JWT_ID.value]
        with pytest.raises(JwtInvalidClaimsError) as exc_info:
            require_claims(claims)
        assert "missing_claims" in exc_info.value.details
        assert len(exc_info.value.details["missing_claims"]) == 2

    def test_extra_claims_allowed(self) -> None:
        claims = self._all_claims()
        claims["custom_claim"] = "value"
        require_claims(claims)  # без исключения
