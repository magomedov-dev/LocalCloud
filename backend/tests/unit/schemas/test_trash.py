"""Модульные тесты схем корзины."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import NodeType, NodeVisibility, TrashItemStatus
from schemas.nodes import NodeListItem
from schemas.trash import (
    TrashCleanupRequest,
    TrashEmptyRequest,
    TrashItemListItem,
    TrashItemRead,
    TrashPurgeRequest,
    TrashPurgeResponse,
    TrashQueryParams,
    TrashRestoreRequest,
    TrashRestoreResponse,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _node_list_item():
    return NodeListItem(
        id=uuid4(),
        owner_id=uuid4(),
        parent_id=None,
        name="file.txt",
        node_type=NodeType.FILE,
        visibility=NodeVisibility.PRIVATE,
        path="/file.txt",
        depth=0,
        created_at=NOW,
        updated_at=NOW,
        is_deleted=True,
    )


def _trash_item_kwargs(**overrides):
    base = dict(
        id=uuid4(),
        node_id=uuid4(),
        owner_id=uuid4(),
        original_path="/folder/file.txt",
        status=TrashItemStatus.IN_TRASH,
        deleted_at=NOW,
        restore_available=True,
    )
    base.update(overrides)
    return base


class TestTrashItemRead:
    """Тесты схемы чтения элемента корзины."""

    def test_valid_minimal(self):
        r = TrashItemRead(**_trash_item_kwargs())
        assert r.deleted_by is None
        assert r.expires_at is None
        assert r.purged_at is None
        assert r.node is None
        assert r.status == TrashItemStatus.IN_TRASH

    def test_with_node(self):
        r = TrashItemRead(**_trash_item_kwargs(node=_node_list_item()))
        assert r.node is not None
        assert r.node.name == "file.txt"

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            TrashItemRead(id=uuid4())

    def test_status_enum_coercion(self):
        r = TrashItemRead(**_trash_item_kwargs(status="purged"))
        assert r.status == TrashItemStatus.PURGED

    def test_from_attributes(self):
        class Obj:
            pass

        obj = Obj()
        data = _trash_item_kwargs(deleted_by=None, original_parent_id=None,
                                  expires_at=None, purged_at=None, node=None)
        for k, v in data.items():
            setattr(obj, k, v)
        r = TrashItemRead.model_validate(obj)
        assert r.original_path == "/folder/file.txt"


class TestTrashItemListItem:
    """Тесты элемента списка корзины."""

    def test_valid(self):
        r = TrashItemListItem(**_trash_item_kwargs())
        assert r.restore_available is True

    def test_with_node(self):
        r = TrashItemListItem(**_trash_item_kwargs(node=_node_list_item()))
        assert r.node.node_type == NodeType.FILE


class TestTrashQueryParams:
    """Тесты параметров запроса списка корзины."""

    def test_defaults(self):
        p = TrashQueryParams()
        assert p.status == TrashItemStatus.IN_TRASH
        assert p.sort_by == "deleted_at"
        assert p.sort_desc is True
        assert p.restore_available is None

    def test_query_normalized(self):
        p = TrashQueryParams(query="  term  ")
        assert p.query == "term"

    def test_query_blank_raises(self):
        # str_strip_whitespace обрезает до "", что нарушает min_length=1.
        with pytest.raises(ValidationError):
            TrashQueryParams(query="   ")

    def test_deleted_range_invalid_raises(self):
        with pytest.raises(ValidationError):
            TrashQueryParams(
                deleted_from=NOW + timedelta(days=1),
                deleted_to=NOW,
            )

    def test_deleted_range_valid(self):
        p = TrashQueryParams(deleted_from=NOW, deleted_to=NOW + timedelta(days=1))
        assert p.deleted_to > p.deleted_from

    def test_status_can_be_none(self):
        p = TrashQueryParams(status=None)
        assert p.status is None

    def test_sort_by_too_long_raises(self):
        with pytest.raises(ValidationError):
            TrashQueryParams(sort_by="a" * 65)


class TestTrashRestoreRequest:
    """Тесты запроса восстановления из корзины."""

    def test_with_trash_item_id(self):
        r = TrashRestoreRequest(trash_item_id=uuid4())
        assert r.node_id is None

    def test_with_node_id(self):
        r = TrashRestoreRequest(node_id=uuid4())
        assert r.trash_item_id is None

    def test_neither_identifier_raises(self):
        with pytest.raises(ValidationError):
            TrashRestoreRequest()

    def test_with_target_parent(self):
        r = TrashRestoreRequest(trash_item_id=uuid4(), target_parent_id=uuid4())
        assert r.target_parent_id is not None


class TestTrashRestoreResponse:
    """Тесты ответа на восстановление из корзины."""

    def test_valid_defaults(self):
        r = TrashRestoreResponse(success=True)
        assert r.trash_item is None
        assert r.node is None
        assert r.message == "Элемент успешно восстановлен из корзины."

    def test_with_payload(self):
        r = TrashRestoreResponse(
            success=True,
            trash_item=TrashItemRead(**_trash_item_kwargs()),
            node=_node_list_item(),
        )
        assert r.trash_item is not None
        assert r.node is not None


class TestTrashPurgeRequest:
    """Тесты запроса окончательного удаления из корзины."""

    def test_with_trash_item_ids(self):
        r = TrashPurgeRequest(trash_item_ids=[uuid4()])
        assert r.node_ids is None

    def test_with_node_ids(self):
        r = TrashPurgeRequest(node_ids=[uuid4(), uuid4()])
        assert len(r.node_ids) == 2

    def test_neither_raises(self):
        with pytest.raises(ValidationError):
            TrashPurgeRequest()

    def test_empty_lists_raise(self):
        with pytest.raises(ValidationError):
            TrashPurgeRequest(trash_item_ids=[])

    def test_duplicate_ids_raise(self):
        dup = uuid4()
        with pytest.raises(ValidationError):
            TrashPurgeRequest(trash_item_ids=[dup, dup])

    def test_reason_normalized(self):
        r = TrashPurgeRequest(node_ids=[uuid4()], reason="  cleanup  ")
        assert r.reason == "cleanup"

    def test_reason_blank_becomes_none(self):
        r = TrashPurgeRequest(node_ids=[uuid4()], reason="   ")
        assert r.reason is None

    def test_too_many_ids_raises(self):
        with pytest.raises(ValidationError):
            TrashPurgeRequest(node_ids=[uuid4() for _ in range(1001)])


class TestTrashPurgeResponse:
    """Тесты ответа на окончательное удаление из корзины."""

    def test_valid_defaults(self):
        r = TrashPurgeResponse(success=True, requested_count=2, purged_count=2)
        assert r.failed_count == 0
        assert r.purged_trash_item_ids == []
        assert r.failed_trash_item_ids == []
        assert r.message == "Окончательное удаление элементов корзины выполнено."

    def test_negative_count_raises(self):
        with pytest.raises(ValidationError):
            TrashPurgeResponse(success=False, requested_count=-1, purged_count=0)


class TestTrashEmptyRequest:
    """Тесты запроса очистки корзины."""

    def test_defaults(self):
        r = TrashEmptyRequest()
        assert r.owner_id is None
        assert r.only_expired is False
        assert r.reason is None

    def test_reason_normalized(self):
        r = TrashEmptyRequest(reason="  go  ")
        assert r.reason == "go"

    def test_reason_blank_becomes_none(self):
        r = TrashEmptyRequest(reason="   ")
        assert r.reason is None

    def test_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            TrashEmptyRequest(reason="a" * 513)


class TestTrashCleanupRequest:
    """Тесты запроса автоматической очистки корзины."""

    def test_defaults(self):
        r = TrashCleanupRequest()
        assert r.limit == 500
        assert r.dry_run is False
        assert r.owner_id is None

    def test_limit_out_of_range_low_raises(self):
        with pytest.raises(ValidationError):
            TrashCleanupRequest(limit=0)

    def test_limit_out_of_range_high_raises(self):
        with pytest.raises(ValidationError):
            TrashCleanupRequest(limit=5001)

    def test_limit_boundaries(self):
        assert TrashCleanupRequest(limit=1).limit == 1
        assert TrashCleanupRequest(limit=5000).limit == 5000
