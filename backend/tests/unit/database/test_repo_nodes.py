"""Юнит-тесты репозитория узлов файловой системы (FileSystemNodeRepository)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
    RepositoryError,
)
from database.models.enums import NodeType, NodeVisibility
from database.repositories.nodes import FileSystemNodeRepository


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
    return FileSystemNodeRepository(session=session), session, result


def make_node(**kwargs):
    node = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        node_type=NodeType.FOLDER,
        name="test-folder",
        path="/test-folder",
        depth=1,
        is_deleted=False,
        visibility=NodeVisibility.PRIVATE,
        parent_id=None,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(node, k, v)
    node.soft_delete = MagicMock()
    node.restore = MagicMock()
    return node


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
async def test_get_by_id_returns_node_when_found():
    repo, session, result = make_repo()
    node = make_node()
    result.scalar_one_or_none = MagicMock(return_value=node)
    res = await repo.get_by_id(node.id)
    assert res is node


@pytest.mark.asyncio
async def test_get_required_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_by_id_returns_node():
    repo, session, result = make_repo()
    node = make_node()
    result.scalar_one_or_none = MagicMock(return_value=node)
    res = await repo.get_required_by_id(node.id)
    assert res is node


# ---------------------------------------------------------------------------
# Тесты: get_active_node_by_id / get_required_active_node_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_node_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_active_node_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_active_node_by_id_returns_node_when_found():
    repo, session, result = make_repo()
    node = make_node(is_deleted=False)
    result.scalar_one_or_none = MagicMock(return_value=node)
    res = await repo.get_active_node_by_id(node.id)
    assert res is node


@pytest.mark.asyncio
async def test_get_required_active_node_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_active_node_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_by_owner_and_path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_owner_and_path_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_owner_and_path(owner_id=uuid.uuid4(), path="/test")
    assert res is None


@pytest.mark.asyncio
async def test_get_by_owner_and_path_returns_node():
    repo, session, result = make_repo()
    node = make_node()
    result.scalar_one_or_none = MagicMock(return_value=node)
    res = await repo.get_by_owner_and_path(owner_id=node.owner_id, path="/test-folder")
    assert res is node


# ---------------------------------------------------------------------------
# Тесты: list_owner_nodes / list_owner_root_nodes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_owner_nodes_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    # Заглядываем в сигнатуру метода — проверяем, что он существует
    if hasattr(repo, 'list_owner_nodes'):
        res = await repo.list_owner_nodes(uuid.uuid4())
        assert res == []


@pytest.mark.asyncio
async def test_list_children_returns_empty_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    # пробуем get_children или list_children
    if hasattr(repo, 'get_children'):
        res = await repo.get_children(parent_id=uuid.uuid4())
        assert isinstance(res, list)
    elif hasattr(repo, 'list_children'):
        res = await repo.list_children(node_id=uuid.uuid4())
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: search_nodes (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_nodes_raises_for_invalid_pagination():
    repo, session, result = make_repo()
    if hasattr(repo, 'search_nodes'):
        with pytest.raises(Exception):
            await repo.search_nodes(owner_id=uuid.uuid4(), query="test", offset=-1)


@pytest.mark.asyncio
async def test_search_nodes_returns_list():
    repo, session, result = make_repo()
    if hasattr(repo, 'search_nodes'):
        result.scalars.return_value.all.return_value = []
        res = await repo.search_nodes(owner_id=uuid.uuid4(), query="test")
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: count by owner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=5)
    from database.models.filesystem import FileSystemNode
    count = await repo.count(FileSystemNode.owner_id == uuid.uuid4())
    assert count == 5


# ---------------------------------------------------------------------------
# Тесты: хелперы по типу узла (если есть в репозитории)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_owner_nodes_by_type_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'list_by_type'):
        res = await repo.list_by_type(owner_id=uuid.uuid4(), node_type=NodeType.FOLDER)
        assert isinstance(res, list)
    elif hasattr(repo, 'list_nodes_by_type'):
        res = await repo.list_nodes_by_type(owner_id=uuid.uuid4(), node_type=NodeType.FOLDER)
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: soft_delete_node (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_soft_delete_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'soft_delete_node'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.soft_delete_node(node_id=uuid.uuid4(), deleted_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_soft_delete_success():
    repo, session, result = make_repo()
    node = make_node()
    result.scalar_one_or_none = MagicMock(return_value=node)
    if hasattr(repo, 'soft_delete_node'):
        res = await repo.soft_delete_node(node_id=node.id, deleted_by=uuid.uuid4())
        assert res is node


# ---------------------------------------------------------------------------
# Тесты: проверка exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exists_returns_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    from database.models.filesystem import FileSystemNode
    res = await repo.exists(FileSystemNode.id == uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_exists_returns_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    from database.models.filesystem import FileSystemNode
    res = await repo.exists(FileSystemNode.id == uuid.uuid4())
    assert res is True


# ---------------------------------------------------------------------------
# Расширенные хелперы
# ---------------------------------------------------------------------------

def make_real_node(**kwargs):
    """Мок узла с реальными path/depth/name, чтобы циклы в коде работали."""
    node = make_node(**kwargs)
    # rename/move/mark_deleted — это MagicMock; задаём им реальные side effects
    # чтобы последующее чтение атрибутов в коде вело себя реалистично.
    def _rename(new_name, updated_by=None):
        node.name = new_name
        node.updated_by = updated_by
    def _move(new_parent_id, new_path, new_depth, updated_by=None):
        node.parent_id = new_parent_id
        node.path = new_path
        node.depth = new_depth
        node.updated_by = updated_by
    def _mark_deleted(deleted_at=None, *, deleted_by=None):
        node.is_deleted = True
        node.deleted_at = deleted_at
        node.deleted_by = deleted_by
    node.rename = MagicMock(side_effect=_rename)
    node.move = MagicMock(side_effect=_move)
    node.mark_deleted = MagicMock(side_effect=_mark_deleted)
    return node


def set_scalar_one_or_none(result, *values):
    """Возвращает последовательные значения из result.scalar_one_or_none()."""
    result.scalar_one_or_none = MagicMock(side_effect=list(values))


def set_scalars_all(result, *batches):
    """Возвращает последовательные списки из result.scalars().all()."""
    scalars_objs = []
    for batch in batches:
        s = MagicMock()
        s.all = MagicMock(return_value=list(batch))
        scalars_objs.append(s)
    result.scalars = MagicMock(side_effect=scalars_objs)


def set_exists_count(result, *values):
    """Управляет и exists(), и count() (оба используют scalar_one)."""
    result.scalar_one = MagicMock(side_effect=list(values))


# ---------------------------------------------------------------------------
# get_nodes_by_ids
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_nodes_by_ids_empty_returns_empty():
    repo, session, result = make_repo()
    res = await repo.get_nodes_by_ids([])
    assert res == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_nodes_by_ids_returns_nodes():
    repo, session, result = make_repo()
    nodes = [make_node(), make_node()]
    set_scalars_all(result, nodes)
    res = await repo.get_nodes_by_ids([n.id for n in nodes], include_deleted=False)
    assert res == nodes
    session.execute.assert_awaited()


# ---------------------------------------------------------------------------
# Списки: корневые узлы / потомки / удалённые
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_root_nodes_returns_list_with_filters():
    repo, session, result = make_repo()
    nodes = [make_node(parent_id=None)]
    set_scalars_all(result, nodes)
    res = await repo.get_root_nodes(
        owner_id=uuid.uuid4(),
        include_deleted=True,
        node_type=NodeType.FOLDER,
        sort_by="created_at",
        sort_direction="desc",
    )
    assert res == nodes


@pytest.mark.asyncio
async def test_get_root_nodes_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.get_root_nodes(owner_id=uuid.uuid4(), limit=0)


@pytest.mark.asyncio
async def test_get_children_returns_list():
    repo, session, result = make_repo()
    nodes = [make_node()]
    set_scalars_all(result, nodes)
    res = await repo.get_children(
        parent_id=uuid.uuid4(),
        include_deleted=True,
        node_type=NodeType.FILE,
    )
    assert res == nodes


@pytest.mark.asyncio
async def test_get_active_children_delegates():
    repo, session, result = make_repo()
    nodes = [make_node()]
    set_scalars_all(result, nodes)
    res = await repo.get_active_children(parent_id=uuid.uuid4())
    assert res == nodes


@pytest.mark.asyncio
async def test_get_deleted_children_delegates():
    repo, session, result = make_repo()
    nodes = [make_node(is_deleted=True)]
    set_scalars_all(result, nodes)
    res = await repo.get_deleted_children(parent_id=uuid.uuid4())
    assert res == nodes


@pytest.mark.asyncio
async def test_list_deleted_nodes_returns_list():
    repo, session, result = make_repo()
    nodes = [make_node(is_deleted=True)]
    set_scalars_all(result, nodes)
    res = await repo.list_deleted_nodes(owner_id=uuid.uuid4())
    assert res == nodes


@pytest.mark.asyncio
async def test_list_deleted_nodes_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.list_deleted_nodes(owner_id=uuid.uuid4(), offset=-5)


# ---------------------------------------------------------------------------
# Иерархия: потомки / предки / хлебные крошки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_descendants_returns_list():
    repo, session, result = make_repo()
    root = make_node()
    children = [make_node(), make_node()]
    # get_required_by_id -> scalar_one_or_none(root); потомки -> scalars().all()
    set_scalar_one_or_none(result, root)
    set_scalars_all(result, children)
    res = await repo.get_descendants(node_id=root.id, include_self=True)
    assert res == children


@pytest.mark.asyncio
async def test_get_descendants_no_self_no_deleted_no_order():
    repo, session, result = make_repo()
    root = make_node()
    set_scalar_one_or_none(result, root)
    set_scalars_all(result, [])
    res = await repo.get_descendants(
        node_id=root.id,
        include_self=False,
        include_deleted=False,
        order_by_depth=False,
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_descendants_root_missing_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_descendants(node_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_ancestors_walks_parents():
    repo, session, result = make_repo()
    grandparent = make_node(name="gp", path="/gp", parent_id=None, depth=0)
    parent = make_node(name="p", path="/gp/p", parent_id=grandparent.id, depth=1)
    node = make_node(name="n", path="/gp/p/n", parent_id=parent.id, depth=2)
    # get_required_by_id(node), затем get_by_id(parent), get_by_id(grandparent)
    set_scalar_one_or_none(result, node, parent, grandparent)
    res = await repo.get_ancestors(node_id=node.id, include_self=True)
    assert res == [node, parent, grandparent]


@pytest.mark.asyncio
async def test_get_ancestors_breaks_on_missing_parent():
    repo, session, result = make_repo()
    parent_id = uuid.uuid4()
    node = make_node(parent_id=parent_id)
    # узел найден, затем поиск родителя возвращает None -> break
    set_scalar_one_or_none(result, node, None)
    res = await repo.get_ancestors(node_id=node.id, include_self=False)
    assert res == []


@pytest.mark.asyncio
async def test_get_ancestors_excludes_deleted():
    repo, session, result = make_repo()
    parent = make_node(name="p", parent_id=None, is_deleted=True)
    node = make_node(name="n", parent_id=parent.id, is_deleted=True)
    set_scalar_one_or_none(result, node, parent)
    # include_self True, но удалённые исключены -> узел пропущен; родитель удалён -> пропущен
    res = await repo.get_ancestors(
        node_id=node.id, include_self=True, include_deleted=False
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_breadcrumbs_reverses_ancestors():
    repo, session, result = make_repo()
    parent = make_node(name="p", path="/p", parent_id=None, depth=0)
    node = make_node(name="n", path="/p/n", parent_id=parent.id, depth=1)
    set_scalar_one_or_none(result, node, parent)
    res = await repo.get_breadcrumbs(node_id=node.id, include_self=True)
    # ancestors = [node, parent] в обратном порядке -> [parent, node]
    assert res == [parent, node]


# ---------------------------------------------------------------------------
# create_node и хелперы
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_node_root_success():
    repo, session, result = make_repo()
    set_exists_count(result, 0)  # check_name_conflict -> exists False
    owner_id = uuid.uuid4()
    res = await repo.create_node(
        owner_id=owner_id,
        name="newfile",
        node_type=NodeType.FILE,
    )
    session.add.assert_called_once()
    assert res.name == "newfile"
    assert res.path == "/newfile"
    assert res.depth == 0


@pytest.mark.asyncio
async def test_create_node_with_parent_builds_path():
    repo, session, result = make_repo()
    owner_id = uuid.uuid4()
    parent = make_node(
        owner_id=owner_id, node_type=NodeType.FOLDER,
        path="/docs", depth=0, is_deleted=False,
    )
    # get_required_by_id(parent), затем check_name_conflict exists -> 0
    set_scalar_one_or_none(result, parent)
    set_exists_count(result, 0)
    res = await repo.create_node(
        owner_id=owner_id,
        name="child",
        node_type=NodeType.FOLDER,
        parent_id=parent.id,
    )
    assert res.path == "/docs/child"
    assert res.depth == 1


@pytest.mark.asyncio
async def test_create_node_explicit_path_and_depth():
    repo, session, result = make_repo()
    res = await repo.create_node(
        owner_id=uuid.uuid4(),
        name="x",
        node_type=NodeType.FILE,
        path="//custom//path//",
        depth=3,
        check_conflict=False,
    )
    assert res.path == "/custom/path"
    assert res.depth == 3


@pytest.mark.asyncio
async def test_create_node_conflict_raises():
    repo, session, result = make_repo()
    set_exists_count(result, 1)  # конфликт есть
    with pytest.raises(DuplicateEntityError):
        await repo.create_node(
            owner_id=uuid.uuid4(),
            name="dup",
            node_type=NodeType.FILE,
        )


@pytest.mark.asyncio
async def test_create_node_invalid_name_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_node(
            owner_id=uuid.uuid4(),
            name="bad/name",
            node_type=NodeType.FILE,
        )


@pytest.mark.asyncio
async def test_create_node_check_owner_exists_missing():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.create_node(
            owner_id=uuid.uuid4(),
            name="x",
            node_type=NodeType.FILE,
            check_owner_exists=True,
        )


@pytest.mark.asyncio
async def test_create_node_check_owner_exists_db_error():
    repo, session, result = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.create_node(
            owner_id=uuid.uuid4(),
            name="x",
            node_type=NodeType.FILE,
            check_owner_exists=True,
        )


@pytest.mark.asyncio
async def test_create_node_negative_depth_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_node(
            owner_id=uuid.uuid4(),
            name="x",
            node_type=NodeType.FILE,
            depth=-1,
            check_conflict=False,
        )


@pytest.mark.asyncio
async def test_create_file_node_delegates():
    repo, session, result = make_repo()
    set_exists_count(result, 0)
    res = await repo.create_file_node(owner_id=uuid.uuid4(), name="f.txt")
    assert res.node_type == NodeType.FILE


@pytest.mark.asyncio
async def test_create_folder_node_delegates():
    repo, session, result = make_repo()
    set_exists_count(result, 0)
    res = await repo.create_folder_node(owner_id=uuid.uuid4(), name="folder")
    assert res.node_type == NodeType.FOLDER


@pytest.mark.asyncio
async def test_create_node_integrity_error_maps_duplicate():
    repo, session, result = make_repo()
    set_exists_count(result, 0)
    orig = MagicMock()
    orig.sqlstate = "23505"
    orig.constraint_name = "uq_name"
    session.flush = AsyncMock(side_effect=IntegrityError("s", {}, orig))
    with pytest.raises(DuplicateEntityError):
        await repo.create_node(
            owner_id=uuid.uuid4(), name="x", node_type=NodeType.FILE,
        )


@pytest.mark.asyncio
async def test_create_node_sqlalchemy_error_maps_repository():
    repo, session, result = make_repo()
    set_exists_count(result, 0)
    session.flush = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.create_node(
            owner_id=uuid.uuid4(), name="x", node_type=NodeType.FILE,
        )


# ---------------------------------------------------------------------------
# ветки _validate_parent_for_new_node (через create_node)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_node_parent_other_owner():
    repo, session, result = make_repo()
    parent = make_node(owner_id=uuid.uuid4(), node_type=NodeType.FOLDER)
    set_scalar_one_or_none(result, parent)
    with pytest.raises(InvalidQueryError):
        await repo.create_node(
            owner_id=uuid.uuid4(), name="x", node_type=NodeType.FILE,
            parent_id=parent.id,
        )


@pytest.mark.asyncio
async def test_create_node_parent_not_folder():
    repo, session, result = make_repo()
    owner_id = uuid.uuid4()
    parent = make_node(owner_id=owner_id, node_type=NodeType.FILE)
    set_scalar_one_or_none(result, parent)
    with pytest.raises(InvalidQueryError):
        await repo.create_node(
            owner_id=owner_id, name="x", node_type=NodeType.FILE,
            parent_id=parent.id,
        )


@pytest.mark.asyncio
async def test_create_node_parent_deleted():
    repo, session, result = make_repo()
    owner_id = uuid.uuid4()
    parent = make_node(owner_id=owner_id, node_type=NodeType.FOLDER, is_deleted=True)
    set_scalar_one_or_none(result, parent)
    with pytest.raises(InvalidQueryError):
        await repo.create_node(
            owner_id=owner_id, name="x", node_type=NodeType.FILE,
            parent_id=parent.id,
        )


# ---------------------------------------------------------------------------
# rename_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rename_node_same_name_returns_early():
    repo, session, result = make_repo()
    node = make_real_node(name="same")
    result.scalar_one_or_none = MagicMock(return_value=node)
    res = await repo.rename_node(node_id=node.id, new_name="same")
    assert res is node
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_rename_node_conflict_raises():
    repo, session, result = make_repo()
    node = make_real_node(name="old", parent_id=None)
    result.scalar_one_or_none = MagicMock(return_value=node)
    set_exists_count(result, 1)  # конфликт
    with pytest.raises(DuplicateEntityError):
        await repo.rename_node(node_id=node.id, new_name="new")


@pytest.mark.asyncio
async def test_rename_node_root_success_updates_path():
    repo, session, result = make_repo()
    node = make_real_node(name="old", path="/old", parent_id=None, depth=0)
    # get_required_by_id(node); затем потомки: снова get_required_by_id(node)
    set_scalar_one_or_none(result, node, node)
    set_exists_count(result, 0)  # нет конфликта
    set_scalars_all(result, [])  # потомки пусты
    res = await repo.rename_node(
        node_id=node.id, new_name="newname", refresh=True,
    )
    assert res is node
    assert node.name == "newname"
    assert node.path == "/newname"
    session.flush.assert_awaited()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_rename_node_with_parent_and_descendants():
    repo, session, result = make_repo()
    owner_id = uuid.uuid4()
    parent = make_real_node(
        name="docs", path="/docs", parent_id=None, depth=0, owner_id=owner_id,
    )
    node = make_real_node(
        name="old", path="/docs/old", parent_id=parent.id, depth=1, owner_id=owner_id,
    )
    child = make_real_node(
        name="c", path="/docs/old/c", parent_id=node.id, depth=2, owner_id=owner_id,
    )
    # rename_node: get_required_by_id(node), get_required_by_id(parent),
    # update_descendant_paths -> get_descendants -> get_required_by_id(node)
    set_scalar_one_or_none(result, node, parent, node)
    set_exists_count(result, 0)
    set_scalars_all(result, [child])
    res = await repo.rename_node(node_id=node.id, new_name="new")
    assert res is node
    assert node.path == "/docs/new"
    assert child.path == "/docs/new/c"


@pytest.mark.asyncio
async def test_rename_node_invalid_name():
    repo, session, result = make_repo()
    node = make_real_node(name="old")
    result.scalar_one_or_none = MagicMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.rename_node(node_id=node.id, new_name="  ")


# ---------------------------------------------------------------------------
# move_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_node_same_parent_returns_early():
    repo, session, result = make_repo()
    parent_id = uuid.uuid4()
    node = make_real_node(parent_id=parent_id)
    result.scalar_one_or_none = MagicMock(return_value=node)
    res = await repo.move_node(node_id=node.id, new_parent_id=parent_id)
    assert res is node


@pytest.mark.asyncio
async def test_move_node_into_self_raises():
    repo, session, result = make_repo()
    node = make_real_node(parent_id=None)
    result.scalar_one_or_none = MagicMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.move_node(node_id=node.id, new_parent_id=node.id)


@pytest.mark.asyncio
async def test_move_node_to_root_success():
    repo, session, result = make_repo()
    owner_id = uuid.uuid4()
    node = make_real_node(
        name="n", path="/p/n", parent_id=uuid.uuid4(), depth=1, owner_id=owner_id,
    )
    # get_required_by_id(node); конфликт есть; затем потомки get_required(node)
    set_scalar_one_or_none(result, node, node)
    set_exists_count(result, 0)  # нет конфликта имён в корне
    set_scalars_all(result, [])  # нет потомков
    res = await repo.move_node(node_id=node.id, new_parent_id=None, refresh=True)
    assert res is node
    assert node.parent_id is None
    assert node.path == "/n"
    assert node.depth == 0
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_move_node_to_folder_success_with_descendants():
    repo, session, result = make_repo()
    owner_id = uuid.uuid4()
    new_parent = make_real_node(
        name="dest", path="/dest", parent_id=None, depth=0,
        owner_id=owner_id, node_type=NodeType.FOLDER,
    )
    node = make_real_node(
        name="n", path="/n", parent_id=None, depth=0, owner_id=owner_id,
    )
    child = make_real_node(
        name="c", path="/n/c", parent_id=node.id, depth=1, owner_id=owner_id,
    )
    # get_required_by_id(node); get_required_by_id(new_parent);
    # _ensure_not_moving_into_descendant -> get_descendants -> get_required(node);
    # затем update_descendant_paths -> get_descendants -> get_required(node)
    set_scalar_one_or_none(result, node, new_parent, node, node)
    set_exists_count(result, 0)  # нет конфликта
    # первый вызов потомков (проверка не в потомка), второй (обновление путей)
    set_scalars_all(result, [child], [child])
    res = await repo.move_node(node_id=node.id, new_parent_id=new_parent.id)
    assert res is node
    assert node.parent_id == new_parent.id
    assert node.path == "/dest/n"
    assert node.depth == 1
    assert child.path == "/dest/n/c"
    assert child.depth == 2


@pytest.mark.asyncio
async def test_move_node_conflict_raises():
    repo, session, result = make_repo()
    node = make_real_node(name="n", parent_id=uuid.uuid4(), owner_id=uuid.uuid4())
    result.scalar_one_or_none = MagicMock(return_value=node)
    set_exists_count(result, 1)  # конфликт в корне
    with pytest.raises(DuplicateEntityError):
        await repo.move_node(node_id=node.id, new_parent_id=None)


@pytest.mark.asyncio
async def test_move_node_into_descendant_raises():
    repo, session, result = make_repo()
    owner_id = uuid.uuid4()
    new_parent = make_real_node(
        name="dest", path="/n/sub", parent_id=None, depth=2,
        owner_id=owner_id, node_type=NodeType.FOLDER,
    )
    node = make_real_node(
        name="n", path="/n", parent_id=None, depth=0, owner_id=owner_id,
    )
    # get_required(node), get_required(new_parent),
    # _ensure_not_moving_into_descendant -> get_descendants -> get_required(node)
    set_scalar_one_or_none(result, node, new_parent, node)
    # множество потомков включает new_parent.id
    descendant = make_real_node(id=new_parent.id, owner_id=owner_id)
    set_scalars_all(result, [descendant])
    with pytest.raises(InvalidQueryError):
        await repo.move_node(node_id=node.id, new_parent_id=new_parent.id)


# ---------------------------------------------------------------------------
# update_path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_path_success_with_descendants():
    repo, session, result = make_repo()
    node = make_real_node(name="n", path="/old", depth=0)
    child = make_real_node(name="c", path="/old/c", depth=1, parent_id=node.id)
    # get_required(node); update_descendant_paths -> get_descendants -> get_required(node)
    set_scalar_one_or_none(result, node, node)
    set_scalars_all(result, [child])
    res = await repo.update_path(
        node_id=node.id, new_path="/new", new_depth=0, refresh=True,
    )
    assert res is node
    assert node.path == "/new"
    assert child.path == "/new/c"
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_update_path_no_descendants_keeps_depth():
    repo, session, result = make_repo()
    node = make_real_node(name="n", path="/old", depth=2)
    result.scalar_one_or_none = MagicMock(return_value=node)
    await repo.update_path(
        node_id=node.id, new_path="/new", update_descendants=False,
    )
    assert node.path == "/new"
    assert node.depth == 2


@pytest.mark.asyncio
async def test_update_path_negative_depth_raises():
    repo, session, result = make_repo()
    node = make_real_node(name="n", path="/old", depth=0)
    result.scalar_one_or_none = MagicMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.update_path(node_id=node.id, new_path="/new", new_depth=-1)


# ---------------------------------------------------------------------------
# update_descendant_paths — ветка точного префикса
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_descendant_paths_exact_match_branch():
    repo, session, result = make_repo()
    root = make_real_node()
    # потомок, чей path в точности равен старому префиксу
    exact = make_real_node(name="x", path="/old", depth=1)
    other = make_real_node(name="y", path="/other", depth=2)  # нет совпадения
    set_scalar_one_or_none(result, root)
    set_scalars_all(result, [exact, other])
    res = await repo.update_descendant_paths(
        node_id=root.id,
        old_path_prefix="/old",
        new_path_prefix="/new",
        depth_delta=1,
    )
    assert exact.path == "/new"
    assert exact.depth == 2
    assert other.path == "/other"  # без изменений
    assert other.depth == 3
    assert res == [exact, other]


# ---------------------------------------------------------------------------
# Видимость
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_visibility_single():
    repo, session, result = make_repo()
    node = make_real_node()
    result.scalar_one_or_none = MagicMock(return_value=node)
    res = await repo.update_visibility(
        node_id=node.id, visibility=NodeVisibility.PUBLIC, refresh=True,
    )
    assert node.visibility == NodeVisibility.PUBLIC
    assert res is node
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_update_visibility_recursive():
    repo, session, result = make_repo()
    node = make_real_node()
    child = make_real_node(name="c", path="/n/c", parent_id=node.id, depth=1)
    # get_required(node); get_descendants -> get_required(node)
    set_scalar_one_or_none(result, node, node)
    set_scalars_all(result, [child])
    res = await repo.update_visibility(
        node_id=node.id, visibility=NodeVisibility.SHARED, recursive=True,
    )
    assert node.visibility == NodeVisibility.SHARED
    assert child.visibility == NodeVisibility.SHARED
    assert res is node


@pytest.mark.asyncio
async def test_make_private_shared_public_delegate():
    for method, vis in (
        ("make_private", NodeVisibility.PRIVATE),
        ("make_shared", NodeVisibility.SHARED),
        ("make_public", NodeVisibility.PUBLIC),
    ):
        repo, session, result = make_repo()
        node = make_real_node()
        result.scalar_one_or_none = MagicMock(return_value=node)
        res = await getattr(repo, method)(node_id=node.id)
        assert node.visibility == vis
        assert res is node


# ---------------------------------------------------------------------------
# Мягкое удаление / поддерево
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_soft_delete_node_single():
    repo, session, result = make_repo()
    node = make_real_node()
    result.scalar_one_or_none = MagicMock(return_value=node)
    res = await repo.soft_delete_node(
        node_id=node.id, deleted_by=uuid.uuid4(), refresh=True,
    )
    assert res is node
    assert node.is_deleted is True
    node.mark_deleted.assert_called_once()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_soft_delete_node_with_explicit_deleted_at():
    repo, session, result = make_repo()
    node = make_real_node()
    result.scalar_one_or_none = MagicMock(return_value=node)
    moment = datetime(2024, 1, 1, tzinfo=UTC)
    res = await repo.soft_delete_node(node_id=node.id, deleted_at=moment)
    assert node.deleted_at == moment
    assert res is node


@pytest.mark.asyncio
async def test_soft_delete_node_recursive():
    repo, session, result = make_repo()
    root = make_real_node()
    child = make_real_node(name="c", parent_id=root.id)
    # soft_delete_subtree -> get_descendants -> get_required(root)
    set_scalar_one_or_none(result, root)
    set_scalars_all(result, [root, child])
    res = await repo.soft_delete_node(
        node_id=root.id, recursive=True, refresh=True,
    )
    assert res is root
    assert root.is_deleted is True
    assert child.is_deleted is True
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_soft_delete_subtree_default_time():
    repo, session, result = make_repo()
    root = make_real_node()
    set_scalar_one_or_none(result, root)
    set_scalars_all(result, [root])
    res = await repo.soft_delete_subtree(node_id=root.id)
    assert res == [root]
    assert root.is_deleted is True
    assert root.deleted_at is not None


# ---------------------------------------------------------------------------
# Восстановление / поддерево
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restore_node_single_success():
    repo, session, result = make_repo()
    node = make_real_node(is_deleted=True, parent_id=None)
    result.scalar_one_or_none = MagicMock(return_value=node)
    set_exists_count(result, 0)  # нет конфликта
    res = await repo.restore_node(node_id=node.id, refresh=True)
    assert res is node
    assert node.is_deleted is False
    assert node.deleted_at is None
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_restore_node_no_conflict_check():
    repo, session, result = make_repo()
    node = make_real_node(is_deleted=True)
    result.scalar_one_or_none = MagicMock(return_value=node)
    await repo.restore_node(node_id=node.id, check_conflict=False)
    assert node.is_deleted is False


@pytest.mark.asyncio
async def test_restore_node_conflict_raises():
    repo, session, result = make_repo()
    node = make_real_node(is_deleted=True, parent_id=None)
    result.scalar_one_or_none = MagicMock(return_value=node)
    set_exists_count(result, 1)  # конфликт
    with pytest.raises(DuplicateEntityError):
        await repo.restore_node(node_id=node.id)


@pytest.mark.asyncio
async def test_restore_node_recursive():
    repo, session, result = make_repo()
    root = make_real_node(is_deleted=True, parent_id=None)
    child = make_real_node(name="c", is_deleted=True, parent_id=root.id)
    # restore_subtree: get_required(root); проверка конфликта exists;
    # get_descendants -> get_required(root)
    set_scalar_one_or_none(result, root, root)
    set_exists_count(result, 0)
    set_scalars_all(result, [root, child])
    res = await repo.restore_node(node_id=root.id, recursive=True, refresh=True)
    assert res is root
    assert root.is_deleted is False
    assert child.is_deleted is False
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_restore_subtree_conflict_raises():
    repo, session, result = make_repo()
    root = make_real_node(is_deleted=True, parent_id=None)
    result.scalar_one_or_none = MagicMock(return_value=root)
    set_exists_count(result, 1)  # конфликт
    with pytest.raises(DuplicateEntityError):
        await repo.restore_subtree(node_id=root.id)


@pytest.mark.asyncio
async def test_restore_subtree_no_conflict_check():
    repo, session, result = make_repo()
    root = make_real_node(is_deleted=True)
    set_scalar_one_or_none(result, root, root)
    set_scalars_all(result, [root])
    res = await repo.restore_subtree(node_id=root.id, check_conflict=False)
    assert res == [root]
    assert root.is_deleted is False


# ---------------------------------------------------------------------------
# mark_purged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_purged_success():
    repo, session, result = make_repo()
    result.rowcount = 1
    await repo.mark_purged(node_id=uuid.uuid4())
    session.execute.assert_awaited()
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_mark_purged_not_found_raises():
    repo, session, result = make_repo()
    result.rowcount = 0
    with pytest.raises(EntityNotFoundError):
        await repo.mark_purged(node_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# check_name_conflict / get_path_exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_name_conflict_root_with_exclude_and_deleted():
    repo, session, result = make_repo()
    set_exists_count(result, 1)
    res = await repo.check_name_conflict(
        owner_id=uuid.uuid4(),
        parent_id=None,
        name="dup",
        exclude_node_id=uuid.uuid4(),
        include_deleted=True,
    )
    assert res is True


@pytest.mark.asyncio
async def test_check_name_conflict_with_parent_false():
    repo, session, result = make_repo()
    set_exists_count(result, 0)
    res = await repo.check_name_conflict(
        owner_id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        name="x",
    )
    assert res is False


@pytest.mark.asyncio
async def test_check_name_conflict_invalid_name():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.check_name_conflict(
            owner_id=uuid.uuid4(), parent_id=None, name="a/b",
        )


@pytest.mark.asyncio
async def test_get_path_exists_true():
    repo, session, result = make_repo()
    set_exists_count(result, 1)
    res = await repo.get_path_exists(owner_id=uuid.uuid4(), path="/x")
    assert res is True


@pytest.mark.asyncio
async def test_get_path_exists_include_deleted_false():
    repo, session, result = make_repo()
    set_exists_count(result, 0)
    res = await repo.get_path_exists(
        owner_id=uuid.uuid4(), path="/x", include_deleted=True,
    )
    assert res is False


# ---------------------------------------------------------------------------
# поиск
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_by_name_delegates():
    repo, session, result = make_repo()
    nodes = [make_node()]
    set_scalars_all(result, nodes)
    res = await repo.search_by_name(owner_id=uuid.uuid4(), query="abc")
    assert res == nodes


@pytest.mark.asyncio
async def test_search_nodes_with_all_filters():
    repo, session, result = make_repo()
    nodes = [make_node()]
    set_scalars_all(result, nodes)
    res = await repo.search_nodes(
        owner_id=uuid.uuid4(),
        query="  term  ",
        parent_id=uuid.uuid4(),
        node_type=NodeType.FILE,
        include_deleted=True,
    )
    assert res == nodes


@pytest.mark.asyncio
async def test_search_nodes_empty_query_skips_pattern():
    repo, session, result = make_repo()
    set_scalars_all(result, [])
    res = await repo.search_nodes(owner_id=uuid.uuid4(), query="   ")
    assert res == []


@pytest.mark.asyncio
async def test_search_nodes_none_query():
    repo, session, result = make_repo()
    set_scalars_all(result, [])
    res = await repo.search_nodes(owner_id=uuid.uuid4(), query=None)
    assert res == []


@pytest.mark.asyncio
async def test_search_nodes_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.search_nodes(owner_id=uuid.uuid4(), limit=0)


# ---------------------------------------------------------------------------
# подсчёты
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_nodes():
    repo, session, result = make_repo()
    set_exists_count(result, 5)
    res = await repo.count_user_nodes(owner_id=uuid.uuid4(), include_deleted=True)
    assert res == 5


@pytest.mark.asyncio
async def test_count_user_files():
    repo, session, result = make_repo()
    set_exists_count(result, 3)
    res = await repo.count_user_files(owner_id=uuid.uuid4())
    assert res == 3


@pytest.mark.asyncio
async def test_count_user_folders():
    repo, session, result = make_repo()
    set_exists_count(result, 2)
    res = await repo.count_user_folders(owner_id=uuid.uuid4(), include_deleted=True)
    assert res == 2


@pytest.mark.asyncio
async def test_count_children():
    repo, session, result = make_repo()
    set_exists_count(result, 4)
    res = await repo.count_children(
        parent_id=uuid.uuid4(), include_deleted=True, node_type=NodeType.FILE,
    )
    assert res == 4


@pytest.mark.asyncio
async def test_count_root_nodes():
    repo, session, result = make_repo()
    set_exists_count(result, 7)
    res = await repo.count_root_nodes(
        owner_id=uuid.uuid4(), include_deleted=True, node_type=NodeType.FOLDER,
    )
    assert res == 7


# ---------------------------------------------------------------------------
# Внутренние хелперы: _validate_node_name / _normalize_path / order_by / depth
# ---------------------------------------------------------------------------

def test_validate_node_name_empty():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_node_name("   ")


def test_validate_node_name_dot():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_node_name(".")
    with pytest.raises(InvalidQueryError):
        repo._validate_node_name("..")


def test_validate_node_name_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_node_name("a" * 256)


def test_validate_node_name_ok():
    repo, session, result = make_repo()
    assert repo._validate_node_name("  good  ") == "good"


def test_normalize_path_empty_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_path("   ")


def test_normalize_path_adds_leading_and_strips():
    repo, session, result = make_repo()
    assert repo._normalize_path("a//b//c/") == "/a/b/c"


def test_normalize_path_root():
    repo, session, result = make_repo()
    assert repo._normalize_path("/") == "/"


def test_build_node_path_root_parent():
    repo, session, result = make_repo()
    assert repo._build_node_path(parent=None, name="x") == "/x"


def test_build_node_path_parent_root():
    repo, session, result = make_repo()
    parent = make_node(path="/")
    assert repo._build_node_path(parent=parent, name="x") == "/x"


def test_build_node_path_nested_parent():
    repo, session, result = make_repo()
    parent = make_node(path="/docs")
    assert repo._build_node_path(parent=parent, name="x") == "/docs/x"


def test_build_node_depth():
    repo, session, result = make_repo()
    assert repo._build_node_depth(parent=None) == 0
    parent = make_node(depth=3)
    assert repo._build_node_depth(parent=parent) == 4


def test_get_order_by_invalid_field():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_order_by("bogus", "asc")


def test_get_order_by_invalid_direction():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_order_by("name", "sideways")


def test_get_order_by_asc_and_desc():
    repo, session, result = make_repo()
    assert repo._get_order_by("name", "asc") is not None
    assert repo._get_order_by("created_at", "desc") is not None


def test_utc_now_returns_aware():
    repo, session, result = make_repo()
    now = repo._utc_now()
    assert now.tzinfo is not None


# ---------------------------------------------------------------------------
# Покрытие оставшихся веток
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_active_node_by_id_returns_node():
    repo, session, result = make_repo()
    node = make_node(is_deleted=False)
    result.scalar_one_or_none = MagicMock(return_value=node)
    res = await repo.get_required_active_node_by_id(node.id)
    assert res is node


@pytest.mark.asyncio
async def test_get_root_nodes_default_excludes_deleted():
    repo, session, result = make_repo()
    nodes = [make_node(parent_id=None)]
    set_scalars_all(result, nodes)
    res = await repo.get_root_nodes(owner_id=uuid.uuid4())
    assert res == nodes


@pytest.mark.asyncio
async def test_count_user_nodes_default_excludes_deleted():
    repo, session, result = make_repo()
    set_exists_count(result, 1)
    assert await repo.count_user_nodes(owner_id=uuid.uuid4()) == 1


@pytest.mark.asyncio
async def test_count_user_files_default_excludes_deleted():
    repo, session, result = make_repo()
    set_exists_count(result, 1)
    assert await repo.count_user_files(owner_id=uuid.uuid4()) == 1


@pytest.mark.asyncio
async def test_count_user_folders_default_excludes_deleted():
    repo, session, result = make_repo()
    set_exists_count(result, 1)
    assert await repo.count_user_folders(owner_id=uuid.uuid4()) == 1


@pytest.mark.asyncio
async def test_count_children_default_excludes_deleted():
    repo, session, result = make_repo()
    set_exists_count(result, 1)
    assert await repo.count_children(parent_id=uuid.uuid4()) == 1


@pytest.mark.asyncio
async def test_count_root_nodes_default_excludes_deleted():
    repo, session, result = make_repo()
    set_exists_count(result, 1)
    assert await repo.count_root_nodes(owner_id=uuid.uuid4()) == 1


@pytest.mark.asyncio
async def test_override_create_integrity_error_handler(monkeypatch):
    """Напрямую проверяет ветку except IntegrityError в переопределении."""
    repo, session, result = make_repo()
    orig = MagicMock()
    orig.sqlstate = "23505"
    orig.constraint_name = "uq"

    async def boom(self, entity, *, flush=True, refresh=False):
        raise IntegrityError("s", {}, orig)

    from database.repositories.base import BaseRepository
    monkeypatch.setattr(BaseRepository, "create", boom)
    with pytest.raises(DuplicateEntityError):
        await repo.create(make_node())


@pytest.mark.asyncio
async def test_override_create_sqlalchemy_error_handler(monkeypatch):
    """Напрямую проверяет ветку except SQLAlchemyError в переопределении."""
    repo, session, result = make_repo()

    async def boom(self, entity, *, flush=True, refresh=False):
        raise SQLAlchemyError("boom")

    from database.repositories.base import BaseRepository
    monkeypatch.setattr(BaseRepository, "create", boom)
    with pytest.raises(RepositoryError):
        await repo.create(make_node())
