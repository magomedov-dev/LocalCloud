"""Тесты DTO PermissionCheckResult: флаг denied и raise_if_denied."""

from __future__ import annotations

import uuid

import pytest

from security.permissions.dto import PermissionCheckResult
from security.permissions.enums import PermissionAction, PermissionDeniedReason
from security.permissions.exceptions import PermissionDeniedError


class TestPermissionCheckResultDenied:
    def test_denied_is_inverse_of_allowed_true(self) -> None:
        result = PermissionCheckResult(allowed=True, action=PermissionAction.READ)
        assert result.denied is False

    def test_denied_is_inverse_of_allowed_false(self) -> None:
        result = PermissionCheckResult(allowed=False, action=PermissionAction.WRITE)
        assert result.denied is True


class TestPermissionCheckResultRaiseIfDenied:
    def test_allowed_result_does_not_raise(self) -> None:
        result = PermissionCheckResult(allowed=True, action=PermissionAction.READ)
        # не должно вызывать исключение
        result.raise_if_denied()

    def test_denied_result_raises_permission_denied_error(self) -> None:
        result = PermissionCheckResult(
            allowed=False,
            action=PermissionAction.WRITE,
            reason=PermissionDeniedReason.ANONYMOUS_USER,
        )
        with pytest.raises(PermissionDeniedError):
            result.raise_if_denied()

    def test_denied_result_error_contains_action(self) -> None:
        node_id = uuid.uuid4()
        user_id = uuid.uuid4()
        result = PermissionCheckResult(
            allowed=False,
            action=PermissionAction.DELETE,
            reason=PermissionDeniedReason.INACTIVE_USER,
            user_id=user_id,
            node_id=node_id,
        )
        with pytest.raises(PermissionDeniedError) as exc_info:
            result.raise_if_denied()

        err = exc_info.value
        assert "delete" in err.details.get("action", "")

    def test_denied_result_error_contains_reason(self) -> None:
        result = PermissionCheckResult(
            allowed=False,
            action=PermissionAction.READ,
            reason=PermissionDeniedReason.PERMISSION_NOT_FOUND,
        )
        with pytest.raises(PermissionDeniedError) as exc_info:
            result.raise_if_denied()

        err = exc_info.value
        assert "permission_not_found" in err.details.get("reason", "")

    def test_denied_result_error_contains_user_id(self) -> None:
        user_id = uuid.uuid4()
        result = PermissionCheckResult(
            allowed=False,
            action=PermissionAction.READ,
            reason=PermissionDeniedReason.ANONYMOUS_USER,
            user_id=user_id,
        )
        with pytest.raises(PermissionDeniedError) as exc_info:
            result.raise_if_denied()

        err = exc_info.value
        assert str(user_id) in err.details.get("user_id", "")

    def test_denied_result_error_contains_node_id(self) -> None:
        node_id = uuid.uuid4()
        result = PermissionCheckResult(
            allowed=False,
            action=PermissionAction.READ,
            reason=PermissionDeniedReason.DELETED_NODE,
            node_id=node_id,
        )
        with pytest.raises(PermissionDeniedError) as exc_info:
            result.raise_if_denied()

        err = exc_info.value
        assert str(node_id) in err.details.get("node_id", "")

    def test_default_values(self) -> None:
        result = PermissionCheckResult(allowed=True, action=PermissionAction.READ)
        assert result.reason is None
        assert result.user_id is None
        assert result.node_id is None
        assert result.permission_level is None
        assert result.is_admin is False
        assert result.is_owner is False
        assert result.details is None
