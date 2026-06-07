"""Unit-тесты для StorageMultipartManager."""
from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.constants import StorageConstants
from storage.buckets import StorageBucketNameValidator
from storage.exceptions import (
    StorageConnectionError,
    StorageError,
    StorageMultipartUploadError,
    StorageMultipartUploadNotFoundError,
)
from storage.multipart import StorageMultipartManager, _CompletionPart
from storage.objects import StorageObjectManager
from storage.types import StorageUploadPart


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_validator() -> StorageBucketNameValidator:
    return StorageBucketNameValidator(min_length=3, max_length=63)


def _make_stat_result():
    stat = MagicMock()
    stat.size = 100
    stat.etag = "final-etag"
    stat.content_type = "application/octet-stream"
    stat.last_modified = None
    stat.metadata = None
    stat._metadata = None
    stat.http_headers = None
    stat._http_headers = None
    stat.headers = None
    stat._headers = None
    return stat


def make_raw_client():
    raw = MagicMock()
    raw._create_multipart_upload = MagicMock(return_value="upload-id-123")
    raw._upload_part = MagicMock(return_value="part-etag-1")
    raw._complete_multipart_upload = MagicMock(return_value=MagicMock())
    raw._abort_multipart_upload = MagicMock(return_value=None)
    raw._list_parts = MagicMock(return_value=[])
    raw.stat_object = MagicMock(return_value=_make_stat_result())
    return raw


def make_client():
    raw = make_raw_client()
    client = MagicMock()
    client.get_raw_client = MagicMock(return_value=raw)

    async def execute(fn, *args, operation_name=None, **kwargs):
        if callable(fn):
            return fn(*args, **kwargs)
        return fn

    client.execute = AsyncMock(side_effect=execute)
    return client, raw


def make_manager():
    client, raw = make_client()
    validator = make_validator()
    obj_manager = StorageObjectManager(client=client, bucket_name_validator=validator)
    mp_manager = StorageMultipartManager(
        client=client,
        bucket_name_validator=validator,
        object_manager=obj_manager,
    )
    return mp_manager, client, raw


# ---------------------------------------------------------------------------
# create_multipart_upload
# ---------------------------------------------------------------------------

class TestCreateMultipartUpload:
    @pytest.mark.asyncio
    async def test_create_returns_upload_id(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.create_multipart_upload(
            bucket="test-bucket",
            object_key="large-file.bin",
        )
        assert result.upload_id == "upload-id-123"
        assert result.bucket == "test-bucket"
        assert result.object_key == "large-file.bin"

    @pytest.mark.asyncio
    async def test_create_with_content_type(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.create_multipart_upload(
            bucket="test-bucket",
            object_key="video.mp4",
            content_type="video/mp4",
        )
        assert result.upload_id == "upload-id-123"

    @pytest.mark.asyncio
    async def test_create_storage_error_raises_multipart_error(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "create_multipart_upload":
                raise StorageError("failed", details={"reason": "error"})
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises((StorageMultipartUploadError, StorageError)):
            await manager.create_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
            )

    @pytest.mark.asyncio
    async def test_create_with_empty_upload_id_raises(self) -> None:
        manager, client, raw = make_manager()
        raw._create_multipart_upload.return_value = ""  # пустой upload_id

        with pytest.raises(StorageMultipartUploadError):
            await manager.create_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
            )

    @pytest.mark.asyncio
    async def test_create_with_none_upload_id_raises(self) -> None:
        manager, client, raw = make_manager()
        raw._create_multipart_upload.return_value = None  # type: ignore[assignment]

        with pytest.raises(StorageMultipartUploadError):
            await manager.create_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
            )


# ---------------------------------------------------------------------------
# upload_part
# ---------------------------------------------------------------------------

