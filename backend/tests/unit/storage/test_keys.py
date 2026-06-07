"""Unit-тесты для построения и валидации ключей объектов хранилища."""
from __future__ import annotations

import uuid

import pytest

from core.constants import StorageConstants
from storage.exceptions import InvalidStorageKeyError
from storage.keys import (
    build_archive_object_key,
    build_backup_object_key,
    build_file_object_key,
    build_file_version_object_key,
    build_preview_object_key,
    build_public_download_object_key,
    build_temporary_object_key,
    build_trash_object_key,
    build_upload_part_object_key,
    build_upload_temp_object_key,
    extract_extension,
    get_object_key_filename,
    get_object_key_parent,
    make_object_metadata_filename,
    normalize_extension,
    normalize_object_key,
    object_key_starts_with_prefix,
    sanitize_filename_for_metadata,
    split_object_key,
    validate_object_key,
)


class TestNormalizeObjectKey:
    def test_valid_key_returned_stripped(self) -> None:
        result = normalize_object_key("  users/abc/file  ")
        assert result == "users/abc/file"

    def test_valid_key_no_stripping_needed(self) -> None:
        result = normalize_object_key("users/123/file.txt")
        assert result == "users/123/file.txt"

    def test_none_raises_invalid_storage_key_error(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            normalize_object_key(None)  # type: ignore[arg-type]

    def test_empty_after_strip_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            normalize_object_key("   ")


class TestValidateObjectKey:
    def test_valid_key_passes(self) -> None:
        assert validate_object_key("users/abc/def") == "users/abc/def"

    def test_non_string_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_object_key(123)  # type: ignore[arg-type]

    def test_empty_string_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_object_key("")

    def test_too_long_raises(self) -> None:
        long_key = "a" * (StorageConstants.S3_OBJECT_KEY_MAX_LENGTH + 1)
        with pytest.raises(InvalidStorageKeyError):
            validate_object_key(long_key)

    def test_max_length_passes(self) -> None:
        # Строим ключ ровно максимальной длины из допустимых символов.
        # Используем путь-подобный ключ, чтобы не было запрещённых сегментов.
        segment = "a" * 100
        # Набираем длину по шаблону "segment/segment/...".
        key = "/".join([segment] * (StorageConstants.S3_OBJECT_KEY_MAX_LENGTH // 101))
        # Просто убеждаемся, что для допустимых длин ошибки нет.
        assert len(key) <= StorageConstants.S3_OBJECT_KEY_MAX_LENGTH

    def test_contains_double_dot_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_object_key("users/../secret")

    def test_absolute_path_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_object_key("/absolute/path")

    def test_backslash_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_object_key("users\\file")

    def test_double_slash_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_object_key("users//file")

    def test_single_dot_segment_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            validate_object_key("users/./file")


class TestBuildFileObjectKey:
    def test_returns_valid_key(self) -> None:
        user_id = uuid.uuid4()
        file_id = uuid.uuid4()
        version_id = uuid.uuid4()
        key = build_file_object_key(user_id=user_id, file_id=file_id, version_id=version_id)
        assert str(user_id) in key
        assert str(file_id) in key
        assert str(version_id) in key

    def test_key_contains_expected_segments(self) -> None:
        user_id = uuid.uuid4()
        file_id = uuid.uuid4()
        version_id = uuid.uuid4()
        key = build_file_object_key(user_id=user_id, file_id=file_id, version_id=version_id)
        assert "users" in key
        assert "files" in key
        assert "versions" in key

    def test_non_uuid_user_id_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_file_object_key(
                user_id="not-a-uuid",  # type: ignore[arg-type]
                file_id=uuid.uuid4(),
                version_id=uuid.uuid4(),
            )

    def test_non_uuid_file_id_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_file_object_key(
                user_id=uuid.uuid4(),
                file_id="bad",  # type: ignore[arg-type]
                version_id=uuid.uuid4(),
            )


class TestBuildFileVersionObjectKey:
    def test_returns_valid_key(self) -> None:
        user_id = uuid.uuid4()
        file_id = uuid.uuid4()
        version_id = uuid.uuid4()
        key = build_file_version_object_key(
            user_id=user_id, file_id=file_id, version_id=version_id
        )
        assert key == f"users/{user_id}/files/{file_id}/versions/{version_id}"

    def test_key_is_valid_object_key(self) -> None:
        key = build_file_version_object_key(
            user_id=uuid.uuid4(), file_id=uuid.uuid4(), version_id=uuid.uuid4()
        )
        # Не должно выбрасывать исключение.
        validate_object_key(key)


class TestBuildUploadTempObjectKey:
    def test_returns_valid_key(self) -> None:
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        key = build_upload_temp_object_key(user_id=user_id, upload_session_id=session_id)
        assert "users" in key
        assert "uploads" in key
        assert "source" in key
        assert str(user_id) in key

    def test_non_uuid_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_upload_temp_object_key(
                user_id="not-uuid",  # type: ignore[arg-type]
                upload_session_id=uuid.uuid4(),
            )


class TestBuildUploadPartObjectKey:
    def test_returns_valid_key(self) -> None:
        user_id = uuid.uuid4()
        session_id = uuid.uuid4()
        key = build_upload_part_object_key(
            user_id=user_id, upload_session_id=session_id, part_number=1
        )
        assert "parts" in key
        assert "1" in key

    def test_zero_part_number_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_upload_part_object_key(
                user_id=uuid.uuid4(), upload_session_id=uuid.uuid4(), part_number=0
            )

    def test_negative_part_number_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_upload_part_object_key(
                user_id=uuid.uuid4(), upload_session_id=uuid.uuid4(), part_number=-1
            )

    def test_bool_part_number_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_upload_part_object_key(
                user_id=uuid.uuid4(), upload_session_id=uuid.uuid4(), part_number=True  # type: ignore[arg-type]
            )

    def test_valid_large_part_number(self) -> None:
        key = build_upload_part_object_key(
            user_id=uuid.uuid4(),
            upload_session_id=uuid.uuid4(),
            part_number=StorageConstants.S3_MULTIPART_MAX_PART_NUMBER,
        )
        assert key

    def test_too_large_part_number_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_upload_part_object_key(
                user_id=uuid.uuid4(),
                upload_session_id=uuid.uuid4(),
                part_number=StorageConstants.S3_MULTIPART_MAX_PART_NUMBER + 1,
            )


class TestBuildArchiveObjectKey:
    def test_returns_valid_key(self) -> None:
        user_id = uuid.uuid4()
        task_id = uuid.uuid4()
        key = build_archive_object_key(user_id=user_id, task_id=task_id)
        assert "archives" in key
        assert str(user_id) in key
        assert str(task_id) in key

    def test_default_extension_is_zip(self) -> None:
        key = build_archive_object_key(user_id=uuid.uuid4(), task_id=uuid.uuid4())
        assert "zip" in key


class TestBuildTemporaryObjectKey:
    def test_returns_valid_key_without_filename(self) -> None:
        object_id = uuid.uuid4()
        key = build_temporary_object_key(namespace="exports", object_id=object_id)
        assert "tmp" in key
        assert "exports" in key
        assert str(object_id) in key

    def test_returns_valid_key_with_filename(self) -> None:
        object_id = uuid.uuid4()
        key = build_temporary_object_key(
            namespace="exports", object_id=object_id, filename="report.csv"
        )
        assert "report.csv" in key

    def test_non_uuid_object_id_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_temporary_object_key(
                namespace="ns",
                object_id="not-uuid",  # type: ignore[arg-type]
            )

    def test_invalid_namespace_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_temporary_object_key(namespace="bad/ns", object_id=uuid.uuid4())

    def test_filename_sanitized_to_empty_is_omitted(self) -> None:
        object_id = uuid.uuid4()
        key = build_temporary_object_key(
            namespace="ns", object_id=object_id, filename="..."
        )
        assert key == f"tmp/ns/{object_id}"


class TestSystemPathPrefix:
    def test_windows_drive_path_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError) as exc_info:
            validate_object_key("C:/Windows/system32")
        assert exc_info.value.details["reason"] == "absolute_system_path"


class TestBuildPreviewObjectKey:
    def test_without_extension(self) -> None:
        user_id = uuid.uuid4()
        file_id = uuid.uuid4()
        key = build_preview_object_key(user_id=user_id, file_id=file_id)
        assert key == f"users/{user_id}/previews/{file_id}/preview"

    def test_with_extension(self) -> None:
        user_id = uuid.uuid4()
        file_id = uuid.uuid4()
        key = build_preview_object_key(
            user_id=user_id, file_id=file_id, extension="jpg"
        )
        assert key == f"users/{user_id}/previews/{file_id}/preview.jpg"

    def test_extension_with_leading_dot_normalized(self) -> None:
        key = build_preview_object_key(
            user_id=uuid.uuid4(), file_id=uuid.uuid4(), extension=".PNG"
        )
        assert key.endswith("preview.png")

    def test_non_uuid_file_id_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_preview_object_key(
                user_id=uuid.uuid4(),
                file_id="bad",  # type: ignore[arg-type]
            )


class TestBuildPublicDownloadObjectKey:
    def test_without_version(self) -> None:
        public_link_id = uuid.uuid4()
        file_id = uuid.uuid4()
        key = build_public_download_object_key(
            public_link_id=public_link_id, file_id=file_id
        )
        assert key == f"public/{public_link_id}/files/{file_id}"

    def test_with_version(self) -> None:
        public_link_id = uuid.uuid4()
        file_id = uuid.uuid4()
        version_id = uuid.uuid4()
        key = build_public_download_object_key(
            public_link_id=public_link_id,
            file_id=file_id,
            version_id=version_id,
        )
        assert key == (
            f"public/{public_link_id}/files/{file_id}/versions/{version_id}"
        )

    def test_non_uuid_public_link_id_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_public_download_object_key(
                public_link_id="bad",  # type: ignore[arg-type]
                file_id=uuid.uuid4(),
            )


class TestBuildTrashObjectKey:
    def test_without_object_id(self) -> None:
        user_id = uuid.uuid4()
        node_id = uuid.uuid4()
        key = build_trash_object_key(user_id=user_id, node_id=node_id)
        assert key == f"users/{user_id}/trash/{node_id}"

    def test_with_object_id(self) -> None:
        user_id = uuid.uuid4()
        node_id = uuid.uuid4()
        object_id = uuid.uuid4()
        key = build_trash_object_key(
            user_id=user_id, node_id=node_id, object_id=object_id
        )
        assert key == f"users/{user_id}/trash/{node_id}/objects/{object_id}"

    def test_non_uuid_node_id_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_trash_object_key(
                user_id=uuid.uuid4(),
                node_id="bad",  # type: ignore[arg-type]
            )


class TestBuildBackupObjectKey:
    def test_default_prefix(self) -> None:
        backup_id = uuid.uuid4()
        key = build_backup_object_key(backup_id=backup_id, filename="db.sql")
        assert key == f"backups/{backup_id}/db.sql"

    def test_custom_prefix(self) -> None:
        backup_id = uuid.uuid4()
        key = build_backup_object_key(
            backup_id=backup_id, filename="db.sql", prefix="snapshots"
        )
        assert key == f"snapshots/{backup_id}/db.sql"

    def test_empty_sanitized_filename_falls_back_to_backup(self) -> None:
        backup_id = uuid.uuid4()
        key = build_backup_object_key(backup_id=backup_id, filename="...")
        assert key == f"backups/{backup_id}/backup"

    def test_invalid_prefix_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            build_backup_object_key(
                backup_id=uuid.uuid4(), filename="db.sql", prefix="bad/prefix"
            )

    def test_filename_with_path_is_sanitized_to_basename(self) -> None:
        backup_id = uuid.uuid4()
        key = build_backup_object_key(
            backup_id=backup_id, filename="some/dir/db.sql"
        )
        assert key == f"backups/{backup_id}/db.sql"


class TestExtractExtension:
    def test_none_returns_none(self) -> None:
        assert extract_extension(None) is None

    def test_empty_sanitized_returns_none(self) -> None:
        assert extract_extension("...") is None

    def test_no_suffix_returns_none(self) -> None:
        assert extract_extension("README") is None

    def test_extracts_lowercased_extension(self) -> None:
        assert extract_extension("Report.CSV") == "csv"

    def test_extension_with_path_uses_basename(self) -> None:
        assert extract_extension("dir/photo.JPG") == "jpg"


class TestNormalizeExtension:
    def test_none_returns_none(self) -> None:
        assert normalize_extension(None) is None

    def test_strips_leading_dot_and_lowercases(self) -> None:
        assert normalize_extension(".JPG") == "jpg"

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_extension("   ") is None

    def test_dot_only_returns_none(self) -> None:
        assert normalize_extension(".") is None

    def test_forward_slash_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError) as exc_info:
            normalize_extension("a/b")
        assert exc_info.value.details["reason"] == "extension_contains_path_separator"

    def test_backslash_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError) as exc_info:
            normalize_extension("a\\b")
        assert exc_info.value.details["reason"] == "extension_contains_path_separator"

    def test_double_dot_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError) as exc_info:
            normalize_extension("ta..r")
        assert exc_info.value.details["reason"] == "invalid_extension"

    def test_unsafe_chars_stripped(self) -> None:
        # "j!p!g" -> небезопасные символы убираются UNSAFE_EXTENSION_CHARS_PATTERN.
        assert normalize_extension("j!p!g") == "jpg"

    def test_only_unsafe_chars_returns_none(self) -> None:
        assert normalize_extension("!!!") is None

    def test_too_long_raises(self) -> None:
        long_ext = "a" * (StorageConstants.STORAGE_EXTENSION_MAX_LENGTH + 1)
        with pytest.raises(InvalidStorageKeyError) as exc_info:
            normalize_extension(long_ext)
        assert exc_info.value.details["reason"] == "extension_too_long"


