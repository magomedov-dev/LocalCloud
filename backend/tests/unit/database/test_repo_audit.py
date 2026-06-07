"""Модульные тесты репозитория AuditLogRepository: создание событий, фильтрация,
подсчёты, агрегации и нормализация входных данных."""
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
from database.models.enums import AuditAction, AuditResourceType, AuditResult
from database.repositories.audit import AuditLogRepository


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
    return AuditLogRepository(session=session), session, result


def make_log(**kwargs):
    log = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        action=AuditAction.USER_LOGIN,
        result=AuditResult.SUCCESS,
        entity_type="user",
        entity_id=uuid.uuid4(),
        ip_address="127.0.0.1",
        user_agent="agent",
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(log, k, v)
    return log


def make_integrity_error(sqlstate="23505", constraint="uq_audit_logs"):
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = constraint
    orig.table_name = "audit_logs"
    orig.column_name = None
    err = IntegrityError("stmt", {}, orig)
    err.orig = orig
    return err


# ---------------------------------------------------------------------------
# get_log_by_id / get_required_log_by_id / get_by_id / get_required_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_log_by_id_returns_none():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    res = await repo.get_log_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_log_by_id_returns_log():
    repo, session, result = make_repo()
    log = make_log()
    session.get = AsyncMock(return_value=log)
    res = await repo.get_log_by_id(log.id)
    assert res is log


@pytest.mark.asyncio
async def test_get_required_log_by_id_returns_log():
    repo, session, result = make_repo()
    log = make_log()
    session.get = AsyncMock(return_value=log)
    res = await repo.get_required_log_by_id(log.id)
    assert res is log


@pytest.mark.asyncio
async def test_get_required_log_by_id_raises():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_log_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_by_id_returns_log():
    repo, session, result = make_repo()
    log = make_log()
    session.get = AsyncMock(return_value=log)
    res = await repo.get_by_id(log.id)
    assert res is log


@pytest.mark.asyncio
async def test_get_required_by_id_returns_log():
    repo, session, result = make_repo()
    log = make_log()
    session.get = AsyncMock(return_value=log)
    res = await repo.get_required_by_id(log.id)
    assert res is log


@pytest.mark.asyncio
async def test_get_required_by_id_raises():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# create_event: all result branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_event_user_success():
    repo, session, result = make_repo()
    user_id = uuid.uuid4()
    res = await repo.create_event(
        action=AuditAction.USER_LOGIN,
        result=AuditResult.SUCCESS,
        user_id=user_id,
        entity_type="  user  ",
        entity_id=uuid.uuid4(),
        resource_type=AuditResourceType.USER,
        request_id="req-1",
        correlation_id="corr-1",
        ip_address="  10.0.0.1  ",
        user_agent="  ua  ",
        message="ok",
        error_code="E1",
        metadata={"k": "v"},
    )
    session.add.assert_called_once()
    session.flush.assert_awaited()
    assert res.user_id == user_id
    assert res.action == AuditAction.USER_LOGIN
    assert res.entity_type == "user"
    assert res.ip_address == "10.0.0.1"
    assert res.user_agent == "ua"


@pytest.mark.asyncio
async def test_create_event_failure_branch():
    repo, session, result = make_repo()
    res = await repo.create_event(
        action=AuditAction.USER_LOGIN_FAILED,
        result=AuditResult.FAILURE,
        user_id=uuid.uuid4(),
        error_code="BAD",
        message="failed",
    )
    assert res.result == AuditResult.FAILURE


@pytest.mark.asyncio
async def test_create_event_denied_branch():
    repo, session, result = make_repo()
    res = await repo.create_event(
        action=AuditAction.USER_LOGIN,
        result=AuditResult.DENIED,
        user_id=uuid.uuid4(),
        entity_type="user",
        entity_id=uuid.uuid4(),
        resource_type=AuditResourceType.USER,
    )
    assert res.result == AuditResult.DENIED


@pytest.mark.asyncio
async def test_create_event_system_branch():
    repo, session, result = make_repo()
    res = await repo.create_event(
        action=AuditAction.USER_LOGIN,
        result=AuditResult.SUCCESS,
        user_id=None,
        entity_type="node",
    )
    assert res.user_id is None
    assert res.result == AuditResult.SUCCESS


@pytest.mark.asyncio
async def test_create_event_with_refresh():
    repo, session, result = make_repo()
    res = await repo.create_event(
        action=AuditAction.USER_LOGIN,
        user_id=uuid.uuid4(),
        refresh=True,
    )
    session.refresh.assert_awaited()
    assert res is not None


@pytest.mark.asyncio
async def test_create_event_request_id_too_long_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_event(
            action=AuditAction.USER_LOGIN,
            user_id=uuid.uuid4(),
            request_id="x" * 129,
        )