class TestUploadPart:
    @pytest.mark.asyncio
    async def test_upload_part_returns_part_info(self) -> None:
        manager, client, raw = make_manager()
        raw._upload_part.return_value = "part-etag-1"

        result = await manager.upload_part(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            part_number=1,
            data=b"chunk data here",
            size_bytes=15,
        )
        assert result.part_number == 1
        assert result.etag == "part-etag-1"

    @pytest.mark.asyncio
    async def test_upload_part_with_bytearray(self) -> None:
        manager, client, raw = make_manager()
        data = bytearray(b"chunk bytes")
        result = await manager.upload_part(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            part_number=1,
            data=data,
            size_bytes=11,
        )
        assert result.part_number == 1

    @pytest.mark.asyncio
    async def test_upload_part_invalid_part_number_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            await manager.upload_part(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number=0,  # недопустимо (должно быть >= 1)
                data=b"chunk",
                size_bytes=5,
            )

    @pytest.mark.asyncio
    async def test_upload_part_invalid_upload_id_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            await manager.upload_part(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="",  # пустой upload_id
                part_number=1,
                data=b"chunk",
                size_bytes=5,
            )

    @pytest.mark.asyncio
    async def test_upload_part_storage_error_raises(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "upload_part":
                raise StorageError("upload failed", details={"reason": "error"})
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises((StorageMultipartUploadError, StorageError)):
            await manager.upload_part(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number=1,
                data=b"chunk data here!",
                size_bytes=16,
            )


# ---------------------------------------------------------------------------
# complete_multipart_upload
# ---------------------------------------------------------------------------

class TestCompleteMultipartUpload:
    @pytest.mark.asyncio
    async def test_complete_returns_object_info(self) -> None:
        manager, client, raw = make_manager()
        parts = [StorageUploadPart(part_number=1, etag="etag1", size_bytes=15)]
        result = await manager.complete_multipart_upload(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            parts=parts,
        )
        assert result.bucket == "test-bucket"
        assert result.etag == "final-etag"

    @pytest.mark.asyncio
    async def test_complete_with_empty_parts_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            await manager.complete_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                parts=[],
            )

    @pytest.mark.asyncio
    async def test_complete_with_tuple_parts(self) -> None:
        manager, client, raw = make_manager()
        parts = [(1, "etag1"), (2, "etag2")]
        result = await manager.complete_multipart_upload(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            parts=parts,
        )
        assert result.bucket == "test-bucket"

    @pytest.mark.asyncio
    async def test_complete_with_dict_parts(self) -> None:
        manager, client, raw = make_manager()
        parts = [{"part_number": 1, "etag": "etag1"}]
        result = await manager.complete_multipart_upload(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            parts=parts,
        )
        assert result.bucket == "test-bucket"

    @pytest.mark.asyncio
    async def test_complete_storage_error_raises(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "complete_multipart_upload":
                raise StorageError("complete failed", details={"reason": "error"})
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_raises)

        parts = [StorageUploadPart(part_number=1, etag="etag1", size_bytes=15)]
        with pytest.raises((StorageMultipartUploadError, StorageError)):
            await manager.complete_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                parts=parts,
            )

    @pytest.mark.asyncio
    async def test_complete_duplicate_parts_raises(self) -> None:
        manager, client, raw = make_manager()
        parts = [
            StorageUploadPart(part_number=1, etag="etag1", size_bytes=15),
            StorageUploadPart(part_number=1, etag="etag2", size_bytes=15),  # дубликат
        ]
        with pytest.raises(StorageMultipartUploadError):
            await manager.complete_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                parts=parts,
            )


# ---------------------------------------------------------------------------
# abort_multipart_upload
# ---------------------------------------------------------------------------

