"""Модульные тесты схем файлов."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import (
    FilePreviewStatus,
    FileProcessingStatus,
    StorageObjectStatus,
)
from schemas.files import (
    FileDownloadRequest,
    FileDownloadResponse,
    FileRenameRequest,
    FileSearchQuery,
    FileUpdateRequest,
)


class TestFileRenameRequest:
    """Тесты запроса переименования файла."""

    def test_valid(self):
        r = FileRenameRequest(name="document.pdf")
        assert r.name == "document.pdf"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            FileRenameRequest()

    def test_name_with_slash_raises(self):
        with pytest.raises(ValidationError):
            FileRenameRequest(name="bad/name.txt")

    def test_name_dot_raises(self):
        with pytest.raises(ValidationError):
            FileRenameRequest(name=".")

    def test_name_strips_whitespace(self):
        r = FileRenameRequest(name="  doc.pdf  ")
        assert r.name == "doc.pdf"

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            FileRenameRequest(name="a" * 256)


class TestFileUpdateRequest:
    """Тесты запроса обновления метаданных файла."""

    def test_all_optional(self):
        r = FileUpdateRequest()
        assert r.mime_type is None
        assert r.extension is None
        assert r.checksum is None
        assert r.checksum_algorithm is None

    def test_mime_type_normalization(self):
        r = FileUpdateRequest(mime_type="  application/pdf  ")
        assert r.mime_type == "application/pdf"

    def test_whitespace_only_mime_type_becomes_none(self):
        r = FileUpdateRequest(mime_type="   ")
        assert r.mime_type is None

    def test_extension_strips_leading_dot(self):
        r = FileUpdateRequest(extension=".pdf")
        assert r.extension == "pdf"

    def test_extension_lowercased(self):
        r = FileUpdateRequest(extension="PDF")
        assert r.extension == "pdf"

    def test_extension_whitespace_becomes_none(self):
        r = FileUpdateRequest(extension="   ")
        assert r.extension is None

    def test_checksum_algorithm_lowercased(self):
        r = FileUpdateRequest(checksum_algorithm="SHA256")
        assert r.checksum_algorithm == "sha256"

    def test_checksum_algorithm_whitespace_becomes_none(self):
        r = FileUpdateRequest(checksum_algorithm="   ")
        assert r.checksum_algorithm is None

    def test_mime_type_too_long_raises(self):
        with pytest.raises(ValidationError):
            FileUpdateRequest(mime_type="a" * 256)


class TestFileDownloadRequest:
    """Тесты запроса скачивания файла."""

    def test_valid_minimal(self):
        r = FileDownloadRequest(file_id=uuid4())
        assert r.force_download is True
        assert r.filename is None

    def test_file_id_required(self):
        with pytest.raises(ValidationError):
            FileDownloadRequest()

    def test_valid_with_filename(self):
        r = FileDownloadRequest(file_id=uuid4(), filename="document.pdf")
        assert r.filename == "document.pdf"

    def test_filename_with_slash_raises(self):
        with pytest.raises(ValidationError):
            FileDownloadRequest(file_id=uuid4(), filename="bad/file.pdf")


class TestFileDownloadResponse:
    """Тесты ответа на запрос скачивания файла."""

    def _make(self, **kwargs):
        now = datetime.now(timezone.utc)
        defaults = {
            "presigned_url": "https://example.com/file",
            "expires_at": now,
        }
        defaults.update(kwargs)
        return FileDownloadResponse(**defaults)

    def test_valid_minimal(self):
        r = self._make()
        assert r.method == "GET"
        assert r.headers == {}

    def test_method_uppercased(self):
        r = self._make(method="get")
        assert r.method == "GET"

    def test_method_stripped(self):
        r = self._make(method="  GET  ")
        assert r.method == "GET"

    def test_empty_method_raises(self):
        with pytest.raises(ValidationError):
            self._make(method="")

    def test_whitespace_method_raises(self):
        with pytest.raises(ValidationError):
            self._make(method="   ")

    def test_presigned_url_required(self):
        with pytest.raises(ValidationError):
            FileDownloadResponse(expires_at=datetime.now(timezone.utc))

    def test_optional_fields_default(self):
        r = self._make()
        assert r.file_id is None
        assert r.filename is None
        assert r.size_bytes is None
        assert r.mime_type is None


class TestFileSearchQuery:
    """Тесты параметров поиска файлов."""

    def test_defaults(self):
        q = FileSearchQuery()
        assert q.query is None
        assert q.sort_by == "created_at"
        assert q.sort_desc is True
        assert q.include_deleted is False

    def test_query_normalization(self):
        q = FileSearchQuery(query="  report  ")
        assert q.query == "report"

    def test_whitespace_query_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            FileSearchQuery(query="   ")

    def test_mime_type_lowercased(self):
        q = FileSearchQuery(mime_type="APPLICATION/PDF")
        assert q.mime_type == "application/pdf"

    def test_extension_strips_dot(self):
        q = FileSearchQuery(extension=".PDF")
        assert q.extension == "pdf"

    def test_max_size_less_than_min_size_raises(self):
        with pytest.raises(ValidationError):
            FileSearchQuery(min_size_bytes=1000, max_size_bytes=500)

    def test_created_to_before_from_raises(self):
        d1 = datetime(2024, 1, 10, tzinfo=timezone.utc)
        d2 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            FileSearchQuery(created_from=d1, created_to=d2)

    def test_updated_to_before_from_raises(self):
        d1 = datetime(2024, 1, 10, tzinfo=timezone.utc)
        d2 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            FileSearchQuery(updated_from=d1, updated_to=d2)

    def test_negative_min_size_raises(self):
        with pytest.raises(ValidationError):
            FileSearchQuery(min_size_bytes=-1)

    def test_explicit_none_fields_stay_none(self):
        q = FileSearchQuery(
            query=None,
            mime_type=None,
            extension=None,
            max_size_bytes=None,
            created_to=None,
            updated_to=None,
        )
        assert q.query is None
        assert q.mime_type is None
        assert q.extension is None
        assert q.max_size_bytes is None
        assert q.created_to is None
        assert q.updated_to is None

    def test_valid_ranges_returned(self):
        d_from = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d_to = datetime(2024, 1, 10, tzinfo=timezone.utc)
        q = FileSearchQuery(
            min_size_bytes=100,
            max_size_bytes=200,
            created_from=d_from,
            created_to=d_to,
            updated_from=d_from,
            updated_to=d_to,
        )
        assert q.max_size_bytes == 200
        assert q.created_to == d_to
        assert q.updated_to == d_to


class TestFileUpdateRequestNone:
    """Тесты явной передачи None в запросе обновления файла."""

    def test_explicit_none_optional_text(self):
        r = FileUpdateRequest(
            mime_type=None,
            extension=None,
            checksum=None,
            checksum_algorithm=None,
        )
        assert r.mime_type is None
        assert r.extension is None
        assert r.checksum is None
        assert r.checksum_algorithm is None


class TestFileDownloadRequestNone:
    """Тесты явной передачи None в запросе скачивания файла."""

    def test_explicit_none_filename(self):
        r = FileDownloadRequest(file_id=uuid4(), filename=None)
        assert r.filename is None
