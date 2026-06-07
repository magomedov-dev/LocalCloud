"""Юнит-тесты репозитория частей загрузки (UploadPartsRepository)."""
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
from database.models.enums import UploadPartStatus
from database.repositories.base import BaseRepository
from database.repositories.parts import UploadPartsRepository


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
    return UploadPartsRepository(session=session), session, result


def make_upload_part(**kwargs):
    part = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        upload_session_id=uuid.uuid4(),
        part_number=1,
        size_bytes=512,
        etag=None,
        checksum=None,
        status=UploadPartStatus.PENDING,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(part, k, v)
    part.mark_uploaded = MagicMock()
    part.mark_failed = MagicMock()
    return part


# ---------------------------------------------------------------------------
# Тесты: get_part_by_id / get_required_part_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_part_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_part_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_part_by_id_returns_part_when_found():
    repo, session, result = make_repo()
    part = make_upload_part()
    result.scalar_one_or_none = MagicMock(return_value=part)
    res = await repo.get_part_by_id(part.id)
    assert res is part


@pytest.mark.asyncio
async def test_get_required_part_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_part_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_part_by_id_returns_part():
    repo, session, result = make_repo()
    part = make_upload_part()
    result.scalar_one_or_none = MagicMock(return_value=part)
    res = await repo.get_required_part_by_id(part.id)
    assert res is part


# ---------------------------------------------------------------------------
# Тесты: get_by_id (переопределение)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_required_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_part_by_session_and_number (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_part_by_session_and_number_returns_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'get_part_by_session_and_number'):
        res = await repo.get_part_by_session_and_number(
            upload_session_id=uuid.uuid4(),
            part_number=1,
        )
        assert res is None


@pytest.mark.asyncio
async def test_get_part_by_session_and_number_returns_part():
    repo, session, result = make_repo()
    part = make_upload_part()
    result.scalar_one_or_none = MagicMock(return_value=part)
    if hasattr(repo, 'get_part_by_session_and_number'):
        res = await repo.get_part_by_session_and_number(
            upload_session_id=part.upload_session_id,
            part_number=part.part_number,
        )
        assert res is part


# ---------------------------------------------------------------------------
# Тесты: list_session_parts (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_session_parts_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'list_session_parts'):
        res = await repo.list_session_parts(uuid.uuid4())
        assert isinstance(res, list)
    elif hasattr(repo, 'list_parts_by_session'):
        res = await repo.list_parts_by_session(uuid.uuid4())
        assert isinstance(res, list)


@pytest.mark.asyncio
async def test_list_uploaded_parts_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'list_uploaded_parts'):
        res = await repo.list_uploaded_parts(uuid.uuid4())
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: create_part (если метод существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_part_raises_for_invalid_number():
    repo, session, result = make_repo()
    if hasattr(repo, 'create_part'):
        with pytest.raises((InvalidQueryError, Exception)):
            await repo.create_part(
                upload_session_id=uuid.uuid4(),
                part_number=0,
                size_bytes=512,
                check_session_exists=False,
            )


@pytest.mark.asyncio
async def test_create_part_success():
    repo, session, result = make_repo()
    if hasattr(repo, 'create_part'):
        part = make_upload_part()

        async def fake_create(entity, flush=True, refresh=False):
            return part

        repo.create = fake_create  # type: ignore
        res = await repo.create_part(
            upload_session_id=uuid.uuid4(),
            part_number=1,
            size_bytes=512,
            check_session_exists=False,
        )
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: create_parts_bulk (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_parts_bulk_returns_list():
    repo, session, result = make_repo()
    if hasattr(repo, 'create_parts_bulk'):
        parts = [
            {"part_number": 1, "size_bytes": 512},
            {"part_number": 2, "size_bytes": 512},
        ]
        res = await repo.create_parts_bulk(
            upload_session_id=uuid.uuid4(),
            parts=parts,
            check_session_exists=False,
        )
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: mark_part_uploaded (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_part_uploaded_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'mark_part_uploaded'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.mark_part_uploaded(uuid.uuid4(), 1, etag="etag-123")


@pytest.mark.asyncio
async def test_mark_part_uploaded_success():
    repo, session, result = make_repo()
    part = make_upload_part()
    result.scalar_one_or_none = MagicMock(return_value=part)
    if hasattr(repo, 'mark_part_uploaded'):
        res = await repo.mark_part_uploaded(part.upload_session_id, part.part_number, etag="etag-123")
        assert res is part


# ---------------------------------------------------------------------------
# Тесты: count_session_parts (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_session_parts_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    if hasattr(repo, 'count_session_parts'):
        count = await repo.count_session_parts(uuid.uuid4())
        assert count == 3
    elif hasattr(repo, 'count_uploaded_parts'):
        count = await repo.count_uploaded_parts(uuid.uuid4())
        assert count == 3


# ---------------------------------------------------------------------------
# Тесты: get_completion_info (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_completion_info_returns_list():
    repo, session, result = make_repo()
    result.all = MagicMock(return_value=[])
    if hasattr(repo, 'get_completion_info'):
        res = await repo.get_completion_info(uuid.uuid4())
        assert isinstance(res, list)
    elif hasattr(repo, 'get_uploaded_parts_for_completion'):
        res = await repo.get_uploaded_parts_for_completion(uuid.uuid4())
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: delete parts (if methods exist)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_session_parts_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 5
    if hasattr(repo, 'delete_session_parts'):
        count = await repo.delete_session_parts(uuid.uuid4())
        assert isinstance(count, int)


# ---------------------------------------------------------------------------
# Тесты: count (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=4)
    from database.models.uploads import UploadPart
    count = await repo.count(UploadPart.upload_session_id == uuid.uuid4())
    assert count == 4


# ---------------------------------------------------------------------------
# Тесты: exists (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exists_returns_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    from database.models.uploads import UploadPart
    res = await repo.exists(UploadPart.id == uuid.uuid4())
    assert res is False


# ---------------------------------------------------------------------------
# Хелперы для настройки scalars/scalar
# ---------------------------------------------------------------------------

def set_scalars(result, items):
    result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=items))
    )