# ---------------------------------------------------------------------------
# create_log / create_user_log / create_system_log / create_entity_log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_log_user():
    repo, session, result = make_repo()
    uid = uuid.uuid4()
    res = await repo.create_log(action=AuditAction.USER_LOGIN, user_id=uid)
    assert res.user_id == uid


@pytest.mark.asyncio
async def test_create_user_log():
    repo, session, result = make_repo()
    uid = uuid.uuid4()
    res = await repo.create_user_log(user_id=uid, action=AuditAction.USER_LOGOUT)
    assert res.user_id == uid
    assert res.action == AuditAction.USER_LOGOUT


@pytest.mark.asyncio
async def test_create_system_log():
    repo, session, result = make_repo()
    res = await repo.create_system_log(
        action=AuditAction.USER_LOGIN, entity_type="node", entity_id=uuid.uuid4()
    )
    assert res.user_id is None


@pytest.mark.asyncio
async def test_create_entity_log():
    repo, session, result = make_repo()
    eid = uuid.uuid4()
    res = await repo.create_entity_log(
        action=AuditAction.FOLDER_CREATED,
        entity_type="folder",
        entity_id=eid,
        user_id=uuid.uuid4(),
    )
    assert res.entity_id == eid
    assert res.entity_type == "folder"


# ---------------------------------------------------------------------------
# list_logs and helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_logs_empty():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_logs()
    assert res == []
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_list_logs_with_all_filters():
    repo, session, result = make_repo()
    logs = [make_log(), make_log()]
    result.scalars.return_value.all.return_value = logs
    res = await repo.list_logs(
        offset=0,
        limit=10,
        user_id=uuid.uuid4(),
        actions=[AuditAction.USER_LOGIN, AuditAction.USER_LOGOUT],
        entity_type="user",
        entity_id=uuid.uuid4(),
        ip_address="127.0.0.1",
        created_from=datetime.now(UTC) - timedelta(days=1),
        created_to=datetime.now(UTC),
        system_only=False,
        metadata_contains={"k": "v"},
        sort_by="action",
        sort_direction="asc",
    )
    assert res == logs


@pytest.mark.asyncio
async def test_list_logs_system_only_true():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_logs(system_only=True)
    assert res == []


@pytest.mark.asyncio
async def test_list_logs_single_action():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_logs(action=AuditAction.USER_LOGIN)
    assert res == []


@pytest.mark.asyncio
async def test_list_logs_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.list_logs(offset=-1)


@pytest.mark.asyncio
async def test_list_logs_invalid_period():
    repo, session, result = make_repo()
    now = datetime.now(UTC)
    with pytest.raises(InvalidQueryError):
        await repo.list_logs(created_from=now, created_to=now - timedelta(days=1))


@pytest.mark.asyncio
async def test_list_logs_empty_actions_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_logs(actions=[])


@pytest.mark.asyncio
async def test_list_logs_invalid_sort_field():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_logs(sort_by="nope")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_logs_invalid_sort_direction():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_logs(sort_direction="sideways")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_logs_sqlalchemy_error_maps():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.list_logs()


@pytest.mark.asyncio
async def test_list_logs_entity_type_too_long_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_logs(entity_type="x" * 129)


@pytest.mark.asyncio
async def test_list_logs_ip_address_too_long_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_logs(ip_address="x" * 65)


# ---------------------------------------------------------------------------
# list_user_logs / list_system_logs / list_entity_logs / by action / by period
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_logs():
    repo, session, result = make_repo()
    logs = [make_log()]
    result.scalars.return_value.all.return_value = logs
    res = await repo.list_user_logs(uuid.uuid4())
    assert res == logs


@pytest.mark.asyncio
async def test_list_system_logs():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_system_logs(action=AuditAction.USER_LOGIN)
    assert res == []


@pytest.mark.asyncio
async def test_list_entity_logs():
    repo, session, result = make_repo()
    logs = [make_log()]
    result.scalars.return_value.all.return_value = logs
    res = await repo.list_entity_logs(entity_type="user", entity_id=uuid.uuid4())
    assert res == logs


@pytest.mark.asyncio
async def test_list_by_action():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_by_action(AuditAction.USER_LOGIN, user_id=uuid.uuid4())
    assert res == []


@pytest.mark.asyncio
async def test_list_by_actions():
    repo, session, result = make_repo()
    logs = [make_log()]
    result.scalars.return_value.all.return_value = logs
    res = await repo.list_by_actions(
        [AuditAction.USER_LOGIN, AuditAction.USER_LOGOUT]
    )
    assert res == logs


@pytest.mark.asyncio
async def test_list_by_actions_empty_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_by_actions([])


