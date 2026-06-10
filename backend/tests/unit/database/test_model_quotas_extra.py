"""Дополнительные модульные тесты модели UserQuota: свойства использования,
проверки лимитов и операции изменения квот через фабрику create_default."""
from __future__ import annotations

import uuid

import pytest

from database.models.quotas import UserQuota


def make_quota(**kwargs) -> UserQuota:
    """Создаёт UserQuota через фабрику create_default для корректной инициализации."""
    user_id = kwargs.pop("user_id", uuid.uuid4())
    q = UserQuota.create_default(
        user_id=user_id,
        storage_limit_bytes=kwargs.pop("storage_limit_bytes", 1024 * 1024 * 1024),
        max_file_size_bytes=kwargs.pop("max_file_size_bytes", 512 * 1024 * 1024),
        files_limit=kwargs.pop("files_limit", None),
        public_links_limit=kwargs.pop("public_links_limit", None),
        active_upload_sessions_limit=kwargs.pop("active_upload_sessions_limit", None),
    )
    # Применяем переопределения, которые create_default не поддерживает напрямую
    if "storage_used_bytes" in kwargs:
        q.storage_used_bytes = kwargs.pop("storage_used_bytes")
    if "files_used" in kwargs:
        q.files_used = kwargs.pop("files_used")
    if "public_links_used" in kwargs:
        q.public_links_used = kwargs.pop("public_links_used")
    if "active_upload_sessions_used" in kwargs:
        q.active_upload_sessions_used = kwargs.pop("active_upload_sessions_used")
    return q


class TestUserQuotaProperties:
    def test_available_storage_bytes_full_quota(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=30)
        assert q.available_storage_bytes == 70

    def test_available_storage_bytes_zero_when_full(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=100)
        assert q.available_storage_bytes == 0

    def test_available_storage_bytes_clamped_to_zero(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=150)
        assert q.available_storage_bytes == 0

    def test_usage_percent_zero(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=0)
        assert q.usage_percent == 0.0

    def test_usage_percent_fifty(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=50)
        assert q.usage_percent == 50.0

    def test_usage_percent_hundred(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=100)
        assert q.usage_percent == 100.0

    def test_is_storage_full_false_when_space_available(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=99)
        assert q.is_storage_full is False

    def test_is_storage_full_true_when_at_limit(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=100)
        assert q.is_storage_full is True

    def test_has_files_limit_false_when_none(self) -> None:
        q = make_quota(files_limit=None)
        assert q.has_files_limit is False

    def test_has_files_limit_true_when_set(self) -> None:
        q = make_quota(files_limit=100)
        assert q.has_files_limit is True

    def test_has_public_links_limit_false(self) -> None:
        q = make_quota(public_links_limit=None)
        assert q.has_public_links_limit is False

    def test_has_public_links_limit_true(self) -> None:
        q = make_quota(public_links_limit=10)
        assert q.has_public_links_limit is True

    def test_is_files_limit_reached_false(self) -> None:
        q = make_quota(files_limit=10, files_used=5)
        assert q.is_files_limit_reached is False

    def test_is_files_limit_reached_true(self) -> None:
        q = make_quota(files_limit=10, files_used=10)
        assert q.is_files_limit_reached is True

    def test_is_public_links_limit_reached_false_when_no_limit(self) -> None:
        q = make_quota(public_links_limit=None, public_links_used=100)
        assert q.is_public_links_limit_reached is False

    def test_usage_percent_zero_limit_with_usage(self) -> None:
        q = make_quota(storage_limit_bytes=0, storage_used_bytes=10)
        assert q.usage_percent == 100.0

    def test_usage_percent_zero_limit_no_usage(self) -> None:
        q = make_quota(storage_limit_bytes=0, storage_used_bytes=0)
        assert q.usage_percent == 0.0

    def test_has_active_upload_sessions_limit_false(self) -> None:
        q = make_quota(active_upload_sessions_limit=None)
        assert q.has_active_upload_sessions_limit is False

    def test_has_active_upload_sessions_limit_true(self) -> None:
        q = make_quota(active_upload_sessions_limit=3)
        assert q.has_active_upload_sessions_limit is True


