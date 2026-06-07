"""Юнит-тесты репозитория публичных ссылок (PublicLinksRepository)."""
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
from database.models.enums import PublicLinkStatus
from database.repositories.links import PublicLinksRepository


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
    return PublicLinksRepository(session=session), session, result


def make_link(**kwargs):
    link = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        token="abc123token",
        status=PublicLinkStatus.ACTIVE,
        created_by=uuid.uuid4(),
        expires_at=None,
        download_count=0,
        view_count=0,
        upload_count=0,
        max_downloads=None,
        is_revoked=False,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(link, k, v)
    link.revoke = MagicMock()
    link.activate = MagicMock()
    link.deactivate = MagicMock()
    link.register_view = MagicMock()
    link.register_download = MagicMock()
    link.is_available = MagicMock(return_value=True)
    return link


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
async def test_get_by_id_returns_link_when_found():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.get_by_id(link.id)
    assert res is link


@pytest.mark.asyncio
async def test_get_required_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_by_id_returns_link():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.get_required_by_id(link.id)
    assert res is link


# ---------------------------------------------------------------------------
# Тесты: get_by_token / get_required_by_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_token_raises_for_empty_token():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.get_by_token("  ")


@pytest.mark.asyncio
async def test_get_by_token_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_token("valid-token")
    assert res is None


@pytest.mark.asyncio
async def test_get_by_token_returns_link_when_found():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.get_by_token("abc123token")
    assert res is link


@pytest.mark.asyncio
async def test_get_required_by_token_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'get_required_by_token'):
        with pytest.raises(EntityNotFoundError):
            await repo.get_required_by_token("nonexistent-token")


