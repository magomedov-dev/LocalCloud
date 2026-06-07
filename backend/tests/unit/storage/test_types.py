"""Unit-тесты для Pydantic-моделей и перечислений модуля storage."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from storage.types import (
    StorageBucketInfo,
    StorageChecksumAlgorithm,
    StorageCompleteMultipartUploadRequest,
    StorageCopyResult,
    StorageDeleteResult,
    StorageDownloadResult,
    StorageHealthState,
    StorageHealthStatus,
    StorageIntegrityProblemType,
    StorageIntegrityReport,
    StorageIntegrityStatus,
    StorageMultipartUpload,
    StorageMultipartUploadStatus,
    StorageObjectDeleteResult,
    StorageObjectInfo,
    StorageObjectMetadata,
    StorageObjectStatus,
    StorageObjectVisibility,
    StoragePresignedUploadPartUrl,
    StoragePresignedUrl,
    StoragePresignedUrlMethod,
    StoragePutObjectRequest,
    StorageUploadPart,
)
from storage.exceptions import StorageObjectError


# ---------------------------------------------------------------------------
# Значения StrEnum
# ---------------------------------------------------------------------------


class TestStorageChecksumAlgorithm:
    def test_md5(self) -> None:
        assert StorageChecksumAlgorithm.MD5 == "md5"

    def test_sha1(self) -> None:
        assert StorageChecksumAlgorithm.SHA1 == "sha1"

    def test_sha256(self) -> None:
        assert StorageChecksumAlgorithm.SHA256 == "sha256"

    def test_sha512(self) -> None:
        assert StorageChecksumAlgorithm.SHA512 == "sha512"

    def test_is_str(self) -> None:
        assert isinstance(StorageChecksumAlgorithm.MD5, str)


class TestStoragePresignedUrlMethod:
    def test_get(self) -> None:
        assert StoragePresignedUrlMethod.GET == "GET"

    def test_put(self) -> None:
        assert StoragePresignedUrlMethod.PUT == "PUT"

    def test_post(self) -> None:
        assert StoragePresignedUrlMethod.POST == "POST"

    def test_delete(self) -> None:
        assert StoragePresignedUrlMethod.DELETE == "DELETE"


class TestStorageObjectVisibility:
    def test_private(self) -> None:
        assert StorageObjectVisibility.PRIVATE == "private"


class TestStorageObjectStatus:
    def test_pending(self) -> None:
        assert StorageObjectStatus.PENDING == "pending"

    def test_available(self) -> None:
        assert StorageObjectStatus.AVAILABLE == "available"

    def test_missing(self) -> None:
        assert StorageObjectStatus.MISSING == "missing"

    def test_corrupted(self) -> None:
        assert StorageObjectStatus.CORRUPTED == "corrupted"

    def test_deleting(self) -> None:
        assert StorageObjectStatus.DELETING == "deleting"

    def test_deleted(self) -> None:
        assert StorageObjectStatus.DELETED == "deleted"


class TestStorageMultipartUploadStatus:
    def test_initiated(self) -> None:
        assert StorageMultipartUploadStatus.INITIATED == "initiated"

    def test_completed(self) -> None:
        assert StorageMultipartUploadStatus.COMPLETED == "completed"

    def test_aborted(self) -> None:
        assert StorageMultipartUploadStatus.ABORTED == "aborted"

    def test_failed(self) -> None:
        assert StorageMultipartUploadStatus.FAILED == "failed"

    def test_expired(self) -> None:
        assert StorageMultipartUploadStatus.EXPIRED == "expired"


class TestStorageIntegrityProblemType:
    def test_object_not_found(self) -> None:
        assert StorageIntegrityProblemType.OBJECT_NOT_FOUND == "object_not_found"

    def test_size_mismatch(self) -> None:
        assert StorageIntegrityProblemType.SIZE_MISMATCH == "size_mismatch"

    def test_checksum_mismatch(self) -> None:
        assert StorageIntegrityProblemType.CHECKSUM_MISMATCH == "checksum_mismatch"


class TestStorageHealthState:
    def test_healthy(self) -> None:
        assert StorageHealthState.HEALTHY == "healthy"

    def test_degraded(self) -> None:
        assert StorageHealthState.DEGRADED == "degraded"

    def test_unhealthy(self) -> None:
        assert StorageHealthState.UNHEALTHY == "unhealthy"


# ---------------------------------------------------------------------------
# StorageObjectMetadata
# ---------------------------------------------------------------------------


class TestStorageObjectMetadata:
    def test_empty_metadata_valid(self) -> None:
        meta = StorageObjectMetadata()
        assert meta.values == {}

    def test_values_from_dict(self) -> None:
        meta = StorageObjectMetadata(values={"key": "value"})
        assert meta.values["key"] == "value"

    def test_none_input_gives_empty(self) -> None:
        meta = StorageObjectMetadata(values=None)  # type: ignore[arg-type]
        assert meta.values == {}

    def test_non_mapping_raises_type_error(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            StorageObjectMetadata(values="not-a-dict")  # type: ignore[arg-type]

    def test_empty_key_raises(self) -> None:
        with pytest.raises((ValidationError, ValueError)):
            StorageObjectMetadata(values={"": "value"})

    def test_none_value_skipped(self) -> None:
        meta = StorageObjectMetadata(values={"key": None, "other": "val"})  # type: ignore[arg-type]
        assert "key" not in meta.values
        assert meta.values["other"] == "val"

    def test_non_string_value_converted_to_string(self) -> None:
        meta = StorageObjectMetadata(values={"count": 42})  # type: ignore[arg-type]
        assert meta.values["count"] == "42"

    def test_has_metadata_true_when_non_empty(self) -> None:
        meta = StorageObjectMetadata(values={"k": "v"})
        assert meta.has_metadata is True

    def test_has_metadata_false_when_empty(self) -> None:
        meta = StorageObjectMetadata()
        assert meta.has_metadata is False

    def test_get_returns_value(self) -> None:
        meta = StorageObjectMetadata(values={"k": "v"})
        assert meta.get("k") == "v"

    def test_get_returns_default_for_missing(self) -> None:
        meta = StorageObjectMetadata()
        assert meta.get("missing", "default") == "default"

    def test_to_headers_prefixed(self) -> None:
        meta = StorageObjectMetadata(values={"file_id": "123"})
        headers = meta.to_headers()
        assert "x-amz-meta-file_id" in headers
        assert headers["x-amz-meta-file_id"] == "123"

    def test_to_headers_custom_prefix(self) -> None:
        meta = StorageObjectMetadata(values={"k": "v"})
        headers = meta.to_headers(prefix="custom-")
        assert "custom-k" in headers

    def test_to_plain_dict(self) -> None:
        meta = StorageObjectMetadata(values={"a": "1", "b": "2"})
        d = meta.to_plain_dict()
        assert d == {"a": "1", "b": "2"}

    def test_constructed_from_another_metadata(self) -> None:
        meta1 = StorageObjectMetadata(values={"k": "v"})
        meta2 = StorageObjectMetadata(values=meta1)  # type: ignore[arg-type]
        assert meta2.values == {"k": "v"}


# ---------------------------------------------------------------------------
# StorageBucketInfo
# ---------------------------------------------------------------------------


class TestStorageBucketInfo:
    def test_valid_bucket(self) -> None:
        info = StorageBucketInfo(name="my-bucket")
        assert info.name == "my-bucket"

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageBucketInfo(name="")

    def test_whitespace_name_raises(self) -> None:
        # str_strip_whitespace=True в конфиге, поэтому "  " -> "" -> валидатор падает.
        with pytest.raises(ValidationError):
            StorageBucketInfo(name="   ")

    def test_created_at_optional(self) -> None:
        info = StorageBucketInfo(name="bucket")
        assert info.created_at is None

    def test_created_at_stored(self) -> None:
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        info = StorageBucketInfo(name="bucket", created_at=dt)
        assert info.created_at == dt


# ---------------------------------------------------------------------------
# StorageObjectInfo
# ---------------------------------------------------------------------------


class TestStorageObjectInfo:
    def _make_valid(self, **kwargs) -> StorageObjectInfo:
        defaults = dict(
            bucket="my-bucket",
            object_key="path/to/file.txt",
            size_bytes=1024,
        )
        defaults.update(kwargs)
        return StorageObjectInfo(**defaults)

    def test_valid_construction(self) -> None:
        info = self._make_valid()
        assert info.bucket == "my-bucket"
        assert info.size_bytes == 1024

    def test_empty_bucket_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(bucket="")

    def test_empty_object_key_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(object_key="")

    def test_negative_size_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(size_bytes=-1)

    def test_zero_size_valid(self) -> None:
        info = self._make_valid(size_bytes=0)
        assert info.size_bytes == 0

    def test_checksum_without_algorithm_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(checksum="abc123", checksum_algorithm=None)

    def test_algorithm_without_checksum_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(
                checksum=None,
                checksum_algorithm=StorageChecksumAlgorithm.SHA256,
            )

    def test_checksum_and_algorithm_together_valid(self) -> None:
        info = self._make_valid(
            checksum="abc123",
            checksum_algorithm=StorageChecksumAlgorithm.SHA256,
        )
        assert info.has_checksum is True

    def test_has_checksum_false_when_no_checksum(self) -> None:
        info = self._make_valid()
        assert info.has_checksum is False

    def test_default_status_available(self) -> None:
        info = self._make_valid()
        assert info.status == StorageObjectStatus.AVAILABLE

    def test_is_available_true(self) -> None:
        info = self._make_valid(status=StorageObjectStatus.AVAILABLE)
        assert info.is_available is True

    def test_is_available_false(self) -> None:
        info = self._make_valid(status=StorageObjectStatus.MISSING)
        assert info.is_available is False

    def test_is_missing_true(self) -> None:
        info = self._make_valid(status=StorageObjectStatus.MISSING)
        assert info.is_missing is True

    def test_is_corrupted_true(self) -> None:
        info = self._make_valid(status=StorageObjectStatus.CORRUPTED)
        assert info.is_corrupted is True

    def test_has_metadata_false_by_default(self) -> None:
        info = self._make_valid()
        assert info.has_metadata is False

    def test_has_metadata_true_when_set(self) -> None:
        meta = StorageObjectMetadata(values={"k": "v"})
        info = self._make_valid(metadata=meta)
        assert info.has_metadata is True


# ---------------------------------------------------------------------------
# StoragePutObjectRequest
# ---------------------------------------------------------------------------


class TestStoragePutObjectRequest:
    def test_valid_construction(self) -> None:
        req = StoragePutObjectRequest(
            bucket="bucket",
            object_key="key",
            data=b"hello",
        )
        assert req.size_bytes == 5

    def test_empty_bucket_raises(self) -> None:
        with pytest.raises(ValidationError):
            StoragePutObjectRequest(bucket="", object_key="key", data=b"")

    def test_empty_object_key_raises(self) -> None:
        with pytest.raises(ValidationError):
            StoragePutObjectRequest(bucket="bucket", object_key="", data=b"")

    def test_has_metadata_false_by_default(self) -> None:
        req = StoragePutObjectRequest(bucket="b", object_key="k", data=b"")
        assert req.has_metadata is False


# ---------------------------------------------------------------------------
# StorageUploadPart
# ---------------------------------------------------------------------------


class TestStorageUploadPart:
    def test_valid_construction(self) -> None:
        part = StorageUploadPart(part_number=1, etag="abc123")
        assert part.part_number == 1
        assert part.etag == "abc123"

    def test_zero_part_number_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageUploadPart(part_number=0, etag="abc")

    def test_negative_part_number_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageUploadPart(part_number=-1, etag="abc")

    def test_empty_etag_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageUploadPart(part_number=1, etag="")

    def test_zero_size_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageUploadPart(part_number=1, etag="abc", size_bytes=0)

    def test_negative_size_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageUploadPart(part_number=1, etag="abc", size_bytes=-1)

    def test_none_size_allowed(self) -> None:
        part = StorageUploadPart(part_number=1, etag="abc", size_bytes=None)
        assert part.size_bytes is None

    def test_has_checksum_false_by_default(self) -> None:
        part = StorageUploadPart(part_number=1, etag="abc")
        assert part.has_checksum is False

    def test_has_checksum_true_when_set(self) -> None:
        part = StorageUploadPart(part_number=1, etag="abc", checksum="xyz")
        assert part.has_checksum is True


# ---------------------------------------------------------------------------
# StorageMultipartUpload
# ---------------------------------------------------------------------------


class TestStorageMultipartUpload:
    def test_valid_construction(self) -> None:
        upload = StorageMultipartUpload(
            bucket="bucket",
            object_key="key",
            upload_id="upload-123",
        )
        assert upload.upload_id == "upload-123"

    def test_empty_bucket_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageMultipartUpload(bucket="", object_key="key", upload_id="id")

    def test_empty_object_key_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageMultipartUpload(bucket="b", object_key="", upload_id="id")

    def test_empty_upload_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageMultipartUpload(bucket="b", object_key="k", upload_id="")

    def test_default_status_initiated(self) -> None:
        upload = StorageMultipartUpload(
            bucket="b", object_key="k", upload_id="id"
        )
        assert upload.status == StorageMultipartUploadStatus.INITIATED

    def test_is_finished_false_for_initiated(self) -> None:
        upload = StorageMultipartUpload(
            bucket="b", object_key="k", upload_id="id",
            status=StorageMultipartUploadStatus.INITIATED,
        )
        assert upload.is_finished is False

    def test_is_finished_false_for_uploading(self) -> None:
        upload = StorageMultipartUpload(
            bucket="b", object_key="k", upload_id="id",
            status=StorageMultipartUploadStatus.UPLOADING,
        )
        assert upload.is_finished is False

    def test_is_finished_true_for_completed(self) -> None:
        upload = StorageMultipartUpload(
            bucket="b", object_key="k", upload_id="id",
            status=StorageMultipartUploadStatus.COMPLETED,
        )
        assert upload.is_finished is True

    def test_is_finished_true_for_aborted(self) -> None:
        upload = StorageMultipartUpload(
            bucket="b", object_key="k", upload_id="id",
            status=StorageMultipartUploadStatus.ABORTED,
        )
        assert upload.is_finished is True

    def test_is_finished_true_for_failed(self) -> None:
        upload = StorageMultipartUpload(
            bucket="b", object_key="k", upload_id="id",
            status=StorageMultipartUploadStatus.FAILED,
        )
        assert upload.is_finished is True

    def test_is_finished_true_for_expired(self) -> None:
        upload = StorageMultipartUpload(
            bucket="b", object_key="k", upload_id="id",
            status=StorageMultipartUploadStatus.EXPIRED,
        )
        assert upload.is_finished is True

    def test_has_metadata_false_by_default(self) -> None:
        upload = StorageMultipartUpload(bucket="b", object_key="k", upload_id="id")
        assert upload.has_metadata is False


# ---------------------------------------------------------------------------
# StorageCompleteMultipartUploadRequest
# ---------------------------------------------------------------------------


class TestStorageCompleteMultipartUploadRequest:
    def _make_part(self, part_number: int = 1) -> StorageUploadPart:
        return StorageUploadPart(part_number=part_number, etag=f"etag-{part_number}")

    def test_valid_construction(self) -> None:
        req = StorageCompleteMultipartUploadRequest(
            bucket="b",
            object_key="k",
            upload_id="id",
            parts=[self._make_part(1)],
        )
        assert req.parts_count == 1

    def test_empty_bucket_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageCompleteMultipartUploadRequest(
                bucket="", object_key="k", upload_id="id",
                parts=[self._make_part()],
            )

    def test_empty_parts_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageCompleteMultipartUploadRequest(
                bucket="b", object_key="k", upload_id="id",
                parts=[],
            )

    def test_duplicate_part_numbers_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageCompleteMultipartUploadRequest(
                bucket="b", object_key="k", upload_id="id",
                parts=[self._make_part(1), self._make_part(1)],
            )

    def test_parts_sorted_by_number(self) -> None:
        req = StorageCompleteMultipartUploadRequest(
            bucket="b", object_key="k", upload_id="id",
            parts=[self._make_part(3), self._make_part(1), self._make_part(2)],
        )
        assert [p.part_number for p in req.parts] == [1, 2, 3]

    def test_parts_count(self) -> None:
        req = StorageCompleteMultipartUploadRequest(
            bucket="b", object_key="k", upload_id="id",
            parts=[self._make_part(1), self._make_part(2)],
        )
        assert req.parts_count == 2


# ---------------------------------------------------------------------------
# StoragePresignedUrl
# ---------------------------------------------------------------------------


class TestStoragePresignedUrl:
    def _make_valid(self, **kwargs) -> StoragePresignedUrl:
        defaults = dict(
            url="https://example.com/presigned",
            method=StoragePresignedUrlMethod.GET,
            bucket="bucket",
            object_key="key",
            expires_in_seconds=3600,
        )
        defaults.update(kwargs)
        return StoragePresignedUrl(**defaults)

    def test_valid_construction(self) -> None:
        url = self._make_valid()
        assert url.expires_in == 3600

    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(url="")

    def test_empty_bucket_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(bucket="")

    def test_empty_object_key_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(object_key="")

    def test_zero_expires_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(expires_in_seconds=0)

    def test_negative_expires_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._make_valid(expires_in_seconds=-1)

    def test_is_download_url_true_for_get(self) -> None:
        url = self._make_valid(method=StoragePresignedUrlMethod.GET)
        assert url.is_download_url is True

    def test_is_download_url_false_for_put(self) -> None:
        url = self._make_valid(method=StoragePresignedUrlMethod.PUT)
        assert url.is_download_url is False

    def test_is_upload_url_true_for_put(self) -> None:
        url = self._make_valid(method=StoragePresignedUrlMethod.PUT)
        assert url.is_upload_url is True

    def test_is_upload_url_true_for_post(self) -> None:
        url = self._make_valid(method=StoragePresignedUrlMethod.POST)
        assert url.is_upload_url is True

    def test_is_upload_url_false_for_get(self) -> None:
        url = self._make_valid(method=StoragePresignedUrlMethod.GET)
        assert url.is_upload_url is False

    def test_headers_none_gives_empty_dict(self) -> None:
        url = self._make_valid(headers=None)
        assert url.headers == {}

    def test_non_mapping_headers_raises(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            self._make_valid(headers="not-a-dict")  # type: ignore[arg-type]

    def test_headers_normalized(self) -> None:
        url = self._make_valid(headers={"  Content-Type  ": "application/octet-stream"})
        # ключ обрезается от пробелов
        assert "Content-Type" in url.headers


# ---------------------------------------------------------------------------
# StoragePresignedUploadPartUrl
# ---------------------------------------------------------------------------


class TestStoragePresignedUploadPartUrl:
    def _make_presigned_url(self) -> StoragePresignedUrl:
        return StoragePresignedUrl(
            url="https://example.com/part",
            method=StoragePresignedUrlMethod.PUT,
            bucket="bucket",
            object_key="key",
            expires_in_seconds=600,
        )

    def test_valid_construction(self) -> None:
        part_url = StoragePresignedUploadPartUrl(
            part_number=1,
            url=self._make_presigned_url(),
        )
        assert part_url.part_number == 1

    def test_zero_part_number_raises(self) -> None:
        with pytest.raises(ValidationError):
            StoragePresignedUploadPartUrl(
                part_number=0,
                url=self._make_presigned_url(),
            )

    def test_negative_part_number_raises(self) -> None:
        with pytest.raises(ValidationError):
            StoragePresignedUploadPartUrl(
                part_number=-1,
                url=self._make_presigned_url(),
            )


# ---------------------------------------------------------------------------
# StorageDownloadResult
# ---------------------------------------------------------------------------


class TestStorageDownloadResult:
    def test_valid_construction(self) -> None:
        result = StorageDownloadResult(
            bucket="b",
            object_key="k",
            data=b"hello",
            size_bytes=5,
        )
        assert result.is_success is True

    def test_empty_bucket_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageDownloadResult(bucket="", object_key="k", data=b"", size_bytes=0)

    def test_negative_size_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageDownloadResult(bucket="b", object_key="k", data=b"", size_bytes=-1)

    def test_is_success_false_when_size_mismatch(self) -> None:
        result = StorageDownloadResult(
            bucket="b", object_key="k", data=b"hi", size_bytes=10
        )
        assert result.is_success is False

    def test_has_metadata_false_by_default(self) -> None:
        result = StorageDownloadResult(
            bucket="b", object_key="k", data=b"x", size_bytes=1
        )
        assert result.has_metadata is False


# ---------------------------------------------------------------------------
# StorageDeleteResult
# ---------------------------------------------------------------------------


class TestStorageDeleteResult:
    def test_valid_construction(self) -> None:
        result = StorageDeleteResult(bucket="b", object_key="k", deleted=True)
        assert result.is_success is True

    def test_is_success_false_when_not_deleted(self) -> None:
        result = StorageDeleteResult(bucket="b", object_key="k", deleted=False)
        assert result.is_success is False

    def test_empty_bucket_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageDeleteResult(bucket="", object_key="k", deleted=True)

    def test_empty_object_key_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageDeleteResult(bucket="b", object_key="", deleted=True)


# ---------------------------------------------------------------------------
# StorageCopyResult
# ---------------------------------------------------------------------------


class TestStorageCopyResult:
    def test_valid_construction(self) -> None:
        result = StorageCopyResult(
            source_bucket="src-b",
            source_object_key="src-k",
            destination_bucket="dst-b",
            destination_object_key="dst-k",
        )
        assert result.source_bucket == "src-b"

    def test_empty_source_bucket_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageCopyResult(
                source_bucket="",
                source_object_key="k",
                destination_bucket="b",
                destination_object_key="k",
            )

    def test_empty_destination_object_key_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageCopyResult(
                source_bucket="b",
                source_object_key="k",
                destination_bucket="b",
                destination_object_key="",
            )


# ---------------------------------------------------------------------------
# StorageIntegrityStatus
# ---------------------------------------------------------------------------


class TestStorageIntegrityStatus:
    def test_success_no_problem_type_valid(self) -> None:
        status = StorageIntegrityStatus(is_success=True)
        assert status.has_problem is False

    def test_failure_without_problem_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageIntegrityStatus(is_success=False, problem_type=None)

    def test_failure_with_problem_type_valid(self) -> None:
        status = StorageIntegrityStatus(
            is_success=False,
            problem_type=StorageIntegrityProblemType.SIZE_MISMATCH,
        )
        assert status.has_problem is True

    def test_has_problem_false_when_success(self) -> None:
        status = StorageIntegrityStatus(is_success=True)
        assert status.has_problem is False


# ---------------------------------------------------------------------------
# StorageIntegrityReport
# ---------------------------------------------------------------------------


class TestStorageIntegrityReport:
    def _make_now(self) -> datetime:
        return datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)

    def test_valid_construction(self) -> None:
        report = StorageIntegrityReport(
            bucket="b",
            object_key="k",
            checked_at=self._make_now(),
            object_exists=True,
        )
        assert report.is_success is True

    def test_empty_bucket_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageIntegrityReport(
                bucket="",
                object_key="k",
                checked_at=self._make_now(),
                object_exists=True,
            )

    def test_is_success_false_when_object_missing(self) -> None:
        report = StorageIntegrityReport(
            bucket="b",
            object_key="k",
            checked_at=self._make_now(),
            object_exists=False,
        )
        assert report.is_success is False

    def test_problems_derived_from_status_fields(self) -> None:
        bad_status = StorageIntegrityStatus(
            is_success=False,
            problem_type=StorageIntegrityProblemType.SIZE_MISMATCH,
        )
        report = StorageIntegrityReport(
            bucket="b",
            object_key="k",
            checked_at=self._make_now(),
            object_exists=True,
            size_status=bad_status,
        )
        assert report.has_problems is True
        assert len(report.problems) == 1

    def test_no_duplicate_problems(self) -> None:
        bad_status = StorageIntegrityStatus(
            is_success=False,
            problem_type=StorageIntegrityProblemType.SIZE_MISMATCH,
            message="mismatch",
        )
        report = StorageIntegrityReport(
            bucket="b",
            object_key="k",
            checked_at=self._make_now(),
            object_exists=True,
            size_status=bad_status,
            problems=[bad_status],
        )
        # Одна и та же проблема не должна дублироваться.
        assert len(report.problems) == 1

    def test_has_problems_false_when_no_issues(self) -> None:
        report = StorageIntegrityReport(
            bucket="b",
            object_key="k",
            checked_at=self._make_now(),
            object_exists=True,
        )
        assert report.has_problems is False


# ---------------------------------------------------------------------------
# StorageHealthStatus
# ---------------------------------------------------------------------------


class TestStorageHealthStatus:
    def _make_now(self) -> datetime:
        return datetime(2024, 6, 1, tzinfo=UTC)

    def test_valid_construction(self) -> None:
        status = StorageHealthStatus(
            state=StorageHealthState.HEALTHY,
            checked_at=self._make_now(),
            connection_ok=True,
        )
        assert status.is_healthy is True

    def test_is_healthy_false_for_degraded(self) -> None:
        status = StorageHealthStatus(
            state=StorageHealthState.DEGRADED,
            checked_at=self._make_now(),
            connection_ok=True,
        )
        assert status.is_healthy is False
        assert status.is_degraded is True

    def test_is_unhealthy_true(self) -> None:
        status = StorageHealthStatus(
            state=StorageHealthState.UNHEALTHY,
            checked_at=self._make_now(),
            connection_ok=False,
        )
        assert status.is_unhealthy is True

    def test_is_success_same_as_is_healthy(self) -> None:
        status = StorageHealthStatus(
            state=StorageHealthState.HEALTHY,
            checked_at=self._make_now(),
            connection_ok=True,
        )
        assert status.is_success is True

    def test_negative_latency_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageHealthStatus(
                state=StorageHealthState.HEALTHY,
                checked_at=self._make_now(),
                connection_ok=True,
                latency_ms=-1.0,
            )

    def test_zero_latency_threshold_raises(self) -> None:
        with pytest.raises(ValidationError):
            StorageHealthStatus(
                state=StorageHealthState.HEALTHY,
                checked_at=self._make_now(),
                connection_ok=True,
                latency_threshold_ms=0.0,
            )

    def test_positive_latency_valid(self) -> None:
        status = StorageHealthStatus(
            state=StorageHealthState.HEALTHY,
            checked_at=self._make_now(),
            connection_ok=True,
            latency_ms=42.5,
            latency_threshold_ms=100.0,
        )
        assert status.latency_ms == 42.5


# ---------------------------------------------------------------------------
# StorageObjectDeleteResult (non-Pydantic)
# ---------------------------------------------------------------------------


class TestStorageObjectDeleteResult:
    def test_success_when_no_errors(self) -> None:
        result = StorageObjectDeleteResult(deleted_count=5)
        assert result.is_success is True
        assert result.has_errors is False
        assert result.deleted_count == 5

    def test_has_errors_when_errors_provided(self) -> None:
        err = StorageObjectError("error")
        result = StorageObjectDeleteResult(deleted_count=3, errors=[err])
        assert result.has_errors is True
        assert result.is_success is False

    def test_none_errors_gives_empty_list(self) -> None:
        result = StorageObjectDeleteResult(deleted_count=0, errors=None)
        assert result.errors == []

    def test_deleted_count_zero_valid(self) -> None:
        result = StorageObjectDeleteResult(deleted_count=0)
        assert result.deleted_count == 0
        assert result.is_success is True
