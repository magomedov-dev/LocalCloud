"""Модульные тесты ORM-модели User.

Тесты проверяют свойства уровня Python и методы смены состояния через
``model_construct``, поэтому сессия БД не требуется.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


from database.models.enums import SystemRole, UserStatus
from database.models.roles import Role
from database.models.users import User


def make_role(code: str, *, is_active: bool = True) -> Role:
    return Role(
        id=uuid.uuid4(),
        code=code,
        name=code,
        description=None,
        is_active=is_active,
        is_system=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(**kwargs: object) -> User:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        email="user@example.com",
        username="testuser",
        password_hash="hashed_pw",
        status=UserStatus.ACTIVE,
        last_login_at=None,
        approved_at=None,
        blocked_at=None,
        rejected_at=None,
        deleted_at=None,
        block_reason=None,
        rejection_reason=None,
        roles=[],
    )
    defaults.update(kwargs)
    return User(**defaults)


# ---------------------------------------------------------------------------
# is_active
# ---------------------------------------------------------------------------

class TestIsActive:
    def test_active_status_returns_true(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        assert user.is_active is True

    def test_pending_status_returns_false(self) -> None:
        user = make_user(status=UserStatus.PENDING)
        assert user.is_active is False

    def test_blocked_status_returns_false(self) -> None:
        user = make_user(status=UserStatus.BLOCKED)
        assert user.is_active is False

    def test_rejected_status_returns_false(self) -> None:
        user = make_user(status=UserStatus.REJECTED)
        assert user.is_active is False

    def test_deleted_status_returns_false(self) -> None:
        user = make_user(status=UserStatus.DELETED)
        assert user.is_active is False


# ---------------------------------------------------------------------------
# is_blocked
# ---------------------------------------------------------------------------

class TestIsBlocked:
    def test_blocked_status_returns_true(self) -> None:
        user = make_user(status=UserStatus.BLOCKED)
        assert user.is_blocked is True

    def test_active_status_returns_false(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        assert user.is_blocked is False

    def test_pending_status_returns_false(self) -> None:
        user = make_user(status=UserStatus.PENDING)
        assert user.is_blocked is False


# ---------------------------------------------------------------------------
# is_pending
# ---------------------------------------------------------------------------

class TestIsPending:
    def test_pending_status_returns_true(self) -> None:
        user = make_user(status=UserStatus.PENDING)
        assert user.is_pending is True

    def test_active_status_returns_false(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        assert user.is_pending is False


# ---------------------------------------------------------------------------
# is_rejected
# ---------------------------------------------------------------------------

class TestIsRejected:
    def test_rejected_status_returns_true(self) -> None:
        user = make_user(status=UserStatus.REJECTED)
        assert user.is_rejected is True

    def test_active_status_returns_false(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        assert user.is_rejected is False


# ---------------------------------------------------------------------------
# is_deleted
# ---------------------------------------------------------------------------

class TestIsDeleted:
    def test_deleted_status_returns_true(self) -> None:
        user = make_user(status=UserStatus.DELETED)
        assert user.is_deleted is True

    def test_active_status_returns_false(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        assert user.is_deleted is False


# ---------------------------------------------------------------------------
# can_login
# ---------------------------------------------------------------------------

class TestCanLogin:
    def test_active_user_can_login(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        assert user.can_login is True

    def test_blocked_user_cannot_login(self) -> None:
        user = make_user(status=UserStatus.BLOCKED)
        assert user.can_login is False

    def test_pending_user_cannot_login(self) -> None:
        user = make_user(status=UserStatus.PENDING)
        assert user.can_login is False

    def test_rejected_user_cannot_login(self) -> None:
        user = make_user(status=UserStatus.REJECTED)
        assert user.can_login is False

    def test_deleted_user_cannot_login(self) -> None:
        user = make_user(status=UserStatus.DELETED)
        assert user.can_login is False


# ---------------------------------------------------------------------------
# approve()
# ---------------------------------------------------------------------------

class TestApprove:
    def test_sets_status_to_active(self) -> None:
        user = make_user(status=UserStatus.PENDING)
        user.approve()
        assert user.status == UserStatus.ACTIVE

    def test_sets_approved_at(self) -> None:
        user = make_user(status=UserStatus.PENDING)
        user.approve()
        assert user.approved_at is not None

    def test_custom_approved_at_is_stored(self) -> None:
        moment = datetime(2024, 6, 1, tzinfo=UTC)
        user = make_user(status=UserStatus.PENDING)
        user.approve(approved_at=moment)
        assert user.approved_at == moment

    def test_clears_rejected_at(self) -> None:
        user = make_user(status=UserStatus.REJECTED, rejected_at=datetime.now(UTC))
        user.approve()
        assert user.rejected_at is None

    def test_clears_rejection_reason(self) -> None:
        user = make_user(status=UserStatus.REJECTED, rejection_reason="bad actor")
        user.approve()
        assert user.rejection_reason is None


# ---------------------------------------------------------------------------
# reject()
# ---------------------------------------------------------------------------

class TestReject:
    def test_sets_status_to_rejected(self) -> None:
        user = make_user(status=UserStatus.PENDING)
        user.reject()
        assert user.status == UserStatus.REJECTED

    def test_sets_rejected_at(self) -> None:
        user = make_user(status=UserStatus.PENDING)
        user.reject()
        assert user.rejected_at is not None

    def test_stores_reason(self) -> None:
        user = make_user(status=UserStatus.PENDING)
        user.reject(reason="spam account")
        assert user.rejection_reason == "spam account"

    def test_custom_rejected_at_is_stored(self) -> None:
        moment = datetime(2024, 3, 15, tzinfo=UTC)
        user = make_user(status=UserStatus.PENDING)
        user.reject(rejected_at=moment)
        assert user.rejected_at == moment


# ---------------------------------------------------------------------------
# block()
# ---------------------------------------------------------------------------

class TestBlock:
    def test_sets_status_to_blocked(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user.block()
        assert user.status == UserStatus.BLOCKED

    def test_sets_blocked_at(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user.block()
        assert user.blocked_at is not None

    def test_stores_reason(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user.block(reason="violated ToS")
        assert user.block_reason == "violated ToS"

    def test_custom_blocked_at_is_stored(self) -> None:
        moment = datetime(2024, 1, 10, tzinfo=UTC)
        user = make_user(status=UserStatus.ACTIVE)
        user.block(blocked_at=moment)
        assert user.blocked_at == moment


# ---------------------------------------------------------------------------
# unblock()
# ---------------------------------------------------------------------------

class TestUnblock:
    def test_sets_status_to_active(self) -> None:
        user = make_user(status=UserStatus.BLOCKED, block_reason="old reason")
        user.unblock()
        assert user.status == UserStatus.ACTIVE

    def test_clears_blocked_at(self) -> None:
        user = make_user(status=UserStatus.BLOCKED, blocked_at=datetime.now(UTC))
        user.unblock()
        assert user.blocked_at is None

    def test_clears_block_reason(self) -> None:
        user = make_user(status=UserStatus.BLOCKED, block_reason="old reason")
        user.unblock()
        assert user.block_reason is None


# ---------------------------------------------------------------------------
# mark_deleted()
# ---------------------------------------------------------------------------

class TestMarkDeleted:
    def test_sets_status_to_deleted(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user.mark_deleted()
        assert user.status == UserStatus.DELETED

    def test_sets_deleted_at(self) -> None:
        user = make_user(status=UserStatus.ACTIVE)
        user.mark_deleted()
        assert user.deleted_at is not None

    def test_custom_deleted_at_is_stored(self) -> None:
        moment = datetime(2024, 12, 31, tzinfo=UTC)
        user = make_user(status=UserStatus.ACTIVE)
        user.mark_deleted(deleted_at=moment)
        assert user.deleted_at == moment


# ---------------------------------------------------------------------------
# mark_login()
# ---------------------------------------------------------------------------

class TestMarkLogin:
    def test_sets_last_login_at(self) -> None:
        user = make_user(last_login_at=None)
        user.mark_login()
        assert user.last_login_at is not None

    def test_custom_timestamp_is_stored(self) -> None:
        moment = datetime(2024, 7, 4, tzinfo=UTC)
        user = make_user(last_login_at=None)
        user.mark_login(logged_in_at=moment)
        assert user.last_login_at == moment


# ---------------------------------------------------------------------------
# change_password_hash()
# ---------------------------------------------------------------------------

class TestChangePasswordHash:
    def test_updates_password_hash(self) -> None:
        user = make_user(password_hash="old_hash")
        user.change_password_hash("new_hash")
        assert user.password_hash == "new_hash"


# ---------------------------------------------------------------------------
# roles / is_admin / is_regular_user / has_role
# ---------------------------------------------------------------------------

class TestRoleCodes:
    def test_role_codes_only_active(self) -> None:
        user = make_user(
            roles=[
                make_role("admin", is_active=True),
                make_role("inactive", is_active=False),
            ]
        )
        assert user.role_codes == {"admin"}

    def test_role_codes_empty(self) -> None:
        user = make_user(roles=[])
        assert user.role_codes == set()


class TestIsAdmin:
    def test_is_admin_true(self) -> None:
        user = make_user(roles=[make_role(SystemRole.ADMIN.value)])
        assert user.is_admin is True

    def test_is_admin_false(self) -> None:
        user = make_user(roles=[make_role(SystemRole.USER.value)])
        assert user.is_admin is False


class TestIsRegularUser:
    def test_is_regular_user_true(self) -> None:
        user = make_user(roles=[make_role(SystemRole.USER.value)])
        assert user.is_regular_user is True

    def test_is_regular_user_false(self) -> None:
        user = make_user(roles=[make_role(SystemRole.ADMIN.value)])
        assert user.is_regular_user is False


class TestHasRole:
    def test_has_role_with_string(self) -> None:
        user = make_user(roles=[make_role(SystemRole.ADMIN.value)])
        assert user.has_role(SystemRole.ADMIN.value) is True

    def test_has_role_with_enum(self) -> None:
        user = make_user(roles=[make_role(SystemRole.ADMIN.value)])
        assert user.has_role(SystemRole.ADMIN) is True

    def test_has_role_missing(self) -> None:
        user = make_user(roles=[make_role(SystemRole.USER.value)])
        assert user.has_role(SystemRole.ADMIN) is False


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------

class TestRepr:
    def test_repr_is_non_empty_string(self) -> None:
        user = make_user()
        result = repr(user)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_repr_contains_user_keyword(self) -> None:
        user = make_user()
        assert "User" in repr(user)
