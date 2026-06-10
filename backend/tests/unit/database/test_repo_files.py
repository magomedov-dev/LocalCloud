"""Модульные тесты репозитория FileRepository: получение, создание и обновление
файлов, работа с хранилищем, поиск, подсчёты и нормализация входных данных."""
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
from database.models.enums import (
    FilePreviewStatus,
    FileProcessingStatus,
    NodeType,
    NodeVisibility,
    StorageObjectStatus,
)
from database.repositories.files import FileRepository


# ---------------------------------------------------------------------------
# Helpers
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
    return FileRepository(session=session), session, result


def make_file(**kwargs):
    file_obj = MagicMock()
    node = MagicMock()
    node.id = uuid.uuid4()
    node.owner_id = uuid.uuid4()
    node.node_type = NodeType.FILE
    node.name = "test.txt"
    node.path = "/test.txt"
    node.depth = 1
    node.is_deleted = False
    node.visibility = NodeVisibility.PRIVATE

    defaults = dict(
        id=uuid.uuid4(),
        node_id=node.id,
        node=node,
        storage_bucket="my-bucket",
        storage_key="files/test.txt",
        size_bytes=1024,
        mime_type="text/plain",
        extension="txt",
        checksum=None,
        checksum_algorithm=None,
        storage_status=StorageObjectStatus.AVAILABLE,
        processing_status=FileProcessingStatus.PENDING,
        preview_status=FilePreviewStatus.NOT_REQUIRED,
        preview_storage_key=None,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(file_obj, k, v)
    return file_obj


# ---------------------------------------------------------------------------
# Tests: get_by_id / get_required_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_by_id_returns_file_when_found():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.get_by_id(file_obj.id)
    assert res is file_obj


@pytest.mark.asyncio
async def test_get_required_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_by_id_returns_file():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.get_required_by_id(file_obj.id)
    assert res is file_obj


# ---------------------------------------------------------------------------
# Tests: get_by_node_id / get_required_by_node_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_node_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_node_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_by_node_id_returns_file_when_found():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.get_by_node_id(file_obj.node_id)
    assert res is file_obj


@pytest.mark.asyncio
async def test_get_required_by_node_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_node_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Tests: get_by_storage_key (if exists)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_storage_key_returns_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'get_by_storage_key'):
        res = await repo.get_by_storage_key(
            storage_bucket="bucket",
            storage_key="key/file.txt",
        )
        assert res is None


# ---------------------------------------------------------------------------
# Тесты: create_file (если метод есть в репозитории)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_file_raises_for_empty_storage_key():
    repo, session, result = make_repo()
    if hasattr(repo, 'create_file'):
        with pytest.raises((InvalidQueryError, Exception)):
            await repo.create_file(
                node_id=uuid.uuid4(),
                storage_bucket="bucket",
                storage_key="",
                size_bytes=1024,
            )


# ---------------------------------------------------------------------------
# Tests: list files (if methods exist)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_owner_files_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    for method_name in ['list_owner_files', 'list_user_files', 'list_files']:
        if hasattr(repo, method_name):
            method = getattr(repo, method_name)
            try:
                res = await method(uuid.uuid4())
            except TypeError:
                res = await method(owner_id=uuid.uuid4())
            assert isinstance(res, list)
            break


# ---------------------------------------------------------------------------
# Tests: count (inherited base)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=7)
    from database.models.filesystem import File
    count = await repo.count(File.id == uuid.uuid4())
    assert count == 7


