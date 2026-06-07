"""Модульные тесты схем пользователей."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import UserStatus
from schemas.users import (
    AdminChangePasswordRequest,
    UserAdminUpdate,
    UserApproveRequest,
    UserBlockRequest,
    UserCreate,
    UserQueryParams,
    UserRejectRequest,
    UserStatusUpdateRequest,
    UserUpdate,
)


class TestUserCreate:
    """Тесты схемы создания пользователя."""

    def test_valid(self):
        u = UserCreate(
            email="user@example.com",
            username="ivan_petrov",
            password="securepass",
        )
        assert u.email == "ivan_petrov@example.com" or u.email == "user@example.com"
        assert u.username == "ivan_petrov"
        assert u.status == UserStatus.PENDING
        assert u.is_email_verified is False

    def test_missing_email_raises(self):
        with pytest.raises(ValidationError):
            UserCreate(username="user", password="securepass")

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError):
            UserCreate(email="not-valid", username="user", password="securepass")

    def test_missing_username_raises(self):
        with pytest.raises(ValidationError):
            UserCreate(email="u@e.com", password="securepass")

    def test_username_too_short_raises(self):
        with pytest.raises(ValidationError):
            UserCreate(email="u@e.com", username="ab", password="securepass")

    def test_username_min_length_3(self):
        u = UserCreate(email="u@e.com", username="abc", password="securepass")
        assert u.username == "abc"

    def test_username_too_long_raises(self):
        with pytest.raises(ValidationError):
            UserCreate(email="u@e.com", username="a" * 65, password="securepass")

    def test_username_invalid_chars_raises(self):
        with pytest.raises(ValidationError):
            UserCreate(email="u@e.com", username="user name!", password="securepass")

    def test_username_valid_chars(self):
        u = UserCreate(email="u@e.com", username="user.name-1_ok", password="securepass")
        assert u.username == "user.name-1_ok"

    def test_password_min_length_8(self):
        UserCreate(email="u@e.com", username="user123", password="12345678")

    def test_password_too_short_raises(self):
        with pytest.raises(ValidationError):
            UserCreate(email="u@e.com", username="user123", password="1234567")

    def test_password_too_long_raises(self):
        with pytest.raises(ValidationError):
            UserCreate(email="u@e.com", username="user123", password="a" * 129)

    def test_status_custom(self):
        u = UserCreate(
            email="u@e.com",
            username="user123",
            password="securepass",
            status=UserStatus.ACTIVE,
        )
        assert u.status == UserStatus.ACTIVE

    def test_username_strips_whitespace(self):
        u = UserCreate(email="u@e.com", username="  user123  ", password="securepass")
        assert u.username == "user123"

    def test_empty_username_after_strip_raises(self):
        with pytest.raises(ValidationError):
            UserCreate(email="u@e.com", username="   ", password="securepass")


class TestUserUpdate:
    """Тесты схемы обновления пользователя."""

    def test_all_optional_by_default(self):
        u = UserUpdate()
        assert u.email is None
        assert u.username is None

    def test_valid_email(self):
        u = UserUpdate(email="new@example.com")
        assert str(u.email) == "new@example.com"

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError):
            UserUpdate(email="not-email")

    def test_valid_username(self):
        u = UserUpdate(username="new_name")
        assert u.username == "new_name"

    def test_username_invalid_chars_raises(self):
        with pytest.raises(ValidationError):
            UserUpdate(username="bad name!")

    def test_username_whitespace_only_raises(self):
        with pytest.raises(ValidationError):
            UserUpdate(username="   ")


class TestUserAdminUpdate:
    """Тесты схемы административного обновления пользователя."""

    def test_valid_with_status(self):
        u = UserAdminUpdate(status=UserStatus.BLOCKED, block_reason="spam")
        assert u.status == UserStatus.BLOCKED

    def test_block_reason_strips_whitespace(self):
        u = UserAdminUpdate(block_reason="  spam  ")
        assert u.block_reason == "spam"

    def test_whitespace_only_reason_becomes_none(self):
        u = UserAdminUpdate(block_reason="   ")
        assert u.block_reason is None

    def test_block_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            UserAdminUpdate(block_reason="a" * 513)


class TestUserBlockRequest:
    """Тесты запроса блокировки пользователя."""

    def test_valid(self):
        r = UserBlockRequest(reason="spamming")
        assert r.reason == "spamming"

    def test_reason_strips_whitespace(self):
        r = UserBlockRequest(reason="  spam  ")
        assert r.reason == "spam"

    def test_empty_reason_raises(self):
        with pytest.raises(ValidationError):
            UserBlockRequest(reason="")

    def test_whitespace_reason_raises(self):
        with pytest.raises(ValidationError):
            UserBlockRequest(reason="   ")

    def test_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            UserBlockRequest(reason="a" * 513)

    def test_missing_reason_raises(self):
        with pytest.raises(ValidationError):
            UserBlockRequest()


class TestUserRejectRequest:
    """Тесты запроса отклонения пользователя."""

    def test_valid(self):
        r = UserRejectRequest(reason="fake account")
        assert r.reason == "fake account"

    def test_empty_reason_raises(self):
        with pytest.raises(ValidationError):
            UserRejectRequest(reason="")

    def test_whitespace_reason_raises(self):
        with pytest.raises(ValidationError):
            UserRejectRequest(reason="  ")


class TestUserStatusUpdateRequest:
    """Тесты запроса обновления статуса пользователя."""

    def test_valid(self):
        r = UserStatusUpdateRequest(status=UserStatus.ACTIVE)
        assert r.status == UserStatus.ACTIVE

    def test_optional_reason(self):
        r = UserStatusUpdateRequest(status=UserStatus.BLOCKED, reason="abuse")
        assert r.reason == "abuse"

    def test_whitespace_reason_becomes_none(self):
        r = UserStatusUpdateRequest(status=UserStatus.ACTIVE, reason="   ")
        assert r.reason is None

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            UserStatusUpdateRequest(status="invalid_status")


class TestUserApproveRequest:
    """Тесты запроса одобрения пользователя."""

    def test_default_is_email_verified_true(self):
        r = UserApproveRequest()
        assert r.is_email_verified is True

    def test_can_set_false(self):
        r = UserApproveRequest(is_email_verified=False)
        assert r.is_email_verified is False


class TestUserQueryParams:
    """Тесты параметров запроса списка пользователей."""

    def test_defaults(self):
        q = UserQueryParams()
        assert q.query is None
        assert q.status is None
        assert q.sort_by == "created_at"
        assert q.sort_desc is True

    def test_query_strips_whitespace(self):
        q = UserQueryParams(query="  john  ")
        assert q.query == "john"

    def test_whitespace_query_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UserQueryParams(query="   ")

    def test_created_to_before_created_from_raises(self):
        from datetime import datetime, timezone
        d1 = datetime(2024, 1, 10, tzinfo=timezone.utc)
        d2 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            UserQueryParams(created_from=d1, created_to=d2)

    def test_valid_date_range(self):
        from datetime import datetime, timezone
        d1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d2 = datetime(2024, 1, 10, tzinfo=timezone.utc)
        q = UserQueryParams(created_from=d1, created_to=d2)
        assert q.created_from == d1
        assert q.created_to == d2


class TestAdminChangePasswordRequest:
    """Тесты запроса смены пароля администратором."""

    def test_valid(self):
        r = AdminChangePasswordRequest(new_password="newpassword")
        assert r.new_password == "newpassword"

    def test_too_short_raises(self):
        with pytest.raises(ValidationError):
            AdminChangePasswordRequest(new_password="1234567")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError):
            AdminChangePasswordRequest(new_password="a" * 129)

    def test_missing_raises(self):
        with pytest.raises(ValidationError):
            AdminChangePasswordRequest()


class TestUserSchemaNoneBranches:
    """Тесты ветвей с явной передачей None в схемах пользователей."""

    def test_user_update_username_none(self):
        u = UserUpdate(username=None)
        assert u.username is None

    def test_user_admin_update_reasons_none(self):
        u = UserAdminUpdate(block_reason=None, rejection_reason=None)
        assert u.block_reason is None
        assert u.rejection_reason is None

    def test_user_admin_update_reasons_whitespace_become_none(self):
        u = UserAdminUpdate(block_reason="   ", rejection_reason="   ")
        assert u.block_reason is None
        assert u.rejection_reason is None

    def test_user_status_update_reason_none(self):
        u = UserStatusUpdateRequest(status=UserStatus.BLOCKED, reason=None)
        assert u.reason is None

    def test_user_status_update_reason_whitespace_none(self):
        u = UserStatusUpdateRequest(status=UserStatus.BLOCKED, reason="   ")
        assert u.reason is None

    def test_user_query_params_query_none(self):
        q = UserQueryParams(query=None)
        assert q.query is None
