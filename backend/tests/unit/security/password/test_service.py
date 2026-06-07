"""Тесты сервиса паролей: хеширование, проверка и необходимость перехеширования."""

from __future__ import annotations

import pytest

from core.config import Settings
from security.password.enums import (
    SUPPORTED_PASSWORD_HASH_SCHEMES,
    PasswordHashScheme,
)
from security.password.service import (
    build_password_context,
    get_password_hash_scheme_from_settings,
    hash_password,
    password_needs_rehash,
    verify_and_update_password_hash,
    verify_password,
)


class TestBuildPasswordContext:
    def test_bcrypt_context_created(self) -> None:
        ctx = build_password_context("bcrypt")
        assert ctx is not None

    def test_argon2_context_created(self) -> None:
        ctx = build_password_context("argon2")
        assert ctx is not None

    def test_unsupported_scheme_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            build_password_context("md5")

    def test_bcrypt_context_can_hash_and_verify(self) -> None:
        ctx = build_password_context("bcrypt")
        hashed = ctx.hash("test_password")
        assert ctx.verify("test_password", hashed)


class TestHashPassword:
    def test_returns_non_empty_string(self) -> None:
        hashed = hash_password("MyPassword123")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_bcrypt_hash_starts_with_prefix(self) -> None:
        hashed = hash_password("MyPassword123", scheme="bcrypt")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_same_password_produces_different_hashes(self) -> None:
        h1 = hash_password("SamePassword1", scheme="bcrypt")
        h2 = hash_password("SamePassword1", scheme="bcrypt")
        assert h1 != h2  # bcrypt использует соль

    def test_empty_password_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            hash_password("")

    def test_non_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            hash_password(None)  # type: ignore[arg-type]

    def test_explicit_bcrypt_scheme(self) -> None:
        hashed = hash_password("Password1", scheme="bcrypt")
        assert hashed

    def test_hash_is_verifiable(self) -> None:
        password = "VerifyMe123"
        hashed = hash_password(password, scheme="bcrypt")
        assert verify_password(password, hashed, scheme="bcrypt")


class TestVerifyPassword:
    def test_correct_password_returns_true(self) -> None:
        password = "CorrectPass1"
        hashed = hash_password(password, scheme="bcrypt")
        assert verify_password(password, hashed, scheme="bcrypt") is True

    def test_wrong_password_returns_false(self) -> None:
        hashed = hash_password("CorrectPass1", scheme="bcrypt")
        assert verify_password("WrongPass1", hashed, scheme="bcrypt") is False

    def test_none_hash_returns_false(self) -> None:
        assert verify_password("SomePass1", None) is False  # type: ignore[arg-type]

    def test_empty_hash_returns_false(self) -> None:
        assert verify_password("SomePass1", "") is False

    def test_whitespace_hash_returns_false(self) -> None:
        assert verify_password("SomePass1", "   ") is False

    def test_non_string_password_returns_false(self) -> None:
        hashed = hash_password("SomePass1", scheme="bcrypt")
        assert verify_password(None, hashed) is False  # type: ignore[arg-type]

    def test_invalid_hash_format_returns_false(self) -> None:
        assert verify_password("SomePass1", "not-a-valid-hash") is False

    def test_case_sensitive_verification(self) -> None:
        hashed = hash_password("CaseSensitive1", scheme="bcrypt")
        assert verify_password("casesensitive1", hashed, scheme="bcrypt") is False

    def test_empty_password_returns_false(self) -> None:
        hashed = hash_password("ValidPass1", scheme="bcrypt")
        assert verify_password("", hashed) is False


class TestPasswordNeedsRehash:
    def test_none_hash_needs_rehash(self) -> None:
        assert password_needs_rehash(None) is True

    def test_empty_hash_needs_rehash(self) -> None:
        assert password_needs_rehash("") is True

    def test_whitespace_hash_needs_rehash(self) -> None:
        assert password_needs_rehash("   ") is True

    def test_invalid_hash_needs_rehash(self) -> None:
        assert password_needs_rehash("not-a-valid-hash") is True

    def test_valid_current_scheme_hash_does_not_need_rehash(self) -> None:
        hashed = hash_password("TestPass1", scheme="bcrypt")
        assert password_needs_rehash(hashed, scheme="bcrypt") is False


class TestVerifyAndUpdatePasswordHash:
    def test_correct_password_no_rehash_needed_returns_true_none(self) -> None:
        password = "GoodPass1"
        hashed = hash_password(password, scheme="bcrypt")
        is_valid, new_hash = verify_and_update_password_hash(password, hashed, scheme="bcrypt")
        assert is_valid is True
        assert new_hash is None

    def test_incorrect_password_returns_false_none(self) -> None:
        hashed = hash_password("GoodPass1", scheme="bcrypt")
        is_valid, new_hash = verify_and_update_password_hash("WrongPass1", hashed, scheme="bcrypt")
        assert is_valid is False
        assert new_hash is None

    def test_none_hash_returns_false_none(self) -> None:
        is_valid, new_hash = verify_and_update_password_hash("SomePass1", None)
        assert is_valid is False
        assert new_hash is None

    def test_correct_password_with_invalid_hash_returns_false_none(self) -> None:
        is_valid, new_hash = verify_and_update_password_hash("SomePass1", "bad-hash")
        assert is_valid is False
        assert new_hash is None

    def test_new_hash_is_verifiable_when_returned(self) -> None:
        password = "TestPass1"
        # используем хеш argon2, но проверяем по схеме bcrypt, чтобы вызвать перехеширование;
        # это имитирует хеш пароля из другой (устаревшей) схемы
        argon2_hash = build_password_context("argon2").hash(password)
        is_valid, new_hash = verify_and_update_password_hash(password, argon2_hash, scheme="bcrypt")
        assert is_valid is True
        if new_hash is not None:
            # новый хеш также должен проверять исходный пароль
            assert verify_password(password, new_hash, scheme="bcrypt") is True


class TestGetPasswordHashSchemeFromSettings:
    def test_returns_scheme_from_explicit_settings(
        self, test_settings: Settings
    ) -> None:
        scheme = get_password_hash_scheme_from_settings(test_settings)
        assert scheme == "bcrypt"

    def test_returns_normalized_scheme_enum(self, test_settings: Settings) -> None:
        # PasswordHashScheme — это алиас Literal, поэтому значение является обычной строкой
        scheme = get_password_hash_scheme_from_settings(test_settings)
        assert scheme in SUPPORTED_PASSWORD_HASH_SCHEMES
