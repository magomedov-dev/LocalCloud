"""Юнит-тесты репозитория сессий загрузки (UploadSessionsRepository)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
    RepositoryError,
)
from database.models.enums import UploadSessionStatus
from database.repositories.sessions import UploadSessionsRepository


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
    result.one = MagicMock(return_value=(0, 0))
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session, result


def make_repo():
    session, result = make_session()
    return UploadSessionsRepository(session=session), session, result


def make_upload_session(**kwargs):
    sess = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        parent_node_id=uuid.uuid4(),
        file_name="test.txt",
        file_size_bytes=1024,
        part_size_bytes=512,
        parts_count=2,
        uploaded_parts_count=0,
        uploaded_bytes=0,
        storage_bucket="bucket",
        storage_key="key/test.txt",
        upload_id="upload-123",
        status=UploadSessionStatus.CREATED,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        all_parts_uploaded=False,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(sess, k, v)
    sess.mark_uploading = MagicMock()
    sess.complete = MagicMock()
    sess.fail = MagicMock()
    sess.abort = MagicMock()
    sess.expire = MagicMock()
    sess.register_uploaded_part = MagicMock()
    sess.unregister_uploaded_part = MagicMock()
    sess.can_be_completed_at = MagicMock(return_value=True)
    sess.can_receive_parts_at = MagicMock(return_value=True)
    return sess


# ---------------------------------------------------------------------------
# Тесты: get_session_by_id / get_required_session_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_session_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    res = await repo.get_session_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_session_by_id_returns_session_when_found():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    res = await repo.get_session_by_id(sess.id)
    assert res is sess


@pytest.mark.asyncio
async def test_get_required_session_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_session_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_by_upload_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_upload_id_returns_none_for_empty_string():
    repo, session, result = make_repo()
    res = await repo.get_by_upload_id("   ")
    assert res is None


@pytest.mark.asyncio
async def test_get_by_upload_id_returns_session_when_found():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.get_by_upload_id("upload-123")
    assert res is sess


@pytest.mark.asyncio
async def test_get_required_by_upload_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_upload_id("nonexistent")


# ---------------------------------------------------------------------------
# Тесты: get_by_storage_key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_storage_key_returns_none_for_empty_values():
    repo, session, result = make_repo()
    res = await repo.get_by_storage_key(storage_bucket="", storage_key="key")
    assert res is None
    res = await repo.get_by_storage_key(storage_bucket="bucket", storage_key="   ")
    assert res is None


@pytest.mark.asyncio
async def test_get_by_storage_key_returns_session_when_found():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.get_by_storage_key(storage_bucket="bucket", storage_key="key/file.txt")
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: is_upload_id_exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_upload_id_exists_returns_false_for_empty():
    repo, session, result = make_repo()
    res = await repo.is_upload_id_exists("  ")
    assert res is False


@pytest.mark.asyncio
async def test_is_upload_id_exists_returns_true_when_found():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.is_upload_id_exists("upload-id")
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: list_user_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_sessions_returns_empty_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_user_sessions(uuid.uuid4())
    assert res == []


@pytest.mark.asyncio
async def test_list_user_sessions_raises_with_both_status_and_statuses():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_user_sessions(
            uuid.uuid4(),
            status=UploadSessionStatus.CREATED,
            statuses=[UploadSessionStatus.UPLOADING],
        )


@pytest.mark.asyncio
async def test_list_user_sessions_raises_with_empty_statuses():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_user_sessions(uuid.uuid4(), statuses=[])


@pytest.mark.asyncio
async def test_list_user_sessions_returns_sessions():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalars.return_value.all.return_value = [sess]
    res = await repo.list_user_sessions(uuid.uuid4())
    assert len(res) == 1


# ---------------------------------------------------------------------------
# Тесты: list_by_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_by_status_returns_list():
    repo, session, result = make_repo()
    sess = make_upload_session(status=UploadSessionStatus.CREATED)
    result.scalars.return_value.all.return_value = [sess]
    res = await repo.list_by_status(UploadSessionStatus.CREATED)
    assert len(res) == 1


@pytest.mark.asyncio
async def test_list_by_status_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.list_by_status(UploadSessionStatus.CREATED, offset=-1)


# ---------------------------------------------------------------------------
# Тесты: create_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_session_raises_for_empty_filename():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_session(
            user_id=uuid.uuid4(),
            parent_node_id=uuid.uuid4(),
            file_name="",
            file_size_bytes=1024,
            part_size_bytes=512,
            storage_bucket="bucket",
            storage_key="key",
            upload_id="uid",
            parts_count=2,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            check_user_exists=False,
            check_parent_exists=False,
            check_duplicate_upload_id=False,
        )


@pytest.mark.asyncio
async def test_create_session_raises_for_negative_file_size():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_session(
            user_id=uuid.uuid4(),
            parent_node_id=uuid.uuid4(),
            file_name="test.txt",
            file_size_bytes=-1,
            part_size_bytes=512,
            storage_bucket="bucket",
            storage_key="key",
            upload_id="uid",
            parts_count=2,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            check_user_exists=False,
            check_parent_exists=False,
            check_duplicate_upload_id=False,
        )


@pytest.mark.asyncio
async def test_create_session_success():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    # Подменяем create, чтобы вернуть мок-сессию
    async def fake_create(entity, flush=True, refresh=False):
        return sess

    repo.create = fake_create  # type: ignore
    result.scalar_one = MagicMock(return_value=0)  # is_upload_id_exists -> False

    res = await repo.create_session(
        user_id=uuid.uuid4(),
        parent_node_id=uuid.uuid4(),
        file_name="test.txt",
        file_size_bytes=1024,
        part_size_bytes=512,
        storage_bucket="bucket",
        storage_key="key/test.txt",
        upload_id="upload-id-unique",
        parts_count=2,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        check_user_exists=False,
        check_parent_exists=False,
        check_duplicate_upload_id=False,
    )
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: update_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_raises_when_session_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_status(uuid.uuid4(), UploadSessionStatus.COMPLETED)


@pytest.mark.asyncio
async def test_update_status_success():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    res = await repo.update_status(sess.id, UploadSessionStatus.COMPLETED)
    assert res.status == UploadSessionStatus.COMPLETED


# ---------------------------------------------------------------------------
# Тесты: mark_uploading
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_uploading_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.mark_uploading(uuid.uuid4())


@pytest.mark.asyncio
async def test_mark_uploading_success():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    res = await repo.mark_uploading(sess.id)
    sess.mark_uploading.assert_called_once()
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: mark_failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_failed_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.mark_failed(uuid.uuid4())


@pytest.mark.asyncio
async def test_mark_failed_success():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    res = await repo.mark_failed(sess.id, reason="error occurred")
    sess.fail.assert_called_once()
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: mark_aborted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_aborted_success():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    res = await repo.mark_aborted(sess.id)
    sess.abort.assert_called_once()
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: mark_expired
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_expired_success():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    res = await repo.mark_expired(sess.id)
    sess.expire.assert_called_once()
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: register_uploaded_part
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_uploaded_part_raises_for_negative_size():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.register_uploaded_part(uuid.uuid4(), part_size_bytes=-1)


@pytest.mark.asyncio
async def test_register_uploaded_part_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.register_uploaded_part(uuid.uuid4(), part_size_bytes=512)


@pytest.mark.asyncio
async def test_register_uploaded_part_success():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.register_uploaded_part(sess.id, part_size_bytes=512)
    sess.register_uploaded_part.assert_called_once_with(512)
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: increment_uploaded_parts_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increment_uploaded_parts_count_raises_for_zero_increment():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.increment_uploaded_parts_count(uuid.uuid4(), increment_by=0)


@pytest.mark.asyncio
async def test_increment_uploaded_parts_count_raises_for_negative_bytes():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.increment_uploaded_parts_count(
            uuid.uuid4(), increment_by=1, uploaded_bytes_increment=-1
        )


@pytest.mark.asyncio
async def test_increment_uploaded_parts_count_success():
    repo, session, result = make_repo()
    sess = make_upload_session(uploaded_parts_count=0, parts_count=5, uploaded_bytes=0, file_size_bytes=1024)
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.increment_uploaded_parts_count(sess.id, increment_by=1)
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: count_user_sessions / count_by_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_sessions_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=5)
    count = await repo.count_user_sessions(uuid.uuid4())
    assert count == 5


@pytest.mark.asyncio
async def test_count_by_status_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    count = await repo.count_by_status(UploadSessionStatus.CREATED)
    assert count == 3


# ---------------------------------------------------------------------------
# Тесты: can_complete_session / can_receive_parts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_can_complete_session_returns_false_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    res = await repo.can_complete_session(uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_can_complete_session_returns_true_when_can_complete():
    repo, session, result = make_repo()
    sess = make_upload_session()
    sess.can_be_completed_at = MagicMock(return_value=True)
    session.get = AsyncMock(return_value=sess)
    res = await repo.can_complete_session(sess.id)
    assert res is True


@pytest.mark.asyncio
async def test_can_receive_parts_returns_false_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    res = await repo.can_receive_parts(uuid.uuid4())
    assert res is False


# ---------------------------------------------------------------------------
# Тесты: find_expired_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_expired_sessions_raises_on_empty_statuses():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.find_expired_sessions(statuses=[])


@pytest.mark.asyncio
async def test_find_expired_sessions_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_expired_sessions()
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: find_unfinished_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_unfinished_sessions_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_unfinished_sessions()
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: search_user_sessions / count_user_sessions_filtered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_user_sessions_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_user_sessions(user_id=uuid.uuid4())
    assert res == []


@pytest.mark.asyncio
async def test_count_user_sessions_filtered_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=7)
    count = await repo.count_user_sessions_filtered(user_id=uuid.uuid4())
    assert count == 7


# ---------------------------------------------------------------------------
# Тесты: get_required_by_upload_id success / get_by_upload_id none result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_by_upload_id_returns_session():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.get_required_by_upload_id("upload-123")
    assert res is sess


@pytest.mark.asyncio
async def test_get_by_upload_id_none_when_missing():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_upload_id("missing")
    assert res is None


# ---------------------------------------------------------------------------
# Тесты: list_user_sessions — ветки фильтров
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_sessions_with_single_status_and_asc_order():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_user_sessions(
        uuid.uuid4(),
        status=UploadSessionStatus.CREATED,
        order_by_created_desc=False,
    )
    assert res == []


@pytest.mark.asyncio
async def test_list_user_sessions_with_statuses_filter():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalars.return_value.all.return_value = [sess]
    res = await repo.list_user_sessions(
        uuid.uuid4(),
        statuses=[UploadSessionStatus.CREATED, UploadSessionStatus.UPLOADING],
    )
    assert res == [sess]


# ---------------------------------------------------------------------------
# Тесты: list_user_active_sessions / list_user_sessions_by_statuses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_active_sessions_returns_list():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalars.return_value.all.return_value = [sess]
    res = await repo.list_user_active_sessions(uuid.uuid4())
    assert res == [sess]


@pytest.mark.asyncio
async def test_list_user_sessions_by_statuses_raises_on_empty():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_user_sessions_by_statuses(uuid.uuid4(), statuses=[])


@pytest.mark.asyncio
async def test_list_user_sessions_by_statuses_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_user_sessions_by_statuses(
        uuid.uuid4(), statuses=[UploadSessionStatus.CREATED]
    )
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: list_parent_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_parent_sessions_raises_both_status_and_statuses():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_parent_sessions(
            uuid.uuid4(),
            status=UploadSessionStatus.CREATED,
            statuses=[UploadSessionStatus.UPLOADING],
        )


@pytest.mark.asyncio
async def test_list_parent_sessions_raises_empty_statuses():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_parent_sessions(uuid.uuid4(), statuses=[])


@pytest.mark.asyncio
async def test_list_parent_sessions_with_status_and_asc():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_parent_sessions(
        uuid.uuid4(),
        status=UploadSessionStatus.CREATED,
        order_by_created_desc=False,
    )
    assert res == []


@pytest.mark.asyncio
async def test_list_parent_sessions_with_statuses():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalars.return_value.all.return_value = [sess]
    res = await repo.list_parent_sessions(
        uuid.uuid4(),
        statuses=[UploadSessionStatus.UPLOADING],
    )
    assert res == [sess]


# ---------------------------------------------------------------------------
# Тесты: list_by_status — ветка сортировки по возрастанию
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_by_status_asc_order():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_by_status(
        UploadSessionStatus.CREATED, order_by_created_desc=False
    )
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: create_session existence checks / duplicate / integrity error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_session_raises_when_user_missing():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.create_session(
            user_id=uuid.uuid4(),
            parent_node_id=uuid.uuid4(),
            file_name="test.txt",
            file_size_bytes=1024,
            part_size_bytes=512,
            storage_bucket="bucket",
            storage_key="key",
            upload_id="uid",
            parts_count=2,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            check_user_exists=True,
            check_parent_exists=False,
            check_duplicate_upload_id=False,
        )


@pytest.mark.asyncio
async def test_create_session_raises_when_parent_missing():
    repo, session, result = make_repo()
    sess_user = make_upload_session()
    # session.get используется и для пользователя, и для родителя; сначала пользователь, потом None
    session.get = AsyncMock(side_effect=[sess_user, None])
    with pytest.raises(EntityNotFoundError):
        await repo.create_session(
            user_id=uuid.uuid4(),
            parent_node_id=uuid.uuid4(),
            file_name="test.txt",
            file_size_bytes=1024,
            part_size_bytes=512,
            storage_bucket="bucket",
            storage_key="key",
            upload_id="uid",
            parts_count=2,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            check_user_exists=True,
            check_parent_exists=True,
            check_duplicate_upload_id=False,
        )


@pytest.mark.asyncio
async def test_create_session_raises_on_duplicate_upload_id():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)  # is_upload_id_exists -> True
    with pytest.raises(DuplicateEntityError):
        await repo.create_session(
            user_id=uuid.uuid4(),
            parent_node_id=uuid.uuid4(),
            file_name="test.txt",
            file_size_bytes=1024,
            part_size_bytes=512,
            storage_bucket="bucket",
            storage_key="key",
            upload_id="dup",
            parts_count=2,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            check_user_exists=False,
            check_parent_exists=False,
            check_duplicate_upload_id=True,
        )


@pytest.mark.asyncio
async def test_create_session_maps_integrity_error():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)

    async def fake_create(entity, flush=True, refresh=False):
        raise IntegrityError("stmt", {}, Exception("boom"))

    repo.create = fake_create  # type: ignore
    with pytest.raises(RepositoryError):
        await repo.create_session(
            user_id=uuid.uuid4(),
            parent_node_id=uuid.uuid4(),
            file_name="test.txt",
            file_size_bytes=1024,
            part_size_bytes=512,
            storage_bucket="bucket",
            storage_key="key/test.txt",
            upload_id="uid",
            parts_count=2,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            mime_type=" text/plain ",
            checksum=" abc ",
            checksum_algorithm=" md5 ",
            client_ip=" 127.0.0.1 ",
            user_agent=" agent ",
            check_user_exists=False,
            check_parent_exists=False,
            check_duplicate_upload_id=False,
        )


# ---------------------------------------------------------------------------
# Тесты: update_status_for_session — ветка refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_for_session_with_refresh():
    repo, session, result = make_repo()
    sess = make_upload_session()
    res = await repo.update_status_for_session(
        sess, UploadSessionStatus.COMPLETED, refresh=True
    )
    assert res.status == UploadSessionStatus.COMPLETED
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_uploading_with_refresh():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    await repo.mark_uploading(sess.id, refresh=True)
    session.refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# Тесты: mark_completed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_completed_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.mark_completed(uuid.uuid4())


@pytest.mark.asyncio
async def test_mark_completed_raises_when_parts_incomplete():
    repo, session, result = make_repo()
    sess = make_upload_session(all_parts_uploaded=False)
    session.get = AsyncMock(return_value=sess)
    with pytest.raises(InvalidQueryError):
        await repo.mark_completed(sess.id, require_all_parts=True)


@pytest.mark.asyncio
async def test_mark_completed_success_with_refresh():
    repo, session, result = make_repo()
    sess = make_upload_session(all_parts_uploaded=True)
    session.get = AsyncMock(return_value=sess)
    res = await repo.mark_completed(sess.id, require_all_parts=True, refresh=True)
    sess.complete.assert_called_once()
    session.refresh.assert_awaited_once()
    assert res is sess


@pytest.mark.asyncio
async def test_mark_completed_skips_check_when_not_required():
    repo, session, result = make_repo()
    sess = make_upload_session(all_parts_uploaded=False)
    session.get = AsyncMock(return_value=sess)
    completed_at = datetime.now(UTC)
    res = await repo.mark_completed(
        sess.id, completed_at=completed_at, require_all_parts=False
    )
    sess.complete.assert_called_once_with(completed_at=completed_at)
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: mark_failed / mark_aborted / mark_expired — ветка refreshes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_failed_with_refresh_no_reason():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    await repo.mark_failed(sess.id, refresh=True)
    sess.fail.assert_called_once()
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_aborted_with_refresh():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    await repo.mark_aborted(sess.id, refresh=True)
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_expired_with_refresh():
    repo, session, result = make_repo()
    sess = make_upload_session()
    session.get = AsyncMock(return_value=sess)
    await repo.mark_expired(sess.id, refresh=True)
    session.refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# Тесты: mark_expired_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_expired_sessions_marks_found():
    repo, session, result = make_repo()
    sess1 = make_upload_session()
    sess2 = make_upload_session()
    result.scalars.return_value.all.return_value = [sess1, sess2]
    moment = datetime.now(UTC)
    count = await repo.mark_expired_sessions(moment=moment)
    assert count == 2
    sess1.expire.assert_called_once_with(expired_at=moment)
    sess2.expire.assert_called_once_with(expired_at=moment)
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_mark_expired_sessions_no_flush_default_moment():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    count = await repo.mark_expired_sessions(flush=False)
    assert count == 0


# ---------------------------------------------------------------------------
# Тесты: register_uploaded_part refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_uploaded_part_with_refresh():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalar_one_or_none = MagicMock(return_value=sess)
    await repo.register_uploaded_part(sess.id, part_size_bytes=10, refresh=True)
    session.refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# Тесты: unregister_uploaded_part
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unregister_uploaded_part_raises_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.unregister_uploaded_part(uuid.uuid4(), part_size_bytes=-1)


@pytest.mark.asyncio
async def test_unregister_uploaded_part_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.unregister_uploaded_part(uuid.uuid4(), part_size_bytes=10)


@pytest.mark.asyncio
async def test_unregister_uploaded_part_success_with_refresh():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.unregister_uploaded_part(
        sess.id, part_size_bytes=10, refresh=True
    )
    sess.unregister_uploaded_part.assert_called_once_with(10)
    session.refresh.assert_awaited_once()
    assert res is sess


# ---------------------------------------------------------------------------
# Тесты: increment_uploaded_parts_count — дополнительные ветки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increment_uploaded_parts_count_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.increment_uploaded_parts_count(uuid.uuid4(), increment_by=1)


@pytest.mark.asyncio
async def test_increment_uploaded_parts_count_raises_when_exceeds_total():
    repo, session, result = make_repo()
    sess = make_upload_session(uploaded_parts_count=2, parts_count=2)
    result.scalar_one_or_none = MagicMock(return_value=sess)
    with pytest.raises(InvalidQueryError):
        await repo.increment_uploaded_parts_count(sess.id, increment_by=1)


@pytest.mark.asyncio
async def test_increment_uploaded_parts_count_transitions_to_uploading():
    repo, session, result = make_repo()
    sess = make_upload_session(
        uploaded_parts_count=0,
        parts_count=5,
        uploaded_bytes=0,
        file_size_bytes=1024,
        status=UploadSessionStatus.CREATED,
    )
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.increment_uploaded_parts_count(
        sess.id, increment_by=1, uploaded_bytes_increment=512, refresh=True
    )
    assert res.uploaded_parts_count == 1
    assert res.uploaded_bytes == 512
    assert res.status == UploadSessionStatus.UPLOADING
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_increment_uploaded_parts_count_caps_bytes_at_file_size():
    repo, session, result = make_repo()
    sess = make_upload_session(
        uploaded_parts_count=0,
        parts_count=5,
        uploaded_bytes=900,
        file_size_bytes=1024,
        status=UploadSessionStatus.UPLOADING,
    )
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.increment_uploaded_parts_count(
        sess.id, increment_by=1, uploaded_bytes_increment=500
    )
    assert res.uploaded_bytes == 1024


# ---------------------------------------------------------------------------
# Тесты: set_uploaded_parts_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_uploaded_parts_count_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.set_uploaded_parts_count(uuid.uuid4(), 1)


@pytest.mark.asyncio
async def test_set_uploaded_parts_count_success_with_bytes_and_refresh():
    repo, session, result = make_repo()
    sess = make_upload_session(parts_count=5, file_size_bytes=1024)
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.set_uploaded_parts_count(
        sess.id, 3, uploaded_bytes=512, refresh=True
    )
    assert res.uploaded_parts_count == 3
    assert res.uploaded_bytes == 512
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_uploaded_parts_count_without_bytes():
    repo, session, result = make_repo()
    sess = make_upload_session(parts_count=5, file_size_bytes=1024)
    result.scalar_one_or_none = MagicMock(return_value=sess)
    res = await repo.set_uploaded_parts_count(sess.id, 2)
    assert res.uploaded_parts_count == 2


# ---------------------------------------------------------------------------
# Тесты: recalculate_progress_from_parts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recalculate_progress_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.recalculate_progress_from_parts(uuid.uuid4())


@pytest.mark.asyncio
async def test_recalculate_progress_updates_and_transitions():
    repo, session, result = make_repo()
    sess = make_upload_session(status=UploadSessionStatus.CREATED)
    result.scalar_one_or_none = MagicMock(return_value=sess)
    result.one = MagicMock(return_value=(3, 1500))
    res = await repo.recalculate_progress_from_parts(sess.id, refresh=True)
    assert res.uploaded_parts_count == 3
    assert res.uploaded_bytes == 1500
    assert res.status == UploadSessionStatus.UPLOADING
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_recalculate_progress_keeps_status_when_zero_parts():
    repo, session, result = make_repo()
    sess = make_upload_session(status=UploadSessionStatus.CREATED)
    result.scalar_one_or_none = MagicMock(return_value=sess)
    result.one = MagicMock(return_value=(0, 0))
    res = await repo.recalculate_progress_from_parts(sess.id)
    assert res.uploaded_parts_count == 0
    assert res.status == UploadSessionStatus.CREATED


@pytest.mark.asyncio
async def test_recalculate_progress_maps_sqlalchemy_error():
    repo, session, result = make_repo()
    sess = make_upload_session()
    # Первый execute возвращает сессию для обновления, второй бросает ошибку
    first_result = MagicMock()
    first_result.scalar_one_or_none = MagicMock(return_value=sess)
    session.execute = AsyncMock(
        side_effect=[first_result, SQLAlchemyError("boom")]
    )
    with pytest.raises(RepositoryError):
        await repo.recalculate_progress_from_parts(sess.id)


# ---------------------------------------------------------------------------
# Тесты: find_expired_sessions с явными статусами / фильтры find_unfinished
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_expired_sessions_with_statuses_and_moment():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_expired_sessions(
        moment=datetime.now(UTC),
        statuses=[UploadSessionStatus.UPLOADING],
    )
    assert res == []


@pytest.mark.asyncio
async def test_find_unfinished_sessions_with_filters():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_unfinished_sessions(
        user_id=uuid.uuid4(), parent_node_id=uuid.uuid4()
    )
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: find_ready_to_complete_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_ready_to_complete_sessions_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_ready_to_complete_sessions(moment=datetime.now(UTC))
    assert res == []


@pytest.mark.asyncio
async def test_find_ready_to_complete_sessions_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.find_ready_to_complete_sessions(limit=0)


# ---------------------------------------------------------------------------
# Тесты: can_complete_session false / can_receive_parts true
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_can_complete_session_returns_false_when_cannot():
    repo, session, result = make_repo()
    sess = make_upload_session()
    sess.can_be_completed_at = MagicMock(return_value=False)
    session.get = AsyncMock(return_value=sess)
    res = await repo.can_complete_session(sess.id)
    assert res is False


@pytest.mark.asyncio
async def test_can_receive_parts_returns_true():
    repo, session, result = make_repo()
    sess = make_upload_session()
    sess.can_receive_parts_at = MagicMock(return_value=True)
    session.get = AsyncMock(return_value=sess)
    res = await repo.can_receive_parts(sess.id)
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: count_user_active_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_active_sessions_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=4)
    count = await repo.count_user_active_sessions(
        uuid.uuid4(), moment=datetime.now(UTC)
    )
    assert count == 4


# ---------------------------------------------------------------------------
# Тесты: search_user_sessions all — ветки фильтров
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_user_sessions_with_all_filters():
    repo, session, result = make_repo()
    sess = make_upload_session()
    result.scalars.return_value.all.return_value = [sess]
    now = datetime.now(UTC)
    res = await repo.search_user_sessions(
        user_id=uuid.uuid4(),
        parent_node_id=uuid.uuid4(),
        status=UploadSessionStatus.CREATED,
        filename_query="  Test  ",
        created_from=now - timedelta(days=1),
        created_to=now,
        expires_before=now + timedelta(hours=1),
        sort_by="expires_at",
        sort_desc=False,
    )
    assert res == [sess]


@pytest.mark.asyncio
async def test_search_user_sessions_exclude_terminal_branch():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_user_sessions(
        user_id=uuid.uuid4(),
        include_terminal=False,
        sort_by="unknown_field",
    )
    assert res == []


@pytest.mark.asyncio
async def test_search_user_sessions_sort_by_file_name():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_user_sessions(
        user_id=uuid.uuid4(),
        sort_by="file_name",
    )
    assert res == []


@pytest.mark.asyncio
async def test_search_user_sessions_sort_by_status():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_user_sessions(
        user_id=uuid.uuid4(),
        sort_by="status",
    )
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: count_user_sessions_filtered all — ветки фильтров
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_sessions_filtered_with_all_filters():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=2)
    now = datetime.now(UTC)
    count = await repo.count_user_sessions_filtered(
        user_id=uuid.uuid4(),
        parent_node_id=uuid.uuid4(),
        status=UploadSessionStatus.CREATED,
        filename_query="file",
        created_from=now - timedelta(days=1),
        created_to=now,
        expires_before=now,
    )
    assert count == 2


@pytest.mark.asyncio
async def test_count_user_sessions_filtered_exclude_terminal():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    count = await repo.count_user_sessions_filtered(
        user_id=uuid.uuid4(),
        include_terminal=False,
    )
    assert count == 0


# ---------------------------------------------------------------------------
# Тесты: _ensure_user_exists / _ensure_parent_node_exists — ветки ошибок
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_user_exists_maps_sqlalchemy_error():
    repo, session, result = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._ensure_user_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_user_exists_passes_when_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=make_upload_session())
    await repo._ensure_user_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_parent_node_exists_maps_sqlalchemy_error():
    repo, session, result = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._ensure_parent_node_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_parent_node_exists_raises_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo._ensure_parent_node_exists(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: _validate_session_values exhaustive branches
# ---------------------------------------------------------------------------

def _valid_values(**overrides):
    base = dict(
        file_name="test.txt",
        file_size_bytes=1024,
        part_size_bytes=512,
        parts_count=2,
        uploaded_parts_count=0,
        uploaded_bytes=0,
        storage_bucket="bucket",
        storage_key="key",
        upload_id="uid",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "overrides",
    [
        {"file_name": "x" * 256},
        {"part_size_bytes": 0},
        {"parts_count": 0},
        {"uploaded_parts_count": -1},
        {"uploaded_parts_count": 5, "parts_count": 2},
        {"uploaded_bytes": -1},
        {"uploaded_bytes": 5000, "file_size_bytes": 1024},
        {"storage_bucket": ""},
        {"storage_key": ""},
        {"upload_id": ""},
    ],
)
def test_validate_session_values_raises(overrides):
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_session_values(**_valid_values(**overrides))


def test_validate_session_values_passes_for_valid():
    repo, session, result = make_repo()
    repo._validate_session_values(**_valid_values())


# ---------------------------------------------------------------------------
# Тесты: _validate_progress_values branches
# ---------------------------------------------------------------------------

def test_validate_progress_values_raises_negative_parts():
    repo, session, result = make_repo()
    sess = make_upload_session(parts_count=5, file_size_bytes=1024)
    with pytest.raises(InvalidQueryError):
        repo._validate_progress_values(
            upload_session=sess,
            uploaded_parts_count=-1,
            uploaded_bytes=None,
            operation="op",
        )


def test_validate_progress_values_raises_exceeds_parts():
    repo, session, result = make_repo()
    sess = make_upload_session(parts_count=5, file_size_bytes=1024)
    with pytest.raises(InvalidQueryError):
        repo._validate_progress_values(
            upload_session=sess,
            uploaded_parts_count=6,
            uploaded_bytes=None,
            operation="op",
        )


def test_validate_progress_values_raises_negative_bytes():
    repo, session, result = make_repo()
    sess = make_upload_session(parts_count=5, file_size_bytes=1024)
    with pytest.raises(InvalidQueryError):
        repo._validate_progress_values(
            upload_session=sess,
            uploaded_parts_count=1,
            uploaded_bytes=-1,
            operation="op",
        )


def test_validate_progress_values_raises_bytes_exceed_file_size():
    repo, session, result = make_repo()
    sess = make_upload_session(parts_count=5, file_size_bytes=1024)
    with pytest.raises(InvalidQueryError):
        repo._validate_progress_values(
            upload_session=sess,
            uploaded_parts_count=1,
            uploaded_bytes=5000,
            operation="op",
        )


def test_validate_progress_values_passes():
    repo, session, result = make_repo()
    sess = make_upload_session(parts_count=5, file_size_bytes=1024)
    repo._validate_progress_values(
        upload_session=sess,
        uploaded_parts_count=2,
        uploaded_bytes=512,
        operation="op",
    )


# ---------------------------------------------------------------------------
# Тесты: _base_select
# ---------------------------------------------------------------------------

def test_base_select_returns_select():
    repo, session, result = make_repo()
    stmt = repo._base_select()
    assert stmt is not None
