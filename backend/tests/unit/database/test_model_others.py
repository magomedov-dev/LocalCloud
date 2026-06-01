"""Модульные тесты моделей UserQuota, UploadSession, UploadPart,
RegistrationRequest, NodePermission и PublicLink.

Все экземпляры создаются через ``model_construct``, поэтому сессия БД не требуется.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from database.models.enums import (
    PermissionLevel,
    PermissionSubjectType,
    PublicLinkPermissionType,
    PublicLinkStatus,
    RegistrationRequestStatus,
    UploadPartStatus,
    UploadSessionStatus,
)
from database.models.links import PublicLink
from database.models.permissions import NodePermission
from database.models.quotas import UserQuota
from database.models.registration import RegistrationRequest
from database.models.uploads import UploadPart, UploadSession


# ===========================================================================
# UserQuota
# ===========================================================================

def make_quota(**kwargs: object) -> UserQuota:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        storage_limit_bytes=10 * 1024 * 1024 * 1024,  # 10 GB
        storage_used_bytes=0,
        max_file_size_bytes=1024 * 1024 * 1024,  # 1 GB
        files_limit=None,
        files_used=0,
        public_links_limit=100,
        public_links_used=0,
        active_upload_sessions_limit=10,
        active_upload_sessions_used=0,
    )
    defaults.update(kwargs)
    return UserQuota(**defaults)


class TestUserQuotaAvailableStorageBytes:
    def test_unused_quota_is_full_limit(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=0)
        assert q.available_storage_bytes == 1000

    def test_partially_used_quota(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=300)
        assert q.available_storage_bytes == 700

    def test_fully_used_quota_returns_zero(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=1000)
        assert q.available_storage_bytes == 0


class TestUserQuotaIsStorageFull:
    def test_used_equals_limit_is_full(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=1000)
        assert q.is_storage_full is True

    def test_used_less_than_limit_not_full(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=999)
        assert q.is_storage_full is False


class TestUserQuotaUsagePercent:
    def test_no_usage_is_zero_percent(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=0)
        assert q.usage_percent == 0.0

    def test_half_used_is_50_percent(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=500)
        assert q.usage_percent == pytest.approx(50.0)

    def test_full_usage_is_100_percent(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=1000)
        assert q.usage_percent == 100.0

    def test_zero_limit_with_usage_is_100(self) -> None:
        q = make_quota(storage_limit_bytes=0, storage_used_bytes=1)
        assert q.usage_percent == 100.0

    def test_zero_limit_without_usage_is_zero(self) -> None:
        q = make_quota(storage_limit_bytes=0, storage_used_bytes=0)
        assert q.usage_percent == 0.0


class TestUserQuotaCanStoreFileSize:
    def test_small_file_fits(self) -> None:
        q = make_quota(
            storage_limit_bytes=1000,
            storage_used_bytes=0,
            max_file_size_bytes=500,
            files_limit=None,
        )
        assert q.can_store_file_size(100) is True

    def test_file_too_large_for_max_size(self) -> None:
        q = make_quota(
            storage_limit_bytes=1000,
            storage_used_bytes=0,
            max_file_size_bytes=50,
        )
        assert q.can_store_file_size(100) is False

    def test_file_too_large_for_available_space(self) -> None:
        q = make_quota(
            storage_limit_bytes=1000,
            storage_used_bytes=950,
            max_file_size_bytes=500,
        )
        assert q.can_store_file_size(100) is False

    def test_files_limit_reached_returns_false(self) -> None:
        q = make_quota(
            storage_limit_bytes=10000,
            storage_used_bytes=0,
            max_file_size_bytes=5000,
            files_limit=5,
            files_used=5,
        )
        assert q.can_store_file_size(100) is False


class TestUserQuotaHasLimits:
    def test_has_files_limit_when_set(self) -> None:
        q = make_quota(files_limit=10)
        assert q.has_files_limit is True

    def test_no_files_limit_when_none(self) -> None:
        q = make_quota(files_limit=None)
        assert q.has_files_limit is False

    def test_has_public_links_limit(self) -> None:
        q = make_quota(public_links_limit=100)
        assert q.has_public_links_limit is True

    def test_has_upload_sessions_limit(self) -> None:
        q = make_quota(active_upload_sessions_limit=10)
        assert q.has_active_upload_sessions_limit is True


class TestUserQuotaLimitReached:
    def test_files_limit_reached(self) -> None:
        q = make_quota(files_limit=5, files_used=5)
        assert q.is_files_limit_reached is True

    def test_files_limit_not_reached(self) -> None:
        q = make_quota(files_limit=5, files_used=3)
        assert q.is_files_limit_reached is False

    def test_public_links_limit_reached(self) -> None:
        q = make_quota(public_links_limit=10, public_links_used=10)
        assert q.is_public_links_limit_reached is True

    def test_upload_sessions_limit_reached(self) -> None:
        q = make_quota(active_upload_sessions_limit=5, active_upload_sessions_used=5)
        assert q.is_active_upload_sessions_limit_reached is True


class TestUserQuotaIncreaseDecreaseStorage:
    def test_increase_storage_usage(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=100)
        q.increase_storage_usage(200)
        assert q.storage_used_bytes == 300

    def test_increase_beyond_limit_raises(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=900)
        with pytest.raises(ValueError):
            q.increase_storage_usage(200)

    def test_negative_increase_raises(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=100)
        with pytest.raises(ValueError):
            q.increase_storage_usage(-1)

    def test_decrease_storage_usage(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=300)
        q.decrease_storage_usage(100)
        assert q.storage_used_bytes == 200

    def test_decrease_below_zero_clamps_to_zero(self) -> None:
        q = make_quota(storage_limit_bytes=1000, storage_used_bytes=50)
        q.decrease_storage_usage(200)
        assert q.storage_used_bytes == 0


class TestUserQuotaRepr:
    def test_repr_non_empty(self) -> None:
        q = make_quota()
        assert isinstance(repr(q), str) and len(repr(q)) > 0


# ===========================================================================
# UploadSession
# ===========================================================================

def make_upload_session(**kwargs: object) -> UploadSession:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        parent_node_id=uuid.uuid4(),
        file_name="upload.bin",
        file_size_bytes=5 * 1024 * 1024,
        part_size_bytes=5 * 1024 * 1024,
        mime_type="application/octet-stream",
        checksum=None,
        checksum_algorithm=None,
        storage_bucket="my-bucket",
        storage_key="uploads/upload.bin",
        upload_id="s3-upload-id-123",
        status=UploadSessionStatus.CREATED,
        parts_count=3,
        uploaded_parts_count=0,
        uploaded_bytes=0,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        completed_at=None,
        aborted_at=None,
        failed_at=None,
        failure_reason=None,
        client_ip=None,
        user_agent=None,
        parts=[],
    )
    defaults.update(kwargs)
    return UploadSession(**defaults)


class TestUploadSessionStatusProperties:
    def test_is_created(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.CREATED)
        assert s.is_created is True
        assert s.is_uploading is False

    def test_is_uploading(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.UPLOADING)
        assert s.is_uploading is True
        assert s.is_created is False

    def test_is_completed(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.COMPLETED)
        assert s.is_completed is True

    def test_is_failed(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.FAILED)
        assert s.is_failed is True

    def test_is_aborted(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.ABORTED)
        assert s.is_aborted is True

    def test_is_expired(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.EXPIRED)
        assert s.is_expired is True


class TestUploadSessionIsFinished:
    def test_completed_is_finished(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.COMPLETED)
        assert s.is_finished is True

    def test_failed_is_finished(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.FAILED)
        assert s.is_finished is True

    def test_aborted_is_finished(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.ABORTED)
        assert s.is_finished is True

    def test_expired_is_finished(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.EXPIRED)
        assert s.is_finished is True

    def test_created_not_finished(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.CREATED)
        assert s.is_finished is False

    def test_uploading_not_finished(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.UPLOADING)
        assert s.is_finished is False


class TestUploadSessionIsExpiredAt:
    def test_expires_at_in_past_returns_true(self) -> None:
        s = make_upload_session(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        assert s.is_expired_at(datetime.now(UTC)) is True

    def test_expires_at_in_future_returns_false(self) -> None:
        s = make_upload_session(expires_at=datetime.now(UTC) + timedelta(hours=1))
        assert s.is_expired_at(datetime.now(UTC)) is False


class TestUploadSessionProgressPercent:
    def test_zero_uploaded_is_zero_percent(self) -> None:
        s = make_upload_session(parts_count=4, uploaded_parts_count=0)
        assert s.progress_percent == 0.0

    def test_all_uploaded_is_100_percent(self) -> None:
        s = make_upload_session(parts_count=4, uploaded_parts_count=4)
        assert s.progress_percent == 100.0

    def test_half_uploaded_is_50_percent(self) -> None:
        s = make_upload_session(parts_count=4, uploaded_parts_count=2)
        assert s.progress_percent == pytest.approx(50.0)


class TestUploadSessionAllPartsUploaded:
    def test_all_parts_uploaded_returns_true(self) -> None:
        s = make_upload_session(parts_count=3, uploaded_parts_count=3)
        assert s.all_parts_uploaded is True

    def test_partial_upload_returns_false(self) -> None:
        s = make_upload_session(parts_count=3, uploaded_parts_count=2)
        assert s.all_parts_uploaded is False


class TestUploadSessionComplete:
    def test_sets_status_completed(self) -> None:
        s = make_upload_session()
        s.complete()
        assert s.status == UploadSessionStatus.COMPLETED

    def test_sets_completed_at(self) -> None:
        s = make_upload_session(completed_at=None)
        s.complete()
        assert s.completed_at is not None

    def test_clears_failure_reason(self) -> None:
        s = make_upload_session(failure_reason="old reason")
        s.complete()
        assert s.failure_reason is None


class TestUploadSessionFail:
    def test_sets_status_failed(self) -> None:
        s = make_upload_session()
        s.fail()
        assert s.status == UploadSessionStatus.FAILED

    def test_sets_failed_at(self) -> None:
        s = make_upload_session(failed_at=None)
        s.fail()
        assert s.failed_at is not None

    def test_stores_failure_reason(self) -> None:
        s = make_upload_session()
        s.fail(reason="network error")
        assert s.failure_reason == "network error"


class TestUploadSessionAbort:
    def test_sets_status_aborted(self) -> None:
        s = make_upload_session()
        s.abort()
        assert s.status == UploadSessionStatus.ABORTED

    def test_sets_aborted_at(self) -> None:
        s = make_upload_session(aborted_at=None)
        s.abort()
        assert s.aborted_at is not None


class TestUploadSessionProgressZeroParts:
    def test_zero_parts_count_returns_zero(self) -> None:
        s = make_upload_session(parts_count=0, uploaded_parts_count=0)
        assert s.progress_percent == 0.0


class TestUploadSessionCanReceivePartsAt:
    def test_created_session_can_receive(self) -> None:
        s = make_upload_session(
            status=UploadSessionStatus.CREATED,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert s.can_receive_parts_at(datetime.now(UTC)) is True

    def test_uploading_session_can_receive(self) -> None:
        s = make_upload_session(
            status=UploadSessionStatus.UPLOADING,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert s.can_receive_parts_at(datetime.now(UTC)) is True

    def test_finished_session_cannot_receive(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.COMPLETED)
        assert s.can_receive_parts_at(datetime.now(UTC)) is False

    def test_expired_session_cannot_receive(self) -> None:
        s = make_upload_session(
            status=UploadSessionStatus.CREATED,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        assert s.can_receive_parts_at(datetime.now(UTC)) is False


class TestUploadSessionCanBeCompletedAt:
    def test_all_parts_uploaded_can_complete(self) -> None:
        s = make_upload_session(
            status=UploadSessionStatus.UPLOADING,
            parts_count=2,
            uploaded_parts_count=2,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert s.can_be_completed_at(datetime.now(UTC)) is True

    def test_partial_upload_cannot_complete(self) -> None:
        s = make_upload_session(
            status=UploadSessionStatus.UPLOADING,
            parts_count=2,
            uploaded_parts_count=1,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert s.can_be_completed_at(datetime.now(UTC)) is False


class TestUploadSessionCanBeAbortedAt:
    def test_active_session_can_be_aborted(self) -> None:
        s = make_upload_session(
            status=UploadSessionStatus.UPLOADING,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert s.can_be_aborted_at(datetime.now(UTC)) is True

    def test_finished_session_cannot_be_aborted(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.COMPLETED)
        assert s.can_be_aborted_at(datetime.now(UTC)) is False


class TestUploadSessionMarkUploading:
    def test_created_transitions_to_uploading(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.CREATED)
        s.mark_uploading()
        assert s.status == UploadSessionStatus.UPLOADING

    def test_already_uploading_unchanged(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.UPLOADING)
        s.mark_uploading()
        assert s.status == UploadSessionStatus.UPLOADING


class TestUploadSessionRegisterUploadedPart:
    def test_increments_counts(self) -> None:
        s = make_upload_session(
            status=UploadSessionStatus.UPLOADING,
            parts_count=3,
            uploaded_parts_count=0,
            uploaded_bytes=0,
            file_size_bytes=300,
        )
        s.register_uploaded_part(100)
        assert s.uploaded_parts_count == 1
        assert s.uploaded_bytes == 100

    def test_created_session_transitions_to_uploading(self) -> None:
        s = make_upload_session(
            status=UploadSessionStatus.CREATED,
            parts_count=3,
            uploaded_parts_count=0,
            uploaded_bytes=0,
            file_size_bytes=300,
        )
        s.register_uploaded_part(50)
        assert s.status == UploadSessionStatus.UPLOADING

    def test_uploaded_bytes_clamped_to_file_size(self) -> None:
        s = make_upload_session(
            status=UploadSessionStatus.UPLOADING,
            parts_count=1,
            uploaded_parts_count=0,
            uploaded_bytes=0,
            file_size_bytes=100,
        )
        s.register_uploaded_part(500)
        assert s.uploaded_bytes == 100

    def test_negative_size_raises(self) -> None:
        s = make_upload_session(parts_count=3, uploaded_parts_count=0)
        with pytest.raises(ValueError):
            s.register_uploaded_part(-1)

    def test_all_parts_registered_raises(self) -> None:
        s = make_upload_session(parts_count=2, uploaded_parts_count=2)
        with pytest.raises(ValueError):
            s.register_uploaded_part(10)


class TestUploadSessionUnregisterUploadedPart:
    def test_decrements_counts(self) -> None:
        s = make_upload_session(
            parts_count=3,
            uploaded_parts_count=2,
            uploaded_bytes=200,
        )
        s.unregister_uploaded_part(100)
        assert s.uploaded_parts_count == 1
        assert s.uploaded_bytes == 100

    def test_counts_clamped_to_zero(self) -> None:
        s = make_upload_session(
            parts_count=3,
            uploaded_parts_count=0,
            uploaded_bytes=0,
        )
        s.unregister_uploaded_part(50)
        assert s.uploaded_parts_count == 0
        assert s.uploaded_bytes == 0

    def test_negative_size_raises(self) -> None:
        s = make_upload_session(uploaded_parts_count=1, uploaded_bytes=10)
        with pytest.raises(ValueError):
            s.unregister_uploaded_part(-1)


class TestUploadSessionExpire:
    def test_sets_status_expired(self) -> None:
        s = make_upload_session(status=UploadSessionStatus.UPLOADING)
        s.expire()
        assert s.status == UploadSessionStatus.EXPIRED

    def test_sets_aborted_at(self) -> None:
        moment = datetime(2025, 2, 1, tzinfo=UTC)
        s = make_upload_session(aborted_at=None)
        s.expire(expired_at=moment)
        assert s.aborted_at == moment

    def test_default_aborted_at_set(self) -> None:
        s = make_upload_session(aborted_at=None)
        s.expire()
        assert s.aborted_at is not None


class TestUploadSessionRecalculateProgressFromParts:
    def test_recalculates_from_uploaded_parts(self) -> None:
        parts = [
            make_upload_part(status=UploadPartStatus.UPLOADED, size_bytes=100),
            make_upload_part(status=UploadPartStatus.UPLOADED, size_bytes=150),
            make_upload_part(status=UploadPartStatus.PENDING, size_bytes=200),
        ]
        s = make_upload_session(
            parts=parts,
            uploaded_parts_count=0,
            uploaded_bytes=0,
        )
        s.recalculate_progress_from_parts()
        assert s.uploaded_parts_count == 2
        assert s.uploaded_bytes == 250


class TestUploadSessionRepr:
    def test_repr_non_empty(self) -> None:
        s = make_upload_session()
        assert isinstance(repr(s), str) and len(repr(s)) > 0


# ===========================================================================
# UploadPart
# ===========================================================================

def make_upload_part(**kwargs: object) -> UploadPart:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        upload_session_id=uuid.uuid4(),
        part_number=1,
        size_bytes=5 * 1024 * 1024,
        etag=None,
        checksum=None,
        status=UploadPartStatus.PENDING,
        uploaded_at=None,
        failed_at=None,
        failure_reason=None,
    )
    defaults.update(kwargs)
    return UploadPart(**defaults)


class TestUploadPartStatusProperties:
    def test_is_pending(self) -> None:
        part = make_upload_part(status=UploadPartStatus.PENDING)
        assert part.is_pending is True
        assert part.is_uploaded is False

    def test_is_uploaded(self) -> None:
        part = make_upload_part(status=UploadPartStatus.UPLOADED)
        assert part.is_uploaded is True
        assert part.is_pending is False

    def test_is_failed(self) -> None:
        part = make_upload_part(status=UploadPartStatus.FAILED)
        assert part.is_failed is True


class TestUploadPartMarkUploaded:
    def test_sets_status_to_uploaded(self) -> None:
        part = make_upload_part(status=UploadPartStatus.PENDING)
        part.mark_uploaded(etag="abc123-etag")
        assert part.status == UploadPartStatus.UPLOADED

    def test_stores_etag(self) -> None:
        part = make_upload_part()
        part.mark_uploaded(etag="abc123-etag")
        assert part.etag == "abc123-etag"

    def test_sets_uploaded_at(self) -> None:
        part = make_upload_part(uploaded_at=None)
        part.mark_uploaded(etag="abc123-etag")
        assert part.uploaded_at is not None

    def test_stores_checksum(self) -> None:
        part = make_upload_part()
        part.mark_uploaded(etag="abc", checksum="sha256:xyz")
        assert part.checksum == "sha256:xyz"

    def test_empty_etag_raises(self) -> None:
        part = make_upload_part()
        with pytest.raises(ValueError):
            part.mark_uploaded(etag="")

    def test_clears_failed_at(self) -> None:
        part = make_upload_part(failed_at=datetime.now(UTC))
        part.mark_uploaded(etag="abc")
        assert part.failed_at is None


class TestUploadPartMarkFailed:
    def test_sets_status_to_failed(self) -> None:
        part = make_upload_part(status=UploadPartStatus.PENDING)
        part.mark_failed()
        assert part.status == UploadPartStatus.FAILED

    def test_sets_failed_at(self) -> None:
        part = make_upload_part(failed_at=None)
        part.mark_failed()
        assert part.failed_at is not None

    def test_stores_reason(self) -> None:
        part = make_upload_part()
        part.mark_failed(reason="timeout")
        assert part.failure_reason == "timeout"


class TestUploadPartReset:
    def test_sets_status_to_pending(self) -> None:
        part = make_upload_part(status=UploadPartStatus.UPLOADED)
        part.reset()
        assert part.status == UploadPartStatus.PENDING

    def test_clears_etag(self) -> None:
        part = make_upload_part(etag="old-etag")
        part.reset()
        assert part.etag is None

    def test_clears_uploaded_at(self) -> None:
        part = make_upload_part(uploaded_at=datetime.now(UTC))
        part.reset()
        assert part.uploaded_at is None


class TestUploadPartRepr:
    def test_repr_non_empty(self) -> None:
        part = make_upload_part()
        assert isinstance(repr(part), str) and len(repr(part)) > 0


class TestUploadPartCreatePending:
    def test_creates_pending_part(self) -> None:
        session_id = uuid.uuid4()
        part = UploadPart.create_pending(
            upload_session_id=session_id,
            part_number=1,
            size_bytes=1024,
        )
        assert part.upload_session_id == session_id
        assert part.part_number == 1
        assert part.size_bytes == 1024
        assert part.status == UploadPartStatus.PENDING


# ===========================================================================
# RegistrationRequest
# ===========================================================================

def make_reg_request(**kwargs: object) -> RegistrationRequest:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        email="applicant@example.com",
        username="applicant",
        password_hash="hashed_pw",
        status=RegistrationRequestStatus.PENDING,
        comment=None,
        rejection_reason=None,
        reviewed_at=None,
        reviewed_by=None,
        created_user_id=None,
    )
    defaults.update(kwargs)
    return RegistrationRequest(**defaults)


class TestRegistrationRequestStatusProperties:
    def test_is_pending(self) -> None:
        r = make_reg_request(status=RegistrationRequestStatus.PENDING)
        assert r.is_pending is True

    def test_is_approved(self) -> None:
        r = make_reg_request(status=RegistrationRequestStatus.APPROVED)
        assert r.is_approved is True

    def test_is_rejected(self) -> None:
        r = make_reg_request(status=RegistrationRequestStatus.REJECTED)
        assert r.is_rejected is True

    def test_is_cancelled(self) -> None:
        r = make_reg_request(status=RegistrationRequestStatus.CANCELLED)
        assert r.is_cancelled is True

    def test_pending_not_approved(self) -> None:
        r = make_reg_request(status=RegistrationRequestStatus.PENDING)
        assert r.is_approved is False


class TestRegistrationRequestIsReviewed:
    def test_reviewed_at_set_returns_true(self) -> None:
        r = make_reg_request(reviewed_at=datetime.now(UTC))
        assert r.is_reviewed is True

    def test_reviewed_at_none_returns_false(self) -> None:
        r = make_reg_request(reviewed_at=None)
        assert r.is_reviewed is False


class TestRegistrationRequestCanBeReviewed:
    def test_pending_can_be_reviewed(self) -> None:
        r = make_reg_request(status=RegistrationRequestStatus.PENDING)
        assert r.can_be_reviewed is True

    def test_approved_cannot_be_reviewed(self) -> None:
        r = make_reg_request(status=RegistrationRequestStatus.APPROVED)
        assert r.can_be_reviewed is False


class TestRegistrationRequestApprove:
    def test_sets_status_to_approved(self) -> None:
        reviewer_id = uuid.uuid4()
        created_user_id = uuid.uuid4()
        r = make_reg_request()
        r.approve(reviewer_id=reviewer_id, created_user_id=created_user_id)
        assert r.status == RegistrationRequestStatus.APPROVED

    def test_stores_reviewer_id(self) -> None:
        reviewer_id = uuid.uuid4()
        r = make_reg_request()
        r.approve(reviewer_id=reviewer_id, created_user_id=uuid.uuid4())
        assert r.reviewed_by == reviewer_id

    def test_stores_created_user_id(self) -> None:
        created_user_id = uuid.uuid4()
        r = make_reg_request()
        r.approve(reviewer_id=uuid.uuid4(), created_user_id=created_user_id)
        assert r.created_user_id == created_user_id

    def test_sets_reviewed_at(self) -> None:
        r = make_reg_request(reviewed_at=None)
        r.approve(reviewer_id=uuid.uuid4(), created_user_id=uuid.uuid4())
        assert r.reviewed_at is not None

    def test_clears_rejection_reason(self) -> None:
        r = make_reg_request(rejection_reason="old reason")
        r.approve(reviewer_id=uuid.uuid4(), created_user_id=uuid.uuid4())
        assert r.rejection_reason is None


class TestRegistrationRequestReject:
    def test_sets_status_to_rejected(self) -> None:
        r = make_reg_request()
        r.reject(reviewer_id=uuid.uuid4())
        assert r.status == RegistrationRequestStatus.REJECTED

    def test_stores_rejection_reason(self) -> None:
        r = make_reg_request()
        r.reject(reviewer_id=uuid.uuid4(), reason="spam")
        assert r.rejection_reason == "spam"

    def test_sets_reviewed_at(self) -> None:
        r = make_reg_request(reviewed_at=None)
        r.reject(reviewer_id=uuid.uuid4())
        assert r.reviewed_at is not None

    def test_clears_created_user_id(self) -> None:
        r = make_reg_request(created_user_id=uuid.uuid4())
        r.reject(reviewer_id=uuid.uuid4())
        assert r.created_user_id is None


class TestRegistrationRequestCancel:
    def test_sets_status_to_cancelled(self) -> None:
        r = make_reg_request()
        r.cancel()
        assert r.status == RegistrationRequestStatus.CANCELLED

    def test_stores_comment(self) -> None:
        r = make_reg_request()
        r.cancel(comment="user withdrew")
        assert r.comment == "user withdrew"

    def test_sets_reviewed_at(self) -> None:
        r = make_reg_request(reviewed_at=None)
        r.cancel()
        assert r.reviewed_at is not None


class TestRegistrationRequestResetToPending:
    def test_sets_status_to_pending(self) -> None:
        r = make_reg_request(status=RegistrationRequestStatus.REJECTED)
        r.reset_to_pending()
        assert r.status == RegistrationRequestStatus.PENDING

    def test_clears_reviewed_by(self) -> None:
        r = make_reg_request(reviewed_by=uuid.uuid4())
        r.reset_to_pending()
        assert r.reviewed_by is None

    def test_clears_reviewed_at(self) -> None:
        r = make_reg_request(reviewed_at=datetime.now(UTC))
        r.reset_to_pending()
        assert r.reviewed_at is None


class TestRegistrationRequestRepr:
    def test_repr_non_empty(self) -> None:
        r = make_reg_request()
        assert isinstance(repr(r), str) and len(repr(r)) > 0


# ===========================================================================
# NodePermission
# ===========================================================================

def make_permission(**kwargs: object) -> NodePermission:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        subject_type=PermissionSubjectType.USER,
        permission_level=PermissionLevel.READ,
        granted_by=None,
        can_read=True,
        can_download=False,
        can_write=False,
        can_delete=False,
        can_share=False,
        expires_at=None,
        revoked_at=None,
        revoke_reason=None,
    )
    defaults.update(kwargs)
    return NodePermission(**defaults)


class TestNodePermissionIsRevoked:
    def test_revoked_at_set_returns_true(self) -> None:
        p = make_permission(revoked_at=datetime.now(UTC))
        assert p.is_revoked is True

    def test_revoked_at_none_returns_false(self) -> None:
        p = make_permission(revoked_at=None)
        assert p.is_revoked is False


class TestNodePermissionHasAnyPermission:
    def test_can_read_true_returns_true(self) -> None:
        p = make_permission(can_read=True)
        assert p.has_any_permission is True

    def test_all_false_returns_false(self) -> None:
        p = make_permission(
            can_read=False,
            can_download=False,
            can_write=False,
            can_delete=False,
            can_share=False,
        )
        assert p.has_any_permission is False


class TestNodePermissionIsReadOnly:
    def test_only_read_enabled_is_read_only(self) -> None:
        p = make_permission(
            can_read=True,
            can_download=False,
            can_write=False,
            can_delete=False,
            can_share=False,
        )
        assert p.is_read_only is True

    def test_read_and_download_not_read_only(self) -> None:
        p = make_permission(can_read=True, can_download=True)
        assert p.is_read_only is False


class TestNodePermissionIsOwnerLike:
    def test_all_flags_true_is_owner_like(self) -> None:
        p = make_permission(
            can_read=True,
            can_download=True,
            can_write=True,
            can_delete=True,
            can_share=True,
        )
        assert p.is_owner_like is True

    def test_missing_one_flag_not_owner_like(self) -> None:
        p = make_permission(
            can_read=True,
            can_download=True,
            can_write=True,
            can_delete=True,
            can_share=False,
        )
        assert p.is_owner_like is False


class TestNodePermissionIsExpiredAt:
    def test_expires_at_in_past_returns_true(self) -> None:
        p = make_permission(expires_at=datetime.now(UTC) - timedelta(hours=1))
        assert p.is_expired_at(datetime.now(UTC)) is True

    def test_expires_at_in_future_returns_false(self) -> None:
        p = make_permission(expires_at=datetime.now(UTC) + timedelta(hours=1))
        assert p.is_expired_at(datetime.now(UTC)) is False

    def test_expires_at_none_returns_false(self) -> None:
        p = make_permission(expires_at=None)
        assert p.is_expired_at(datetime.now(UTC)) is False


class TestNodePermissionIsActiveAt:
    def test_active_permission_returns_true(self) -> None:
        p = make_permission(
            revoked_at=None,
            expires_at=None,
            can_read=True,
        )
        assert p.is_active_at(datetime.now(UTC)) is True

    def test_revoked_permission_returns_false(self) -> None:
        p = make_permission(revoked_at=datetime.now(UTC) - timedelta(minutes=1))
        assert p.is_active_at(datetime.now(UTC)) is False

    def test_expired_permission_returns_false(self) -> None:
        p = make_permission(expires_at=datetime.now(UTC) - timedelta(hours=1))
        assert p.is_active_at(datetime.now(UTC)) is False

    def test_no_flags_set_returns_false(self) -> None:
        p = make_permission(
            can_read=False,
            can_download=False,
            can_write=False,
            can_delete=False,
            can_share=False,
            revoked_at=None,
            expires_at=None,
        )
        assert p.is_active_at(datetime.now(UTC)) is False


class TestNodePermissionAllowsMethods:
    def _active_perm(self, **flags: bool) -> NodePermission:
        return make_permission(revoked_at=None, expires_at=None, **flags)

    def test_allows_read_at_when_can_read(self) -> None:
        p = self._active_perm(can_read=True)
        assert p.allows_read_at(datetime.now(UTC)) is True

    def test_allows_download_at_when_can_download(self) -> None:
        p = self._active_perm(can_read=True, can_download=True)
        assert p.allows_download_at(datetime.now(UTC)) is True

    def test_allows_write_at_when_can_write(self) -> None:
        p = self._active_perm(can_read=True, can_write=True)
        assert p.allows_write_at(datetime.now(UTC)) is True

    def test_allows_delete_at_when_can_delete(self) -> None:
        p = self._active_perm(can_read=True, can_delete=True)
        assert p.allows_delete_at(datetime.now(UTC)) is True

    def test_allows_share_at_when_can_share(self) -> None:
        p = self._active_perm(can_read=True, can_share=True)
        assert p.allows_share_at(datetime.now(UTC)) is True


class TestNodePermissionRevoke:
    def test_sets_revoked_at(self) -> None:
        p = make_permission(revoked_at=None)
        p.revoke()
        assert p.revoked_at is not None

    def test_stores_reason(self) -> None:
        p = make_permission()
        p.revoke(reason="policy violation")
        assert p.revoke_reason == "policy violation"

    def test_custom_revoked_at_stored(self) -> None:
        moment = datetime(2024, 4, 1, tzinfo=UTC)
        p = make_permission()
        p.revoke(revoked_at=moment)
        assert p.revoked_at == moment


class TestNodePermissionUpdatePermissions:
    def test_updates_provided_flags(self) -> None:
        p = make_permission(
            can_read=False,
            can_download=False,
            can_write=False,
            can_delete=False,
            can_share=False,
        )
        p.update_permissions(
            can_read=True,
            can_download=True,
            can_write=True,
            can_delete=True,
            can_share=True,
        )
        assert p.can_read is True
        assert p.can_download is True
        assert p.can_write is True
        assert p.can_delete is True
        assert p.can_share is True

    def test_none_flags_leave_values_unchanged(self) -> None:
        p = make_permission(
            can_read=True,
            can_download=True,
            can_write=True,
            can_delete=True,
            can_share=True,
        )
        p.update_permissions()
        assert p.can_read is True
        assert p.can_download is True
        assert p.can_write is True
        assert p.can_delete is True
        assert p.can_share is True

    def test_updates_permission_level(self) -> None:
        p = make_permission(permission_level=PermissionLevel.READ)
        p.update_permissions(permission_level=PermissionLevel.WRITE)
        assert p.permission_level == PermissionLevel.WRITE

    def test_expires_at_always_set(self) -> None:
        moment = datetime(2025, 1, 1, tzinfo=UTC)
        p = make_permission(expires_at=None)
        p.update_permissions(expires_at=moment)
        assert p.expires_at == moment

    def test_expires_at_reset_to_none(self) -> None:
        p = make_permission(expires_at=datetime.now(UTC))
        p.update_permissions()
        assert p.expires_at is None


class TestNodePermissionSyncLevelFromFlags:
    def _perm(self, **flags: bool) -> NodePermission:
        base = dict(
            can_read=False,
            can_download=False,
            can_write=False,
            can_delete=False,
            can_share=False,
        )
        base.update(flags)
        return make_permission(**base)

    def test_owner_like_maps_to_owner(self) -> None:
        p = self._perm(
            can_read=True,
            can_download=True,
            can_write=True,
            can_delete=True,
            can_share=True,
        )
        p.sync_permission_level_from_flags()
        assert p.permission_level == PermissionLevel.OWNER

    def test_read_only_maps_to_read(self) -> None:
        p = self._perm(can_read=True)
        p.sync_permission_level_from_flags()
        assert p.permission_level == PermissionLevel.READ

    def test_read_download_maps_to_download(self) -> None:
        p = self._perm(can_read=True, can_download=True)
        p.sync_permission_level_from_flags()
        assert p.permission_level == PermissionLevel.DOWNLOAD

    def test_read_download_write_maps_to_write(self) -> None:
        p = self._perm(can_read=True, can_download=True, can_write=True)
        p.sync_permission_level_from_flags()
        assert p.permission_level == PermissionLevel.WRITE

    def test_read_download_write_delete_maps_to_delete(self) -> None:
        p = self._perm(
            can_read=True,
            can_download=True,
            can_write=True,
            can_delete=True,
        )
        p.sync_permission_level_from_flags()
        assert p.permission_level == PermissionLevel.DELETE

    def test_unmatched_combination_falls_back_to_read(self) -> None:
        # can_write установлен, а can_download нет -> ни одна из именованных веток не совпадает
        p = self._perm(can_read=True, can_write=True)
        p.sync_permission_level_from_flags()
        assert p.permission_level == PermissionLevel.READ

    def test_no_flags_falls_back_to_read(self) -> None:
        p = self._perm()
        p.sync_permission_level_from_flags()
        assert p.permission_level == PermissionLevel.READ


class TestNodePermissionRepr:
    def test_repr_non_empty(self) -> None:
        p = make_permission()
        assert isinstance(repr(p), str) and len(repr(p)) > 0


# ===========================================================================
# PublicLink
# ===========================================================================

def make_public_link(**kwargs: object) -> PublicLink:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        token="abc123token",
        password_hash=None,
        permission_type=PublicLinkPermissionType.DOWNLOAD,
        status=PublicLinkStatus.ACTIVE,
        expires_at=None,
        max_downloads=None,
        download_count=0,
        view_count=0,
        upload_count=0,
        is_active=True,
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
        last_accessed_at=None,
        last_downloaded_at=None,
        last_uploaded_at=None,
        description=None,
    )
    defaults.update(kwargs)
    return PublicLink(**defaults)


class TestPublicLinkIsActive:
    def test_active_status_and_flag_true(self) -> None:
        link = make_public_link(status=PublicLinkStatus.ACTIVE, is_active=True)
        assert link.is_active is True

    def test_is_active_flag_false(self) -> None:
        link = make_public_link(is_active=False)
        assert link.is_active is False


class TestPublicLinkIsRevoked:
    def test_revoked_at_set_returns_true(self) -> None:
        link = make_public_link(revoked_at=datetime.now(UTC))
        assert link.is_revoked is True

    def test_revoked_status_returns_true(self) -> None:
        link = make_public_link(status=PublicLinkStatus.REVOKED, revoked_at=None)
        assert link.is_revoked is True

    def test_active_link_not_revoked(self) -> None:
        link = make_public_link(status=PublicLinkStatus.ACTIVE, revoked_at=None)
        assert link.is_revoked is False


class TestPublicLinkIsDisabled:
    def test_disabled_status_returns_true(self) -> None:
        link = make_public_link(status=PublicLinkStatus.DISABLED)
        assert link.is_disabled is True

    def test_is_active_false_returns_true(self) -> None:
        link = make_public_link(status=PublicLinkStatus.ACTIVE, is_active=False)
        assert link.is_disabled is True

    def test_active_link_not_disabled(self) -> None:
        link = make_public_link(status=PublicLinkStatus.ACTIVE, is_active=True)
        assert link.is_disabled is False


class TestPublicLinkIsPasswordProtected:
    def test_password_hash_set_returns_true(self) -> None:
        link = make_public_link(password_hash="hashed")
        assert link.is_password_protected is True

    def test_password_hash_none_returns_false(self) -> None:
        link = make_public_link(password_hash=None)
        assert link.is_password_protected is False


class TestPublicLinkHasDownloadLimit:
    def test_max_downloads_set_returns_true(self) -> None:
        link = make_public_link(max_downloads=10)
        assert link.has_download_limit is True

    def test_max_downloads_none_returns_false(self) -> None:
        link = make_public_link(max_downloads=None)
        assert link.has_download_limit is False


class TestPublicLinkIsDownloadLimitReached:
    def test_limit_reached(self) -> None:
        link = make_public_link(max_downloads=5, download_count=5)
        assert link.is_download_limit_reached is True

    def test_limit_not_reached(self) -> None:
        link = make_public_link(max_downloads=5, download_count=3)
        assert link.is_download_limit_reached is False

    def test_no_limit_never_reached(self) -> None:
        link = make_public_link(max_downloads=None, download_count=999)
        assert link.is_download_limit_reached is False


class TestPublicLinkAllowsPermissions:
    def test_download_allows_view_and_download(self) -> None:
        link = make_public_link(permission_type=PublicLinkPermissionType.DOWNLOAD)
        assert link.allows_view is True
        assert link.allows_download is True
        assert link.allows_upload is False

    def test_view_allows_view_only(self) -> None:
        link = make_public_link(permission_type=PublicLinkPermissionType.VIEW)
        assert link.allows_view is True
        assert link.allows_download is False
        assert link.allows_upload is False

    def test_upload_allows_upload_only(self) -> None:
        link = make_public_link(permission_type=PublicLinkPermissionType.UPLOAD)
        assert link.allows_view is False
        assert link.allows_download is False
        assert link.allows_upload is True


class TestPublicLinkIsExpiredAt:
    def test_expires_at_in_past_returns_true(self) -> None:
        link = make_public_link(expires_at=datetime.now(UTC) - timedelta(hours=1))
        assert link.is_expired_at(datetime.now(UTC)) is True

    def test_expires_at_in_future_returns_false(self) -> None:
        link = make_public_link(expires_at=datetime.now(UTC) + timedelta(hours=1))
        assert link.is_expired_at(datetime.now(UTC)) is False

    def test_no_expiration_returns_false(self) -> None:
        link = make_public_link(expires_at=None)
        assert link.is_expired_at(datetime.now(UTC)) is False


class TestPublicLinkIsAvailableAt:
    def test_active_non_expired_link_is_available(self) -> None:
        link = make_public_link(
            status=PublicLinkStatus.ACTIVE,
            is_active=True,
            revoked_at=None,
            expires_at=None,
            max_downloads=None,
            download_count=0,
        )
        assert link.is_available_at(datetime.now(UTC)) is True

    def test_inactive_link_not_available(self) -> None:
        link = make_public_link(is_active=False)
        assert link.is_available_at(datetime.now(UTC)) is False

    def test_revoked_link_not_available(self) -> None:
        link = make_public_link(revoked_at=datetime.now(UTC) - timedelta(minutes=1))
        assert link.is_available_at(datetime.now(UTC)) is False

    def test_expired_link_not_available(self) -> None:
        link = make_public_link(expires_at=datetime.now(UTC) - timedelta(hours=1))
        assert link.is_available_at(datetime.now(UTC)) is False

    def test_download_limit_reached_not_available(self) -> None:
        link = make_public_link(max_downloads=5, download_count=5)
        assert link.is_available_at(datetime.now(UTC)) is False


class TestPublicLinkRevoke:
    def test_sets_status_to_revoked(self) -> None:
        link = make_public_link()
        link.revoke()
        assert link.status == PublicLinkStatus.REVOKED

    def test_sets_is_active_false(self) -> None:
        link = make_public_link(is_active=True)
        link.revoke()
        assert link.is_active is False

    def test_sets_revoked_at(self) -> None:
        link = make_public_link(revoked_at=None)
        link.revoke()
        assert link.revoked_at is not None

    def test_stores_reason(self) -> None:
        link = make_public_link()
        link.revoke(reason="abuse")
        assert link.revoke_reason == "abuse"

    def test_stores_revoked_by(self) -> None:
        admin_id = uuid.uuid4()
        link = make_public_link()
        link.revoke(revoked_by=admin_id)
        assert link.revoked_by == admin_id


class TestPublicLinkDisable:
    def test_sets_status_disabled(self) -> None:
        link = make_public_link()
        link.disable()
        assert link.status == PublicLinkStatus.DISABLED

    def test_sets_is_active_false(self) -> None:
        link = make_public_link(is_active=True)
        link.disable()
        assert link.is_active is False


class TestPublicLinkActivate:
    def test_sets_status_active(self) -> None:
        link = make_public_link(status=PublicLinkStatus.DISABLED, is_active=False)
        link.activate()
        assert link.status == PublicLinkStatus.ACTIVE

    def test_sets_is_active_true(self) -> None:
        link = make_public_link(status=PublicLinkStatus.DISABLED, is_active=False)
        link.activate()
        assert link.is_active is True

    def test_revoked_link_raises(self) -> None:
        link = make_public_link(status=PublicLinkStatus.REVOKED)
        with pytest.raises(ValueError):
            link.activate()


class TestPublicLinkMarkExpired:
    def test_sets_status_expired(self) -> None:
        link = make_public_link()
        link.mark_expired()
        assert link.status == PublicLinkStatus.EXPIRED

    def test_sets_is_active_false(self) -> None:
        link = make_public_link(is_active=True)
        link.mark_expired()
        assert link.is_active is False


class TestPublicLinkMarkAccessed:
    def test_increments_view_count(self) -> None:
        link = make_public_link(view_count=0)
        link.mark_accessed()
        assert link.view_count == 1

    def test_sets_last_accessed_at(self) -> None:
        link = make_public_link(last_accessed_at=None)
        link.mark_accessed()
        assert link.last_accessed_at is not None


class TestPublicLinkRegisterDownload:
    def test_increments_download_count(self) -> None:
        link = make_public_link(download_count=0, max_downloads=None)
        link.register_download()
        assert link.download_count == 1

    def test_sets_last_downloaded_at(self) -> None:
        link = make_public_link(last_downloaded_at=None, max_downloads=None)
        link.register_download()
        assert link.last_downloaded_at is not None

    def test_raises_when_limit_reached(self) -> None:
        link = make_public_link(max_downloads=3, download_count=3)
        with pytest.raises(ValueError):
            link.register_download()


class TestPublicLinkUpdateDownloadLimit:
    def test_sets_new_limit(self) -> None:
        link = make_public_link(max_downloads=5, download_count=2)
        link.update_download_limit(10)
        assert link.max_downloads == 10

    def test_set_to_none_removes_limit(self) -> None:
        link = make_public_link(max_downloads=5, download_count=0)
        link.update_download_limit(None)
        assert link.max_downloads is None

    def test_new_limit_below_current_downloads_raises(self) -> None:
        link = make_public_link(max_downloads=10, download_count=8)
        with pytest.raises(ValueError):
            link.update_download_limit(5)


class TestPublicLinkCanActionAt:
    def test_can_view_at_true(self) -> None:
        link = make_public_link(permission_type=PublicLinkPermissionType.VIEW)
        assert link.can_view_at(datetime.now(UTC)) is True

    def test_can_view_at_false_when_unavailable(self) -> None:
        link = make_public_link(
            permission_type=PublicLinkPermissionType.VIEW, is_active=False
        )
        assert link.can_view_at(datetime.now(UTC)) is False

    def test_can_download_at_true(self) -> None:
        link = make_public_link(permission_type=PublicLinkPermissionType.DOWNLOAD)
        assert link.can_download_at(datetime.now(UTC)) is True

    def test_can_download_at_false_when_view_only(self) -> None:
        link = make_public_link(permission_type=PublicLinkPermissionType.VIEW)
        assert link.can_download_at(datetime.now(UTC)) is False

    def test_can_upload_at_true(self) -> None:
        link = make_public_link(permission_type=PublicLinkPermissionType.UPLOAD)
        assert link.can_upload_at(datetime.now(UTC)) is True

    def test_can_upload_at_false_when_download(self) -> None:
        link = make_public_link(permission_type=PublicLinkPermissionType.DOWNLOAD)
        assert link.can_upload_at(datetime.now(UTC)) is False


class TestPublicLinkRegisterUpload:
    def test_increments_upload_count(self) -> None:
        link = make_public_link(upload_count=0)
        link.register_upload()
        assert link.upload_count == 1

    def test_sets_last_uploaded_and_accessed(self) -> None:
        when = datetime.now(UTC)
        link = make_public_link(last_uploaded_at=None, last_accessed_at=None)
        link.register_upload(uploaded_at=when)
        assert link.last_uploaded_at == when
        assert link.last_accessed_at == when


class TestPublicLinkUpdatePasswordHash:
    def test_sets_password_hash(self) -> None:
        link = make_public_link(password_hash=None)
        link.update_password_hash("newhash")
        assert link.password_hash == "newhash"

    def test_clears_password_hash(self) -> None:
        link = make_public_link(password_hash="old")
        link.update_password_hash(None)
        assert link.password_hash is None


class TestPublicLinkUpdateExpiration:
    def test_sets_expiration(self) -> None:
        when = datetime.now(UTC) + timedelta(days=1)
        link = make_public_link(expires_at=None)
        link.update_expiration(when)
        assert link.expires_at == when

    def test_clears_expiration(self) -> None:
        link = make_public_link(expires_at=datetime.now(UTC))
        link.update_expiration(None)
        assert link.expires_at is None


class TestPublicLinkRepr:
    def test_repr_non_empty(self) -> None:
        link = make_public_link()
        assert isinstance(repr(link), str) and len(repr(link)) > 0

    def test_repr_contains_class_name(self) -> None:
        link = make_public_link()
        assert "PublicLink" in repr(link)