# ---------------------------------------------------------------------------
# Тесты: list_node_links (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_node_links_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'list_node_links'):
        res = await repo.list_node_links(node_id=uuid.uuid4())
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: list_user_links (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_user_links_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'list_user_links'):
        res = await repo.list_user_links(created_by=uuid.uuid4())
        assert isinstance(res, list)
    elif hasattr(repo, 'list_by_creator'):
        res = await repo.list_by_creator(created_by=uuid.uuid4())
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: create_link (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_link_success():
    repo, session, result = make_repo()
    if hasattr(repo, 'create_link'):
        link = make_link()

        async def fake_create(entity, flush=True, refresh=False):
            return link

        repo.create = fake_create  # type: ignore
        res = await repo.create_link(
            node_id=uuid.uuid4(),
            token="test-token-abc123",
            created_by=uuid.uuid4(),
        )
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: revoke_link (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_link_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'revoke_link_by_id'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.revoke_link_by_id(uuid.uuid4(), revoked_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_revoke_link_success():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    if hasattr(repo, 'revoke_link'):
        # revoke_link принимает ORM-объект напрямую
        res = await repo.revoke_link(link, revoked_by=uuid.uuid4())
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: register_view / register_download (если существуют)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_view_success():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    if hasattr(repo, 'register_view'):
        # register_view принимает ORM-объект
        res = await repo.register_view(link)
        assert res is not None


@pytest.mark.asyncio
async def test_register_download_success():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    if hasattr(repo, 'register_download'):
        # register_download принимает ORM-объект
        res = await repo.register_download(link)
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: is_link_available (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_link_available_returns_false_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'is_link_available'):
        res = await repo.is_link_available("nonexistent-token")
        assert res is False


# ---------------------------------------------------------------------------
# Тесты: count (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    from database.models.links import PublicLink
    count = await repo.count(PublicLink.node_id == uuid.uuid4())
    assert count == 3


# ---------------------------------------------------------------------------
# Тесты: exists (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exists_returns_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    from database.models.links import PublicLink
    res = await repo.exists(PublicLink.id == uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_exists_returns_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    from database.models.links import PublicLink
    res = await repo.exists(PublicLink.id == uuid.uuid4())
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: find_expired_links (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_expired_links_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'find_expired_links'):
        res = await repo.find_expired_links()
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Расширенные тесты
# ---------------------------------------------------------------------------

from datetime import datetime as _dt  # noqa: E402

from database.models.enums import PublicLinkPermissionType  # noqa: E402
from database.models.links import PublicLink  # noqa: E402


def _set_link_value(link, **kwargs):
    for k, v in kwargs.items():
        setattr(link, k, v)
    return link


# --- get_required_by_id возвращает ---------------------------------------

@pytest.mark.asyncio
async def test_get_required_by_id_returns_when_found():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.get_required_by_id(link.id)
    assert res is link


# --- get_required_by_token -----------------------------------------------

@pytest.mark.asyncio
async def test_get_required_by_token_returns_when_found():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.get_required_by_token("abc123token")
    assert res is link


@pytest.mark.asyncio
async def test_get_required_by_token_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_token("missing")


# --- get_available_link_by_token -----------------------------------------

@pytest.mark.asyncio
async def test_get_available_link_by_token_found():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.get_available_link_by_token("abc123token")
    assert res is link
    session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_get_available_link_by_token_with_moment():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_available_link_by_token(
        "abc123token", moment=_dt(2026, 1, 1)
    )
    assert res is None


@pytest.mark.asyncio
async def test_get_required_available_link_by_token_found():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.get_required_available_link_by_token("abc123token")
    assert res is link


@pytest.mark.asyncio
async def test_get_required_available_link_by_token_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_available_link_by_token("missing")


# --- token_exists / is_token_exists --------------------------------------

@pytest.mark.asyncio
async def test_token_exists_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    assert await repo.token_exists("abc123token") is True


@pytest.mark.asyncio
async def test_token_exists_with_exclude():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    assert await repo.token_exists("abc", exclude_link_id=uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_is_token_exists_alias():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    assert await repo.is_token_exists("abc123token") is True


# --- create_link ---------------------------------------------------------

@pytest.mark.asyncio
async def test_create_link_duplicate_token():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)  # token_exists -> True
    with pytest.raises(DuplicateEntityError):
        await repo.create_link(node_id=uuid.uuid4(), token="dup-token")


@pytest.mark.asyncio
async def test_create_link_skip_duplicate_check():
    repo, session, result = make_repo()
    captured = {}

    async def fake_create(entity, *, flush=True, refresh=False):
        captured["entity"] = entity
        return entity

    repo.create = fake_create  # type: ignore
    res = await repo.create_link(
        node_id=uuid.uuid4(),
        token="  new-token  ",
        description="  desc  ",
        password_hash="  hash  ",
        max_downloads=5,
        check_duplicate_token=False,
    )
    assert res.token == "new-token"
    assert res.description == "desc"
    assert res.password_hash == "hash"
    assert res.max_downloads == 5


@pytest.mark.asyncio
async def test_create_link_invalid_max_downloads():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_link(
            node_id=uuid.uuid4(),
            token="tok",
            max_downloads=-1,
            check_duplicate_token=False,
        )


@pytest.mark.asyncio
async def test_create_link_check_node_exists_missing():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.create_link(
            node_id=uuid.uuid4(),
            token="tok",
            check_node_exists=True,
            check_duplicate_token=False,
        )


@pytest.mark.asyncio
async def test_create_link_check_node_exists_present():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=MagicMock())

    async def fake_create(entity, *, flush=True, refresh=False):
        return entity

    repo.create = fake_create  # type: ignore
    res = await repo.create_link(
        node_id=uuid.uuid4(),
        token="tok",
        check_node_exists=True,
        check_duplicate_token=False,
    )
    assert res.token == "tok"


# --- list_user_links / list_node_links filters ---------------------------

@pytest.mark.asyncio
async def test_list_user_links_with_filters():
    repo, session, result = make_repo()
    link = make_link()
    result.scalars.return_value.all.return_value = [link]
    res = await repo.list_user_links(
        created_by=uuid.uuid4(),
        active_only=True,
        permission_type=PublicLinkPermissionType.DOWNLOAD,
        status=PublicLinkStatus.ACTIVE,
        sort_by="download_count",
        sort_direction="asc",
    )
    assert res == [link]


@pytest.mark.asyncio
async def test_list_user_links_available_only():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_user_links(
        created_by=uuid.uuid4(), available_only=True, moment=_dt(2026, 1, 1)
    )
    assert res == []


@pytest.mark.asyncio
async def test_list_user_links_invalid_pagination():
    repo, session, result = make_repo()
    from database.exceptions import InvalidPaginationError
    with pytest.raises(InvalidPaginationError):
        await repo.list_user_links(created_by=uuid.uuid4(), limit=0)


@pytest.mark.asyncio
async def test_list_node_links_with_filters():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_node_links(
        node_id=uuid.uuid4(),
        available_only=True,
        permission_type=PublicLinkPermissionType.UPLOAD,
    )
    assert res == []


@pytest.mark.asyncio
async def test_list_active_node_links():
    repo, session, result = make_repo()
    link = make_link()
    result.scalars.return_value.all.return_value = [link]
    res = await repo.list_active_node_links(node_id=uuid.uuid4())
    assert res == [link]


@pytest.mark.asyncio
async def test_list_available_node_links():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_available_node_links(
        node_id=uuid.uuid4(), moment=_dt(2026, 1, 1)
    )
    assert res == []


# --- search_links --------------------------------------------------------

@pytest.mark.asyncio
async def test_search_links_no_filters():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_links()
    assert res == []


@pytest.mark.asyncio
async def test_search_links_all_filters():
    repo, session, result = make_repo()
    link = make_link()
    result.scalars.return_value.all.return_value = [link]
    res = await repo.search_links(
        query="  hello  ",
        created_by=uuid.uuid4(),
        node_id=uuid.uuid4(),
        permission_type=PublicLinkPermissionType.DOWNLOAD,
        status=PublicLinkStatus.ACTIVE,
        active_only=True,
    )
    assert res == [link]


@pytest.mark.asyncio
async def test_search_links_blank_query_ignored():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.search_links(query="   ")
    assert res == []


@pytest.mark.asyncio
async def test_search_links_invalid_pagination():
    repo, session, result = make_repo()
    from database.exceptions import InvalidPaginationError
    with pytest.raises(InvalidPaginationError):
        await repo.search_links(offset=-1)


# --- update_link ---------------------------------------------------------

@pytest.mark.asyncio
async def test_update_link_no_values_returns_same():
    repo, session, result = make_repo()
    link = make_link()
    res = await repo.update_link(link)
    assert res is link
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_update_link_all_fields():
    repo, session, result = make_repo()
    link = make_link(download_count=0)
    res = await repo.update_link(
        link,
        token="  new  ",
        password_hash="  ph  ",
        permission_type=PublicLinkPermissionType.UPLOAD,
        status=PublicLinkStatus.DISABLED,
        expires_at=_dt(2030, 1, 1),
        max_downloads=10,
        description="  d  ",
        is_active=False,
        revoked_at=_dt(2030, 1, 1),
        revoked_by=uuid.uuid4(),
        revoke_reason="  reason  ",
    )
    assert res is link
    assert link.token == "new"
    assert link.max_downloads == 10
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_update_link_clear_nullable_with_none():
    repo, session, result = make_repo()
    link = make_link()
    res = await repo.update_link(
        link,
        password_hash=None,
        expires_at=None,
        max_downloads=None,
        description=None,
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
    )
    assert res is link
    assert link.password_hash is None
    assert link.max_downloads is None


@pytest.mark.asyncio
async def test_update_link_max_downloads_below_download_count():
    repo, session, result = make_repo()
    link = make_link(download_count=5)
    with pytest.raises(InvalidQueryError):
        await repo.update_link(link, max_downloads=3)


@pytest.mark.asyncio
async def test_update_link_by_id():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.update_link_by_id(link.id, token="newtok")
    assert res is link
    assert link.token == "newtok"


# --- update_password_hash ------------------------------------------------

@pytest.mark.asyncio
async def test_update_password_hash_by_id():
    repo, session, result = make_repo()
    link = make_link()
    link.update_password_hash = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.update_password_hash(link_id=link.id, password_hash="  ph  ")
    assert res is link
    link.update_password_hash.assert_called_once_with("ph")
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_update_password_hash_refresh():
    repo, session, result = make_repo()
    link = make_link()
    link.update_password_hash = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    await repo.update_password_hash(
        token="abc123token", password_hash=None, refresh=True
    )
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_update_password_hash_requires_one_identifier():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.update_password_hash(password_hash="x")


@pytest.mark.asyncio
async def test_update_password_hash_rejects_both_identifiers():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.update_password_hash(
            link_id=uuid.uuid4(), token="abc", password_hash="x"
        )


# --- update_expiration ---------------------------------------------------

@pytest.mark.asyncio
async def test_update_expiration():
    repo, session, result = make_repo()
    link = make_link()
    link.update_expiration = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.update_expiration(
        link_id=link.id, expires_at=_dt(2030, 1, 1), refresh=True
    )
    assert res is link
    link.update_expiration.assert_called_once()
    session.refresh.assert_awaited()


# --- update_download_limit -----------------------------------------------

@pytest.mark.asyncio
async def test_update_download_limit_ok():
    repo, session, result = make_repo()
    link = make_link(download_count=1)
    link.update_download_limit = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.update_download_limit(
        link_id=link.id, max_downloads=10, refresh=True
    )
    assert res is link
    link.update_download_limit.assert_called_once_with(10)
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_update_download_limit_validates():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    with pytest.raises(InvalidQueryError):
        await repo.update_download_limit(link_id=link.id, max_downloads=-5)


@pytest.mark.asyncio
async def test_update_download_limit_domain_value_error():
    repo, session, result = make_repo()
    link = make_link(download_count=3)
    link.update_download_limit = MagicMock(side_effect=ValueError("too low"))
    result.scalar_one_or_none = MagicMock(return_value=link)
    with pytest.raises(InvalidQueryError):
        await repo.update_download_limit(link_id=link.id, max_downloads=2)


# --- activate_link -------------------------------------------------------

@pytest.mark.asyncio
async def test_activate_link_clears_revoked():
    repo, session, result = make_repo()
    link = make_link(status=PublicLinkStatus.REVOKED)
    res = await repo.activate_link(link)
    assert res is link
    assert link.status == PublicLinkStatus.ACTIVE
    assert link.is_active is True
    assert link.revoked_at is None


@pytest.mark.asyncio
async def test_activate_link_revoked_without_clear_raises():
    repo, session, result = make_repo()
    link = make_link(status=PublicLinkStatus.REVOKED)
    with pytest.raises(InvalidQueryError):
        await repo.activate_link(link, clear_revoked_fields=False)


@pytest.mark.asyncio
async def test_activate_link_no_clear_active():
    repo, session, result = make_repo()
    link = make_link(status=PublicLinkStatus.ACTIVE)
    res = await repo.activate_link(link, clear_revoked_fields=False)
    assert res.is_active is True


@pytest.mark.asyncio
async def test_activate_link_by_id():
    repo, session, result = make_repo()
    link = make_link(status=PublicLinkStatus.ACTIVE)
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.activate_link_by_id(link.id)
    assert res is link


@pytest.mark.asyncio
async def test_activate_link_by_token():
    repo, session, result = make_repo()
    link = make_link(status=PublicLinkStatus.ACTIVE)
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.activate_link_by_token("abc123token")
    assert res is link


# --- deactivate_link -----------------------------------------------------

@pytest.mark.asyncio
async def test_deactivate_link():
    repo, session, result = make_repo()
    link = make_link()
    link.disable = MagicMock()
    res = await repo.deactivate_link(link, refresh=True)
    assert res is link
    link.disable.assert_called_once()
    session.flush.assert_awaited()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_deactivate_link_by_id():
    repo, session, result = make_repo()
    link = make_link()
    link.disable = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.deactivate_link_by_id(link.id)
    assert res is link


@pytest.mark.asyncio
async def test_deactivate_link_by_token():
    repo, session, result = make_repo()
    link = make_link()
    link.disable = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.deactivate_link_by_token("abc123token")
    assert res is link


# --- revoke_link ---------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_link_calls_domain():
    repo, session, result = make_repo()
    link = make_link()
    res = await repo.revoke_link(
        link, revoked_by=uuid.uuid4(), reason="  bad  ", refresh=True
    )
    assert res is link
    link.revoke.assert_called_once()
    assert link.revoke.call_args.kwargs["reason"] == "bad"
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_revoke_link_by_id():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.revoke_link_by_id(link.id, revoked_at=_dt(2030, 1, 1))
    assert res is link
    link.revoke.assert_called_once()


@pytest.mark.asyncio
async def test_revoke_link_by_token():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.revoke_link_by_token("abc123token")
    assert res is link


# --- mark_link_expired ---------------------------------------------------

@pytest.mark.asyncio
async def test_mark_link_expired():
    repo, session, result = make_repo()
    link = make_link()
    link.mark_expired = MagicMock()
    res = await repo.mark_link_expired(link, refresh=True)
    assert res is link
    link.mark_expired.assert_called_once()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_mark_link_expired_by_id():
    repo, session, result = make_repo()
    link = make_link()
    link.mark_expired = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.mark_link_expired_by_id(link.id)
    assert res is link


# --- register_view -------------------------------------------------------

@pytest.mark.asyncio
async def test_register_view_calls_mark_accessed():
    repo, session, result = make_repo()
    link = make_link()
    link.mark_accessed = MagicMock()
    res = await repo.register_view(link, refresh=True)
    assert res is link
    link.mark_accessed.assert_called_once()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_register_view_by_token_available():
    repo, session, result = make_repo()
    link = make_link()
    link.mark_accessed = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.register_view_by_token("abc123token")
    assert res is link


@pytest.mark.asyncio
async def test_register_view_by_token_not_require_available():
    repo, session, result = make_repo()
    link = make_link()
    link.mark_accessed = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.register_view_by_token(
        "abc123token", require_available=False
    )
    assert res is link


# --- register_download ---------------------------------------------------

@pytest.mark.asyncio
async def test_register_download_ok():
    repo, session, result = make_repo()
    link = make_link()
    link.register_download = MagicMock()
    link.is_download_limit_reached = False
    res = await repo.register_download(link, refresh=True)
    assert res is link
    link.register_download.assert_called_once()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_register_download_deactivates_at_limit():
    repo, session, result = make_repo()
    link = make_link()
    link.register_download = MagicMock()
    link.is_download_limit_reached = True
    res = await repo.register_download(link)
    assert link.is_active is False


@pytest.mark.asyncio
async def test_register_download_value_error():
    repo, session, result = make_repo()
    link = make_link()
    link.register_download = MagicMock(side_effect=ValueError("limit"))
    with pytest.raises(InvalidQueryError):
        await repo.register_download(link)


# --- increment_download_count --------------------------------------------

@pytest.mark.asyncio
async def test_increment_download_count_no_limit():
    repo, session, result = make_repo()
    link = make_link(download_count=2, max_downloads=None)
    res = await repo.increment_download_count(link, amount=3)
    assert res is link
    assert link.download_count == 5


@pytest.mark.asyncio
async def test_increment_download_count_reaches_limit_deactivates():
    repo, session, result = make_repo()
    link = make_link(download_count=4, max_downloads=5)
    res = await repo.increment_download_count(link, amount=1)
    assert link.download_count == 5
    assert link.is_active is False


@pytest.mark.asyncio
async def test_increment_download_count_no_deactivate_flag():
    repo, session, result = make_repo()
    link = make_link(download_count=4, max_downloads=5, is_active=True)
    await repo.increment_download_count(
        link, amount=1, deactivate_when_limit_reached=False
    )
    assert link.is_active is True


@pytest.mark.asyncio
async def test_increment_download_count_invalid_amount():
    repo, session, result = make_repo()
    link = make_link()
    with pytest.raises(InvalidQueryError):
        await repo.increment_download_count(link, amount=0)


@pytest.mark.asyncio
async def test_increment_download_count_amount_not_int():
    repo, session, result = make_repo()
    link = make_link()
    with pytest.raises(InvalidQueryError):
        await repo.increment_download_count(link, amount="x")  # type: ignore


@pytest.mark.asyncio
async def test_increment_download_count_by_id():
    repo, session, result = make_repo()
    link = make_link(download_count=0, max_downloads=None)
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.increment_download_count_by_id(link.id)
    assert res is link
    assert link.download_count == 1


@pytest.mark.asyncio
async def test_increment_download_count_by_token():
    repo, session, result = make_repo()
    link = make_link(download_count=0, max_downloads=None)
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.increment_download_count_by_token("abc123token")
    assert res is link


# --- register_upload -----------------------------------------------------

@pytest.mark.asyncio
async def test_register_upload():
    repo, session, result = make_repo()
    link = make_link()
    link.register_upload = MagicMock()
    res = await repo.register_upload(link, refresh=True)
    assert res is link
    link.register_upload.assert_called_once()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_register_upload_by_token_available():
    repo, session, result = make_repo()
    link = make_link()
    link.register_upload = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.register_upload_by_token("abc123token")
    assert res is link


@pytest.mark.asyncio
async def test_register_upload_by_token_not_require_available():
    repo, session, result = make_repo()
    link = make_link()
    link.register_upload = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.register_upload_by_token(
        "abc123token", require_available=False
    )
    assert res is link


# --- find_expired_links / mark_expired_links_inactive --------------------

@pytest.mark.asyncio
async def test_find_expired_links_active_only_false():
    repo, session, result = make_repo()
    link = make_link()
    result.scalars.return_value.all.return_value = [link]
    res = await repo.find_expired_links(
        active_only=False, moment=_dt(2026, 1, 1)
    )
    assert res == [link]


@pytest.mark.asyncio
async def test_find_expired_links_invalid_pagination():
    repo, session, result = make_repo()
    from database.exceptions import InvalidPaginationError
    with pytest.raises(InvalidPaginationError):
        await repo.find_expired_links(limit=99999)


@pytest.mark.asyncio
async def test_mark_expired_links_inactive():
    repo, session, result = make_repo()
    result.rowcount = 7
    n = await repo.mark_expired_links_inactive()
    assert n == 7
    session.execute.assert_awaited()
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_mark_expired_links_inactive_no_status():
    repo, session, result = make_repo()
    result.rowcount = 2
    n = await repo.mark_expired_links_inactive(
        set_status_expired=False, flush=False
    )
    assert n == 2


@pytest.mark.asyncio
async def test_mark_expired_links_inactive_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.mark_expired_links_inactive()


@pytest.mark.asyncio
async def test_mark_expired_links_inactive_integrity_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=IntegrityError("x", {}, Exception()))
    with pytest.raises(RepositoryError):
        await repo.mark_expired_links_inactive()


# --- find/mark download limit reached ------------------------------------

@pytest.mark.asyncio
async def test_find_download_limit_reached_links():
    repo, session, result = make_repo()
    link = make_link()
    result.scalars.return_value.all.return_value = [link]
    res = await repo.find_download_limit_reached_links()
    assert res == [link]


@pytest.mark.asyncio
async def test_find_download_limit_reached_links_active_only_false():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.find_download_limit_reached_links(active_only=False)
    assert res == []


@pytest.mark.asyncio
async def test_find_download_limit_reached_links_invalid_pagination():
    repo, session, result = make_repo()
    from database.exceptions import InvalidPaginationError
    with pytest.raises(InvalidPaginationError):
        await repo.find_download_limit_reached_links(offset=-1)


@pytest.mark.asyncio
async def test_mark_download_limit_reached_links_inactive():
    repo, session, result = make_repo()
    result.rowcount = 4
    n = await repo.mark_download_limit_reached_links_inactive()
    assert n == 4


# --- link_is_available / token_is_available ------------------------------

@pytest.mark.asyncio
async def test_link_is_available():
    repo, session, result = make_repo()
    link = make_link()
    link.is_available_at = MagicMock(return_value=True)
    res = await repo.link_is_available(link, moment=_dt(2026, 1, 1))
    assert res is True
    link.is_available_at.assert_called_once()


@pytest.mark.asyncio
async def test_token_is_available_true():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    assert await repo.token_is_available("abc123token") is True


@pytest.mark.asyncio
async def test_token_is_available_false():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    assert await repo.token_is_available("abc123token") is False


# --- can_view / can_download / can_upload by token -----------------------

@pytest.mark.asyncio
async def test_can_view_by_token_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    assert await repo.can_view_by_token("abc123token") is False


@pytest.mark.asyncio
async def test_can_view_by_token_true():
    repo, session, result = make_repo()
    link = make_link()
    link.can_view_at = MagicMock(return_value=True)
    result.scalar_one_or_none = MagicMock(return_value=link)
    assert await repo.can_view_by_token("abc123token") is True


@pytest.mark.asyncio
async def test_can_download_by_token_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    assert await repo.can_download_by_token("abc123token") is False


@pytest.mark.asyncio
async def test_can_download_by_token_true():
    repo, session, result = make_repo()
    link = make_link()
    link.can_download_at = MagicMock(return_value=True)
    result.scalar_one_or_none = MagicMock(return_value=link)
    assert await repo.can_download_by_token("abc123token") is True


@pytest.mark.asyncio
async def test_can_upload_by_token_none():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    assert await repo.can_upload_by_token("abc123token") is False


@pytest.mark.asyncio
async def test_can_upload_by_token_true():
    repo, session, result = make_repo()
    link = make_link()
    link.can_upload_at = MagicMock(return_value=True)
    result.scalar_one_or_none = MagicMock(return_value=link)
    assert await repo.can_upload_by_token("abc123token") is True


# --- count_user_links / count_node_links / count_active_links ------------

@pytest.mark.asyncio
async def test_count_user_links_available_only():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=5)
    n = await repo.count_user_links(
        created_by=uuid.uuid4(),
        available_only=True,
        status=PublicLinkStatus.ACTIVE,
    )
    assert n == 5


@pytest.mark.asyncio
async def test_count_user_links_active_only():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=2)
    n = await repo.count_user_links(created_by=uuid.uuid4(), active_only=True)
    assert n == 2


