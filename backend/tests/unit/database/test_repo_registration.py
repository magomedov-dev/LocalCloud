"""Юнит-тесты репозитория заявок на регистрацию (RegistrationRequestsRepository)."""
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
from database.models.enums import RegistrationRequestStatus
from database.repositories.registration import RegistrationRequestsRepository


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
    return RegistrationRequestsRepository(session=session), session, result


def make_reg_request(**kwargs):
    req = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        email="user@example.com",
        username="testuser",
        password_hash="hashedpassword",
        status=RegistrationRequestStatus.PENDING,
        can_be_reviewed=True,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(req, k, v)
    req.approve = MagicMock()
    req.reject = MagicMock()
    req.cancel = MagicMock()
    req.reset_to_pending = MagicMock()
    return req


# ---------------------------------------------------------------------------
# Тесты: get_request_by_id / get_required_request_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_request_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    res = await repo.get_request_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_request_by_id_returns_request_when_found():
    repo, session, result = make_repo()
    req = make_reg_request()
    session.get = AsyncMock(return_value=req)
    res = await repo.get_request_by_id(req.id)
    assert res is req


@pytest.mark.asyncio
async def test_get_required_request_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_request_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_latest_by_email / get_latest_by_username
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_latest_by_email_returns_none_for_empty_email():
    repo, session, result = make_repo()
    res = await repo.get_latest_by_email("   ")
    assert res is None


@pytest.mark.asyncio
async def test_get_latest_by_email_returns_request_when_found():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalar_one_or_none = MagicMock(return_value=req)
    res = await repo.get_latest_by_email("user@example.com")
    assert res is req


@pytest.mark.asyncio
async def test_get_latest_by_username_returns_none_for_empty():
    repo, session, result = make_repo()
    res = await repo.get_latest_by_username("   ")
    assert res is None


@pytest.mark.asyncio
async def test_get_latest_by_username_returns_request_when_found():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalar_one_or_none = MagicMock(return_value=req)
    res = await repo.get_latest_by_username("testuser")
    assert res is req


# ---------------------------------------------------------------------------
# Тесты: get_pending_by_email / get_pending_by_username
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pending_by_email_returns_none_for_empty():
    repo, session, result = make_repo()
    res = await repo.get_pending_by_email("  ")
    assert res is None


@pytest.mark.asyncio
async def test_get_pending_by_email_returns_request():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalar_one_or_none = MagicMock(return_value=req)
    res = await repo.get_pending_by_email("user@example.com")
    assert res is req


@pytest.mark.asyncio
async def test_get_pending_by_username_returns_none_for_empty():
    repo, session, result = make_repo()
    res = await repo.get_pending_by_username("   ")
    assert res is None


# ---------------------------------------------------------------------------
# Тесты: email_has_pending_request / username_has_pending_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_email_has_pending_request_returns_false_for_empty():
    repo, session, result = make_repo()
    res = await repo.email_has_pending_request("  ")
    assert res is False


@pytest.mark.asyncio
async def test_email_has_pending_request_returns_true_when_exists():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.email_has_pending_request("user@example.com")
    assert res is True


@pytest.mark.asyncio
async def test_username_has_pending_request_returns_false_for_empty():
    repo, session, result = make_repo()
    res = await repo.username_has_pending_request("  ")
    assert res is False


# ---------------------------------------------------------------------------
# Тесты: create_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_request_raises_for_empty_email():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_request(
            email="",
            username="user",
            password_hash="hash",
            check_pending_duplicates=False,
            check_created_user_exists=False,
        )


@pytest.mark.asyncio
async def test_create_request_raises_for_invalid_email():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_request(
            email="notavalidemail",
            username="user",
            password_hash="hash",
            check_pending_duplicates=False,
            check_created_user_exists=False,
        )


@pytest.mark.asyncio
async def test_create_request_raises_for_empty_username():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_request(
            email="user@example.com",
            username="",
            password_hash="hash",
            check_pending_duplicates=False,
            check_created_user_exists=False,
        )


@pytest.mark.asyncio
async def test_create_request_raises_for_empty_password_hash():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_request(
            email="user@example.com",
            username="testuser",
            password_hash="",
            check_pending_duplicates=False,
            check_created_user_exists=False,
        )


