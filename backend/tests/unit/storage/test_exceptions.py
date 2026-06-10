"""Unit-тесты для иерархии исключений модуля storage."""
from __future__ import annotations


from storage.exceptions import (
    InvalidStorageBucketNameError,
    InvalidStorageKeyError,
    InvalidStorageMetadataError,
    StorageAuthenticationError,
    StorageBucketAlreadyExistsError,
    StorageBucketError,
    StorageBucketNotFoundError,
    StorageChecksumMismatchError,
    StorageConfigurationError,
    StorageConnectionError,
    StorageCopyError,
    StorageDeleteError,
    StorageDownloadError,
    StorageError,
    StorageHealthCheckError,
    StorageIntegrityError,
    StorageMultipartUploadError,
    StorageMultipartUploadNotFoundError,
    StorageObjectAlreadyExistsError,
    StorageObjectError,
    StorageObjectNotFoundError,
    StoragePermissionDeniedError,
    StoragePresignedUrlError,
    StorageTimeoutError,
    StorageUploadError,
)


class TestStorageError:
    def test_default_message(self) -> None:
        err = StorageError()
        assert err.message

    def test_custom_message_stored(self) -> None:
        err = StorageError("storage failure")
        assert err.message == "storage failure"

    def test_details_copied(self) -> None:
        original = {"bucket": "test"}
        err = StorageError(details=original)
        original["bucket"] = "changed"
        assert err.details["bucket"] == "test"

    def test_empty_details_default(self) -> None:
        err = StorageError()
        assert err.details == {}

    def test_cause_stored(self) -> None:
        cause = IOError("network error")
        err = StorageError(cause=cause)
        assert err.cause is cause
        assert err.__cause__ is cause

    def test_str_without_details(self) -> None:
        err = StorageError("msg")
        assert str(err) == "msg"

    def test_str_with_details(self) -> None:
        err = StorageError("msg", details={"k": "v"})
        assert "Details" in str(err)

    def test_to_dict(self) -> None:
        err = StorageError("test")
        d = err.to_dict()
        assert d["error"] == "StorageError"
        assert d["message"] == "test"

    def test_to_dict_with_cause(self) -> None:
        err = StorageError(cause=RuntimeError("root"))
        assert err.to_dict()["cause"] == "RuntimeError"

    def test_to_dict_includes_details(self) -> None:
        err = StorageError("msg", details={"bucket": "b"})
        assert err.to_dict()["details"] == {"bucket": "b"}


class TestStorageConnectionError:
    def test_is_storage_error(self) -> None:
        assert issubclass(StorageConnectionError, StorageError)

    def test_endpoint_in_details(self) -> None:
        err = StorageConnectionError(endpoint="minio:9000")
        assert err.details["endpoint"] == "minio:9000"

    def test_secure_in_details(self) -> None:
        err = StorageConnectionError(secure=True)
        assert err.details["secure"] is True

    def test_none_fields_not_in_details(self) -> None:
        err = StorageConnectionError()
        assert "endpoint" not in err.details


class TestStorageAuthenticationError:
    def test_is_storage_error(self) -> None:
        assert issubclass(StorageAuthenticationError, StorageError)

    def test_access_key_in_details(self) -> None:
        err = StorageAuthenticationError(access_key="AKIA123")
        assert err.details["access_key"] == "AKIA123"

    def test_operation_in_details(self) -> None:
        err = StorageAuthenticationError(operation="list_objects")
        assert err.details["operation"] == "list_objects"

    def test_none_fields_not_in_details(self) -> None:
        err = StorageAuthenticationError()
        assert err.details == {}


class TestStoragePermissionDeniedError:
    def test_is_authentication_error(self) -> None:
        assert issubclass(StoragePermissionDeniedError, StorageAuthenticationError)

    def test_bucket_and_object_key_in_details(self) -> None:
        err = StoragePermissionDeniedError(
            bucket="b", object_key="k", operation="put_object"
        )
        assert err.details["bucket"] == "b"
        assert err.details["object_key"] == "k"
        assert err.details["operation"] == "put_object"

    def test_none_fields_not_in_details(self) -> None:
        err = StoragePermissionDeniedError()
        assert "bucket" not in err.details
        assert "object_key" not in err.details