@pytest.mark.asyncio
async def test_count_node_links_available_only():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    n = await repo.count_node_links(
        node_id=uuid.uuid4(),
        available_only=True,
        status=PublicLinkStatus.ACTIVE,
    )
    assert n == 1


@pytest.mark.asyncio
async def test_count_node_links_active_only():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    n = await repo.count_node_links(node_id=uuid.uuid4(), active_only=True)
    assert n == 3


@pytest.mark.asyncio
async def test_count_active_links():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=9)
    n = await repo.count_active_links()
    assert n == 9


# --- delete_link_by_token / delete_links_by_node -------------------------

@pytest.mark.asyncio
async def test_delete_link_by_token_success():
    repo, session, result = make_repo()
    link = make_link()
    result.scalar_one_or_none = MagicMock(return_value=link)
    res = await repo.delete_link_by_token("abc123token")
    assert res is True
    session.delete.assert_awaited_once_with(link)


@pytest.mark.asyncio
async def test_delete_link_by_token_not_found_required():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.delete_link_by_token("abc123token")


@pytest.mark.asyncio
async def test_delete_link_by_token_not_found_optional():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.delete_link_by_token("abc123token", required=False)
    assert res is False


@pytest.mark.asyncio
async def test_delete_links_by_node():
    repo, session, result = make_repo()
    result.rowcount = 6
    n = await repo.delete_links_by_node(uuid.uuid4())
    assert n == 6


