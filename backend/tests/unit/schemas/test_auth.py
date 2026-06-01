"""Модульные тесты схем аутентификации."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas.auth import (
    AuthSessionRead,
    LoginRequest,
    PasswordChangeRequest,
    TokenPair,
)


class TestLoginRequest:
    """Тесты запроса входа в систему."""

    def test_valid(self):
        r = LoginRequest(email_or_username="user@example.com", password="secret123")
        assert r.email_or_username == "user@example.com"
        assert r.password == "secret123"

    def test_username_allowed(self):
        r = LoginRequest(email_or_username="ivan.petrov", password="pass")
        assert r.email_or_username == "ivan.petrov"

    def test_email_or_username_strips_whitespace(self):
        r = LoginRequest(email_or_username="  user@example.com  ", password="pass")
        assert r.email_or_username == "user@example.com"

    def test_email_or_username_empty_after_strip_raises(self):
        with pytest.raises(ValidationError):
            LoginRequest(email_or_username="   ", password="pass")

    def test_email_or_username_missing_raises(self):
        with pytest.raises(ValidationError):
            LoginRequest(password="pass")

    def test_password_missing_raises(self):
        with pytest.raises(ValidationError):
            LoginRequest(email_or_username="user")

    def test_password_max_length_128(self):
        LoginRequest(email_or_username="user", password="a" * 128)

    def test_password_too_long_raises(self):
        with pytest.raises(ValidationError):
            LoginRequest(email_or_username="user", password="a" * 129)

    def test_email_or_username_max_length(self):
        LoginRequest(email_or_username="a" * 320, password="pass")

    def test_email_or_username_too_long_raises(self):
        with pytest.raises(ValidationError):
            LoginRequest(email_or_username="a" * 321, password="pass")

    def test_password_min_length_1(self):
        LoginRequest(email_or_username="user", password="x")

    def test_password_empty_raises(self):
        with pytest.raises(ValidationError):
            LoginRequest(email_or_username="user", password="")


class TestPasswordChangeRequest:
    """Тесты запроса смены пароля."""

    def test_valid(self):
        r = PasswordChangeRequest(current_password="oldpass", new_password="newpass12")
        assert r.current_password == "oldpass"
        assert r.new_password == "newpass12"

    def test_current_password_required(self):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(new_password="newpass12")

    def test_new_password_required(self):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(current_password="oldpass")

    def test_new_password_min_length_8(self):
        PasswordChangeRequest(current_password="old", new_password="12345678")

    def test_new_password_too_short_raises(self):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(current_password="old", new_password="1234567")

    def test_current_password_empty_raises(self):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(current_password="", new_password="newpass12")

    def test_new_password_empty_raises(self):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(current_password="old", new_password="")


class TestAuthSessionRead:
    """Тесты схемы чтения сессии аутентификации."""

    def _make(self, **kwargs):
        now = datetime.now(timezone.utc)
        defaults = {
            "id": uuid4(),
            "user_id": uuid4(),
            "status": "active",
            "expires_at": now,
            "is_active": True,
            "created_at": now,
        }
        defaults.update(kwargs)
        return AuthSessionRead(**defaults)

    def test_valid_minimal(self):
        s = self._make()
        assert s.status == "active"
        assert s.is_active is True

    def test_optional_fields_default_to_none(self):
        s = self._make()
        assert s.revoked_at is None
        assert s.revoke_reason is None
        assert s.ip_address is None
        assert s.user_agent is None
        assert s.device_name is None

    def test_missing_id_raises(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            AuthSessionRead(
                user_id=uuid4(),
                status="active",
                expires_at=now,
                is_active=True,
                created_at=now,
            )

    def test_invalid_uuid_raises(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            AuthSessionRead(
                id="not-a-uuid",
                user_id=uuid4(),
                status="active",
                expires_at=now,
                is_active=True,
                created_at=now,
            )


class TestTokenPair:
    """Тесты пары токенов доступа и обновления."""

    def test_valid(self):
        t = TokenPair(access_token="access.token", refresh_token="refresh.token")
        assert t.token_type == "bearer"
        assert t.access_expires_at is None
        assert t.refresh_expires_at is None

    def test_missing_access_token_raises(self):
        with pytest.raises(ValidationError):
            TokenPair(refresh_token="tok")

    def test_missing_refresh_token_raises(self):
        with pytest.raises(ValidationError):
            TokenPair(access_token="tok")

    def test_empty_access_token_raises(self):
        with pytest.raises(ValidationError):
            TokenPair(access_token="", refresh_token="tok")