class TestStorageTimeoutError:
    def test_is_storage_error(self) -> None:
        assert issubclass(StorageTimeoutError, StorageError)

    def test_all_fields_in_details(self) -> None:
        err = StorageTimeoutError(
            operation="download",
            timeout_seconds=30.0,
            bucket="b",
            object_key="k",
        )
        assert err.details["operation"] == "download"
        assert err.details["timeout_seconds"] == 30.0
        assert err.details["bucket"] == "b"
        assert err.details["object_key"] == "k"

    def test_none_fields_not_in_details(self) -> None:
        err = StorageTimeoutError()
        assert err.details == {}


class TestStorageHealthCheckError:
    def test_is_storage_error(self) -> None:
        assert issubclass(StorageHealthCheckError, StorageError)

    def test_default_message(self) -> None:
        err = StorageHealthCheckError()
        assert err.message

    def test_component_in_details(self) -> None:
        err = StorageHealthCheckError(component="storage")
        assert err.details["component"] == "storage"

    def test_no_component_not_in_details(self) -> None:
        err = StorageHealthCheckError()
        assert "component" not in err.details


class TestStorageBucketError:
    def test_is_storage_error(self) -> None:
        assert issubclass(StorageBucketError, StorageError)

    def test_bucket_in_details(self) -> None:
        err = StorageBucketError(bucket="my-bucket")
        assert err.details["bucket"] == "my-bucket"

    def test_operation_in_details(self) -> None:
        err = StorageBucketError(operation="create")
        assert err.details["operation"] == "create"


class TestStorageBucketNotFoundError:
    def test_is_bucket_error(self) -> None:
        assert issubclass(StorageBucketNotFoundError, StorageBucketError)

    def test_bucket_name_in_details(self) -> None:
        err = StorageBucketNotFoundError("my-bucket")
        assert err.details["bucket"] == "my-bucket"

    def test_auto_message_contains_bucket_name(self) -> None:
        err = StorageBucketNotFoundError("my-bucket")
        assert "my-bucket" in err.message

    def test_custom_message(self) -> None:
        err = StorageBucketNotFoundError("b", message="custom msg")
        assert err.message == "custom msg"

    def test_operation_is_get_bucket(self) -> None:
        err = StorageBucketNotFoundError("b")
        assert err.details.get("operation") == "get_bucket"


class TestStorageBucketAlreadyExistsError:
    def test_is_bucket_error(self) -> None:
        assert issubclass(StorageBucketAlreadyExistsError, StorageBucketError)

    def test_bucket_name_in_details(self) -> None:
        err = StorageBucketAlreadyExistsError("my-bucket")
        assert err.details["bucket"] == "my-bucket"

    def test_operation_is_create_bucket(self) -> None:
        err = StorageBucketAlreadyExistsError("b")
        assert err.details.get("operation") == "create_bucket"


class TestStorageObjectError:
    def test_is_storage_error(self) -> None:
        assert issubclass(StorageObjectError, StorageError)

    def test_bucket_in_details(self) -> None:
        err = StorageObjectError(bucket="b")
        assert err.details["bucket"] == "b"

    def test_object_key_in_details(self) -> None:
        err = StorageObjectError(object_key="path/to/file.txt")
        assert err.details["object_key"] == "path/to/file.txt"


class TestStorageObjectNotFoundError:
    def test_is_object_error(self) -> None:
        assert issubclass(StorageObjectNotFoundError, StorageObjectError)

    def test_bucket_and_key_in_details(self) -> None:
        err = StorageObjectNotFoundError(bucket="b", object_key="k")
        assert err.details["bucket"] == "b"
        assert err.details["object_key"] == "k"

    def test_operation_is_get_object(self) -> None:
        err = StorageObjectNotFoundError(bucket="b", object_key="k")
        assert err.details.get("operation") == "get_object"

    def test_custom_message(self) -> None:
        err = StorageObjectNotFoundError(bucket="b", object_key="k", message="custom")
        assert err.message == "custom"