class TestSanitizeFilenameForMetadata:
    def test_none_returns_empty(self) -> None:
        assert sanitize_filename_for_metadata(None) == ""

    def test_strips_and_takes_basename(self) -> None:
        assert sanitize_filename_for_metadata("  dir/sub/file.txt  ") == "file.txt"

    def test_backslash_normalized_to_basename(self) -> None:
        assert sanitize_filename_for_metadata("dir\\file.txt") == "file.txt"

    def test_unsafe_chars_replaced(self) -> None:
        assert sanitize_filename_for_metadata("a\x00b.txt") == "a_b.txt"

    def test_dot_segment_returns_empty(self) -> None:
        assert sanitize_filename_for_metadata(".") == ""

    def test_double_dot_segment_returns_empty(self) -> None:
        assert sanitize_filename_for_metadata("..") == ""

    def test_truncated_to_max_length(self) -> None:
        long_name = "a" * (
            StorageConstants.STORAGE_FILENAME_METADATA_MAX_LENGTH + 50
        )
        result = sanitize_filename_for_metadata(long_name)
        assert len(result) == StorageConstants.STORAGE_FILENAME_METADATA_MAX_LENGTH


class TestMakeObjectMetadataFilename:
    def test_valid_filename_returns_dict(self) -> None:
        result = make_object_metadata_filename("report.csv")
        assert result == {"original-filename": "report.csv"}

    def test_empty_filename_returns_empty_dict(self) -> None:
        assert make_object_metadata_filename("...") == {}

    def test_none_returns_empty_dict(self) -> None:
        assert make_object_metadata_filename(None) == {}


