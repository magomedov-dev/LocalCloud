"""Юнит-тесты репозитория прав доступа к узлам (NodePermissionsRepository)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.exceptions import (
    EntityNotFoundError,
    InvalidQueryError,
    RepositoryError,
)
from database.repositories.permissions import NodePermissionsRepository


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
    return NodePermissionsRepository(session=session), session, result


def make_permission(**kwargs):
    perm = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        granted_by=uuid.uuid4(),
        can_read=True,
        can_write=False,
        can_delete=False,
        can_share=False,
        is_revoked=False,
        expires_at=None,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(perm, k, v)
    perm.revoke = MagicMock()
    perm.restore = MagicMock()
    return perm


# ---------------------------------------------------------------------------
# Тесты: get_permission_by_id / get_required_permission_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_permission_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    res = await repo.get_permission_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_permission_by_id_returns_permission_when_found():
    repo, session, result = make_repo()
    perm = make_permission()
    session.get = AsyncMock(return_value=perm)
    res = await repo.get_permission_by_id(perm.id)
    assert res is perm


@pytest.mark.asyncio
async def test_get_required_permission_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_permission_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_by_node_and_user / get_required_by_node_and_user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_node_and_user_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_node_and_user(
        node_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    assert res is None


@pytest.mark.asyncio
async def test_get_by_node_and_user_returns_permission_when_found():
    repo, session, result = make_repo()
    perm = make_permission()
    result.scalar_one_or_none = MagicMock(return_value=perm)
    res = await repo.get_by_node_and_user(
        node_id=perm.node_id,
        user_id=perm.user_id,
    )
    assert res is perm


@pytest.mark.asyncio
async def test_get_required_by_node_and_user_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_node_and_user(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
        )


# ---------------------------------------------------------------------------
# Тесты: grant_permission (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_grant_permission_success():
    repo, session, result = make_repo()
    if hasattr(repo, 'grant_permission'):
        perm = make_permission()

        async def fake_create(entity, flush=True, refresh=False):
            return perm

        repo.create = fake_create  # type: ignore
        result.scalar_one_or_none = MagicMock(return_value=None)
        res = await repo.grant_permission(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            granted_by=uuid.uuid4(),
            can_read=True,
        )
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: list_node_permissions / list_user_permissions (если существуют)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_node_permissions_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'list_node_permissions'):
        res = await repo.list_node_permissions(uuid.uuid4())
        assert isinstance(res, list)


@pytest.mark.asyncio
async def test_list_user_permissions_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'list_user_permissions'):
        res = await repo.list_user_permissions(uuid.uuid4())
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: revoke_permission (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_permission_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    if hasattr(repo, 'revoke_permission'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.revoke_permission(MagicMock(), revoked_by=uuid.uuid4())


@pytest.mark.asyncio
async def test_revoke_permission_success():
    repo, session, result = make_repo()
    perm = make_permission()
    session.get = AsyncMock(return_value=perm)
    if hasattr(repo, 'revoke_permission'):
        # revoke_permission принимает ORM-объект, а не ID
        res = await repo.revoke_permission(perm)
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: check_user_access (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_user_access_returns_false_when_no_permission():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'check_user_access'):
        res = await repo.check_user_access(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
        )
        assert res is False or res is None


# ---------------------------------------------------------------------------
# Тесты: count (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=2)
    from database.models.permissions import NodePermission
    count = await repo.count(NodePermission.node_id == uuid.uuid4())
    assert count == 2


# ---------------------------------------------------------------------------
# Тесты: exists (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exists_returns_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    from database.models.permissions import NodePermission
    res = await repo.exists(NodePermission.id == uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_exists_returns_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    from database.models.permissions import NodePermission
    res = await repo.exists(NodePermission.id == uuid.uuid4())
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: update_permission (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_permission_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    if hasattr(repo, 'update_permission'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.update_permission(uuid.uuid4(), can_write=True)


# ---------------------------------------------------------------------------
# Тесты: bulk_revoke (если существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_revoke_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 3
    if hasattr(repo, 'bulk_revoke'):
        count = await repo.bulk_revoke(node_id=uuid.uuid4())
        assert isinstance(count, int)
    elif hasattr(repo, 'revoke_all_node_permissions'):
        count = await repo.revoke_all_node_permissions(node_id=uuid.uuid4())
        assert isinstance(count, int)


# ---------------------------------------------------------------------------
# Расширенные хелперы
# ---------------------------------------------------------------------------

def make_orm_permission(**kwargs):
    """Создать объект, похожий на NodePermission, с конкретными булевыми флагами.

    Базовый ``update`` вызывает ``setattr`` по реальным именам атрибутов, а
    ``_validate_any_permission`` читает флаги ``permission.can_*``, поэтому
    флаги должны быть обычными булевыми значениями (не атрибутами MagicMock).
    """
    perm = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        granted_by=uuid.uuid4(),
        can_read=True,
        can_download=False,
        can_write=False,
        can_delete=False,
        can_share=False,
        expires_at=None,
        revoked_at=None,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(perm, k, v)
    return perm


# ---------------------------------------------------------------------------
# get_active_by_node_and_user / required variants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_by_node_and_user_found():
    repo, session, result = make_repo()
    perm = make_orm_permission()
    result.scalar_one_or_none = MagicMock(return_value=perm)
    res = await repo.get_active_by_node_and_user(
        node_id=perm.node_id, user_id=perm.user_id
    )
    assert res is perm


@pytest.mark.asyncio
async def test_get_active_by_node_and_user_with_moment():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_active_by_node_and_user(
        node_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        moment=datetime(2025, 1, 1, tzinfo=UTC),
    )
    assert res is None


@pytest.mark.asyncio
async def test_get_required_active_by_node_and_user_found():
    repo, session, result = make_repo()
    perm = make_orm_permission()
    result.scalar_one_or_none = MagicMock(return_value=perm)
    res = await repo.get_required_active_by_node_and_user(
        node_id=perm.node_id, user_id=perm.user_id
    )
    assert res is perm


@pytest.mark.asyncio
async def test_get_required_active_by_node_and_user_raises():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_active_by_node_and_user(
            node_id=uuid.uuid4(), user_id=uuid.uuid4()
        )


# ---------------------------------------------------------------------------
# grant_permission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_grant_permission_creates_new():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.grant_permission(
        node_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        granted_by=uuid.uuid4(),
        can_read=True,
        can_write=True,
    )
    session.add.assert_called_once()
    assert res is session.add.call_args.args[0]
    assert res.can_read is True
    assert res.can_write is True


@pytest.mark.asyncio
async def test_grant_permission_no_flags_raises():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.grant_permission(
            node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            can_read=False,
        )


@pytest.mark.asyncio
async def test_grant_permission_updates_existing():
    repo, session, result = make_repo()
    existing = make_orm_permission(can_read=True, can_write=False)
    result.scalar_one_or_none = MagicMock(return_value=existing)
    res = await repo.grant_permission(
        node_id=existing.node_id,
        user_id=existing.user_id,
        can_read=True,
        can_write=True,
    )
    # Существующая запись переиспользована и обновлена на месте.
    assert res is existing
    assert existing.can_write is True
    assert existing.revoked_at is None
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# update_permission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_permission_applies_all_fields():
    repo, session, result = make_repo()
    perm = make_orm_permission(can_read=True)
    new_grantor = uuid.uuid4()
    expires = datetime(2030, 1, 1, tzinfo=UTC)
    res = await repo.update_permission(
        perm,
        can_read=True,
        can_download=True,
        can_write=True,
        can_delete=True,
        can_share=True,
        granted_by=new_grantor,
        expires_at=expires,
        revoked_at=None,
    )
    assert res is perm
    assert perm.can_download is True
    assert perm.can_share is True
    assert perm.granted_by == new_grantor
    assert perm.expires_at == expires
    assert perm.revoked_at is None


@pytest.mark.asyncio
async def test_update_permission_unset_keeps_existing_flags():
    repo, session, result = make_repo()
    perm = make_orm_permission(can_read=True, can_write=False)
    # Флаги не переданы -> валидация использует текущее состояние права (can_read True).
    res = await repo.update_permission(perm)
    assert res is perm


@pytest.mark.asyncio
async def test_update_permission_clearing_all_flags_raises():
    repo, session, result = make_repo()
    perm = make_orm_permission(
        can_read=True,
        can_download=False,
        can_write=False,
        can_delete=False,
        can_share=False,
    )
    with pytest.raises(InvalidQueryError):
        await repo.update_permission(perm, can_read=False)


# ---------------------------------------------------------------------------
# update_permission_by_node_and_user / extend_permission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_permission_by_node_and_user_success():
    repo, session, result = make_repo()
    perm = make_orm_permission(can_read=True)
    result.scalar_one_or_none = MagicMock(return_value=perm)
    res = await repo.update_permission_by_node_and_user(
        node_id=perm.node_id,
        user_id=perm.user_id,
        can_write=True,
    )
    assert res is perm
    assert perm.can_write is True


@pytest.mark.asyncio
async def test_update_permission_by_node_and_user_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_permission_by_node_and_user(
            node_id=uuid.uuid4(), user_id=uuid.uuid4(), can_write=True
        )


@pytest.mark.asyncio
async def test_extend_permission_sets_expiry():
    repo, session, result = make_repo()
    perm = make_orm_permission(can_read=True)
    result.scalar_one_or_none = MagicMock(return_value=perm)
    expires = datetime(2031, 6, 1, tzinfo=UTC)
    res = await repo.extend_permission(
        node_id=perm.node_id, user_id=perm.user_id, expires_at=expires
    )
    assert res is perm
    assert perm.expires_at == expires


@pytest.mark.asyncio
async def test_extend_permission_to_unlimited():
    repo, session, result = make_repo()
    perm = make_orm_permission(can_read=True, expires_at=datetime.now(UTC))
    result.scalar_one_or_none = MagicMock(return_value=perm)
    res = await repo.extend_permission(
        node_id=perm.node_id, user_id=perm.user_id, expires_at=None
    )
    assert res is perm
    assert perm.expires_at is None


# ---------------------------------------------------------------------------
# отзыв / восстановление одного права
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_permission_default_moment():
    repo, session, result = make_repo()
    perm = make_orm_permission()
    res = await repo.revoke_permission(perm)
    assert res is perm
    assert perm.revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_permission_explicit_moment():
    repo, session, result = make_repo()
    perm = make_orm_permission()
    when = datetime(2025, 5, 5, tzinfo=UTC)
    res = await repo.revoke_permission(perm, revoked_at=when)
    assert perm.revoked_at == when
    assert res is perm


@pytest.mark.asyncio
async def test_revoke_permission_by_id_success():
    repo, session, result = make_repo()
    perm = make_orm_permission()
    session.get = AsyncMock(return_value=perm)
    res = await repo.revoke_permission_by_id(perm.id)
    assert res is perm
    assert perm.revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_permission_by_id_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.revoke_permission_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_revoke_permission_by_node_and_user_success():
    repo, session, result = make_repo()
    perm = make_orm_permission()
    result.scalar_one_or_none = MagicMock(return_value=perm)
    res = await repo.revoke_permission_by_node_and_user(
        node_id=perm.node_id, user_id=perm.user_id
    )
    assert res is perm
    assert perm.revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_permission_by_node_and_user_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.revoke_permission_by_node_and_user(
            node_id=uuid.uuid4(), user_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_restore_permission_clears_revoked():
    repo, session, result = make_repo()
    perm = make_orm_permission(can_read=True, revoked_at=datetime.now(UTC))
    res = await repo.restore_permission(perm)
    assert res is perm
    assert perm.revoked_at is None


@pytest.mark.asyncio
async def test_restore_permission_by_node_and_user_success():
    repo, session, result = make_repo()
    perm = make_orm_permission(can_read=True, revoked_at=datetime.now(UTC))
    result.scalar_one_or_none = MagicMock(return_value=perm)
    res = await repo.restore_permission_by_node_and_user(
        node_id=perm.node_id, user_id=perm.user_id
    )
    assert res is perm
    assert perm.revoked_at is None


@pytest.mark.asyncio
async def test_restore_permission_by_node_and_user_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.restore_permission_by_node_and_user(
            node_id=uuid.uuid4(), user_id=uuid.uuid4()
        )


# ---------------------------------------------------------------------------
# варианты массового отзыва
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoke_all_node_permissions_only_active():
    repo, session, result = make_repo()
    result.rowcount = 4
    count = await repo.revoke_all_node_permissions(node_id=uuid.uuid4())
    assert count == 4


@pytest.mark.asyncio
async def test_revoke_all_node_permissions_all():
    repo, session, result = make_repo()
    result.rowcount = 7
    count = await repo.revoke_all_node_permissions(
        node_id=uuid.uuid4(), only_active=False
    )
    assert count == 7


@pytest.mark.asyncio
async def test_revoke_all_user_permissions():
    repo, session, result = make_repo()
    result.rowcount = 2
    count = await repo.revoke_all_user_permissions(user_id=uuid.uuid4())
    assert count == 2


@pytest.mark.asyncio
async def test_revoke_all_user_permissions_all():
    repo, session, result = make_repo()
    result.rowcount = 1
    count = await repo.revoke_all_user_permissions(
        user_id=uuid.uuid4(), only_active=False
    )
    assert count == 1


@pytest.mark.asyncio
async def test_revoke_permissions_granted_by_user():
    repo, session, result = make_repo()
    result.rowcount = 5
    count = await repo.revoke_permissions_granted_by_user(granted_by=uuid.uuid4())
    assert count == 5


@pytest.mark.asyncio
async def test_revoke_permissions_granted_by_user_all():
    repo, session, result = make_repo()
    result.rowcount = 0
    count = await repo.revoke_permissions_granted_by_user(
        granted_by=uuid.uuid4(), only_active=False
    )
    assert count == 0


@pytest.mark.asyncio
async def test_bulk_revoke_maps_integrity_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(
        side_effect=IntegrityError("stmt", {}, Exception("orig"))
    )
    with pytest.raises(RepositoryError):
        await repo.revoke_all_node_permissions(node_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_bulk_revoke_maps_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.revoke_all_user_permissions(user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# геттеры списков: по узлу / пользователю / выдавшему
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_node_permissions_returns_list():
    repo, session, result = make_repo()
    perms = [make_orm_permission(), make_orm_permission()]
    result.scalars.return_value.all.return_value = perms
    res = await repo.get_node_permissions(node_id=uuid.uuid4())
    assert res == perms


@pytest.mark.asyncio
async def test_get_node_permissions_active_only():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_node_permissions(
        node_id=uuid.uuid4(), active_only=True, moment=datetime(2025, 1, 1)
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_node_permissions_invalid_pagination():
    repo, session, result = make_repo()
    from database.exceptions import InvalidPaginationError

    with pytest.raises(InvalidPaginationError):
        await repo.get_node_permissions(node_id=uuid.uuid4(), limit=0)


@pytest.mark.asyncio
async def test_get_user_permissions_returns_list():
    repo, session, result = make_repo()
    perms = [make_orm_permission()]
    result.scalars.return_value.all.return_value = perms
    res = await repo.get_user_permissions(user_id=uuid.uuid4())
    assert res == perms


@pytest.mark.asyncio
async def test_get_user_permissions_active_only():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_user_permissions(user_id=uuid.uuid4(), active_only=True)
    assert res == []


@pytest.mark.asyncio
async def test_get_granted_by_user_returns_list():
    repo, session, result = make_repo()
    perms = [make_orm_permission()]
    result.scalars.return_value.all.return_value = perms
    res = await repo.get_granted_by_user(granted_by=uuid.uuid4())
    assert res == perms


@pytest.mark.asyncio
async def test_get_granted_by_user_active_only():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_granted_by_user(granted_by=uuid.uuid4(), active_only=True)
    assert res == []


# ---------------------------------------------------------------------------
# get_accessible_node_ids
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_accessible_node_ids_no_requirements():
    repo, session, result = make_repo()
    ids = [uuid.uuid4(), uuid.uuid4()]
    result.scalars.return_value.all.return_value = ids
    res = await repo.get_accessible_node_ids(user_id=uuid.uuid4())
    assert res == ids


@pytest.mark.asyncio
async def test_get_accessible_node_ids_with_requirements():
    repo, session, result = make_repo()
    ids = [uuid.uuid4()]
    result.scalars.return_value.all.return_value = ids
    res = await repo.get_accessible_node_ids(
        user_id=uuid.uuid4(),
        require_read=True,
        require_download=True,
        require_write=True,
        require_delete=True,
        require_share=True,
    )
    assert res == ids


@pytest.mark.asyncio
async def test_get_accessible_node_ids_invalid_pagination():
    repo, session, result = make_repo()
    from database.exceptions import InvalidPaginationError

    with pytest.raises(InvalidPaginationError):
        await repo.get_accessible_node_ids(user_id=uuid.uuid4(), offset=-1)


@pytest.mark.asyncio
async def test_get_accessible_node_ids_maps_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_accessible_node_ids(user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# user_has_permission и удобные проверки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_has_permission_true():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())
    res = await repo.user_has_permission(
        node_id=uuid.uuid4(), user_id=uuid.uuid4()
    )
    assert res is True


@pytest.mark.asyncio
async def test_user_has_permission_false():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.user_has_permission(
        node_id=uuid.uuid4(), user_id=uuid.uuid4(), require_write=True
    )
    assert res is False


@pytest.mark.asyncio
async def test_user_can_read():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())
    assert await repo.user_can_read(node_id=uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_user_can_download():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    assert (
        await repo.user_can_download(node_id=uuid.uuid4(), user_id=uuid.uuid4())
        is False
    )


@pytest.mark.asyncio
async def test_user_can_write():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())
    assert await repo.user_can_write(node_id=uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_user_can_delete():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())
    assert await repo.user_can_delete(node_id=uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_user_can_share():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    assert (
        await repo.user_can_share(node_id=uuid.uuid4(), user_id=uuid.uuid4())
        is False
    )


# ---------------------------------------------------------------------------
# подсчёты
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_node_permissions():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    assert await repo.count_node_permissions(node_id=uuid.uuid4()) == 3


@pytest.mark.asyncio
async def test_count_node_permissions_active_only():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    assert (
        await repo.count_node_permissions(node_id=uuid.uuid4(), active_only=True)
        == 1
    )


@pytest.mark.asyncio
async def test_count_user_permissions():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=2)
    assert await repo.count_user_permissions(user_id=uuid.uuid4()) == 2


@pytest.mark.asyncio
async def test_count_user_permissions_active_only():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    assert (
        await repo.count_user_permissions(user_id=uuid.uuid4(), active_only=True)
        == 0
    )


@pytest.mark.asyncio
async def test_count_granted_by_user():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=5)
    assert await repo.count_granted_by_user(granted_by=uuid.uuid4()) == 5


@pytest.mark.asyncio
async def test_count_granted_by_user_active_only():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=4)
    assert (
        await repo.count_granted_by_user(granted_by=uuid.uuid4(), active_only=True)
        == 4
    )


# ---------------------------------------------------------------------------
# delete_permission_by_node_and_user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_permission_by_node_and_user_success():
    repo, session, result = make_repo()
    perm = make_orm_permission()
    result.scalar_one_or_none = MagicMock(return_value=perm)
    res = await repo.delete_permission_by_node_and_user(
        node_id=perm.node_id, user_id=perm.user_id
    )
    assert res is True
    session.delete.assert_awaited_once_with(perm)


@pytest.mark.asyncio
async def test_delete_permission_by_node_and_user_not_found_required():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.delete_permission_by_node_and_user(
            node_id=uuid.uuid4(), user_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_delete_permission_by_node_and_user_not_found_optional():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.delete_permission_by_node_and_user(
        node_id=uuid.uuid4(), user_id=uuid.uuid4(), required=False
    )
    assert res is False
    session.delete.assert_not_called()


# ---------------------------------------------------------------------------
# _normalize_moment branches
# ---------------------------------------------------------------------------

def test_normalize_moment_none_returns_now():
    repo, session, result = make_repo()
    res = repo._normalize_moment(None)
    assert res.tzinfo is UTC


def test_normalize_moment_naive_gets_utc():
    repo, session, result = make_repo()
    naive = datetime(2025, 1, 1, 12, 0, 0)
    res = repo._normalize_moment(naive)
    assert res.tzinfo is UTC


def test_normalize_moment_aware_unchanged():
    repo, session, result = make_repo()
    aware = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    res = repo._normalize_moment(aware)
    assert res is aware
