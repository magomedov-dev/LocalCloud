"""Unit-тесты для StorageService."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.constants import StorageConstants
from storage.service import StorageService
from storage.types import (
    StorageCopyResult,
    StorageDownloadResult,
    StorageObjectDeleteResult,
    StorageObjectInfo,
    StorageObjectMetadata,
    StoragePresignedUrl,
    StoragePresignedUrlMethod,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_object_info(
    bucket: str = "localcloud-files",
    key: str = "test/file.bin",
    size: int = 100,
) -> StorageObjectInfo:
    return StorageObjectInfo(
        bucket=bucket,
        object_key=key,
        size_bytes=size,
        content_type="application/octet-stream",
        etag="etag-abc",
    )


def _make_download_result(
    bucket: str = "localcloud-files",
    key: str = "test/file.bin",
) -> StorageDownloadResult:
    return StorageDownloadResult(
        bucket=bucket,
        object_key=key,
        data=b"file content",
        size_bytes=12,
        content_type="application/octet-stream",
        etag="etag-abc",
    )


def _make_copy_result() -> StorageCopyResult:
    from datetime import UTC, datetime
    return StorageCopyResult(
        source_bucket="localcloud-files",
        source_object_key="src.bin",
        destination_bucket="localcloud-files",
        destination_object_key="dst.bin",
        etag="etag-def",
        copied_at=datetime.now(UTC),
    )


def _make_presigned_url() -> StoragePresignedUrl:
    from datetime import UTC, datetime, timedelta
    return StoragePresignedUrl(
        url="http://localhost:9000/localcloud-files/file.bin?sig=abc",
        method=StoragePresignedUrlMethod.GET,
        bucket="localcloud-files",
        object_key="file.bin",
        expires_in_seconds=3600,
        expires_at=datetime.now(UTC) + timedelta(seconds=3600),
        headers={},
    )


def make_storage_service() -> tuple[StorageService, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Создаёт StorageService со всеми замоканными подменеджерами."""
    settings = MagicMock()
    settings.minio_region = "us-east-1"

    client = MagicMock()
    client.ping = AsyncMock(return_value=True)

    object_manager = MagicMock()
    bucket_manager = MagicMock()
    multipart_manager = MagicMock()
    presigned_manager = MagicMock()
    integrity_checker = MagicMock()
    health_checker = MagicMock()

    service = StorageService(
        settings=settings,
        client=client,
        bucket_manager=bucket_manager,
        object_manager=object_manager,
        multipart_manager=multipart_manager,
        presigned_url_manager=presigned_manager,
        integrity_checker=integrity_checker,
        health_checker=health_checker,
    )
    return service, object_manager, bucket_manager, multipart_manager, presigned_manager


# ---------------------------------------------------------------------------
# Default buckets
# ---------------------------------------------------------------------------

class TestDefaultBuckets:
    def test_default_files_bucket(self) -> None:
        service, *_ = make_storage_service()
        assert service.default_files_bucket == StorageConstants.MINIO_BUCKET_FILES

    def test_default_temp_bucket(self) -> None:
        service, *_ = make_storage_service()
        assert service.default_temp_bucket == StorageConstants.MINIO_BUCKET_TEMP

    def test_default_archives_bucket(self) -> None:
        service, *_ = make_storage_service()
        assert service.default_archives_bucket == StorageConstants.MINIO_BUCKET_ARCHIVES

    def test_default_buckets_list(self) -> None:
        service, *_ = make_storage_service()
        assert len(service.default_buckets) == 3
        assert service.default_files_bucket in service.default_buckets
        assert service.default_temp_bucket in service.default_buckets
        assert service.default_archives_bucket in service.default_buckets


# ---------------------------------------------------------------------------
# upload_file_object
# ---------------------------------------------------------------------------