# ---------------------------------------------------------------------------
# Tests: exists (inherited base)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exists_returns_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    from database.models.filesystem import File
    res = await repo.exists(File.id == uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_exists_returns_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    from database.models.filesystem import File
    res = await repo.exists(File.id == uuid.uuid4())
    assert res is True


# ---------------------------------------------------------------------------
# Tests: update file fields (if methods exist)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_processing_status_success():
    repo, session, result = make_repo()
    if hasattr(repo, 'update_processing_status'):
        file_obj = make_file()
        result.scalar_one_or_none = MagicMock(return_value=file_obj)
        res = await repo.update_processing_status(
            file_id=file_obj.id, processing_status=FileProcessingStatus.READY
        )
        assert res is file_obj


# ---------------------------------------------------------------------------
# Tests: search files (if method exists)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_files_returns_list():
    repo, session, result = make_repo()
    if hasattr(repo, 'search_files'):
        result.scalars.return_value.all.return_value = []
        res = await repo.search_files(owner_id=uuid.uuid4(), query="test")
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Tests: nodes sub-repo is accessible
# ---------------------------------------------------------------------------

def test_nodes_sub_repo_accessible():
    repo, session, result = make_repo()
    assert hasattr(repo, 'nodes')
    from database.repositories.nodes import FileSystemNodeRepository
    assert isinstance(repo.nodes, FileSystemNodeRepository)


# ---------------------------------------------------------------------------
# Helpers for error mapping
# ---------------------------------------------------------------------------

def make_integrity_error(sqlstate="23505", constraint="uq_files_storage_key"):
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = constraint
    orig.table_name = "files"
    orig.column_name = None
    err = IntegrityError("stmt", {}, orig)
    err.orig = orig
    return err


# ---------------------------------------------------------------------------
# get_required_by_node_id / active by node id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_by_node_id_returns_file():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.get_required_by_node_id(file_obj.node_id)
    assert res is file_obj


@pytest.mark.asyncio
async def test_get_by_node_id_excludes_deleted():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.get_by_node_id(file_obj.node_id, include_deleted_node=False)
    assert res is file_obj
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_get_active_by_node_id_returns_file():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.get_active_by_node_id(file_obj.node_id)
    assert res is file_obj


@pytest.mark.asyncio
async def test_get_required_active_by_node_id_raises_when_missing():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_active_by_node_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_active_by_node_id_returns_file():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.get_required_active_by_node_id(file_obj.node_id)
    assert res is file_obj


# ---------------------------------------------------------------------------
# get_by_storage_key / get_required_by_storage_key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_storage_key_returns_file():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.get_by_storage_key(
        storage_bucket="my-bucket", storage_key="files/test.txt"
    )
    assert res is file_obj


@pytest.mark.asyncio
async def test_get_by_storage_key_validates_empty_key():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.get_by_storage_key(storage_bucket="b", storage_key="   ")


@pytest.mark.asyncio
async def test_get_required_by_storage_key_returns_file():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.get_required_by_storage_key(
        storage_bucket="my-bucket", storage_key="files/test.txt"
    )
    assert res is file_obj


@pytest.mark.asyncio
async def test_get_required_by_storage_key_raises_when_missing():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_storage_key(
            storage_bucket="my-bucket", storage_key="files/missing.txt"
        )


# ---------------------------------------------------------------------------
# create_file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_file_success_no_validation():
    repo, session, result = make_repo()
    node_id = uuid.uuid4()
    res = await repo.create_file(
        node_id=node_id,
        storage_bucket="my-bucket",
        storage_key="files/x.txt",
        size_bytes=512,
        mime_type="Text/Plain",
        extension=".TXT",
        checksum="ABCDEF",
        checksum_algorithm="SHA256",
        validate_node=False,
        check_duplicate_node=False,
    )
    session.add.assert_called_once()
    session.flush.assert_awaited()
    assert res.node_id == node_id
    # нормализация применена
    assert res.mime_type == "text/plain"
    assert res.extension == "txt"
    assert res.checksum == "abcdef"
    assert res.checksum_algorithm == "sha256"


@pytest.mark.asyncio
async def test_create_file_validates_node(monkeypatch):
    repo, session, result = make_repo()
    node_id = uuid.uuid4()
    called = {}

    async def fake_validate(nid, *, check_duplicate=True):
        called["node_id"] = nid
        called["check_duplicate"] = check_duplicate
        return MagicMock()

    monkeypatch.setattr(repo, "_validate_file_node", fake_validate)
    await repo.create_file(
        node_id=node_id,
        storage_bucket="b",
        storage_key="k",
        size_bytes=1,
        validate_node=True,
        check_duplicate_node=True,
    )
    assert called["node_id"] == node_id
    assert called["check_duplicate"] is True


@pytest.mark.asyncio
async def test_create_file_raises_for_negative_size():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_file(
            node_id=uuid.uuid4(),
            storage_bucket="b",
            storage_key="k",
            size_bytes=-1,
            validate_node=False,
        )


