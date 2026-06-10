"""Модульные тесты схем заявок на регистрацию."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from database.models.enums import RegistrationRequestStatus
from schemas.registration import (
    RegistrationApproveRequest,
    RegistrationCancelRequest,
    RegistrationQueryParams,
    RegistrationRejectRequest,
    RegistrationRequestCreate,
)


class TestRegistrationRequestCreate:
    """Тесты схемы создания заявки на регистрацию."""

    def test_valid(self):
        r = RegistrationRequestCreate(
            email="user@example.com",
            username="ivan_petrov",
            password="securepassword",
        )
        assert r.username == "ivan_petrov"

    def test_email_required(self):
        with pytest.raises(ValidationError):
            RegistrationRequestCreate(username="user123", password="password123")

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError):
            RegistrationRequestCreate(
                email="not-email",
                username="user123",
                password="password123",
            )

    def test_username_required(self):
        with pytest.raises(ValidationError):
            RegistrationRequestCreate(email="u@e.com", password="password123")

    def test_username_too_short_raises(self):
        with pytest.raises(ValidationError):
            RegistrationRequestCreate(email="u@e.com", username="ab", password="password123")

    def test_username_min_length_3(self):
        r = RegistrationRequestCreate(
            email="u@e.com", username="abc", password="password123"
        )
        assert r.username == "abc"

    def test_username_too_long_raises(self):
        with pytest.raises(ValidationError):
            RegistrationRequestCreate(
                email="u@e.com", username="a" * 65, password="password123"
            )

    def test_username_invalid_chars_raises(self):
        with pytest.raises(ValidationError):
            RegistrationRequestCreate(
                email="u@e.com", username="bad user!", password="password123"
            )

    def test_username_valid_special_chars(self):
        r = RegistrationRequestCreate(
            email="u@e.com",
            username="user.name-1_ok",
            password="password123",
        )
        assert r.username == "user.name-1_ok"

    def test_username_strips_whitespace(self):
        r = RegistrationRequestCreate(
            email="u@e.com", username="  user123  ", password="password123"
        )
        assert r.username == "user123"

    def test_password_min_length_8(self):
        RegistrationRequestCreate(
            email="u@e.com", username="user123", password="12345678"
        )

    def test_password_too_short_raises(self):
        with pytest.raises(ValidationError):
            RegistrationRequestCreate(
                email="u@e.com", username="user123", password="1234567"
            )

    def test_password_max_length_128(self):
        RegistrationRequestCreate(
            email="u@e.com", username="user123", password="a" * 128
        )

    def test_password_too_long_raises(self):
        with pytest.raises(ValidationError):
            RegistrationRequestCreate(
                email="u@e.com", username="user123", password="a" * 129
            )


class TestRegistrationApproveRequest:
    """Тесты запроса одобрения заявки на регистрацию."""

    def test_defaults(self):
        r = RegistrationApproveRequest()
        assert r.comment is None

    def test_comment_normalization(self):
        r = RegistrationApproveRequest(comment="  approved  ")
        assert r.comment == "approved"

    def test_whitespace_comment_becomes_none(self):
        r = RegistrationApproveRequest(comment="   ")
        assert r.comment is None

    def test_comment_too_long_raises(self):
        with pytest.raises(ValidationError):
            RegistrationApproveRequest(comment="a" * 513)


class TestRegistrationRejectRequest:
    """Тесты запроса отклонения заявки на регистрацию."""

    def test_valid(self):
        r = RegistrationRejectRequest(rejection_reason="fake account")
        assert r.rejection_reason == "fake account"

    def test_rejection_reason_required(self):
        with pytest.raises(ValidationError):
            RegistrationRejectRequest()

    def test_empty_rejection_reason_raises(self):
        with pytest.raises(ValidationError):
            RegistrationRejectRequest(rejection_reason="")

    def test_whitespace_rejection_reason_raises(self):
        with pytest.raises(ValidationError):
            RegistrationRejectRequest(rejection_reason="   ")

    def test_rejection_reason_strips_whitespace(self):
        r = RegistrationRejectRequest(rejection_reason="  bad actor  ")
        assert r.rejection_reason == "bad actor"

    def test_rejection_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            RegistrationRejectRequest(rejection_reason="a" * 513)

    def test_optional_comment(self):
        r = RegistrationRejectRequest(rejection_reason="reason", comment="note")
        assert r.comment == "note"

    def test_whitespace_comment_becomes_none(self):
        r = RegistrationRejectRequest(rejection_reason="reason", comment="   ")
        assert r.comment is None


class TestRegistrationCancelRequest:
    """Тесты запроса отмены заявки на регистрацию."""

    def test_no_reason(self):
        r = RegistrationCancelRequest()
        assert r.reason is None

    def test_reason_normalization(self):
        r = RegistrationCancelRequest(reason="  changed mind  ")
        assert r.reason == "changed mind"

    def test_whitespace_reason_becomes_none(self):
        r = RegistrationCancelRequest(reason="   ")
        assert r.reason is None

    def test_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            RegistrationCancelRequest(reason="a" * 513)


class TestRegistrationQueryParams:
    """Тесты параметров запроса списка заявок на регистрацию."""

    def test_defaults(self):
        q = RegistrationQueryParams()
        assert q.query is None
        assert q.status is None
        assert q.sort_by == "created_at"
        assert q.sort_desc is True

    def test_query_normalization(self):
        q = RegistrationQueryParams(query="  john  ")
        assert q.query == "john"

    def test_whitespace_query_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RegistrationQueryParams(query="   ")

    def test_status_filter(self):
        q = RegistrationQueryParams(status=RegistrationRequestStatus.PENDING)
        assert q.status == RegistrationRequestStatus.PENDING

    def test_created_to_before_from_raises(self):
        d1 = datetime(2024, 1, 10, tzinfo=timezone.utc)
        d2 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            RegistrationQueryParams(created_from=d1, created_to=d2)

    def test_reviewed_to_before_from_raises(self):
        d1 = datetime(2024, 1, 10, tzinfo=timezone.utc)
        d2 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            RegistrationQueryParams(reviewed_from=d1, reviewed_to=d2)


class TestRegistrationNoneBranches:
    """Тесты ветвей с явной передачей None в схемах регистрации."""

    def test_approve_comment_none(self):
        r = RegistrationApproveRequest(comment=None)
        assert r.comment is None

    def test_reject_comment_none(self):
        r = RegistrationRejectRequest(rejection_reason="spam", comment=None)
        assert r.comment is None

    def test_cancel_reason_none(self):
        r = RegistrationCancelRequest(reason=None)
        assert r.reason is None

    def test_query_params_query_none(self):
        q = RegistrationQueryParams(query=None)
        assert q.query is None

    def test_query_params_valid_ranges(self):
        d_from = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d_to = datetime(2024, 1, 10, tzinfo=timezone.utc)
        q = RegistrationQueryParams(
            created_from=d_from,
            created_to=d_to,
            reviewed_from=d_from,
            reviewed_to=d_to,
        )
        assert q.created_to == d_to
        assert q.reviewed_to == d_to
