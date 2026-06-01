"""Тесты DTO JwtPayload: user_id, тип токена, проверка истечения, неизменяемость."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from security.jwt.dto import JwtPayload
from security.jwt.enums import JwtErrorCode
from security.jwt.exceptions import JwtTokenError


_SENTINEL = object()


def _make_payload(
    subject: object = _SENTINEL,
    token_type: str = "access",
    expires_at: datetime | None = None,
) -> JwtPayload:
    now = datetime.now(UTC)
    return JwtPayload(
        subject=str(uuid.uuid4()) if subject is _SENTINEL else subject,  # type: ignore[arg-type]
        token_type=token_type,  # type: ignore[arg-type]
        jti=uuid.uuid4().hex,
        issued_at=now,
        not_before=now,
        expires_at=expires_at or (now + timedelta(minutes=15)),
        issuer="test",
        audience="test-users",
        claims={},
    )


class TestJwtPayloadUserId:
    def test_valid_uuid_returns_uuid_object(self) -> None:
        user_id = uuid.uuid4()
        payload = _make_payload(subject=str(user_id))
        assert payload.user_id == user_id
        assert isinstance(payload.user_id, uuid.UUID)

    def test_invalid_uuid_raises_jwt_token_error(self) -> None:
        payload = _make_payload(subject="not-a-uuid")
        with pytest.raises(JwtTokenError) as exc_info:
            _ = payload.user_id
        assert exc_info.value.code == JwtErrorCode.INVALID_SUBJECT

    def test_empty_subject_raises_jwt_token_error(self) -> None:
        payload = _make_payload(subject="")
        with pytest.raises(JwtTokenError):
            _ = payload.user_id

    def test_numeric_string_subject_raises_jwt_token_error(self) -> None:
        payload = _make_payload(subject="12345")
        with pytest.raises(JwtTokenError):
            _ = payload.user_id


class TestJwtPayloadTokenTypeProperties:
    def test_is_access_token_true_for_access(self) -> None:
        payload = _make_payload(token_type="access")
        assert payload.is_access_token is True
        assert payload.is_refresh_token is False

    def test_is_refresh_token_true_for_refresh(self) -> None:
        payload = _make_payload(token_type="refresh")
        assert payload.is_refresh_token is True
        assert payload.is_access_token is False


class TestJwtPayloadIsExpiredAt:
    def test_future_token_not_expired(self) -> None:
        payload = _make_payload(expires_at=datetime.now(UTC) + timedelta(hours=1))
        assert payload.is_expired_at() is False

    def test_past_token_is_expired(self) -> None:
        payload = _make_payload(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        assert payload.is_expired_at() is True

    def test_explicit_moment_in_future_not_expired(self) -> None:
        now = datetime.now(UTC)
        payload = _make_payload(expires_at=now + timedelta(hours=1))
        assert payload.is_expired_at(moment=now) is False

    def test_explicit_moment_after_expiry_is_expired(self) -> None:
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        payload = _make_payload(expires_at=expires_at)
        future_moment = expires_at + timedelta(seconds=1)
        assert payload.is_expired_at(moment=future_moment) is True

    def test_expiry_exactly_at_moment_is_considered_expired(self) -> None:
        moment = datetime.now(UTC)
        payload = _make_payload(expires_at=moment)
        assert payload.is_expired_at(moment=moment) is True


class TestJwtPayloadImmutability:
    def test_payload_is_frozen(self) -> None:
        payload = _make_payload()
        with pytest.raises((AttributeError, TypeError)):
            payload.subject = "other"  # type: ignore[misc]
