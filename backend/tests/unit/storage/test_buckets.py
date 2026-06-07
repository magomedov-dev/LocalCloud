"""Unit-тесты для StorageBucketManager и валидатора имён бакетов."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from storage.buckets import StorageBucketManager, StorageBucketNameValidator
from storage.exceptions import (
    InvalidStorageBucketNameError,
    StorageBucketAlreadyExistsError,
    StorageBucketError,
    StorageBucketNotFoundError,
    StorageConnectionError,
    StorageError,
)
from storage.types import StorageBucketInfo


class TestStorageBucketNameValidatorInit:
    def test_valid_init(self) -> None:
        v = StorageBucketNameValidator(min_length=3, max_length=63)
        assert v.min_length == 3
        assert v.max_length == 63

    def test_non_int_min_length_raises(self) -> None:
        with pytest.raises(ValueError):
            StorageBucketNameValidator(min_length="3", max_length=63)  # type: ignore[arg-type]

    def test_non_int_max_length_raises(self) -> None:
        with pytest.raises(ValueError):
            StorageBucketNameValidator(min_length=3, max_length="63")  # type: ignore[arg-type]

    def test_bool_min_length_raises(self) -> None:
        with pytest.raises(ValueError):
            StorageBucketNameValidator(min_length=True, max_length=63)  # type: ignore[arg-type]

    def test_zero_min_length_raises(self) -> None:
        with pytest.raises(ValueError, match="больше нуля"):
            StorageBucketNameValidator(min_length=0, max_length=63)

    def test_negative_min_length_raises(self) -> None:
        with pytest.raises(ValueError):
            StorageBucketNameValidator(min_length=-1, max_length=63)

    def test_max_less_than_min_raises(self) -> None:
        with pytest.raises(ValueError, match="больше или равен"):
            StorageBucketNameValidator(min_length=10, max_length=5)

    def test_max_equals_min_valid(self) -> None:
        v = StorageBucketNameValidator(min_length=5, max_length=5)
        assert v.min_length == v.max_length


class TestStorageBucketNameValidatorValidate:
    def _make_validator(self, min_length: int = 3, max_length: int = 63) -> StorageBucketNameValidator:
        return StorageBucketNameValidator(min_length=min_length, max_length=max_length)

    def test_valid_lowercase_name(self) -> None:
        v = self._make_validator()
        result = v.validate("my-bucket")
        assert result == "my-bucket"

    def test_valid_name_with_numbers(self) -> None:
        v = self._make_validator()
        result = v.validate("bucket123")
        assert result == "bucket123"

    def test_uppercase_normalized_to_lowercase(self) -> None:
        v = self._make_validator()
        result = v.validate("MyBucket")
        assert result == "mybucket"

    def test_whitespace_stripped(self) -> None:
        v = self._make_validator()
        result = v.validate("  mybucket  ")
        assert result == "mybucket"

    def test_non_string_raises(self) -> None:
        v = self._make_validator()
        with pytest.raises(InvalidStorageBucketNameError):
            v.validate(123)  # type: ignore[arg-type]

    def test_empty_string_raises(self) -> None:
        v = self._make_validator()
        with pytest.raises(InvalidStorageBucketNameError):
            v.validate("")

    def test_whitespace_only_raises(self) -> None:
        v = self._make_validator()
        with pytest.raises(InvalidStorageBucketNameError):
            v.validate("   ")

    def test_too_short_raises(self) -> None:
        v = self._make_validator(min_length=5)
        with pytest.raises(InvalidStorageBucketNameError) as exc_info:
            v.validate("ab")
        assert "короткое" in exc_info.value.message.lower() or "short" in exc_info.value.message.lower()

    def test_too_long_raises(self) -> None:
        v = self._make_validator(max_length=10)
        with pytest.raises(InvalidStorageBucketNameError) as exc_info:
            v.validate("a" * 11)
        assert "длинное" in exc_info.value.message.lower() or "long" in exc_info.value.message.lower()

    def test_exactly_min_length_valid(self) -> None:
        v = self._make_validator(min_length=3, max_length=63)
        result = v.validate("abc")
        assert result == "abc"

    def test_exactly_max_length_valid(self) -> None:
        v = self._make_validator(min_length=3, max_length=10)
        result = v.validate("a" * 10)
        assert result == "a" * 10

    def test_invalid_characters_raises(self) -> None:
        v = self._make_validator()
        with pytest.raises(InvalidStorageBucketNameError):
            v.validate("bucket_name")  # подчёркивание не допускается

    def test_uppercase_chars_in_middle_valid_after_lower(self) -> None:
        v = self._make_validator()
        result = v.validate("MyBucket123")
        assert result == "mybucket123"

    def test_repeated_dots_raises(self) -> None:
        v = self._make_validator()
        with pytest.raises(InvalidStorageBucketNameError) as exc_info:
            v.validate("my..bucket")
        assert "точки" in exc_info.value.message.lower() or "dots" in exc_info.value.message.lower()

    def test_dot_dash_raises(self) -> None:
        v = self._make_validator()
        with pytest.raises(InvalidStorageBucketNameError) as exc_info:
            v.validate("my.-bucket")
        assert ".-" in exc_info.value.message or "-." in exc_info.value.message

    def test_dash_dot_raises(self) -> None:
        v = self._make_validator()
        with pytest.raises(InvalidStorageBucketNameError):
            v.validate("my-.bucket")

    def test_ip_like_name_raises(self) -> None:
        v = self._make_validator()
        with pytest.raises(InvalidStorageBucketNameError) as exc_info:
            v.validate("192.168.1.1")
        assert "ipv4" in exc_info.value.message.lower() or "ip" in exc_info.value.message.lower()

    def test_name_with_valid_dots_allowed(self) -> None:
        v = self._make_validator()
        result = v.validate("my.bucket.name")
        assert result == "my.bucket.name"

    def test_name_with_dashes_allowed(self) -> None:
        v = self._make_validator()
        result = v.validate("my-bucket-name")
        assert result == "my-bucket-name"


# ---------------------------------------------------------------------------
# Вспомогательные функции для тестов StorageBucketManager
# ---------------------------------------------------------------------------

def make_validator() -> StorageBucketNameValidator:
    return StorageBucketNameValidator(min_length=3, max_length=63)


def make_bucket(name: str, created_at: datetime | None = None) -> SimpleNamespace:
    """Эмулирует объект bucket из MinIO SDK."""
    return SimpleNamespace(name=name, creation_date=created_at)


def make_client() -> tuple[MagicMock, MagicMock]:
    """Создаёт замоканный StorageClient с проксирующим execute."""
    raw = MagicMock()
    client = MagicMock()
    client.get_raw_client = MagicMock(return_value=raw)

    async def execute(fn, *args, operation_name=None, **kwargs):
        return fn(*args, **kwargs)

    client.execute = AsyncMock(side_effect=execute)
    return client, raw


def make_manager() -> tuple[StorageBucketManager, MagicMock, MagicMock]:
    client, raw = make_client()
    manager = StorageBucketManager(
        client=client,
        bucket_name_validator=make_validator(),
    )
    return manager, client, raw


# ---------------------------------------------------------------------------
# bucket_exists
# ---------------------------------------------------------------------------

class TestBucketExists:
    @pytest.mark.asyncio
    async def test_returns_true(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        result = await manager.bucket_exists("My-Bucket")
        assert result is True
        raw.bucket_exists.assert_called_once_with("my-bucket")

    @pytest.mark.asyncio
    async def test_returns_false(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=False)
        assert await manager.bucket_exists("my-bucket") is False

    @pytest.mark.asyncio
    async def test_invalid_name_raises(self) -> None:
        manager, client, raw = make_manager()
        with pytest.raises(InvalidStorageBucketNameError):
            await manager.bucket_exists("ab")

    @pytest.mark.asyncio
    async def test_storage_error_mapped(self) -> None:
        manager, client, raw = make_manager()
        client.execute = AsyncMock(side_effect=StorageError("boom"))
        with pytest.raises(StorageBucketError):
            await manager.bucket_exists("my-bucket")


# ---------------------------------------------------------------------------
# get_bucket_info
# ---------------------------------------------------------------------------

class TestGetBucketInfo:
    @pytest.mark.asyncio
    async def test_found(self) -> None:
        manager, client, raw = make_manager()
        created = datetime(2024, 1, 1, tzinfo=timezone.utc)
        raw.list_buckets = MagicMock(
            return_value=[make_bucket("other"), make_bucket("my-bucket", created)]
        )
        info = await manager.get_bucket_info("my-bucket")
        assert isinstance(info, StorageBucketInfo)
        assert info.name == "my-bucket"
        assert info.created_at == created

    @pytest.mark.asyncio
    async def test_not_found_raises(self) -> None:
        manager, client, raw = make_manager()
        raw.list_buckets = MagicMock(return_value=[make_bucket("other")])
        with pytest.raises(StorageBucketNotFoundError):
            await manager.get_bucket_info("my-bucket")

    @pytest.mark.asyncio
    async def test_storage_error_mapped(self) -> None:
        manager, client, raw = make_manager()
        client.execute = AsyncMock(side_effect=StorageError("boom"))
        with pytest.raises(StorageBucketError):
            await manager.get_bucket_info("my-bucket")


# ---------------------------------------------------------------------------
# require_bucket_exists
# ---------------------------------------------------------------------------

class TestRequireBucketExists:
    @pytest.mark.asyncio
    async def test_exists_returns_info(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.list_buckets = MagicMock(return_value=[make_bucket("my-bucket")])
        info = await manager.require_bucket_exists("my-bucket")
        assert info.name == "my-bucket"

    @pytest.mark.asyncio
    async def test_missing_raises_not_found(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=False)
        with pytest.raises(StorageBucketNotFoundError):
            await manager.require_bucket_exists("my-bucket")


# ---------------------------------------------------------------------------
# list_buckets
# ---------------------------------------------------------------------------

class TestListBuckets:
    @pytest.mark.asyncio
    async def test_returns_all(self) -> None:
        manager, client, raw = make_manager()
        created = datetime(2024, 1, 1, tzinfo=timezone.utc)
        raw.list_buckets = MagicMock(
            return_value=[make_bucket("alpha", created), make_bucket("beta")]
        )
        result = await manager.list_buckets()
        assert [b.name for b in result] == ["alpha", "beta"]
        assert result[0].created_at == created
        assert result[1].created_at is None

    @pytest.mark.asyncio
    async def test_skips_nameless_bucket(self) -> None:
        manager, client, raw = make_manager()
        raw.list_buckets = MagicMock(
            return_value=[make_bucket(None), make_bucket("alpha")]
        )
        result = await manager.list_buckets()
        assert [b.name for b in result] == ["alpha"]

    @pytest.mark.asyncio
    async def test_invalid_name_kept_unnormalized(self) -> None:
        manager, client, raw = make_manager()
        # Имя не проходит валидацию (uppercase + underscore) -> остаётся как есть.
        raw.list_buckets = MagicMock(return_value=[make_bucket("BAD_NAME")])
        result = await manager.list_buckets()
        assert result[0].name == "BAD_NAME"

    @pytest.mark.asyncio
    async def test_storage_error_mapped(self) -> None:
        manager, client, raw = make_manager()
        client.execute = AsyncMock(side_effect=StorageError("boom"))
        with pytest.raises(StorageBucketError):
            await manager.list_buckets()


# ---------------------------------------------------------------------------
# create_bucket
# ---------------------------------------------------------------------------

class TestCreateBucket:
    @pytest.mark.asyncio
    async def test_creates_when_absent(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=False)
        raw.make_bucket = MagicMock(return_value=None)
        raw.list_buckets = MagicMock(return_value=[make_bucket("my-bucket")])
        info = await manager.create_bucket("my-bucket", region="us-east-1")
        assert info.name == "my-bucket"
        raw.make_bucket.assert_called_once_with(
            "my-bucket", location="us-east-1", object_lock=False
        )

    @pytest.mark.asyncio
    async def test_object_lock_passed(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=False)
        raw.make_bucket = MagicMock(return_value=None)
        raw.list_buckets = MagicMock(return_value=[make_bucket("my-bucket")])
        await manager.create_bucket("my-bucket", object_lock=True)
        raw.make_bucket.assert_called_once_with(
            "my-bucket", location=None, object_lock=True
        )

    @pytest.mark.asyncio
    async def test_exists_ignore_returns_info(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.make_bucket = MagicMock(return_value=None)
        raw.list_buckets = MagicMock(return_value=[make_bucket("my-bucket")])
        info = await manager.create_bucket("my-bucket", ignore_existing=True)
        assert info.name == "my-bucket"
        raw.make_bucket.assert_not_called()

    @pytest.mark.asyncio
    async def test_exists_no_ignore_raises(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        with pytest.raises(StorageBucketAlreadyExistsError):
            await manager.create_bucket("my-bucket", ignore_existing=False)

    @pytest.mark.asyncio
    async def test_make_bucket_error_mapped(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=False)

        async def execute(fn, *args, operation_name=None, **kwargs):
            if operation_name == "create_bucket":
                raise StorageError("boom")
            return fn(*args, **kwargs)

        client.execute = AsyncMock(side_effect=execute)
        with pytest.raises(StorageBucketError):
            await manager.create_bucket("my-bucket")


# ---------------------------------------------------------------------------
# ensure_bucket_exists / ensure_buckets_exist
# ---------------------------------------------------------------------------

class TestEnsureBucketExists:
    @pytest.mark.asyncio
    async def test_existing_returns_info_no_create(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.make_bucket = MagicMock(return_value=None)
        raw.list_buckets = MagicMock(return_value=[make_bucket("my-bucket")])
        info = await manager.ensure_bucket_exists("my-bucket")
        assert info.name == "my-bucket"
        raw.make_bucket.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_creates(self) -> None:
        manager, client, raw = make_manager()
        # Сначала отсутствует (ensure + create check), затем create.
        raw.bucket_exists = MagicMock(side_effect=[False, False])
        raw.make_bucket = MagicMock(return_value=None)
        raw.list_buckets = MagicMock(return_value=[make_bucket("my-bucket")])
        info = await manager.ensure_bucket_exists("my-bucket", region="eu")
        assert info.name == "my-bucket"
        raw.make_bucket.assert_called_once_with(
            "my-bucket", location="eu", object_lock=False
        )

    @pytest.mark.asyncio
    async def test_ensure_buckets_exist_multiple(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.list_buckets = MagicMock(
            return_value=[make_bucket("alpha"), make_bucket("beta")]
        )
        result = await manager.ensure_buckets_exist(["alpha", "beta"])
        assert sorted(b.name for b in result) == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# remove_bucket
# ---------------------------------------------------------------------------

class TestRemoveBucket:
    @pytest.mark.asyncio
    async def test_removes_existing(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.remove_bucket = MagicMock(return_value=None)
        result = await manager.remove_bucket("my-bucket")
        assert result is True
        raw.remove_bucket.assert_called_once_with("my-bucket")

    @pytest.mark.asyncio
    async def test_missing_ok_returns_false(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=False)
        result = await manager.remove_bucket("my-bucket", missing_ok=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_missing_not_ok_raises(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=False)
        with pytest.raises(StorageBucketNotFoundError):
            await manager.remove_bucket("my-bucket", missing_ok=False)

    @pytest.mark.asyncio
    async def test_remove_error_mapped(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)

        async def execute(fn, *args, operation_name=None, **kwargs):
            if operation_name == "remove_bucket":
                raise StorageError("boom")
            return fn(*args, **kwargs)

        client.execute = AsyncMock(side_effect=execute)
        with pytest.raises(StorageBucketError):
            await manager.remove_bucket("my-bucket")


# ---------------------------------------------------------------------------
# check_bucket_access / check_buckets_access
# ---------------------------------------------------------------------------

class TestCheckBucketAccess:
    @pytest.mark.asyncio
    async def test_access_ok(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.list_buckets = MagicMock(return_value=[make_bucket("my-bucket")])
        assert await manager.check_bucket_access("my-bucket") is True

    @pytest.mark.asyncio
    async def test_missing_raises(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=False)
        with pytest.raises(StorageBucketNotFoundError):
            await manager.check_bucket_access("my-bucket")

    @pytest.mark.asyncio
    async def test_check_buckets_access_map(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.list_buckets = MagicMock(
            return_value=[make_bucket("alpha"), make_bucket("beta")]
        )
        result = await manager.check_buckets_access(["Alpha", "beta"])
        assert result == {"alpha": True, "beta": True}


# ---------------------------------------------------------------------------
# bucket_is_empty / remove_bucket_if_empty
# ---------------------------------------------------------------------------

class TestBucketIsEmpty:
    @pytest.mark.asyncio
    async def test_empty(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.list_objects = MagicMock(return_value=iter([]))
        assert await manager.bucket_is_empty("my-bucket") is True

    @pytest.mark.asyncio
    async def test_not_empty(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.list_objects = MagicMock(return_value=iter([object()]))
        assert await manager.bucket_is_empty("my-bucket") is False

    @pytest.mark.asyncio
    async def test_missing_raises(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=False)
        with pytest.raises(StorageBucketNotFoundError):
            await manager.bucket_is_empty("my-bucket")

    @pytest.mark.asyncio
    async def test_list_objects_error_mapped(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)

        async def execute(fn, *args, operation_name=None, **kwargs):
            if operation_name == "bucket_is_empty":
                raise StorageError("boom")
            return fn(*args, **kwargs)

        client.execute = AsyncMock(side_effect=execute)
        with pytest.raises(StorageBucketError):
            await manager.bucket_is_empty("my-bucket")


class TestRemoveBucketIfEmpty:
    @pytest.mark.asyncio
    async def test_empty_removed(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.list_objects = MagicMock(return_value=iter([]))
        raw.remove_bucket = MagicMock(return_value=None)
        assert await manager.remove_bucket_if_empty("my-bucket") is True
        raw.remove_bucket.assert_called_once_with("my-bucket")

    @pytest.mark.asyncio
    async def test_not_empty_raises(self) -> None:
        manager, client, raw = make_manager()
        raw.bucket_exists = MagicMock(return_value=True)
        raw.list_objects = MagicMock(return_value=iter([object()]))
        with pytest.raises(StorageBucketError):
            await manager.remove_bucket_if_empty("my-bucket")


# ---------------------------------------------------------------------------
# _extract_bucket_created_at
# ---------------------------------------------------------------------------

class TestExtractBucketCreatedAt:
    def test_returns_datetime(self) -> None:
        created = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert (
            StorageBucketManager._extract_bucket_created_at(make_bucket("x", created))
            == created
        )

    def test_returns_none_when_missing(self) -> None:
        assert StorageBucketManager._extract_bucket_created_at(object()) is None

    def test_returns_none_when_not_datetime(self) -> None:
        obj = SimpleNamespace(creation_date="2024-01-01")
        assert StorageBucketManager._extract_bucket_created_at(obj) is None


# ---------------------------------------------------------------------------
# _bucket_error mapping
# ---------------------------------------------------------------------------

class TestBucketErrorMapping:
    def test_passes_through_not_found(self) -> None:
        exc = StorageBucketNotFoundError("b")
        result = StorageBucketManager._bucket_error(exc, bucket="b", operation="op")
        assert result is exc

    def test_passes_through_already_exists(self) -> None:
        exc = StorageBucketAlreadyExistsError("b")
        result = StorageBucketManager._bucket_error(exc, bucket="b", operation="op")
        assert result is exc

    def test_passes_through_connection_error(self) -> None:
        exc = StorageConnectionError()
        result = StorageBucketManager._bucket_error(exc, bucket="b", operation="op")
        assert result is exc

    def test_no_such_bucket_code_maps_to_not_found(self) -> None:
        exc = StorageError("e", details={"code": "NoSuchBucket"})
        result = StorageBucketManager._bucket_error(exc, bucket="b", operation="op")
        assert isinstance(result, StorageBucketNotFoundError)

    def test_status_404_maps_to_not_found(self) -> None:
        exc = StorageError("e", details={"status_code": 404})
        result = StorageBucketManager._bucket_error(exc, bucket="b", operation="op")
        assert isinstance(result, StorageBucketNotFoundError)

    def test_not_found_with_no_bucket_returns_bucket_error(self) -> None:
        exc = StorageError("e", details={"code": "NoSuchBucket"})
        result = StorageBucketManager._bucket_error(exc, bucket=None, operation="op")
        assert isinstance(result, StorageBucketError)
        assert not isinstance(result, StorageBucketNotFoundError)

    def test_already_owned_maps_to_already_exists(self) -> None:
        exc = StorageError("e", details={"code": "BucketAlreadyOwnedByYou"})
        result = StorageBucketManager._bucket_error(exc, bucket="b", operation="op")
        assert isinstance(result, StorageBucketAlreadyExistsError)

    def test_status_409_maps_to_already_exists(self) -> None:
        exc = StorageError("e", details={"status_code": 409})
        result = StorageBucketManager._bucket_error(exc, bucket="b", operation="op")
        assert isinstance(result, StorageBucketAlreadyExistsError)

    def test_already_exists_with_no_bucket_returns_bucket_error(self) -> None:
        exc = StorageError("e", details={"code": "BucketAlreadyExists"})
        result = StorageBucketManager._bucket_error(exc, bucket=None, operation="op")
        assert isinstance(result, StorageBucketError)
        assert not isinstance(result, StorageBucketAlreadyExistsError)

    def test_bucket_not_empty_code_maps_to_bucket_error(self) -> None:
        exc = StorageError("e", details={"code": "BucketNotEmpty"})
        result = StorageBucketManager._bucket_error(exc, bucket="b", operation="op")
        assert isinstance(result, StorageBucketError)
        assert result.details.get("reason") == "bucket_not_empty"

    def test_unknown_error_maps_to_generic_bucket_error(self) -> None:
        exc = StorageError("e", details={"code": "Whatever"})
        result = StorageBucketManager._bucket_error(exc, bucket="b", operation="op")
        assert isinstance(result, StorageBucketError)
        assert result.cause is exc
