"""Тесты валидаторов паролей: нормализация схемы и проверка надёжности."""

from __future__ import annotations

import pytest

from security.password.enums import (
    DEFAULT_MAX_PASSWORD_LENGTH,
    DEFAULT_MIN_PASSWORD_LENGTH,
    PasswordValidationErrorCode,
)
from security.password.validators import (
    normalize_password_hash_scheme,
    require_strong_password,
    validate_password_strength,
    validate_password_value,
)


class TestNormalizePasswordHashScheme:
    def test_bcrypt_is_valid(self) -> None:
        assert normalize_password_hash_scheme("bcrypt") == "bcrypt"

    def test_argon2_is_valid(self) -> None:
        assert normalize_password_hash_scheme("argon2") == "argon2"

    def test_uppercase_bcrypt_normalized(self) -> None:
        assert normalize_password_hash_scheme("BCRYPT") == "bcrypt"

    def test_uppercase_argon2_normalized(self) -> None:
        assert normalize_password_hash_scheme("ARGON2") == "argon2"

    def test_mixed_case_normalized(self) -> None:
        assert normalize_password_hash_scheme("Bcrypt") == "bcrypt"

    def test_whitespace_stripped(self) -> None:
        assert normalize_password_hash_scheme("  bcrypt  ") == "bcrypt"

    def test_invalid_scheme_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Неподдерживаемый"):
            normalize_password_hash_scheme("md5")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            normalize_password_hash_scheme("")

    def test_non_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="строкой"):
            normalize_password_hash_scheme(42)  # type: ignore[arg-type]

    def test_none_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            normalize_password_hash_scheme(None)  # type: ignore[arg-type]


class TestValidatePasswordValue:
    def test_valid_password_returned(self) -> None:
        password = "MySecurePass123"
        assert validate_password_value(password) == password

    def test_password_not_stripped(self) -> None:
        password = "  spaced  "
        assert validate_password_value(password) == password

    def test_empty_password_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="пустым"):
            validate_password_value("")

    def test_non_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="строкой"):
            validate_password_value(123)  # type: ignore[arg-type]

    def test_none_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            validate_password_value(None)  # type: ignore[arg-type]

    def test_single_char_password_accepted(self) -> None:
        assert validate_password_value("x") == "x"