@pytest.mark.asyncio
async def test_create_file_with_node(monkeypatch):
    repo, session, result = make_repo()
    node = MagicMock()
    node.id = uuid.uuid4()
    repo.nodes.create_node = AsyncMock(return_value=node)
    res = await repo.create_file_with_node(
        owner_id=uuid.uuid4(),
        name="file.txt",
        storage_bucket="b",
        storage_key="k",
        size_bytes=10,
    )
    repo.nodes.create_node.assert_awaited_once()
    assert res.node_id == node.id


@pytest.mark.asyncio
async def test_create_for_existing_node(monkeypatch):
    repo, session, result = make_repo()
    node_id = uuid.uuid4()
    repo._validate_file_node = AsyncMock(return_value=MagicMock())
    res = await repo.create_for_existing_node(
        node_id=node_id,
        storage_bucket="b",
        storage_key="k",
        size_bytes=10,
    )
    repo._validate_file_node.assert_awaited_once()
    assert res.node_id == node_id


# ---------------------------------------------------------------------------
# create() override: error mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_maps_duplicate_error():
    repo, session, result = make_repo()
    session.flush = AsyncMock(side_effect=make_integrity_error("23505"))
    file_obj = make_file()
    with pytest.raises(DuplicateEntityError):
        await repo.create(file_obj, flush=True)


@pytest.mark.asyncio
async def test_create_maps_integrity_to_constraint():
    from database.exceptions import ConstraintViolationError
    repo, session, result = make_repo()
    session.flush = AsyncMock(side_effect=make_integrity_error("23503"))
    file_obj = make_file()
    with pytest.raises(ConstraintViolationError):
        await repo.create(file_obj, flush=True)


@pytest.mark.asyncio
async def test_create_maps_raw_integrity_error(monkeypatch):
    # Если super().create пробрасывает чистый IntegrityError, он преобразуется.
    from database.repositories.base import BaseRepository
    repo, session, result = make_repo()
    file_obj = make_file()

    async def raise_integrity(self, entity, *, flush=True, refresh=False):
        raise make_integrity_error("99999")

    monkeypatch.setattr(BaseRepository, "create", raise_integrity)
    with pytest.raises(RepositoryError):
        await repo.create(file_obj, flush=True)


# ---------------------------------------------------------------------------
# _get_required_by_file_id_or_node_id branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolver_requires_an_id():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo._get_required_by_file_id_or_node_id(file_id=None, node_id=None)


@pytest.mark.asyncio
async def test_resolver_rejects_both_ids():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo._get_required_by_file_id_or_node_id(
            file_id=uuid.uuid4(), node_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_resolver_by_node_id():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo._get_required_by_file_id_or_node_id(
        file_id=None, node_id=file_obj.node_id
    )
    assert res is file_obj


# ---------------------------------------------------------------------------
# get_storage_info / update_storage_info
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_storage_info_returns_dict():
    repo, session, result = make_repo()
    file_obj = make_file(checksum="abc", checksum_algorithm="sha256")
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    info = await repo.get_storage_info(file_id=file_obj.id)
    assert info["storage_bucket"] == "my-bucket"
    assert info["storage_key"] == "files/test.txt"
    assert info["size_bytes"] == 1024
    assert info["checksum"] == "abc"


@pytest.mark.asyncio
async def test_update_storage_info_applies_values():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.update_storage_info(
        file_id=file_obj.id,
        storage_bucket="new-bucket",
        storage_key="new/key",
        size_bytes=2048,
        checksum="DEAD",
        checksum_algorithm="MD5",
        storage_status=StorageObjectStatus.MISSING,
    )
    assert res is file_obj
    assert file_obj.storage_bucket == "new-bucket"
    assert file_obj.storage_key == "new/key"
    assert file_obj.size_bytes == 2048
    assert file_obj.checksum == "dead"
    assert file_obj.checksum_algorithm == "md5"
    assert file_obj.storage_status == StorageObjectStatus.MISSING


@pytest.mark.asyncio
async def test_update_storage_info_without_optional_values():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.update_storage_info(
        file_id=file_obj.id,
        storage_bucket="b",
        storage_key="k",
    )
    assert res is file_obj


# ---------------------------------------------------------------------------
# update_metadata / update_size / update_checksum
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_metadata():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.update_metadata(
        file_id=file_obj.id,
        size_bytes=99,
        mime_type="Image/PNG",
        extension="PNG",
        checksum="FF",
        checksum_algorithm="CRC",
    )
    assert res is file_obj
    assert file_obj.mime_type == "image/png"
    assert file_obj.extension == "png"
    assert file_obj.size_bytes == 99


@pytest.mark.asyncio
async def test_update_metadata_without_size():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.update_metadata(node_id=file_obj.node_id)
    assert res is file_obj


@pytest.mark.asyncio
async def test_update_size():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.update_size(file_id=file_obj.id, size_bytes=4096)
    assert file_obj.size_bytes == 4096
    assert res is file_obj


@pytest.mark.asyncio
async def test_update_checksum():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.update_checksum(
        node_id=file_obj.node_id, checksum="ABC", checksum_algorithm="sha1"
    )
    assert file_obj.checksum == "abc"
    assert file_obj.checksum_algorithm == "sha1"
    assert res is file_obj


# ---------------------------------------------------------------------------
# storage status helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_storage_status():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.update_storage_status(
        file_id=file_obj.id, storage_status=StorageObjectStatus.CORRUPTED
    )
    assert file_obj.storage_status == StorageObjectStatus.CORRUPTED
    assert res is file_obj