@pytest.mark.asyncio
async def test_create_request_success():
    repo, session, result = make_repo()
    req = make_reg_request()

    async def fake_create(entity, flush=True, refresh=False):
        return req

    repo.create = fake_create  # type: ignore
    res = await repo.create_request(
        email="user@example.com",
        username="testuser",
        password_hash="validhash",
        check_pending_duplicates=False,
        check_created_user_exists=False,
    )
    assert res is req


# ---------------------------------------------------------------------------
# Тесты: list_requests / list_pending
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_requests_returns_empty_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_requests()
    assert res == []


@pytest.mark.asyncio
async def test_list_pending_returns_list():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalars.return_value.all.return_value = [req]
    res = await repo.list_pending()
    assert len(res) == 1


@pytest.mark.asyncio
async def test_list_approved_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_approved()
    assert res == []


@pytest.mark.asyncio
async def test_list_rejected_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_rejected()
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: approve_request / reject_request / cancel_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_request_raises_when_not_reviewable():
    repo, session, result = make_repo()
    req = make_reg_request(can_be_reviewed=False)
    with pytest.raises(InvalidQueryError):
        await repo.approve_request(
            req,
            reviewed_by=uuid.uuid4(),
            created_user_id=uuid.uuid4(),
            check_user_exists=False,
            require_pending=True,
        )


@pytest.mark.asyncio
async def test_approve_request_success():
    repo, session, result = make_repo()
    req = make_reg_request(can_be_reviewed=True)
    res = await repo.approve_request(
        req,
        reviewed_by=uuid.uuid4(),
        created_user_id=uuid.uuid4(),
        check_user_exists=False,
    )
    req.approve.assert_called_once()
    assert res is req


@pytest.mark.asyncio
async def test_reject_request_success():
    repo, session, result = make_repo()
    req = make_reg_request(can_be_reviewed=True)
    res = await repo.reject_request(
        req,
        reviewed_by=uuid.uuid4(),
        reason="Not approved",
    )
    req.reject.assert_called_once()
    assert res is req


@pytest.mark.asyncio
async def test_cancel_request_success():
    repo, session, result = make_repo()
    req = make_reg_request()
    res = await repo.cancel_request(req)
    req.cancel.assert_called_once()
    assert res is req


# ---------------------------------------------------------------------------
# Тесты: reset_to_pending
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_to_pending_success():
    repo, session, result = make_repo()
    req = make_reg_request()
    res = await repo.reset_to_pending(req)
    req.reset_to_pending.assert_called_once()
    assert res is req


@pytest.mark.asyncio
async def test_reset_to_pending_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.reset_to_pending_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: count_by_status / count_pending / count_reviewed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_by_status_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=5)
    count = await repo.count_by_status(RegistrationRequestStatus.PENDING)
    assert count == 5


@pytest.mark.asyncio
async def test_count_pending_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    count = await repo.count_pending()
    assert count == 3


@pytest.mark.asyncio
async def test_count_reviewed_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=10)
    count = await repo.count_reviewed()
    assert count == 10


# ---------------------------------------------------------------------------
# Тесты: search_requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_requests_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_requests("test")
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: get_status_counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_counts_returns_dict():
    repo, session, result = make_repo()
    result.all = MagicMock(return_value=[(RegistrationRequestStatus.PENDING, 5)])
    counts = await repo.get_status_counts()
    assert isinstance(counts, dict)


@pytest.mark.asyncio
async def test_get_status_counts_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.get_status_counts()


# ---------------------------------------------------------------------------
# Тесты: ветки поиска с учётом регистра
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_latest_by_email_case_sensitive_branch():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalar_one_or_none = MagicMock(return_value=req)
    res = await repo.get_latest_by_email("User@Example.com", case_sensitive=True)
    assert res is req


@pytest.mark.asyncio
async def test_get_latest_by_username_case_sensitive_branch():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalar_one_or_none = MagicMock(return_value=req)
    res = await repo.get_latest_by_username("TestUser", case_sensitive=True)
    assert res is req


@pytest.mark.asyncio
async def test_get_pending_by_email_case_sensitive_branch():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalar_one_or_none = MagicMock(return_value=req)
    res = await repo.get_pending_by_email("User@Example.com", case_sensitive=True)
    assert res is req