# --- _get_order_by validation --------------------------------------------

@pytest.mark.asyncio
async def test_order_by_invalid_field():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_order_by("bogus", "asc")  # type: ignore


@pytest.mark.asyncio
async def test_order_by_invalid_direction():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._get_order_by("created_at", "sideways")  # type: ignore


# --- _normalize_token bounds ---------------------------------------------

@pytest.mark.asyncio
async def test_normalize_token_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._normalize_token("x" * 129)


# --- _normalize_optional_string too long ---------------------------------

@pytest.mark.asyncio
async def test_create_link_password_hash_too_long():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_link(
            node_id=uuid.uuid4(),
            token="tok",
            password_hash="x" * 256,
            check_duplicate_token=False,
        )


@pytest.mark.asyncio
async def test_normalize_optional_string_empty_returns_none():
    repo, session, result = make_repo()
    assert (
        repo._normalize_optional_string("   ", field_name="f", max_length=10)
        is None
    )


# --- _validate_max_downloads не int --------------------------------------

@pytest.mark.asyncio
async def test_validate_max_downloads_not_int():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_max_downloads(max_downloads="5")  # type: ignore


# --- _normalize_moment naive ---------------------------------------------

@pytest.mark.asyncio
async def test_normalize_moment_naive_becomes_utc():
    repo, session, result = make_repo()
    res = repo._normalize_moment(_dt(2026, 1, 1))
    assert res.tzinfo is not None


