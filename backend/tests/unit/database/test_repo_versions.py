"""Юнит-тесты репозитория версий файлов (FileVersionRepository)."""
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
from database.repositories.versions import FileVersionRepository


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
    session.add_all = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session, result


def make_repo():
    session, result = make_session()
    return FileVersionRepository(session=session), session, result


def make_version(**kwargs):
    version = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        version_number=1,
        storage_bucket="my-bucket",
        storage_key="versions/v1.bin",
        size_bytes=1024,
        checksum="abc123",
        mime_type="text/plain",
        created_by=None,
        change_comment=None,
        is_current=False,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(version, k, v)
    return version


def make_integrity_error(sqlstate="23505", constraint="uq_file_versions_storage_key"):
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = constraint
    orig.table_name = "file_versions"
    orig.column_name = None
    err = IntegrityError("stmt", {}, orig)
    err.orig = orig
    return err


# ---------------------------------------------------------------------------
# get_by_id / get_required_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_by_id_returns_version():
    repo, session, result = make_repo()
    version = make_version()
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.get_by_id(version.id)
    assert res is version
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_get_required_by_id_raises_when_missing():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_by_id_returns_version():
    repo, session, result = make_repo()
    version = make_version()
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.get_required_by_id(version.id)
    assert res is version


# ---------------------------------------------------------------------------
# get_versions_by_file_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_versions_by_file_id_newest_first():
    repo, session, result = make_repo()
    versions = [make_version(), make_version()]
    result.scalars.return_value.all.return_value = versions
    res = await repo.get_versions_by_file_id(uuid.uuid4(), newest_first=True)
    assert res == versions


@pytest.mark.asyncio
async def test_get_versions_by_file_id_oldest_first():
    repo, session, result = make_repo()
    versions = [make_version()]
    result.scalars.return_value.all.return_value = versions
    res = await repo.get_versions_by_file_id(
        uuid.uuid4(), offset=0, limit=10, newest_first=False
    )
    assert res == versions


@pytest.mark.asyncio
async def test_get_versions_by_file_id_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.get_versions_by_file_id(uuid.uuid4(), offset=-1, limit=10)