# ---------------------------------------------------------------------------
# Тесты: get_pending_by_username (без учёта регистра + с учётом регистра + пусто)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pending_by_username_returns_request():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalar_one_or_none = MagicMock(return_value=req)
    res = await repo.get_pending_by_username("testuser")
    assert res is req


@pytest.mark.asyncio
async def test_get_pending_by_username_case_sensitive_branch():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalar_one_or_none = MagicMock(return_value=req)
    res = await repo.get_pending_by_username("TestUser", case_sensitive=True)
    assert res is req


# ---------------------------------------------------------------------------
# Тесты: get_pending_by_email_or_username
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pending_by_email_or_username_returns_request():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalar_one_or_none = MagicMock(return_value=req)
    res = await repo.get_pending_by_email_or_username(
        email="user@example.com",
        username="testuser",
    )
    assert res is req


@pytest.mark.asyncio
async def test_get_pending_by_email_or_username_returns_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_pending_by_email_or_username(
        email="user@example.com",
        username="testuser",
    )
    assert res is None


# ---------------------------------------------------------------------------
# Тесты: email/username_has_pending_request (положительный + чувствительность к регистру)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_email_has_pending_request_case_sensitive_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    res = await repo.email_has_pending_request(
        "User@Example.com",
        case_sensitive=True,
    )
    assert res is False


@pytest.mark.asyncio
async def test_username_has_pending_request_returns_true_when_exists():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.username_has_pending_request("testuser")
    assert res is True


@pytest.mark.asyncio
async def test_username_has_pending_request_case_sensitive_branch():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.username_has_pending_request(
        "TestUser",
        case_sensitive=True,
    )
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: create_request — дубликат / created_user / ошибка целостности
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_request_raises_duplicate_email():
    repo, session, result = make_repo()
    repo.email_has_pending_request = AsyncMock(return_value=True)
    with pytest.raises(DuplicateEntityError):
        await repo.create_request(
            email="user@example.com",
            username="testuser",
            password_hash="validhash",
            check_pending_duplicates=True,
            check_created_user_exists=False,
        )


@pytest.mark.asyncio
async def test_create_request_raises_duplicate_username():
    repo, session, result = make_repo()
    repo.email_has_pending_request = AsyncMock(return_value=False)
    repo.username_has_pending_request = AsyncMock(return_value=True)
    with pytest.raises(DuplicateEntityError):
        await repo.create_request(
            email="user@example.com",
            username="testuser",
            password_hash="validhash",
            check_pending_duplicates=True,
            check_created_user_exists=False,
        )


@pytest.mark.asyncio
async def test_create_request_raises_when_created_user_missing():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.create_request(
            email="user@example.com",
            username="testuser",
            password_hash="validhash",
            created_user_id=uuid.uuid4(),
            check_pending_duplicates=False,
            check_created_user_exists=True,
        )


@pytest.mark.asyncio
async def test_create_request_success_with_created_user():
    repo, session, result = make_repo()
    user = MagicMock()
    session.get = AsyncMock(return_value=user)
    req = make_reg_request()

    async def fake_create(entity, flush=True, refresh=False):
        return req

    repo.create = fake_create  # type: ignore
    res = await repo.create_request(
        email="  User@Example.com  ",
        username="  testuser  ",
        password_hash="validhash",
        comment="  hello  ",
        rejection_reason="  nope  ",
        created_user_id=uuid.uuid4(),
        check_pending_duplicates=False,
        check_created_user_exists=True,
    )
    assert res is req


@pytest.mark.asyncio
async def test_create_request_maps_integrity_error():
    repo, session, result = make_repo()

    async def fake_create(entity, flush=True, refresh=False):
        raise IntegrityError("stmt", {}, Exception("orig"))

    repo.create = fake_create  # type: ignore
    with pytest.raises((DuplicateEntityError, RepositoryError)):
        await repo.create_request(
            email="user@example.com",
            username="testuser",
            password_hash="validhash",
            check_pending_duplicates=False,
            check_created_user_exists=False,
        )


