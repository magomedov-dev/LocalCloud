"""Unit-тесты для StorageIntegrityChecker и функций расчёта контрольных сумм."""
from __future__ import annotations

import hashlib
import io
from unittest.mock import AsyncMock, MagicMock

import pytest

from storage.exceptions import (
    StorageConnectionError,
    StorageError,
    StorageIntegrityError,
    StorageObjectNotFoundError,
)
from storage.integrity import (
    StorageIntegrityChecker,
    calculate_bytes_checksum,
    calculate_stream_checksum,
    create_hash,
    normalize_checksum_algorithm,
    validate_checksum_chunk_size,
)
from storage.types import (
    StorageChecksumAlgorithm,
    StorageIntegrityProblemType,
    StorageObjectInfo,
    StorageObjectMetadata,
    StorageObjectStatus,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

_BUCKET = "localcloud-files"
_KEY = "test/file.bin"


def _make_object_info(
    *,
    size: int = 12,
    metadata: dict[str, str] | None = None,
    status: StorageObjectStatus = StorageObjectStatus.AVAILABLE,
    bucket: str = _BUCKET,
    key: str = _KEY,
) -> StorageObjectInfo:
    return StorageObjectInfo(
        bucket=bucket,
        object_key=key,
        size_bytes=size,
        content_type="application/octet-stream",
        etag="etag-abc",
        metadata=StorageObjectMetadata(values=metadata or {}),
        status=status,
    )


def _make_checker() -> tuple[StorageIntegrityChecker, MagicMock]:
    manager = MagicMock()
    manager.object_exists = AsyncMock()
    manager.stat_object = AsyncMock()
    manager.calculate_object_checksum = AsyncMock()
    checker = StorageIntegrityChecker(object_manager=manager)
    return checker, manager


class TestNormalizeChecksumAlgorithm:
    def test_enum_returned_unchanged(self) -> None:
        result = normalize_checksum_algorithm(StorageChecksumAlgorithm.SHA256)
        assert result == StorageChecksumAlgorithm.SHA256

    def test_string_md5_normalized(self) -> None:
        result = normalize_checksum_algorithm("md5")
        assert result == StorageChecksumAlgorithm.MD5

    def test_string_sha1_normalized(self) -> None:
        result = normalize_checksum_algorithm("sha1")
        assert result == StorageChecksumAlgorithm.SHA1

    def test_string_sha256_normalized(self) -> None:
        result = normalize_checksum_algorithm("sha256")
        assert result == StorageChecksumAlgorithm.SHA256

    def test_string_sha512_normalized(self) -> None:
        result = normalize_checksum_algorithm("sha512")
        assert result == StorageChecksumAlgorithm.SHA512

    def test_uppercase_string_normalized(self) -> None:
        result = normalize_checksum_algorithm("SHA256")
        assert result == StorageChecksumAlgorithm.SHA256

    def test_whitespace_stripped(self) -> None:
        result = normalize_checksum_algorithm("  sha256  ")
        assert result == StorageChecksumAlgorithm.SHA256

    def test_unsupported_algorithm_raises(self) -> None:
        with pytest.raises(StorageIntegrityError) as exc_info:
            normalize_checksum_algorithm("crc32")
        assert "алгоритм" in exc_info.value.message.lower() or "algorithm" in exc_info.value.message.lower()

    def test_non_string_non_enum_raises(self) -> None:
        with pytest.raises(StorageIntegrityError):
            normalize_checksum_algorithm(42)  # type: ignore[arg-type]

    def test_none_raises(self) -> None:
        with pytest.raises(StorageIntegrityError):
            normalize_checksum_algorithm(None)  # type: ignore[arg-type]


class TestCalculateBytesChecksum:
    def test_md5_matches_expected(self) -> None:
        data = b"hello world"
        expected = hashlib.md5(data).hexdigest()
        result = calculate_bytes_checksum(data, algorithm=StorageChecksumAlgorithm.MD5)
        assert result == expected

    def test_sha256_matches_expected(self) -> None:
        data = b"test data"
        expected = hashlib.sha256(data).hexdigest()
        result = calculate_bytes_checksum(data, algorithm=StorageChecksumAlgorithm.SHA256)
        assert result == expected

    def test_sha512_matches_expected(self) -> None:
        data = b"another test"
        expected = hashlib.sha512(data).hexdigest()
        result = calculate_bytes_checksum(data, algorithm=StorageChecksumAlgorithm.SHA512)
        assert result == expected

    def test_sha1_matches_expected(self) -> None:
        data = b"sha1 test"
        expected = hashlib.sha1(data).hexdigest()
        result = calculate_bytes_checksum(data, algorithm=StorageChecksumAlgorithm.SHA1)
        assert result == expected

    def test_bytearray_accepted(self) -> None:
        data = bytearray(b"test bytearray")
        result = calculate_bytes_checksum(data, algorithm="sha256")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_string_algorithm_accepted(self) -> None:
        data = b"test"
        result = calculate_bytes_checksum(data, algorithm="sha256")
        expected = hashlib.sha256(data).hexdigest()
        assert result == expected

    def test_empty_bytes_returns_checksum(self) -> None:
        result = calculate_bytes_checksum(b"", algorithm=StorageChecksumAlgorithm.SHA256)
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected

    def test_non_bytes_raises_integrity_error(self) -> None:
        with pytest.raises(StorageIntegrityError):
            calculate_bytes_checksum("not bytes", algorithm=StorageChecksumAlgorithm.SHA256)  # type: ignore[arg-type]

    def test_different_data_different_checksums(self) -> None:
        c1 = calculate_bytes_checksum(b"data1", algorithm=StorageChecksumAlgorithm.SHA256)
        c2 = calculate_bytes_checksum(b"data2", algorithm=StorageChecksumAlgorithm.SHA256)
        assert c1 != c2

    def test_same_data_same_checksum(self) -> None:
        data = b"consistent data"
        c1 = calculate_bytes_checksum(data, algorithm=StorageChecksumAlgorithm.SHA256)
        c2 = calculate_bytes_checksum(data, algorithm=StorageChecksumAlgorithm.SHA256)
        assert c1 == c2

    def test_returns_hex_string(self) -> None:
        data = b"hex test"
        result = calculate_bytes_checksum(data, algorithm=StorageChecksumAlgorithm.SHA256)
        assert all(c in "0123456789abcdef" for c in result)


class TestCreateHash:
    def test_md5(self) -> None:
        h = create_hash(StorageChecksumAlgorithm.MD5)
        h.update(b"abc")
        assert h.hexdigest() == hashlib.md5(b"abc").hexdigest()

    def test_sha1(self) -> None:
        h = create_hash(StorageChecksumAlgorithm.SHA1)
        assert h.name == "sha1"

    def test_sha256(self) -> None:
        h = create_hash(StorageChecksumAlgorithm.SHA256)
        assert h.name == "sha256"

    def test_sha512(self) -> None:
        h = create_hash(StorageChecksumAlgorithm.SHA512)
        assert h.name == "sha512"

    def test_unsupported_algorithm_raises(self) -> None:
        fake = MagicMock()
        fake.value = "crc32"
        with pytest.raises(StorageIntegrityError) as exc_info:
            create_hash(fake)
        assert exc_info.value.details["algorithm"] == "crc32"


class TestValidateChecksumChunkSize:
    def test_valid_returns_value(self) -> None:
        assert validate_checksum_chunk_size(1024) == 1024

    def test_non_int_raises(self) -> None:
        with pytest.raises(StorageIntegrityError):
            validate_checksum_chunk_size("1024")  # type: ignore[arg-type]

    def test_bool_raises(self) -> None:
        with pytest.raises(StorageIntegrityError):
            validate_checksum_chunk_size(True)  # type: ignore[arg-type]

    def test_zero_raises(self) -> None:
        with pytest.raises(StorageIntegrityError) as exc_info:
            validate_checksum_chunk_size(0)
        assert exc_info.value.details["chunk_size"] == 0

    def test_negative_raises(self) -> None:
        with pytest.raises(StorageIntegrityError):
            validate_checksum_chunk_size(-5)


class TestCalculateStreamChecksum:
    def test_matches_bytes_checksum(self) -> None:
        data = b"streaming hash data" * 100
        stream = io.BytesIO(data)
        result = calculate_stream_checksum(
            stream,
            algorithm=StorageChecksumAlgorithm.SHA256,
            chunk_size=64,
        )
        assert result == hashlib.sha256(data).hexdigest()

    def test_empty_stream(self) -> None:
        stream = io.BytesIO(b"")
        result = calculate_stream_checksum(
            stream,
            algorithm="sha256",
            chunk_size=64,
        )
        assert result == hashlib.sha256(b"").hexdigest()

    def test_position_reset_by_default(self) -> None:
        data = b"abcdefghij"
        stream = io.BytesIO(data)
        stream.seek(3)
        calculate_stream_checksum(
            stream,
            algorithm="sha256",
            chunk_size=4,
        )
        assert stream.tell() == 3

    def test_position_not_reset_when_disabled(self) -> None:
        data = b"abcdefghij"
        stream = io.BytesIO(data)
        stream.seek(2)
        calculate_stream_checksum(
            stream,
            algorithm="sha256",
            chunk_size=4,
            reset_position=False,
        )
        assert stream.tell() == len(data)

    def test_bytearray_chunks_accepted(self) -> None:
        class _BytearrayStream:
            def __init__(self) -> None:
                self._chunks = [bytearray(b"aa"), bytearray(b"bb"), b""]
                self._index = 0

            def read(self, size: int) -> bytes | bytearray:
                chunk = self._chunks[self._index]
                self._index += 1
                return chunk

        result = calculate_stream_checksum(
            _BytearrayStream(),  # type: ignore[arg-type]
            algorithm="sha256",
            chunk_size=2,
        )
        assert result == hashlib.sha256(b"aabb").hexdigest()

    def test_non_bytes_chunk_raises(self) -> None:
        class _BadStream:
            def read(self, size: int) -> str:
                return "not bytes"

        with pytest.raises(StorageIntegrityError) as exc_info:
            calculate_stream_checksum(
                _BadStream(),  # type: ignore[arg-type]
                algorithm="sha256",
                chunk_size=4,
            )
        assert exc_info.value.details["chunk_type"] == "str"

    def test_missing_read_raises(self) -> None:
        with pytest.raises(StorageIntegrityError):
            calculate_stream_checksum(
                object(),  # type: ignore[arg-type]
                algorithm="sha256",
                chunk_size=4,
            )

    def test_invalid_chunk_size_raises(self) -> None:
        stream = io.BytesIO(b"data")
        with pytest.raises(StorageIntegrityError):
            calculate_stream_checksum(stream, algorithm="sha256", chunk_size=0)

    def test_tell_failure_does_not_crash(self) -> None:
        data = b"abcdef"

        class _NoTellStream:
            def __init__(self) -> None:
                self._stream = io.BytesIO(data)

            def read(self, size: int) -> bytes:
                return self._stream.read(size)

            def tell(self) -> int:
                raise OSError("no tell")

            def seek(self, pos: int) -> int:
                return self._stream.seek(pos)

        result = calculate_stream_checksum(
            _NoTellStream(),  # type: ignore[arg-type]
            algorithm="sha256",
            chunk_size=2,
        )
        assert result == hashlib.sha256(data).hexdigest()

    def test_seek_failure_on_reset_is_swallowed(self) -> None:
        data = b"abcdef"

        class _BadSeekStream:
            def __init__(self) -> None:
                self._stream = io.BytesIO(data)

            def read(self, size: int) -> bytes:
                return self._stream.read(size)

            def tell(self) -> int:
                return 0

            def seek(self, pos: int) -> int:
                raise OSError("cannot seek")

        result = calculate_stream_checksum(
            _BadSeekStream(),  # type: ignore[arg-type]
            algorithm="sha256",
            chunk_size=2,
        )
        assert result == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# StorageIntegrityChecker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestVerifyObjectExists:
    async def test_object_present(self) -> None:
        checker, manager = _make_checker()
        manager.object_exists.return_value = True
        status = await checker.verify_object_exists(bucket=_BUCKET, object_key=_KEY)
        assert status.is_success is True

    async def test_object_absent(self) -> None:
        checker, manager = _make_checker()
        manager.object_exists.return_value = False
        status = await checker.verify_object_exists(bucket=_BUCKET, object_key=_KEY)
        assert status.is_success is False
        assert status.problem_type == StorageIntegrityProblemType.OBJECT_NOT_FOUND
        assert status.expected is True
        assert status.actual is False

    async def test_connection_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.object_exists.side_effect = StorageConnectionError("down")
        with pytest.raises(StorageIntegrityError) as exc_info:
            await checker.verify_object_exists(bucket=_BUCKET, object_key=_KEY)
        assert exc_info.value.details["operation"] == "verify_object_exists"

    async def test_storage_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.object_exists.side_effect = StorageError("boom")
        with pytest.raises(StorageIntegrityError) as exc_info:
            await checker.verify_object_exists(bucket=_BUCKET, object_key=_KEY)
        assert exc_info.value.details["error_type"] == "StorageError"


@pytest.mark.asyncio
class TestVerifyObjectSize:
    async def test_size_match(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(size=100)
        status = await checker.verify_object_size(
            bucket=_BUCKET, object_key=_KEY, expected_size_bytes=100
        )
        assert status.is_success is True
        assert status.actual == 100

    async def test_size_mismatch(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(size=50)
        status = await checker.verify_object_size(
            bucket=_BUCKET, object_key=_KEY, expected_size_bytes=100
        )
        assert status.is_success is False
        assert status.problem_type == StorageIntegrityProblemType.SIZE_MISMATCH
        assert status.expected == 100
        assert status.actual == 50

    async def test_uses_provided_object_info(self) -> None:
        checker, manager = _make_checker()
        info = _make_object_info(size=100)
        status = await checker.verify_object_size(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_size_bytes=100,
            object_info=info,
        )
        assert status.is_success is True
        manager.stat_object.assert_not_called()

    async def test_object_not_found(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageObjectNotFoundError(
            bucket=_BUCKET, object_key=_KEY
        )
        status = await checker.verify_object_size(
            bucket=_BUCKET, object_key=_KEY, expected_size_bytes=100
        )
        assert status.is_success is False
        assert status.problem_type == StorageIntegrityProblemType.OBJECT_NOT_FOUND
        assert status.actual is None

    async def test_negative_expected_size_raises(self) -> None:
        checker, _ = _make_checker()
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_size(
                bucket=_BUCKET, object_key=_KEY, expected_size_bytes=-1
            )

    async def test_bool_expected_size_raises(self) -> None:
        checker, _ = _make_checker()
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_size(
                bucket=_BUCKET, object_key=_KEY, expected_size_bytes=True  # type: ignore[arg-type]
            )

    async def test_connection_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageConnectionError("down")
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_size(
                bucket=_BUCKET, object_key=_KEY, expected_size_bytes=100
            )

    async def test_storage_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageError("boom")
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_size(
                bucket=_BUCKET, object_key=_KEY, expected_size_bytes=100
            )


@pytest.mark.asyncio
class TestVerifyObjectChecksum:
    async def test_checksum_match(self) -> None:
        checker, manager = _make_checker()
        data = b"file content"
        expected = hashlib.sha256(data).hexdigest()
        manager.calculate_object_checksum.return_value = expected
        status = await checker.verify_object_checksum(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_checksum=expected,
            expected_checksum_algorithm="sha256",
        )
        assert status.is_success is True
        assert status.actual == expected

    async def test_checksum_uppercase_expected_normalized(self) -> None:
        checker, manager = _make_checker()
        data = b"file content"
        actual = hashlib.sha256(data).hexdigest()
        manager.calculate_object_checksum.return_value = actual
        expected = actual.upper()
        status = await checker.verify_object_checksum(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_checksum=expected,
            expected_checksum_algorithm=StorageChecksumAlgorithm.SHA256,
        )
        assert status.is_success is True

    async def test_checksum_mismatch(self) -> None:
        checker, manager = _make_checker()
        manager.calculate_object_checksum.return_value = hashlib.sha256(
            b"actual"
        ).hexdigest()
        status = await checker.verify_object_checksum(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_checksum="deadbeef",
            expected_checksum_algorithm="sha256",
        )
        assert status.is_success is False
        assert status.problem_type == StorageIntegrityProblemType.CHECKSUM_MISMATCH
        assert status.expected == "deadbeef"

    async def test_object_not_found(self) -> None:
        checker, manager = _make_checker()
        manager.calculate_object_checksum.side_effect = StorageObjectNotFoundError(
            bucket=_BUCKET, object_key=_KEY
        )
        status = await checker.verify_object_checksum(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_checksum="abc123",
            expected_checksum_algorithm="sha256",
        )
        assert status.is_success is False
        assert status.problem_type == StorageIntegrityProblemType.OBJECT_NOT_FOUND
        assert status.actual is None

    async def test_empty_checksum_raises(self) -> None:
        checker, _ = _make_checker()
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_checksum(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_checksum="   ",
                expected_checksum_algorithm="sha256",
            )

    async def test_non_string_checksum_raises(self) -> None:
        checker, _ = _make_checker()
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_checksum(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_checksum=123,  # type: ignore[arg-type]
                expected_checksum_algorithm="sha256",
            )

    async def test_connection_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.calculate_object_checksum.side_effect = StorageConnectionError("down")
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_checksum(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_checksum="abc",
                expected_checksum_algorithm="sha256",
            )

    async def test_storage_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.calculate_object_checksum.side_effect = StorageError("boom")
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_checksum(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_checksum="abc",
                expected_checksum_algorithm="sha256",
            )


@pytest.mark.asyncio
class TestVerifyObjectMetadata:
    async def test_subset_match(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(
            metadata={"a": "1", "b": "2", "extra": "x"}
        )
        status = await checker.verify_object_metadata(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_metadata={"a": "1", "b": "2"},
        )
        assert status.is_success is True

    async def test_subset_mismatch(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(metadata={"a": "1"})
        status = await checker.verify_object_metadata(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_metadata={"a": "2"},
        )
        assert status.is_success is False
        assert status.problem_type == StorageIntegrityProblemType.METADATA_MISMATCH

    async def test_exact_match_success(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(metadata={"a": "1"})
        status = await checker.verify_object_metadata(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_metadata={"a": "1"},
            require_exact_match=True,
        )
        assert status.is_success is True

    async def test_exact_match_extra_fails(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(
            metadata={"a": "1", "extra": "x"}
        )
        status = await checker.verify_object_metadata(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_metadata={"a": "1"},
            require_exact_match=True,
        )
        assert status.is_success is False

    async def test_storage_metadata_object_accepted(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(metadata={"a": "1"})
        status = await checker.verify_object_metadata(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_metadata=StorageObjectMetadata(values={"a": "1"}),
        )
        assert status.is_success is True

    async def test_object_not_found(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageObjectNotFoundError(
            bucket=_BUCKET, object_key=_KEY
        )
        status = await checker.verify_object_metadata(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_metadata={"a": "1"},
        )
        assert status.is_success is False
        assert status.problem_type == StorageIntegrityProblemType.OBJECT_NOT_FOUND
        assert status.actual is None

    async def test_connection_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageConnectionError("down")
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_metadata(
                bucket=_BUCKET, object_key=_KEY, expected_metadata={"a": "1"}
            )

    async def test_storage_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageError("boom")
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_metadata(
                bucket=_BUCKET, object_key=_KEY, expected_metadata={"a": "1"}
            )


@pytest.mark.asyncio
class TestVerifyObjectStatus:
    async def test_status_match(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(
            status=StorageObjectStatus.AVAILABLE
        )
        status = await checker.verify_object_status(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_status=StorageObjectStatus.AVAILABLE,
        )
        assert status.is_success is True
        assert status.actual == StorageObjectStatus.AVAILABLE.value

    async def test_status_mismatch(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(
            status=StorageObjectStatus.CORRUPTED
        )
        status = await checker.verify_object_status(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_status=StorageObjectStatus.AVAILABLE,
        )
        assert status.is_success is False
        assert status.problem_type == StorageIntegrityProblemType.OBJECT_STATUS_MISMATCH

    async def test_not_found_expected_missing_succeeds(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageObjectNotFoundError(
            bucket=_BUCKET, object_key=_KEY
        )
        status = await checker.verify_object_status(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_status=StorageObjectStatus.MISSING,
        )
        assert status.is_success is True
        assert status.actual == StorageObjectStatus.MISSING.value

    async def test_not_found_expected_available_fails(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageObjectNotFoundError(
            bucket=_BUCKET, object_key=_KEY
        )
        status = await checker.verify_object_status(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_status=StorageObjectStatus.AVAILABLE,
        )
        assert status.is_success is False
        assert status.problem_type == StorageIntegrityProblemType.OBJECT_STATUS_MISMATCH

    async def test_invalid_expected_status_raises(self) -> None:
        checker, _ = _make_checker()
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_status(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_status="available",  # type: ignore[arg-type]
            )

    async def test_connection_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageConnectionError("down")
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_status(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_status=StorageObjectStatus.AVAILABLE,
            )

    async def test_storage_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageError("boom")
        with pytest.raises(StorageIntegrityError):
            await checker.verify_object_status(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_status=StorageObjectStatus.AVAILABLE,
            )


@pytest.mark.asyncio
class TestBuildIntegrityReport:
    async def test_full_success_report(self) -> None:
        checker, manager = _make_checker()
        data = b"file content"
        checksum = hashlib.sha256(data).hexdigest()
        manager.stat_object.return_value = _make_object_info(
            size=len(data),
            metadata={"a": "1"},
            status=StorageObjectStatus.AVAILABLE,
        )
        manager.calculate_object_checksum.return_value = checksum

        report = await checker.build_integrity_report(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_size_bytes=len(data),
            expected_checksum=checksum,
            expected_checksum_algorithm="sha256",
            expected_metadata={"a": "1"},
            expected_status=StorageObjectStatus.AVAILABLE,
        )
        assert report.object_exists is True
        assert report.is_success is True
        assert report.problems == []
        assert report.size_status is not None
        assert report.checksum_status is not None
        assert report.metadata_status is not None
        assert report.object_status is not None

    async def test_report_collects_problems(self) -> None:
        checker, manager = _make_checker()
        data = b"actual data"
        manager.stat_object.return_value = _make_object_info(
            size=5,
            metadata={"a": "wrong"},
            status=StorageObjectStatus.CORRUPTED,
        )
        manager.calculate_object_checksum.return_value = hashlib.sha256(
            data
        ).hexdigest()

        report = await checker.build_integrity_report(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_size_bytes=999,
            expected_checksum="deadbeef",
            expected_checksum_algorithm="sha256",
            expected_metadata={"a": "1"},
            expected_status=StorageObjectStatus.AVAILABLE,
        )
        assert report.is_success is False
        problem_types = {p.problem_type for p in report.problems}
        assert StorageIntegrityProblemType.SIZE_MISMATCH in problem_types
        assert StorageIntegrityProblemType.CHECKSUM_MISMATCH in problem_types
        assert StorageIntegrityProblemType.METADATA_MISMATCH in problem_types
        assert StorageIntegrityProblemType.OBJECT_STATUS_MISMATCH in problem_types

    async def test_report_object_not_found(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageObjectNotFoundError(
            bucket=_BUCKET, object_key=_KEY
        )
        report = await checker.build_integrity_report(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_size_bytes=100,
        )
        assert report.object_exists is False
        assert report.has_problems is True
        assert report.size_status is None
        assert report.problems[0].problem_type == (
            StorageIntegrityProblemType.OBJECT_NOT_FOUND
        )

    async def test_report_not_found_with_expected_status_missing(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageObjectNotFoundError(
            bucket=_BUCKET, object_key=_KEY
        )
        report = await checker.build_integrity_report(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_status=StorageObjectStatus.MISSING,
        )
        assert report.object_exists is False
        assert report.object_status is not None
        assert report.object_status.is_success is True

    async def test_report_no_expectations(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info()
        report = await checker.build_integrity_report(
            bucket=_BUCKET, object_key=_KEY
        )
        assert report.object_exists is True
        assert report.size_status is None
        assert report.checksum_status is None
        assert report.is_success is True

    async def test_report_checksum_without_algorithm_raises(self) -> None:
        checker, _ = _make_checker()
        with pytest.raises(StorageIntegrityError) as exc_info:
            await checker.build_integrity_report(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_checksum="abc",
            )
        assert exc_info.value.details["field"] == "expected_checksum_algorithm"

    async def test_report_algorithm_without_checksum_raises(self) -> None:
        checker, _ = _make_checker()
        with pytest.raises(StorageIntegrityError) as exc_info:
            await checker.build_integrity_report(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_checksum_algorithm="sha256",
            )
        assert exc_info.value.details["field"] == "expected_checksum"

    async def test_report_invalid_size_raises(self) -> None:
        checker, _ = _make_checker()
        with pytest.raises(StorageIntegrityError):
            await checker.build_integrity_report(
                bucket=_BUCKET,
                object_key=_KEY,
                expected_size_bytes=-10,
            )

    async def test_report_connection_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageConnectionError("down")
        with pytest.raises(StorageIntegrityError) as exc_info:
            await checker.build_integrity_report(bucket=_BUCKET, object_key=_KEY)
        assert exc_info.value.details["operation"] == "build_integrity_report"

    async def test_report_storage_error_raises_critical(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.side_effect = StorageError("boom")
        with pytest.raises(StorageIntegrityError):
            await checker.build_integrity_report(bucket=_BUCKET, object_key=_KEY)

    async def test_verify_object_alias(self) -> None:
        checker, manager = _make_checker()
        manager.stat_object.return_value = _make_object_info(size=12)
        report = await checker.verify_object(
            bucket=_BUCKET,
            object_key=_KEY,
            expected_size_bytes=12,
        )
        assert report.object_exists is True
        assert report.size_status is not None
        assert report.size_status.is_success is True


class TestValidateStaticHelpers:
    def test_validate_expected_size_non_int(self) -> None:
        with pytest.raises(StorageIntegrityError):
            StorageIntegrityChecker._validate_expected_size("100")  # type: ignore[arg-type]

    def test_validate_expected_size_negative(self) -> None:
        with pytest.raises(StorageIntegrityError):
            StorageIntegrityChecker._validate_expected_size(-1)

    def test_validate_expected_size_ok(self) -> None:
        assert StorageIntegrityChecker._validate_expected_size(0) is None

    def test_normalize_expected_checksum_ok(self) -> None:
        result = StorageIntegrityChecker._normalize_expected_checksum("  ABCdef  ")
        assert result == "abcdef"

    def test_validate_checksum_expectation_both_none(self) -> None:
        assert (
            StorageIntegrityChecker._validate_checksum_expectation(
                expected_checksum=None,
                expected_checksum_algorithm=None,
            )
            is None
        )

    def test_critical_integrity_error_details(self) -> None:
        exc = StorageError("orig", details={"foo": "bar"})
        result = StorageIntegrityChecker._critical_integrity_error(
            exc,
            bucket=_BUCKET,
            object_key=_KEY,
            operation="op",
            expected="exp",
        )
        assert isinstance(result, StorageIntegrityError)
        assert result.details["operation"] == "op"
        assert result.details["error_type"] == "StorageError"
        assert result.details["reason"] == "orig"
        assert result.details["foo"] == "bar"
