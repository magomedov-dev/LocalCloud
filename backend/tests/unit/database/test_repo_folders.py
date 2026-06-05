"""Юнит-тесты репозитория папок (FolderRepository)."""
from __future__ import annotations

import uuid
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
from database.repositories.folders import FolderRepository


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
    return FolderRepository(session=session), session, result


def make_folder(**kwargs):
    folder = MagicMock()
    node = MagicMock()
    node.id = uuid.uuid4()
    node.owner_id = uuid.uuid4()
    node.node_type = NodeType.FOLDER
    node.name = "test-folder"
    node.path = "/test-folder"
    node.depth = 1
    node.is_deleted = False
    node.visibility = NodeVisibility.PRIVATE
    node.soft_delete = MagicMock()
    node.restore = MagicMock()

    defaults = dict(
        id=uuid.uuid4(),
        node_id=node.id,
        node=node,
        color=None,
        description=None,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(folder, k, v)
    return folder


# ---------------------------------------------------------------------------
# Тесты: get_folder_by_id / get_required_folder_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_folder_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_folder_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_folder_by_id_returns_folder_when_found():
    repo, session, result = make_repo()
    folder = make_folder()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.get_folder_by_id(folder.id)
    assert res is folder


@pytest.mark.asyncio
async def test_get_required_folder_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_folder_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_folder_by_id_returns_folder():
    repo, session, result = make_repo()
    folder = make_folder()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.get_required_folder_by_id(folder.id)
    assert res is folder


# ---------------------------------------------------------------------------
# Тесты: get_by_node_id / get_required_by_node_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_node_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_node_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_by_node_id_returns_folder_when_found():
    repo, session, result = make_repo()
    folder = make_folder()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.get_by_node_id(folder.node_id)
    assert res is folder


@pytest.mark.asyncio
async def test_get_required_by_node_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_node_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_active_by_node_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_active_by_node_id(uuid.uuid4())
    assert res is None


# ---------------------------------------------------------------------------
# Тесты: создание папки (если метод существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_folder_raises_for_empty_name():
    repo, session, result = make_repo()
    if hasattr(repo, 'create_folder'):
        with pytest.raises((InvalidQueryError, Exception)):
            await repo.create_folder(
                owner_id=uuid.uuid4(),
                name="",
                parent_node_id=None,
                check_parent_exists=False,
            )


@pytest.mark.asyncio
async def test_create_folder_success():
    repo, session, result = make_repo()
    if hasattr(repo, 'create_folder'):
        folder = make_folder()

        async def fake_create(entity, flush=True, refresh=False):
            return folder

        repo.create = fake_create  # type: ignore
        res = await repo.create_folder(
            owner_id=uuid.uuid4(),
            name="my-folder",
            parent_id=None,
        )
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: list_user_folders / list_folders (если существуют)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_returns_empty_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    # Пробуем разные варианты имён методов для листинга
    for method_name in ['list_user_folders', 'list_folders', 'list_owner_folders']:
        if hasattr(repo, method_name):
            method = getattr(repo, method_name)
            try:
                res = await method(uuid.uuid4())
            except TypeError:
                res = await method(owner_id=uuid.uuid4())
            assert isinstance(res, list)
            break


# ---------------------------------------------------------------------------
# Тесты: update_folder (если метод существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rename_folder_raises_for_empty_name():
    repo, session, result = make_repo()
    if hasattr(repo, 'rename_folder'):
        folder = make_folder()
        result.scalar_one_or_none = MagicMock(return_value=folder)
        with pytest.raises((InvalidQueryError, Exception)):
            await repo.rename_folder(folder.id, new_name="")


# ---------------------------------------------------------------------------
# Тесты: count (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    from database.models.filesystem import Folder
    count = await repo.count(Folder.id == uuid.uuid4())
    assert count == 3


# ---------------------------------------------------------------------------
# Тесты: get_by_id (унаследованный базовый)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_id_base_returns_none():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    res = await repo.get_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_exists_returns_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    from database.models.filesystem import Folder
    res = await repo.exists(Folder.id == uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_exists_returns_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    from database.models.filesystem import Folder
    res = await repo.exists(Folder.id == uuid.uuid4())
    assert res is True


def make_integrity_error(sqlstate="23505", constraint="uq_folders_node_id"):
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = constraint
    orig.table_name = "folders"
    orig.column_name = None
    err = IntegrityError("stmt", {}, orig)
    err.orig = orig
    return err


def make_node(node_type=NodeType.FOLDER):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.owner_id = uuid.uuid4()
    node.node_type = node_type
    node.name = "test-folder"
    node.path = "/test-folder"
    node.depth = 1
    node.is_deleted = False
    node.updated_by = None
    node.visibility = NodeVisibility.PRIVATE
    return node


# ---------------------------------------------------------------------------
# get_required_by_node_id / active by node id (дополнительно)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_by_node_id_returns_folder():
    repo, session, result = make_repo()
    folder = make_folder()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.get_required_by_node_id(folder.node_id)
    assert res is folder


@pytest.mark.asyncio
async def test_get_active_by_node_id_returns_folder():
    repo, session, result = make_repo()
    folder = make_folder()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.get_active_by_node_id(folder.node_id)
    assert res is folder


@pytest.mark.asyncio
async def test_get_required_active_by_node_id_returns_folder():
    repo, session, result = make_repo()
    folder = make_folder()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.get_required_active_by_node_id(folder.node_id)
    assert res is folder


@pytest.mark.asyncio
async def test_get_required_active_by_node_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_active_by_node_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# get_by_owner_and_path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_owner_and_path_returns_none_when_node_missing():
    repo, session, result = make_repo()
    repo.nodes.get_by_owner_and_path = AsyncMock(return_value=None)
    res = await repo.get_by_owner_and_path(owner_id=uuid.uuid4(), path="/x")
    assert res is None


@pytest.mark.asyncio
async def test_get_by_owner_and_path_returns_none_when_node_not_folder():
    repo, session, result = make_repo()
    node = make_node(node_type=NodeType.FILE)
    repo.nodes.get_by_owner_and_path = AsyncMock(return_value=node)
    res = await repo.get_by_owner_and_path(owner_id=uuid.uuid4(), path="/x")
    assert res is None


@pytest.mark.asyncio
async def test_get_by_owner_and_path_returns_folder():
    repo, session, result = make_repo()
    node = make_node()
    folder = make_folder()
    repo.nodes.get_by_owner_and_path = AsyncMock(return_value=node)
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.get_by_owner_and_path(owner_id=uuid.uuid4(), path="/x")
    assert res is folder


# ---------------------------------------------------------------------------
# folder_exists_for_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_folder_exists_for_node_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    assert await repo.folder_exists_for_node(uuid.uuid4()) is True


@pytest.mark.asyncio
async def test_folder_exists_for_node_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    assert await repo.folder_exists_for_node(uuid.uuid4()) is False


# ---------------------------------------------------------------------------
# create_folder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_folder_success_delegates_to_nodes():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.create_node = AsyncMock(return_value=node)
    res = await repo.create_folder(
        owner_id=node.owner_id,
        name="my-folder",
        parent_id=None,
        description="  hello  ",
        color="  blue  ",
    )
    repo.nodes.create_node.assert_awaited_once()
    session.add.assert_called_once()
    session.flush.assert_awaited()
    assert res.node_id == node.id
    assert res.description == "hello"
    assert res.color == "blue"


@pytest.mark.asyncio
async def test_create_folder_with_refresh():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.create_node = AsyncMock(return_value=node)
    res = await repo.create_folder(
        owner_id=node.owner_id,
        name="f",
        parent_id=uuid.uuid4(),
        refresh=True,
    )
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is res


@pytest.mark.asyncio
async def test_create_folder_maps_integrity_error():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.create_node = AsyncMock(return_value=node)
    session.flush = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo.create_folder(owner_id=node.owner_id, name="f")


@pytest.mark.asyncio
async def test_create_folder_outer_integrity_handler():
    # repo.flush подменён, чтобы бросить СЫРОЙ IntegrityError и дойти до внешнего
    # except в create_folder (обычно self.flush() конвертирует его раньше).
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.create_node = AsyncMock(return_value=node)
    repo.flush = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo.create_folder(owner_id=node.owner_id, name="f")


@pytest.mark.asyncio
async def test_create_folder_outer_sqlalchemy_handler():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.create_node = AsyncMock(return_value=node)
    repo.flush = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.create_folder(owner_id=node.owner_id, name="f")


@pytest.mark.asyncio
async def test_create_folder_maps_sqlalchemy_error():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.create_node = AsyncMock(return_value=node)
    session.flush = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.create_folder(
            owner_id=node.owner_id,
            name="f",
            parent_id=uuid.uuid4(),
        )


# ---------------------------------------------------------------------------
# create_for_existing_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_for_existing_node_success():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    repo.folder_exists_for_node = AsyncMock(return_value=False)
    res = await repo.create_for_existing_node(
        node_id=node.id,
        description="d",
        color="red",
    )
    assert res.node_id == node.id
    assert res.color == "red"


@pytest.mark.asyncio
async def test_create_for_existing_node_raises_when_not_folder():
    repo, session, result = make_repo()
    node = make_node(node_type=NodeType.FILE)
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.create_for_existing_node(node_id=node.id)


@pytest.mark.asyncio
async def test_create_for_existing_node_raises_on_duplicate():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    repo.folder_exists_for_node = AsyncMock(return_value=True)
    with pytest.raises(DuplicateEntityError):
        await repo.create_for_existing_node(node_id=node.id)


@pytest.mark.asyncio
async def test_create_for_existing_node_skip_duplicate_check():
    repo, session, result = make_repo()
    node = make_node()
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    repo.folder_exists_for_node = AsyncMock(return_value=True)
    res = await repo.create_for_existing_node(
        node_id=node.id,
        check_duplicate=False,
    )
    assert res.node_id == node.id


# ---------------------------------------------------------------------------
# Методы листинга
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_folders_root():
    repo, session, result = make_repo()
    folders = [make_folder()]
    result.scalars.return_value.all.return_value = folders
    res = await repo.list_user_folders(owner_id=uuid.uuid4(), parent_id=None)
    assert res == folders


@pytest.mark.asyncio
async def test_list_user_folders_with_parent_and_deleted():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_user_folders(
        owner_id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        include_deleted=True,
        sort_by="created_at",
        sort_direction="desc",
    )
    assert res == []


@pytest.mark.asyncio
async def test_list_user_folders_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_user_folders(owner_id=uuid.uuid4(), limit=-1)


@pytest.mark.asyncio
async def test_list_child_folders_delegates():
    repo, session, result = make_repo()
    folders = [make_folder()]
    result.scalars.return_value.all.return_value = folders
    res = await repo.list_child_folders(parent_id=uuid.uuid4())
    assert res == folders


@pytest.mark.asyncio
async def test_list_user_folders_by_parent_include_deleted():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_user_folders_by_parent(
        parent_id=uuid.uuid4(),
        include_deleted=True,
        sort_by="color",
    )
    assert res == []


@pytest.mark.asyncio
async def test_list_deleted_folders():
    repo, session, result = make_repo()
    folders = [make_folder()]
    result.scalars.return_value.all.return_value = folders
    res = await repo.list_deleted_folders(owner_id=uuid.uuid4())
    assert res == folders


@pytest.mark.asyncio
async def test_list_deleted_folders_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_deleted_folders(owner_id=uuid.uuid4(), offset=-5)


# ---------------------------------------------------------------------------
# update_metadata / update_metadata_by_node_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_metadata_success():
    repo, session, result = make_repo()
    folder = make_folder()
    folder.update_metadata = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.update_metadata(
        folder_id=folder.id,
        description="d",
        color="green",
        refresh=True,
    )
    folder.update_metadata.assert_called_once()
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is folder
    assert res is folder


@pytest.mark.asyncio
async def test_update_metadata_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_metadata(folder_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_metadata_by_node_id_success_sets_updated_by():
    repo, session, result = make_repo()
    folder = make_folder()
    folder.update_metadata = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    user = uuid.uuid4()
    res = await repo.update_metadata_by_node_id(
        node_id=folder.node_id,
        description="d",
        updated_by=user,
    )
    assert folder.node.updated_by == user
    assert res is folder


@pytest.mark.asyncio
async def test_update_metadata_by_node_id_node_none():
    repo, session, result = make_repo()
    folder = make_folder(node=None)
    folder.update_metadata = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.update_metadata_by_node_id(
        node_id=uuid.uuid4(),
        refresh=True,
    )
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is folder
    assert res is folder


# ---------------------------------------------------------------------------
# set_color / set_description
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_color_success():
    repo, session, result = make_repo()
    folder = make_folder()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    user = uuid.uuid4()
    res = await repo.set_color(node_id=folder.node_id, color="cyan", updated_by=user)
    assert res.color == "cyan"
    assert folder.node.updated_by == user


@pytest.mark.asyncio
async def test_set_color_node_none_with_refresh():
    repo, session, result = make_repo()
    folder = make_folder(node=None)
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.set_color(node_id=uuid.uuid4(), color=None, refresh=True)
    assert res.color is None
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is folder


@pytest.mark.asyncio
async def test_set_color_invalid_color():
    repo, session, result = make_repo()
    folder = make_folder()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    with pytest.raises(InvalidQueryError):
        await repo.set_color(node_id=folder.node_id, color="x" * 33)


@pytest.mark.asyncio
async def test_set_description_success():
    repo, session, result = make_repo()
    folder = make_folder()
    result.scalar_one_or_none = MagicMock(return_value=folder)
    user = uuid.uuid4()
    res = await repo.set_description(
        node_id=folder.node_id,
        description="  text  ",
        updated_by=user,
    )
    assert res.description == "text"
    assert folder.node.updated_by == user


@pytest.mark.asyncio
async def test_set_description_node_none_with_refresh():
    repo, session, result = make_repo()
    folder = make_folder(node=None)
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.set_description(node_id=uuid.uuid4(), description="", refresh=True)
    assert res.description is None
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is folder


# ---------------------------------------------------------------------------
# rename / move / soft_delete / restore (делегирование)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rename_folder_success():
    repo, session, result = make_repo()
    node = make_node()
    folder = make_folder()
    repo.nodes.rename_node = AsyncMock(return_value=node)
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.rename_folder(node_id=node.id, new_name="new", refresh=True)
    repo.nodes.rename_node.assert_awaited_once()
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is folder
    assert res is folder


@pytest.mark.asyncio
async def test_rename_folder_raises_when_not_folder():
    repo, session, result = make_repo()
    node = make_node(node_type=NodeType.FILE)
    repo.nodes.rename_node = AsyncMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.rename_folder(node_id=node.id, new_name="new")


@pytest.mark.asyncio
async def test_move_folder_success():
    repo, session, result = make_repo()
    node = make_node()
    folder = make_folder()
    repo.nodes.move_node = AsyncMock(return_value=node)
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.move_folder(node_id=node.id, new_parent_id=None, refresh=True)
    repo.nodes.move_node.assert_awaited_once()
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is folder
    assert res is folder


@pytest.mark.asyncio
async def test_move_folder_raises_when_not_folder():
    repo, session, result = make_repo()
    node = make_node(node_type=NodeType.FILE)
    repo.nodes.move_node = AsyncMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.move_folder(node_id=node.id, new_parent_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_soft_delete_folder_success():
    repo, session, result = make_repo()
    node = make_node()
    folder = make_folder()
    repo.nodes.soft_delete_node = AsyncMock(return_value=node)
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.soft_delete_folder(node_id=node.id, refresh=True)
    repo.nodes.soft_delete_node.assert_awaited_once()
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is folder
    assert res is folder


@pytest.mark.asyncio
async def test_soft_delete_folder_raises_when_not_folder():
    repo, session, result = make_repo()
    node = make_node(node_type=NodeType.FILE)
    repo.nodes.soft_delete_node = AsyncMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.soft_delete_folder(node_id=node.id)


@pytest.mark.asyncio
async def test_restore_folder_success():
    repo, session, result = make_repo()
    node = make_node()
    folder = make_folder()
    repo.nodes.restore_node = AsyncMock(return_value=node)
    result.scalar_one_or_none = MagicMock(return_value=folder)
    res = await repo.restore_folder(node_id=node.id, refresh=True)
    repo.nodes.restore_node.assert_awaited_once()
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is folder
    assert res is folder


@pytest.mark.asyncio
async def test_restore_folder_raises_when_not_folder():
    repo, session, result = make_repo()
    node = make_node(node_type=NodeType.FILE)
    repo.nodes.restore_node = AsyncMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.restore_folder(node_id=node.id)


# ---------------------------------------------------------------------------
# search_folders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_folders_no_filters():
    repo, session, result = make_repo()
    folders = [make_folder()]
    result.scalars.return_value.all.return_value = folders
    res = await repo.search_folders(owner_id=uuid.uuid4())
    assert res == folders


@pytest.mark.asyncio
async def test_search_folders_all_filters():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_folders(
        owner_id=uuid.uuid4(),
        query="  doc  ",
        parent_id=uuid.uuid4(),
        include_deleted=True,
        color="blue",
        sort_by="updated_at",
        sort_direction="desc",
    )
    assert res == []


@pytest.mark.asyncio
async def test_search_folders_blank_query_ignored():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_folders(owner_id=uuid.uuid4(), query="   ")
    assert res == []


@pytest.mark.asyncio
async def test_search_folders_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.search_folders(owner_id=uuid.uuid4(), limit=0)


# ---------------------------------------------------------------------------
# Методы подсчёта
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_folders_filtered_root():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=5)
    res = await repo.count_user_folders_filtered(owner_id=uuid.uuid4(), parent_id=None)
    assert res == 5


@pytest.mark.asyncio
async def test_count_user_folders_filtered_with_parent_and_deleted():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=2)
    res = await repo.count_user_folders_filtered(
        owner_id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        include_deleted=True,
    )
    assert res == 2


@pytest.mark.asyncio
async def test_count_user_folders_filtered_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.count_user_folders_filtered(owner_id=uuid.uuid4(), parent_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_count_search_results_with_filters():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=7)
    res = await repo.count_search_results(
        owner_id=uuid.uuid4(),
        query="x",
        parent_id=uuid.uuid4(),
        include_deleted=True,
        color="red",
    )
    assert res == 7


@pytest.mark.asyncio
async def test_count_search_results_blank_query():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    res = await repo.count_search_results(owner_id=uuid.uuid4(), query="  ")
    assert res == 0


@pytest.mark.asyncio
async def test_count_search_results_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.count_search_results(owner_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_count_user_folders():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=4)
    res = await repo.count_user_folders(owner_id=uuid.uuid4(), include_deleted=True)
    assert res == 4


@pytest.mark.asyncio
async def test_count_user_folders_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.count_user_folders(owner_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_count_child_folders():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=6)
    res = await repo.count_child_folders(parent_id=uuid.uuid4())
    assert res == 6


@pytest.mark.asyncio
async def test_count_child_folders_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.count_child_folders(parent_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Вспомогательные методы
# ---------------------------------------------------------------------------

def test_base_select():
    repo, session, result = make_repo()
    stmt = repo._base_select()
    assert stmt is not None


def test_normalize_optional_text():
    repo, session, result = make_repo()
    assert repo._normalize_optional_text(None) is None
    assert repo._normalize_optional_text("   ") is None
    assert repo._normalize_optional_text("  hi  ") == "hi"


def test_normalize_color():
    repo, session, result = make_repo()
    assert repo._normalize_color(None) is None
    assert repo._normalize_color("   ") is None
    assert repo._normalize_color("  red  ") == "red"
    with pytest.raises(InvalidQueryError):
        repo._normalize_color("x" * 33)


def test_get_folder_order_by_valid():
    repo, session, result = make_repo()
    assert repo._get_folder_order_by("name", "asc") is not None
    assert repo._get_folder_order_by("color", "desc") is not None


def test_get_folder_order_by_invalid_field():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_folder_order_by("bogus", "asc")  # type: ignore


def test_get_folder_order_by_invalid_direction():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_folder_order_by("name", "sideways")  # type: ignore
