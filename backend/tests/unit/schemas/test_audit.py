"""Модульные тесты схем аудита."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import AuditAction, AuditResourceType, AuditResult
from schemas.audit import (
    AuditExportRequest,
    AuditLogCreate,
    AuditLogListItem,
    AuditLogRead,
    AuditQueryParams,
    AuditSummaryRead,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestAuditLogRead:
    """Тесты схемы чтения записи аудита."""

    def test_valid_minimal(self):
        r = AuditLogRead(
            id=uuid4(),
            action=AuditAction.USER_LOGIN,
            result=AuditResult.SUCCESS,
            created_at=NOW,
        )
        assert r.user_id is None
        assert r.metadata is None

    def test_metadata_validation_alias(self):
        r = AuditLogRead(
            id=uuid4(),
            action=AuditAction.USER_LOGIN,
            result=AuditResult.SUCCESS,
            created_at=NOW,
            metadata_={"k": "v"},
        )
        assert r.metadata == {"k": "v"}

    def test_metadata_serialization_alias(self):
        r = AuditLogRead(
            id=uuid4(),
            action=AuditAction.USER_LOGIN,
            result=AuditResult.SUCCESS,
            created_at=NOW,
            metadata={"k": "v"},
        )
        dumped = r.model_dump(by_alias=True)
        assert dumped["metadata"] == {"k": "v"}

    def test_from_attributes_with_metadata_underscore(self):
        class Obj:
            id = uuid4()
            user_id = None
            action = AuditAction.USER_LOGIN
            result = AuditResult.SUCCESS
            entity_type = None
            entity_id = None
            resource_type = None
            request_id = None
            correlation_id = None
            ip_address = None
            user_agent = None
            message = None
            error_code = None
            metadata_ = {"a": 1}
            created_at = NOW

        r = AuditLogRead.model_validate(Obj())
        assert r.metadata == {"a": 1}

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            AuditLogRead(id=uuid4())

    def test_entity_type_too_long_raises(self):
        with pytest.raises(ValidationError):
            AuditLogRead(
                id=uuid4(),
                action=AuditAction.USER_LOGIN,
                result=AuditResult.SUCCESS,
                created_at=NOW,
                entity_type="a" * 129,
            )


class TestAuditLogListItem:
    """Тесты элемента списка записей аудита."""

    def test_valid(self):
        r = AuditLogListItem(
            id=uuid4(),
            action=AuditAction.FILE_UPLOADED,
            result=AuditResult.SUCCESS,
            created_at=NOW,
        )
        assert r.message is None

    def test_resource_type_enum_coercion(self):
        r = AuditLogListItem(
            id=uuid4(),
            action=AuditAction.FILE_UPLOADED,
            result=AuditResult.SUCCESS,
            created_at=NOW,
            resource_type="file",
        )
        assert r.resource_type == AuditResourceType.FILE


class TestAuditLogCreate:
    """Тесты схемы создания записи аудита."""

    def test_valid_minimal(self):
        r = AuditLogCreate(action=AuditAction.USER_LOGIN)
        assert r.result == AuditResult.SUCCESS

    def test_action_required(self):
        with pytest.raises(ValidationError):
            AuditLogCreate()

    def test_optional_text_normalized(self):
        r = AuditLogCreate(
            action=AuditAction.USER_LOGIN,
            entity_type="  user  ",
            message="  logged in  ",
        )
        assert r.entity_type == "user"
        assert r.message == "logged in"

    def test_optional_text_blank_becomes_none(self):
        r = AuditLogCreate(
            action=AuditAction.USER_LOGIN,
            entity_type="   ",
            request_id="   ",
        )
        assert r.entity_type is None
        assert r.request_id is None

    def test_metadata_alias(self):
        r = AuditLogCreate(action=AuditAction.USER_LOGIN, metadata_={"x": 1})
        assert r.metadata == {"x": 1}


class TestAuditQueryParams:
    """Тесты параметров запроса записей аудита."""

    def test_defaults(self):
        p = AuditQueryParams()
        assert p.limit == 50
        assert p.sort_by == "created_at"
        assert p.sort_desc is True
        assert p.action is None

    def test_optional_text_normalized(self):
        p = AuditQueryParams(entity_type="  user  ", query="  search  ")
        assert p.entity_type == "user"
        assert p.query == "search"

    def test_query_blank_becomes_none(self):
        p = AuditQueryParams(entity_type="   ")
        assert p.entity_type is None

    def test_created_range_invalid_raises(self):
        with pytest.raises(ValidationError):
            AuditQueryParams(created_from=NOW + timedelta(days=1), created_to=NOW)

    def test_created_range_valid(self):
        p = AuditQueryParams(created_from=NOW, created_to=NOW + timedelta(days=1))
        assert p.created_to > p.created_from

    def test_action_enum_coercion(self):
        p = AuditQueryParams(action="user.login")
        assert p.action == AuditAction.USER_LOGIN

    def test_query_too_long_raises(self):
        with pytest.raises(ValidationError):
            AuditQueryParams(query="a" * 256)


class TestAuditExportRequest:
    """Тесты запроса экспорта записей аудита."""

    def test_defaults(self):
        r = AuditExportRequest()
        assert r.format == "json"
        assert r.include_metadata is True
        assert r.limit is None

    def test_format_normalized_lower(self):
        r = AuditExportRequest(format="  CSV  ")
        assert r.format == "csv"

    def test_invalid_format_raises(self):
        with pytest.raises(ValidationError):
            AuditExportRequest(format="xml")

    def test_optional_text_normalized(self):
        r = AuditExportRequest(entity_type="  file  ")
        assert r.entity_type == "file"

    def test_optional_text_blank_becomes_none(self):
        r = AuditExportRequest(entity_type="   ")
        assert r.entity_type is None

    def test_limit_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            AuditExportRequest(limit=0)

    def test_limit_too_high_raises(self):
        with pytest.raises(ValidationError):
            AuditExportRequest(limit=100_001)

    def test_created_range_invalid_raises(self):
        with pytest.raises(ValidationError):
            AuditExportRequest(created_from=NOW + timedelta(days=1), created_to=NOW)

    def test_created_range_valid(self):
        r = AuditExportRequest(created_from=NOW, created_to=NOW + timedelta(days=1))
        assert r.created_to > r.created_from


class TestAuditSummaryRead:
    """Тесты схемы сводки по аудиту."""

    def test_valid_defaults(self):
        r = AuditSummaryRead(total_count=10)
        assert r.success_count == 0
        assert r.by_action == {}
        assert r.by_resource_type == {}
        assert r.by_result == {}
        assert r.period_from is None

    def test_negative_total_raises(self):
        with pytest.raises(ValidationError):
            AuditSummaryRead(total_count=-1)

    def test_with_distributions(self):
        r = AuditSummaryRead(
            total_count=3,
            success_count=2,
            failure_count=1,
            by_action={AuditAction.USER_LOGIN: 2},
            by_resource_type={AuditResourceType.USER: 2},
            by_result={AuditResult.SUCCESS: 2, AuditResult.FAILURE: 1},
            period_from=NOW,
            period_to=NOW + timedelta(days=1),
        )
        assert r.by_action[AuditAction.USER_LOGIN] == 2
        assert r.by_result[AuditResult.FAILURE] == 1
