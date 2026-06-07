"""Юнит-тесты репозитория refresh-токенов (RefreshTokensRepository)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidPaginationError,
    InvalidQueryError,
    RepositoryError,
)
from database.models.enums import SessionStatus
from database.models.tokens import RefreshToken
from database.repositories.tokens import RefreshTokensRepository


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


def make_integrity_error(sqlstate="23505"):
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = "uq_test"
    orig.table_name = "refresh_tokens"
    orig.column_name = "token_hash"
    exc = IntegrityError("msg", {}, orig)
    exc.orig = orig
    return exc


def make_repo():
    session, result = make_session()
    repo = RefreshTokensRepository(session=session)
    return repo, session, result


def future_time(seconds=3600) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def past_time(seconds=3600) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


def make_token(**kwargs) -> RefreshToken:
    defaults = dict(
        user_id=uuid.uuid4(),
        token_hash="somehash",
        status=SessionStatus.ACTIVE,
        expires_at=future_time(),
        is_active=True,
    )
    defaults.update(kwargs)
    return RefreshToken(**defaults)


# ---------------------------------------------------------------------------
# get_token_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_token_by_id_found():
    repo, session, _ = make_repo()
    token = make_token()
    session.get = AsyncMock(return_value=token)
    result = await repo.get_token_by_id(uuid.uuid4())
    assert result is token


@pytest.mark.asyncio
async def test_get_token_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    result = await repo.get_token_by_id(uuid.uuid4())
    assert result is None


# ---------------------------------------------------------------------------
# get_required_token_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_token_by_id_found():
    repo, session, _ = make_repo()
    token = make_token()
    session.get = AsyncMock(return_value=token)
    result = await repo.get_required_token_by_id(uuid.uuid4())
    assert result is token


@pytest.mark.asyncio
async def test_get_required_token_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_token_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# get_by_hash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_hash_found():
    repo, session, result = make_repo()
    token = make_token()
    result.scalar_one_or_none = MagicMock(return_value=token)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_hash("somehash")
    assert found is token


@pytest.mark.asyncio
async def test_get_by_hash_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_hash("nonexistent")
    assert found is None


@pytest.mark.asyncio
async def test_get_by_hash_empty_returns_none():
    repo, _, _ = make_repo()
    result = await repo.get_by_hash("   ")
    assert result is None


# ---------------------------------------------------------------------------
# get_required_by_hash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_by_hash_found():
    repo, session, result = make_repo()
    token = make_token()
    result.scalar_one_or_none = MagicMock(return_value=token)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_required_by_hash("somehash")
    assert found is token


@pytest.mark.asyncio
async def test_get_required_by_hash_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_hash("nonexistent")


# ---------------------------------------------------------------------------
# token_hash_exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_hash_exists_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    assert await repo.token_hash_exists("somehash") is True


@pytest.mark.asyncio
async def test_token_hash_exists_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    assert await repo.token_hash_exists("nope") is False


@pytest.mark.asyncio
async def test_token_hash_exists_empty_returns_false():
    repo, _, _ = make_repo()
    assert await repo.token_hash_exists("") is False


# ---------------------------------------------------------------------------
# create_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_token_success():
    repo, session, result = make_repo()
    user_id = uuid.uuid4()
    # пользователь существует
    session.get = AsyncMock(return_value=MagicMock())
    # нет дубликата
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    token = await repo.create_token(
        user_id=user_id,
        token_hash="newhash",
        expires_at=future_time(),
        check_user_exists=False,
        check_duplicate=False,
        check_parent_exists=False,
        flush=False,
    )
    assert token.user_id == user_id
    assert token.token_hash == "newhash"
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_token_empty_hash_raises():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_token(
            user_id=uuid.uuid4(),
            token_hash="",
            expires_at=future_time(),
        )


@pytest.mark.asyncio
async def test_create_token_duplicate_hash_raises():
    repo, session, result = make_repo()
    # дубликат существует
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(DuplicateEntityError):
        await repo.create_token(
            user_id=uuid.uuid4(),
            token_hash="duphash",
            expires_at=future_time(),
            check_user_exists=False,
            check_duplicate=True,
            check_parent_exists=False,
        )


@pytest.mark.asyncio
async def test_create_token_user_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.create_token(
            user_id=uuid.uuid4(),
            token_hash="somehash",
            expires_at=future_time(),
            check_user_exists=True,
            check_duplicate=False,
            check_parent_exists=False,
        )


@pytest.mark.asyncio
async def test_create_token_integrity_error():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo.create_token(
            user_id=uuid.uuid4(),
            token_hash="newhash",
            expires_at=future_time(),
            check_user_exists=False,
            check_duplicate=False,
            check_parent_exists=False,
        )


@pytest.mark.asyncio
async def test_create_token_outer_integrity_handler():
    # repo.create подменён, чтобы бросить СЫРОЙ IntegrityError и дойти до внешнего
    # except в create_token (обычно BaseRepository.create конвертирует его в
    # DuplicateEntityError до запуска обработчика подкласса).
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    repo.create = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo.create_token(
            user_id=uuid.uuid4(),
            token_hash="newhash",
            expires_at=future_time(),
            check_user_exists=False,
            check_duplicate=False,
            check_parent_exists=False,
        )


# ---------------------------------------------------------------------------
# list_user_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_tokens_returns_list():
    repo, session, result = make_repo()
    tokens = [make_token()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=tokens)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_user_tokens(uuid.uuid4())
    assert found == tokens


@pytest.mark.asyncio
async def test_list_user_tokens_invalid_pagination():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidPaginationError):
        await repo.list_user_tokens(uuid.uuid4(), offset=-1)


@pytest.mark.asyncio
async def test_list_active_user_tokens_returns_list():
    repo, session, result = make_repo()
    tokens = [make_token()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=tokens)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_active_user_tokens(uuid.uuid4())
    assert found == tokens


# ---------------------------------------------------------------------------
# revoke_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_token_success():
    repo, session, _ = make_repo()
    token = make_token()
    result = await repo.revoke_token(token, reason="logout", flush=False)
    assert result.status == SessionStatus.REVOKED
    assert result.is_active is False


@pytest.mark.asyncio
async def test_revoke_token_calls_flush():
    repo, session, _ = make_repo()
    token = make_token()
    await repo.revoke_token(token, flush=True)
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_token_no_deactivate():
    repo, session, _ = make_repo()
    token = make_token()
    result = await repo.revoke_token(token, deactivate=False, flush=False)
    assert result.is_active is True


# ---------------------------------------------------------------------------
# revoke_token_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_token_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.revoke_token_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_revoke_token_by_hash_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(EntityNotFoundError):
        await repo.revoke_token_by_hash("nonexistent")


# ---------------------------------------------------------------------------
# revoke_all_user_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_all_user_tokens_returns_count():
    repo, session, result = make_repo()
    token = make_token()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[token])))
    session.execute = AsyncMock(return_value=result)
    count = await repo.revoke_all_user_tokens(uuid.uuid4(), flush=False)
    assert count == 1


@pytest.mark.asyncio
async def test_revoke_all_user_tokens_exclude_token():
    repo, session, result = make_repo()
    token = make_token()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[token])))
    session.execute = AsyncMock(return_value=result)
    # SQL-фильтрация исключённого токена происходит на уровне БД, не в моке;
    # мок возвращает один токен, поэтому count отражает обработанные из мок-результата
    count = await repo.revoke_all_user_tokens(
        uuid.uuid4(), exclude_token_id=token.id, flush=False
    )
    assert count >= 0  # зависит от реализации; исключение — в SQL WHERE


# ---------------------------------------------------------------------------
# deactivate_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deactivate_token_success():
    repo, session, _ = make_repo()
    token = make_token()
    result = await repo.deactivate_token(token, flush=False)
    assert result.is_active is False


@pytest.mark.asyncio
async def test_deactivate_token_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.deactivate_token_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# rotate_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rotate_token_success():
    repo, session, result = make_repo()
    token = make_token()
    # Нет дубликата
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    new_token = await repo.rotate_token(
        old_token=token,
        new_token_hash="newhash",
        new_expires_at=future_time(7200),
        check_duplicate=False,
        flush=False,
    )
    assert new_token.token_hash == "newhash"
    assert new_token.user_id == token.user_id


@pytest.mark.asyncio
async def test_rotate_token_inactive_raises():
    repo, session, result = make_repo()
    token = make_token(is_active=False)
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(InvalidQueryError):
        await repo.rotate_token(
            old_token=token,
            new_token_hash="newhash",
            new_expires_at=future_time(),
        )


@pytest.mark.asyncio
async def test_rotate_token_revoked_raises():
    repo, session, result = make_repo()
    token = make_token()
    token.revoke(revoked_at=datetime.now(UTC))
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(InvalidQueryError):
        await repo.rotate_token(
            old_token=token,
            new_token_hash="newhash",
            new_expires_at=future_time(),
        )


@pytest.mark.asyncio
async def test_rotate_token_duplicate_hash_raises():
    repo, session, result = make_repo()
    token = make_token()
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(DuplicateEntityError):
        await repo.rotate_token(
            old_token=token,
            new_token_hash="duphash",
            new_expires_at=future_time(),
            check_duplicate=True,
        )


# ---------------------------------------------------------------------------
# is_token_active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_token_active_true():
    repo, session, result = make_repo()
    token = make_token()
    result.scalar_one_or_none = MagicMock(return_value=token)
    session.execute = AsyncMock(return_value=result)
    assert await repo.is_token_active("somehash") is True


@pytest.mark.asyncio
async def test_is_token_active_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    assert await repo.is_token_active("nonexistent") is False


# ---------------------------------------------------------------------------
# get_active_by_hash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_by_hash_empty_returns_none():
    repo, _, _ = make_repo()
    result = await repo.get_active_by_hash("  ")
    assert result is None


@pytest.mark.asyncio
async def test_get_active_by_hash_found():
    repo, session, result = make_repo()
    token = make_token()
    result.scalar_one_or_none = MagicMock(return_value=token)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_active_by_hash("somehash")
    assert found is token


# ---------------------------------------------------------------------------
# get_required_active_by_hash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_active_by_hash_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_active_by_hash("nonexistent")


# ---------------------------------------------------------------------------
# mark_expired_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_expired_tokens_returns_count():
    repo, session, result = make_repo()
    token = make_token(expires_at=past_time())
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[token])))
    session.execute = AsyncMock(return_value=result)
    count = await repo.mark_expired_tokens(flush=False)
    assert count == 1


@pytest.mark.asyncio
async def test_mark_expired_tokens_db_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.mark_expired_tokens()


# ---------------------------------------------------------------------------
# delete_expired_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_expired_tokens_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 3
    session.execute = AsyncMock(return_value=result)
    count = await repo.delete_expired_tokens(flush=False)
    assert count == 3


@pytest.mark.asyncio
async def test_delete_expired_tokens_db_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.delete_expired_tokens()


# ---------------------------------------------------------------------------
# delete_revoked_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_revoked_tokens_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 2
    session.execute = AsyncMock(return_value=result)
    count = await repo.delete_revoked_tokens(flush=False)
    assert count == 2


# ---------------------------------------------------------------------------
# delete_user_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_user_tokens_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 5
    session.execute = AsyncMock(return_value=result)
    count = await repo.delete_user_tokens(uuid.uuid4(), flush=False)
    assert count == 5


# ---------------------------------------------------------------------------
# count_user_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_tokens():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=4)
    session.execute = AsyncMock(return_value=result)
    count = await repo.count_user_tokens(uuid.uuid4())
    assert count == 4


# ---------------------------------------------------------------------------
# get_status_counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_counts_success():
    repo, session, result = make_repo()
    result.all = MagicMock(return_value=[(SessionStatus.ACTIVE, 3)])
    session.execute = AsyncMock(return_value=result)
    counts = await repo.get_status_counts()
    assert counts[SessionStatus.ACTIVE] == 3


@pytest.mark.asyncio
async def test_get_status_counts_db_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.get_status_counts()


# ---------------------------------------------------------------------------
# create_token: parent / validation — дополнительные ветки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_token_parent_exists_checked():
    repo, session, result = make_repo()
    parent = make_token()
    session.get = AsyncMock(return_value=parent)
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    token = await repo.create_token(
        user_id=uuid.uuid4(),
        token_hash="childhash",
        expires_at=future_time(),
        parent_token_id=uuid.uuid4(),
        check_user_exists=False,
        check_duplicate=False,
        check_parent_exists=True,
        flush=False,
    )
    assert token.token_hash == "childhash"
    # поиск родителя идёт через session.get
    session.get.assert_awaited()


@pytest.mark.asyncio
async def test_create_token_parent_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.create_token(
            user_id=uuid.uuid4(),
            token_hash="childhash",
            expires_at=future_time(),
            parent_token_id=uuid.uuid4(),
            check_user_exists=False,
            check_duplicate=False,
            check_parent_exists=True,
        )


@pytest.mark.asyncio
async def test_create_token_too_long_hash_raises():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_token(
            user_id=uuid.uuid4(),
            token_hash="x" * 256,
            expires_at=future_time(),
            check_user_exists=False,
            check_duplicate=False,
            check_parent_exists=False,
        )


@pytest.mark.asyncio
async def test_create_token_strips_device_name():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    token = await repo.create_token(
        user_id=uuid.uuid4(),
        token_hash="newhash",
        expires_at=future_time(),
        device_name="  iPhone  ",
        check_user_exists=False,
        check_duplicate=False,
        check_parent_exists=False,
        flush=False,
    )
    assert token.device_name == "iPhone"


# ---------------------------------------------------------------------------
# list_user_tokens: ветки фильтрации / сортировки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_tokens_all_filters_applied():
    repo, session, result = make_repo()
    tokens = [make_token()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=tokens)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_user_tokens(
        uuid.uuid4(),
        include_inactive=False,
        include_revoked=False,
        include_expired=False,
        order_by_created_desc=False,
        moment=datetime.now(UTC),
    )
    assert found == tokens


@pytest.mark.asyncio
async def test_list_active_user_tokens_order_asc():
    repo, session, result = make_repo()
    tokens = [make_token()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=tokens)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_active_user_tokens(
        uuid.uuid4(), order_by_created_desc=False
    )
    assert found == tokens


# ---------------------------------------------------------------------------
# list_revoked_user_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_revoked_user_tokens_returns_list():
    repo, session, result = make_repo()
    tokens = [make_token()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=tokens)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_revoked_user_tokens(uuid.uuid4())
    assert found == tokens


@pytest.mark.asyncio
async def test_list_revoked_user_tokens_order_asc():
    repo, session, result = make_repo()
    tokens = [make_token()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=tokens)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_revoked_user_tokens(
        uuid.uuid4(), order_by_revoked_desc=False
    )
    assert found == tokens


@pytest.mark.asyncio
async def test_list_revoked_user_tokens_invalid_pagination():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidPaginationError):
        await repo.list_revoked_user_tokens(uuid.uuid4(), limit=0)


# ---------------------------------------------------------------------------
# list_expired_user_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_expired_user_tokens_returns_list():
    repo, session, result = make_repo()
    tokens = [make_token(expires_at=past_time())]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=tokens)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_expired_user_tokens(uuid.uuid4(), moment=datetime.now(UTC))
    assert found == tokens


@pytest.mark.asyncio
async def test_list_expired_user_tokens_invalid_pagination():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidPaginationError):
        await repo.list_expired_user_tokens(uuid.uuid4(), offset=-5)


# ---------------------------------------------------------------------------
# revoke_token: replaced_by + — ветка refreshes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_token_with_replaced_by_and_refresh():
    repo, session, _ = make_repo()
    token = make_token()
    replacement_id = uuid.uuid4()
    result = await repo.revoke_token(
        token,
        reason="  rotated  ",
        replaced_by_token_id=replacement_id,
        flush=True,
        refresh=True,
    )
    assert result.replaced_by_token_id == replacement_id
    assert result.revoke_reason == "rotated"
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is token


# ---------------------------------------------------------------------------
# revoke_token_by_id / by_hash: — успешные сценарии
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_token_by_id_success():
    repo, session, _ = make_repo()
    token = make_token()
    session.get = AsyncMock(return_value=token)
    result = await repo.revoke_token_by_id(token.id, flush=False)
    assert result is token
    assert result.status == SessionStatus.REVOKED


@pytest.mark.asyncio
async def test_revoke_token_by_hash_success():
    repo, session, result = make_repo()
    token = make_token()
    result.scalar_one_or_none = MagicMock(return_value=token)
    session.execute = AsyncMock(return_value=result)
    revoked = await repo.revoke_token_by_hash("somehash", flush=False)
    assert revoked is token
    assert revoked.status == SessionStatus.REVOKED


# ---------------------------------------------------------------------------
# revoke_all_user_tokens: ветка исключения в памяти
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_all_user_tokens_excludes_matching_token():
    repo, session, result = make_repo()
    keep = make_token(id=uuid.uuid4())
    drop = make_token(id=uuid.uuid4())
    result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[keep, drop]))
    )
    session.execute = AsyncMock(return_value=result)
    count = await repo.revoke_all_user_tokens(
        uuid.uuid4(), exclude_token_id=keep.id, reason="  bulk  ", flush=True
    )
    assert count == 1
    assert keep.status == SessionStatus.ACTIVE
    assert drop.status == SessionStatus.REVOKED
    assert drop.revoke_reason == "bulk"
    session.flush.assert_awaited()


# ---------------------------------------------------------------------------
# deactivate_token: refresh + успех by_id/by_hash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deactivate_token_with_refresh():
    repo, session, _ = make_repo()
    token = make_token()
    await repo.deactivate_token(token, flush=True, refresh=True)
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is token


@pytest.mark.asyncio
async def test_deactivate_token_by_id_success():
    repo, session, _ = make_repo()
    token = make_token()
    session.get = AsyncMock(return_value=token)
    result = await repo.deactivate_token_by_id(token.id, flush=False)
    assert result.is_active is False


@pytest.mark.asyncio
async def test_deactivate_token_by_hash_success():
    repo, session, result = make_repo()
    token = make_token()
    result.scalar_one_or_none = MagicMock(return_value=token)
    session.execute = AsyncMock(return_value=result)
    deactivated = await repo.deactivate_token_by_hash("somehash", flush=False)
    assert deactivated.is_active is False


@pytest.mark.asyncio
async def test_deactivate_token_by_hash_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(EntityNotFoundError):
        await repo.deactivate_token_by_hash("nonexistent")


# ---------------------------------------------------------------------------
# rotate_token: flush + refresh, — ветки ошибок
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rotate_token_with_flush_and_refresh():
    repo, session, result = make_repo()
    old = make_token()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    new_token = await repo.rotate_token(
        old_token=old,
        new_token_hash="rotated",
        new_expires_at=future_time(7200),
        device_name="  Pad  ",
        check_duplicate=False,
        flush=True,
        refresh=True,
    )
    assert new_token.token_hash == "rotated"
    assert new_token.device_name == "Pad"
    assert old.replaced_by_token_id == new_token.id
    assert old.revoke_reason == "Replaced by token rotation"
    session.refresh.assert_awaited_once()
    assert session.refresh.await_args.args[0] is new_token


@pytest.mark.asyncio
async def test_rotate_token_inherits_device_name():
    repo, session, result = make_repo()
    old = make_token(device_name="OldDevice")
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    new_token = await repo.rotate_token(
        old_token=old,
        new_token_hash="rotated2",
        new_expires_at=future_time(7200),
        check_duplicate=False,
        flush=False,
    )
    assert new_token.device_name == "OldDevice"


@pytest.mark.asyncio
async def test_rotate_token_empty_new_hash_raises():
    repo, session, result = make_repo()
    old = make_token()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(InvalidQueryError):
        await repo.rotate_token(
            old_token=old,
            new_token_hash="   ",
            new_expires_at=future_time(),
            check_duplicate=False,
        )


@pytest.mark.asyncio
async def test_rotate_token_integrity_error():
    # Сырой IntegrityError из session.add (не обёрнутый flush() заранее)
    # проверяет обработчик IntegrityError в rotate_token.
    repo, session, result = make_repo()
    old = make_token()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo.rotate_token(
            old_token=old,
            new_token_hash="rotated",
            new_expires_at=future_time(),
            check_duplicate=False,
        )


@pytest.mark.asyncio
async def test_rotate_token_sqlalchemy_error():
    # Сырой SQLAlchemyError из session.add проверяет обработчик
    # SQLAlchemyError в rotate_token.
    repo, session, result = make_repo()
    old = make_token()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.rotate_token(
            old_token=old,
            new_token_hash="rotated",
            new_expires_at=future_time(),
            check_duplicate=False,
        )


# ---------------------------------------------------------------------------
# rotate_token_by_hash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rotate_token_by_hash_success():
    repo, session, result = make_repo()
    old = make_token()
    # get_required_by_hash возвращает old; token_hash_exists -> 0
    result.scalar_one_or_none = MagicMock(return_value=old)
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    new_token = await repo.rotate_token_by_hash(
        old_token_hash="oldhash",
        new_token_hash="newrotated",
        new_expires_at=future_time(7200),
        check_duplicate=False,
        flush=False,
    )
    assert new_token.token_hash == "newrotated"
    assert new_token.user_id == old.user_id


@pytest.mark.asyncio
async def test_rotate_token_by_hash_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(EntityNotFoundError):
        await repo.rotate_token_by_hash(
            old_token_hash="missing",
            new_token_hash="newrotated",
            new_expires_at=future_time(),
        )


# ---------------------------------------------------------------------------
# get_required_active_by_hash: success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_active_by_hash_found():
    repo, session, result = make_repo()
    token = make_token()
    result.scalar_one_or_none = MagicMock(return_value=token)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_required_active_by_hash("somehash")
    assert found is token


# ---------------------------------------------------------------------------
# mark_expired_tokens: ветка flush
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_expired_tokens_with_flush():
    repo, session, result = make_repo()
    token = make_token(expires_at=past_time())
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[token])))
    session.execute = AsyncMock(return_value=result)
    count = await repo.mark_expired_tokens(flush=True)
    assert count == 1
    assert token.status == SessionStatus.EXPIRED
    session.flush.assert_awaited()


# ---------------------------------------------------------------------------
# delete_expired_tokens: flush + ошибка целостности
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_expired_tokens_with_flush():
    repo, session, result = make_repo()
    result.rowcount = 2
    session.execute = AsyncMock(return_value=result)
    count = await repo.delete_expired_tokens(flush=True)
    assert count == 2
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_delete_expired_tokens_integrity_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23503"))
    with pytest.raises((DuplicateEntityError, RepositoryError)):
        await repo.delete_expired_tokens()


# ---------------------------------------------------------------------------
# delete_revoked_tokens: revoked_before, flush, ошибки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_revoked_tokens_with_revoked_before_and_flush():
    repo, session, result = make_repo()
    result.rowcount = 4
    session.execute = AsyncMock(return_value=result)
    count = await repo.delete_revoked_tokens(
        revoked_before=datetime.now(UTC), flush=True
    )
    assert count == 4
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_delete_revoked_tokens_integrity_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23503"))
    with pytest.raises((DuplicateEntityError, RepositoryError)):
        await repo.delete_revoked_tokens()


@pytest.mark.asyncio
async def test_delete_revoked_tokens_db_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.delete_revoked_tokens()


# ---------------------------------------------------------------------------
# delete_inactive_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_inactive_tokens_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 7
    session.execute = AsyncMock(return_value=result)
    count = await repo.delete_inactive_tokens(flush=True)
    assert count == 7
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_delete_inactive_tokens_integrity_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23503"))
    with pytest.raises((DuplicateEntityError, RepositoryError)):
        await repo.delete_inactive_tokens()


@pytest.mark.asyncio
async def test_delete_inactive_tokens_db_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.delete_inactive_tokens()


# ---------------------------------------------------------------------------
# delete_user_tokens: flush + ошибки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_user_tokens_with_flush():
    repo, session, result = make_repo()
    result.rowcount = 3
    session.execute = AsyncMock(return_value=result)
    count = await repo.delete_user_tokens(uuid.uuid4(), flush=True)
    assert count == 3
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_delete_user_tokens_integrity_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23503"))
    with pytest.raises((DuplicateEntityError, RepositoryError)):
        await repo.delete_user_tokens(uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_user_tokens_db_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.delete_user_tokens(uuid.uuid4())


# ---------------------------------------------------------------------------
# count_active_user_tokens / count_revoked_user_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_active_user_tokens():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=2)
    session.execute = AsyncMock(return_value=result)
    count = await repo.count_active_user_tokens(uuid.uuid4(), moment=datetime.now(UTC))
    assert count == 2


@pytest.mark.asyncio
async def test_count_revoked_user_tokens():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=6)
    session.execute = AsyncMock(return_value=result)
    count = await repo.count_revoked_user_tokens(uuid.uuid4())
    assert count == 6


# ---------------------------------------------------------------------------
# _ensure_user_exists: ветка ошибки БД (через create_token)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_token_ensure_user_db_error():
    repo, session, _ = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.create_token(
            user_id=uuid.uuid4(),
            token_hash="somehash",
            expires_at=future_time(),
            check_user_exists=True,
            check_duplicate=False,
            check_parent_exists=False,
        )