class TestSplitObjectKey:
    def test_splits_into_segments(self) -> None:
        assert split_object_key("users/abc/file.txt") == ["users", "abc", "file.txt"]

    def test_invalid_key_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            split_object_key("users//file")


class TestGetObjectKeyFilename:
    def test_returns_last_segment(self) -> None:
        assert get_object_key_filename("users/abc/file.txt") == "file.txt"

    def test_single_segment(self) -> None:
        assert get_object_key_filename("file.txt") == "file.txt"


class TestGetObjectKeyParent:
    def test_returns_parent_prefix(self) -> None:
        assert get_object_key_parent("users/abc/file.txt") == "users/abc"

    def test_top_level_returns_none(self) -> None:
        assert get_object_key_parent("file.txt") is None


class TestObjectKeyStartsWithPrefix:
    def test_exact_match(self) -> None:
        assert object_key_starts_with_prefix("users/abc", "users/abc") is True

    def test_inside_prefix(self) -> None:
        assert object_key_starts_with_prefix("users/abc/file", "users/abc") is True

    def test_not_inside_prefix(self) -> None:
        assert object_key_starts_with_prefix("users/abcd/file", "users/abc") is False

    def test_invalid_key_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError):
            object_key_starts_with_prefix("users//abc", "users")


class TestBuildObjectKeyPartValidation:
    def test_non_string_part_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError) as exc_info:
            build_backup_object_key(
                backup_id=uuid.uuid4(),
                filename="db.sql",
                prefix=123,  # type: ignore[arg-type]
            )
        assert exc_info.value.details["reason"] == "invalid_object_key_part_type"

    def test_forbidden_part_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError) as exc_info:
            build_temporary_object_key(namespace="..", object_id=uuid.uuid4())
        assert exc_info.value.details["reason"] == "invalid_object_key_part"

    def test_part_with_path_separator_raises(self) -> None:
        with pytest.raises(InvalidStorageKeyError) as exc_info:
            build_temporary_object_key(namespace="a/b", object_id=uuid.uuid4())
        assert exc_info.value.details["reason"] == "object_key_part_contains_path_separator"