class TestUserQuotaCanMethods:
    def test_can_store_file_true_when_space_available(self) -> None:
        q = make_quota(
            storage_limit_bytes=1000, storage_used_bytes=500,
            max_file_size_bytes=600,
        )
        assert q.can_store_file_size(400) is True

    def test_can_store_file_false_when_insufficient_space(self) -> None:
        q = make_quota(
            storage_limit_bytes=1000, storage_used_bytes=800,
            max_file_size_bytes=600,
        )
        assert q.can_store_file_size(300) is False

    def test_can_increase_usage_by_true(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=50)
        assert q.can_increase_usage_by(40) is True

    def test_can_increase_usage_by_false(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=80)
        assert q.can_increase_usage_by(30) is False

    def test_can_decrease_usage_by_true(self) -> None:
        q = make_quota(storage_used_bytes=50)
        assert q.can_decrease_usage_by(50) is True

    def test_can_decrease_usage_by_false(self) -> None:
        q = make_quota(storage_used_bytes=10)
        assert q.can_decrease_usage_by(20) is False

    def test_can_create_file_with_space(self) -> None:
        q = make_quota(
            storage_limit_bytes=1000, storage_used_bytes=0,
            max_file_size_bytes=600, files_limit=None,
        )
        assert q.can_create_file(50) is True

    def test_can_create_file_false_when_files_limit_reached(self) -> None:
        q = make_quota(files_limit=5, files_used=5, max_file_size_bytes=1000)
        assert q.can_create_file(0) is False

    def test_can_create_public_link_true_no_limit(self) -> None:
        q = make_quota(public_links_limit=None)
        assert q.can_create_public_link() is True

    def test_can_create_public_link_false_at_limit(self) -> None:
        q = make_quota(public_links_limit=5, public_links_used=5)
        assert q.can_create_public_link() is False

    def test_can_create_upload_session_true(self) -> None:
        q = make_quota(active_upload_sessions_limit=None)
        assert q.can_create_upload_session() is True


class TestUserQuotaUsageMethods:
    def test_increase_storage_usage(self) -> None:
        q = make_quota(storage_used_bytes=100)
        q.increase_storage_usage(50)
        assert q.storage_used_bytes == 150

    def test_increase_storage_usage_negative_raises(self) -> None:
        q = make_quota(storage_used_bytes=100)
        with pytest.raises(ValueError):
            q.increase_storage_usage(-1)

    def test_increase_storage_usage_over_quota_raises(self) -> None:
        q = make_quota(storage_limit_bytes=100, storage_used_bytes=90)
        with pytest.raises(ValueError):
            q.increase_storage_usage(50)

    def test_decrease_storage_usage(self) -> None:
        q = make_quota(storage_used_bytes=100)
        q.decrease_storage_usage(30)
        assert q.storage_used_bytes == 70

    def test_decrease_storage_usage_clamped_to_zero(self) -> None:
        q = make_quota(storage_used_bytes=10)
        q.decrease_storage_usage(50)
        assert q.storage_used_bytes == 0

    def test_set_storage_usage(self) -> None:
        q = make_quota(storage_used_bytes=0)
        q.set_storage_usage(500)
        assert q.storage_used_bytes == 500

    def test_increase_files_used(self) -> None:
        q = make_quota(files_used=5)
        q.increase_files_used()
        assert q.files_used == 6

    def test_increase_files_used_by_count(self) -> None:
        q = make_quota(files_used=5)
        q.increase_files_used(3)
        assert q.files_used == 8

    def test_decrease_files_used(self) -> None:
        q = make_quota(files_used=5)
        q.decrease_files_used()
        assert q.files_used == 4

    def test_decrease_files_used_clamped_to_zero(self) -> None:
        q = make_quota(files_used=0)
        q.decrease_files_used(10)
        assert q.files_used == 0

    def test_set_files_used(self) -> None:
        q = make_quota(files_used=3)
        q.set_files_used(10)
        assert q.files_used == 10

    def test_increase_public_links_used(self) -> None:
        q = make_quota(public_links_used=2)
        q.increase_public_links_used()
        assert q.public_links_used == 3

    def test_decrease_public_links_used(self) -> None:
        q = make_quota(public_links_used=3)
        q.decrease_public_links_used()
        assert q.public_links_used == 2

    def test_set_public_links_used(self) -> None:
        q = make_quota(public_links_used=0)
        q.set_public_links_used(7)
        assert q.public_links_used == 7

    def test_increase_upload_sessions_used(self) -> None:
        q = make_quota(active_upload_sessions_used=1)
        q.increase_active_upload_sessions_used()
        assert q.active_upload_sessions_used == 2

    def test_decrease_upload_sessions_used(self) -> None:
        q = make_quota(active_upload_sessions_used=2)
        q.decrease_active_upload_sessions_used()
        assert q.active_upload_sessions_used == 1

    def test_set_active_upload_sessions_used(self) -> None:
        q = make_quota(active_upload_sessions_used=0)
        q.set_active_upload_sessions_used(3)
        assert q.active_upload_sessions_used == 3