@pytest.mark.asyncio
async def test_mark_storage_available_missing_corrupted():
    for marker, expected in [
        ("mark_storage_available", StorageObjectStatus.AVAILABLE),
        ("mark_storage_missing", StorageObjectStatus.MISSING),
        ("mark_storage_corrupted", StorageObjectStatus.CORRUPTED),
    ]:
        repo, session, result = make_repo()
        file_obj = make_file()
        result.scalar_one_or_none = MagicMock(return_value=file_obj)
        res = await getattr(repo, marker)(file_id=file_obj.id)
        assert file_obj.storage_status == expected
        assert res is file_obj


# ---------------------------------------------------------------------------
# processing status helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_processing_status_node_id():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.update_processing_status(
        node_id=file_obj.node_id, processing_status=FileProcessingStatus.FAILED
    )
    assert file_obj.processing_status == FileProcessingStatus.FAILED
    assert res is file_obj


@pytest.mark.asyncio
async def test_mark_processing_and_failed():
    for marker, expected in [
        ("mark_processing", FileProcessingStatus.PROCESSING),
        ("mark_processing_failed", FileProcessingStatus.FAILED),
    ]:
        repo, session, result = make_repo()
        file_obj = make_file()
        result.scalar_one_or_none = MagicMock(return_value=file_obj)
        res = await getattr(repo, marker)(file_id=file_obj.id)
        assert file_obj.processing_status == expected
        assert res is file_obj


@pytest.mark.asyncio
async def test_mark_ready_calls_model_and_flushes():
    repo, session, result = make_repo()
    file_obj = make_file()
    file_obj.mark_ready = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.mark_ready(file_id=file_obj.id, refresh=True)
    file_obj.mark_ready.assert_called_once()
    session.flush.assert_awaited()
    session.refresh.assert_awaited()
    assert res is file_obj


@pytest.mark.asyncio
async def test_mark_ready_no_flush_no_refresh():
    repo, session, result = make_repo()
    file_obj = make_file()
    file_obj.mark_ready = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.mark_ready(file_id=file_obj.id, flush=False, refresh=False)
    assert res is file_obj
    session.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# preview helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_preview():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.update_preview(
        file_id=file_obj.id,
        preview_status=FilePreviewStatus.READY,
        preview_storage_key="  previews/x.png  ",
    )
    assert file_obj.preview_status == FilePreviewStatus.READY
    assert file_obj.preview_storage_key == "previews/x.png"
    assert res is file_obj


@pytest.mark.asyncio
async def test_set_preview_ready_calls_model():
    repo, session, result = make_repo()
    file_obj = make_file()
    file_obj.set_preview_ready = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.set_preview_ready(
        file_id=file_obj.id, preview_storage_key="previews/x.png", refresh=True
    )
    file_obj.set_preview_ready.assert_called_once_with("previews/x.png")
    session.flush.assert_awaited()
    session.refresh.assert_awaited()
    assert res is file_obj