@pytest.mark.asyncio
async def test_list_by_period():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_by_period(
        created_from=datetime.now(UTC) - timedelta(days=1),
        created_to=datetime.now(UTC),
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_latest_user_logs():
    repo, session, result = make_repo()
    logs = [make_log()]
    result.scalars.return_value.all.return_value = logs
    res = await repo.get_latest_user_logs(uuid.uuid4(), limit=5)
    assert res == logs


@pytest.mark.asyncio
async def test_get_latest_entity_logs():
    repo, session, result = make_repo()
    logs = [make_log()]
    result.scalars.return_value.all.return_value = logs
    res = await repo.get_latest_entity_logs(
        entity_type="user", entity_id=uuid.uuid4(), limit=5
    )
    assert res == logs


# ---------------------------------------------------------------------------
# search_logs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_logs_with_query():
    repo, session, result = make_repo()
    logs = [make_log()]
    result.scalars.return_value.all.return_value = logs
    res = await repo.search_logs(query="  login  ", user_id=uuid.uuid4())
    assert res == logs


@pytest.mark.asyncio
async def test_search_logs_blank_query_skipped():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_logs(query="   ")
    assert res == []


@pytest.mark.asyncio
async def test_search_logs_none_query():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_logs(query=None)
    assert res == []


@pytest.mark.asyncio
async def test_search_logs_invalid_pagination():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.search_logs(limit=0)


@pytest.mark.asyncio
async def test_search_logs_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.search_logs(query="x")


# ---------------------------------------------------------------------------
# count_logs and count helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_logs_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=42)
    total = await repo.count_logs(user_id=uuid.uuid4())
    assert total == 42


@pytest.mark.asyncio
async def test_count_logs_with_query():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    total = await repo.count_logs(query="login")
    assert total == 3


@pytest.mark.asyncio
async def test_count_logs_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.count_logs()


@pytest.mark.asyncio
async def test_count_user_logs():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=7)
    total = await repo.count_user_logs(uuid.uuid4())
    assert total == 7


@pytest.mark.asyncio
async def test_count_entity_logs():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=2)
    total = await repo.count_entity_logs(entity_type="user", entity_id=uuid.uuid4())
    assert total == 2


@pytest.mark.asyncio
async def test_count_system_logs():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=9)
    total = await repo.count_system_logs()
    assert total == 9


@pytest.mark.asyncio
async def test_count_by_action():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=4)
    total = await repo.count_by_action(AuditAction.USER_LOGIN)
    assert total == 4


# ---------------------------------------------------------------------------
# get_action_counts / get_entity_type_counts / get_user_activity_counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_action_counts():
    repo, session, result = make_repo()
    result.all = MagicMock(
        return_value=[(AuditAction.USER_LOGIN, 5), (AuditAction.USER_LOGOUT, 2)]
    )
    counts = await repo.get_action_counts(user_id=uuid.uuid4())
    assert counts[AuditAction.USER_LOGIN] == 5
    assert counts[AuditAction.USER_LOGOUT] == 2


@pytest.mark.asyncio
async def test_get_action_counts_with_filters():
    repo, session, result = make_repo()
    result.all = MagicMock(return_value=[])
    counts = await repo.get_action_counts(
        entity_type="user",
        created_from=datetime.now(UTC) - timedelta(days=1),
        created_to=datetime.now(UTC),
    )
    assert counts == {}


@pytest.mark.asyncio
async def test_get_action_counts_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_action_counts()


@pytest.mark.asyncio
async def test_get_entity_type_counts():
    repo, session, result = make_repo()
    result.all = MagicMock(return_value=[("user", 3), ("folder", 1), (None, 9)])
    counts = await repo.get_entity_type_counts(user_id=uuid.uuid4())
    assert counts == {"user": 3, "folder": 1}


@pytest.mark.asyncio
async def test_get_entity_type_counts_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_entity_type_counts()


@pytest.mark.asyncio
async def test_get_user_activity_counts():
    repo, session, result = make_repo()
    uid1 = uuid.uuid4()
    uid2 = uuid.uuid4()
    result.all = MagicMock(return_value=[(uid1, 10), (uid2, 4), (None, 1)])
    counts = await repo.get_user_activity_counts()
    assert counts == {uid1: 10, uid2: 4}


@pytest.mark.asyncio
async def test_get_user_activity_counts_invalid_limit():
    repo, session, result = make_repo()
    with pytest.raises(Exception):
        await repo.get_user_activity_counts(limit=0)


@pytest.mark.asyncio
async def test_get_user_activity_counts_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_user_activity_counts()


