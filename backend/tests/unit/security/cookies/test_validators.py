"""Тесты валидаторов cookie: имя, значение, max-age, samesite, домен, путь."""

from __future__ import annotations

import pytest

from security.cookies.enums import CookieErrorCode
from security.cookies.exceptions import CookieError
from security.cookies.validators import (
    normalize_cookie_domain,
    normalize_cookie_path,
    normalize_samesite,
    validate_cookie_name,
    validate_cookie_value,
    validate_max_age_seconds,
)


class TestValidateCookieName:
    def test_valid_name_returned_stripped(self) -> None:
        assert validate_cookie_name("  session_id  ") == "session_id"

    def test_plain_valid_name(self) -> None:
        assert validate_cookie_name("access_token") == "access_token"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_name("")
        assert exc_info.value.code == CookieErrorCode.INVALID_COOKIE_NAME

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_name("   ")
        assert exc_info.value.code == CookieErrorCode.INVALID_COOKIE_NAME

    def test_non_string_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_name(123)  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_COOKIE_NAME

    def test_none_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_name(None)  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_COOKIE_NAME

    def test_name_with_internal_spaces_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_name("my cookie")
        assert exc_info.value.code == CookieErrorCode.INVALID_COOKIE_NAME

    def test_name_with_semicolon_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_name("name;value")
        assert exc_info.value.code == CookieErrorCode.INVALID_COOKIE_NAME

    def test_name_with_comma_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_name("a,b")
        assert exc_info.value.code == CookieErrorCode.INVALID_COOKIE_NAME

    def test_name_with_equals_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_name("key=value")
        assert exc_info.value.code == CookieErrorCode.INVALID_COOKIE_NAME

    def test_name_with_tab_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_name("tab\there")
        assert exc_info.value.code == CookieErrorCode.INVALID_COOKIE_NAME


class TestValidateCookieValue:
    def test_valid_value_returned_stripped(self) -> None:
        assert validate_cookie_value("  abc123  ") == "abc123"

    def test_plain_valid_value(self) -> None:
        assert validate_cookie_value("mytoken") == "mytoken"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_value("")
        assert exc_info.value.code == CookieErrorCode.INVALID_TOKEN

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_value("  ")
        assert exc_info.value.code == CookieErrorCode.INVALID_TOKEN

    def test_non_string_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_value(42)  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_TOKEN

    def test_none_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_cookie_value(None)  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_TOKEN


class TestValidateMaxAgeSeconds:
    def test_positive_int_passes(self) -> None:
        assert validate_max_age_seconds(3600) == 3600

    def test_one_second_passes(self) -> None:
        assert validate_max_age_seconds(1) == 1

    def test_zero_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_max_age_seconds(0)
        assert exc_info.value.code == CookieErrorCode.INVALID_MAX_AGE

    def test_negative_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_max_age_seconds(-1)
        assert exc_info.value.code == CookieErrorCode.INVALID_MAX_AGE

    def test_float_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_max_age_seconds(3600.5)  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_MAX_AGE

    def test_bool_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_max_age_seconds(True)  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_MAX_AGE

    def test_non_int_string_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            validate_max_age_seconds("3600")  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_MAX_AGE


class TestNormalizeSamesite:
    def test_lax_valid(self) -> None:
        assert normalize_samesite("lax") == "lax"

    def test_strict_valid(self) -> None:
        assert normalize_samesite("strict") == "strict"

    def test_none_valid(self) -> None:
        assert normalize_samesite("none") == "none"

    def test_case_insensitive_upper(self) -> None:
        assert normalize_samesite("LAX") == "lax"

    def test_case_insensitive_mixed(self) -> None:
        assert normalize_samesite("Strict") == "strict"

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            normalize_samesite("always")
        assert exc_info.value.code == CookieErrorCode.INVALID_SAMESITE

    def test_empty_string_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            normalize_samesite("")
        assert exc_info.value.code == CookieErrorCode.INVALID_SAMESITE

    def test_non_string_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            normalize_samesite(1)  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_SAMESITE


class TestNormalizeCookieDomain:
    def test_none_returns_none(self) -> None:
        assert normalize_cookie_domain(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_cookie_domain("") is None

    def test_whitespace_returns_none(self) -> None:
        assert normalize_cookie_domain("   ") is None

    def test_valid_string_returned(self) -> None:
        assert normalize_cookie_domain("example.com") == "example.com"

    def test_strips_whitespace(self) -> None:
        assert normalize_cookie_domain("  example.com  ") == "example.com"

    def test_non_string_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            normalize_cookie_domain(123)  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_SETTINGS


class TestNormalizeCookiePath:
    def test_valid_path_with_slash_returned(self) -> None:
        assert normalize_cookie_path("/api") == "/api"

    def test_adds_leading_slash_if_missing(self) -> None:
        assert normalize_cookie_path("api") == "/api"

    def test_root_path_accepted(self) -> None:
        assert normalize_cookie_path("/") == "/"

    def test_strips_whitespace_before_slash_check(self) -> None:
        result = normalize_cookie_path("  /auth  ")
        assert result == "/auth"

    def test_empty_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            normalize_cookie_path("")
        assert exc_info.value.code == CookieErrorCode.INVALID_SETTINGS

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            normalize_cookie_path("  ")
        assert exc_info.value.code == CookieErrorCode.INVALID_SETTINGS

    def test_non_string_raises(self) -> None:
        with pytest.raises(CookieError) as exc_info:
            normalize_cookie_path(42)  # type: ignore[arg-type]
        assert exc_info.value.code == CookieErrorCode.INVALID_SETTINGS