@pytest.mark.asyncio
async def test_set_preview_ready_no_flush():
    repo, session, result = make_repo()
    file_obj = make_file()
    file_obj.set_preview_ready = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.set_preview_ready(
        file_id=file_obj.id, preview_storage_key="p/x", flush=False, refresh=False
    )
    assert res is file_obj
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_status_markers():
    for marker, expected in [
        ("mark_preview_not_required", FilePreviewStatus.NOT_REQUIRED),
        ("mark_preview_pending", FilePreviewStatus.PENDING),
        ("mark_preview_generating", FilePreviewStatus.GENERATING),
        ("mark_preview_failed", FilePreviewStatus.FAILED),
    ]:
        repo, session, result = make_repo()
        file_obj = make_file()
        result.scalar_one_or_none = MagicMock(return_value=file_obj)
        res = await getattr(repo, marker)(file_id=file_obj.id)
        assert file_obj.preview_status == expected
        assert res is file_obj


# ---------------------------------------------------------------------------
# find_by_checksum / find_duplicates_by_checksum
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_by_checksum_empty_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.find_by_checksum(checksum="   ")


@pytest.mark.asyncio
async def test_find_by_checksum_with_filters():
    repo, session, result = make_repo()
    files = [make_file(), make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.find_by_checksum(
        checksum="ABC",
        checksum_algorithm="sha256",
        owner_id=uuid.uuid4(),
        include_deleted_nodes=True,
    )
    assert res == files
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_find_duplicates_excludes_file_id():
    repo, session, result = make_repo()
    f1 = make_file()
    f2 = make_file()
    result.scalars.return_value.all.return_value = [f1, f2]
    res = await repo.find_duplicates_by_checksum(
        checksum="abc", exclude_file_id=f1.id
    )
    assert f1 not in res
    assert f2 in res


@pytest.mark.asyncio
async def test_find_duplicates_no_exclude():
    repo, session, result = make_repo()
    files = [make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.find_duplicates_by_checksum(checksum="abc")
    assert res == files


# ---------------------------------------------------------------------------
# list_by_mime_type / list_by_extension
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_by_mime_type_empty_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_by_mime_type(mime_type="  ")


@pytest.mark.asyncio
async def test_list_by_mime_type_with_owner():
    repo, session, result = make_repo()
    files = [make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.list_by_mime_type(
        mime_type="text/plain", owner_id=uuid.uuid4(), include_deleted_nodes=True
    )
    assert res == files


@pytest.mark.asyncio
async def test_list_by_extension_empty_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_by_extension(extension=".")


@pytest.mark.asyncio
async def test_list_by_extension_with_owner():
    repo, session, result = make_repo()
    files = [make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.list_by_extension(
        extension="txt", owner_id=uuid.uuid4(), include_deleted_nodes=True
    )
    assert res == files


@pytest.mark.asyncio
async def test_list_by_mime_type_excludes_deleted_default():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_by_mime_type(mime_type="text/plain")
    assert res == []


@pytest.mark.asyncio
async def test_list_by_extension_excludes_deleted_default():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_by_extension(extension="txt")
    assert res == []


@pytest.mark.asyncio
async def test_list_child_files_excludes_deleted_default():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_child_files(parent_id=uuid.uuid4())
    assert res == []


# ---------------------------------------------------------------------------
# is_file_node / file_exists_for_node / storage_key_exists / require_file_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_file_node_false_when_missing():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=False)
    res = await repo.is_file_node(uuid.uuid4(), include_deleted=False)
    assert res is False


@pytest.mark.asyncio
async def test_is_file_node_true_without_record_requirement():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=True)
    res = await repo.is_file_node(uuid.uuid4())
    assert res is True


@pytest.mark.asyncio
async def test_is_file_node_requires_record():
    repo, session, result = make_repo()
    # узел существует (scalar_value через scalar_one_or_none), затем проверка exists()
    result.scalar_one_or_none = MagicMock(return_value=True)
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.is_file_node(uuid.uuid4(), require_file_record=True)
    assert res is True


@pytest.mark.asyncio
async def test_file_exists_for_node():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.file_exists_for_node(uuid.uuid4())
    assert res is True


@pytest.mark.asyncio
async def test_storage_key_exists_with_bucket_and_exclude():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.storage_key_exists(
        storage_key="k", storage_bucket="b", exclude_file_id=uuid.uuid4()
    )
    assert res is True


@pytest.mark.asyncio
async def test_storage_key_exists_invalid_key():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.storage_key_exists(storage_key="  ")


@pytest.mark.asyncio
async def test_require_file_node_success():
    repo, session, result = make_repo()
    node = MagicMock()
    node.id = uuid.uuid4()
    node.node_type = NodeType.FILE
    node.is_deleted = False
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    res = await repo.require_file_node(node.id)
    assert res is node


@pytest.mark.asyncio
async def test_require_file_node_not_a_file():
    repo, session, result = make_repo()
    node = MagicMock()
    node.id = uuid.uuid4()
    node.node_type = NodeType.FOLDER
    node.is_deleted = False
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.require_file_node(node.id)


@pytest.mark.asyncio
async def test_require_file_node_deleted_disallowed():
    repo, session, result = make_repo()
    node = MagicMock()
    node.id = uuid.uuid4()
    node.node_type = NodeType.FILE
    node.is_deleted = True
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    with pytest.raises(InvalidQueryError):
        await repo.require_file_node(node.id, include_deleted=False)


# ---------------------------------------------------------------------------
# _validate_file_node
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_file_node_duplicate():
    repo, session, result = make_repo()
    node = MagicMock()
    node.id = uuid.uuid4()
    node.node_type = NodeType.FILE
    node.is_deleted = False
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    result.scalar_one = MagicMock(return_value=1)  # file_exists_for_node -> True (файл существует)
    with pytest.raises(DuplicateEntityError):
        await repo._validate_file_node(node.id, check_duplicate=True)


@pytest.mark.asyncio
async def test_validate_file_node_no_duplicate_check():
    repo, session, result = make_repo()
    node = MagicMock()
    node.id = uuid.uuid4()
    node.node_type = NodeType.FILE
    node.is_deleted = False
    repo.nodes.get_required_by_id = AsyncMock(return_value=node)
    res = await repo._validate_file_node(node.id, check_duplicate=False)
    assert res is node


# ---------------------------------------------------------------------------
# list methods
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_by_node_ids_empty_returns_empty():
    repo, session, result = make_repo()
    res = await repo.list_by_node_ids([])
    assert res == []
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_by_node_ids_returns_files():
    repo, session, result = make_repo()
    files = [make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.list_by_node_ids([uuid.uuid4()], include_deleted_nodes=False)
    assert res == files


@pytest.mark.asyncio
async def test_list_user_files():
    repo, session, result = make_repo()
    files = [make_file(), make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.list_user_files(owner_id=uuid.uuid4(), include_deleted_nodes=True)
    assert res == files


@pytest.mark.asyncio
async def test_list_child_files():
    repo, session, result = make_repo()
    files = [make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.list_child_files(parent_id=uuid.uuid4(), include_deleted_nodes=True)
    assert res == files


@pytest.mark.asyncio
async def test_list_ready_files_with_owner():
    repo, session, result = make_repo()
    files = [make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.list_ready_files(owner_id=uuid.uuid4(), include_deleted_nodes=True)
    assert res == files


@pytest.mark.asyncio
async def test_list_ready_files_without_owner():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_ready_files()
    assert res == []


@pytest.mark.asyncio
async def test_list_by_storage_status():
    repo, session, result = make_repo()
    files = [make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.list_by_storage_status(
        storage_status=StorageObjectStatus.MISSING,
        owner_id=uuid.uuid4(),
        include_deleted_nodes=False,
    )
    assert res == files


# ---------------------------------------------------------------------------
# search_user_files / count_user_files_filtered / _build_search_statement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_user_files_full_filters():
    repo, session, result = make_repo()
    files = [make_file()]
    result.scalars.return_value.all.return_value = files
    res = await repo.search_user_files(
        owner_id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        include_deleted_nodes=False,
        query="  doc  ",
        mime_type="text/plain",
        extension="txt",
        storage_status=StorageObjectStatus.AVAILABLE,
        processing_status=FileProcessingStatus.READY,
        preview_status=FilePreviewStatus.READY,
        min_size_bytes=1,
        max_size_bytes=1000,
        created_from="2020-01-01",
        created_to="2020-12-31",
        updated_from="2021-01-01",
        updated_to="2021-12-31",
        sort_by="name",
        sort_direction="asc",
    )
    assert res == files


@pytest.mark.asyncio
async def test_search_user_files_query_blank_skipped():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_user_files(owner_id=uuid.uuid4(), query="   ")
    assert res == []


@pytest.mark.asyncio
async def test_search_user_files_sort_variants():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    for sort_by in [
        "path", "size_bytes", "mime_type", "extension",
        "created_at", "updated_at", "unknown_field",
    ]:
        res = await repo.search_user_files(
            owner_id=uuid.uuid4(), sort_by=sort_by, sort_direction="desc"
        )
        assert res == []


@pytest.mark.asyncio
async def test_count_user_files_filtered():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=42)
    total = await repo.count_user_files_filtered(owner_id=uuid.uuid4())
    assert total == 42


@pytest.mark.asyncio
async def test_count_user_files_filtered_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    total = await repo.count_user_files_filtered(owner_id=uuid.uuid4())
    assert total == 0


# ---------------------------------------------------------------------------
# count_user_files / sum_user_files_size / count_child_files
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_files():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=5)
    total = await repo.count_user_files(owner_id=uuid.uuid4(), include_deleted_nodes=True)
    assert total == 5


@pytest.mark.asyncio
async def test_count_user_files_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    total = await repo.count_user_files(owner_id=uuid.uuid4())
    assert total == 0


@pytest.mark.asyncio
async def test_sum_user_files_size():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=12345)
    total = await repo.sum_user_files_size(owner_id=uuid.uuid4(), include_deleted_nodes=True)
    assert total == 12345


@pytest.mark.asyncio
async def test_sum_user_files_size_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    total = await repo.sum_user_files_size(owner_id=uuid.uuid4())
    assert total == 0


@pytest.mark.asyncio
async def test_count_child_files():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=3)
    total = await repo.count_child_files(parent_id=uuid.uuid4(), include_deleted_nodes=True)
    assert total == 3


@pytest.mark.asyncio
async def test_count_child_files_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    total = await repo.count_child_files(parent_id=uuid.uuid4())
    assert total == 0


# ---------------------------------------------------------------------------
# delete_by_node_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_by_node_id_success():
    repo, session, result = make_repo()
    file_obj = make_file()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo.delete_by_node_id(file_obj.node_id)
    assert res is True
    session.delete.assert_awaited_once_with(file_obj)


@pytest.mark.asyncio
async def test_delete_by_node_id_missing_required_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.delete_by_node_id(uuid.uuid4(), required=True)


@pytest.mark.asyncio
async def test_delete_by_node_id_missing_not_required():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.delete_by_node_id(uuid.uuid4(), required=False)
    assert res is False


# ---------------------------------------------------------------------------
# _execute_file_statement error branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_file_statement_success():
    repo, session, result = make_repo()
    files = [make_file()]
    result.scalars.return_value.all.return_value = files
    from database.models.filesystem import File
    res = await repo._execute_file_statement(
        repo.select(), operation="op"
    )
    assert res == files


@pytest.mark.asyncio
async def test_execute_file_statement_integrity_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo._execute_file_statement(repo.select(), operation="op")


@pytest.mark.asyncio
async def test_execute_file_statement_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._execute_file_statement(repo.select(), operation="op")


# ---------------------------------------------------------------------------
# validation helpers
# ---------------------------------------------------------------------------

def test_validate_storage_bucket_empty():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_storage_bucket("   ")


def test_validate_storage_bucket_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_storage_bucket("x" * 129)


def test_normalize_storage_key_optional_none_and_blank():
    repo, session, result = make_repo()
    assert repo._normalize_storage_key_optional(None) is None
    assert repo._normalize_storage_key_optional("   ") is None
    assert repo._normalize_storage_key_optional("  k ") == "k"


def test_validate_size_bytes_not_int():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_size_bytes("10")


def test_normalize_mime_type_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_mime_type("x" * 256)


def test_normalize_mime_type_blank_returns_none():
    repo, session, result = make_repo()
    assert repo._normalize_mime_type("   ") is None


def test_normalize_extension_path_separator():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_extension("a/b")


def test_normalize_extension_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_extension("x" * 33)


def test_normalize_extension_leading_dot_only():
    repo, session, result = make_repo()
    assert repo._normalize_extension(".") is None


def test_normalize_checksum_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_checksum("x" * 129)


def test_normalize_checksum_blank():
    repo, session, result = make_repo()
    assert repo._normalize_checksum("   ") is None


def test_normalize_checksum_algorithm_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_checksum_algorithm("x" * 33)


def test_normalize_checksum_algorithm_blank():
    repo, session, result = make_repo()
    assert repo._normalize_checksum_algorithm("   ") is None