class TestAbortMultipartUpload:
    @pytest.mark.asyncio
    async def test_abort_returns_true(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.abort_multipart_upload(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_abort_missing_upload_raises_when_not_missing_ok(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageMultipartUploadNotFoundError(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
            )

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageMultipartUploadNotFoundError):
            await manager.abort_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
            )

    @pytest.mark.asyncio
    async def test_abort_missing_upload_returns_false_when_missing_ok(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageMultipartUploadNotFoundError(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
            )

        client.execute = AsyncMock(side_effect=execute_raises)

        result = await manager.abort_multipart_upload(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            missing_ok=True,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_abort_invalid_upload_id_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            await manager.abort_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="",  # пустой upload_id
            )


# ---------------------------------------------------------------------------
# list_uploaded_parts
# ---------------------------------------------------------------------------

class TestListUploadedParts:
    @pytest.mark.asyncio
    async def test_list_returns_empty_list(self) -> None:
        manager, client, raw = make_manager()
        raw._list_parts.return_value = []
        result = await manager.list_uploaded_parts(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_list_returns_sorted_parts(self) -> None:
        manager, client, raw = make_manager()
        part2 = MagicMock()
        part2.part_number = 2
        part2.etag = "etag2"
        part2.size = 100
        part2.last_modified = None
        part1 = MagicMock()
        part1.part_number = 1
        part1.etag = "etag1"
        part1.size = 100
        part1.last_modified = None
        raw._list_parts.return_value = [part2, part1]
        result = await manager.list_uploaded_parts(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
        )
        assert len(result) == 2
        assert result[0].part_number == 1
        assert result[1].part_number == 2


# ---------------------------------------------------------------------------
# validate_* methods
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validate_upload_id_valid(self) -> None:
        from storage.multipart import StorageMultipartManager
        result = StorageMultipartManager.validate_upload_id("  valid-id  ")
        assert result == "valid-id"

    def test_validate_upload_id_empty_raises(self) -> None:
        with pytest.raises(StorageMultipartUploadError):
            StorageMultipartManager.validate_upload_id("   ")

    def test_validate_upload_id_non_string_raises(self) -> None:
        with pytest.raises(StorageMultipartUploadError):
            StorageMultipartManager.validate_upload_id(123)  # type: ignore[arg-type]

    def test_build_completion_parts_with_unsupported_type_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.build_completion_parts([42])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# create_multipart_upload — additional branches
# ---------------------------------------------------------------------------

class TestCreateMultipartUploadExtra:
    @pytest.mark.asyncio
    async def test_create_passes_headers_to_raw_client(self) -> None:
        manager, client, raw = make_manager()

        await manager.create_multipart_upload(
            bucket="test-bucket",
            object_key="video.mp4",
            content_type="video/mp4",
            metadata={"author": "alice"},
        )

        # _create_multipart_upload(bucket, key, headers)
        args, _ = raw._create_multipart_upload.call_args
        assert args[0] == "test-bucket"
        assert args[1] == "video.mp4"
        headers = args[2]
        assert headers["Content-Type"] == "video/mp4"
        # Пользовательские метаданные сворачиваются в заголовки amz-meta-*.
        assert any("alice" == value for value in headers.values())

    @pytest.mark.asyncio
    async def test_create_whitespace_only_upload_id_raises(self) -> None:
        manager, client, raw = make_manager()
        raw._create_multipart_upload.return_value = "   "

        with pytest.raises(StorageMultipartUploadError):
            await manager.create_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
            )

    @pytest.mark.asyncio
    async def test_create_strips_upload_id(self) -> None:
        manager, client, raw = make_manager()
        raw._create_multipart_upload.return_value = "  padded-id  "

        result = await manager.create_multipart_upload(
            bucket="test-bucket",
            object_key="large-file.bin",
        )
        assert result.upload_id == "padded-id"


# ---------------------------------------------------------------------------
# upload_part — additional branches
# ---------------------------------------------------------------------------

class TestUploadPartExtra:
    @pytest.mark.asyncio
    async def test_upload_part_with_file_like_object(self) -> None:
        manager, client, raw = make_manager()
        raw._upload_part.return_value = "stream-etag"

        result = await manager.upload_part(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            part_number=2,
            data=BytesIO(b"0123456789"),
            size_bytes=10,
        )
        assert result.part_number == 2
        assert result.etag == "stream-etag"
        # Проверяем позиционные аргументы raw-вызова: bucket, key, payload, {}, upload_id, part_number.
        args, _ = raw._upload_part.call_args
        assert args[0] == "test-bucket"
        assert args[2] == b"0123456789"
        assert args[4] == "upload-id-123"
        assert args[5] == 2

    @pytest.mark.asyncio
    async def test_upload_part_etag_from_result_attr_is_stripped(self) -> None:
        manager, client, raw = make_manager()
        result_obj = MagicMock()
        result_obj.etag = '"quoted-etag"'
        raw._upload_part.return_value = result_obj

        result = await manager.upload_part(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            part_number=1,
            data=b"chunk",
            size_bytes=5,
        )
        assert result.etag == "quoted-etag"

    @pytest.mark.asyncio
    async def test_upload_part_etag_falls_back_to_str(self) -> None:
        manager, client, raw = make_manager()

        class NoEtag:
            def __str__(self) -> str:
                return '"fallback-etag"'

        raw._upload_part.return_value = NoEtag()

        result = await manager.upload_part(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            part_number=1,
            data=b"chunk",
            size_bytes=5,
        )
        assert result.etag == "fallback-etag"

    @pytest.mark.asyncio
    async def test_upload_part_empty_etag_raises(self) -> None:
        manager, client, raw = make_manager()
        raw._upload_part.return_value = ""  # откатывается к "" → пустой etag

        with pytest.raises(StorageMultipartUploadError):
            await manager.upload_part(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number=1,
                data=b"chunk",
                size_bytes=5,
            )

    @pytest.mark.asyncio
    async def test_upload_part_none_result_raises_empty_etag(self) -> None:
        manager, client, raw = make_manager()
        raw._upload_part.return_value = None

        with pytest.raises(StorageMultipartUploadError):
            await manager.upload_part(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number=1,
                data=b"chunk",
                size_bytes=5,
            )

    @pytest.mark.asyncio
    async def test_upload_part_invalid_data_type_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            await manager.upload_part(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number=1,
                data=12345,  # type: ignore[arg-type]
                size_bytes=5,
            )

    @pytest.mark.asyncio
    async def test_upload_part_stream_returns_non_bytes_raises(self) -> None:
        manager, client, raw = make_manager()
        stream = MagicMock()
        stream.read = MagicMock(return_value="not-bytes")

        with pytest.raises(StorageMultipartUploadError):
            await manager.upload_part(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number=1,
                data=stream,
                size_bytes=5,
            )

    @pytest.mark.asyncio
    async def test_upload_part_size_mismatch_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            await manager.upload_part(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number=1,
                data=b"short",  # 5 байт
                size_bytes=10,  # несоответствие
            )


# ---------------------------------------------------------------------------
# list_uploaded_parts — additional branches
# ---------------------------------------------------------------------------

class TestListUploadedPartsExtra:
    @pytest.mark.asyncio
    async def test_list_storage_error_maps_to_multipart_error(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "list_uploaded_parts":
                raise StorageError("list failed", details={"reason": "boom"})
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageMultipartUploadError):
            await manager.list_uploaded_parts(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
            )

    @pytest.mark.asyncio
    async def test_list_skips_parts_missing_number_or_etag(self) -> None:
        manager, client, raw = make_manager()
        good = MagicMock()
        good.part_number = 1
        good.etag = '"e1"'
        good.size = 50
        good.last_modified = datetime.now(UTC)
        no_number = MagicMock()
        no_number.part_number = None
        no_number.etag = "e2"
        no_number.size = 50
        no_number.last_modified = None
        no_etag = MagicMock()
        no_etag.part_number = 3
        no_etag.etag = None
        no_etag.size = 50
        no_etag.last_modified = None
        raw._list_parts.return_value = [good, no_number, no_etag]

        result = await manager.list_uploaded_parts(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
        )
        assert len(result) == 1
        assert result[0].part_number == 1
        assert result[0].etag == "e1"
        assert result[0].size_bytes == 50
        assert isinstance(result[0].uploaded_at, datetime)

    @pytest.mark.asyncio
    async def test_list_part_with_none_size_and_bad_last_modified(self) -> None:
        manager, client, raw = make_manager()
        part = MagicMock()
        part.part_number = 1
        part.etag = "e1"
        part.size = None
        part.last_modified = "2020-01-01"  # не datetime
        raw._list_parts.return_value = [part]

        result = await manager.list_uploaded_parts(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
        )
        assert result[0].size_bytes is None
        assert result[0].uploaded_at is None

    @pytest.mark.asyncio
    async def test_list_invalid_max_parts_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            await manager.list_uploaded_parts(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                max_parts=0,
            )

    @pytest.mark.asyncio
    async def test_list_invalid_marker_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            await manager.list_uploaded_parts(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number_marker=-1,
            )


# ---------------------------------------------------------------------------
# abort_multipart_upload — error mapping branches
# ---------------------------------------------------------------------------

class TestAbortMultipartUploadExtra:
    @pytest.mark.asyncio
    async def test_abort_generic_storage_error_maps_and_raises(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError("abort failed", details={"reason": "boom"})

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageMultipartUploadError):
            await manager.abort_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
            )

    @pytest.mark.asyncio
    async def test_abort_missing_ok_converts_404_storage_error_to_false(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError(
                "not found",
                details={"code": "NoSuchUpload", "status_code": 404},
            )

        client.execute = AsyncMock(side_effect=execute_raises)

        result = await manager.abort_multipart_upload(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            missing_ok=True,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_abort_missing_ok_reraises_non_404_storage_error(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError("server error", details={"status_code": 500})

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageMultipartUploadError):
            await manager.abort_multipart_upload(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                missing_ok=True,
            )


# ---------------------------------------------------------------------------
# validate_part_number
# ---------------------------------------------------------------------------

class TestValidatePartNumber:
    def test_non_int_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_part_number("1")  # type: ignore[arg-type]

    def test_bool_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_part_number(True)  # type: ignore[arg-type]

    def test_too_large_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_part_number(
                StorageConstants.S3_MULTIPART_MAX_PART_NUMBER + 1,
            )

    def test_valid_returns_value(self) -> None:
        manager, client, raw = make_manager()
        assert manager.validate_part_number(5) == 5


# ---------------------------------------------------------------------------
# validate_part_number_marker
# ---------------------------------------------------------------------------

class TestValidatePartNumberMarker:
    def test_non_int_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_part_number_marker("0")  # type: ignore[arg-type]

    def test_negative_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_part_number_marker(-1)

    def test_too_large_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_part_number_marker(
                StorageConstants.S3_MULTIPART_MAX_PART_NUMBER + 1,
            )

    def test_zero_allowed(self) -> None:
        manager, client, raw = make_manager()
        assert manager.validate_part_number_marker(0) == 0


# ---------------------------------------------------------------------------
# validate_max_parts
# ---------------------------------------------------------------------------

class TestValidateMaxParts:
    def test_non_int_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_max_parts("100")  # type: ignore[arg-type]

    def test_zero_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_max_parts(0)

    def test_too_large_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_max_parts(
                StorageConstants.S3_MULTIPART_MAX_PART_NUMBER + 1,
            )

    def test_valid_returns_value(self) -> None:
        manager, client, raw = make_manager()
        assert manager.validate_max_parts(500) == 500


# ---------------------------------------------------------------------------
# validate_part_size
# ---------------------------------------------------------------------------

class TestValidatePartSize:
    def test_non_int_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_part_size("10")  # type: ignore[arg-type]

    def test_below_min_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_part_size(0)

    def test_non_last_below_s3_min_raises_when_enforced(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.validate_part_size(
                1024,
                is_last_part=False,
                enforce_s3_min_size=True,
            )

    def test_last_part_below_s3_min_allowed_when_enforced(self) -> None:
        manager, client, raw = make_manager()
        assert (
            manager.validate_part_size(
                1024,
                is_last_part=True,
                enforce_s3_min_size=True,
            )
            == 1024
        )

    def test_valid_returns_value(self) -> None:
        manager, client, raw = make_manager()
        assert manager.validate_part_size(10) == 10


# ---------------------------------------------------------------------------
# _validate_etag
# ---------------------------------------------------------------------------

class TestValidateEtag:
    def test_non_string_raises(self) -> None:
        with pytest.raises(StorageMultipartUploadError):
            StorageMultipartManager._validate_etag(123, part_number=1)  # type: ignore[arg-type]

    def test_empty_after_strip_raises(self) -> None:
        with pytest.raises(StorageMultipartUploadError):
            StorageMultipartManager._validate_etag('""', part_number=1)

    def test_strips_quotes_and_whitespace(self) -> None:
        assert (
            StorageMultipartManager._validate_etag('  "abc"  ', part_number=1)
            == "abc"
        )


# ---------------------------------------------------------------------------
# build_completion_parts / _extract_completion_part
# ---------------------------------------------------------------------------

class TestBuildCompletionParts:
    def test_tuple_wrong_length_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.build_completion_parts([(1, "etag", "extra")])  # type: ignore[list-item]

    def test_dict_missing_keys_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.build_completion_parts([{"part_number": 1}])

    def test_returns_completion_part_objects_sorted(self) -> None:
        manager, client, raw = make_manager()
        result = manager.build_completion_parts([(2, "e2"), (1, "e1")])
        assert all(isinstance(item, _CompletionPart) for item in result)
        assert [item.part_number for item in result] == [1, 2]
        assert result[0].etag == "e1"

    def test_storage_upload_part_input(self) -> None:
        manager, client, raw = make_manager()
        part = StorageUploadPart(part_number=1, etag="e1", size_bytes=10)
        result = manager.build_completion_parts([part])
        assert result[0].part_number == 1
        assert result[0].etag == "e1"

    def test_empty_etag_in_completion_part_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageMultipartUploadError):
            manager.build_completion_parts([(1, "  ")])


# ---------------------------------------------------------------------------
# _extract_parts
# ---------------------------------------------------------------------------

class TestExtractParts:
    def test_none_returns_empty(self) -> None:
        assert StorageMultipartManager._extract_parts(None) == []

    def test_list_returned_as_is(self) -> None:
        data = [1, 2, 3]
        assert StorageMultipartManager._extract_parts(data) == [1, 2, 3]

    def test_object_with_parts_attr(self) -> None:
        result = MagicMock()
        result.parts = [10, 20]
        assert StorageMultipartManager._extract_parts(result) == [10, 20]

    def test_tuple_with_parts_attr_item(self) -> None:
        holder = MagicMock()
        holder.parts = [7, 8]
        # У первого элемента кортежа нет .parts, у второго есть.
        plain = object()
        assert StorageMultipartManager._extract_parts((plain, holder)) == [7, 8]

    def test_tuple_with_list_item(self) -> None:
        # Используем объекты, у которых .parts равен None, чтобы дойти до ветки списка.
        class NoParts:
            parts = None

        inner = [1, 2]
        assert StorageMultipartManager._extract_parts((NoParts(), inner)) == [1, 2]

    def test_unknown_returns_empty(self) -> None:
        class NoParts:
            parts = None

        assert StorageMultipartManager._extract_parts(NoParts()) == []


# ---------------------------------------------------------------------------
# _multipart_error mapping
# ---------------------------------------------------------------------------

class TestMultipartErrorMapping:
    def test_connection_error_passthrough(self) -> None:
        exc = StorageConnectionError("down")
        result = StorageMultipartManager._multipart_error(
            exc,
            bucket="b",
            object_key="k",
            upload_id="u",
            operation="upload_part",
        )
        assert result is exc

    def test_existing_multipart_error_passthrough(self) -> None:
        exc = StorageMultipartUploadError("already mapped")
        result = StorageMultipartManager._multipart_error(
            exc,
            bucket="b",
            object_key="k",
            upload_id="u",
            operation="upload_part",
        )
        assert result is exc

    def test_not_found_code_with_upload_id_maps_to_not_found(self) -> None:
        exc = StorageError("no such", details={"code": "NoSuchUpload"})
        result = StorageMultipartManager._multipart_error(
            exc,
            bucket="b",
            object_key="k",
            upload_id="u",
            operation="upload_part",
        )
        assert isinstance(result, StorageMultipartUploadNotFoundError)

    def test_status_404_with_upload_id_maps_to_not_found(self) -> None:
        exc = StorageError("missing", details={"status_code": 404})
        result = StorageMultipartManager._multipart_error(
            exc,
            bucket="b",
            object_key="k",
            upload_id="u",
            operation="list_uploaded_parts",
        )
        assert isinstance(result, StorageMultipartUploadNotFoundError)

    def test_not_found_with_none_upload_id_maps_to_generic_multipart(self) -> None:
        exc = StorageError("missing", details={"code": "InvalidUploadId"})
        result = StorageMultipartManager._multipart_error(
            exc,
            bucket="b",
            object_key="k",
            upload_id=None,
            operation="create_multipart_upload",
        )
        assert isinstance(result, StorageMultipartUploadError)
        assert not isinstance(result, StorageMultipartUploadNotFoundError)

    def test_generic_error_maps_to_multipart_error(self) -> None:
        exc = StorageError("boom", details={"code": "InternalError"})
        result = StorageMultipartManager._multipart_error(
            exc,
            bucket="b",
            object_key="k",
            upload_id="u",
            operation="upload_part",
            part_number=3,
        )
        assert isinstance(result, StorageMultipartUploadError)
        assert result.details["operation"] == "upload_part"
        assert result.details["reason"] == "boom"