class TestUploadFileObject:
    @pytest.mark.asyncio
    async def test_delegates_to_object_manager(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_object_info()
        object_manager.put_object = AsyncMock(return_value=expected)

        user_id = uuid.uuid4()
        file_id = uuid.uuid4()
        version_id = uuid.uuid4()

        result = await service.upload_file_object(
            data=b"hello",
            length=5,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )
        assert result is expected
        object_manager.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_explicit_bucket(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_object_info(bucket="localcloud-temp")
        object_manager.put_object = AsyncMock(return_value=expected)

        result = await service.upload_file_object(
            data=b"data",
            length=4,
            bucket="localcloud-temp",
            object_key="explicit-key.bin",
        )
        assert result is expected
        call_kwargs = object_manager.put_object.call_args[1]
        assert call_kwargs["bucket"] == "localcloud-temp"

    @pytest.mark.asyncio
    async def test_uses_explicit_object_key(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_object_info()
        object_manager.put_object = AsyncMock(return_value=expected)

        result = await service.upload_file_object(
            data=b"data",
            length=4,
            object_key="my/custom/key.bin",
        )
        assert result is expected
        call_kwargs = object_manager.put_object.call_args[1]
        assert call_kwargs["object_key"] == "my/custom/key.bin"


# ---------------------------------------------------------------------------
# download_file_object
# ---------------------------------------------------------------------------

class TestDownloadFileObject:
    @pytest.mark.asyncio
    async def test_delegates_to_object_manager(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_download_result()
        object_manager.get_object_bytes = AsyncMock(return_value=expected)

        result = await service.download_file_object(object_key="test/file.bin")
        assert result is expected
        object_manager.get_object_bytes.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_default_bucket_when_none(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_download_result()
        object_manager.get_object_bytes = AsyncMock(return_value=expected)

        await service.download_file_object(object_key="test/file.bin")
        call_kwargs = object_manager.get_object_bytes.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket


# ---------------------------------------------------------------------------
# delete_file_object
# ---------------------------------------------------------------------------

class TestDeleteFileObject:
    @pytest.mark.asyncio
    async def test_delegates_to_object_manager(self) -> None:
        service, object_manager, *_ = make_storage_service()
        object_manager.delete_object = AsyncMock(return_value=True)

        result = await service.delete_file_object(object_key="test/file.bin")
        assert result is True
        object_manager.delete_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_missing_ok(self) -> None:
        service, object_manager, *_ = make_storage_service()
        object_manager.delete_object = AsyncMock(return_value=False)

        result = await service.delete_file_object(object_key="test/file.bin", missing_ok=True)
        assert result is False
        call_kwargs = object_manager.delete_object.call_args[1]
        assert call_kwargs["missing_ok"] is True


# ---------------------------------------------------------------------------
# get_file_object_info (stat)
# ---------------------------------------------------------------------------

class TestGetFileObjectInfo:
    @pytest.mark.asyncio
    async def test_delegates_to_stat_object(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_object_info()
        object_manager.stat_object = AsyncMock(return_value=expected)

        result = await service.get_file_object_info(object_key="test/file.bin")
        assert result is expected
        object_manager.stat_object.assert_called_once()


# ---------------------------------------------------------------------------
# file_object_exists
# ---------------------------------------------------------------------------

class TestFileObjectExists:
    @pytest.mark.asyncio
    async def test_returns_true_when_exists(self) -> None:
        service, object_manager, *_ = make_storage_service()
        object_manager.object_exists = AsyncMock(return_value=True)

        result = await service.file_object_exists(object_key="test/file.bin")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_exists(self) -> None:
        service, object_manager, *_ = make_storage_service()
        object_manager.object_exists = AsyncMock(return_value=False)

        result = await service.file_object_exists(object_key="test/file.bin")
        assert result is False


# ---------------------------------------------------------------------------
# delete_file_objects
# ---------------------------------------------------------------------------

class TestDeleteFileObjects:
    @pytest.mark.asyncio
    async def test_delegates_to_delete_objects(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = StorageObjectDeleteResult(deleted_count=2)
        object_manager.delete_objects = AsyncMock(return_value=expected)

        result = await service.delete_file_objects(object_keys=["a.bin", "b.bin"])
        assert result is expected
        object_manager.delete_objects.assert_called_once()


# ---------------------------------------------------------------------------
# copy_file_object
# ---------------------------------------------------------------------------

class TestCopyFileObject:
    @pytest.mark.asyncio
    async def test_delegates_to_copy_object(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_copy_result()
        object_manager.copy_object = AsyncMock(return_value=expected)

        result = await service.copy_file_object(
            source_object_key="src.bin",
            destination_object_key="dst.bin",
        )
        assert result is expected
        object_manager.copy_object.assert_called_once()


# ---------------------------------------------------------------------------
# create_download_url
# ---------------------------------------------------------------------------

class TestCreateDownloadUrl:
    @pytest.mark.asyncio
    async def test_delegates_to_presigned_manager(self) -> None:
        service, object_manager, bucket_manager, multipart_manager, presigned_manager = make_storage_service()
        expected = _make_presigned_url()
        presigned_manager.generate_presigned_get_url = AsyncMock(return_value=expected)

        result = await service.create_download_url(object_key="file.bin")
        assert result is expected
        presigned_manager.generate_presigned_get_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_default_expires(self) -> None:
        service, object_manager, bucket_manager, multipart_manager, presigned_manager = make_storage_service()
        expected = _make_presigned_url()
        presigned_manager.generate_presigned_get_url = AsyncMock(return_value=expected)

        await service.create_download_url(object_key="file.bin")
        call_kwargs = presigned_manager.generate_presigned_get_url.call_args[1]
        assert call_kwargs["expires_in_seconds"] == service.presigned_download_expire_seconds


# ---------------------------------------------------------------------------
# create_upload_url
# ---------------------------------------------------------------------------

class TestCreateUploadUrl:
    @pytest.mark.asyncio
    async def test_delegates_to_presigned_manager(self) -> None:
        service, object_manager, bucket_manager, multipart_manager, presigned_manager = make_storage_service()
        from datetime import UTC, datetime, timedelta
        expected = StoragePresignedUrl(
            url="http://localhost:9000/localcloud-files/file.bin?sig=abc",
            method=StoragePresignedUrlMethod.PUT,
            bucket="localcloud-files",
            object_key="file.bin",
            expires_in_seconds=3600,
            expires_at=datetime.now(UTC) + timedelta(seconds=3600),
            headers={},
        )
        presigned_manager.generate_presigned_put_url = AsyncMock(return_value=expected)

        result = await service.create_upload_url(object_key="file.bin")
        assert result is expected
        presigned_manager.generate_presigned_put_url.assert_called_once()


# ---------------------------------------------------------------------------
# build key helpers
# ---------------------------------------------------------------------------

class TestBuildKeyHelpers:
    def test_build_file_key(self) -> None:
        service, *_ = make_storage_service()
        user_id = uuid.uuid4()
        file_id = uuid.uuid4()
        version_id = uuid.uuid4()
        key = service.build_file_key(user_id=user_id, file_id=file_id, version_id=version_id)
        assert isinstance(key, str)
        assert len(key) > 0

    def test_build_archive_key(self) -> None:
        service, *_ = make_storage_service()
        user_id = uuid.uuid4()
        task_id = uuid.uuid4()
        key = service.build_archive_key(user_id=user_id, task_id=task_id)
        assert isinstance(key, str)
        assert key.endswith(".zip")

    def test_build_preview_key(self) -> None:
        service, *_ = make_storage_service()
        user_id = uuid.uuid4()
        file_id = uuid.uuid4()
        key = service.build_preview_key(user_id=user_id, file_id=file_id)
        assert isinstance(key, str)
        assert len(key) > 0


# ---------------------------------------------------------------------------
# _resolve_file_object_key
# ---------------------------------------------------------------------------

class TestResolveFileObjectKey:
    def test_explicit_key_returned_when_provided(self) -> None:
        result = StorageService._resolve_file_object_key(
            object_key="explicit/key.bin",
            user_id=None,
            file_id=None,
            version_id=None,
        )
        assert result == "explicit/key.bin"

    def test_missing_ids_without_explicit_key_raises(self) -> None:
        from storage.exceptions import StorageError
        with pytest.raises(StorageError):
            StorageService._resolve_file_object_key(
                object_key=None,
                user_id=None,
                file_id=None,
                version_id=None,
            )

    def test_all_ids_returns_built_key(self) -> None:
        result = StorageService._resolve_file_object_key(
            object_key=None,
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
        )
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# ensure_storage_ready
# ---------------------------------------------------------------------------

class TestEnsureStorageReady:
    @pytest.mark.asyncio
    async def test_check_access_when_not_creating(self) -> None:
        service, object_manager, bucket_manager, *_ = make_storage_service()
        bucket_manager.check_bucket_access = AsyncMock(return_value=True)

        result = await service.ensure_storage_ready()

        assert result is True
        service.client.ping.assert_awaited_once()
        bucket_manager.check_bucket_access.assert_awaited_once_with(
            service.default_files_bucket,
        )

    @pytest.mark.asyncio
    async def test_creates_bucket_when_requested(self) -> None:
        service, object_manager, bucket_manager, *_ = make_storage_service()
        bucket_manager.ensure_bucket_exists = AsyncMock(return_value=True)

        result = await service.ensure_storage_ready(
            bucket="localcloud-temp",
            create_bucket=True,
            region="eu-west-1",
            object_lock=True,
        )

        assert result is True
        bucket_manager.ensure_bucket_exists.assert_awaited_once_with(
            "localcloud-temp",
            region="eu-west-1",
            object_lock=True,
        )

    @pytest.mark.asyncio
    async def test_uses_settings_region_by_default(self) -> None:
        service, object_manager, bucket_manager, *_ = make_storage_service()
        bucket_manager.ensure_bucket_exists = AsyncMock(return_value=True)

        await service.ensure_storage_ready(create_bucket=True)

        call_kwargs = bucket_manager.ensure_bucket_exists.call_args[1]
        assert call_kwargs["region"] == service.settings.minio_region

    @pytest.mark.asyncio
    async def test_propagates_ping_error(self) -> None:
        from storage.exceptions import StorageError

        service, *_ = make_storage_service()
        service.client.ping = AsyncMock(side_effect=StorageError("ping failed"))

        with pytest.raises(StorageError):
            await service.ensure_storage_ready()


# ---------------------------------------------------------------------------
# ensure_buckets_ready
# ---------------------------------------------------------------------------

class TestEnsureBucketsReady:
    @pytest.mark.asyncio
    async def test_checks_default_buckets(self) -> None:
        service, object_manager, bucket_manager, *_ = make_storage_service()
        bucket_manager.check_bucket_access = AsyncMock(return_value=True)

        result = await service.ensure_buckets_ready()

        assert result == {bucket: True for bucket in service.default_buckets}
        assert bucket_manager.check_bucket_access.await_count == len(service.default_buckets)
        service.client.ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_missing_buckets(self) -> None:
        service, object_manager, bucket_manager, *_ = make_storage_service()
        bucket_manager.ensure_bucket_exists = AsyncMock(return_value=True)

        result = await service.ensure_buckets_ready(
            buckets=["localcloud-files"],
            create_missing=True,
        )

        assert result == {"localcloud-files": True}
        bucket_manager.ensure_bucket_exists.assert_awaited_once()
        call_kwargs = bucket_manager.ensure_bucket_exists.call_args[1]
        assert call_kwargs["region"] == service.settings.minio_region


# ---------------------------------------------------------------------------
# get_file_object_stream
# ---------------------------------------------------------------------------

class TestGetFileObjectStream:
    @pytest.mark.asyncio
    async def test_delegates_to_get_object_stream(self) -> None:
        service, object_manager, *_ = make_storage_service()
        sentinel = object()
        object_manager.get_object_stream = AsyncMock(return_value=sentinel)

        result = await service.get_file_object_stream(
            object_key="test/file.bin",
            offset=10,
            length=20,
        )

        assert result is sentinel
        call_kwargs = object_manager.get_object_stream.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket
        assert call_kwargs["object_key"] == "test/file.bin"
        assert call_kwargs["offset"] == 10
        assert call_kwargs["length"] == 20


# ---------------------------------------------------------------------------
# create_delete_url
# ---------------------------------------------------------------------------

class TestCreateDeleteUrl:
    @pytest.mark.asyncio
    async def test_delegates_to_presigned_manager(self) -> None:
        service, *_, presigned_manager = make_storage_service()
        expected = _make_presigned_url()
        presigned_manager.generate_presigned_delete_url = AsyncMock(return_value=expected)

        result = await service.create_delete_url(object_key="file.bin")

        assert result is expected
        call_kwargs = presigned_manager.generate_presigned_delete_url.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket
        assert call_kwargs["expires_in_seconds"] == service.presigned_upload_expire_seconds

    @pytest.mark.asyncio
    async def test_uses_explicit_expires(self) -> None:
        service, *_, presigned_manager = make_storage_service()
        expected = _make_presigned_url()
        presigned_manager.generate_presigned_delete_url = AsyncMock(return_value=expected)

        await service.create_delete_url(object_key="file.bin", expires_in_seconds=120)

        call_kwargs = presigned_manager.generate_presigned_delete_url.call_args[1]
        assert call_kwargs["expires_in_seconds"] == 120


# ---------------------------------------------------------------------------
# create_upload_part_url(s)
# ---------------------------------------------------------------------------

class TestCreateUploadPartUrls:
    @pytest.mark.asyncio
    async def test_single_part_url(self) -> None:
        service, *_, presigned_manager = make_storage_service()
        expected = _make_presigned_url()
        presigned_manager.generate_presigned_upload_part_url = AsyncMock(return_value=expected)

        result = await service.create_upload_part_url(
            object_key="file.bin",
            upload_id="upload-1",
            part_number=2,
        )

        assert result is expected
        call_kwargs = presigned_manager.generate_presigned_upload_part_url.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket
        assert call_kwargs["upload_id"] == "upload-1"
        assert call_kwargs["part_number"] == 2
        assert call_kwargs["expires_in_seconds"] == service.presigned_upload_expire_seconds

    @pytest.mark.asyncio
    async def test_multiple_part_urls(self) -> None:
        service, *_, presigned_manager = make_storage_service()
        expected = ["url-a", "url-b"]
        presigned_manager.generate_presigned_upload_part_urls = AsyncMock(return_value=expected)

        result = await service.create_upload_part_urls(
            object_key="file.bin",
            upload_id="upload-1",
            part_numbers=[1, 2],
            expires_in_seconds=300,
        )

        assert result is expected
        call_kwargs = presigned_manager.generate_presigned_upload_part_urls.call_args[1]
        assert call_kwargs["part_numbers"] == [1, 2]
        assert call_kwargs["expires_in_seconds"] == 300


# ---------------------------------------------------------------------------
# multipart upload lifecycle
# ---------------------------------------------------------------------------

class TestMultipartLifecycle:
    @pytest.mark.asyncio
    async def test_init_multipart_upload(self) -> None:
        service, object_manager, bucket_manager, multipart_manager, *_ = make_storage_service()
        sentinel = object()
        multipart_manager.create_multipart_upload = AsyncMock(return_value=sentinel)

        result = await service.init_multipart_upload(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            content_type="application/octet-stream",
        )

        assert result is sentinel
        call_kwargs = multipart_manager.create_multipart_upload.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket
        assert call_kwargs["content_type"] == "application/octet-stream"
        assert isinstance(call_kwargs["metadata"], StorageObjectMetadata)

    @pytest.mark.asyncio
    async def test_upload_multipart_part(self) -> None:
        service, object_manager, bucket_manager, multipart_manager, *_ = make_storage_service()
        sentinel = object()
        multipart_manager.upload_part = AsyncMock(return_value=sentinel)

        result = await service.upload_multipart_part(
            object_key="file.bin",
            upload_id="upload-1",
            part_number=1,
            data=b"chunk",
            size_bytes=5,
        )

        assert result is sentinel
        call_kwargs = multipart_manager.upload_part.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket
        assert call_kwargs["part_number"] == 1
        assert call_kwargs["size_bytes"] == 5

    @pytest.mark.asyncio
    async def test_list_multipart_parts_uses_default_max_parts(self) -> None:
        service, object_manager, bucket_manager, multipart_manager, *_ = make_storage_service()
        multipart_manager.list_uploaded_parts = AsyncMock(return_value=[])

        result = await service.list_multipart_parts(
            object_key="file.bin",
            upload_id="upload-1",
        )

        assert result == []
        call_kwargs = multipart_manager.list_uploaded_parts.call_args[1]
        assert call_kwargs["max_parts"] == service.multipart_max_parts
        assert call_kwargs["part_number_marker"] == 0

    @pytest.mark.asyncio
    async def test_list_multipart_parts_explicit_max_parts(self) -> None:
        service, object_manager, bucket_manager, multipart_manager, *_ = make_storage_service()
        multipart_manager.list_uploaded_parts = AsyncMock(return_value=[])

        await service.list_multipart_parts(
            object_key="file.bin",
            upload_id="upload-1",
            max_parts=7,
            part_number_marker=3,
        )

        call_kwargs = multipart_manager.list_uploaded_parts.call_args[1]
        assert call_kwargs["max_parts"] == 7
        assert call_kwargs["part_number_marker"] == 3

    @pytest.mark.asyncio
    async def test_complete_multipart_upload(self) -> None:
        service, object_manager, bucket_manager, multipart_manager, *_ = make_storage_service()
        expected = _make_object_info()
        multipart_manager.complete_multipart_upload = AsyncMock(return_value=expected)

        result = await service.complete_multipart_upload(
            object_key="file.bin",
            upload_id="upload-1",
            parts=[(1, "etag-1")],
        )

        assert result is expected
        call_kwargs = multipart_manager.complete_multipart_upload.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket
        assert call_kwargs["parts"] == [(1, "etag-1")]

    @pytest.mark.asyncio
    async def test_abort_multipart_upload(self) -> None:
        service, object_manager, bucket_manager, multipart_manager, *_ = make_storage_service()
        multipart_manager.abort_multipart_upload = AsyncMock(return_value=True)

        result = await service.abort_multipart_upload(
            object_key="file.bin",
            upload_id="upload-1",
            missing_ok=True,
        )

        assert result is True
        call_kwargs = multipart_manager.abort_multipart_upload.call_args[1]
        assert call_kwargs["missing_ok"] is True


# ---------------------------------------------------------------------------
# verify_file_object
# ---------------------------------------------------------------------------

class TestVerifyFileObject:
    @pytest.mark.asyncio
    async def test_delegates_to_integrity_checker(self) -> None:
        service = make_storage_service()[0]
        integrity = service.integrity
        sentinel = object()
        integrity.verify_object = AsyncMock(return_value=sentinel)

        result = await service.verify_file_object(
            object_key="file.bin",
            expected_size_bytes=100,
            expected_checksum="abc",
            require_exact_metadata_match=True,
        )

        assert result is sentinel
        call_kwargs = integrity.verify_object.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket
        assert call_kwargs["object_key"] == "file.bin"
        assert call_kwargs["expected_size_bytes"] == 100
        assert call_kwargs["expected_checksum"] == "abc"
        assert call_kwargs["require_exact_metadata_match"] is True


# ---------------------------------------------------------------------------
# archive / preview objects
# ---------------------------------------------------------------------------

class TestArchiveAndPreviewObjects:
    @pytest.mark.asyncio
    async def test_upload_archive_object(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_object_info(bucket="localcloud-archives")
        object_manager.put_object = AsyncMock(return_value=expected)
        user_id = uuid.uuid4()
        task_id = uuid.uuid4()

        result = await service.upload_archive_object(
            user_id=user_id,
            task_id=task_id,
            data=b"zip-data",
            length=8,
        )

        assert result is expected
        call_kwargs = object_manager.put_object.call_args[1]
        assert call_kwargs["bucket"] == service.default_archives_bucket
        assert call_kwargs["object_key"].endswith(".zip")
        assert isinstance(call_kwargs["metadata"], StorageObjectMetadata)

    @pytest.mark.asyncio
    async def test_upload_archive_object_merges_extra_metadata(self) -> None:
        service, object_manager, *_ = make_storage_service()
        object_manager.put_object = AsyncMock(return_value=_make_object_info())

        await service.upload_archive_object(
            user_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            data=b"zip-data",
            length=8,
            metadata={"custom": "value"},
        )

        call_kwargs = object_manager.put_object.call_args[1]
        assert isinstance(call_kwargs["metadata"], StorageObjectMetadata)

    @pytest.mark.asyncio
    async def test_upload_preview_object(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_object_info()
        object_manager.put_object = AsyncMock(return_value=expected)

        result = await service.upload_preview_object(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            data=b"preview-data",
            length=12,
            content_type="image/png",
            extension="png",
        )

        assert result is expected
        call_kwargs = object_manager.put_object.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket
        assert call_kwargs["content_type"] == "image/png"
        assert isinstance(call_kwargs["metadata"], StorageObjectMetadata)

    @pytest.mark.asyncio
    async def test_download_archive_object(self) -> None:
        service, object_manager, *_ = make_storage_service()
        expected = _make_download_result(bucket="localcloud-archives")
        object_manager.get_object_bytes = AsyncMock(return_value=expected)

        result = await service.download_archive_object(
            user_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
        )

        assert result is expected
        call_kwargs = object_manager.get_object_bytes.call_args[1]
        assert call_kwargs["bucket"] == service.default_archives_bucket
        assert call_kwargs["object_key"].endswith(".zip")

    @pytest.mark.asyncio
    async def test_delete_archive_object(self) -> None:
        service, object_manager, *_ = make_storage_service()
        object_manager.delete_object = AsyncMock(return_value=True)

        result = await service.delete_archive_object(
            user_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            missing_ok=True,
        )

        assert result is True
        call_kwargs = object_manager.delete_object.call_args[1]
        assert call_kwargs["bucket"] == service.default_archives_bucket
        assert call_kwargs["missing_ok"] is True

    @pytest.mark.asyncio
    async def test_delete_preview_object(self) -> None:
        service, object_manager, *_ = make_storage_service()
        object_manager.delete_object = AsyncMock(return_value=True)

        result = await service.delete_preview_object(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
        )

        assert result is True
        call_kwargs = object_manager.delete_object.call_args[1]
        assert call_kwargs["bucket"] == service.default_files_bucket


# ---------------------------------------------------------------------------
# build_file_version_key
# ---------------------------------------------------------------------------

class TestBuildFileVersionKey:
    def test_build_file_version_key(self) -> None:
        service, *_ = make_storage_service()
        key = service.build_file_version_key(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
        )
        assert isinstance(key, str)
        assert len(key) > 0


# ---------------------------------------------------------------------------
# bucket resolvers
# ---------------------------------------------------------------------------

class TestBucketResolvers:
    def test_resolve_temp_bucket_default(self) -> None:
        service, *_ = make_storage_service()
        assert service._resolve_temp_bucket(None) == service.default_temp_bucket

    def test_resolve_temp_bucket_explicit(self) -> None:
        service, *_ = make_storage_service()
        assert service._resolve_temp_bucket("localcloud-files") == "localcloud-files"

    def test_resolve_archives_bucket_default(self) -> None:
        service, *_ = make_storage_service()
        assert service._resolve_archives_bucket(None) == service.default_archives_bucket

    def test_resolve_archives_bucket_explicit(self) -> None:
        service, *_ = make_storage_service()
        assert service._resolve_archives_bucket("localcloud-temp") == "localcloud-temp"


# ---------------------------------------------------------------------------
# metadata building branches
# ---------------------------------------------------------------------------

class TestBuildFileUploadMetadata:
    def test_returns_empty_when_ids_missing(self) -> None:
        result = StorageService._build_file_upload_metadata(
            user_id=None,
            file_id=None,
            version_id=None,
            checksum=None,
            checksum_algorithm=None,
            original_filename=None,
            content_type=None,
            created_by=None,
        )
        assert isinstance(result, StorageObjectMetadata)

    def test_builds_file_metadata_without_version(self) -> None:
        result = StorageService._build_file_upload_metadata(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            version_id=None,
            checksum="abc",
            checksum_algorithm=None,
            original_filename="name.txt",
            content_type="text/plain",
            created_by=None,
        )
        assert isinstance(result, StorageObjectMetadata)

    def test_builds_file_version_metadata_with_version(self) -> None:
        result = StorageService._build_file_upload_metadata(
            user_id=uuid.uuid4(),
            file_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            checksum=None,
            checksum_algorithm=None,
            original_filename=None,
            content_type=None,
            created_by=None,
        )
        assert isinstance(result, StorageObjectMetadata)


# ---------------------------------------------------------------------------
# get_storage_service factory
# ---------------------------------------------------------------------------

class TestGetStorageServiceFactory:
    def test_creates_service(self) -> None:
        from storage.service import get_storage_service

        settings = MagicMock()
        settings.minio_region = "us-east-1"
        client = MagicMock()

        service = get_storage_service(settings=settings, client=client)

        assert isinstance(service, StorageService)
        assert service.client is client
        assert service.settings is settings
