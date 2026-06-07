"""Модульные тесты ORM-модели RefreshToken: проверка состояния токена,
истечения, отзыва и связанных переходов."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from database.models.enums import SessionStatus
from database.models.tokens import RefreshToken


def make_token(**kwargs: object) -> RefreshToken:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash="abc123",
        status=SessionStatus.ACTIVE,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        revoked_at=None,
        revoke_reason=None,
        replaced_by_token_id=None,
        parent_token_id=None,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return RefreshToken(**defaults)


# ---------------------------------------------------------------------------
# can_be_used_at
# ---------------------------------------------------------------------------

class TestCanBeUsedAt:
    def test_active_token_with_future_expiry_returns_true(self) -> None:
        token = make_token(
            status=SessionStatus.ACTIVE,
            is_active=True,
            revoked_at=None,
            replaced_by_token_id=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert token.can_be_used_at(datetime.now(UTC)) is True

    def test_revoked_at_set_returns_false(self) -> None:
        token = make_token(
            revoked_at=datetime.now(UTC),
            is_active=False,
            status=SessionStatus.REVOKED,
        )
        assert token.can_be_used_at(datetime.now(UTC)) is False

    def test_replaced_by_token_id_set_returns_false(self) -> None:
        token = make_token(
            replaced_by_token_id=uuid.uuid4(),
            is_active=False,
            status=SessionStatus.REVOKED,
        )
        assert token.can_be_used_at(datetime.now(UTC)) is False

    def test_is_active_false_returns_false(self) -> None:
        token = make_token(is_active=False, status=SessionStatus.ACTIVE)
        assert token.can_be_used_at(datetime.now(UTC)) is False

    def test_expired_token_returns_false(self) -> None:
        token = make_token(
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        assert token.can_be_used_at(datetime.now(UTC)) is False

    def test_status_not_active_returns_false(self) -> None:
        token = make_token(status=SessionStatus.REVOKED, is_active=False)
        assert token.can_be_used_at(datetime.now(UTC)) is False

    def test_at_exact_expiry_moment_returns_false(self) -> None:
        moment = datetime.now(UTC)
        token = make_token(expires_at=moment)
        # expires_at должно быть строго больше moment
        assert token.can_be_used_at(moment) is False


# ---------------------------------------------------------------------------
# is_expired_at
# ---------------------------------------------------------------------------

class TestIsExpiredAt:
    def test_past_moment_returns_true(self) -> None:
        token = make_token(expires_at=datetime.now(UTC) - timedelta(hours=1))
        assert token.is_expired_at(datetime.now(UTC)) is True

    def test_future_moment_returns_false(self) -> None:
        token = make_token(expires_at=datetime.now(UTC) + timedelta(hours=1))
        assert token.is_expired_at(datetime.now(UTC)) is False

    def test_at_expiry_moment_returns_true(self) -> None:
        moment = datetime.now(UTC)
        token = make_token(expires_at=moment)
        assert token.is_expired_at(moment) is True


# ---------------------------------------------------------------------------
# is_revoked
# ---------------------------------------------------------------------------

class TestIsRevoked:
    def test_revoked_at_set_returns_true(self) -> None:
        token = make_token(revoked_at=datetime.now(UTC))
        assert token.is_revoked is True

    def test_status_revoked_returns_true(self) -> None:
        token = make_token(status=SessionStatus.REVOKED, revoked_at=None, is_active=False)
        assert token.is_revoked is True

    def test_active_token_returns_false(self) -> None:
        token = make_token(
            status=SessionStatus.ACTIVE,
            revoked_at=None,
            is_active=True,
        )
        assert token.is_revoked is False


# ---------------------------------------------------------------------------
# is_replaced
# ---------------------------------------------------------------------------

class TestIsReplaced:
    def test_replaced_by_token_id_set_returns_true(self) -> None:
        token = make_token(replaced_by_token_id=uuid.uuid4())
        assert token.is_replaced is True

    def test_replaced_by_token_id_none_returns_false(self) -> None:
        token = make_token(replaced_by_token_id=None)
        assert token.is_replaced is False


# ---------------------------------------------------------------------------
# revoke()
# ---------------------------------------------------------------------------

class TestRevoke:
    def test_sets_status_to_revoked(self) -> None:
        token = make_token()
        token.revoke()
        assert token.status == SessionStatus.REVOKED

    def test_sets_is_active_false(self) -> None:
        token = make_token()
        token.revoke()
        assert token.is_active is False

    def test_sets_revoked_at_not_none(self) -> None:
        token = make_token()
        token.revoke()
        assert token.revoked_at is not None

    def test_stores_revoke_reason(self) -> None:
        token = make_token()
        token.revoke(reason="logout")
        assert token.revoke_reason == "logout"

    def test_revoke_reason_none_by_default(self) -> None:
        token = make_token()
        token.revoke()
        assert token.revoke_reason is None

    def test_custom_revoked_at_stored(self) -> None:
        moment = datetime(2024, 1, 1, tzinfo=UTC)
        token = make_token()
        token.revoke(revoked_at=moment)
        assert token.revoked_at == moment


# ---------------------------------------------------------------------------
# mark_expired()
# ---------------------------------------------------------------------------

class TestMarkExpired:
    def test_sets_status_to_expired(self) -> None:
        token = make_token()
        token.mark_expired()
        assert token.status == SessionStatus.EXPIRED

    def test_sets_is_active_false(self) -> None:
        token = make_token()
        token.mark_expired()
        assert token.is_active is False


# ---------------------------------------------------------------------------
# deactivate()
# ---------------------------------------------------------------------------

class TestDeactivate:
    def test_sets_is_active_false(self) -> None:
        token = make_token()
        token.deactivate()
        assert token.is_active is False

    def test_status_unchanged(self) -> None:
        token = make_token(status=SessionStatus.ACTIVE)
        token.deactivate()
        # deactivate() только устанавливает is_active=False, но не меняет status
        assert token.status == SessionStatus.ACTIVE


# ---------------------------------------------------------------------------
# is_expired property
# ---------------------------------------------------------------------------

class TestIsExpiredProperty:
    def test_expired_status_returns_true(self) -> None:
        token = make_token(status=SessionStatus.EXPIRED, is_active=False)
        assert token.is_expired is True

    def test_active_status_returns_false(self) -> None:
        token = make_token(status=SessionStatus.ACTIVE)
        assert token.is_expired is False


class TestRefreshTokenRepr:
    def test_repr_non_empty(self) -> None:
        token = make_token()
        result = repr(token)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_repr_contains_class_name(self) -> None:
        token = make_token()
        assert "RefreshToken" in repr(token)