class TestStorageObjectAlreadyExistsError:
    def test_is_object_error(self) -> None:
        assert issubclass(StorageObjectAlreadyExistsError, StorageObjectError)

    def test_operation_is_put_object(self) -> None:
        err = StorageObjectAlreadyExistsError(bucket="b", object_key="k")
        assert err.details.get("operation") == "put_object"


class TestStorageObjectErrorOperation:
    def test_operation_in_details(self) -> None:
        err = StorageObjectError(operation="copy")
        assert err.details["operation"] == "copy"


class TestStorageUploadError:
    def test_is_object_error(self) -> None:
        assert issubclass(StorageUploadError, StorageObjectError)

    def test_upload_id_in_details(self) -> None:
        err = StorageUploadError(bucket="b", object_key="k", upload_id="up-1")
        assert err.details["upload_id"] == "up-1"

    def test_default_operation_is_upload(self) -> None:
        err = StorageUploadError(bucket="b", object_key="k")
        assert err.details["operation"] == "upload"

    def test_custom_operation_used(self) -> None:
        err = StorageUploadError(bucket="b", object_key="k", operation="resume")
        assert err.details["operation"] == "resume"


class TestStorageDownloadError:
    def test_is_object_error(self) -> None:
        assert issubclass(StorageDownloadError, StorageObjectError)

    def test_operation_is_download(self) -> None:
        err = StorageDownloadError(bucket="b", object_key="k")
        assert err.details["operation"] == "download"


class TestStorageDeleteError:
    def test_is_object_error(self) -> None:
        assert issubclass(StorageDeleteError, StorageObjectError)

    def test_operation_is_delete(self) -> None:
        err = StorageDeleteError(bucket="b", object_key="k")
        assert err.details["operation"] == "delete"


class TestStorageCopyError:
    def test_is_object_error(self) -> None:
        assert issubclass(StorageCopyError, StorageObjectError)

    def test_all_fields_in_details(self) -> None:
        err = StorageCopyError(
            source_bucket="sb",
            source_object_key="sk",
            destination_bucket="db",
            destination_object_key="dk",
        )
        assert err.details["source_bucket"] == "sb"
        assert err.details["source_object_key"] == "sk"
        assert err.details["destination_bucket"] == "db"
        assert err.details["destination_object_key"] == "dk"

    def test_operation_is_copy(self) -> None:
        err = StorageCopyError(destination_bucket="db", destination_object_key="dk")
        assert err.details["operation"] == "copy"
        # bucket/key назначения дублируются в поля уровня объекта.
        assert err.details["bucket"] == "db"
        assert err.details["object_key"] == "dk"


class TestStorageMultipartUploadError:
    def test_is_upload_error(self) -> None:
        assert issubclass(StorageMultipartUploadError, StorageUploadError)

    def test_part_number_in_details(self) -> None:
        err = StorageMultipartUploadError(
            bucket="b", object_key="k", upload_id="u", part_number=3
        )
        assert err.details["part_number"] == 3
        assert err.details["upload_id"] == "u"

    def test_default_operation_is_multipart_upload(self) -> None:
        err = StorageMultipartUploadError(bucket="b", object_key="k")
        assert err.details["operation"] == "multipart_upload"

    def test_custom_operation_used(self) -> None:
        err = StorageMultipartUploadError(
            bucket="b", object_key="k", operation="complete"
        )
        assert err.details["operation"] == "complete"


class TestStorageMultipartUploadNotFoundError:
    def test_is_multipart_error(self) -> None:
        assert issubclass(StorageMultipartUploadNotFoundError, StorageMultipartUploadError)

    def test_default_message_and_details(self) -> None:
        err = StorageMultipartUploadNotFoundError(
            bucket="b", object_key="k", upload_id="u-1"
        )
        assert "не найдена" in err.message
        assert err.details["upload_id"] == "u-1"
        assert err.details["operation"] == "get_multipart_upload"

    def test_custom_message(self) -> None:
        err = StorageMultipartUploadNotFoundError(
            bucket="b", object_key="k", upload_id="u", message="gone"
        )
        assert err.message == "gone"