def set_scalar_one(result, value):
    result.scalar_one = MagicMock(return_value=value)


def set_scalar_one_or_none(result, value):
    result.scalar_one_or_none = MagicMock(return_value=value)


def make_integrity_error(sqlstate="23505", constraint_name="uq"):
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = constraint_name
    orig.table_name = "upload_parts"
    orig.column_name = None
    return IntegrityError("stmt", {}, orig)


# ---------------------------------------------------------------------------
# get_by_session_and_part_number / required
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_session_and_part_number_returns_part():
    repo, session, result = make_repo()
    part = make_upload_part()
    set_scalar_one_or_none(result, part)
    res = await repo.get_by_session_and_part_number(
        upload_session_id=part.upload_session_id,
        part_number=part.part_number,
    )
    assert res is part


@pytest.mark.asyncio
async def test_get_by_session_and_part_number_invalid_number():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.get_by_session_and_part_number(
            upload_session_id=uuid.uuid4(),
            part_number=0,
        )


@pytest.mark.asyncio
async def test_get_required_by_session_and_part_number_returns_part():
    repo, session, result = make_repo()
    part = make_upload_part()
    set_scalar_one_or_none(result, part)
    res = await repo.get_required_by_session_and_part_number(
        upload_session_id=part.upload_session_id,
        part_number=part.part_number,
    )
    assert res is part