class TestUserQuotaUpdateLimits:
    def test_update_storage_limit(self) -> None:
        q = make_quota(storage_limit_bytes=1000)
        q.update_limits(storage_limit_bytes=2000)
        assert q.storage_limit_bytes == 2000

    def test_update_files_limit(self) -> None:
        q = make_quota(files_limit=10)
        q.update_limits(files_limit=20)
        assert q.files_limit == 20

    def test_update_limits_none_removes_files_limit(self) -> None:
        q = make_quota(files_limit=10)
        # Для files_limit значение None означает «снять лимит» (без ограничения)
        q.update_limits(files_limit=None)
        assert q.files_limit is None

    def test_update_limits_storage_none_does_not_change(self) -> None:
        q = make_quota(storage_limit_bytes=1000)
        q.update_limits(storage_limit_bytes=None)
        # storage_limit_bytes None = не изменять
        assert q.storage_limit_bytes == 1000


class TestUserQuotaValidationErrors:
    def test_decrease_storage_usage_negative_raises(self) -> None:
        q = make_quota(storage_used_bytes=100)
        with pytest.raises(ValueError):
            q.decrease_storage_usage(-1)

    def test_set_storage_usage_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.set_storage_usage(-1)

    def test_set_storage_usage_above_limit_raises(self) -> None:
        q = make_quota(storage_limit_bytes=100)
        with pytest.raises(ValueError):
            q.set_storage_usage(200)

    def test_increase_files_used_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.increase_files_used(-1)

    def test_increase_files_used_above_limit_raises(self) -> None:
        q = make_quota(files_limit=5, files_used=5)
        with pytest.raises(ValueError):
            q.increase_files_used(1)

    def test_decrease_files_used_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.decrease_files_used(-1)

    def test_set_files_used_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.set_files_used(-1)

    def test_set_files_used_above_limit_raises(self) -> None:
        q = make_quota(files_limit=5)
        with pytest.raises(ValueError):
            q.set_files_used(10)

    def test_increase_public_links_used_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.increase_public_links_used(-1)

    def test_increase_public_links_used_above_limit_raises(self) -> None:
        q = make_quota(public_links_limit=5, public_links_used=5)
        with pytest.raises(ValueError):
            q.increase_public_links_used(1)

    def test_decrease_public_links_used_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.decrease_public_links_used(-1)

    def test_set_public_links_used_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.set_public_links_used(-1)

    def test_set_public_links_used_above_limit_raises(self) -> None:
        q = make_quota(public_links_limit=5)
        with pytest.raises(ValueError):
            q.set_public_links_used(10)

    def test_increase_upload_sessions_used_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.increase_active_upload_sessions_used(-1)

    def test_increase_upload_sessions_used_above_limit_raises(self) -> None:
        q = make_quota(active_upload_sessions_limit=3, active_upload_sessions_used=3)
        with pytest.raises(ValueError):
            q.increase_active_upload_sessions_used(1)

    def test_decrease_upload_sessions_used_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.decrease_active_upload_sessions_used(-1)

    def test_set_upload_sessions_used_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.set_active_upload_sessions_used(-1)

    def test_set_upload_sessions_used_above_limit_raises(self) -> None:
        q = make_quota(active_upload_sessions_limit=3)
        with pytest.raises(ValueError):
            q.set_active_upload_sessions_used(10)


class TestUserQuotaUpdateLimitsErrors:
    def test_update_storage_limit_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.update_limits(storage_limit_bytes=-1)

    def test_update_storage_limit_below_usage_raises(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=500)
        with pytest.raises(ValueError):
            q.update_limits(storage_limit_bytes=100)

    def test_update_max_file_size_negative_raises(self) -> None:
        q = make_quota()
        with pytest.raises(ValueError):
            q.update_limits(max_file_size_bytes=-1)

    def test_update_max_file_size_sets_value(self) -> None:
        q = make_quota()
        q.update_limits(max_file_size_bytes=12345)
        assert q.max_file_size_bytes == 12345

    def test_update_files_limit_below_usage_raises(self) -> None:
        q = make_quota(files_limit=10, files_used=8)
        with pytest.raises(ValueError):
            q.update_limits(files_limit=5)

    def test_update_public_links_limit_below_usage_raises(self) -> None:
        q = make_quota(public_links_limit=10, public_links_used=8)
        with pytest.raises(ValueError):
            q.update_limits(public_links_limit=5)

    def test_update_upload_sessions_limit_below_usage_raises(self) -> None:
        q = make_quota(
            active_upload_sessions_limit=10, active_upload_sessions_used=8
        )
        with pytest.raises(ValueError):
            q.update_limits(active_upload_sessions_limit=5)


class TestUserQuotaRepr:
    def test_repr_returns_string(self) -> None:
        q = make_quota()
        result = repr(q)
        assert isinstance(result, str)
        assert len(result) > 0