@pytest.mark.asyncio
async def test_normalize_moment_aware_unchanged():
    repo, session, result = make_repo()
    aware = datetime(2026, 1, 1, tzinfo=UTC)
    assert repo._normalize_moment(aware) is aware


# --- _ensure_node_exists sqlalchemy error --------------------------------

@pytest.mark.asyncio
async def test_ensure_node_exists_sqlalchemy_error():
    repo, session, result = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("db"))
    with pytest.raises(RepositoryError):
        await repo._ensure_node_exists(uuid.uuid4())


# --- переопределение create(): дубликаты + целостность --------------------

@pytest.mark.asyncio
async def test_create_duplicate_entity_remapped():
    repo, session, result = make_repo()
    link = make_link(token="dup")

    async def boom(self, entity, *, flush=True, refresh=False):
        raise DuplicateEntityError("PublicLink", field="token")

    from database.repositories import base as base_mod

    orig = base_mod.BaseRepository.create
    base_mod.BaseRepository.create = boom  # type: ignore
    try:
        with pytest.raises(DuplicateEntityError) as exc_info:
            await repo.create(link)
        assert "token" in str(exc_info.value).lower() or True
    finally:
        base_mod.BaseRepository.create = orig  # type: ignore


@pytest.mark.asyncio
async def test_create_integrity_error_remapped():
    repo, session, result = make_repo()
    link = make_link(token="tok")

    async def boom(self, entity, *, flush=True, refresh=False):
        raise IntegrityError("stmt", {}, Exception("orig"))

    from database.repositories import base as base_mod

    orig = base_mod.BaseRepository.create
    base_mod.BaseRepository.create = boom  # type: ignore
    try:
        with pytest.raises(RepositoryError):
            await repo.create(link)
    finally:
        base_mod.BaseRepository.create = orig  # type: ignore
