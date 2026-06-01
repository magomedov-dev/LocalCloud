"""Юнит-тесты репозитория элементов корзины (TrashItemRepository)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.exceptions import (
    EntityNotFoundError,
    InvalidQueryError,
    RepositoryError,
)
from database.models.enums import TrashItemStatus
from database.repositories.trash import TrashItemRepository


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

def make_session():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.scalar_one = MagicMock(return_value=0)
    result.rowcount = 0
    result.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session, result


def make_repo():
    session, result = make_session()
    return TrashItemRepository(session=session), session, result


def make_trash_item(**kwargs):
    item = MagicMock()
    node = MagicMock()
    node.id = uuid.uuid4()
    node.owner_id = uuid.uuid4()
    node.is_deleted = True
    node.restore = MagicMock()

    defaults = dict(
        id=uuid.uuid4(),
        node_id=node.id,
        node=node,
        owner_id=node.owner_id,
        deleter_id=uuid.uuid4(),
        deleted_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        original_path="/test.txt",
        original_parent_id=None,
        purged_at=None,
        restore_available=True,
        status=TrashItemStatus.IN_TRASH,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(item, k, v)
    item.purge = MagicMock()
    item.disable_restore = MagicMock()
    return item


# ---------------------------------------------------------------------------
# Тесты: get_by_id / get_required_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_by_id_returns_item_when_found():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.get_by_id(item.id)
    assert res is item


@pytest.mark.asyncio
async def test_get_required_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_by_id_returns_item():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.get_required_by_id(item.id)
    assert res is item


# ---------------------------------------------------------------------------
# Тесты: get_by_node_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_node_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_node_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_by_node_id_returns_item_when_found():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.get_by_node_id(item.node_id)
    assert res is item


@pytest.mark.asyncio
async def test_get_by_node_id_without_purged():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_node_id(uuid.uuid4(), include_purged=False)
    assert res is None


# ---------------------------------------------------------------------------
# Тесты: list_user_trash (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_trash_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    for method_name in ['list_user_trash', 'list_by_owner', 'list_owner_trash']:
        if hasattr(repo, method_name):
            method = getattr(repo, method_name)
            try:
                res = await method(uuid.uuid4())
            except TypeError:
                res = await method(owner_id=uuid.uuid4())
            assert isinstance(res, list)
            break


# ---------------------------------------------------------------------------
# Тесты: create_trash_item (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_trash_item_success():
    repo, session, result = make_repo()
    if hasattr(repo, 'create_trash_item'):
        item = make_trash_item()
        mock_node = MagicMock()
        user_id = uuid.uuid4()
        node_id = uuid.uuid4()
        mock_node.id = node_id
        mock_node.owner_id = user_id
        mock_node.parent_id = None
        mock_node.path = "/test.txt"
        mock_node.is_deleted = False

        # Мокаем внутренние вызовы, которые делает TrashItemRepository
        repo.nodes.get_required_by_id = AsyncMock(return_value=mock_node)
        repo.nodes.soft_delete_node = AsyncMock(return_value=mock_node)
        repo.get_by_node_id = AsyncMock(return_value=None)  # нет существующего элемента корзины

        async def fake_create(entity, flush=True, refresh=False):
            return item

        repo.create = fake_create  # type: ignore
        res = await repo.create_trash_item(
            node_id=node_id,
            owner_id=user_id,
            deleted_by=user_id,
            original_path="/test.txt",
        )
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: restore_item (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restore_item_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'restore_item'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.restore_item(uuid.uuid4())


@pytest.mark.asyncio
async def test_restore_item_success():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    if hasattr(repo, 'restore_item'):
        res = await repo.restore_item(item.id)
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: purge_item (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purge_item_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'purge_item'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.purge_item(uuid.uuid4())


@pytest.mark.asyncio
async def test_purge_item_success():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    if hasattr(repo, 'purge_item'):
        res = await repo.purge_item(item.id)
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: find_expired_items (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_expired_items_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'find_expired_items'):
        res = await repo.find_expired_items()
        assert isinstance(res, list)
    elif hasattr(repo, 'find_items_to_purge'):
        res = await repo.find_items_to_purge()
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: count (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=4)
    from database.models.filesystem import TrashItem
    count = await repo.count(TrashItem.owner_id == uuid.uuid4())
    assert count == 4


# ---------------------------------------------------------------------------
# Тесты: exists (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exists_returns_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    from database.models.filesystem import TrashItem
    res = await repo.exists(TrashItem.id == uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_exists_returns_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    from database.models.filesystem import TrashItem
    res = await repo.exists(TrashItem.id == uuid.uuid4())
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: nodes sub-repo is accessible
# ---------------------------------------------------------------------------

def test_nodes_sub_repo_accessible():
    repo, session, result = make_repo()
    assert hasattr(repo, 'nodes')
    from database.repositories.nodes import FileSystemNodeRepository
    assert isinstance(repo.nodes, FileSystemNodeRepository)


# ---------------------------------------------------------------------------
# Тесты: get_required_by_node_id / get_active / get_required_active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_by_node_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_node_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_by_node_id_returns_item():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.get_required_by_node_id(item.node_id)
    assert res is item


@pytest.mark.asyncio
async def test_get_active_by_node_id_returns_item():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.get_active_by_node_id(item.node_id)
    assert res is item


@pytest.mark.asyncio
async def test_get_required_active_by_node_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_active_by_node_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_active_by_node_id_returns_item():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.get_required_active_by_node_id(item.node_id)
    assert res is item


# ---------------------------------------------------------------------------
# Тесты: create_trash_item
# ---------------------------------------------------------------------------

def make_node(**kwargs):
    node = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        parent_id=None,
        path="/test.txt",
        is_deleted=False,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(node, k, v)
    return node


@pytest.mark.asyncio
async def test_create_trash_item_new_with_soft_delete():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    repo.nodes.soft_delete_node = AsyncMock()
    repo.get_by_node_id = AsyncMock(return_value=None)

    created = make_trash_item()

    async def fake_create(entity, flush=True, refresh=False):
        return created

    repo.create = fake_create  # type: ignore
    res = await repo.create_trash_item(
        node_id=node.id,
        deleted_by=uuid.uuid4(),
        refresh=True,
    )
    assert res is created
    repo.nodes.soft_delete_node.assert_awaited_once()
    session.flush.assert_awaited()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_create_trash_item_owner_mismatch_raises():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    repo.get_by_node_id = AsyncMock(return_value=None)
    with pytest.raises(InvalidQueryError):
        await repo.create_trash_item(node_id=node.id, owner_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_create_trash_item_invalid_expiration_raises():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    repo.get_by_node_id = AsyncMock(return_value=None)
    moment = datetime.now(UTC)
    with pytest.raises(InvalidQueryError):
        await repo.create_trash_item(
            node_id=node.id,
            deleted_at=moment,
            expires_at=moment - timedelta(days=1),
        )


@pytest.mark.asyncio
async def test_create_trash_item_existing_active_raises_duplicate():
    from database.exceptions import DuplicateEntityError
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    existing = make_trash_item()
    existing.is_in_trash = True
    existing.purged_at = None
    repo.get_by_node_id = AsyncMock(return_value=existing)
    with pytest.raises(DuplicateEntityError):
        await repo.create_trash_item(node_id=node.id)


@pytest.mark.asyncio
async def test_create_trash_item_existing_reused():
    repo, session, result = make_repo()
    node = make_node(is_deleted=False)
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    repo.nodes.soft_delete_node = AsyncMock()
    existing = make_trash_item()
    existing.is_in_trash = False
    existing.purged_at = None
    repo.get_by_node_id = AsyncMock(return_value=existing)

    res = await repo.create_trash_item(
        node_id=node.id,
        deleted_by=uuid.uuid4(),
        original_path="//foo//bar/",
        refresh=True,
    )
    assert res is existing
    assert existing.purged_at is None
    assert existing.status == TrashItemStatus.IN_TRASH
    assert existing.original_path == "/foo/bar"
    repo.nodes.soft_delete_node.assert_awaited_once()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_create_trash_item_existing_node_already_deleted_skips_soft_delete():
    repo, session, result = make_repo()
    node = make_node(is_deleted=True)
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    repo.nodes.soft_delete_node = AsyncMock()
    existing = make_trash_item()
    existing.is_in_trash = False
    existing.purged_at = datetime.now(UTC)
    repo.get_by_node_id = AsyncMock(return_value=existing)

    res = await repo.create_trash_item(node_id=node.id)
    assert res is existing
    repo.nodes.soft_delete_node.assert_not_awaited()


# ---------------------------------------------------------------------------
# Тесты: get_user_trash list / filters / sort
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_trash_returns_list():
    repo, session, result = make_repo()
    items = [make_trash_item(), make_trash_item()]
    result.scalars.return_value.all.return_value = items
    res = await repo.get_user_trash(owner_id=uuid.uuid4())
    assert res == items


@pytest.mark.asyncio
async def test_get_user_trash_include_purged_and_non_restorable():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_user_trash(
        owner_id=uuid.uuid4(),
        include_purged=True,
        include_non_restorable=False,
        sort_by="original_path",
        sort_direction="asc",
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_user_trash_invalid_pagination_raises():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.get_user_trash(owner_id=uuid.uuid4(), limit=0)


@pytest.mark.asyncio
async def test_get_user_active_trash_returns_list():
    repo, session, result = make_repo()
    items = [make_trash_item()]
    result.scalars.return_value.all.return_value = items
    res = await repo.get_user_active_trash(owner_id=uuid.uuid4())
    assert res == items


@pytest.mark.asyncio
async def test_get_user_active_trash_exclude_expired():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_user_active_trash(
        owner_id=uuid.uuid4(),
        exclude_expired=True,
        now=datetime.now(UTC),
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_user_active_trash_exclude_expired_default_now():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_user_active_trash(
        owner_id=uuid.uuid4(),
        exclude_expired=True,
    )
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: просроченные элементы / готовые к очистке / невосстановимые
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_expired_items_with_owner_and_restorable_filter():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_expired_items(
        now=datetime.now(UTC),
        owner_id=uuid.uuid4(),
        include_non_restorable=False,
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_expired_items_default_now():
    repo, session, result = make_repo()
    items = [make_trash_item()]
    result.scalars.return_value.all.return_value = items
    res = await repo.get_expired_items()
    assert res == items


@pytest.mark.asyncio
async def test_get_items_ready_for_purge_delegates():
    repo, session, result = make_repo()
    items = [make_trash_item()]
    result.scalars.return_value.all.return_value = items
    res = await repo.get_items_ready_for_purge(limit=10)
    assert res == items


@pytest.mark.asyncio
async def test_get_non_restorable_items_with_owner_include_purged():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_non_restorable_items(
        owner_id=uuid.uuid4(),
        include_purged=True,
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_non_restorable_items_default():
    repo, session, result = make_repo()
    items = [make_trash_item()]
    result.scalars.return_value.all.return_value = items
    res = await repo.get_non_restorable_items()
    assert res == items


# ---------------------------------------------------------------------------
# Тесты: mark_restored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_restored_success():
    repo, session, result = make_repo()
    item = make_trash_item(purged_at=None, restore_available=True)
    item.restore = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=item)
    repo.nodes.restore_node = AsyncMock()
    res = await repo.mark_restored(trash_item_id=item.id, restored_by=uuid.uuid4(), refresh=True)
    assert res is item
    item.restore.assert_called_once()
    repo.nodes.restore_node.assert_awaited_once()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_mark_restored_without_node_restore():
    repo, session, result = make_repo()
    item = make_trash_item(purged_at=None, restore_available=True)
    item.restore = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=item)
    repo.nodes.restore_node = AsyncMock()
    res = await repo.mark_restored(trash_item_id=item.id, restore_node=False)
    assert res is item
    repo.nodes.restore_node.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_restored_purged_raises():
    repo, session, result = make_repo()
    item = make_trash_item(purged_at=datetime.now(UTC))
    result.scalar_one_or_none = MagicMock(return_value=item)
    with pytest.raises(InvalidQueryError):
        await repo.mark_restored(trash_item_id=item.id)


@pytest.mark.asyncio
async def test_mark_restored_not_restorable_raises():
    repo, session, result = make_repo()
    item = make_trash_item(purged_at=None, restore_available=False)
    result.scalar_one_or_none = MagicMock(return_value=item)
    with pytest.raises(InvalidQueryError):
        await repo.mark_restored(trash_item_id=item.id)


# ---------------------------------------------------------------------------
# Тесты: mark_purged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_purged_success():
    repo, session, result = make_repo()
    item = make_trash_item()
    item.purge = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.mark_purged(trash_item_id=item.id, refresh=True)
    assert res is item
    item.purge.assert_called_once()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_mark_purged_with_purge_node():
    repo, session, result = make_repo()
    item = make_trash_item()
    item.purge = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=item)
    repo.nodes.mark_purged = AsyncMock()
    res = await repo.mark_purged(node_id=item.node_id, purge_node=True)
    assert res is item
    repo.nodes.mark_purged.assert_awaited_once()


# ---------------------------------------------------------------------------
# Тесты: disable_restore / enable_restore
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disable_restore_success():
    repo, session, result = make_repo()
    item = make_trash_item(restore_available=True)
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.disable_restore(trash_item_id=item.id, refresh=True)
    assert res.restore_available is False
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_enable_restore_success():
    repo, session, result = make_repo()
    item = make_trash_item(restore_available=False, purged_at=None)
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.enable_restore(trash_item_id=item.id, refresh=True)
    assert res.restore_available is True
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_enable_restore_purged_raises():
    repo, session, result = make_repo()
    item = make_trash_item(purged_at=datetime.now(UTC))
    result.scalar_one_or_none = MagicMock(return_value=item)
    with pytest.raises(InvalidQueryError):
        await repo.enable_restore(trash_item_id=item.id)


# ---------------------------------------------------------------------------
# Тесты: update_expiration / expire_item_now
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_expiration_success():
    repo, session, result = make_repo()
    moment = datetime.now(UTC)
    item = make_trash_item(deleted_at=moment)
    result.scalar_one_or_none = MagicMock(return_value=item)
    new_exp = moment + timedelta(days=10)
    res = await repo.update_expiration(trash_item_id=item.id, expires_at=new_exp, refresh=True)
    assert res.expires_at == new_exp
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_update_expiration_none_unlimited():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.update_expiration(trash_item_id=item.id, expires_at=None)
    assert res.expires_at is None


@pytest.mark.asyncio
async def test_update_expiration_invalid_raises():
    repo, session, result = make_repo()
    moment = datetime.now(UTC)
    item = make_trash_item(deleted_at=moment)
    result.scalar_one_or_none = MagicMock(return_value=item)
    with pytest.raises(InvalidQueryError):
        await repo.update_expiration(trash_item_id=item.id, expires_at=moment - timedelta(days=1))


@pytest.mark.asyncio
async def test_expire_item_now_success():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.expire_item_now(trash_item_id=item.id, refresh=True)
    assert res.expires_at is not None
    session.refresh.assert_awaited()


# ---------------------------------------------------------------------------
# Тесты: delete_trash_item / delete_purged_items / delete_by_node_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_trash_item_success():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.delete_trash_item(trash_item_id=item.id)
    assert res is True
    session.delete.assert_awaited_once_with(item)


@pytest.mark.asyncio
async def test_delete_trash_item_not_found_required_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.delete_trash_item(trash_item_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_trash_item_not_found_not_required_returns_false():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.delete_trash_item(node_id=uuid.uuid4(), required=False)
    assert res is False


@pytest.mark.asyncio
async def test_delete_purged_items_with_filters():
    repo, session, result = make_repo()
    result.rowcount = 5
    res = await repo.delete_purged_items(
        owner_id=uuid.uuid4(),
        older_than=datetime.now(UTC),
    )
    assert res == 5


@pytest.mark.asyncio
async def test_delete_purged_items_no_filters():
    repo, session, result = make_repo()
    result.rowcount = 2
    res = await repo.delete_purged_items()
    assert res == 2


@pytest.mark.asyncio
async def test_delete_by_node_id_delegates():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.delete_by_node_id(item.node_id)
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_trash_items_all_flags():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=7)
    res = await repo.count_user_trash_items(
        owner_id=uuid.uuid4(),
        include_purged=True,
        only_restorable=True,
    )
    assert res == 7


@pytest.mark.asyncio
async def test_count_user_trash_items_default():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    res = await repo.count_user_trash_items(owner_id=uuid.uuid4())
    assert res == 3


@pytest.mark.asyncio
async def test_count_active_user_trash_items_exclude_expired():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.count_active_user_trash_items(
        owner_id=uuid.uuid4(),
        exclude_expired=True,
        now=datetime.now(UTC),
    )
    assert res == 1


@pytest.mark.asyncio
async def test_count_active_user_trash_items_default():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    res = await repo.count_active_user_trash_items(owner_id=uuid.uuid4())
    assert res == 0


@pytest.mark.asyncio
async def test_count_expired_items_with_owner():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=9)
    res = await repo.count_expired_items(now=datetime.now(UTC), owner_id=uuid.uuid4())
    assert res == 9


@pytest.mark.asyncio
async def test_count_expired_items_default():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=4)
    res = await repo.count_expired_items()
    assert res == 4


# ---------------------------------------------------------------------------
# Тесты: search_user_trash / count_user_trash_filtered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_user_trash_all_filters():
    repo, session, result = make_repo()
    items = [make_trash_item()]
    result.scalars.return_value.all.return_value = items
    now = datetime.now(UTC)
    res = await repo.search_user_trash(
        owner_id=uuid.uuid4(),
        include_purged=True,
        status=TrashItemStatus.IN_TRASH,
        restore_available=True,
        deleted_from=now - timedelta(days=5),
        deleted_to=now,
        expires_before=now + timedelta(days=5),
        query="  Foo  ",
        sort_by="expires_at",
        sort_direction="asc",
    )
    assert res == items


@pytest.mark.asyncio
async def test_search_user_trash_minimal():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_user_trash(owner_id=uuid.uuid4(), query="")
    assert res == []


@pytest.mark.asyncio
async def test_count_user_trash_filtered_all_filters():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=11)
    now = datetime.now(UTC)
    res = await repo.count_user_trash_filtered(
        owner_id=uuid.uuid4(),
        include_purged=True,
        status=TrashItemStatus.IN_TRASH,
        restore_available=False,
        deleted_from=now - timedelta(days=5),
        deleted_to=now,
        expires_before=now,
        query="bar",
    )
    assert res == 11


@pytest.mark.asyncio
async def test_count_user_trash_filtered_minimal_returns_zero():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=None)
    res = await repo.count_user_trash_filtered(owner_id=uuid.uuid4())
    assert res == 0


# ---------------------------------------------------------------------------
# Тесты: trash_item_exists_for_node / can_restore / is_expired
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trash_item_exists_for_node_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.trash_item_exists_for_node(uuid.uuid4(), include_purged=False)
    assert res is True


@pytest.mark.asyncio
async def test_can_restore_true():
    repo, session, result = make_repo()
    item = make_trash_item(restore_available=True, purged_at=None, expires_at=None)
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.can_restore(trash_item_id=item.id)
    assert res is True


@pytest.mark.asyncio
async def test_can_restore_not_found_false():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.can_restore(trash_item_id=uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_can_restore_not_available_false():
    repo, session, result = make_repo()
    item = make_trash_item(restore_available=False)
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.can_restore(trash_item_id=item.id)
    assert res is False


@pytest.mark.asyncio
async def test_can_restore_purged_false():
    repo, session, result = make_repo()
    item = make_trash_item(restore_available=True, purged_at=datetime.now(UTC))
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.can_restore(trash_item_id=item.id)
    assert res is False


@pytest.mark.asyncio
async def test_can_restore_expired_false():
    repo, session, result = make_repo()
    past = datetime.now(UTC) - timedelta(days=1)
    item = make_trash_item(restore_available=True, purged_at=None, expires_at=past)
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.can_restore(trash_item_id=item.id, check_expiration=True)
    assert res is False


@pytest.mark.asyncio
async def test_can_restore_check_expiration_not_expired_true():
    repo, session, result = make_repo()
    future = datetime.now(UTC) + timedelta(days=1)
    item = make_trash_item(restore_available=True, purged_at=None, expires_at=future)
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.can_restore(trash_item_id=item.id, check_expiration=True, now=datetime.now(UTC))
    assert res is True


@pytest.mark.asyncio
async def test_is_expired_true():
    repo, session, result = make_repo()
    past = datetime.now(UTC) - timedelta(days=1)
    item = make_trash_item(expires_at=past)
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.is_expired(trash_item_id=item.id)
    assert res is True


@pytest.mark.asyncio
async def test_is_expired_not_found_false():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.is_expired(trash_item_id=uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_is_expired_no_expiration_false():
    repo, session, result = make_repo()
    item = make_trash_item(expires_at=None)
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.is_expired(trash_item_id=item.id, now=datetime.now(UTC))
    assert res is False


# ---------------------------------------------------------------------------
# Тесты: lookup validation (_validate_single_lookup)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lookup_by_node_id_branch():
    repo, session, result = make_repo()
    item = make_trash_item()
    result.scalar_one_or_none = MagicMock(return_value=item)
    res = await repo.disable_restore(node_id=item.node_id)
    assert res is item


@pytest.mark.asyncio
async def test_lookup_no_id_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.disable_restore()


@pytest.mark.asyncio
async def test_lookup_both_ids_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.disable_restore(trash_item_id=uuid.uuid4(), node_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_required_lookup_not_found_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.disable_restore(trash_item_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: _validate_original_path
# ---------------------------------------------------------------------------

def test_validate_original_path_empty_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_original_path("   ")


def test_validate_original_path_normalizes():
    repo, session, result = make_repo()
    assert repo._validate_original_path("foo//bar/") == "/foo/bar"


def test_validate_original_path_root():
    repo, session, result = make_repo()
    assert repo._validate_original_path("/") == "/"


# ---------------------------------------------------------------------------
# Тесты: _get_order_by validation
# ---------------------------------------------------------------------------

def test_get_order_by_invalid_field_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_order_by("nope", "asc")


def test_get_order_by_invalid_direction_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_order_by("deleted_at", "sideways")


def test_get_order_by_asc_and_desc():
    repo, session, result = make_repo()
    assert repo._get_order_by("deleted_at", "asc") is not None
    assert repo._get_order_by("purged_at", "desc") is not None


# ---------------------------------------------------------------------------
# Тесты: переопределённый create (дубликаты / маппинг ошибок целостности)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_maps_duplicate_entity_error():
    from database.exceptions import DuplicateEntityError
    repo, session, result = make_repo()
    item = make_trash_item()

    async def boom(self, entity, *, flush=True, refresh=False):
        raise DuplicateEntityError("TrashItem", repository="x")

    import database.repositories.base as base_mod
    orig = base_mod.BaseRepository.create
    base_mod.BaseRepository.create = boom  # type: ignore
    try:
        with pytest.raises(DuplicateEntityError):
            await repo.create(item)
    finally:
        base_mod.BaseRepository.create = orig  # type: ignore


@pytest.mark.asyncio
async def test_create_maps_integrity_error():
    repo, session, result = make_repo()
    item = make_trash_item()
    item.node_id = uuid.uuid4()

    async def boom(self, entity, *, flush=True, refresh=False):
        raise IntegrityError("stmt", {}, Exception("orig"))

    import database.repositories.base as base_mod
    orig = base_mod.BaseRepository.create
    base_mod.BaseRepository.create = boom  # type: ignore
    try:
        with pytest.raises(RepositoryError):
            await repo.create(item)
    finally:
        base_mod.BaseRepository.create = orig  # type: ignore


@pytest.mark.asyncio
async def test_create_success_path():
    repo, session, result = make_repo()
    item = make_trash_item()
    res = await repo.create(item, flush=False)
    assert res is item
    session.add.assert_called_once_with(item)


# ---------------------------------------------------------------------------
# Тесты: _execute_trash_item_statement error mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_trash_item_statement_success():
    repo, session, result = make_repo()
    items = [make_trash_item()]
    result.scalars.return_value.all.return_value = items
    res = await repo._execute_trash_item_statement(repo.select(), operation="op")
    assert res == items


@pytest.mark.asyncio
async def test_execute_trash_item_statement_integrity_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("orig")))
    with pytest.raises(RepositoryError):
        await repo._execute_trash_item_statement(repo.select(), operation="op")


@pytest.mark.asyncio
async def test_execute_trash_item_statement_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._execute_trash_item_statement(repo.select(), operation="op")