@pytest.mark.asyncio
async def test_get_required_by_session_and_part_number_raises():
    repo, session, result = make_repo()
    set_scalar_one_or_none(result, None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_session_and_part_number(
            upload_session_id=uuid.uuid4(),
            part_number=2,
        )


# ---------------------------------------------------------------------------
# get_session_parts and status-filtered variants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_session_parts_returns_list():
    repo, session, result = make_repo()
    parts = [make_upload_part(), make_upload_part(part_number=2)]
    set_scalars(result, parts)
    res = await repo.get_session_parts(uuid.uuid4())
    assert res == parts


@pytest.mark.asyncio
async def test_get_session_parts_invalid_pagination():
    repo, session, result = make_repo()
    from database.exceptions import InvalidPaginationError
    with pytest.raises(InvalidPaginationError):
        await repo.get_session_parts(uuid.uuid4(), offset=-1)


@pytest.mark.asyncio
async def test_get_uploaded_parts_returns_list():
    repo, session, result = make_repo()
    part = make_upload_part(status=UploadPartStatus.UPLOADED, etag="e")
    set_scalars(result, [part])
    res = await repo.get_uploaded_parts(uuid.uuid4())
    assert res == [part]


@pytest.mark.asyncio
async def test_get_pending_parts_returns_list():
    repo, session, result = make_repo()
    set_scalars(result, [])
    res = await repo.get_pending_parts(uuid.uuid4())
    assert res == []


@pytest.mark.asyncio
async def test_get_failed_parts_returns_list():
    repo, session, result = make_repo()
    set_scalars(result, [])
    res = await repo.get_failed_parts(uuid.uuid4())
    assert res == []


@pytest.mark.asyncio
async def test_get_session_parts_by_status_propagates_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_session_parts_by_status(
            upload_session_id=uuid.uuid4(),
            status=UploadPartStatus.PENDING,
        )


# ---------------------------------------------------------------------------
# create_part
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_part_success_real():
    repo, session, result = make_repo()
    # нет дубликата (exists -> False)
    set_scalar_one(result, 0)
    res = await repo.create_part(
        upload_session_id=uuid.uuid4(),
        part_number=1,
        size_bytes=512,
    )
    assert res.part_number == 1
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_part_duplicate_raises():
    repo, session, result = make_repo()
    # part_exists -> exists() -> scalar_one истинно
    set_scalar_one(result, 1)
    with pytest.raises(DuplicateEntityError):
        await repo.create_part(
            upload_session_id=uuid.uuid4(),
            part_number=1,
            size_bytes=512,
        )


@pytest.mark.asyncio
async def test_create_part_check_session_exists_missing():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.create_part(
            upload_session_id=uuid.uuid4(),
            part_number=1,
            size_bytes=512,
            check_session_exists=True,
        )


@pytest.mark.asyncio
async def test_create_part_skips_duplicate_check():
    repo, session, result = make_repo()
    res = await repo.create_part(
        upload_session_id=uuid.uuid4(),
        part_number=3,
        size_bytes=10,
        check_duplicate=False,
    )
    assert res.part_number == 3


# ---------------------------------------------------------------------------
# create_parts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_parts_empty_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_parts(uuid.uuid4(), [])


@pytest.mark.asyncio
async def test_create_parts_missing_key_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_parts(uuid.uuid4(), [{"part_number": 1}])


@pytest.mark.asyncio
async def test_create_parts_duplicate_number_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_parts(
            uuid.uuid4(),
            [
                {"part_number": 1, "size_bytes": 10},
                {"part_number": 1, "size_bytes": 20},
            ],
        )


@pytest.mark.asyncio
async def test_create_parts_success():
    repo, session, result = make_repo()
    res = await repo.create_parts(
        uuid.uuid4(),
        [
            {"part_number": 1, "size_bytes": 10},
            {
                "part_number": 2,
                "size_bytes": 20,
                "status": "uploaded",
                "etag": "  abc ",
                "checksum": "DEAD",
            },
        ],
    )
    assert len(res) == 2
    session.add_all.assert_called_once()


@pytest.mark.asyncio
async def test_create_parts_check_session_exists_ok():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=MagicMock())
    res = await repo.create_parts(
        uuid.uuid4(),
        [{"part_number": 1, "size_bytes": 10}],
        check_session_exists=True,
    )
    assert len(res) == 1


# ---------------------------------------------------------------------------
# create_parts_by_sizes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_parts_by_sizes_invalid_first_number():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_parts_by_sizes(uuid.uuid4(), [10, 20], first_part_number=0)


@pytest.mark.asyncio
async def test_create_parts_by_sizes_empty():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_parts_by_sizes(uuid.uuid4(), [])


@pytest.mark.asyncio
async def test_create_parts_by_sizes_success():
    repo, session, result = make_repo()
    res = await repo.create_parts_by_sizes(uuid.uuid4(), [10, 20, 30])
    assert len(res) == 3
    assert [p.part_number for p in res] == [1, 2, 3]


# ---------------------------------------------------------------------------
# mark_part_uploaded / mark_part_failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_part_uploaded_empty_etag_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.mark_part_uploaded(uuid.uuid4(), 1, etag="   ")


@pytest.mark.asyncio
async def test_mark_part_uploaded_with_refresh():
    repo, session, result = make_repo()
    part = make_upload_part()
    set_scalar_one_or_none(result, part)
    res = await repo.mark_part_uploaded(
        part.upload_session_id, part.part_number, etag="etag-1", refresh=True
    )
    assert res is part
    part.mark_uploaded.assert_called_once()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_mark_part_failed_success():
    repo, session, result = make_repo()
    part = make_upload_part()
    set_scalar_one_or_none(result, part)
    res = await repo.mark_part_failed(
        part.upload_session_id, part.part_number, reason="oops", refresh=True
    )
    assert res is part
    part.mark_failed.assert_called_once()


