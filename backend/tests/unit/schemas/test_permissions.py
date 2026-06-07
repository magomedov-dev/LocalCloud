"""Модульные тесты схем прав доступа."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import PermissionLevel, PermissionSubjectType
from schemas.permissions import (
    EffectivePermissionRead,
    NodePermissionCreate,
    NodePermissionUpdate,
    PermissionFlags,
    PermissionGrantRequest,
    PermissionRevokeRequest,
    PermissionUpdateRequest,
)


class TestPermissionFlags:
    """Тесты флагов прав доступа."""

    def test_defaults(self):
        f = PermissionFlags()
        assert f.can_read is True
        assert f.can_download is False
        assert f.can_write is False
        assert f.can_delete is False
        assert f.can_share is False

    def test_all_true(self):
        f = PermissionFlags(
            can_read=True,
            can_download=True,
            can_write=True,
            can_delete=True,
            can_share=True,
        )
        assert all([f.can_read, f.can_download, f.can_write, f.can_delete, f.can_share])


class TestNodePermissionCreate:
    """Тесты схемы создания права на узел."""

    def test_valid_minimal(self):
        r = NodePermissionCreate(node_id=uuid4(), user_id=uuid4())
        assert r.subject_type == PermissionSubjectType.USER
        assert r.permission_level == PermissionLevel.READ
        assert r.granted_by is None
        assert r.expires_at is None

    def test_node_id_required(self):
        with pytest.raises(ValidationError):
            NodePermissionCreate(user_id=uuid4())

    def test_user_id_required(self):
        with pytest.raises(ValidationError):
            NodePermissionCreate(node_id=uuid4())

    def test_custom_permission_level(self):
        r = NodePermissionCreate(
            node_id=uuid4(),
            user_id=uuid4(),
            permission_level=PermissionLevel.WRITE,
        )
        assert r.permission_level == PermissionLevel.WRITE


class TestPermissionGrantRequest:
    """Тесты запроса выдачи права доступа."""

    def test_valid(self):
        r = PermissionGrantRequest(node_id=uuid4(), user_id=uuid4())
        assert r.permission_level == PermissionLevel.READ
        assert r.expires_at is None

    def test_node_id_required(self):
        with pytest.raises(ValidationError):
            PermissionGrantRequest(user_id=uuid4())

    def test_user_id_required(self):
        with pytest.raises(ValidationError):
            PermissionGrantRequest(node_id=uuid4())


class TestPermissionUpdateRequest:
    """Тесты запроса обновления права доступа."""

    def test_valid_with_permission_id(self):
        r = PermissionUpdateRequest(
            permission_id=uuid4(),
            can_read=True,
        )
        assert r.can_read is True

    def test_valid_with_node_and_user_id(self):
        r = PermissionUpdateRequest(
            node_id=uuid4(),
            user_id=uuid4(),
            can_write=True,
        )
        assert r.can_write is True

    def test_no_identifier_raises(self):
        with pytest.raises(ValidationError):
            PermissionUpdateRequest(can_read=True)

    def test_only_node_id_without_user_id_raises(self):
        with pytest.raises(ValidationError):
            PermissionUpdateRequest(node_id=uuid4(), can_read=True)

    def test_no_update_fields_raises(self):
        with pytest.raises(ValidationError):
            PermissionUpdateRequest(permission_id=uuid4())


class TestPermissionRevokeRequest:
    """Тесты запроса отзыва права доступа."""

    def test_valid_with_permission_id(self):
        r = PermissionRevokeRequest(permission_id=uuid4())
        assert r.revoke_reason is None

    def test_valid_with_node_and_user_id(self):
        r = PermissionRevokeRequest(node_id=uuid4(), user_id=uuid4())
        assert r.revoke_reason is None

    def test_no_identifier_raises(self):
        with pytest.raises(ValidationError):
            PermissionRevokeRequest()

    def test_only_node_id_without_user_id_raises(self):
        with pytest.raises(ValidationError):
            PermissionRevokeRequest(node_id=uuid4())

    def test_revoke_reason_normalization(self):
        r = PermissionRevokeRequest(
            permission_id=uuid4(),
            revoke_reason="  violated terms  ",
        )
        assert r.revoke_reason == "violated terms"

    def test_whitespace_reason_becomes_none(self):
        r = PermissionRevokeRequest(
            permission_id=uuid4(),
            revoke_reason="   ",
        )
        assert r.revoke_reason is None

    def test_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            PermissionRevokeRequest(
                permission_id=uuid4(),
                revoke_reason="a" * 513,
            )


class TestEffectivePermissionRead:
    """Тесты схемы чтения эффективных прав доступа."""

    def test_valid_minimal(self):
        r = EffectivePermissionRead(node_id=uuid4())
        assert r.can_read is True
        assert r.is_owner is False
        assert r.is_admin is False
        assert r.is_public is False
        assert r.user_id is None

    def test_node_id_required(self):
        with pytest.raises(ValidationError):
            EffectivePermissionRead()