class TestStoragePresignedUrlError:
    def test_is_storage_error(self) -> None:
        assert issubclass(StoragePresignedUrlError, StorageError)

    def test_all_fields_in_details(self) -> None:
        err = StoragePresignedUrlError(
            bucket="b",
            object_key="k",
            method="GET",
            expires_in_seconds=3600,
        )
        assert err.details["bucket"] == "b"
        assert err.details["object_key"] == "k"
        assert err.details["method"] == "GET"
        assert err.details["expires_in_seconds"] == 3600

    def test_none_fields_not_in_details(self) -> None:
        err = StoragePresignedUrlError()
        assert err.details == {}


class TestStorageIntegrityError:
    def test_is_storage_error(self) -> None:
        assert issubclass(StorageIntegrityError, StorageError)

    def test_all_fields_in_details(self) -> None:
        err = StorageIntegrityError(
            bucket="b",
            object_key="k",
            algorithm="sha256",
            expected="abc",
            actual="def",
        )
        assert err.details["bucket"] == "b"
        assert err.details["object_key"] == "k"
        assert err.details["algorithm"] == "sha256"
        assert err.details["expected"] == "abc"
        assert err.details["actual"] == "def"

    def test_none_fields_not_in_details(self) -> None:
        err = StorageIntegrityError()
        assert err.details == {}


class TestStorageChecksumMismatchError:
    def test_is_integrity_error(self) -> None:
        assert issubclass(StorageChecksumMismatchError, StorageIntegrityError)

    def test_default_message_and_details(self) -> None:
        err = StorageChecksumMismatchError(
            bucket="b",
            object_key="k",
            algorithm="md5",
            expected="e",
            actual="a",
        )
        assert "не совпадает" in err.message
        assert err.details["algorithm"] == "md5"
        assert err.details["expected"] == "e"
        assert err.details["actual"] == "a"

    def test_custom_message(self) -> None:
        err = StorageChecksumMismatchError(
            bucket="b",
            object_key="k",
            algorithm="md5",
            expected="e",
            actual="a",
            message="checksum off",
        )
        assert err.message == "checksum off"


class TestInvalidStorageKeyError:
    def test_is_storage_error(self) -> None:
        assert issubclass(InvalidStorageKeyError, StorageError)

    def test_object_key_and_reason_in_details(self) -> None:
        err = InvalidStorageKeyError(object_key="bad//key", reason="double_slash")
        assert err.details["object_key"] == "bad//key"
        assert err.details["reason"] == "double_slash"

    def test_none_fields_not_in_details(self) -> None:
        err = InvalidStorageKeyError()
        assert err.details == {}


class TestInvalidStorageBucketNameError:
    def test_is_storage_error(self) -> None:
        assert issubclass(InvalidStorageBucketNameError, StorageError)

    def test_bucket_and_reason_in_details(self) -> None:
        err = InvalidStorageBucketNameError(bucket="BAD", reason="uppercase")
        assert err.details["bucket"] == "BAD"
        assert err.details["reason"] == "uppercase"

    def test_none_fields_not_in_details(self) -> None:
        err = InvalidStorageBucketNameError()
        assert err.details == {}


class TestInvalidStorageMetadataError:
    def test_is_storage_error(self) -> None:
        assert issubclass(InvalidStorageMetadataError, StorageError)

    def test_all_fields_in_details(self) -> None:
        err = InvalidStorageMetadataError(
            metadata_key="user_id",
            metadata_value="bad",
            reason="invalid_uuid",
        )
        assert err.details["metadata_key"] == "user_id"
        assert err.details["metadata_value"] == "bad"
        assert err.details["reason"] == "invalid_uuid"

    def test_none_fields_not_in_details(self) -> None:
        err = InvalidStorageMetadataError()
        assert err.details == {}


class TestStorageConfigurationError:
    def test_is_storage_error(self) -> None:
        assert issubclass(StorageConfigurationError, StorageError)

    def test_all_fields_in_details(self) -> None:
        err = StorageConfigurationError(
            parameter="endpoint",
            value="",
            reason="missing_endpoint",
        )
        assert err.details["parameter"] == "endpoint"
        assert err.details["value"] == ""
        assert err.details["reason"] == "missing_endpoint"

    def test_none_fields_not_in_details(self) -> None:
        err = StorageConfigurationError()
        assert err.details == {}