# ---------------------------------------------------------------------------
# Тесты: validation length branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_request_raises_for_too_long_email():
    repo, session, result = make_repo()
    long_local = "a" * 320
    with pytest.raises(InvalidQueryError):
        await repo.create_request(
            email=f"{long_local}@example.com",
            username="testuser",
            password_hash="validhash",
            check_pending_duplicates=False,
            check_created_user_exists=False,
        )


@pytest.mark.asyncio
async def test_create_request_raises_for_too_long_username():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_request(
            email="user@example.com",
            username="u" * 65,
            password_hash="validhash",
            check_pending_duplicates=False,
            check_created_user_exists=False,
        )


@pytest.mark.asyncio
async def test_create_request_raises_for_too_long_password_hash():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_request(
            email="user@example.com",
            username="testuser",
            password_hash="h" * 256,
            check_pending_duplicates=False,
            check_created_user_exists=False,
        )


# ---------------------------------------------------------------------------
# Тесты: list_requests filters / list_cancelled / list_reviewed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_requests_with_all_filters():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalars.return_value.all.return_value = [req]
    res = await repo.list_requests(
        statuses=[RegistrationRequestStatus.PENDING],
        reviewed_by=uuid.uuid4(),
        created_user_id=uuid.uuid4(),
        order_by_created_desc=False,
    )
    assert res == [req]


@pytest.mark.asyncio
async def test_list_cancelled_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_cancelled()
    assert res == []


@pytest.mark.asyncio
async def test_list_reviewed_desc_returns_list():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalars.return_value.all.return_value = [req]
    res = await repo.list_reviewed(order_by_reviewed_desc=True)
    assert res == [req]


@pytest.mark.asyncio
async def test_list_reviewed_asc_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_reviewed(order_by_reviewed_desc=False)
    assert res == []


@pytest.mark.asyncio
async def test_list_by_status_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_by_status(RegistrationRequestStatus.APPROVED)
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: search_requests с фильтром по статусу
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_requests_with_statuses():
    repo, session, result = make_repo()
    req = make_reg_request()
    result.scalars.return_value.all.return_value = [req]
    res = await repo.search_requests(
        "user",
        statuses=[RegistrationRequestStatus.PENDING],
    )
    assert res == [req]


@pytest.mark.asyncio
async def test_search_requests_empty_query():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_requests("   ")
    assert res == []


# ---------------------------------------------------------------------------
# Тесты: approve_request — refresh / check_user_exists / by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_request_with_user_check_and_refresh():
    repo, session, result = make_repo()
    user = MagicMock()
    session.get = AsyncMock(return_value=user)
    req = make_reg_request(can_be_reviewed=True)
    res = await repo.approve_request(
        req,
        reviewed_by=uuid.uuid4(),
        created_user_id=uuid.uuid4(),
        comment="  ok  ",
        check_user_exists=True,
        refresh=True,
    )
    req.approve.assert_called_once()
    session.refresh.assert_awaited_once()
    assert res is req


@pytest.mark.asyncio
async def test_approve_request_by_id_success():
    repo, session, result = make_repo()
    user = MagicMock()
    req = make_reg_request(can_be_reviewed=True)
    session.get = AsyncMock(side_effect=[req, user])
    res = await repo.approve_request_by_id(
        req.id,
        reviewed_by=uuid.uuid4(),
        created_user_id=uuid.uuid4(),
    )
    req.approve.assert_called_once()
    assert res is req


@pytest.mark.asyncio
async def test_approve_request_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.approve_request_by_id(
            uuid.uuid4(),
            reviewed_by=uuid.uuid4(),
            created_user_id=uuid.uuid4(),
        )


# ---------------------------------------------------------------------------
# Тесты: reject_request — refresh / require_pending / by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_request_raises_when_not_reviewable():
    repo, session, result = make_repo()
    req = make_reg_request(can_be_reviewed=False)
    with pytest.raises(InvalidQueryError):
        await repo.reject_request(
            req,
            reviewed_by=uuid.uuid4(),
            require_pending=True,
        )


@pytest.mark.asyncio
async def test_reject_request_with_refresh():
    repo, session, result = make_repo()
    req = make_reg_request(can_be_reviewed=True)
    res = await repo.reject_request(
        req,
        reviewed_by=uuid.uuid4(),
        reason="  bad  ",
        comment="  note  ",
        refresh=True,
    )
    req.reject.assert_called_once()
    session.refresh.assert_awaited_once()
    assert res is req


