"""Unit-тесты для нормализации, валидации и построения метаданных объектов."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from core.constants import StorageConstants
from storage.exceptions import InvalidStorageMetadataError
from storage.metadata import (
    build_archive_metadata,
    build_file_metadata,
    build_file_version_metadata,
    build_preview_metadata,
    build_public_metadata,
    build_upload_metadata,
    filter_empty_metadata,
    get_metadata_value,
    has_metadata_key,
    merge_metadata,
    metadata_from_headers,
    metadata_to_headers,
    normalize_metadata,
    normalize_metadata_key,
    normalize_metadata_value,
    pick_metadata_keys,
    remove_metadata_keys,
    validate_metadata,
)
from storage.types import StorageChecksumAlgorithm, StorageObjectMetadata


class TestNormalizeMetadataKey:
    def test_valid_key_returned_normalized(self) -> None:
        assert normalize_metadata_key("user_id") == "user_id"

    def test_uppercase_lowercased(self) -> None:
        assert normalize_metadata_key("FILE_ID") == "file_id"

    def test_spaces_replaced_with_underscore(self) -> None:
        assert normalize_metadata_key("file id") == "file_id"

    def test_strips_whitespace(self) -> None:
        assert normalize_metadata_key("  key  ") == "key"

    def test_non_string_raises(self) -> None:
        with pytest.raises(InvalidStorageMetadataError):
            normalize_metadata_key(123)  # type: ignore[arg-type]

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidStorageMetadataError):
            normalize_metadata_key("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InvalidStorageMetadataError):
            normalize_metadata_key("   ")

    def test_too_long_key_raises(self) -> None:
        long_key = "a" * (StorageConstants.STORAGE_METADATA_KEY_MAX_LENGTH + 1)
        with pytest.raises(InvalidStorageMetadataError):
            normalize_metadata_key(long_key)

    def test_invalid_chars_raise(self) -> None:
        # Ключи со спецсимволами вне [a-z0-9_-].
        with pytest.raises(InvalidStorageMetadataError):
            normalize_metadata_key("key with @special")

    def test_dash_allowed(self) -> None:
        result = normalize_metadata_key("file-id")
        assert result == "file-id"

    def test_hyphen_in_key(self) -> None:
        result = normalize_metadata_key("original-filename")
        assert result == "original-filename"


class TestNormalizeMetadataValue:
    def test_none_returns_none(self) -> None:
        assert normalize_metadata_value(None) is None

    def test_uuid_converted_to_string(self) -> None:
        uid = uuid.uuid4()
        result = normalize_metadata_value(uid)
        assert result == str(uid)

    def test_datetime_converted_to_isoformat(self) -> None:
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = normalize_metadata_value(dt)
        assert "2024-01-01" in result

    def test_string_stripped(self) -> None:
        assert normalize_metadata_value("  hello  ") == "hello"

    def test_empty_string_returns_none(self) -> None:
        assert normalize_metadata_value("   ") is None

    def test_bool_true_converted(self) -> None:
        assert normalize_metadata_value(True) == "true"

    def test_bool_false_converted(self) -> None:
        assert normalize_metadata_value(False) == "false"

    def test_int_converted_to_string(self) -> None:
        assert normalize_metadata_value(42) == "42"

    def test_float_converted_to_string(self) -> None:
        result = normalize_metadata_value(3.14)
        assert "3.14" in result

    def test_storage_checksum_algorithm_converted(self) -> None:
        result = normalize_metadata_value(StorageChecksumAlgorithm.SHA256)
        assert result == StorageChecksumAlgorithm.SHA256.value

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(InvalidStorageMetadataError):
            normalize_metadata_value(object())

    def test_newline_in_value_raises(self) -> None:
        with pytest.raises(InvalidStorageMetadataError):
            normalize_metadata_value("value\nwith\nnewlines")

    def test_too_long_value_raises(self) -> None:
        long_value = "a" * (StorageConstants.STORAGE_METADATA_VALUE_MAX_LENGTH + 1)
        with pytest.raises(InvalidStorageMetadataError):
            normalize_metadata_value(long_value)


class TestNormalizeMetadata:
    def test_none_returns_empty_metadata(self) -> None:
        result = normalize_metadata(None)
        assert isinstance(result, StorageObjectMetadata)
        assert result.values == {}

    def test_empty_dict_returns_empty_metadata(self) -> None:
        result = normalize_metadata({})
        assert result.values == {}

    def test_valid_dict_normalized(self) -> None:
        result = normalize_metadata({"user_id": str(uuid.uuid4())})
        assert "user_id" in result.values

    def test_none_values_removed(self) -> None:
        uid = uuid.uuid4()
        result = normalize_metadata({"user_id": str(uid), "empty": None})
        assert "empty" not in result.values
        assert "user_id" in result.values

    def test_keys_lowercased(self) -> None:
        uid = uuid.uuid4()
        result = normalize_metadata({"USER_ID": str(uid)})
        assert "user_id" in result.values

    def test_non_mapping_raises(self) -> None:
        with pytest.raises(InvalidStorageMetadataError):
            normalize_metadata("not a mapping")  # type: ignore[arg-type]

    def test_storage_object_metadata_accepted(self) -> None:
        meta = StorageObjectMetadata(values={"key": "value"})
        result = normalize_metadata(meta)
        assert "key" in result.values


class TestValidateMetadata:
    def test_none_returns_empty_metadata(self) -> None:
        result = validate_metadata(None)
        assert result.values == {}

    def test_valid_metadata_passes(self) -> None:
        meta = {"user_id": str(uuid.uuid4())}
        result = validate_metadata(meta)
        assert "user_id" in result.values

    def test_total_size_exceeded_raises(self) -> None:
        # Формируем метаданные, превышающие лимит общего размера.
        large_value = "x" * (StorageConstants.STORAGE_METADATA_VALUE_MAX_LENGTH)
        num_keys = (StorageConstants.STORAGE_METADATA_TOTAL_MAX_SIZE // StorageConstants.STORAGE_METADATA_VALUE_MAX_LENGTH) + 2
        metadata = {f"key{i:02d}": large_value for i in range(num_keys)}
        with pytest.raises(InvalidStorageMetadataError):
            validate_metadata(metadata)


class TestMergeMetadata:
    def test_merges_two_dicts(self) -> None:
        uid = uuid.uuid4()
        result = merge_metadata({"user_id": str(uid)}, {"file_id": str(uid)})
        assert "user_id" in result.values
        assert "file_id" in result.values

    def test_later_overrides_earlier(self) -> None:
        uid1 = uuid.uuid4()
        uid2 = uuid.uuid4()
        result = merge_metadata({"user_id": str(uid1)}, {"user_id": str(uid2)})
        assert result.values["user_id"] == str(uid2)

    def test_none_items_treated_as_empty(self) -> None:
        uid = uuid.uuid4()
        result = merge_metadata({"user_id": str(uid)}, None)
        assert "user_id" in result.values


class TestMetadataToHeaders:
    def test_keys_prefixed_with_x_amz_meta(self) -> None:
        uid = uuid.uuid4()
        result = metadata_to_headers({"user_id": str(uid)})
        assert "x-amz-meta-user_id" in result

    def test_custom_prefix(self) -> None:
        uid = uuid.uuid4()
        result = metadata_to_headers({"user_id": str(uid)}, prefix="custom-")
        assert "custom-user_id" in result

    def test_empty_metadata_returns_empty_dict(self) -> None:
        result = metadata_to_headers(None)
        assert result == {}


class TestMetadataFromHeaders:
    def test_extracts_metadata_from_headers(self) -> None:
        headers = {"x-amz-meta-user_id": str(uuid.uuid4())}
        result = metadata_from_headers(headers)
        assert "user_id" in result.values

    def test_ignores_non_meta_headers(self) -> None:
        headers = {
            "Content-Type": "application/json",
            "x-amz-meta-file_id": str(uuid.uuid4()),
        }
        result = metadata_from_headers(headers)
        assert "file_id" in result.values
        assert "content-type" not in result.values

    def test_none_headers_returns_empty(self) -> None:
        result = metadata_from_headers(None)
        assert result.values == {}


class TestBuildFileMetadata:
    def test_returns_metadata_with_user_id(self) -> None:
        uid = uuid.uuid4()
        file_id = uuid.uuid4()
        result = build_file_metadata(user_id=uid, file_id=file_id)
        assert result.values["user_id"] == str(uid)

    def test_returns_metadata_with_file_id(self) -> None:
        uid = uuid.uuid4()
        file_id = uuid.uuid4()
        result = build_file_metadata(user_id=uid, file_id=file_id)
        assert result.values["file_id"] == str(file_id)

    def test_accepts_string_uuids(self) -> None:
        uid = uuid.uuid4()
        file_id = uuid.uuid4()
        result = build_file_metadata(user_id=str(uid), file_id=str(file_id))
        assert result.values["user_id"] == str(uid)

    def test_invalid_user_id_raises(self) -> None:
        with pytest.raises(InvalidStorageMetadataError):
            build_file_metadata(user_id="not-uuid", file_id=uuid.uuid4())  # type: ignore[arg-type]


class TestFilterEmptyMetadata:
    def test_removes_none_values(self) -> None:
        uid = uuid.uuid4()
        result = filter_empty_metadata({"user_id": str(uid), "empty": None})
        assert "empty" not in result.values
        assert "user_id" in result.values

    def test_none_returns_empty(self) -> None:
        result = filter_empty_metadata(None)
        assert result.values == {}


class TestRemoveMetadataKeys:
    def test_removes_specified_key(self) -> None:
        uid = uuid.uuid4()
        result = remove_metadata_keys({"user_id": str(uid), "file_id": str(uid)}, "user_id")
        assert "user_id" not in result.values
        assert "file_id" in result.values

    def test_missing_key_is_noop(self) -> None:
        uid = uuid.uuid4()
        result = remove_metadata_keys({"user_id": str(uid)}, "nonexistent")
        assert "user_id" in result.values


class TestPickMetadataKeys:
    def test_keeps_only_specified_keys(self) -> None:
        uid = uuid.uuid4()
        result = pick_metadata_keys(
            {"user_id": str(uid), "file_id": str(uid)}, "user_id"
        )
        assert "user_id" in result.values
        assert "file_id" not in result.values


class TestHasMetadataKey:
    def test_returns_true_for_present_key(self) -> None:
        uid = uuid.uuid4()
        assert has_metadata_key({"user_id": str(uid)}, "user_id") is True

    def test_returns_false_for_absent_key(self) -> None:
        assert has_metadata_key({"user_id": "x"}, "file_id") is False


class TestGetMetadataValue:
    def test_returns_value_for_present_key(self) -> None:
        uid = uuid.uuid4()
        result = get_metadata_value({"user_id": str(uid)}, "user_id")
        assert result == str(uid)

    def test_returns_default_for_absent_key(self) -> None:
        result = get_metadata_value({}, "user_id", default="fallback")
        assert result == "fallback"

    def test_returns_none_default_for_absent_key(self) -> None:
        result = get_metadata_value({}, "user_id")
        assert result is None


class TestValidateMetadataSkipsEmptyStringValue:
    def test_whitespace_only_value_dropped(self) -> None:
        # StorageObjectMetadata минует normalize_metadata; validate_metadata
        # сама должна отбрасывать значения, нормализуемые в None (строка 225).
        meta = StorageObjectMetadata(values={"user_id": "x", "blank": "   "})
        result = validate_metadata(meta)
        assert "blank" not in result.values
        assert "user_id" in result.values


class TestBuildFileVersionMetadata:
    def test_includes_version_id(self) -> None:
        uid = uuid.uuid4()
        file_id = uuid.uuid4()
        version_id = uuid.uuid4()
        result = build_file_version_metadata(
            user_id=uid, file_id=file_id, version_id=version_id
        )
        assert result.values["version_id"] == str(version_id)
        assert result.values["user_id"] == str(uid)

    def test_with_checksum_and_algorithm(self) -> None:
        result = build_file_version_metadata(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            checksum="deadbeef",
            checksum_algorithm=StorageChecksumAlgorithm.SHA256,
        )
        assert result.values["checksum"] == "deadbeef"
        assert result.values["checksum_algorithm"] == StorageChecksumAlgorithm.SHA256.value


class TestBuildUploadMetadata:
    def test_minimal(self) -> None:
        uid = uuid.uuid4()
        session_id = uuid.uuid4()
        result = build_upload_metadata(user_id=uid, upload_session_id=session_id)
        assert result.values["user_id"] == str(uid)
        assert result.values["upload_session_id"] == str(session_id)

    def test_with_optional_file_id_and_created_by(self) -> None:
        uid = uuid.uuid4()
        session_id = uuid.uuid4()
        file_id = uuid.uuid4()
        created_by = uuid.uuid4()
        result = build_upload_metadata(
            user_id=uid,
            upload_session_id=session_id,
            file_id=file_id,
            created_by=created_by,
            original_filename="report.pdf",
            content_type="application/pdf",
        )
        assert result.values["file_id"] == str(file_id)
        assert result.values["created_by"] == str(created_by)
        assert result.values["content_type"] == "application/pdf"

    def test_extra_overrides_base(self) -> None:
        uid = uuid.uuid4()
        session_id = uuid.uuid4()
        result = build_upload_metadata(
            user_id=uid,
            upload_session_id=session_id,
            extra={"content_type": "text/plain"},
        )
        assert result.values["content_type"] == "text/plain"


class TestBuildArchiveMetadata:
    def test_defaults(self) -> None:
        uid = uuid.uuid4()
        task_id = uuid.uuid4()
        result = build_archive_metadata(user_id=uid, task_id=task_id)
        assert result.values["user_id"] == str(uid)
        assert result.values["task_id"] == str(task_id)
        assert result.values["content_type"] == "application/zip"
        assert result.values["original_filename"] == "archive.zip"

    def test_with_created_by_and_checksum(self) -> None:
        result = build_archive_metadata(
            user_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            created_by=uuid.uuid4(),
            checksum="abc123",
            checksum_algorithm="sha256",
        )
        assert result.values["checksum"] == "abc123"
        assert result.values["checksum_algorithm"] == "sha256"
        assert "created_by" in result.values


class TestBuildPreviewMetadata:
    def test_minimal(self) -> None:
        uid = uuid.uuid4()
        file_id = uuid.uuid4()
        result = build_preview_metadata(user_id=uid, file_id=file_id)
        assert result.values["user_id"] == str(uid)
        assert result.values["file_id"] == str(file_id)

    def test_with_task_id_and_version(self) -> None:
        uid = uuid.uuid4()
        file_id = uuid.uuid4()
        version_id = uuid.uuid4()
        task_id = uuid.uuid4()
        result = build_preview_metadata(
            user_id=uid,
            file_id=file_id,
            version_id=version_id,
            task_id=task_id,
            content_type="image/png",
        )
        assert result.values["task_id"] == str(task_id)
        assert result.values["version_id"] == str(version_id)
        assert result.values["content_type"] == "image/png"


class TestBuildPublicMetadata:
    def test_minimal(self) -> None:
        link_id = uuid.uuid4()
        file_id = uuid.uuid4()
        result = build_public_metadata(public_link_id=link_id, file_id=file_id)
        assert result.values["public_link_id"] == str(link_id)
        assert result.values["file_id"] == str(file_id)

    def test_with_version_and_checksum(self) -> None:
        link_id = uuid.uuid4()
        file_id = uuid.uuid4()
        version_id = uuid.uuid4()
        result = build_public_metadata(
            public_link_id=link_id,
            file_id=file_id,
            version_id=version_id,
            checksum="ff00",
            checksum_algorithm=StorageChecksumAlgorithm.MD5,
            original_filename="doc.txt",
            content_type="text/plain",
        )
        assert result.values["version_id"] == str(version_id)
        assert result.values["checksum"] == "ff00"
        assert result.values["checksum_algorithm"] == StorageChecksumAlgorithm.MD5.value


class TestNormalizeUuidLikeBranches:
    def test_empty_string_uuid_raises(self) -> None:
        # _normalize_uuid_like через build_file_metadata (строка 866).
        with pytest.raises(InvalidStorageMetadataError):
            build_file_metadata(user_id="   ", file_id=uuid.uuid4())

    def test_unsupported_uuid_type_raises(self) -> None:
        # Значение не str и не UUID (строка 883).
        with pytest.raises(InvalidStorageMetadataError):
            build_file_metadata(user_id=12345, file_id=uuid.uuid4())  # type: ignore[arg-type]


class TestNormalizeChecksumAlgorithmBranches:
    def test_string_algorithm_normalized(self) -> None:
        result = build_file_metadata(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            checksum_algorithm="SHA256",
        )
        assert result.values["checksum_algorithm"] == StorageChecksumAlgorithm.SHA256.value

    def test_blank_string_algorithm_dropped(self) -> None:
        result = build_file_metadata(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            checksum_algorithm="   ",
        )
        assert "checksum_algorithm" not in result.values

    def test_none_algorithm_dropped(self) -> None:
        result = build_file_metadata(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            checksum_algorithm=None,
        )
        assert "checksum_algorithm" not in result.values

    def test_unsupported_algorithm_string_raises(self) -> None:
        with pytest.raises(InvalidStorageMetadataError):
            build_file_metadata(
                user_id=uuid.uuid4(),
                file_id=uuid.uuid4(),
                checksum_algorithm="crc32",
            )

    def test_invalid_algorithm_type_raises(self) -> None:
        with pytest.raises(InvalidStorageMetadataError):
            build_file_metadata(
                user_id=uuid.uuid4(),
                file_id=uuid.uuid4(),
                checksum_algorithm=123,  # type: ignore[arg-type]
            )
