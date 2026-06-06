"""Модульные тесты схем узлов файловой системы."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import NodeType, NodeVisibility
from schemas.nodes import (
    NodeBase,
    NodeCreate,
    NodeMoveRequest,
    NodeQueryParams,
    NodeRenameRequest,
    NodeSearchQuery,
    NodeUpdate,
    ThumbnailBatchRequest,
    validate_node_name,
)


class TestValidateNodeName:
    """Тесты валидации имени узла."""

    def test_valid_name(self):
        assert validate_node_name("document.pdf") == "document.pdf"

    def test_strips_whitespace(self):
        assert validate_node_name("  hello  ") == "hello"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="пустым"):
            validate_node_name("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="пустым"):
            validate_node_name("   ")

    def test_slash_raises(self):
        with pytest.raises(ValueError, match="не должно содержать"):
            validate_node_name("path/file")

    def test_backslash_raises(self):
        with pytest.raises(ValueError, match="не должно содержать"):
            validate_node_name("path\\file")

    def test_nul_char_raises(self):
        with pytest.raises(ValueError, match="не должно содержать"):
            validate_node_name("file\x00name")

    def test_dot_raises(self):
        with pytest.raises(ValueError, match="'\\.'"):
            validate_node_name(".")

    def test_dotdot_raises(self):
        with pytest.raises(ValueError, match="'\\.\\.'"):
            validate_node_name("..")

    def test_unicode_name_valid(self):
        assert validate_node_name("Документы") == "Документы"


class TestNodeBase:
    """Тесты базовой схемы узла."""

    def test_valid_minimal(self):
        n = NodeBase(name="documents", node_type=NodeType.FOLDER)
        assert n.name == "documents"
        assert n.visibility == NodeVisibility.PRIVATE
        assert n.parent_id is None

    def test_name_required(self):
        with pytest.raises(ValidationError):
            NodeBase(node_type=NodeType.FILE)

    def test_name_with_slash_raises(self):
        with pytest.raises(ValidationError):
            NodeBase(name="bad/name", node_type=NodeType.FILE)

    def test_name_dot_raises(self):
        with pytest.raises(ValidationError):
            NodeBase(name=".", node_type=NodeType.FILE)

    def test_parent_id_optional(self):
        pid = uuid4()
        n = NodeBase(name="file.txt", node_type=NodeType.FILE, parent_id=pid)
        assert n.parent_id == pid

    def test_visibility_default_private(self):
        n = NodeBase(name="file.txt", node_type=NodeType.FILE)
        assert n.visibility == NodeVisibility.PRIVATE


class TestNodeCreate:
    """Тесты схемы создания узла."""

    def test_valid(self):
        n = NodeCreate(name="folder1", node_type=NodeType.FOLDER)
        assert n.node_type == NodeType.FOLDER

    def test_node_type_required(self):
        with pytest.raises(ValidationError):
            NodeCreate(name="folder1")

    def test_invalid_node_type_raises(self):
        with pytest.raises(ValidationError):
            NodeCreate(name="f", node_type="invalid")


class TestNodeUpdate:
    """Тесты схемы обновления узла."""

    def test_all_optional(self):
        u = NodeUpdate()
        assert u.name is None
        assert u.parent_id is None
        assert u.visibility is None

    def test_valid_name(self):
        u = NodeUpdate(name="new name")
        assert u.name == "new name"

    def test_name_with_slash_raises(self):
        with pytest.raises(ValidationError):
            NodeUpdate(name="bad/name")

    def test_name_none_allowed(self):
        u = NodeUpdate(name=None)
        assert u.name is None


class TestNodeRenameRequest:
    """Тесты запроса переименования узла."""

    def test_valid(self):
        r = NodeRenameRequest(name="new_name.pdf")
        assert r.name == "new_name.pdf"

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            NodeRenameRequest()

    def test_name_with_slash_raises(self):
        with pytest.raises(ValidationError):
            NodeRenameRequest(name="bad/name")

    def test_name_dot_dot_raises(self):
        with pytest.raises(ValidationError):
            NodeRenameRequest(name="..")

    def test_name_strips_whitespace(self):
        r = NodeRenameRequest(name="  hello.txt  ")
        assert r.name == "hello.txt"


class TestNodeMoveRequest:
    """Тесты запроса перемещения узла."""

    def test_default_target_is_none(self):
        r = NodeMoveRequest()
        assert r.target_parent_id is None

    def test_with_target_parent(self):
        pid = uuid4()
        r = NodeMoveRequest(target_parent_id=pid)
        assert r.target_parent_id == pid


class TestNodeSearchQuery:
    """Тесты параметров поиска узлов."""

    def test_valid(self):
        q = NodeSearchQuery(query="document")
        assert q.query == "document"

    def test_query_required(self):
        with pytest.raises(ValidationError):
            NodeSearchQuery()

    def test_query_strips_whitespace(self):
        q = NodeSearchQuery(query="  doc  ")
        assert q.query == "doc"

    def test_whitespace_query_raises(self):
        with pytest.raises(ValidationError):
            NodeSearchQuery(query="   ")

    def test_query_min_length_1(self):
        with pytest.raises(ValidationError):
            NodeSearchQuery(query="")

    def test_defaults(self):
        q = NodeSearchQuery(query="test")
        assert q.sort_by == "name"
        assert q.sort_desc is False
        assert q.include_deleted is False


class TestNodeQueryParams:
    """Тесты параметров запроса списка узлов."""

    def test_defaults(self):
        q = NodeQueryParams()
        assert q.is_deleted is False
        assert q.sort_by == "name"
        assert q.sort_desc is False

    def test_created_to_before_created_from_raises(self):
        d1 = datetime(2024, 1, 10, tzinfo=timezone.utc)
        d2 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            NodeQueryParams(created_from=d1, created_to=d2)

    def test_updated_to_before_updated_from_raises(self):
        d1 = datetime(2024, 1, 10, tzinfo=timezone.utc)
        d2 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            NodeQueryParams(updated_from=d1, updated_to=d2)


class TestThumbnailBatchRequest:
    """Тесты запроса пакетной генерации миниатюр."""

    def test_valid(self):
        ids = [uuid4()]
        r = ThumbnailBatchRequest(node_ids=ids)
        assert r.node_ids == ids

    def test_empty_list_raises(self):
        with pytest.raises(ValidationError):
            ThumbnailBatchRequest(node_ids=[])

    def test_too_many_ids_raises(self):
        with pytest.raises(ValidationError):
            ThumbnailBatchRequest(node_ids=[uuid4() for _ in range(101)])

    def test_missing_node_ids_raises(self):
        with pytest.raises(ValidationError):
            ThumbnailBatchRequest()


class TestNodeQueryParamsValidRanges:
    """Тесты корректных диапазонов дат в параметрах запроса узлов."""

    def test_valid_date_ranges_returned(self):
        d_from = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d_to = datetime(2024, 1, 10, tzinfo=timezone.utc)
        q = NodeQueryParams(
            created_from=d_from,
            created_to=d_to,
            updated_from=d_from,
            updated_to=d_to,
        )
        assert q.created_to == d_to
        assert q.updated_to == d_to
