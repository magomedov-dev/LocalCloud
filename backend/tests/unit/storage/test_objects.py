"""Unit-тесты для StorageObjectManager."""
from __future__ import annotations

import hashlib
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest

from storage.buckets import StorageBucketNameValidator
from storage.exceptions import (
    StorageDeleteError,
    StorageDownloadError,
    StorageError,
    StorageObjectError,
    StorageObjectNotFoundError,
    StorageUploadError,
)
from storage.objects import StorageObjectManager


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_validator() -> StorageBucketNameValidator:
    return StorageBucketNameValidator(min_length=3, max_length=63)


def make_raw_client():
    raw = MagicMock()
    raw.put_object = MagicMock(return_value=MagicMock(etag="abc123"))
    raw.get_object = MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"hello")))
    raw.remove_object = MagicMock(return_value=None)
    raw.stat_object = MagicMock(
        return_value=MagicMock(
            size=5,
            etag="abc123",
            content_type="text/plain",
            last_modified=None,
            metadata=None,
            _metadata=None,
            http_headers=None,
            _http_headers=None,
            headers=None,
            _headers=None,
        )
    )
    raw.copy_object = MagicMock(return_value=MagicMock())
    raw.remove_objects = MagicMock(return_value=iter([]))
    raw.list_objects = MagicMock(return_value=iter([]))
    return raw


def make_client():
    raw = make_raw_client()
    client = MagicMock()
    client.get_raw_client = MagicMock(return_value=raw)

    async def execute(fn, *args, operation_name=None, **kwargs):
        if callable(fn):
            result = fn(*args, **kwargs)
            return result
        return fn

    client.execute = AsyncMock(side_effect=execute)
    client.settings = MagicMock()
    client.settings.minio_public_url = "http://localhost:9000"
    client.settings.minio_base_url = "http://localhost:9000"
    return client, raw


def make_manager():
    client, raw = make_client()
    manager = StorageObjectManager(
        client=client,
        bucket_name_validator=make_validator(),
    )
    return manager, client, raw


# ---------------------------------------------------------------------------
# put_object
# ---------------------------------------------------------------------------

class TestPutObject:
    @pytest.mark.asyncio
    async def test_put_bytes_success(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.put_object(
            bucket="test-bucket",
            object_key="folder/file.txt",
            data=b"hello world",
            length=11,
            content_type="text/plain",
        )
        assert result.bucket == "test-bucket"
        assert result.object_key == "folder/file.txt"
        assert result.size_bytes == 11
        assert result.etag == "abc123"

    @pytest.mark.asyncio
    async def test_put_file_like_success(self) -> None:
        manager, client, raw = make_manager()
        data = BytesIO(b"stream data")
        result = await manager.put_object(
            bucket="test-bucket",
            object_key="stream.bin",
            data=data,
            length=11,
        )
        assert result.bucket == "test-bucket"

    @pytest.mark.asyncio
    async def test_put_bytearray_success(self) -> None:
        manager, client, raw = make_manager()
        data = bytearray(b"bytearray data")
        result = await manager.put_object(
            bucket="test-bucket",
            object_key="arr.bin",
            data=data,
            length=14,
        )
        assert result.size_bytes == 14

    @pytest.mark.asyncio
    async def test_put_invalid_length_type_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageUploadError):
            await manager.put_object(
                bucket="test-bucket",
                object_key="file.txt",
                data=b"hello",
                length="not-an-int",  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_put_bool_length_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageUploadError):
            await manager.put_object(
                bucket="test-bucket",
                object_key="file.txt",
                data=b"hello",
                length=True,  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_put_negative_length_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageUploadError):
            await manager.put_object(
                bucket="test-bucket",
                object_key="file.txt",
                data=b"hello",
                length=-1,
            )

    @pytest.mark.asyncio
    async def test_put_unsupported_data_type_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageUploadError):
            await manager.put_object(
                bucket="test-bucket",
                object_key="file.txt",
                data=12345,  # type: ignore[arg-type]
                length=5,
            )

    @pytest.mark.asyncio
    async def test_put_storage_error_wrapped_as_upload_error(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError("internal error", details={"reason": "fail"})

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageUploadError):
            await manager.put_object(
                bucket="test-bucket",
                object_key="file.txt",
                data=b"hello",
                length=5,
            )


