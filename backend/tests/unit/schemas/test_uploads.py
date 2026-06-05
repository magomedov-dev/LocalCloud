"""Модульные тесты схем загрузки файлов."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import UploadPartStatus, UploadSessionStatus
from schemas.uploads import (
    UploadAbortRequest,
    UploadCompleteRequest,
    UploadCompleteResponse,
    UploadPartCompleteRequest,
    UploadPartPresignedUrlRead,
    UploadPartRead,
    UploadPresignedUrlsResponse,
    UploadProgressRead,
    UploadQueryParams,
    UploadSessionCreateRequest,
    UploadSessionListItem,
    UploadSessionRead,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestUploadSessionCreateRequest:
    """Тесты запроса создания сессии загрузки."""

    def test_valid_minimal(self):
        r = UploadSessionCreateRequest(
            parent_node_id=uuid4(),
            filename="document.pdf",
            file_size_bytes=1024,
            parts_count=2,
        )
        assert r.filename == "document.pdf"
        assert r.part_size_bytes is None
        assert r.mime_type is None
        assert r.checksum is None
        assert r.checksum_algorithm is None

    def test_filename_validated_and_stripped(self):
        r = UploadSessionCreateRequest(
            parent_node_id=uuid4(),
            filename="  report.txt  ",
            file_size_bytes=10,
            parts_count=1,
        )
        assert r.filename == "report.txt"

    def test_filename_with_slash_raises(self):
        with pytest.raises(ValidationError):
            UploadSessionCreateRequest(
                parent_node_id=uuid4(),
                filename="a/b.txt",
                file_size_bytes=10,
                parts_count=1,
            )

    def test_filename_too_long_raises(self):
        with pytest.raises(ValidationError):
            UploadSessionCreateRequest(
                parent_node_id=uuid4(),
                filename="a" * 256,
                file_size_bytes=10,
                parts_count=1,
            )

    def test_zero_file_size_raises(self):
        with pytest.raises(ValidationError):
            UploadSessionCreateRequest(
                parent_node_id=uuid4(),
                filename="a.txt",
                file_size_bytes=0,
                parts_count=1,
            )

    def test_zero_parts_count_raises(self):
        with pytest.raises(ValidationError):
            UploadSessionCreateRequest(
                parent_node_id=uuid4(),
                filename="a.txt",
                file_size_bytes=10,
                parts_count=0,
            )

    def test_zero_part_size_raises(self):
        with pytest.raises(ValidationError):
            UploadSessionCreateRequest(
                parent_node_id=uuid4(),
                filename="a.txt",
                file_size_bytes=10,
                parts_count=1,
                part_size_bytes=0,
            )

    def test_optional_text_normalization(self):
        r = UploadSessionCreateRequest(
            parent_node_id=uuid4(),
            filename="a.txt",
            file_size_bytes=10,
            parts_count=1,
            mime_type="  application/pdf  ",
            checksum="  abc  ",
        )
        assert r.mime_type == "application/pdf"
        assert r.checksum == "abc"

    def test_optional_text_blank_becomes_none(self):
        r = UploadSessionCreateRequest(
            parent_node_id=uuid4(),
            filename="a.txt",
            file_size_bytes=10,
            parts_count=1,
            mime_type="   ",
            checksum="   ",
        )
        assert r.mime_type is None
        assert r.checksum is None

    def test_checksum_algorithm_lowercased(self):
        r = UploadSessionCreateRequest(
            parent_node_id=uuid4(),
            filename="a.txt",
            file_size_bytes=10,
            parts_count=1,
            checksum_algorithm="  SHA256  ",
        )
        assert r.checksum_algorithm == "sha256"

    def test_checksum_algorithm_blank_becomes_none(self):
        r = UploadSessionCreateRequest(
            parent_node_id=uuid4(),
            filename="a.txt",
            file_size_bytes=10,
            parts_count=1,
            checksum_algorithm="   ",
        )
        assert r.checksum_algorithm is None

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            UploadSessionCreateRequest(filename="a.txt", file_size_bytes=1, parts_count=1)


def _session_kwargs(**overrides):
    base = dict(
        id=uuid4(),
        user_id=uuid4(),
        parent_node_id=uuid4(),
        file_name="file.bin",
        file_size_bytes=1000,
        part_size_bytes=500,
        status=UploadSessionStatus.UPLOADING,
        parts_count=2,
        uploaded_parts_count=1,
        uploaded_bytes=500,
        expires_at=NOW,
        created_at=NOW,
    )
    base.update(overrides)
    return base


class TestUploadSessionRead:
    """Тесты схемы чтения сессии загрузки."""

    def test_valid_and_computed_progress(self):
        r = UploadSessionRead(**_session_kwargs())
        assert r.progress_percent == 50.0
        assert r.is_completed is False
        assert r.is_terminal is False

    def test_progress_capped_at_100(self):
        r = UploadSessionRead(**_session_kwargs(uploaded_bytes=2000, file_size_bytes=1000))
        assert r.progress_percent == 100.0

    def test_is_completed_true(self):
        r = UploadSessionRead(**_session_kwargs(status=UploadSessionStatus.COMPLETED))
        assert r.is_completed is True
        assert r.is_terminal is True

    @pytest.mark.parametrize(
        "status",
        [
            UploadSessionStatus.FAILED,
            UploadSessionStatus.ABORTED,
            UploadSessionStatus.EXPIRED,
        ],
    )
    def test_terminal_statuses(self, status):
        r = UploadSessionRead(**_session_kwargs(status=status))
        assert r.is_terminal is True
        assert r.is_completed is False

    def test_from_attributes(self):
        class Obj:
            pass

        obj = Obj()
        for k, v in _session_kwargs().items():
            setattr(obj, k, v)
        r = UploadSessionRead.model_validate(obj)
        assert r.file_name == "file.bin"

    def test_negative_uploaded_bytes_raises(self):
        with pytest.raises(ValidationError):
            UploadSessionRead(**_session_kwargs(uploaded_bytes=-1))

    def test_serialization_includes_computed(self):
        r = UploadSessionRead(**_session_kwargs())
        dumped = r.model_dump()
        assert "progress_percent" in dumped
        assert dumped["progress_percent"] == 50.0


class TestUploadSessionListItem:
    """Тесты элемента списка сессий загрузки."""

    def test_valid_and_progress(self):
        r = UploadSessionListItem(
            id=uuid4(),
            user_id=uuid4(),
            parent_node_id=uuid4(),
            file_name="f",
            file_size_bytes=200,
            status=UploadSessionStatus.UPLOADING,
            parts_count=2,
            uploaded_parts_count=1,
            uploaded_bytes=50,
            expires_at=NOW,
            created_at=NOW,
        )
        assert r.progress_percent == 25.0


class TestUploadPartRead:
    """Тесты схемы чтения части загрузки."""

    def test_valid(self):
        r = UploadPartRead(
            id=uuid4(),
            upload_session_id=uuid4(),
            part_number=1,
            size_bytes=100,
            status=UploadPartStatus.UPLOADED,
            created_at=NOW,
        )
        assert r.etag is None
        assert r.status == UploadPartStatus.UPLOADED

    def test_part_number_must_be_ge_1(self):
        with pytest.raises(ValidationError):
            UploadPartRead(
                id=uuid4(),
                upload_session_id=uuid4(),
                part_number=0,
                size_bytes=100,
                status=UploadPartStatus.PENDING,
                created_at=NOW,
            )

    def test_etag_too_long_raises(self):
        with pytest.raises(ValidationError):
            UploadPartRead(
                id=uuid4(),
                upload_session_id=uuid4(),
                part_number=1,
                size_bytes=100,
                etag="x" * 513,
                status=UploadPartStatus.UPLOADED,
                created_at=NOW,
            )


class TestUploadPartPresignedUrlRead:
    """Тесты схемы предподписанного URL для части загрузки."""

    def test_valid_defaults(self):
        r = UploadPartPresignedUrlRead(part_number=1, url="http://x", expires_at=NOW)
        assert r.method == "PUT"
        assert r.headers == {}
        assert r.size_bytes is None

    def test_method_normalized_upper(self):
        r = UploadPartPresignedUrlRead(
            part_number=1, url="http://x", expires_at=NOW, method="  post  "
        )
        assert r.method == "POST"

    def test_method_blank_raises(self):
        with pytest.raises(ValidationError):
            UploadPartPresignedUrlRead(
                part_number=1, url="http://x", expires_at=NOW, method="   "
            )

    def test_size_bytes_zero_raises(self):
        with pytest.raises(ValidationError):
            UploadPartPresignedUrlRead(
                part_number=1, url="http://x", expires_at=NOW, size_bytes=0
            )


class TestUploadPresignedUrlsResponse:
    """Тесты ответа с предподписанными URL для загрузки."""

    def test_valid_defaults(self):
        r = UploadPresignedUrlsResponse(
            upload_session_id=uuid4(), status=UploadSessionStatus.CREATED
        )
        assert r.parts == []
        assert r.expires_at is None

    def test_with_parts(self):
        part = UploadPartPresignedUrlRead(part_number=1, url="http://x", expires_at=NOW)
        r = UploadPresignedUrlsResponse(
            upload_session_id=uuid4(),
            status=UploadSessionStatus.UPLOADING,
            parts=[part],
        )
        assert len(r.parts) == 1
        assert r.parts[0].part_number == 1


class TestUploadPartCompleteRequest:
    """Тесты запроса завершения части загрузки."""

    def test_valid(self):
        r = UploadPartCompleteRequest(part_number=1, etag='"abc"', size_bytes=10)
        assert r.etag == "abc"

    def test_etag_stripped_quotes_and_spaces(self):
        r = UploadPartCompleteRequest(part_number=1, etag='  "tag"  ', size_bytes=10)
        assert r.etag == "tag"

    def test_etag_blank_raises(self):
        with pytest.raises(ValidationError):
            UploadPartCompleteRequest(part_number=1, etag='  ""  ', size_bytes=10)

    def test_checksum_normalized(self):
        r = UploadPartCompleteRequest(
            part_number=1, etag="t", size_bytes=10, checksum="  cs  "
        )
        assert r.checksum == "cs"

    def test_checksum_blank_becomes_none(self):
        r = UploadPartCompleteRequest(
            part_number=1, etag="t", size_bytes=10, checksum="   "
        )
        assert r.checksum is None

    def test_part_number_ge_1(self):
        with pytest.raises(ValidationError):
            UploadPartCompleteRequest(part_number=0, etag="t", size_bytes=10)

    def test_size_zero_raises(self):
        with pytest.raises(ValidationError):
            UploadPartCompleteRequest(part_number=1, etag="t", size_bytes=0)

    def test_etag_too_long_raises(self):
        with pytest.raises(ValidationError):
            UploadPartCompleteRequest(part_number=1, etag="x" * 513, size_bytes=10)


class TestUploadCompleteRequest:
    """Тесты запроса завершения загрузки."""

    def test_valid(self):
        r = UploadCompleteRequest(
            upload_session_id=uuid4(),
            parts=[UploadPartCompleteRequest(part_number=1, etag="t", size_bytes=10)],
        )
        assert len(r.parts) == 1

    def test_empty_parts_raises(self):
        with pytest.raises(ValidationError):
            UploadCompleteRequest(upload_session_id=uuid4(), parts=[])

    def test_duplicate_part_numbers_raises(self):
        with pytest.raises(ValidationError):
            UploadCompleteRequest(
                upload_session_id=uuid4(),
                parts=[
                    UploadPartCompleteRequest(part_number=1, etag="a", size_bytes=10),
                    UploadPartCompleteRequest(part_number=1, etag="b", size_bytes=10),
                ],
            )

    def test_checksum_normalized(self):
        r = UploadCompleteRequest(
            upload_session_id=uuid4(),
            parts=[UploadPartCompleteRequest(part_number=1, etag="t", size_bytes=10)],
            checksum="  cs  ",
        )
        assert r.checksum == "cs"

    def test_checksum_blank_becomes_none(self):
        r = UploadCompleteRequest(
            upload_session_id=uuid4(),
            parts=[UploadPartCompleteRequest(part_number=1, etag="t", size_bytes=10)],
            checksum="   ",
        )
        assert r.checksum is None


class TestUploadCompleteResponse:
    """Тесты ответа на завершение загрузки."""

    def test_valid_defaults(self):
        session = UploadSessionRead(**_session_kwargs())
        r = UploadCompleteResponse(upload_session=session)
        assert r.file_id is None
        assert r.node_id is None
        assert r.message == "Файл успешно загружен."


class TestUploadAbortRequest:
    """Тесты запроса прерывания загрузки."""

    def test_valid_minimal(self):
        r = UploadAbortRequest(upload_session_id=uuid4())
        assert r.reason is None

    def test_reason_normalized(self):
        r = UploadAbortRequest(upload_session_id=uuid4(), reason="  bad  ")
        assert r.reason == "bad"

    def test_reason_blank_becomes_none(self):
        r = UploadAbortRequest(upload_session_id=uuid4(), reason="   ")
        assert r.reason is None

    def test_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            UploadAbortRequest(upload_session_id=uuid4(), reason="a" * 513)


class TestUploadProgressRead:
    """Тесты схемы чтения прогресса загрузки."""

    def test_valid_progress(self):
        r = UploadProgressRead(
            upload_session_id=uuid4(),
            status=UploadSessionStatus.UPLOADING,
            file_size_bytes=1000,
            parts_count=2,
            uploaded_parts_count=1,
            uploaded_bytes=250,
        )
        assert r.progress_percent == 25.0

    def test_uploaded_parts_exceeds_total_raises(self):
        with pytest.raises(ValidationError):
            UploadProgressRead(
                upload_session_id=uuid4(),
                status=UploadSessionStatus.UPLOADING,
                file_size_bytes=1000,
                parts_count=2,
                uploaded_parts_count=3,
                uploaded_bytes=10,
            )

    def test_uploaded_bytes_exceeds_size_raises(self):
        with pytest.raises(ValidationError):
            UploadProgressRead(
                upload_session_id=uuid4(),
                status=UploadSessionStatus.UPLOADING,
                file_size_bytes=1000,
                parts_count=2,
                uploaded_parts_count=1,
                uploaded_bytes=2000,
            )

    def test_uploaded_parts_equal_total_ok(self):
        r = UploadProgressRead(
            upload_session_id=uuid4(),
            status=UploadSessionStatus.COMPLETED,
            file_size_bytes=1000,
            parts_count=2,
            uploaded_parts_count=2,
            uploaded_bytes=1000,
        )
        assert r.progress_percent == 100.0


class TestUploadQueryParams:
    """Тесты параметров запроса списка сессий загрузки."""

    def test_defaults(self):
        p = UploadQueryParams()
        assert p.limit == 50
        assert p.offset == 0
        assert p.include_terminal is True
        assert p.sort_by == "created_at"
        assert p.sort_desc is True
        assert p.status is None

    def test_filename_normalized(self):
        p = UploadQueryParams(filename="  doc  ")
        assert p.filename == "doc"

    def test_filename_blank_raises(self):
        # str_strip_whitespace обрезает до "", что нарушает min_length=1.
        with pytest.raises(ValidationError):
            UploadQueryParams(filename="   ")

    def test_created_range_invalid_raises(self):
        with pytest.raises(ValidationError):
            UploadQueryParams(
                created_from=NOW + timedelta(days=1),
                created_to=NOW,
            )

    def test_created_range_valid(self):
        p = UploadQueryParams(created_from=NOW, created_to=NOW + timedelta(days=1))
        assert p.created_to > p.created_from

    def test_status_enum_coercion(self):
        p = UploadQueryParams(status="completed")
        assert p.status == UploadSessionStatus.COMPLETED

    def test_sort_by_too_long_raises(self):
        with pytest.raises(ValidationError):
            UploadQueryParams(sort_by="a" * 65)

    def test_limit_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            UploadQueryParams(limit=0)
