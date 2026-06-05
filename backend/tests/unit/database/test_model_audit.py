"""Модульные тесты ORM-модели AuditLog.

Тесты проверяют вычисляемые свойства уровня Python и __repr__ через обычные
вызовы конструктора, поэтому сессия БД не требуется.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from database.models.audit import AuditLog
from database.models.enums import AuditAction, AuditResult


def make_audit(**kwargs: object) -> AuditLog:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        action=AuditAction.USER_LOGIN,
        result=AuditResult.SUCCESS,
        entity_type=None,
        entity_id=None,
        resource_type=None,
        request_id=None,
        correlation_id=None,
        ip_address=None,
        user_agent=None,
        message=None,
        error_code=None,
        metadata_=None,
        created_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return AuditLog(**defaults)


class TestIsSystemAction:
    def test_no_user_returns_true(self) -> None:
        assert make_audit(user_id=None).is_system_action is True

    def test_with_user_returns_false(self) -> None:
        assert make_audit(user_id=uuid.uuid4()).is_system_action is False


class TestIsUserAction:
    def test_with_user_returns_true(self) -> None:
        assert make_audit(user_id=uuid.uuid4()).is_user_action is True

    def test_no_user_returns_false(self) -> None:
        assert make_audit(user_id=None).is_user_action is False


class TestHasEntity:
    def test_both_set_returns_true(self) -> None:
        log = make_audit(entity_type="file", entity_id=uuid.uuid4())
        assert log.has_entity is True

    def test_missing_id_returns_false(self) -> None:
        log = make_audit(entity_type="file", entity_id=None)
        assert log.has_entity is False

    def test_missing_type_returns_false(self) -> None:
        log = make_audit(entity_type=None, entity_id=uuid.uuid4())
        assert log.has_entity is False


class TestResultProperties:
    def test_is_success_true(self) -> None:
        assert make_audit(result=AuditResult.SUCCESS).is_success is True

    def test_is_success_false(self) -> None:
        assert make_audit(result=AuditResult.FAILURE).is_success is False

    def test_is_failure_true(self) -> None:
        assert make_audit(result=AuditResult.FAILURE).is_failure is True

    def test_is_failure_false(self) -> None:
        assert make_audit(result=AuditResult.SUCCESS).is_failure is False

    def test_is_denied_true(self) -> None:
        assert make_audit(result=AuditResult.DENIED).is_denied is True

    def test_is_denied_false(self) -> None:
        assert make_audit(result=AuditResult.SUCCESS).is_denied is False

    def test_is_warning_true(self) -> None:
        assert make_audit(result=AuditResult.WARNING).is_warning is True

    def test_is_warning_false(self) -> None:
        assert make_audit(result=AuditResult.SUCCESS).is_warning is False


class TestHasMetadata:
    def test_with_metadata_true(self) -> None:
        assert make_audit(metadata_={"k": "v"}).has_metadata is True

    def test_empty_metadata_false(self) -> None:
        assert make_audit(metadata_={}).has_metadata is False

    def test_none_metadata_false(self) -> None:
        assert make_audit(metadata_=None).has_metadata is False


class TestAuditLogRepr:
    def test_repr_non_empty(self) -> None:
        result = repr(make_audit())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_repr_contains_class_name(self) -> None:
        assert "AuditLog" in repr(make_audit())