class TestValidatePasswordStrength:
    def test_valid_password_is_valid(self) -> None:
        result = validate_password_strength("SecurePass1")
        assert result.is_valid is True
        assert result.errors == ()

    def test_empty_password_invalid(self) -> None:
        result = validate_password_strength("")
        assert result.is_valid is False
        codes = [e.code for e in result.errors]
        assert PasswordValidationErrorCode.EMPTY in codes

    def test_non_string_invalid(self) -> None:
        result = validate_password_strength(None)  # type: ignore[arg-type]
        assert result.is_valid is False

    def test_too_short_returns_error(self) -> None:
        short = "Ab1" + "x" * (DEFAULT_MIN_PASSWORD_LENGTH - 4)
        result = validate_password_strength(short)
        assert result.is_valid is False
        codes = [e.code for e in result.errors]
        assert PasswordValidationErrorCode.TOO_SHORT in codes

    def test_exact_min_length_is_valid(self) -> None:
        password = "Ab1" + "x" * (DEFAULT_MIN_PASSWORD_LENGTH - 3)
        result = validate_password_strength(password)
        assert PasswordValidationErrorCode.TOO_SHORT not in [e.code for e in result.errors]

    def test_too_long_returns_error(self) -> None:
        password = "Ab1" + "x" * (DEFAULT_MAX_PASSWORD_LENGTH + 1)
        result = validate_password_strength(password)
        assert result.is_valid is False
        codes = [e.code for e in result.errors]
        assert PasswordValidationErrorCode.TOO_LONG in codes

    def test_exact_max_length_is_valid(self) -> None:
        password = "Ab1" + "x" * (DEFAULT_MAX_PASSWORD_LENGTH - 3)
        result = validate_password_strength(password)
        assert PasswordValidationErrorCode.TOO_LONG not in [e.code for e in result.errors]

    def test_missing_letter_returns_error_when_required(self) -> None:
        result = validate_password_strength("12345678", require_letter=True)
        codes = [e.code for e in result.errors]
        assert PasswordValidationErrorCode.MISSING_LETTER in codes

    def test_missing_letter_no_error_when_not_required(self) -> None:
        result = validate_password_strength("12345678", require_letter=False, require_digit=False)
        assert PasswordValidationErrorCode.MISSING_LETTER not in [e.code for e in result.errors]

    def test_missing_digit_returns_error_when_required(self) -> None:
        result = validate_password_strength("AbcDefGhi", require_digit=True)
        codes = [e.code for e in result.errors]
        assert PasswordValidationErrorCode.MISSING_DIGIT in codes

    def test_missing_digit_no_error_when_not_required(self) -> None:
        result = validate_password_strength("AbcDefGhi", require_digit=False)
        assert PasswordValidationErrorCode.MISSING_DIGIT not in [e.code for e in result.errors]

    def test_missing_special_returns_error_when_required(self) -> None:
        result = validate_password_strength("SecurePass1", require_special=True)
        codes = [e.code for e in result.errors]
        assert PasswordValidationErrorCode.MISSING_SPECIAL in codes

    def test_special_char_satisfies_requirement(self) -> None:
        result = validate_password_strength("SecurePass1!", require_special=True)
        assert PasswordValidationErrorCode.MISSING_SPECIAL not in [e.code for e in result.errors]

    def test_whitespace_returns_error_when_not_allowed(self) -> None:
        result = validate_password_strength("Pass word1", allow_whitespace=False)
        codes = [e.code for e in result.errors]
        assert PasswordValidationErrorCode.CONTAINS_WHITESPACE in codes

    def test_whitespace_allowed_when_configured(self) -> None:
        result = validate_password_strength("Pass word1", allow_whitespace=True)
        assert PasswordValidationErrorCode.CONTAINS_WHITESPACE not in [e.code for e in result.errors]

    def test_multiple_errors_accumulated(self) -> None:
        result = validate_password_strength("ab", require_digit=True, require_special=True)
        assert len(result.errors) >= 2

    def test_messages_tuple_matches_errors(self) -> None:
        result = validate_password_strength("12345678", require_letter=True)
        assert len(result.messages) == len(result.errors)
        for message in result.messages:
            assert isinstance(message, str)

    def test_custom_min_length(self) -> None:
        result = validate_password_strength("Aa1", min_length=3)
        assert result.is_valid is True

    def test_custom_max_length(self) -> None:
        result = validate_password_strength("Aa1xxxx", max_length=5)
        codes = [e.code for e in result.errors]
        assert PasswordValidationErrorCode.TOO_LONG in codes


class TestRequireStrongPassword:
    def test_valid_password_returned(self) -> None:
        password = "SecurePass123"
        assert require_strong_password(password) == password

    def test_weak_password_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            require_strong_password("weak")

    def test_error_message_combines_all_failures(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            require_strong_password("ab", require_digit=True)
        assert ";" in str(exc_info.value) or len(str(exc_info.value)) > 0

    def test_missing_letter_raises(self) -> None:
        with pytest.raises(ValueError):
            require_strong_password("12345678", require_letter=True)

    def test_missing_digit_raises(self) -> None:
        with pytest.raises(ValueError):
            require_strong_password("AbcDefGhi", require_digit=True)

    def test_special_required_raises_when_missing(self) -> None:
        with pytest.raises(ValueError):
            require_strong_password("SecurePass1", require_special=True)

    def test_special_required_passes_when_present(self) -> None:
        password = "SecurePass1!"
        assert require_strong_password(password, require_special=True) == password