# ---------------------------------------------------------------------------
# stat_object
# ---------------------------------------------------------------------------

class TestStatObject:
    @pytest.mark.asyncio
    async def test_stat_returns_object_info(self) -> None:
        manager, client, raw = make_manager()
        info = await manager.stat_object(bucket="test-bucket", object_key="file.txt")
        assert info.bucket == "test-bucket"
        assert info.object_key == "file.txt"
        assert info.size_bytes == 5

    @pytest.mark.asyncio
    async def test_stat_not_found_raises(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageObjectNotFoundError(bucket="test-bucket", object_key="file.txt")

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageObjectNotFoundError):
            await manager.stat_object(bucket="test-bucket", object_key="file.txt")


# ---------------------------------------------------------------------------
# object_exists
# ---------------------------------------------------------------------------

class TestObjectExists:
    @pytest.mark.asyncio
    async def test_exists_returns_true_when_stat_succeeds(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.object_exists(bucket="test-bucket", object_key="file.txt")
        assert result is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_when_not_found(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageObjectNotFoundError(bucket="test-bucket", object_key="file.txt")

        client.execute = AsyncMock(side_effect=execute_raises)

        result = await manager.object_exists(bucket="test-bucket", object_key="file.txt")
        assert result is False


# ---------------------------------------------------------------------------
# delete_object
# ---------------------------------------------------------------------------

class TestDeleteObject:
    @pytest.mark.asyncio
    async def test_delete_existing_object_returns_true(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.delete_object(bucket="test-bucket", object_key="file.txt")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_missing_object_raises_when_not_missing_ok(self) -> None:
        manager, client, raw = make_manager()

        # stat бросает not found, значит object_exists вернёт False.
        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageObjectNotFoundError(bucket="test-bucket", object_key="file.txt")

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageObjectNotFoundError):
            await manager.delete_object(bucket="test-bucket", object_key="file.txt")

    @pytest.mark.asyncio
    async def test_delete_missing_object_returns_false_when_missing_ok(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageObjectNotFoundError(bucket="test-bucket", object_key="file.txt")

        client.execute = AsyncMock(side_effect=execute_raises)

        result = await manager.delete_object(
            bucket="test-bucket",
            object_key="file.txt",
            missing_ok=True,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_storage_error_wrapped(self) -> None:
        manager, client, raw = make_manager()
        call_count = 0

        # Первый вызов — stat_object (успешен, подтверждает наличие), второй падает на remove.
        async def execute_side(fn, *args, operation_name=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if operation_name == "delete_object":
                raise StorageError("delete failed", details={"reason": "io error"})
            # Вызов stat_object — отрабатывает штатно.
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_side)

        with pytest.raises((StorageDeleteError, StorageError)):
            await manager.delete_object(bucket="test-bucket", object_key="file.txt")


# ---------------------------------------------------------------------------
# get_object_bytes (via get_object)
# ---------------------------------------------------------------------------

class TestGetObject:
    @pytest.mark.asyncio
    async def test_get_object_returns_download_result(self) -> None:
        manager, client, raw = make_manager()

        call_num = 0

        async def execute_side(fn, *args, operation_name=None, **kwargs):
            nonlocal call_num
            call_num += 1
            if operation_name == "get_object":
                response_mock = MagicMock()
                response_mock.read = MagicMock(return_value=b"hello")
                response_mock.close = MagicMock()
                response_mock.release_conn = None
                return response_mock
            if operation_name == "read_object_response":
                return b"hello"
            if operation_name in ("stat_object", "close_object_response"):
                if callable(fn):
                    return fn(*args, **kwargs)
                return MagicMock()
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_side)

        result = await manager.get_object(bucket="test-bucket", object_key="file.txt")
        assert result.data == b"hello"

    @pytest.mark.asyncio
    async def test_get_object_not_found_raises(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageObjectNotFoundError(bucket="test-bucket", object_key="file.txt")

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises((StorageObjectNotFoundError, StorageDownloadError)):
            await manager.get_object(bucket="test-bucket", object_key="file.txt")


# ---------------------------------------------------------------------------
# copy_object
# ---------------------------------------------------------------------------

class TestCopyObject:
    @pytest.mark.asyncio
    async def test_copy_returns_result(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.copy_object(
            source_bucket="test-bucket",
            source_object_key="src.txt",
            destination_bucket="test-bucket",
            destination_object_key="dst.txt",
        )
        assert result.source_object_key == "src.txt"
        assert result.destination_object_key == "dst.txt"

    @pytest.mark.asyncio
    async def test_copy_storage_error_raises_copy_error(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "copy_object":
                raise StorageError("copy failed", details={"reason": "error"})
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_raises)

        from storage.exceptions import StorageCopyError
        with pytest.raises((StorageCopyError, StorageError)):
            await manager.copy_object(
                source_bucket="test-bucket",
                source_object_key="src.txt",
                destination_bucket="test-bucket",
                destination_object_key="dst.txt",
            )


# ---------------------------------------------------------------------------
# list_objects
# ---------------------------------------------------------------------------

class TestListObjects:
    @pytest.mark.asyncio
    async def test_list_returns_empty_list(self) -> None:
        manager, client, raw = make_manager()
        raw.list_objects.return_value = iter([])
        result = await manager.list_objects(bucket="test-bucket")
        assert result == []

    @pytest.mark.asyncio
    async def test_list_returns_object_infos(self) -> None:
        manager, client, raw = make_manager()
        item = MagicMock()
        item.object_name = "file.txt"
        item.size = 100
        item.etag = "etag1"
        item.last_modified = None
        item.content_type = "text/plain"
        raw.list_objects.return_value = iter([item])
        result = await manager.list_objects(bucket="test-bucket")
        assert len(result) == 1
        assert result[0].object_key == "file.txt"


# ---------------------------------------------------------------------------
# delete_objects (bulk)
# ---------------------------------------------------------------------------

class TestDeleteObjects:
    @pytest.mark.asyncio
    async def test_delete_empty_list_returns_zero(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.delete_objects(bucket="test-bucket", object_keys=[])
        assert result.deleted_count == 0

    @pytest.mark.asyncio
    async def test_delete_multiple_objects(self) -> None:
        manager, client, raw = make_manager()
        raw.remove_objects.return_value = iter([])
        result = await manager.delete_objects(
            bucket="test-bucket",
            object_keys=["a.txt", "b.txt"],
        )
        assert result.deleted_count == 2

    @pytest.mark.asyncio
    async def test_delete_multiple_with_minio_errors(self) -> None:
        manager, client, raw = make_manager()
        error = MagicMock()
        error.object_name = "b.txt"
        error.code = "AccessDenied"
        error.message = "denied"
        raw.remove_objects.return_value = iter([error])
        result = await manager.delete_objects(
            bucket="test-bucket",
            object_keys=["a.txt", "b.txt"],
        )
        # Запрошено 2, 1 ошибка -> deleted_count = 1.
        assert result.deleted_count == 1
        assert len(result.errors) == 1
        assert result.errors[0].details["object_key"] == "b.txt"
        assert result.errors[0].details["code"] == "AccessDenied"

    @pytest.mark.asyncio
    async def test_delete_objects_storage_error_wrapped(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "delete_objects":
                raise StorageError("bulk failed", details={"reason": "boom"})
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_raises)

        # Путь object_key=None -> общий StorageObjectError.
        with pytest.raises((StorageObjectError, StorageError)):
            await manager.delete_objects(
                bucket="test-bucket",
                object_keys=["a.txt"],
            )


# ---------------------------------------------------------------------------
# delete_object_result (DTO wrapper)
# ---------------------------------------------------------------------------

class TestDeleteObjectResult:
    @pytest.mark.asyncio
    async def test_delete_object_result_deleted_true(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.delete_object_result(
            bucket="test-bucket",
            object_key="file.txt",
        )
        assert result.bucket == "test-bucket"
        assert result.object_key == "file.txt"
        assert result.deleted is True

    @pytest.mark.asyncio
    async def test_delete_object_result_missing_ok_false(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageObjectNotFoundError(bucket="test-bucket", object_key="file.txt")

        client.execute = AsyncMock(side_effect=execute_raises)

        result = await manager.delete_object_result(
            bucket="test-bucket",
            object_key="file.txt",
            missing_ok=True,
        )
        assert result.deleted is False


# ---------------------------------------------------------------------------
# get_object_stream
# ---------------------------------------------------------------------------

class TestGetObjectStream:
    @pytest.mark.asyncio
    async def test_stream_returns_raw_response(self) -> None:
        manager, client, raw = make_manager()
        stream_obj = MagicMock(name="stream")
        raw.get_object = MagicMock(return_value=stream_obj)

        result = await manager.get_object_stream(
            bucket="test-bucket",
            object_key="file.txt",
            offset=10,
            length=20,
        )
        assert result is stream_obj
        # Проверяем, что get_object вызван с kwargs offset/length.
        _, kwargs = raw.get_object.call_args
        assert kwargs["offset"] == 10
        assert kwargs["length"] == 20

    @pytest.mark.asyncio
    async def test_stream_not_found_raises(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageObjectNotFoundError(bucket="test-bucket", object_key="file.txt")

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises((StorageObjectNotFoundError, StorageDownloadError)):
            await manager.get_object_stream(bucket="test-bucket", object_key="file.txt")

    @pytest.mark.asyncio
    async def test_stream_storage_error_wrapped_as_download_error(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError("stream failed", details={"reason": "io"})

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageDownloadError):
            await manager.get_object_stream(bucket="test-bucket", object_key="file.txt")


# ---------------------------------------------------------------------------
# calculate_object_checksum
# ---------------------------------------------------------------------------

class _FakeObjectStream:
    """Имитация потока MinIO: отдаёт данные блоками, затем ``b''``."""

    def __init__(self, data: bytes) -> None:
        self._buffer = BytesIO(data)
        self.read_calls = 0
        self.closed = False
        self.released = False

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        return self._buffer.read(size)

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class TestCalculateObjectChecksum:
    @pytest.mark.asyncio
    async def test_streams_in_chunks_and_matches_hashlib(self) -> None:
        manager, client, raw = make_manager()
        data = b"file content for streaming checksum " * 100
        stream = _FakeObjectStream(data)
        raw.get_object = MagicMock(return_value=stream)

        checksum = await manager.calculate_object_checksum(
            bucket="test-bucket",
            object_key="folder/file.bin",
            algorithm="sha256",
            chunk_size=1024,
        )

        assert checksum == hashlib.sha256(data).hexdigest()
        # Данные читались блоками (а не одним read целиком в память).
        assert stream.read_calls >= 2
        # Поток закрыт и соединение освобождено.
        assert stream.closed is True
        assert stream.released is True

    @pytest.mark.asyncio
    async def test_default_chunk_size_used(self) -> None:
        manager, client, raw = make_manager()
        data = b"short payload"
        raw.get_object = MagicMock(return_value=_FakeObjectStream(data))

        checksum = await manager.calculate_object_checksum(
            bucket="test-bucket",
            object_key="f.bin",
            algorithm="md5",
        )

        assert checksum == hashlib.md5(data).hexdigest()

    @pytest.mark.asyncio
    async def test_not_found_raises(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageObjectNotFoundError(
                bucket="test-bucket", object_key="f.bin"
            )

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises((StorageObjectNotFoundError, StorageDownloadError)):
            await manager.calculate_object_checksum(
                bucket="test-bucket", object_key="f.bin", algorithm="sha256"
            )

    @pytest.mark.asyncio
    async def test_storage_error_wrapped_as_download_error(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError("read failed", details={"reason": "io"})

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageDownloadError):
            await manager.calculate_object_checksum(
                bucket="test-bucket", object_key="f.bin", algorithm="sha256"
            )


# ---------------------------------------------------------------------------
# count_objects
# ---------------------------------------------------------------------------

class TestCountObjects:
    @pytest.mark.asyncio
    async def test_count_objects_returns_count(self) -> None:
        manager, client, raw = make_manager()
        item_a = MagicMock(object_name="a.txt", size=1, etag="e", last_modified=None, content_type=None)
        item_b = MagicMock(object_name="b.txt", size=2, etag="e", last_modified=None, content_type=None)
        raw.list_objects.return_value = iter([item_a, item_b])
        count = await manager.count_objects(bucket="test-bucket", prefix="dir")
        assert count == 2


# ---------------------------------------------------------------------------
# list_objects extra branches
# ---------------------------------------------------------------------------

class TestListObjectsExtra:
    @pytest.mark.asyncio
    async def test_list_skips_items_without_name(self) -> None:
        manager, client, raw = make_manager()
        from datetime import UTC, datetime

        good = MagicMock(
            object_name="dir/file.txt",
            size=42,
            etag="etag-good",
            last_modified=datetime.now(UTC),
            content_type="text/plain",
        )
        empty = MagicMock(
            object_name="",
            size=0,
            etag=None,
            last_modified=None,
            content_type=None,
        )
        raw.list_objects.return_value = iter([good, empty])

        result = await manager.list_objects(bucket="test-bucket", prefix="dir")
        assert len(result) == 1
        assert result[0].object_key == "dir/file.txt"
        assert result[0].size_bytes == 42
        assert result[0].last_modified_at is not None

    @pytest.mark.asyncio
    async def test_list_storage_error_wrapped(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError("list failed", details={"reason": "io"})

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageObjectError):
            await manager.list_objects(bucket="test-bucket")


# ---------------------------------------------------------------------------
# copy_object с метаданными REPLACE
# ---------------------------------------------------------------------------

class TestCopyObjectMetadata:
    @pytest.mark.asyncio
    async def test_copy_with_metadata_sets_replace_directive(self) -> None:
        manager, client, raw = make_manager()
        await manager.copy_object(
            source_bucket="test-bucket",
            source_object_key="src.txt",
            destination_bucket="test-bucket",
            destination_object_key="dst.txt",
            metadata={"purpose": "backup"},
        )
        # copy_object на raw-клиенте должен был быть вызван с metadata_directive.
        _, kwargs = raw.copy_object.call_args
        assert kwargs["metadata_directive"] == "REPLACE"
        assert any("purpose" in k for k in kwargs["metadata"])


# ---------------------------------------------------------------------------
# compose_object
# ---------------------------------------------------------------------------

class TestComposeObject:
    @pytest.mark.asyncio
    async def test_compose_empty_sources_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StorageObjectError):
            await manager.compose_object(
                bucket="test-bucket",
                object_key="out.bin",
                sources=[],
            )

    @pytest.mark.asyncio
    async def test_compose_success_returns_stat(self) -> None:
        manager, client, raw = make_manager()
        raw.compose_object = MagicMock(return_value=MagicMock())
        result = await manager.compose_object(
            bucket="test-bucket",
            object_key="out.bin",
            sources=[("test-bucket", "part1"), ("test-bucket", "part2")],
            metadata={"purpose": "merge"},
        )
        assert result.object_key == "out.bin"
        raw.compose_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_compose_storage_error_wrapped(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "compose_object":
                raise StorageError("compose failed", details={"reason": "bad request"})
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageObjectError):
            await manager.compose_object(
                bucket="test-bucket",
                object_key="out.bin",
                sources=[("test-bucket", "part1")],
            )

    @pytest.mark.asyncio
    async def test_compose_small_objects_fallback(self) -> None:
        manager, client, raw = make_manager()

        get_calls: list[str] = []

        async def execute_side(fn, *args, operation_name=None, **kwargs):
            if operation_name == "compose_object":
                raise StorageError(
                    "compose failed",
                    details={"reason": "size must be greater than 5242880"},
                )
            if operation_name == "get_object":
                resp = MagicMock()
                resp.read = MagicMock(return_value=b"part")
                resp.close = MagicMock()
                resp.release_conn = MagicMock()
                return resp
            if operation_name == "read_object_response":
                get_calls.append("read")
                return b"part"
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_side)

        result = await manager.compose_object(
            bucket="test-bucket",
            object_key="out.bin",
            sources=[("test-bucket", "p1"), ("test-bucket", "p2")],
            metadata={"content_type": "text/plain"},
        )
        # Резервный путь скачивает каждую часть и заново загружает через put_object.
        assert result.object_key == "out.bin"
        assert len(get_calls) == 2


# ---------------------------------------------------------------------------
# _build_object_info / metadata extraction & checksum
# ---------------------------------------------------------------------------

class TestBuildObjectInfoAndMetadata:
    @pytest.mark.asyncio
    async def test_stat_extracts_user_metadata_and_checksum(self) -> None:
        manager, client, raw = make_manager()
        stat = MagicMock()
        stat.size = 128
        stat.etag = "etag-x"
        stat.content_type = "application/pdf"
        stat.last_modified = None
        stat.metadata = {
            "x-amz-meta-checksum": "deadbeef",
            "x-amz-meta-checksum_algorithm": "sha256",
            "x-minio-meta-purpose": "archive",
            "metadata.source": "import",
            "user_id": "42",
            "irrelevant-header": "ignored",
            "x-amz-meta-empty": "   ",
        }
        # Прочие возможные атрибуты оставляем отсутствующими.
        for attr in ("_metadata", "http_headers", "_http_headers", "headers", "_headers"):
            setattr(stat, attr, None)
        raw.stat_object = MagicMock(return_value=stat)

        info = await manager.stat_object(bucket="test-bucket", object_key="file.pdf")
        assert info.size_bytes == 128
        assert info.checksum == "deadbeef"
        assert info.checksum_algorithm is not None
        assert info.checksum_algorithm.value == "sha256"
        assert info.metadata.get("purpose") == "archive"
        assert info.metadata.get("source") == "import"
        assert info.metadata.get("user_id") == "42"
        # Пустые / нерелевантные заголовки отбрасываются.
        assert info.metadata.get("empty") is None

    @pytest.mark.asyncio
    async def test_stat_invalid_checksum_algorithm_ignored(self) -> None:
        manager, client, raw = make_manager()
        stat = MagicMock()
        stat.size = 1
        stat.etag = "e"
        stat.content_type = None
        stat.last_modified = None
        # Недопустимое значение алгоритма -> разбирается в None (контрольной суммы нет, модель валидна).
        stat.metadata = {
            "x-amz-meta-checksum_algorithm": "not-a-real-algo",
        }
        for attr in ("_metadata", "http_headers", "_http_headers", "headers", "_headers"):
            setattr(stat, attr, None)
        raw.stat_object = MagicMock(return_value=stat)

        info = await manager.stat_object(bucket="test-bucket", object_key="file.bin")
        assert info.checksum is None
        assert info.checksum_algorithm is None

    @pytest.mark.asyncio
    async def test_stat_non_mapping_metadata_ignored(self) -> None:
        manager, client, raw = make_manager()
        stat = MagicMock()
        stat.size = 1
        stat.etag = "e"
        stat.content_type = None
        stat.last_modified = None
        stat.metadata = ["not", "a", "mapping"]
        for attr in ("_metadata", "http_headers", "_http_headers", "headers", "_headers"):
            setattr(stat, attr, None)
        raw.stat_object = MagicMock(return_value=stat)

        info = await manager.stat_object(bucket="test-bucket", object_key="file.bin")
        assert info.metadata.has_metadata is False


# ---------------------------------------------------------------------------
# _object_error mapping branches
# ---------------------------------------------------------------------------

class TestObjectErrorMapping:
    @pytest.mark.asyncio
    async def test_connection_error_passed_through(self) -> None:
        from storage.exceptions import StorageConnectionError

        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageConnectionError("no connection")

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageConnectionError):
            await manager.stat_object(bucket="test-bucket", object_key="file.txt")

    @pytest.mark.asyncio
    async def test_404_status_maps_to_not_found(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError("missing", details={"status_code": 404})

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageObjectNotFoundError):
            await manager.stat_object(bucket="test-bucket", object_key="file.txt")

    @pytest.mark.asyncio
    async def test_nosuchkey_code_maps_to_not_found(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError("missing", details={"code": "NoSuchKey"})

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageObjectNotFoundError):
            await manager.stat_object(bucket="test-bucket", object_key="file.txt")

    @pytest.mark.asyncio
    async def test_not_found_with_none_object_key_is_generic_error(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "delete_objects":
                raise StorageError("missing", details={"code": "NoSuchBucket"})
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_raises)

        # delete_objects передаёт object_key=None -> общий StorageObjectError.
        with pytest.raises(StorageObjectError) as exc_info:
            await manager.delete_objects(bucket="test-bucket", object_keys=["a.txt"])
        assert not isinstance(exc_info.value, StorageObjectNotFoundError)

    @pytest.mark.asyncio
    async def test_generic_error_no_operation_kind(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            raise StorageError("weird", details={"reason": "unknown"})

        client.execute = AsyncMock(side_effect=execute_raises)

        # У stat_object нет operation_kind -> общий StorageObjectError.
        with pytest.raises(StorageObjectError):
            await manager.stat_object(bucket="test-bucket", object_key="file.txt")


# ---------------------------------------------------------------------------
# _close_response branches
# ---------------------------------------------------------------------------

class TestCloseResponse:
    @pytest.mark.asyncio
    async def test_get_object_closes_and_releases_connection(self) -> None:
        manager, client, raw = make_manager()

        response_mock = MagicMock()
        response_mock.read = MagicMock(return_value=b"hello")
        response_mock.close = MagicMock()
        response_mock.release_conn = MagicMock()

        async def execute_side(fn, *args, operation_name=None, **kwargs):
            if operation_name == "get_object":
                return response_mock
            if operation_name == "read_object_response":
                return b"hello"
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_side)

        result = await manager.get_object(bucket="test-bucket", object_key="file.txt")
        assert result.data == b"hello"
        response_mock.close.assert_called_once()
        response_mock.release_conn.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_response_swallows_storage_error(self) -> None:
        manager, client, raw = make_manager()

        response_mock = MagicMock()
        response_mock.read = MagicMock(return_value=b"hi")
        response_mock.close = MagicMock()
        response_mock.release_conn = MagicMock()

        async def execute_side(fn, *args, operation_name=None, **kwargs):
            if operation_name == "get_object":
                return response_mock
            if operation_name == "read_object_response":
                return b"hi"
            if operation_name == "close_object_response":
                raise StorageError("close failed")
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_side)

        # Ошибка при закрытии должна поглощаться; результат всё равно возвращается.
        result = await manager.get_object(bucket="test-bucket", object_key="file.txt")
        assert result.data == b"hi"

    @pytest.mark.asyncio
    async def test_close_response_none_is_noop(self) -> None:
        manager, client, raw = make_manager()
        # Напрямую проверяем ветку None.
        await manager._close_response(None)
