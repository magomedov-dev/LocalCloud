"""Тесты сервиса прав доступа: проверки пользователя, владельца и прав на узлы."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from database.models.enums import (
    NodeVisibility,
    PermissionLevel,
    SystemRole,
    UserStatus,
)
from security.permissions.enums import PermissionAction, PermissionDeniedReason
from security.permissions.exceptions import PermissionCheckError, PermissionDeniedError
from security.permissions.service import (
    can_delete_node,
    can_download_node,
    can_manage_node,
    can_read_node,
    can_share_node,
    can_write_node,
    check_node_permission,
    find_user_permission,
    is_active_user,
    is_admin_user,
    is_node_owner,
    is_regular_user,
    permission_allows_action,
    permission_is_active_at,
    permission_level_allows_action,
    permission_level_at_least,
    public_node_allows_action,
    require_active_user,
    require_admin,
    require_node_permission,
    resolve_permission_denied_reason,
)


# ---------------------------------------------------------------------------
# Фабрики заглушек
# ---------------------------------------------------------------------------

def _make_user(
    *,
    id: uuid.UUID | None = None,
    status: UserStatus | str = UserStatus.ACTIVE,
    role: SystemRole | str | None = SystemRole.USER,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        status=status,
        role=role,
    )


def _make_node(
    *,
    id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    visibility: NodeVisibility | str = NodeVisibility.PRIVATE,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        owner_id=owner_id or uuid.uuid4(),
        visibility=visibility,
        is_deleted=is_deleted,
    )


def _make_permission(
    *,
    user_id: uuid.UUID | None = None,
    permission_level: PermissionLevel | str = PermissionLevel.READ,
    can_read: bool = True,
    can_download: bool = False,
    can_write: bool = False,
    can_delete: bool = False,
    can_share: bool = False,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> SimpleNamespace:
    perm = SimpleNamespace(
        user_id=user_id or uuid.uuid4(),
        permission_level=permission_level,
        can_read=can_read,
        can_download=can_download,
        can_write=can_write,
        can_delete=can_delete,
        can_share=can_share,
        revoked_at=revoked_at,
        expires_at=expires_at,
    )

    def is_active_at(moment: datetime) -> bool:
        if perm.revoked_at is not None:
            return False
        if perm.expires_at is not None and perm.expires_at <= moment:
            return False
        return True

    perm.is_active_at = is_active_at
    return perm


def _make_permission_no_callable(
    *,
    user_id: uuid.UUID | None = None,
    permission_level: PermissionLevel | str = PermissionLevel.READ,
    can_read: bool = True,
    can_download: bool = False,
    can_write: bool = False,
    can_delete: bool = False,
    can_share: bool = False,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> SimpleNamespace:
    """Заглушка права БЕЗ вызываемого ``is_active_at``.

    Заставляет ``permission_is_active_at`` использовать резервную ветку
    с revoked_at/expires_at.
    """
    return SimpleNamespace(
        user_id=user_id or uuid.uuid4(),
        permission_level=permission_level,
        can_read=can_read,
        can_download=can_download,
        can_write=can_write,
        can_delete=can_delete,
        can_share=can_share,
        revoked_at=revoked_at,
        expires_at=expires_at,
        is_active_at=None,
    )


# ---------------------------------------------------------------------------
# is_active_user
# ---------------------------------------------------------------------------

class TestIsActiveUser:
    def test_none_returns_false(self) -> None:
        assert is_active_user(None) is False

    def test_active_user_returns_true(self) -> None:
        user = _make_user(status=UserStatus.ACTIVE)
        assert is_active_user(user) is True

    def test_blocked_user_returns_false(self) -> None:
        user = _make_user(status=UserStatus.BLOCKED)
        assert is_active_user(user) is False

    def test_string_active_status_returns_true(self) -> None:
        user = _make_user(status="active")
        assert is_active_user(user) is True

    def test_string_blocked_status_returns_false(self) -> None:
        user = _make_user(status="blocked")
        assert is_active_user(user) is False


# ---------------------------------------------------------------------------
# is_admin_user
# ---------------------------------------------------------------------------

class TestIsAdminUser:
    def test_user_with_admin_role_code_returns_true(self) -> None:
        user = _make_user(role=SystemRole.ADMIN)
        assert is_admin_user(user) is True

    def test_user_with_no_roles_returns_false(self) -> None:
        user = _make_user(role=None)
        assert is_admin_user(user) is False

    def test_user_with_user_role_returns_false(self) -> None:
        user = _make_user(role=SystemRole.USER)
        assert is_admin_user(user) is False

    def test_none_returns_false(self) -> None:
        assert is_admin_user(None) is False


# ---------------------------------------------------------------------------
# is_node_owner
# ---------------------------------------------------------------------------

class TestIsNodeOwner:
    def test_same_ids_returns_true(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid)
        assert is_node_owner(user, node) is True

    def test_different_ids_returns_false(self) -> None:
        user = _make_user(id=uuid.uuid4())
        node = _make_node(owner_id=uuid.uuid4())
        assert is_node_owner(user, node) is False

    def test_none_user_returns_false(self) -> None:
        node = _make_node()
        assert is_node_owner(None, node) is False


# ---------------------------------------------------------------------------
# public_node_allows_action
# ---------------------------------------------------------------------------

class TestPublicNodeAllowsAction:
    def test_public_node_allows_read(self) -> None:
        node = _make_node(visibility=NodeVisibility.PUBLIC)
        assert public_node_allows_action(node, PermissionAction.READ) is True

    def test_public_node_allows_download(self) -> None:
        node = _make_node(visibility=NodeVisibility.PUBLIC)
        assert public_node_allows_action(node, PermissionAction.DOWNLOAD) is True

    def test_public_node_denies_write(self) -> None:
        node = _make_node(visibility=NodeVisibility.PUBLIC)
        assert public_node_allows_action(node, PermissionAction.WRITE) is False

    def test_private_node_denies_all(self) -> None:
        node = _make_node(visibility=NodeVisibility.PRIVATE)
        assert public_node_allows_action(node, PermissionAction.READ) is False
        assert public_node_allows_action(node, PermissionAction.DOWNLOAD) is False

    def test_shared_node_denies_read(self) -> None:
        node = _make_node(visibility=NodeVisibility.SHARED)
        assert public_node_allows_action(node, PermissionAction.READ) is False


# ---------------------------------------------------------------------------
# permission_level_at_least
# ---------------------------------------------------------------------------

class TestPermissionLevelAtLeast:
    def test_owner_at_least_write(self) -> None:
        assert permission_level_at_least(PermissionLevel.OWNER, PermissionLevel.WRITE) is True

    def test_read_not_at_least_write(self) -> None:
        assert permission_level_at_least(PermissionLevel.READ, PermissionLevel.WRITE) is False

    def test_equal_levels(self) -> None:
        assert permission_level_at_least(PermissionLevel.DELETE, PermissionLevel.DELETE) is True

    def test_write_not_at_least_owner(self) -> None:
        assert permission_level_at_least(PermissionLevel.WRITE, PermissionLevel.OWNER) is False


# ---------------------------------------------------------------------------
# permission_allows_action
# ---------------------------------------------------------------------------

class TestPermissionAllowsAction:
    def test_can_read_true_allows_read(self) -> None:
        perm = _make_permission(can_read=True)
        assert permission_allows_action(perm, PermissionAction.READ) is True

    def test_can_read_false_denies_read(self) -> None:
        perm = _make_permission(can_read=False)
        assert permission_allows_action(perm, PermissionAction.READ) is False

    def test_can_write_true_allows_write(self) -> None:
        perm = _make_permission(can_read=True, can_write=True)
        assert permission_allows_action(perm, PermissionAction.WRITE) is True

    def test_revoked_permission_denies(self) -> None:
        perm = _make_permission(can_read=True, revoked_at=datetime.now(UTC))
        assert permission_allows_action(perm, PermissionAction.READ) is False

    def test_expired_permission_denies(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        perm = _make_permission(can_read=True, expires_at=past)
        assert permission_allows_action(perm, PermissionAction.READ) is False


# ---------------------------------------------------------------------------
# find_user_permission
# ---------------------------------------------------------------------------

class TestFindUserPermission:
    def test_finds_matching_users_permission(self) -> None:
        uid = uuid.uuid4()
        perm = _make_permission(user_id=uid, can_read=True)
        result = find_user_permission([perm], user_id=uid)
        assert result is perm

    def test_returns_none_if_not_found(self) -> None:
        perm = _make_permission(user_id=uuid.uuid4(), can_read=True)
        result = find_user_permission([perm], user_id=uuid.uuid4())
        assert result is None

    def test_returns_none_for_empty_permissions(self) -> None:
        result = find_user_permission([], user_id=uuid.uuid4())
        assert result is None

    def test_returns_highest_level_permission(self) -> None:
        uid = uuid.uuid4()
        read_perm = _make_permission(user_id=uid, permission_level=PermissionLevel.READ)
        write_perm = _make_permission(user_id=uid, permission_level=PermissionLevel.WRITE)
        result = find_user_permission([read_perm, write_perm], user_id=uid)
        assert result is write_perm

    def test_skips_revoked_permission(self) -> None:
        uid = uuid.uuid4()
        revoked = _make_permission(user_id=uid, revoked_at=datetime.now(UTC))
        result = find_user_permission([revoked], user_id=uid)
        assert result is None


# ---------------------------------------------------------------------------
# check_node_permission
# ---------------------------------------------------------------------------

class TestCheckNodePermission:
    def test_deleted_node_returns_denied(self) -> None:
        node = _make_node(is_deleted=True)
        result = check_node_permission(user=None, node=node, action=PermissionAction.READ)
        assert result.allowed is False
        assert result.reason == PermissionDeniedReason.DELETED_NODE

    def test_none_user_on_private_node_returns_denied(self) -> None:
        node = _make_node(visibility=NodeVisibility.PRIVATE)
        result = check_node_permission(user=None, node=node, action=PermissionAction.READ)
        assert result.allowed is False
        assert result.reason == PermissionDeniedReason.ANONYMOUS_USER

    def test_none_user_on_public_node_returns_allowed(self) -> None:
        node = _make_node(visibility=NodeVisibility.PUBLIC)
        result = check_node_permission(user=None, node=node, action=PermissionAction.READ)
        assert result.allowed is True

    def test_inactive_user_returns_denied(self) -> None:
        user = _make_user(status=UserStatus.BLOCKED)
        node = _make_node()
        result = check_node_permission(user=user, node=node, action=PermissionAction.READ)
        assert result.allowed is False
        assert result.reason == PermissionDeniedReason.INACTIVE_USER

    def test_admin_user_returns_allowed(self) -> None:
        user = _make_user(role=SystemRole.ADMIN)
        node = _make_node()
        result = check_node_permission(user=user, node=node, action=PermissionAction.READ)
        assert result.allowed is True
        assert result.is_admin is True

    def test_owner_returns_allowed(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid)
        result = check_node_permission(user=user, node=node, action=PermissionAction.READ)
        assert result.allowed is True
        assert result.is_owner is True

    def test_user_with_no_permissions_returns_denied(self) -> None:
        user = _make_user()
        node = _make_node(visibility=NodeVisibility.PRIVATE)
        result = check_node_permission(user=user, node=node, action=PermissionAction.READ, permissions=[])
        assert result.allowed is False
        assert result.reason == PermissionDeniedReason.PERMISSION_NOT_FOUND

    def test_user_with_sufficient_permission_returns_allowed(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(visibility=NodeVisibility.PRIVATE)
        perm = _make_permission(user_id=uid, can_read=True)
        result = check_node_permission(
            user=user, node=node, action=PermissionAction.READ, permissions=[perm]
        )
        assert result.allowed is True

    def test_allow_deleted_true_bypasses_deleted_check(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid, is_deleted=True)
        result = check_node_permission(
            user=user, node=node, action=PermissionAction.READ, allow_deleted=True
        )
        assert result.allowed is True


# ---------------------------------------------------------------------------
# require_node_permission
# ---------------------------------------------------------------------------

class TestRequireNodePermission:
    def test_allowed_result_returns_result(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid)
        result = require_node_permission(user=user, node=node, action=PermissionAction.READ)
        assert result.allowed is True

    def test_denied_result_raises_permission_denied_error(self) -> None:
        user = _make_user()
        node = _make_node(visibility=NodeVisibility.PRIVATE)
        with pytest.raises(PermissionDeniedError):
            require_node_permission(
                user=user, node=node, action=PermissionAction.READ, permissions=[]
            )


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------

class TestRequireAdmin:
    def test_none_raises(self) -> None:
        with pytest.raises(PermissionDeniedError):
            require_admin(None)

    def test_inactive_user_raises(self) -> None:
        user = _make_user(status=UserStatus.BLOCKED)
        with pytest.raises(PermissionDeniedError):
            require_admin(user)

    def test_non_admin_raises(self) -> None:
        user = _make_user(role=SystemRole.USER)
        with pytest.raises(PermissionDeniedError):
            require_admin(user)

    def test_admin_passes(self) -> None:
        user = _make_user(role=SystemRole.ADMIN)
        # не должно вызывать исключение
        require_admin(user)


# ---------------------------------------------------------------------------
# require_active_user
# ---------------------------------------------------------------------------

class TestRequireActiveUser:
    def test_none_raises(self) -> None:
        with pytest.raises(PermissionDeniedError):
            require_active_user(None)

    def test_inactive_user_raises(self) -> None:
        user = _make_user(status=UserStatus.BLOCKED)
        with pytest.raises(PermissionDeniedError):
            require_active_user(user)

    def test_active_user_passes(self) -> None:
        user = _make_user(status=UserStatus.ACTIVE)
        # не должно вызывать исключение
        require_active_user(user)


# ---------------------------------------------------------------------------
# Булевы обёртки: can_read_node, can_download_node, can_write_node, can_delete_node
# ---------------------------------------------------------------------------

class TestCanReadNode:
    def test_owner_can_read(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid)
        assert can_read_node(user, node) is True

    def test_anonymous_cannot_read_private(self) -> None:
        node = _make_node(visibility=NodeVisibility.PRIVATE)
        assert can_read_node(None, node) is False

    def test_anonymous_can_read_public(self) -> None:
        node = _make_node(visibility=NodeVisibility.PUBLIC)
        assert can_read_node(None, node) is True


class TestCanDownloadNode:
    def test_owner_can_download(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid)
        assert can_download_node(user, node) is True

    def test_anonymous_cannot_download_private(self) -> None:
        node = _make_node(visibility=NodeVisibility.PRIVATE)
        assert can_download_node(None, node) is False

    def test_anonymous_can_download_public(self) -> None:
        node = _make_node(visibility=NodeVisibility.PUBLIC)
        assert can_download_node(None, node) is True


class TestCanWriteNode:
    def test_owner_can_write(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid)
        assert can_write_node(user, node) is True

    def test_user_without_write_permission_cannot_write(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        other_uid = uuid.uuid4()
        node = _make_node(owner_id=other_uid, visibility=NodeVisibility.PRIVATE)
        perm = _make_permission(user_id=uid, can_read=True, can_write=False)
        assert can_write_node(user, node, permissions=[perm]) is False


class TestCanDeleteNode:
    def test_owner_can_delete(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid)
        assert can_delete_node(user, node) is True

    def test_user_without_delete_permission_cannot_delete(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        other_uid = uuid.uuid4()
        node = _make_node(owner_id=other_uid, visibility=NodeVisibility.PRIVATE)
        perm = _make_permission(user_id=uid, can_read=True, can_delete=False)
        assert can_delete_node(user, node, permissions=[perm]) is False


# ---------------------------------------------------------------------------
# can_share_node / can_manage_node
# ---------------------------------------------------------------------------


class TestCanShareNode:
    def test_owner_can_share(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid)
        assert can_share_node(user, node) is True

    def test_non_owner_without_share_cannot_share(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uuid.uuid4(), visibility=NodeVisibility.PRIVATE)
        perm = _make_permission(user_id=uid, can_read=True, can_share=False)
        assert can_share_node(user, node, permissions=[perm]) is False


class TestCanManageNode:
    def test_owner_can_manage(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uid)
        assert can_manage_node(user, node) is True

    def test_non_owner_without_owner_level_cannot_manage(self) -> None:
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(owner_id=uuid.uuid4(), visibility=NodeVisibility.PRIVATE)
        perm = _make_permission(user_id=uid, can_read=True, can_share=False)
        assert can_manage_node(user, node, permissions=[perm]) is False


# ---------------------------------------------------------------------------
# is_regular_user
# ---------------------------------------------------------------------------


class TestIsRegularUser:
    def test_user_with_user_role_returns_true(self) -> None:
        user = _make_user(role=SystemRole.USER)
        assert is_regular_user(user) is True

    def test_admin_only_user_returns_false(self) -> None:
        user = _make_user(role=SystemRole.ADMIN)
        assert is_regular_user(user) is False

    def test_none_returns_false(self) -> None:
        assert is_regular_user(None) is False


# ---------------------------------------------------------------------------
# permission_allows_action — остальные ветки действий
# ---------------------------------------------------------------------------


class TestPermissionAllowsActionBranches:
    def test_download_action_uses_can_download(self) -> None:
        perm = _make_permission(can_download=True)
        assert permission_allows_action(perm, PermissionAction.DOWNLOAD) is True

    def test_download_action_denied_when_false(self) -> None:
        perm = _make_permission(can_download=False)
        assert permission_allows_action(perm, PermissionAction.DOWNLOAD) is False

    def test_delete_action_uses_can_delete(self) -> None:
        perm = _make_permission(can_delete=True)
        assert permission_allows_action(perm, PermissionAction.DELETE) is True

    def test_share_requires_can_share_and_owner_level(self) -> None:
        perm = _make_permission(
            can_share=True, permission_level=PermissionLevel.OWNER
        )
        assert permission_allows_action(perm, PermissionAction.SHARE) is True

    def test_share_denied_without_owner_level(self) -> None:
        perm = _make_permission(
            can_share=True, permission_level=PermissionLevel.WRITE
        )
        assert permission_allows_action(perm, PermissionAction.SHARE) is False

    def test_manage_action_branch(self) -> None:
        perm = _make_permission(
            can_share=True, permission_level=PermissionLevel.OWNER
        )
        assert permission_allows_action(perm, PermissionAction.MANAGE) is True

    def test_owner_action_branch(self) -> None:
        perm = _make_permission(
            can_share=True, permission_level=PermissionLevel.OWNER
        )
        assert permission_allows_action(perm, PermissionAction.OWNER) is True

    def test_purge_action_branch(self) -> None:
        perm = _make_permission(
            can_share=True, permission_level=PermissionLevel.OWNER
        )
        assert permission_allows_action(perm, PermissionAction.PURGE) is True

    def test_restore_action_uses_can_delete(self) -> None:
        perm = _make_permission(can_delete=True)
        assert permission_allows_action(perm, PermissionAction.RESTORE) is True

    def test_unknown_action_raises_permission_check_error(self) -> None:
        # действие, для которого требуемый уровень существует, но которое проходит
        # мимо всех явных веток внутри permission_allows_action
        perm = _make_permission(can_read=True)
        with pytest.raises(PermissionCheckError):
            permission_allows_action(perm, "totally-unknown-action")


# ---------------------------------------------------------------------------
# permission_level_allows_action
# ---------------------------------------------------------------------------


class TestPermissionLevelAllowsAction:
    def test_owner_level_allows_share(self) -> None:
        assert (
            permission_level_allows_action(
                PermissionLevel.OWNER, PermissionAction.SHARE
            )
            is True
        )

    def test_read_level_does_not_allow_write(self) -> None:
        assert (
            permission_level_allows_action(
                PermissionLevel.READ, PermissionAction.WRITE
            )
            is False
        )

    def test_read_level_allows_read(self) -> None:
        assert (
            permission_level_allows_action(
                PermissionLevel.READ, PermissionAction.READ
            )
            is True
        )


# ---------------------------------------------------------------------------
# permission_is_active_at — резервная ветка (без вызываемого is_active_at)
# ---------------------------------------------------------------------------


class TestPermissionIsActiveAtFallback:
    def test_active_when_not_revoked_or_expired(self) -> None:
        perm = _make_permission_no_callable()
        assert permission_is_active_at(perm) is True

    def test_revoked_returns_false(self) -> None:
        perm = _make_permission_no_callable(revoked_at=datetime.now(UTC))
        assert permission_is_active_at(perm) is False

    def test_expired_returns_false(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        perm = _make_permission_no_callable(expires_at=past)
        assert permission_is_active_at(perm) is False

    def test_future_expiry_is_active(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=1)
        perm = _make_permission_no_callable(expires_at=future)
        assert permission_is_active_at(perm) is True


# ---------------------------------------------------------------------------
# resolve_permission_denied_reason
# ---------------------------------------------------------------------------


class TestResolvePermissionDeniedReason:
    def test_revoked_returns_revoked_reason(self) -> None:
        perm = _make_permission(revoked_at=datetime.now(UTC))
        assert (
            resolve_permission_denied_reason(perm)
            == PermissionDeniedReason.PERMISSION_REVOKED
        )

    def test_expired_returns_expired_reason(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        perm = _make_permission(expires_at=past)
        assert (
            resolve_permission_denied_reason(perm)
            == PermissionDeniedReason.PERMISSION_EXPIRED
        )

    def test_otherwise_insufficient_permission(self) -> None:
        perm = _make_permission()
        assert (
            resolve_permission_denied_reason(perm)
            == PermissionDeniedReason.INSUFFICIENT_PERMISSION
        )


# ---------------------------------------------------------------------------
# check_node_permission — дополнительные ветки
# ---------------------------------------------------------------------------


class TestCheckNodePermissionExtraBranches:
    def test_authenticated_non_owner_on_public_node_allowed(self) -> None:
        """Активный пользователь (не владелец, не админ) читает публичный узел (строка 147)."""
        user = _make_user()  # обычный пользователь со случайным id
        node = _make_node(
            owner_id=uuid.uuid4(), visibility=NodeVisibility.PUBLIC
        )
        result = check_node_permission(
            user=user, node=node, action=PermissionAction.READ
        )
        assert result.allowed is True
        assert result.details.get("source") == "public_node"

    def test_matched_permission_insufficient_returns_denied_with_reason(self) -> None:
        """У пользователя есть запись права, но она не разрешает действие."""
        uid = uuid.uuid4()
        user = _make_user(id=uid)
        node = _make_node(
            owner_id=uuid.uuid4(), visibility=NodeVisibility.PRIVATE
        )
        # есть только право на чтение; запрашивается запись -> найдено, но недостаточно
        perm = _make_permission(
            user_id=uid, can_read=True, can_write=False
        )
        result = check_node_permission(
            user=user,
            node=node,
            action=PermissionAction.WRITE,
            permissions=[perm],
        )
        assert result.allowed is False
        assert result.reason == PermissionDeniedReason.INSUFFICIENT_PERMISSION