# ---------------------------------------------------------------------------
# get_latest_version / get_required_latest_version
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_latest_version_returns_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_latest_version(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_latest_version_returns_version():
    repo, session, result = make_repo()
    version = make_version(version_number=7)
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.get_latest_version(version.file_id)
    assert res is version


@pytest.mark.asyncio
async def test_get_required_latest_version_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_latest_version(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_latest_version_returns_version():
    repo, session, result = make_repo()
    version = make_version()
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.get_required_latest_version(version.file_id)
    assert res is version


# ---------------------------------------------------------------------------
# get_current_version / get_required_current_version
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_current_version_returns_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_current_version(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_current_version_returns_version():
    repo, session, result = make_repo()
    version = make_version(is_current=True)
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.get_current_version(version.file_id)
    assert res is version


@pytest.mark.asyncio
async def test_get_required_current_version_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_current_version(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_current_version_returns_version():
    repo, session, result = make_repo()
    version = make_version(is_current=True)
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.get_required_current_version(version.file_id)
    assert res is version


# ---------------------------------------------------------------------------
# get_by_file_id_and_version_number / required variant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_file_id_and_version_number_returns_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_file_id_and_version_number(
        file_id=uuid.uuid4(), version_number=2
    )
    assert res is None


@pytest.mark.asyncio
async def test_get_by_file_id_and_version_number_returns_version():
    repo, session, result = make_repo()
    version = make_version(version_number=2)
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.get_by_file_id_and_version_number(
        file_id=version.file_id, version_number=2
    )
    assert res is version


@pytest.mark.asyncio
async def test_get_by_file_id_and_version_number_invalid():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.get_by_file_id_and_version_number(
            file_id=uuid.uuid4(), version_number=0
        )


@pytest.mark.asyncio
async def test_get_required_by_file_id_and_version_number_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_file_id_and_version_number(
            file_id=uuid.uuid4(), version_number=3
        )


@pytest.mark.asyncio
async def test_get_required_by_file_id_and_version_number_returns():
    repo, session, result = make_repo()
    version = make_version(version_number=3)
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.get_required_by_file_id_and_version_number(
        file_id=version.file_id, version_number=3
    )
    assert res is version


# ---------------------------------------------------------------------------
# get_next_version_number / version_number_exists / storage_key_exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_next_version_number_value():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=5)
    res = await repo.get_next_version_number(uuid.uuid4())
    assert res == 5


@pytest.mark.asyncio
async def test_get_next_version_number_defaults_to_one():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_next_version_number(uuid.uuid4())
    assert res == 1


@pytest.mark.asyncio
async def test_version_number_exists_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.version_number_exists(file_id=uuid.uuid4(), version_number=2)
    assert res is True


@pytest.mark.asyncio
async def test_version_number_exists_invalid_number():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.version_number_exists(file_id=uuid.uuid4(), version_number=-1)


@pytest.mark.asyncio
async def test_storage_key_exists_with_exclude():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.storage_key_exists(
        "versions/v1.bin", exclude_version_id=uuid.uuid4()
    )
    assert res is True


@pytest.mark.asyncio
async def test_storage_key_exists_false_no_exclude():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    res = await repo.storage_key_exists("versions/v1.bin")
    assert res is False


@pytest.mark.asyncio
async def test_storage_key_exists_invalid_key():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.storage_key_exists("   ")


# ---------------------------------------------------------------------------
# create_version
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_version_auto_number_no_current(monkeypatch):
    repo, session, result = make_repo()
    file_id = uuid.uuid4()
    repo._ensure_file_exists = AsyncMock()
    repo.get_next_version_number = AsyncMock(return_value=4)

    created = make_version(file_id=file_id, version_number=4)

    async def fake_create(entity, *, flush=True, refresh=False):
        return created

    repo.create = fake_create  # type: ignore[method-assign]
    res = await repo.create_version(
        file_id=file_id,
        storage_bucket="my-bucket",
        storage_key="versions/v4.bin",
        size_bytes=2048,
    )
    repo._ensure_file_exists.assert_awaited_once_with(file_id)
    repo.get_next_version_number.assert_awaited_once_with(file_id)
    assert res is created
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_create_version_explicit_number_and_current():
    repo, session, result = make_repo()
    file_id = uuid.uuid4()
    repo._ensure_file_exists = AsyncMock()
    repo.unset_current_versions = AsyncMock(return_value=0)
    repo._update_file_current_version_id = AsyncMock()

    created = make_version(file_id=file_id, version_number=3, is_current=True)

    async def fake_create(entity, *, flush=True, refresh=False):
        # номер задан явно -> не пересчитывается
        assert entity.version_number == 3
        return created

    repo.create = fake_create  # type: ignore[method-assign]
    res = await repo.create_version(
        file_id=file_id,
        storage_bucket="my-bucket",
        storage_key="versions/v3.bin",
        size_bytes=2048,
        version_number=3,
        is_current=True,
    )
    repo.unset_current_versions.assert_awaited_once()
    repo._update_file_current_version_id.assert_awaited_once()
    assert res is created


@pytest.mark.asyncio
async def test_create_version_current_without_file_update():
    repo, session, result = make_repo()
    file_id = uuid.uuid4()
    repo._ensure_file_exists = AsyncMock()
    repo.unset_current_versions = AsyncMock(return_value=0)
    repo._update_file_current_version_id = AsyncMock()

    created = make_version(file_id=file_id, is_current=True)
    repo.create = AsyncMock(return_value=created)
    res = await repo.create_version(
        file_id=file_id,
        storage_bucket="b",
        storage_key="k",
        size_bytes=1,
        version_number=1,
        is_current=True,
        update_file_current_version=False,
    )
    repo._update_file_current_version_id.assert_not_awaited()
    assert res is created


@pytest.mark.asyncio
async def test_create_version_skip_file_check():
    repo, session, result = make_repo()
    repo._ensure_file_exists = AsyncMock()
    created = make_version()
    repo.create = AsyncMock(return_value=created)
    res = await repo.create_version(
        file_id=created.file_id,
        storage_bucket="b",
        storage_key="k",
        size_bytes=1,
        version_number=1,
        check_file_exists=False,
        flush=False,
    )
    repo._ensure_file_exists.assert_not_awaited()
    assert res is created
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_version_invalid_size():
    repo, session, result = make_repo()
    repo._ensure_file_exists = AsyncMock()
    with pytest.raises(InvalidQueryError):
        await repo.create_version(
            file_id=uuid.uuid4(),
            storage_bucket="b",
            storage_key="k",
            size_bytes=-1,
            version_number=1,
        )


# ---------------------------------------------------------------------------
# set_current_version / set_current_version_by_number / unset / clear
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_current_version_success():
    repo, session, result = make_repo()
    version = make_version()
    result.scalar_one_or_none = MagicMock(return_value=version)
    repo.unset_current_versions = AsyncMock(return_value=0)
    repo._update_file_current_version_id = AsyncMock()
    res = await repo.set_current_version(version_id=version.id, refresh=True)
    assert res is version
    assert version.is_current is True
    repo.unset_current_versions.assert_awaited_once()
    repo._update_file_current_version_id.assert_awaited_once()
    session.flush.assert_awaited()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_set_current_version_no_file_update_no_flush():
    repo, session, result = make_repo()
    version = make_version()
    result.scalar_one_or_none = MagicMock(return_value=version)
    repo.unset_current_versions = AsyncMock(return_value=0)
    repo._update_file_current_version_id = AsyncMock()
    res = await repo.set_current_version(
        version_id=version.id,
        update_file_current_version=False,
        flush=False,
        refresh=False,
    )
    assert res is version
    repo._update_file_current_version_id.assert_not_awaited()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_current_version_missing_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.set_current_version(version_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_set_current_version_by_number_delegates():
    repo, session, result = make_repo()
    version = make_version(version_number=2)
    repo.get_required_by_file_id_and_version_number = AsyncMock(return_value=version)
    repo.set_current_version = AsyncMock(return_value=version)
    res = await repo.set_current_version_by_number(
        file_id=version.file_id, version_number=2
    )
    assert res is version
    repo.set_current_version.assert_awaited_once()


@pytest.mark.asyncio
async def test_unset_current_versions_returns_rowcount():
    repo, session, result = make_repo()
    result.rowcount = 3
    res = await repo.unset_current_versions(file_id=uuid.uuid4())
    assert res == 3
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_unset_current_versions_with_exclude_no_flush():
    repo, session, result = make_repo()
    result.rowcount = 2
    res = await repo.unset_current_versions(
        file_id=uuid.uuid4(), exclude_version_id=uuid.uuid4(), flush=False
    )
    assert res == 2
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_unset_current_versions_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.unset_current_versions(file_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_clear_file_current_version():
    repo, session, result = make_repo()
    repo.unset_current_versions = AsyncMock(return_value=0)
    repo._update_file_current_version_id = AsyncMock()
    await repo.clear_file_current_version(file_id=uuid.uuid4())
    repo.unset_current_versions.assert_awaited_once()
    repo._update_file_current_version_id.assert_awaited_once()
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_clear_file_current_version_no_flush():
    repo, session, result = make_repo()
    repo.unset_current_versions = AsyncMock(return_value=0)
    repo._update_file_current_version_id = AsyncMock()
    await repo.clear_file_current_version(file_id=uuid.uuid4(), flush=False)
    session.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# геттеры информации о хранилище
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_version_storage_info():
    repo, session, result = make_repo()
    version = make_version(checksum="cs", mime_type="text/plain")
    result.scalar_one_or_none = MagicMock(return_value=version)
    info = await repo.get_version_storage_info(version.id)
    assert info["storage_bucket"] == version.storage_bucket
    assert info["storage_key"] == version.storage_key
    assert info["size_bytes"] == version.size_bytes
    assert info["checksum"] == "cs"
    assert info["mime_type"] == "text/plain"
    assert info["version_number"] == version.version_number
    assert info["is_current"] == version.is_current


@pytest.mark.asyncio
async def test_get_current_version_storage_info():
    repo, session, result = make_repo()
    version = make_version(is_current=True)
    result.scalar_one_or_none = MagicMock(return_value=version)
    info = await repo.get_current_version_storage_info(version.file_id)
    assert info["is_current"] is True
    assert info["storage_key"] == version.storage_key


@pytest.mark.asyncio
async def test_list_storage_info_by_file_id():
    repo, session, result = make_repo()
    v1 = make_version(version_number=1)
    v2 = make_version(version_number=2)
    repo.get_versions_by_file_id = AsyncMock(return_value=[v1, v2])
    infos = await repo.list_storage_info_by_file_id(uuid.uuid4())
    assert len(infos) == 2
    assert infos[0]["version_number"] == 1
    assert infos[1]["version_number"] == 2


# ---------------------------------------------------------------------------
# update_version_storage_info / update_change_comment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_version_storage_info_applies_values():
    repo, session, result = make_repo()
    version = make_version()
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.update_version_storage_info(
        version_id=version.id,
        storage_bucket="new-bucket",
        storage_key="new/key",
        size_bytes=4096,
        checksum="DEAD",
        mime_type="Image/PNG",
    )
    assert res is version
    assert version.storage_bucket == "new-bucket"
    assert version.storage_key == "new/key"
    assert version.size_bytes == 4096
    assert version.checksum == "dead"
    assert version.mime_type == "image/png"


@pytest.mark.asyncio
async def test_update_version_storage_info_without_size():
    repo, session, result = make_repo()
    version = make_version(size_bytes=10)
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.update_version_storage_info(
        version_id=version.id,
        storage_bucket="b",
        storage_key="k",
    )
    assert res is version
    assert version.size_bytes == 10


@pytest.mark.asyncio
async def test_update_version_storage_info_missing_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_version_storage_info(
            version_id=uuid.uuid4(),
            storage_bucket="b",
            storage_key="k",
        )


@pytest.mark.asyncio
async def test_update_change_comment():
    repo, session, result = make_repo()
    version = make_version()
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.update_change_comment(
        version_id=version.id, change_comment="  hello  "
    )
    assert res is version
    assert version.change_comment == "hello"


@pytest.mark.asyncio
async def test_update_change_comment_clears():
    repo, session, result = make_repo()
    version = make_version(change_comment="old")
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.update_change_comment(
        version_id=version.id, change_comment="   "
    )
    assert version.change_comment is None
    assert res is version


# ---------------------------------------------------------------------------
# delete_versions_by_file_id / delete_version / delete_old_versions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_versions_by_file_id():
    repo, session, result = make_repo()
    result.rowcount = 4
    repo._update_file_current_version_id = AsyncMock()
    count = await repo.delete_versions_by_file_id(uuid.uuid4())
    assert count == 4
    repo._update_file_current_version_id.assert_awaited_once()
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_delete_versions_by_file_id_no_flush():
    repo, session, result = make_repo()
    result.rowcount = 0
    repo._update_file_current_version_id = AsyncMock()
    count = await repo.delete_versions_by_file_id(uuid.uuid4(), flush=False)
    assert count == 0
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_version_success_current():
    repo, session, result = make_repo()
    version = make_version(is_current=True)
    result.scalar_one_or_none = MagicMock(return_value=version)
    repo._update_file_current_version_id = AsyncMock()
    res = await repo.delete_version(version.id)
    assert res is True
    session.delete.assert_awaited_once_with(version)
    repo._update_file_current_version_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_version_success_not_current():
    repo, session, result = make_repo()
    version = make_version(is_current=False)
    result.scalar_one_or_none = MagicMock(return_value=version)
    repo._update_file_current_version_id = AsyncMock()
    res = await repo.delete_version(version.id)
    assert res is True
    repo._update_file_current_version_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_version_current_no_clear():
    repo, session, result = make_repo()
    version = make_version(is_current=True)
    result.scalar_one_or_none = MagicMock(return_value=version)
    repo._update_file_current_version_id = AsyncMock()
    res = await repo.delete_version(
        version.id, clear_file_current_version=False
    )
    assert res is True
    repo._update_file_current_version_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_version_missing_required_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.delete_version(uuid.uuid4(), required=True)


@pytest.mark.asyncio
async def test_delete_version_missing_not_required():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.delete_version(uuid.uuid4(), required=False)
    assert res is False


@pytest.mark.asyncio
async def test_delete_old_versions_negative_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.delete_old_versions(file_id=uuid.uuid4(), keep_latest=-1)


@pytest.mark.asyncio
async def test_delete_old_versions_keeps_current():
    repo, session, result = make_repo()
    v1 = make_version(version_number=3, is_current=False)
    v2 = make_version(version_number=2, is_current=True)
    v3 = make_version(version_number=1, is_current=False)
    repo.get_versions_by_file_id = AsyncMock(return_value=[v1, v2, v3])
    # keep_latest=1 -> кандидаты v2 и v3; v2 текущая, поэтому сохраняется
    count = await repo.delete_old_versions(
        file_id=uuid.uuid4(), keep_latest=1, keep_current=True
    )
    assert count == 1
    session.delete.assert_awaited_once_with(v3)


@pytest.mark.asyncio
async def test_delete_old_versions_no_keep_current():
    repo, session, result = make_repo()
    v1 = make_version(version_number=3, is_current=False)
    v2 = make_version(version_number=2, is_current=True)
    repo.get_versions_by_file_id = AsyncMock(return_value=[v1, v2])
    count = await repo.delete_old_versions(
        file_id=uuid.uuid4(), keep_latest=1, keep_current=False
    )
    assert count == 1
    session.delete.assert_awaited_once_with(v2)


@pytest.mark.asyncio
async def test_delete_old_versions_nothing_to_delete():
    repo, session, result = make_repo()
    repo.get_versions_by_file_id = AsyncMock(return_value=[make_version()])
    count = await repo.delete_old_versions(file_id=uuid.uuid4(), keep_latest=5)
    assert count == 0
    session.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# count_versions / count_all_versions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_versions():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=6)
    count = await repo.count_versions(uuid.uuid4())
    assert count == 6


@pytest.mark.asyncio
async def test_count_all_versions():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=11)
    count = await repo.count_all_versions()
    assert count == 11


# ---------------------------------------------------------------------------
# find_by_storage_key / get_required_by_storage_key / list_by_checksum
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_by_storage_key_returns_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.find_by_storage_key("versions/v1.bin")
    assert res is None


@pytest.mark.asyncio
async def test_find_by_storage_key_returns_version():
    repo, session, result = make_repo()
    version = make_version()
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.find_by_storage_key("versions/v1.bin")
    assert res is version


@pytest.mark.asyncio
async def test_find_by_storage_key_invalid():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.find_by_storage_key("   ")


@pytest.mark.asyncio
async def test_get_required_by_storage_key_returns_version():
    repo, session, result = make_repo()
    version = make_version()
    result.scalar_one_or_none = MagicMock(return_value=version)
    res = await repo.get_required_by_storage_key("versions/v1.bin")
    assert res is version


@pytest.mark.asyncio
async def test_get_required_by_storage_key_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_storage_key("versions/missing.bin")


@pytest.mark.asyncio
async def test_list_by_checksum_returns_versions():
    repo, session, result = make_repo()
    versions = [make_version()]
    result.scalars.return_value.all.return_value = versions
    res = await repo.list_by_checksum(checksum="ABC")
    assert res == versions


@pytest.mark.asyncio
async def test_list_by_checksum_empty_checksum_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_by_checksum(checksum="   ")


@pytest.mark.asyncio
async def test_list_by_checksum_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_by_checksum(checksum="abc", offset=-1)


# ---------------------------------------------------------------------------
# _ensure_file_exists / _update_file_current_version_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_file_exists_returns_file():
    repo, session, result = make_repo()
    file_obj = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=file_obj)
    res = await repo._ensure_file_exists(uuid.uuid4())
    assert res is file_obj


@pytest.mark.asyncio
async def test_ensure_file_exists_missing_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo._ensure_file_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_file_exists_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._ensure_file_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_file_current_version_id_success():
    repo, session, result = make_repo()
    await repo._update_file_current_version_id(
        file_id=uuid.uuid4(), current_version_id=uuid.uuid4()
    )
    session.execute.assert_awaited()
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_update_file_current_version_id_none_no_flush():
    repo, session, result = make_repo()
    await repo._update_file_current_version_id(
        file_id=uuid.uuid4(), current_version_id=None, flush=False
    )
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_file_current_version_id_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._update_file_current_version_id(
            file_id=uuid.uuid4(), current_version_id=uuid.uuid4()
        )


# ---------------------------------------------------------------------------
# хелперы валидации / нормализации
# ---------------------------------------------------------------------------

def test_validate_version_number_not_int():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_version_number("2")


def test_validate_version_number_non_positive():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_version_number(0)


def test_validate_version_number_ok():
    repo, session, result = make_repo()
    assert repo._validate_version_number(3) == 3


def test_validate_storage_bucket_empty():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_storage_bucket("   ")


def test_validate_storage_bucket_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_storage_bucket("x" * 129)


def test_validate_storage_bucket_ok():
    repo, session, result = make_repo()
    assert repo._validate_storage_bucket("  bucket ") == "bucket"


def test_validate_storage_key_empty():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_storage_key("   ")


def test_validate_storage_key_ok():
    repo, session, result = make_repo()
    assert repo._validate_storage_key("  k ") == "k"


def test_validate_size_bytes_not_int():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_size_bytes("10")


def test_validate_size_bytes_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_size_bytes(-1)


def test_validate_size_bytes_ok():
    repo, session, result = make_repo()
    assert repo._validate_size_bytes(0) == 0


def test_normalize_checksum_none():
    repo, session, result = make_repo()
    assert repo._normalize_checksum(None) is None


def test_normalize_checksum_blank():
    repo, session, result = make_repo()
    assert repo._normalize_checksum("   ") is None


def test_normalize_checksum_lowercases():
    repo, session, result = make_repo()
    assert repo._normalize_checksum("  ABCDEF ") == "abcdef"


def test_normalize_checksum_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_checksum("x" * 129)


def test_normalize_mime_type_none():
    repo, session, result = make_repo()
    assert repo._normalize_mime_type(None) is None


def test_normalize_mime_type_blank():
    repo, session, result = make_repo()
    assert repo._normalize_mime_type("   ") is None


def test_normalize_mime_type_lowercases():
    repo, session, result = make_repo()
    assert repo._normalize_mime_type("Text/Plain") == "text/plain"


def test_normalize_mime_type_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_mime_type("x" * 256)


def test_normalize_change_comment_none():
    repo, session, result = make_repo()
    assert repo._normalize_change_comment(None) is None


def test_normalize_change_comment_blank():
    repo, session, result = make_repo()
    assert repo._normalize_change_comment("   ") is None


def test_normalize_change_comment_strips():
    repo, session, result = make_repo()
    assert repo._normalize_change_comment("  hi ") == "hi"


# ---------------------------------------------------------------------------
# переопределение create(): маппинг ошибок
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_success():
    repo, session, result = make_repo()
    version = make_version()
    res = await repo.create(version, flush=True)
    assert res is version
    session.add.assert_called_once_with(version)


@pytest.mark.asyncio
async def test_create_maps_duplicate_error(monkeypatch):
    from database.repositories.base import BaseRepository
    repo, session, result = make_repo()
    version = make_version()

    async def raise_duplicate(self, entity, *, flush=True, refresh=False):
        raise DuplicateEntityError("FileVersion", field="x", value="y")

    monkeypatch.setattr(BaseRepository, "create", raise_duplicate)
    with pytest.raises(DuplicateEntityError):
        await repo.create(version, flush=True)


@pytest.mark.asyncio
async def test_create_maps_raw_integrity_error(monkeypatch):
    from database.repositories.base import BaseRepository
    repo, session, result = make_repo()
    version = make_version()

    async def raise_integrity(self, entity, *, flush=True, refresh=False):
        raise make_integrity_error("23503")

    monkeypatch.setattr(BaseRepository, "create", raise_integrity)
    with pytest.raises((RepositoryError, DuplicateEntityError)):
        await repo.create(version, flush=True)


# ---------------------------------------------------------------------------
# _execute_file_version_statement — ветки ошибок
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_file_version_statement_success():
    repo, session, result = make_repo()
    versions = [make_version()]
    result.scalars.return_value.all.return_value = versions
    res = await repo._execute_file_version_statement(
        repo.select(), operation="op"
    )
    assert res == versions


@pytest.mark.asyncio
async def test_execute_file_version_statement_integrity_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo._execute_file_version_statement(repo.select(), operation="op")


@pytest.mark.asyncio
async def test_execute_file_version_statement_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._execute_file_version_statement(repo.select(), operation="op")
