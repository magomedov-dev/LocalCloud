"""Модульные тесты схем папок."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas.folders import (
    BulkArchiveRequest,
    FolderArchiveRequest,
    FolderCreateRequest,
    FolderUpdateRequest,
    normalize_folder_color,
)


class TestNormalizeFolderColor:
    """Тесты нормализации цвета папки."""

    def test_none_returns_none(self):
        assert normalize_folder_color(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_folder_color("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_folder_color("   ") is None

    def test_strips_whitespace(self):
        assert normalize_folder_color("  blue  ") == "blue"

    def test_valid_hex_3(self):
        assert normalize_folder_color("#fff") == "#fff"

    def test_valid_hex_6(self):
        assert normalize_folder_color("#3b82f6") == "#3b82f6"

    def test_invalid_hex_raises(self):
        with pytest.raises(ValueError):
            normalize_folder_color("#gg1122")

    def test_invalid_hex_length_raises(self):
        with pytest.raises(ValueError):
            normalize_folder_color("#12345")  # 5 hex-символов - недопустимо

    def test_non_hex_label_allowed(self):
        assert normalize_folder_color("blue") == "blue"

    def test_too_long_raises(self):
        with pytest.raises(ValueError):
            normalize_folder_color("a" * 33)


class TestFolderCreateRequest:
    """Тесты запроса создания папки."""

    def test_valid_minimal(self):
        r = FolderCreateRequest(name="Documents")
        assert r.name == "Documents"
        assert r.parent_id is None
        assert r.description is None
        assert r.color is None

    def test_name_required(self):
        with pytest.raises(ValidationError):
            FolderCreateRequest()

    def test_name_strips_whitespace(self):
        r = FolderCreateRequest(name="  Docs  ")
        assert r.name == "Docs"

    def test_name_with_slash_raises(self):
        with pytest.raises(ValidationError):
            FolderCreateRequest(name="bad/name")

    def test_name_dot_raises(self):
        with pytest.raises(ValidationError):
            FolderCreateRequest(name=".")

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            FolderCreateRequest(name="a" * 256)

    def test_parent_id_optional(self):
        pid = uuid4()
        r = FolderCreateRequest(name="Sub", parent_id=pid)
        assert r.parent_id == pid

    def test_description_normalization(self):
        r = FolderCreateRequest(name="Docs", description="  my docs  ")
        assert r.description == "my docs"

    def test_whitespace_description_becomes_none(self):
        r = FolderCreateRequest(name="Docs", description="   ")
        assert r.description is None

    def test_valid_hex_color(self):
        r = FolderCreateRequest(name="Docs", color="#3b82f6")
        assert r.color == "#3b82f6"

    def test_invalid_hex_color_raises(self):
        with pytest.raises(ValidationError):
            FolderCreateRequest(name="Docs", color="#gggggg")

    def test_non_hex_color_allowed(self):
        r = FolderCreateRequest(name="Docs", color="blue")
        assert r.color == "blue"


class TestFolderUpdateRequest:
    """Тесты запроса обновления папки."""

    def test_all_optional(self):
        r = FolderUpdateRequest()
        assert r.description is None
        assert r.color is None

    def test_valid_description(self):
        r = FolderUpdateRequest(description="new desc")
        assert r.description == "new desc"

    def test_description_whitespace_becomes_none(self):
        r = FolderUpdateRequest(description="   ")
        assert r.description is None

    def test_valid_hex_color(self):
        r = FolderUpdateRequest(color="#22c55e")
        assert r.color == "#22c55e"

    def test_invalid_hex_color_raises(self):
        with pytest.raises(ValidationError):
            FolderUpdateRequest(color="#xyz")

    def test_description_too_long_raises(self):
        with pytest.raises(ValidationError):
            FolderUpdateRequest(description="a" * 2001)

    def test_explicit_none_description_returns_none(self):
        # Проверяет ветку `value is None -> return None` валидатора описания
        # (отличную от ветки «пробелы -> None»).
        r = FolderUpdateRequest(description=None)
        assert r.description is None


class TestFolderArchiveRequest:
    """Тесты запроса архивации папки."""

    def test_valid_minimal(self):
        r = FolderArchiveRequest(folder_id=uuid4())
        assert r.include_deleted is False
        assert r.archive_name is None
        assert r.password is None

    def test_folder_id_required(self):
        with pytest.raises(ValidationError):
            FolderArchiveRequest()

    def test_archive_name_strips_zip_extension(self):
        r = FolderArchiveRequest(folder_id=uuid4(), archive_name="documents.zip")
        assert r.archive_name == "documents"

    def test_archive_name_strips_zip_case_insensitive(self):
        r = FolderArchiveRequest(folder_id=uuid4(), archive_name="DOCS.ZIP")
        assert r.archive_name == "DOCS"

    def test_archive_name_without_zip_kept(self):
        r = FolderArchiveRequest(folder_id=uuid4(), archive_name="documents")
        assert r.archive_name == "documents"

    def test_archive_name_only_zip_raises(self):
        with pytest.raises(ValidationError):
            FolderArchiveRequest(folder_id=uuid4(), archive_name=".zip")

    def test_archive_name_invalid_chars_raises(self):
        with pytest.raises(ValidationError):
            FolderArchiveRequest(folder_id=uuid4(), archive_name="bad/name")


class TestBulkArchiveRequest:
    """Тесты запроса массовой архивации узлов."""

    def test_valid(self):
        r = BulkArchiveRequest(node_ids=[uuid4(), uuid4()])
        assert len(r.node_ids) == 2

    def test_empty_node_ids_raises(self):
        with pytest.raises(ValidationError):
            BulkArchiveRequest(node_ids=[])

    def test_missing_node_ids_raises(self):
        with pytest.raises(ValidationError):
            BulkArchiveRequest()

    def test_too_many_node_ids_raises(self):
        with pytest.raises(ValidationError):
            BulkArchiveRequest(node_ids=[uuid4() for _ in range(201)])

    def test_archive_name_optional(self):
        r = BulkArchiveRequest(node_ids=[uuid4()])
        assert r.archive_name is None