# ---------------------------------------------------------------------------
# delete_logs_before
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_logs_before_returns_rowcount():
    repo, session, result = make_repo()
    result.rowcount = 12
    deleted = await repo.delete_logs_before(created_before=datetime.now(UTC))
    assert deleted == 12
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_delete_logs_before_no_flush():
    repo, session, result = make_repo()
    result.rowcount = 0
    deleted = await repo.delete_logs_before(
        created_before=datetime.now(UTC),
        action=AuditAction.USER_LOGIN,
        entity_type="user",
        system_only=True,
        flush=False,
    )
    assert deleted == 0
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_logs_before_integrity_error_maps_duplicate():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23505"))
    with pytest.raises(DuplicateEntityError):
        await repo.delete_logs_before(created_before=datetime.now(UTC))


@pytest.mark.asyncio
async def test_delete_logs_before_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.delete_logs_before(created_before=datetime.now(UTC))


# ---------------------------------------------------------------------------
# normalization helpers
# ---------------------------------------------------------------------------

def test_normalize_search_query_variants():
    repo, session, result = make_repo()
    assert repo._normalize_search_query(None) is None
    assert repo._normalize_search_query("   ") is None
    assert repo._normalize_search_query("  hi ") == "hi"


def test_normalize_entity_type_variants():
    repo, session, result = make_repo()
    assert repo._normalize_entity_type(None) is None
    assert repo._normalize_entity_type("   ") is None
    assert repo._normalize_entity_type("  user ") == "user"
    with pytest.raises(InvalidQueryError):
        repo._normalize_entity_type("x" * 129)


def test_normalize_ip_address_variants():
    repo, session, result = make_repo()
    assert repo._normalize_ip_address(None) is None
    assert repo._normalize_ip_address("   ") is None
    assert repo._normalize_ip_address("  1.2.3.4 ") == "1.2.3.4"
    with pytest.raises(InvalidQueryError):
        repo._normalize_ip_address("x" * 65)


def test_normalize_user_agent_variants():
    repo, session, result = make_repo()
    assert repo._normalize_user_agent(None) is None
    assert repo._normalize_user_agent("   ") is None
    assert repo._normalize_user_agent("  ua ") == "ua"


def test_normalize_identifier_variants():
    repo, session, result = make_repo()
    assert repo._normalize_identifier(None, field_name="f") is None
    assert repo._normalize_identifier("   ", field_name="f") is None
    assert repo._normalize_identifier("  x ", field_name="f") == "x"
    with pytest.raises(InvalidQueryError):
        repo._normalize_identifier("x" * 129, field_name="f")


def test_normalize_actions_dedup():
    repo, session, result = make_repo()
    res = repo._normalize_actions(
        action=AuditAction.USER_LOGIN,
        actions=[AuditAction.USER_LOGIN, AuditAction.USER_LOGOUT],
    )
    assert res == [AuditAction.USER_LOGIN, AuditAction.USER_LOGOUT]


def test_normalize_actions_empty_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_actions(action=None, actions=[])


def test_validate_period_ok():
    repo, session, result = make_repo()
    now = datetime.now(UTC)
    # Исключение не ожидается.
    repo._validate_period(created_from=now - timedelta(days=1), created_to=now)
    repo._validate_period(created_from=None, created_to=None)


def test_get_order_by_directions():
    repo, session, result = make_repo()
    assert repo._get_order_by("created_at", "asc") is not None
    assert repo._get_order_by("action", "desc") is not None


# ---------------------------------------------------------------------------
# _execute_audit_statement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_audit_statement_success():
    repo, session, result = make_repo()
    logs = [make_log()]
    result.scalars.return_value.all.return_value = logs
    res = await repo._execute_audit_statement(repo.select(), operation="op")
    assert res == logs


@pytest.mark.asyncio
async def test_execute_audit_statement_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._execute_audit_statement(repo.select(), operation="op")


# ---------------------------------------------------------------------------
# create() override: error mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_maps_duplicate_error():
    repo, session, result = make_repo()
    session.flush = AsyncMock(side_effect=make_integrity_error("23505"))
    log = make_log()
    with pytest.raises(DuplicateEntityError):
        await repo.create(log, flush=True)


@pytest.mark.asyncio
async def test_create_maps_raw_integrity_error(monkeypatch):
    from database.repositories.base import BaseRepository

    repo, session, result = make_repo()
    log = make_log()

    async def raise_integrity(self, entity, *, flush=True, refresh=False):
        raise make_integrity_error("99999")

    monkeypatch.setattr(BaseRepository, "create", raise_integrity)
    with pytest.raises(RepositoryError):
        await repo.create(log, flush=True)


@pytest.mark.asyncio
async def test_create_success():
    repo, session, result = make_repo()
    log = make_log()
    res = await repo.create(log, flush=True)
    session.add.assert_called_once_with(log)
    assert res is log
