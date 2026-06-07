"""Unit-тесты для StoragePresignedUrlManager."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from storage.buckets import StorageBucketNameValidator
from storage.exceptions import (
    StorageConnectionError,
    StorageError,
    StoragePresignedUrlError,
)
from storage.presigned import StoragePresignedUrlManager
from storage.types import StoragePresignedUrlMethod


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_validator() -> StorageBucketNameValidator:
    return StorageBucketNameValidator(min_length=3, max_length=63)


def make_raw_client():
    raw = MagicMock()
    raw.get_presigned_url = MagicMock(
        return_value="http://localhost:9000/test-bucket/file.txt?X-Amz-Signature=abc"
    )
    return raw


def make_client(public_url: str = "http://localhost:9000"):
    raw = make_raw_client()
    client = MagicMock()
    client.get_raw_client = MagicMock(return_value=raw)
    client.settings = MagicMock()
    client.settings.minio_public_url = public_url
    client.settings.minio_base_url = "http://localhost:9000"

    async def execute(fn, *args, operation_name=None, **kwargs):
        if callable(fn):
            return fn(*args, **kwargs)
        return fn

    client.execute = AsyncMock(side_effect=execute)
    return client, raw


def make_manager(public_url: str = "http://localhost:9000"):
    client, raw = make_client(public_url=public_url)
    manager = StoragePresignedUrlManager(
        client=client,
        bucket_name_validator=make_validator(),
    )
    return manager, client, raw


# ---------------------------------------------------------------------------
# generate_presigned_get_url
# ---------------------------------------------------------------------------

class TestGeneratePresignedGetUrl:
    @pytest.mark.asyncio
    async def test_returns_presigned_url(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.generate_presigned_get_url(
            bucket="test-bucket",
            object_key="file.txt",
            expires_in_seconds=3600,
        )
        assert result.url.startswith("http://")
        assert "test-bucket" in result.url or "file.txt" in result.url

    @pytest.mark.asyncio
    async def test_returns_correct_method(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.generate_presigned_get_url(
            bucket="test-bucket",
            object_key="file.txt",
            expires_in_seconds=3600,
        )
        from storage.types import StoragePresignedUrlMethod
        assert result.method == StoragePresignedUrlMethod.GET

    @pytest.mark.asyncio
    async def test_storage_error_raises_presigned_error(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name and "presigned" in operation_name:
                raise StorageError("sign failed", details={"reason": "error"})
            if callable(fn):
                return fn(*args, **kwargs)
            return fn

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises((StoragePresignedUrlError, StorageError)):
            await manager.generate_presigned_get_url(
                bucket="test-bucket",
                object_key="file.txt",
                expires_in_seconds=3600,
            )

    @pytest.mark.asyncio
    async def test_with_response_headers(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.generate_presigned_get_url(
            bucket="test-bucket",
            object_key="file.txt",
            expires_in_seconds=3600,
            response_headers={"Content-Disposition": "attachment; filename=file.txt"},
        )
        assert result.url.startswith("http://")


# ---------------------------------------------------------------------------
# generate_presigned_put_url
# ---------------------------------------------------------------------------

class TestGeneratePresignedPutUrl:
    @pytest.mark.asyncio
    async def test_returns_presigned_put_url(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.generate_presigned_put_url(
            bucket="test-bucket",
            object_key="upload.bin",
            expires_in_seconds=1800,
        )
        assert result.url.startswith("http://")

    @pytest.mark.asyncio
    async def test_returns_put_method(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.generate_presigned_put_url(
            bucket="test-bucket",
            object_key="upload.bin",
            expires_in_seconds=1800,
        )
        from storage.types import StoragePresignedUrlMethod
        assert result.method == StoragePresignedUrlMethod.PUT


# ---------------------------------------------------------------------------
# generate_presigned_delete_url
# ---------------------------------------------------------------------------

class TestGeneratePresignedDeleteUrl:
    @pytest.mark.asyncio
    async def test_returns_presigned_delete_url(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.generate_presigned_delete_url(
            bucket="test-bucket",
            object_key="file.txt",
            expires_in_seconds=3600,
        )
        assert result.url.startswith("http://")
        from storage.types import StoragePresignedUrlMethod
        assert result.method == StoragePresignedUrlMethod.DELETE


# ---------------------------------------------------------------------------
# validate_expires_in_seconds
# ---------------------------------------------------------------------------

class TestValidateExpiresInSeconds:
    def test_valid_expires_in_seconds(self) -> None:
        manager, client, raw = make_manager()
        result = manager.validate_expires_in_seconds(3600)
        assert result == 3600

    def test_non_int_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_expires_in_seconds("3600")  # type: ignore[arg-type]

    def test_bool_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_expires_in_seconds(True)  # type: ignore[arg-type]

    def test_zero_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_expires_in_seconds(0)

    def test_negative_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_expires_in_seconds(-100)

    def test_too_large_raises(self) -> None:
        manager, client, raw = make_manager()
        # 7 дней + 1 секунда превышает максимум.
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_expires_in_seconds(7 * 24 * 60 * 60 + 1)

    def test_max_valid_expires(self) -> None:
        manager, client, raw = make_manager()
        result = manager.validate_expires_in_seconds(7 * 24 * 60 * 60)
        assert result == 7 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# validate_part_number
# ---------------------------------------------------------------------------

class TestValidatePartNumber:
    def test_valid_part_number(self) -> None:
        manager, client, raw = make_manager()
        assert manager.validate_part_number(1) == 1
        assert manager.validate_part_number(100) == 100
        assert manager.validate_part_number(10000) == 10000

    def test_zero_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_part_number(0)

    def test_negative_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_part_number(-1)

    def test_bool_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_part_number(True)  # type: ignore[arg-type]

    def test_non_int_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_part_number("1")  # type: ignore[arg-type]

    def test_too_large_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_part_number(10001)


# ---------------------------------------------------------------------------
# validate_upload_id
# ---------------------------------------------------------------------------

class TestValidateUploadId:
    def test_valid_upload_id(self) -> None:
        result = StoragePresignedUrlManager.validate_upload_id("upload-id-123")
        assert result == "upload-id-123"

    def test_strips_whitespace(self) -> None:
        result = StoragePresignedUrlManager.validate_upload_id("  my-id  ")
        assert result == "my-id"

    def test_empty_raises(self) -> None:
        with pytest.raises(StoragePresignedUrlError):
            StoragePresignedUrlManager.validate_upload_id("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(StoragePresignedUrlError):
            StoragePresignedUrlManager.validate_upload_id("   ")

    def test_non_string_raises(self) -> None:
        with pytest.raises(StoragePresignedUrlError):
            StoragePresignedUrlManager.validate_upload_id(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# normalize_response_headers
# ---------------------------------------------------------------------------

class TestNormalizeResponseHeaders:
    def test_none_returns_empty_dict(self) -> None:
        result = StoragePresignedUrlManager.normalize_response_headers(None)
        assert result == {}

    def test_valid_headers_returned(self) -> None:
        result = StoragePresignedUrlManager.normalize_response_headers(
            {"Content-Type": "text/plain"}
        )
        assert result == {"Content-Type": "text/plain"}

    def test_non_dict_raises(self) -> None:
        with pytest.raises(StoragePresignedUrlError):
            StoragePresignedUrlManager.normalize_response_headers("not-a-dict")  # type: ignore[arg-type]

    def test_empty_value_skipped(self) -> None:
        result = StoragePresignedUrlManager.normalize_response_headers(
            {"Content-Type": "text/plain", "X-Empty": ""}
        )
        assert "X-Empty" not in result
        assert result["Content-Type"] == "text/plain"

    def test_empty_key_raises(self) -> None:
        with pytest.raises(StoragePresignedUrlError):
            StoragePresignedUrlManager.normalize_response_headers({"": "value"})


# ---------------------------------------------------------------------------
# public URL replacement
# ---------------------------------------------------------------------------

class TestToPublicUrl:
    @pytest.mark.asyncio
    async def test_url_rewritten_to_public(self) -> None:
        # public_url отличается от внутреннего base_url.
        client, raw = make_client(public_url="https://public.example.com")
        client.settings.minio_base_url = "http://localhost:9000"
        raw.get_presigned_url.return_value = (
            "http://localhost:9000/test-bucket/file.txt?sig=abc"
        )
        manager = StoragePresignedUrlManager(
            client=client,
            bucket_name_validator=make_validator(),
        )
        result = await manager.generate_presigned_get_url(
            bucket="test-bucket",
            object_key="file.txt",
            expires_in_seconds=3600,
        )
        assert result.url.startswith("https://public.example.com")

    @pytest.mark.asyncio
    async def test_url_unchanged_when_same_base_and_public(self) -> None:
        client, raw = make_client(public_url="http://localhost:9000")
        client.settings.minio_base_url = "http://localhost:9000"
        raw.get_presigned_url.return_value = (
            "http://localhost:9000/test-bucket/file.txt?sig=abc"
        )
        manager = StoragePresignedUrlManager(
            client=client,
            bucket_name_validator=make_validator(),
        )
        result = await manager.generate_presigned_get_url(
            bucket="test-bucket",
            object_key="file.txt",
            expires_in_seconds=3600,
        )
        assert result.url == "http://localhost:9000/test-bucket/file.txt?sig=abc"


# ---------------------------------------------------------------------------
# generate_presigned_upload_part_url
# ---------------------------------------------------------------------------

class TestGeneratePresignedUploadPartUrl:
    @pytest.mark.asyncio
    async def test_returns_presigned_url_with_part_params(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.generate_presigned_upload_part_url(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            part_number=1,
            expires_in_seconds=3600,
        )
        assert result.url.startswith("http://")

    @pytest.mark.asyncio
    async def test_invalid_part_number_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            await manager.generate_presigned_upload_part_url(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number=0,
                expires_in_seconds=3600,
            )

    @pytest.mark.asyncio
    async def test_passes_part_query_params_to_client(self) -> None:
        manager, client, raw = make_manager()
        await manager.generate_presigned_upload_part_url(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="  upload-id-123  ",
            part_number=5,
            expires_in_seconds=3600,
        )
        # execute(fn, method, bucket, key, expires=..., extra_query_params=...)
        _, call = client.execute.call_args
        args = client.execute.call_args.args
        assert args[1] == StoragePresignedUrlMethod.PUT.value
        assert args[2] == "test-bucket"
        assert call["extra_query_params"] == {
            "partNumber": "5",
            "uploadId": "upload-id-123",
        }
        assert call["operation_name"] == "generate_presigned_upload_part_url"

    @pytest.mark.asyncio
    async def test_storage_error_mapped_with_details(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "generate_presigned_upload_part_url":
                raise StorageError("boom", details={"x": 1})
            return fn(*args, **kwargs) if callable(fn) else fn

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StoragePresignedUrlError) as exc_info:
            await manager.generate_presigned_upload_part_url(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_number=3,
                expires_in_seconds=3600,
            )
        details = exc_info.value.details
        assert details["upload_id"] == "upload-id-123"
        assert details["part_number"] == 3
        assert details["operation"] == "generate_presigned_upload_part_url"


# ---------------------------------------------------------------------------
# generate_presigned_upload_part_urls (batch)
# ---------------------------------------------------------------------------

class TestGeneratePresignedUploadPartUrls:
    @pytest.mark.asyncio
    async def test_returns_one_dto_per_part(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.generate_presigned_upload_part_urls(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            part_numbers=[1, 2, 3],
            expires_in_seconds=3600,
        )
        assert [item.part_number for item in result] == [1, 2, 3]
        for item in result:
            assert item.url.url.startswith("http://")
            assert item.url.method == StoragePresignedUrlMethod.PUT

    @pytest.mark.asyncio
    async def test_accepts_range(self) -> None:
        manager, client, raw = make_manager()
        result = await manager.generate_presigned_upload_part_urls(
            bucket="test-bucket",
            object_key="large-file.bin",
            upload_id="upload-id-123",
            part_numbers=range(1, 3),
            expires_in_seconds=3600,
        )
        assert [item.part_number for item in result] == [1, 2]

    @pytest.mark.asyncio
    async def test_invalid_part_number_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            await manager.generate_presigned_upload_part_urls(
                bucket="test-bucket",
                object_key="large-file.bin",
                upload_id="upload-id-123",
                part_numbers=[1, 0],
                expires_in_seconds=3600,
            )


# ---------------------------------------------------------------------------
# version_id query param
# ---------------------------------------------------------------------------

class TestVersionIdParam:
    @pytest.mark.asyncio
    async def test_version_id_passed_as_query_param(self) -> None:
        manager, client, raw = make_manager()
        await manager.generate_presigned_get_url(
            bucket="test-bucket",
            object_key="file.txt",
            expires_in_seconds=3600,
            version_id="  v-42  ",
        )
        _, call = client.execute.call_args
        assert call["extra_query_params"] == {"versionId": "v-42"}

    @pytest.mark.asyncio
    async def test_blank_version_id_not_passed(self) -> None:
        manager, client, raw = make_manager()
        await manager.generate_presigned_get_url(
            bucket="test-bucket",
            object_key="file.txt",
            expires_in_seconds=3600,
            version_id="   ",
        )
        _, call = client.execute.call_args
        assert call["extra_query_params"] is None


# ---------------------------------------------------------------------------
# validate_size_range
# ---------------------------------------------------------------------------

class TestValidateSizeRange:
    def test_both_none_ok(self) -> None:
        manager, client, raw = make_manager()
        assert (
            manager.validate_size_range(min_size_bytes=None, max_size_bytes=None)
            is None
        )

    def test_valid_range_ok(self) -> None:
        manager, client, raw = make_manager()
        assert (
            manager.validate_size_range(min_size_bytes=0, max_size_bytes=1024)
            is None
        )

    def test_min_non_int_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_size_range(
                min_size_bytes="0",  # type: ignore[arg-type]
                max_size_bytes=None,
            )

    def test_min_bool_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_size_range(
                min_size_bytes=True,  # type: ignore[arg-type]
                max_size_bytes=None,
            )

    def test_min_negative_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_size_range(min_size_bytes=-1, max_size_bytes=None)

    def test_max_non_int_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_size_range(
                min_size_bytes=None,
                max_size_bytes=1.5,  # type: ignore[arg-type]
            )

    def test_max_bool_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_size_range(
                min_size_bytes=None,
                max_size_bytes=False,  # type: ignore[arg-type]
            )

    def test_max_zero_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_size_range(min_size_bytes=None, max_size_bytes=0)

    def test_max_too_large_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_size_range(
                min_size_bytes=None,
                max_size_bytes=5 * 1024 * 1024 * 1024 + 1,
            )

    def test_min_greater_than_max_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(StoragePresignedUrlError):
            manager.validate_size_range(min_size_bytes=100, max_size_bytes=10)


# ---------------------------------------------------------------------------
# normalize_optional_header_value
# ---------------------------------------------------------------------------

class TestNormalizeOptionalHeaderValue:
    def test_none_returns_none(self) -> None:
        assert (
            StoragePresignedUrlManager.normalize_optional_header_value(
                None, field_name="content_type"
            )
            is None
        )

    def test_valid_value_stripped(self) -> None:
        assert (
            StoragePresignedUrlManager.normalize_optional_header_value(
                "  text/plain  ", field_name="content_type"
            )
            == "text/plain"
        )

    def test_blank_returns_none(self) -> None:
        assert (
            StoragePresignedUrlManager.normalize_optional_header_value(
                "   ", field_name="content_type"
            )
            is None
        )

    def test_non_string_raises(self) -> None:
        with pytest.raises(StoragePresignedUrlError):
            StoragePresignedUrlManager.normalize_optional_header_value(
                123,  # type: ignore[arg-type]
                field_name="content_type",
            )

    def test_newline_raises(self) -> None:
        with pytest.raises(StoragePresignedUrlError):
            StoragePresignedUrlManager.normalize_optional_header_value(
                "value\ninjected", field_name="content_type"
            )

    def test_carriage_return_raises(self) -> None:
        with pytest.raises(StoragePresignedUrlError):
            StoragePresignedUrlManager.normalize_optional_header_value(
                "value\rinjected", field_name="content_type"
            )


# ---------------------------------------------------------------------------
# _to_public_url fallback + _build_post_policy_url
# ---------------------------------------------------------------------------

class TestUrlHelpers:
    @pytest.mark.asyncio
    async def test_url_unchanged_when_not_prefixed_by_internal_base(self) -> None:
        client, raw = make_client(public_url="https://public.example.com")
        client.settings.minio_base_url = "http://localhost:9000"
        raw.get_presigned_url.return_value = (
            "http://other-host:1234/test-bucket/file.txt?sig=abc"
        )
        manager = StoragePresignedUrlManager(
            client=client,
            bucket_name_validator=make_validator(),
        )
        result = await manager.generate_presigned_get_url(
            bucket="test-bucket",
            object_key="file.txt",
            expires_in_seconds=3600,
        )
        assert result.url == "http://other-host:1234/test-bucket/file.txt?sig=abc"

    def test_build_post_policy_url(self) -> None:
        manager, client, raw = make_manager(public_url="https://public.example.com")
        assert (
            manager._build_post_policy_url("test-bucket")
            == "https://public.example.com/test-bucket"
        )


# ---------------------------------------------------------------------------
# _build_presigned_url_result пустой URL
# ---------------------------------------------------------------------------

class TestBuildPresignedUrlResult:
    @pytest.mark.asyncio
    async def test_empty_url_raises(self) -> None:
        manager, client, raw = make_manager()
        raw.get_presigned_url.return_value = ""
        with pytest.raises(StoragePresignedUrlError):
            await manager.generate_presigned_get_url(
                bucket="test-bucket",
                object_key="file.txt",
                expires_in_seconds=3600,
            )

    @pytest.mark.asyncio
    async def test_non_string_url_raises(self) -> None:
        manager, client, raw = make_manager()
        raw.get_presigned_url.return_value = None
        with pytest.raises(StoragePresignedUrlError):
            await manager.generate_presigned_get_url(
                bucket="test-bucket",
                object_key="file.txt",
                expires_in_seconds=3600,
            )


# ---------------------------------------------------------------------------
# _presigned_error mapping branches
# ---------------------------------------------------------------------------

class TestPresignedErrorMapping:
    @pytest.mark.asyncio
    async def test_connection_error_passed_through(self) -> None:
        manager, client, raw = make_manager()
        original = StorageConnectionError("down")

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "generate_presigned_get_url":
                raise original
            return fn(*args, **kwargs) if callable(fn) else fn

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StorageConnectionError) as exc_info:
            await manager.generate_presigned_get_url(
                bucket="test-bucket",
                object_key="file.txt",
                expires_in_seconds=3600,
            )
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_presigned_error_passed_through(self) -> None:
        manager, client, raw = make_manager()
        original = StoragePresignedUrlError("already presigned error")

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "generate_presigned_get_url":
                raise original
            return fn(*args, **kwargs) if callable(fn) else fn

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StoragePresignedUrlError) as exc_info:
            await manager.generate_presigned_get_url(
                bucket="test-bucket",
                object_key="file.txt",
                expires_in_seconds=3600,
            )
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_generic_error_wrapped_with_reason(self) -> None:
        manager, client, raw = make_manager()

        async def execute_raises(fn, *args, operation_name=None, **kwargs):
            if operation_name == "generate_presigned_get_url":
                raise StorageError("low level failure", details={"k": "v"})
            return fn(*args, **kwargs) if callable(fn) else fn

        client.execute = AsyncMock(side_effect=execute_raises)

        with pytest.raises(StoragePresignedUrlError) as exc_info:
            await manager.generate_presigned_get_url(
                bucket="test-bucket",
                object_key="file.txt",
                expires_in_seconds=3600,
            )
        details = exc_info.value.details
        assert details["reason"] == "low level failure"
        assert details["operation"] == "generate_presigned_get_url"
        assert details["k"] == "v"
        assert exc_info.value.cause is not None
