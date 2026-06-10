"""Юнит-тесты репозитория пользователей (UsersRepository)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
from database.models.enums import UserStatus
from database.models.users import User
from database.repositories.users import UsersRepository


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


def make_user(**kwargs) -> User:
    defaults = dict(
        email="test@example.com",
        username="testuser",
        password_hash="hashedpassword",
        status=UserStatus.ACTIVE,
    )
    defaults.update(kwargs)
    return User(**defaults)


def make_integrity_error(sqlstate="23505"):
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = "uq_test"
    orig.table_name = "users"
    orig.column_name = "email"
    exc = IntegrityError("msg", {}, orig)
    exc.orig = orig
    return exc


def make_repo():
    session, result = make_session()
    repo = UsersRepository(session=session)
    return repo, session, result


# ---------------------------------------------------------------------------
# get_user_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_by_id_found():
    repo, session, _ = make_repo()
    user = make_user()
    session.get = AsyncMock(return_value=user)
    result = await repo.get_user_by_id(user.id)
    assert result is user


@pytest.mark.asyncio
async def test_get_user_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    result = await repo.get_user_by_id(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_user_by_id_db_error():
    repo, session, _ = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.get_user_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# get_required_user_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_user_by_id_found():
    repo, session, _ = make_repo()
    user = make_user()
    session.get = AsyncMock(return_value=user)
    result = await repo.get_required_user_by_id(user.id)
    assert result is user


@pytest.mark.asyncio
async def test_get_required_user_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_user_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# get_active_user_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_user_by_id_found():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_active_user_by_id(uuid.uuid4())
    assert found is user


@pytest.mark.asyncio
async def test_get_active_user_by_id_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_active_user_by_id(uuid.uuid4())
    assert found is None


# ---------------------------------------------------------------------------
# get_required_active_user_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_active_user_by_id_found():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_required_active_user_by_id(uuid.uuid4())
    assert found is user


@pytest.mark.asyncio
async def test_get_required_active_user_by_id_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_active_user_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# get_by_email
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_email_found():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_email("TEST@EXAMPLE.COM")
    assert found is user


@pytest.mark.asyncio
async def test_get_by_email_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_email("nobody@example.com")
    assert found is None


@pytest.mark.asyncio
async def test_get_by_email_empty_returns_none():
    repo, session, result = make_repo()
    found = await repo.get_by_email("   ")
    assert found is None


@pytest.mark.asyncio
async def test_get_by_email_include_deleted_false():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_email("test@example.com", include_deleted=False)
    assert found is user
    # Проверяем, что execute был вызван (с дополнительным фильтром)
    session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_required_by_email
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_by_email_found():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_required_by_email("test@example.com")
    assert found is user


@pytest.mark.asyncio
async def test_get_required_by_email_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_email("nobody@example.com")


# ---------------------------------------------------------------------------
# get_active_by_email
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_by_email_empty_returns_none():
    repo, _, _ = make_repo()
    result = await repo.get_active_by_email("")
    assert result is None


@pytest.mark.asyncio
async def test_get_active_by_email_found():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_active_by_email("test@example.com")
    assert found is user


# ---------------------------------------------------------------------------
# email_exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_email_exists_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    assert await repo.email_exists("test@example.com") is True


@pytest.mark.asyncio
async def test_email_exists_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    assert await repo.email_exists("nobody@example.com") is False


@pytest.mark.asyncio
async def test_email_exists_empty_returns_false():
    repo, _, _ = make_repo()
    assert await repo.email_exists("") is False


# ---------------------------------------------------------------------------
# get_by_username
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_username_found():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_username("testuser")
    assert found is user


@pytest.mark.asyncio
async def test_get_by_username_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_username("nobody")
    assert found is None


@pytest.mark.asyncio
async def test_get_by_username_empty_returns_none():
    repo, _, _ = make_repo()
    found = await repo.get_by_username("   ")
    assert found is None


@pytest.mark.asyncio
async def test_get_by_username_include_deleted_false():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_username("testuser", include_deleted=False)
    assert found is None
    session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# username_exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_username_exists_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    assert await repo.username_exists("testuser") is True


@pytest.mark.asyncio
async def test_username_exists_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    assert await repo.username_exists("nobody") is False


@pytest.mark.asyncio
async def test_username_exists_empty_returns_false():
    repo, _, _ = make_repo()
    assert await repo.username_exists("") is False


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_user_success():
    repo, session, result = make_repo()
    # Нет дубликатов
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    user = await repo.create_user(
        email="new@example.com",
        username="newuser",
        password_hash="hashedpassword",
        flush=False,
        check_duplicates=False,
    )
    assert user.email == "new@example.com"
    assert user.username == "newuser"
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_user_invalid_email():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_user(email="", username="user", password_hash="hash")


@pytest.mark.asyncio
async def test_create_user_invalid_email_format():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_user(email="notanemail", username="user", password_hash="hash")


@pytest.mark.asyncio
async def test_create_user_invalid_username():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_user(email="a@b.com", username="", password_hash="hash")


@pytest.mark.asyncio
async def test_create_user_invalid_password_hash():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_user(email="a@b.com", username="user", password_hash="")


@pytest.mark.asyncio
async def test_create_user_duplicate_email():
    repo, session, result = make_repo()
    # email_exists возвращает True
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(DuplicateEntityError):
        await repo.create_user(
            email="existing@example.com",
            username="newuser",
            password_hash="hash",
            check_duplicates=True,
        )


@pytest.mark.asyncio
async def test_create_user_integrity_error():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo.create_user(
            email="new@example.com",
            username="newuser",
            password_hash="hash",
            check_duplicates=False,
        )


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_users_returns_list():
    repo, session, result = make_repo()
    users = [make_user()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=users)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_users()
    assert found == users


@pytest.mark.asyncio
async def test_list_users_invalid_pagination():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidPaginationError):
        await repo.list_users(offset=-1)


@pytest.mark.asyncio
async def test_list_users_invalid_limit():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidPaginationError):
        await repo.list_users(limit=0)


@pytest.mark.asyncio
async def test_list_users_with_statuses():
    repo, session, result = make_repo()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_users(statuses=[UserStatus.ACTIVE])
    assert found == []


# ---------------------------------------------------------------------------
# search_users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_users_returns_list():
    repo, session, result = make_repo()
    users = [make_user()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=users)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.search_users("test")
    assert found == users


@pytest.mark.asyncio
async def test_search_users_empty_query():
    repo, session, result = make_repo()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    session.execute = AsyncMock(return_value=result)
    found = await repo.search_users("")
    assert found == []


@pytest.mark.asyncio
async def test_search_users_invalid_pagination():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidPaginationError):
        await repo.search_users("q", limit=0)


# ---------------------------------------------------------------------------
# find_by_email_or_username
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_by_email_or_username_empty_returns_none():
    repo, _, _ = make_repo()
    result = await repo.find_by_email_or_username("   ")
    assert result is None


@pytest.mark.asyncio
async def test_find_by_email_or_username_found():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.find_by_email_or_username("test@example.com")
    assert found is user


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_sets_status():
    repo, session, _ = make_repo()
    user = make_user()
    result = await repo.update_status(user, UserStatus.BLOCKED, flush=False)
    assert result.status == UserStatus.BLOCKED


@pytest.mark.asyncio
async def test_update_status_calls_flush():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.update_status(user, UserStatus.DELETED, flush=True)
    session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# mark_active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_active_sets_status():
    repo, session, _ = make_repo()
    user = make_user(status=UserStatus.PENDING)
    result = await repo.mark_active(user, flush=False)
    assert result.status == UserStatus.ACTIVE


@pytest.mark.asyncio
async def test_mark_active_calls_flush():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.mark_active(user, flush=True)
    session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# mark_blocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_blocked_sets_status():
    repo, session, _ = make_repo()
    user = make_user()
    result = await repo.mark_blocked(user, reason="spam", flush=False)
    assert result.status == UserStatus.BLOCKED


@pytest.mark.asyncio
async def test_mark_blocked_calls_flush():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.mark_blocked(user, flush=True)
    session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# mark_deleted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_deleted_sets_status():
    repo, session, _ = make_repo()
    user = make_user()
    result = await repo.mark_deleted(user, flush=False)
    assert result.status == UserStatus.DELETED


@pytest.mark.asyncio
async def test_mark_deleted_calls_flush():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.mark_deleted(user, flush=True)
    session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# mark_rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_rejected_sets_status():
    repo, session, _ = make_repo()
    user = make_user()
    result = await repo.mark_rejected(user, reason="bad actor", flush=False)
    assert result.status == UserStatus.REJECTED


# ---------------------------------------------------------------------------
# unblock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unblock_sets_status():
    repo, session, _ = make_repo()
    user = make_user(status=UserStatus.BLOCKED)
    result = await repo.unblock(user, flush=False)
    assert result.status == UserStatus.ACTIVE


# ---------------------------------------------------------------------------
# update_last_login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_last_login_sets_field():
    repo, session, _ = make_repo()
    user = make_user()
    now = datetime.now(UTC)
    result = await repo.update_last_login(user, last_login_at=now, flush=False)
    assert result.last_login_at == now


@pytest.mark.asyncio
async def test_update_last_login_calls_flush():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.update_last_login(user, flush=True)
    session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# update_password_hash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_password_hash_success():
    repo, session, _ = make_repo()
    user = make_user()
    result = await repo.update_password_hash(user, password_hash="newhash", flush=False)
    assert result.password_hash == "newhash"


@pytest.mark.asyncio
async def test_update_password_hash_invalid():
    repo, _, _ = make_repo()
    user = make_user()
    with pytest.raises(InvalidQueryError):
        await repo.update_password_hash(user, password_hash="", flush=False)


@pytest.mark.asyncio
async def test_update_password_hash_calls_flush():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.update_password_hash(user, password_hash="newhash", flush=True)
    session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# update_identity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_identity_no_changes():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    r = await repo.update_identity(user, flush=False)
    assert r is user  # возвращено без изменений


@pytest.mark.asyncio
async def test_update_identity_duplicate_email():
    repo, session, result = make_repo()
    user = make_user()
    # email_exists возвращает True
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(DuplicateEntityError):
        await repo.update_identity(user, email="other@example.com", check_duplicates=True)


# ---------------------------------------------------------------------------
# count_by_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_by_status():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=5)
    session.execute = AsyncMock(return_value=result)
    count = await repo.count_by_status(UserStatus.ACTIVE)
    assert count == 5


@pytest.mark.asyncio
async def test_count_active_users():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    session.execute = AsyncMock(return_value=result)
    count = await repo.count_active_users()
    assert count == 3


@pytest.mark.asyncio
async def test_count_pending_users():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=2)
    session.execute = AsyncMock(return_value=result)
    count = await repo.count_pending_users()
    assert count == 2


@pytest.mark.asyncio
async def test_count_non_deleted_users():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=10)
    session.execute = AsyncMock(return_value=result)
    count = await repo.count_non_deleted_users()
    assert count == 10


# ---------------------------------------------------------------------------
# get_status_counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_counts_success():
    repo, session, result = make_repo()
    result.all = MagicMock(return_value=[(UserStatus.ACTIVE, 5), (UserStatus.PENDING, 2)])
    session.execute = AsyncMock(return_value=result)
    counts = await repo.get_status_counts()
    assert counts[UserStatus.ACTIVE] == 5
    assert counts[UserStatus.PENDING] == 2


@pytest.mark.asyncio
async def test_get_status_counts_db_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.get_status_counts()


# ---------------------------------------------------------------------------
# list_active_users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_active_users():
    repo, session, result = make_repo()
    users = [make_user()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=users)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_active_users()
    assert found == users


# ---------------------------------------------------------------------------
# list_pending_users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pending_users():
    repo, session, result = make_repo()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_pending_users()
    assert found == []


# ---------------------------------------------------------------------------
# путь с ошибкой scalars_all
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_users_db_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.list_users()


# ---------------------------------------------------------------------------
# варианты mark_*_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_active_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.mark_active_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_mark_blocked_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.mark_blocked_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_mark_deleted_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.mark_deleted_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_unblock_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.unblock_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_last_login_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_last_login_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_password_hash_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_password_hash_by_id(uuid.uuid4(), password_hash="hash")


# ---------------------------------------------------------------------------
# update_status_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_by_id_found():
    repo, session, _ = make_repo()
    user = make_user()
    session.get = AsyncMock(return_value=user)
    result = await repo.update_status_by_id(uuid.uuid4(), UserStatus.BLOCKED, flush=False)
    assert result.status == UserStatus.BLOCKED


@pytest.mark.asyncio
async def test_update_status_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_status_by_id(uuid.uuid4(), UserStatus.ACTIVE)


# ---------------------------------------------------------------------------
# ветки case_sensitive для поиска по email
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_email_case_sensitive():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_email("Test@Example.com", case_sensitive=True)
    assert found is user
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_active_by_email_case_sensitive():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_active_by_email("test@example.com", case_sensitive=True)
    assert found is user


# ---------------------------------------------------------------------------
# email_exists branches: case_sensitive / exclude / include_deleted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_email_exists_case_sensitive():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    assert await repo.email_exists("Test@Example.com", case_sensitive=True) is True


@pytest.mark.asyncio
async def test_email_exists_exclude_and_no_deleted():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    out = await repo.email_exists(
        "test@example.com",
        exclude_user_id=uuid.uuid4(),
        include_deleted=False,
    )
    assert out is False
    session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_by_username case_sensitive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_username_case_sensitive():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_by_username("TestUser", case_sensitive=True)
    assert found is user


# ---------------------------------------------------------------------------
# get_required_by_username
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_by_username_found():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_required_by_username("testuser")
    assert found is user


@pytest.mark.asyncio
async def test_get_required_by_username_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_username("nobody")


# ---------------------------------------------------------------------------
# get_active_by_username
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_by_username_empty_returns_none():
    repo, _, _ = make_repo()
    assert await repo.get_active_by_username("   ") is None


@pytest.mark.asyncio
async def test_get_active_by_username_found():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_active_by_username("testuser")
    assert found is user


@pytest.mark.asyncio
async def test_get_active_by_username_case_sensitive():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one_or_none = MagicMock(return_value=user)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_active_by_username("TestUser", case_sensitive=True)
    assert found is user


# ---------------------------------------------------------------------------
# username_exists branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_username_exists_case_sensitive():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    assert await repo.username_exists("TestUser", case_sensitive=True) is True


@pytest.mark.asyncio
async def test_username_exists_exclude_and_no_deleted():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    out = await repo.username_exists(
        "testuser",
        exclude_user_id=uuid.uuid4(),
        include_deleted=False,
    )
    assert out is False


# ---------------------------------------------------------------------------
# create_user: duplicate username + non-unique integrity error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_user_duplicate_username():
    repo, session, result = make_repo()
    # email_exists -> 0 (нет дубля), username_exists -> 1 (дубль)
    result.scalar_one = MagicMock(side_effect=[0, 1])
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(DuplicateEntityError):
        await repo.create_user(
            email="new@example.com",
            username="takenuser",
            password_hash="hash",
            check_duplicates=True,
        )


@pytest.mark.asyncio
async def test_create_user_integrity_error_from_create_call():
    # Защитный обработчик в create_user: если self.create выдаёт сырой
    # IntegrityError, он маппится через _handle_integrity_error.
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    repo.create = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo.create_user(
            email="new@example.com",
            username="newuser",
            password_hash="hash",
            check_duplicates=False,
        )


@pytest.mark.asyncio
async def test_create_user_integrity_error_non_unique():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    # sqlstate не про нарушение уникальности всё равно проходит через _handle_integrity_error
    session.flush = AsyncMock(side_effect=make_integrity_error("23503"))
    with pytest.raises(RepositoryError):
        await repo.create_user(
            email="new@example.com",
            username="newuser",
            password_hash="hash",
            check_duplicates=False,
        )


# ---------------------------------------------------------------------------
# list_users / search_users дополнительные фильтры
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_users_order_asc():
    repo, session, result = make_repo()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    session.execute = AsyncMock(return_value=result)
    found = await repo.list_users(order_by_created_desc=False)
    assert found == []


@pytest.mark.asyncio
async def test_search_users_with_filters():
    repo, session, result = make_repo()
    users = [make_user()]
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=users)))
    session.execute = AsyncMock(return_value=result)
    found = await repo.search_users(
        "test",
        statuses=[UserStatus.ACTIVE],
    )
    assert found == users


# ---------------------------------------------------------------------------
# update_status: все необязательные поля
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_all_optional_fields():
    repo, session, _ = make_repo()
    user = make_user()
    now = datetime.now(UTC)
    result = await repo.update_status(
        user,
        UserStatus.BLOCKED,
        approved_at=now,
        blocked_at=now,
        rejected_at=now,
        deleted_at=now,
        block_reason="  spam  ",
        rejection_reason="  bad  ",
        flush=False,
    )
    assert result.status == UserStatus.BLOCKED
    assert result.approved_at == now
    assert result.blocked_at == now
    assert result.rejected_at == now
    assert result.deleted_at == now
    assert result.block_reason == "spam"
    assert result.rejection_reason == "bad"


@pytest.mark.asyncio
async def test_update_status_blank_reasons_become_none():
    repo, session, _ = make_repo()
    user = make_user(block_reason="x", rejection_reason="y")
    result = await repo.update_status(
        user,
        UserStatus.ACTIVE,
        block_reason="   ",
        rejection_reason="   ",
        flush=False,
    )
    assert result.block_reason is None
    assert result.rejection_reason is None


# ---------------------------------------------------------------------------
# ветки refresh=True для мутаторов на месте
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_active_refresh():
    repo, session, _ = make_repo()
    user = make_user(status=UserStatus.PENDING)
    await repo.mark_active(user, flush=False, refresh=True)
    session.refresh.assert_called_once()
    assert session.refresh.call_args.args[0] is user


@pytest.mark.asyncio
async def test_mark_blocked_refresh():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.mark_blocked(user, flush=False, refresh=True)
    session.refresh.assert_called_once()
    assert session.refresh.call_args.args[0] is user


@pytest.mark.asyncio
async def test_unblock_refresh():
    repo, session, _ = make_repo()
    user = make_user(status=UserStatus.BLOCKED)
    await repo.unblock(user, flush=False, refresh=True)
    session.refresh.assert_called_once()
    assert session.refresh.call_args.args[0] is user


@pytest.mark.asyncio
async def test_unblock_calls_flush():
    repo, session, _ = make_repo()
    user = make_user(status=UserStatus.BLOCKED)
    await repo.unblock(user, flush=True)
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_mark_rejected_refresh_and_flush():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.mark_rejected(user, flush=True, refresh=True)
    session.flush.assert_called_once()
    session.refresh.assert_called_once()
    assert session.refresh.call_args.args[0] is user


@pytest.mark.asyncio
async def test_mark_deleted_refresh():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.mark_deleted(user, flush=False, refresh=True)
    session.refresh.assert_called_once()
    assert session.refresh.call_args.args[0] is user


@pytest.mark.asyncio
async def test_update_last_login_refresh():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.update_last_login(user, flush=False, refresh=True)
    session.refresh.assert_called_once()
    assert session.refresh.call_args.args[0] is user


@pytest.mark.asyncio
async def test_update_password_hash_refresh():
    repo, session, _ = make_repo()
    user = make_user()
    await repo.update_password_hash(user, password_hash="newhash", flush=False, refresh=True)
    session.refresh.assert_called_once()
    assert session.refresh.call_args.args[0] is user


# ---------------------------------------------------------------------------
# варианты *_by_id с найденной сущностью (путь делегирования)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_active_by_id_found():
    repo, session, _ = make_repo()
    user = make_user(status=UserStatus.PENDING)
    session.get = AsyncMock(return_value=user)
    result = await repo.mark_active_by_id(uuid.uuid4(), flush=False)
    assert result.status == UserStatus.ACTIVE


@pytest.mark.asyncio
async def test_mark_blocked_by_id_found():
    repo, session, _ = make_repo()
    user = make_user()
    session.get = AsyncMock(return_value=user)
    result = await repo.mark_blocked_by_id(uuid.uuid4(), reason="spam", flush=False)
    assert result.status == UserStatus.BLOCKED


@pytest.mark.asyncio
async def test_unblock_by_id_found():
    repo, session, _ = make_repo()
    user = make_user(status=UserStatus.BLOCKED)
    session.get = AsyncMock(return_value=user)
    result = await repo.unblock_by_id(uuid.uuid4(), flush=False)
    assert result.status == UserStatus.ACTIVE


@pytest.mark.asyncio
async def test_mark_rejected_by_id_found():
    repo, session, _ = make_repo()
    user = make_user()
    session.get = AsyncMock(return_value=user)
    result = await repo.mark_rejected_by_id(uuid.uuid4(), reason="bad", flush=False)
    assert result.status == UserStatus.REJECTED


@pytest.mark.asyncio
async def test_mark_rejected_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.mark_rejected_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_mark_deleted_by_id_found():
    repo, session, _ = make_repo()
    user = make_user()
    session.get = AsyncMock(return_value=user)
    result = await repo.mark_deleted_by_id(uuid.uuid4(), flush=False)
    assert result.status == UserStatus.DELETED


@pytest.mark.asyncio
async def test_update_last_login_by_id_found():
    repo, session, _ = make_repo()
    user = make_user()
    session.get = AsyncMock(return_value=user)
    now = datetime.now(UTC)
    result = await repo.update_last_login_by_id(uuid.uuid4(), last_login_at=now, flush=False)
    assert result.last_login_at == now


@pytest.mark.asyncio
async def test_update_password_hash_by_id_found():
    repo, session, _ = make_repo()
    user = make_user()
    session.get = AsyncMock(return_value=user)
    result = await repo.update_password_hash_by_id(
        uuid.uuid4(), password_hash="newhash", flush=False,
    )
    assert result.password_hash == "newhash"


# ---------------------------------------------------------------------------
# update_identity: email/username — сценарии установки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_identity_email_and_username_success():
    repo, session, result = make_repo()
    user = make_user()
    # и email_exists, и username_exists возвращают 0 (дубликатов нет)
    result.scalar_one = MagicMock(return_value=0)
    session.execute = AsyncMock(return_value=result)
    out = await repo.update_identity(
        user,
        email="fresh@example.com",
        username="freshuser",
        flush=False,
    )
    assert out.email == "fresh@example.com"
    assert out.username == "freshuser"


@pytest.mark.asyncio
async def test_update_identity_duplicate_username():
    repo, session, result = make_repo()
    user = make_user()
    result.scalar_one = MagicMock(return_value=1)
    session.execute = AsyncMock(return_value=result)
    with pytest.raises(DuplicateEntityError):
        await repo.update_identity(user, username="takenuser", check_duplicates=True)


@pytest.mark.asyncio
async def test_update_identity_skip_duplicate_check():
    repo, session, result = make_repo()
    user = make_user()
    out = await repo.update_identity(
        user,
        email="fresh@example.com",
        username="freshuser",
        flush=False,
        check_duplicates=False,
    )
    assert out.email == "fresh@example.com"
    assert out.username == "freshuser"


@pytest.mark.asyncio
async def test_update_identity_invalid_email():
    repo, _, _ = make_repo()
    user = make_user()
    with pytest.raises(InvalidQueryError):
        await repo.update_identity(user, email="notanemail", check_duplicates=False)


# ---------------------------------------------------------------------------
# update_identity_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_identity_by_id_found():
    repo, session, result = make_repo()
    user = make_user()
    session.get = AsyncMock(return_value=user)
    out = await repo.update_identity_by_id(uuid.uuid4(), flush=False)
    assert out is user


@pytest.mark.asyncio
async def test_update_identity_by_id_not_found():
    repo, session, _ = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_identity_by_id(uuid.uuid4(), email="x@y.com")


# ---------------------------------------------------------------------------
# _base_select helper
# ---------------------------------------------------------------------------

def test_base_select_returns_select():
    repo, _, _ = make_repo()
    statement = repo._base_select()
    assert statement is not None
    # Компилируется в SELECT по таблице users.
    assert "users" in str(statement).lower()


# ---------------------------------------------------------------------------
# ограничения длины при валидации
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_user_email_too_long():
    repo, _, _ = make_repo()
    long_email = "a" * 320 + "@example.com"
    with pytest.raises(InvalidQueryError):
        await repo.create_user(
            email=long_email,
            username="user",
            password_hash="hash",
            check_duplicates=False,
        )


@pytest.mark.asyncio
async def test_create_user_username_too_long():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_user(
            email="a@b.com",
            username="u" * 65,
            password_hash="hash",
            check_duplicates=False,
        )


@pytest.mark.asyncio
async def test_create_user_password_hash_too_long():
    repo, _, _ = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_user(
            email="a@b.com",
            username="user",
            password_hash="h" * 256,
            check_duplicates=False,
        )


# ---------------------------------------------------------------------------
# get_first_admin_user_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_first_admin_user_id_returns_id():
    repo, session, result = make_repo()
    admin_id = uuid.uuid4()
    result.scalar_one_or_none = MagicMock(return_value=admin_id)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_first_admin_user_id()
    assert found == admin_id


@pytest.mark.asyncio
async def test_get_first_admin_user_id_returns_none_when_no_admins():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)
    found = await repo.get_first_admin_user_id()
    assert found is None


@pytest.mark.asyncio
async def test_get_first_admin_user_id_wraps_db_error():
    repo, session, _ = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.get_first_admin_user_id()