@pytest.mark.asyncio
async def test_reject_request_by_id_success():
    repo, session, result = make_repo()
    req = make_reg_request(can_be_reviewed=True)
    session.get = AsyncMock(return_value=req)
    res = await repo.reject_request_by_id(
        req.id,
        reviewed_by=uuid.uuid4(),
    )
    req.reject.assert_called_once()
    assert res is req


# ---------------------------------------------------------------------------
# Тесты: cancel_request — require_pending / refresh / by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_request_raises_when_require_pending_and_not_reviewable():
    repo, session, result = make_repo()
    req = make_reg_request(can_be_reviewed=False)
    with pytest.raises(InvalidQueryError):
        await repo.cancel_request(req, require_pending=True)


@pytest.mark.asyncio
async def test_cancel_request_with_refresh():
    repo, session, result = make_repo()
    req = make_reg_request()
    res = await repo.cancel_request(req, comment="  bye  ", refresh=True)
    req.cancel.assert_called_once()
    session.refresh.assert_awaited_once()
    assert res is req


@pytest.mark.asyncio
async def test_cancel_request_by_id_success():
    repo, session, result = make_repo()
    req = make_reg_request()
    session.get = AsyncMock(return_value=req)
    res = await repo.cancel_request_by_id(req.id)
    req.cancel.assert_called_once()
    assert res is req


# ---------------------------------------------------------------------------
# Тесты: reset_to_pending — refresh / успех by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_to_pending_with_refresh():
    repo, session, result = make_repo()
    req = make_reg_request()
    res = await repo.reset_to_pending(req, refresh=True)
    req.reset_to_pending.assert_called_once()
    session.refresh.assert_awaited_once()
    assert res is req


@pytest.mark.asyncio
async def test_reset_to_pending_by_id_success():
    repo, session, result = make_repo()
    req = make_reg_request()
    session.get = AsyncMock(return_value=req)
    res = await repo.reset_to_pending_by_id(req.id)
    req.reset_to_pending.assert_called_once()
    assert res is req


# ---------------------------------------------------------------------------
# Тесты: set_created_user / set_created_user_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_created_user_success():
    repo, session, result = make_repo()
    user = MagicMock()
    session.get = AsyncMock(return_value=user)
    req = make_reg_request()
    created_user_id = uuid.uuid4()
    res = await repo.set_created_user(
        req,
        created_user_id=created_user_id,
        refresh=True,
    )
    assert req.created_user_id == created_user_id
    session.refresh.assert_awaited_once()
    assert res is req


@pytest.mark.asyncio
async def test_set_created_user_raises_when_user_missing():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    req = make_reg_request()
    with pytest.raises(EntityNotFoundError):
        await repo.set_created_user(
            req,
            created_user_id=uuid.uuid4(),
            check_user_exists=True,
        )


@pytest.mark.asyncio
async def test_set_created_user_skip_check():
    repo, session, result = make_repo()
    req = make_reg_request()
    created_user_id = uuid.uuid4()
    res = await repo.set_created_user(
        req,
        created_user_id=created_user_id,
        check_user_exists=False,
    )
    assert req.created_user_id == created_user_id
    assert res is req


@pytest.mark.asyncio
async def test_set_created_user_by_id_success():
    repo, session, result = make_repo()
    req = make_reg_request()
    user = MagicMock()
    session.get = AsyncMock(side_effect=[req, user])
    created_user_id = uuid.uuid4()
    res = await repo.set_created_user_by_id(
        req.id,
        created_user_id=created_user_id,
    )
    assert req.created_user_id == created_user_id
    assert res is req


# ---------------------------------------------------------------------------
# Тесты: _base_select / _ensure_user_exists — ветки ошибок
# ---------------------------------------------------------------------------

def test_base_select_returns_select():
    repo, session, result = make_repo()
    stmt = repo._base_select()
    assert stmt is not None


@pytest.mark.asyncio
async def test_ensure_user_exists_raises_repository_error_on_db_failure():
    repo, session, result = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._ensure_user_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_user_exists_raises_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo._ensure_user_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_user_exists_passes_when_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=MagicMock())
    await repo._ensure_user_exists(uuid.uuid4())