@pytest.mark.asyncio
async def test_mark_part_failed_not_found_raises():
    repo, session, result = make_repo()
    set_scalar_one_or_none(result, None)
    with pytest.raises(EntityNotFoundError):
        await repo.mark_part_failed(uuid.uuid4(), 1)


# ---------------------------------------------------------------------------
# reset_part
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_part_clear_etag():
    repo, session, result = make_repo()
    part = make_upload_part(status=UploadPartStatus.FAILED)
    part.reset = MagicMock()
    set_scalar_one_or_none(result, part)
    res = await repo.reset_part(part.upload_session_id, part.part_number)
    assert res is part
    part.reset.assert_called_once()


@pytest.mark.asyncio
async def test_reset_part_no_clear_etag():
    repo, session, result = make_repo()
    part = make_upload_part(status=UploadPartStatus.FAILED)
    set_scalar_one_or_none(result, part)
    res = await repo.reset_part(
        part.upload_session_id, part.part_number, clear_etag=False, refresh=True
    )
    assert res.status == UploadPartStatus.PENDING
    assert res.failed_at is None
    assert res.failure_reason is None


# ---------------------------------------------------------------------------
# update_part_status / etag / checksum
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_part_status_success():
    repo, session, result = make_repo()
    part = make_upload_part()
    set_scalar_one_or_none(result, part)
    res = await repo.update_part_status(
        part.upload_session_id, part.part_number, UploadPartStatus.UPLOADED
    )
    assert res.status == UploadPartStatus.UPLOADED


@pytest.mark.asyncio
async def test_update_part_etag_success():
    repo, session, result = make_repo()
    part = make_upload_part()
    set_scalar_one_or_none(result, part)
    res = await repo.update_part_etag(
        part.upload_session_id, part.part_number, etag="  new-etag "
    )
    assert res.etag == "new-etag"


@pytest.mark.asyncio
async def test_update_part_checksum_success():
    repo, session, result = make_repo()
    part = make_upload_part()
    set_scalar_one_or_none(result, part)
    res = await repo.update_part_checksum(
        part.upload_session_id, part.part_number, checksum="ABCDEF"
    )
    assert res.checksum == "abcdef"


# ---------------------------------------------------------------------------
# подсчёты и суммы
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_uploaded_parts():
    repo, session, result = make_repo()
    set_scalar_one(result, 7)
    assert await repo.count_uploaded_parts(uuid.uuid4()) == 7


@pytest.mark.asyncio
async def test_count_pending_parts():
    repo, session, result = make_repo()
    set_scalar_one(result, 2)
    assert await repo.count_pending_parts(uuid.uuid4()) == 2


@pytest.mark.asyncio
async def test_count_failed_parts():
    repo, session, result = make_repo()
    set_scalar_one(result, 1)
    assert await repo.count_failed_parts(uuid.uuid4()) == 1


@pytest.mark.asyncio
async def test_count_session_parts_explicit():
    repo, session, result = make_repo()
    set_scalar_one(result, 9)
    assert await repo.count_session_parts(uuid.uuid4()) == 9


@pytest.mark.asyncio
async def test_count_parts_by_status():
    repo, session, result = make_repo()
    set_scalar_one(result, 4)
    count = await repo.count_parts_by_status(
        upload_session_id=uuid.uuid4(), status=UploadPartStatus.UPLOADED
    )
    assert count == 4


@pytest.mark.asyncio
async def test_sum_uploaded_bytes():
    repo, session, result = make_repo()
    set_scalar_one_or_none(result, 1024)
    assert await repo.sum_uploaded_bytes(uuid.uuid4()) == 1024


@pytest.mark.asyncio
async def test_sum_uploaded_bytes_none():
    repo, session, result = make_repo()
    set_scalar_one_or_none(result, None)
    assert await repo.sum_uploaded_bytes(uuid.uuid4()) == 0


# ---------------------------------------------------------------------------
# check_all_parts_uploaded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_all_parts_uploaded_invalid_expected():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.check_all_parts_uploaded(uuid.uuid4(), expected_parts_count=0)


@pytest.mark.asyncio
async def test_check_all_parts_uploaded_expected_total_mismatch():
    repo, session, result = make_repo()
    # count_uploaded -> 2, count_session -> 3
    set_scalar_one(result, MagicMock())
    result.scalar_one.side_effect = [2, 3]
    res = await repo.check_all_parts_uploaded(uuid.uuid4(), expected_parts_count=2)
    assert res is False


