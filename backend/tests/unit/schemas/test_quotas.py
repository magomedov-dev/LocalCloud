"""Модульные тесты схем квот."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import QuotaResourceType
from schemas.quotas import (
    QuotaCheckRequest,
    QuotaRecalculateRequest,
    QuotaUsageRead,
    UserQuotaBase,
    UserQuotaCreate,
    UserQuotaUpdate,
)


class TestUserQuotaBase:
    """Тесты базовой схемы квоты пользователя."""

    def test_valid_minimal(self):
        q = UserQuotaBase(storage_limit_bytes=1024, max_file_size_bytes=512)
        assert q.storage_used_bytes == 0
        assert q.files_limit is None
        assert q.files_used == 0
        assert q.public_links_limit is None
        assert q.active_upload_sessions_limit is None

    def test_storage_limit_required(self):
        with pytest.raises(ValidationError):
            UserQuotaBase(max_file_size_bytes=512)

    def test_max_file_size_required(self):
        with pytest.raises(ValidationError):
            UserQuotaBase(storage_limit_bytes=1024)

    def test_negative_storage_limit_raises(self):
        with pytest.raises(ValidationError):
            UserQuotaBase(storage_limit_bytes=-1, max_file_size_bytes=512)

    def test_zero_limits_valid(self):
        q = UserQuotaBase(storage_limit_bytes=0, max_file_size_bytes=0)
        assert q.storage_limit_bytes == 0


class TestUserQuotaCreate:
    """Тесты схемы создания квоты пользователя."""

    def test_valid(self):
        uid = uuid4()
        q = UserQuotaCreate(
            storage_limit_bytes=10 * 1024 ** 3,
            max_file_size_bytes=1024 ** 3,
            user_id=uid,
        )
        assert q.user_id == uid

    def test_user_id_required(self):
        with pytest.raises(ValidationError):
            UserQuotaCreate(storage_limit_bytes=1024, max_file_size_bytes=512)


class TestUserQuotaUpdate:
    """Тесты схемы обновления квоты пользователя."""

    def test_all_optional(self):
        u = UserQuotaUpdate()
        assert u.storage_limit_bytes is None
        assert u.files_used is None

    def test_negative_storage_limit_raises(self):
        with pytest.raises(ValidationError):
            UserQuotaUpdate(storage_limit_bytes=-1)


class TestQuotaUsageRead:
    """Тесты схемы чтения использования квоты."""

    def _make(self, **kwargs):
        defaults = {
            "user_id": uuid4(),
            "storage_limit_bytes": 1000,
            "storage_used_bytes": 0,
            "max_file_size_bytes": 500,
            "files_used": 0,
            "public_links_used": 0,
            "active_upload_sessions_used": 0,
        }
        defaults.update(kwargs)
        return QuotaUsageRead(**defaults)

    def test_available_storage_bytes(self):
        r = self._make(storage_limit_bytes=1000, storage_used_bytes=300)
        assert r.available_storage_bytes == 700

    def test_available_storage_bytes_zero_when_exceeded(self):
        r = self._make(storage_limit_bytes=100, storage_used_bytes=200)
        assert r.available_storage_bytes == 0

    def test_usage_percent_basic(self):
        r = self._make(storage_limit_bytes=1000, storage_used_bytes=500)
        assert r.usage_percent == 50.0

    def test_usage_percent_zero(self):
        r = self._make(storage_limit_bytes=1000, storage_used_bytes=0)
        assert r.usage_percent == 0.0

    def test_usage_percent_capped_at_100(self):
        r = self._make(storage_limit_bytes=100, storage_used_bytes=200)
        assert r.usage_percent == 100.0

    def test_usage_percent_zero_limit_with_usage(self):
        r = self._make(storage_limit_bytes=0, storage_used_bytes=100)
        assert r.usage_percent == 100.0

    def test_usage_percent_zero_limit_no_usage(self):
        r = self._make(storage_limit_bytes=0, storage_used_bytes=0)
        assert r.usage_percent == 0.0

    def test_is_storage_full_true(self):
        r = self._make(storage_limit_bytes=100, storage_used_bytes=100)
        assert r.is_storage_full is True

    def test_is_storage_full_false(self):
        r = self._make(storage_limit_bytes=100, storage_used_bytes=99)
        assert r.is_storage_full is False

    def test_is_files_limit_reached_true(self):
        r = self._make(files_limit=10, files_used=10)
        assert r.is_files_limit_reached is True

    def test_is_files_limit_reached_false_no_limit(self):
        r = self._make(files_limit=None, files_used=1000)
        assert r.is_files_limit_reached is False

    def test_is_public_links_limit_reached_true(self):
        r = self._make(public_links_limit=5, public_links_used=5)
        assert r.is_public_links_limit_reached is True

    def test_is_active_upload_sessions_limit_reached_true(self):
        r = self._make(active_upload_sessions_limit=3, active_upload_sessions_used=3)
        assert r.is_active_upload_sessions_limit_reached is True

    def test_usage_percent_rounded(self):
        r = self._make(storage_limit_bytes=3, storage_used_bytes=1)
        assert r.usage_percent == round(1 / 3 * 100, 2)


class TestQuotaCheckRequest:
    """Тесты запроса проверки квоты."""

    def test_valid(self):
        r = QuotaCheckRequest(
            user_id=uuid4(),
            resource_type=QuotaResourceType.STORAGE_BYTES,
            requested_amount=1024,
        )
        assert r.requested_amount == 1024

    def test_user_id_required(self):
        with pytest.raises(ValidationError):
            QuotaCheckRequest(
                resource_type=QuotaResourceType.STORAGE_BYTES,
                requested_amount=0,
            )

    def test_resource_type_required(self):
        with pytest.raises(ValidationError):
            QuotaCheckRequest(user_id=uuid4(), requested_amount=0)

    def test_negative_requested_amount_raises(self):
        with pytest.raises(ValidationError):
            QuotaCheckRequest(
                user_id=uuid4(),
                resource_type=QuotaResourceType.FILE_COUNT,
                requested_amount=-1,
            )

    def test_zero_amount_valid(self):
        r = QuotaCheckRequest(
            user_id=uuid4(),
            resource_type=QuotaResourceType.FILE_COUNT,
            requested_amount=0,
        )
        assert r.requested_amount == 0


class TestQuotaRecalculateRequest:
    """Тесты запроса пересчёта квоты."""

    def test_valid_minimal(self):
        r = QuotaRecalculateRequest(user_id=uuid4())
        assert r.resource_types is None
        assert r.force is False

    def test_user_id_required(self):
        with pytest.raises(ValidationError):
            QuotaRecalculateRequest()

    def test_with_resource_types(self):
        r = QuotaRecalculateRequest(
            user_id=uuid4(),
            resource_types=[QuotaResourceType.STORAGE_BYTES, QuotaResourceType.FILE_COUNT],
        )
        assert len(r.resource_types) == 2