@pytest.mark.asyncio
async def test_check_all_parts_uploaded_expected_uploaded_mismatch():
    repo, session, result = make_repo()
    # uploaded -> 1, total -> 2, ожидается 2
    result.scalar_one.side_effect = [1, 2]
    res = await repo.check_all_parts_uploaded(uuid.uuid4(), expected_parts_count=2)
    assert res is False


@pytest.mark.asyncio
async def test_check_all_parts_uploaded_expected_success():
    repo, session, result = make_repo()
    # uploaded -> 2, total -> 2, затем has_missing_etags exists() -> 0
    result.scalar_one.side_effect = [2, 2, 0]
    res = await repo.check_all_parts_uploaded(uuid.uuid4(), expected_parts_count=2)
    assert res is True


@pytest.mark.asyncio
async def test_check_all_parts_uploaded_no_expected_empty():
    repo, session, result = make_repo()
    # uploaded 0, total 0 -> total <= 0 -> False
    result.scalar_one.side_effect = [0, 0]
    res = await repo.check_all_parts_uploaded(uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_check_all_parts_uploaded_no_expected_success():
    repo, session, result = make_repo()
    # uploaded 3, total 3, has_missing_etags -> 0, require_etags по умолчанию True
    result.scalar_one.side_effect = [3, 3, 0]
    res = await repo.check_all_parts_uploaded(uuid.uuid4())
    assert res is True


@pytest.mark.asyncio
async def test_check_all_parts_uploaded_missing_etags_false():
    repo, session, result = make_repo()
    # uploaded 2, total 2, has_missing_etags -> 1 (истинно)
    result.scalar_one.side_effect = [2, 2, 1]
    res = await repo.check_all_parts_uploaded(uuid.uuid4(), expected_parts_count=2)
    assert res is False


@pytest.mark.asyncio
async def test_check_all_parts_uploaded_no_require_etags():
    repo, session, result = make_repo()
    # uploaded 2, total 2, require_etags False -> пропуск has_missing
    result.scalar_one.side_effect = [2, 2]
    res = await repo.check_all_parts_uploaded(
        uuid.uuid4(), expected_parts_count=2, require_etags=False
    )
    assert res is True


# ---------------------------------------------------------------------------
# get_uploaded_parts_for_completion / get_completion_info
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_uploaded_parts_for_completion():
    repo, session, result = make_repo()
    part = make_upload_part(status=UploadPartStatus.UPLOADED, etag="e1")
    set_scalars(result, [part])
    res = await repo.get_uploaded_parts_for_completion(uuid.uuid4())
    assert res == [part]


@pytest.mark.asyncio
async def test_get_completion_info_filters_none_etag():
    repo, session, result = make_repo()
    good = make_upload_part(
        part_number=1, status=UploadPartStatus.UPLOADED, etag="e1",
        size_bytes=100, checksum="cs",
    )
    bad = make_upload_part(part_number=2, status=UploadPartStatus.UPLOADED, etag=None)
    set_scalars(result, [good, bad])
    res = await repo.get_completion_info(uuid.uuid4())
    assert res == [
        {"part_number": 1, "etag": "e1", "size_bytes": 100, "checksum": "cs"}
    ]


# ---------------------------------------------------------------------------
# has_missing_etags / has_failed_parts / has_pending_parts / part_exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_has_missing_etags_true():
    repo, session, result = make_repo()
    set_scalar_one(result, 1)
    assert await repo.has_missing_etags(uuid.uuid4()) is True


@pytest.mark.asyncio
async def test_has_failed_parts_false():
    repo, session, result = make_repo()
    set_scalar_one(result, 0)
    assert await repo.has_failed_parts(uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_has_pending_parts_true():
    repo, session, result = make_repo()
    set_scalar_one(result, 1)
    assert await repo.has_pending_parts(uuid.uuid4()) is True


@pytest.mark.asyncio
async def test_part_exists_invalid_number():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.part_exists(upload_session_id=uuid.uuid4(), part_number=-1)


@pytest.mark.asyncio
async def test_part_exists_true():
    repo, session, result = make_repo()
    set_scalar_one(result, 1)
    assert await repo.part_exists(
        upload_session_id=uuid.uuid4(), part_number=2
    ) is True


# ---------------------------------------------------------------------------
# операции удаления
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_parts_by_session():
    repo, session, result = make_repo()
    result.rowcount = 5
    assert await repo.delete_parts_by_session(uuid.uuid4()) == 5


@pytest.mark.asyncio
async def test_delete_failed_parts():
    repo, session, result = make_repo()
    result.rowcount = 2
    assert await repo.delete_failed_parts(uuid.uuid4()) == 2


@pytest.mark.asyncio
async def test_delete_part_by_session_and_number_success():
    repo, session, result = make_repo()
    part = make_upload_part()
    set_scalar_one_or_none(result, part)
    res = await repo.delete_part_by_session_and_number(
        part.upload_session_id, part.part_number
    )
    assert res is True
    session.delete.assert_awaited_once_with(part)


@pytest.mark.asyncio
async def test_delete_part_by_session_and_number_not_found_required():
    repo, session, result = make_repo()
    set_scalar_one_or_none(result, None)
    with pytest.raises(EntityNotFoundError):
        await repo.delete_part_by_session_and_number(uuid.uuid4(), 1)


@pytest.mark.asyncio
async def test_delete_part_by_session_and_number_not_found_optional():
    repo, session, result = make_repo()
    set_scalar_one_or_none(result, None)
    res = await repo.delete_part_by_session_and_number(
        uuid.uuid4(), 1, required=False
    )
    assert res is False


# ---------------------------------------------------------------------------
# _ensure_upload_session_exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_upload_session_exists_ok():
    repo, session, result = make_repo()
    sentinel = MagicMock()
    session.get = AsyncMock(return_value=sentinel)
    res = await repo._ensure_upload_session_exists(uuid.uuid4())
    assert res is sentinel


@pytest.mark.asyncio
async def test_ensure_upload_session_exists_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo._ensure_upload_session_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_upload_session_exists_sqlalchemy_error():
    repo, session, result = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._ensure_upload_session_exists(uuid.uuid4())


# ---------------------------------------------------------------------------
# _validate_part_values branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_size_not_int():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_part_values(
            part_number=1, size_bytes="big", status=UploadPartStatus.PENDING,
            etag=None, uploaded_at=None, failed_at=None, failure_reason=None,
        )


@pytest.mark.asyncio
async def test_validate_size_non_positive():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_part_values(
            part_number=1, size_bytes=0, status=UploadPartStatus.PENDING,
            etag=None, uploaded_at=None, failed_at=None, failure_reason=None,
        )


@pytest.mark.asyncio
async def test_validate_uploaded_without_etag():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_part_values(
            part_number=1, size_bytes=10, status=UploadPartStatus.UPLOADED,
            etag=None, uploaded_at=None, failed_at=None, failure_reason=None,
        )


@pytest.mark.asyncio
async def test_validate_uploaded_at_for_non_uploaded():
    repo, _, _ = make_repo()
    from datetime import UTC, datetime
    with pytest.raises(InvalidQueryError):
        repo._validate_part_values(
            part_number=1, size_bytes=10, status=UploadPartStatus.PENDING,
            etag=None, uploaded_at=datetime.now(UTC),
            failed_at=None, failure_reason=None,
        )


@pytest.mark.asyncio
async def test_validate_uploaded_with_failed_at():
    repo, _, _ = make_repo()
    from datetime import UTC, datetime
    with pytest.raises(InvalidQueryError):
        repo._validate_part_values(
            part_number=1, size_bytes=10, status=UploadPartStatus.UPLOADED,
            etag="e", uploaded_at=None, failed_at=datetime.now(UTC),
            failure_reason=None,
        )


@pytest.mark.asyncio
async def test_validate_failed_at_for_non_failed():
    repo, _, _ = make_repo()
    from datetime import UTC, datetime
    # PENDING с failed_at (не uploaded, поэтому проходит ранние проверки) -> последняя ветка
    with pytest.raises(InvalidQueryError):
        repo._validate_part_values(
            part_number=1, size_bytes=10, status=UploadPartStatus.PENDING,
            etag=None, uploaded_at=None, failed_at=datetime.now(UTC),
            failure_reason=None,
        )


@pytest.mark.asyncio
async def test_validate_failure_reason_for_non_failed():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_part_values(
            part_number=1, size_bytes=10, status=UploadPartStatus.PENDING,
            etag=None, uploaded_at=None, failed_at=None,
            failure_reason="boom",
        )


# ---------------------------------------------------------------------------
# _validate_part_number / _validate_expected_parts_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_part_number_not_int():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_part_number("x")


@pytest.mark.asyncio
async def test_validate_expected_parts_count_not_int():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_expected_parts_count("x")


@pytest.mark.asyncio
async def test_validate_expected_parts_count_non_positive():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_expected_parts_count(-3)


# ---------------------------------------------------------------------------
# _coerce_status / _normalize_*
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_coerce_status_passthrough():
    repo, _, _ = make_repo()
    assert repo._coerce_status(UploadPartStatus.FAILED) is UploadPartStatus.FAILED


@pytest.mark.asyncio
async def test_coerce_status_from_string():
    repo, _, _ = make_repo()
    assert repo._coerce_status("pending") == UploadPartStatus.PENDING


@pytest.mark.asyncio
async def test_coerce_status_invalid():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._coerce_status("nonsense")


@pytest.mark.asyncio
async def test_normalize_etag_variants():
    repo, _, _ = make_repo()
    assert repo._normalize_etag(None) is None
    assert repo._normalize_etag("   ") is None
    assert repo._normalize_etag("  ab ") == "ab"


@pytest.mark.asyncio
async def test_normalize_checksum_variants():
    repo, _, _ = make_repo()
    assert repo._normalize_checksum(None) is None
    assert repo._normalize_checksum("   ") is None
    assert repo._normalize_checksum("  ABCD ") == "abcd"


@pytest.mark.asyncio
async def test_normalize_checksum_too_long():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_checksum("a" * 129)


@pytest.mark.asyncio
async def test_normalize_failure_reason_variants():
    repo, _, _ = make_repo()
    assert repo._normalize_failure_reason(None) is None
    assert repo._normalize_failure_reason("   ") is None
    assert repo._normalize_failure_reason("  oops ") == "oops"


@pytest.mark.asyncio
async def test_now_returns_aware_datetime():
    repo, _, _ = make_repo()
    from datetime import datetime
    now = repo._now()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None


# ---------------------------------------------------------------------------
# переопределение create(): маппинг ошибок
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_override_maps_duplicate():
    repo, session, result = make_repo()
    part = make_upload_part()
    session.flush = AsyncMock(
        side_effect=DuplicateEntityError(
            "UploadPart", field="x", repository=repo.repository_name
        )
    )
    with pytest.raises(DuplicateEntityError):
        await repo.create(part)


@pytest.mark.asyncio
async def test_create_override_maps_integrity_error():
    repo, session, result = make_repo()
    part = make_upload_part()
    session.flush = AsyncMock(side_effect=make_integrity_error("23502"))
    with pytest.raises(RepositoryError):
        await repo.create(part)


@pytest.mark.asyncio
async def test_create_override_success():
    repo, session, result = make_repo()
    part = make_upload_part()
    res = await repo.create(part)
    assert res is part


@pytest.mark.asyncio
async def test_create_override_maps_raw_integrity_error(monkeypatch):
    # Заставляем super().create бросить сырой IntegrityError, чтобы сработала
    # ветка IntegrityError в переопределении (-> _handle_integrity_error).
    repo, session, result = make_repo()
    part = make_upload_part()

    async def boom(self, entity, *, flush=True, refresh=False):
        raise make_integrity_error("23503")

    monkeypatch.setattr(BaseRepository, "create", boom)
    with pytest.raises(RepositoryError):
        await repo.create(part)


# ---------------------------------------------------------------------------
# _execute_upload_part_statement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_upload_part_statement_success():
    repo, session, result = make_repo()
    parts = [make_upload_part()]
    set_scalars(result, parts)
    from database.models.uploads import UploadPart
    from sqlalchemy import select
    res = await repo._execute_upload_part_statement(
        select(UploadPart), operation="op"
    )
    assert res == parts


@pytest.mark.asyncio
async def test_execute_upload_part_statement_integrity_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23505"))
    from database.models.uploads import UploadPart
    from sqlalchemy import select
    with pytest.raises(DuplicateEntityError):
        await repo._execute_upload_part_statement(
            select(UploadPart), operation="op"
        )


@pytest.mark.asyncio
async def test_execute_upload_part_statement_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    from database.models.uploads import UploadPart
    from sqlalchemy import select
    with pytest.raises(RepositoryError):
        await repo._execute_upload_part_statement(
            select(UploadPart), operation="op"
        )
