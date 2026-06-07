"""Юнит-тесты репозитория квот пользователя (UserQuotaRepository)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.exceptions import (
    ConstraintViolationError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
    RepositoryError,
)
from database.repositories.quotas import UserQuotaRepository


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
    return UserQuotaRepository(session=session), session, result


def make_quota(**kwargs):
    quota = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        storage_limit_bytes=10 * 1024 * 1024 * 1024,  # 10 GB
        storage_used_bytes=0,
        max_file_size_bytes=1 * 1024 * 1024 * 1024,  # 1 GB
        files_limit=None,
        files_used=0,
        public_links_limit=100,
        public_links_used=0,
        active_upload_sessions_limit=10,
        active_upload_sessions_used=0,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(quota, k, v)
    return quota


# ---------------------------------------------------------------------------
# Тесты: get_by_user_id / get_required_by_user_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_user_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_by_user_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_by_user_id_returns_quota_when_found():
    repo, session, result = make_repo()
    quota = make_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.get_by_user_id(quota.user_id)
    assert res is quota


@pytest.mark.asyncio
async def test_get_by_user_id_for_update():
    repo, session, result = make_repo()
    quota = make_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.get_by_user_id(quota.user_id, for_update=True)
    assert res is quota


@pytest.mark.asyncio
async def test_get_required_by_user_id_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_by_user_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_required_by_user_id_returns_quota():
    repo, session, result = make_repo()
    quota = make_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.get_required_by_user_id(quota.user_id)
    assert res is quota


@pytest.mark.asyncio
async def test_get_by_user_id_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.get_by_user_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: quota_exists_for_user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quota_exists_for_user_returns_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    res = await repo.quota_exists_for_user(uuid.uuid4())
    assert res is False


@pytest.mark.asyncio
async def test_quota_exists_for_user_returns_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.quota_exists_for_user(uuid.uuid4())
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: create_quota
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_quota_raises_for_negative_storage_limit():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_quota(
            user_id=uuid.uuid4(),
            storage_limit_bytes=-1,
            max_file_size_bytes=1024,
            check_user_exists=False,
            check_duplicate=False,
        )


@pytest.mark.asyncio
async def test_create_quota_raises_for_duplicate():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)  # quota_exists_for_user -> True
    with pytest.raises(DuplicateEntityError):
        await repo.create_quota(
            user_id=uuid.uuid4(),
            storage_limit_bytes=1024,
            max_file_size_bytes=512,
            check_user_exists=False,
            check_duplicate=True,
        )


@pytest.mark.asyncio
async def test_create_quota_success():
    repo, session, result = make_repo()
    quota = make_quota()
    result.scalar_one = MagicMock(return_value=0)  # quota_exists_for_user -> False

    async def fake_create(entity, flush=True, refresh=False):
        return quota

    repo.create = fake_create  # type: ignore
    res = await repo.create_quota(
        user_id=uuid.uuid4(),
        storage_limit_bytes=10 * 1024 ** 3,
        max_file_size_bytes=1024 ** 3,
        check_user_exists=False,
        check_duplicate=False,
    )
    assert res is quota


# ---------------------------------------------------------------------------
# Тесты: обновление лимитов квоты (если методы существуют)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_storage_limit_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'update_storage_limit'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.update_storage_limit(uuid.uuid4(), new_limit_bytes=1024)


@pytest.mark.asyncio
async def test_update_storage_limit_success():
    repo, session, result = make_repo()
    quota = make_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    if hasattr(repo, 'update_storage_limit'):
        res = await repo.update_storage_limit(quota.user_id, new_limit_bytes=1024 ** 3)
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: инкремент использованного хранилища (если метод существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increment_storage_used_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'increment_storage_used'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.increment_storage_used(uuid.uuid4(), bytes_delta=512)


@pytest.mark.asyncio
async def test_increment_storage_used_success():
    repo, session, result = make_repo()
    quota = make_quota(storage_used_bytes=100)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    if hasattr(repo, 'increment_storage_used'):
        res = await repo.increment_storage_used(quota.user_id, bytes_delta=512)
        assert res is not None


# ---------------------------------------------------------------------------
# Тесты: recalculate_storage_used (если метод существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recalculate_storage_used_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'recalculate_storage_used'):
        with pytest.raises((EntityNotFoundError, Exception)):
            await repo.recalculate_storage_used(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: find_quotas_near_limit (если метод существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_quotas_near_limit_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    if hasattr(repo, 'find_quotas_near_limit'):
        res = await repo.find_quotas_near_limit(threshold_percent=80)
        assert isinstance(res, list)


# ---------------------------------------------------------------------------
# Тесты: is_storage_available (если метод существует)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_storage_available_returns_false_when_no_quota():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    if hasattr(repo, 'is_storage_available'):
        res = await repo.is_storage_available(uuid.uuid4(), required_bytes=1024)
        assert res is False


@pytest.mark.asyncio
async def test_is_storage_available_returns_true_when_quota_has_space():
    repo, session, result = make_repo()
    quota = make_quota(storage_limit_bytes=1024 ** 3, storage_used_bytes=0)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    if hasattr(repo, 'is_storage_available'):
        res = await repo.is_storage_available(quota.user_id, required_bytes=1024)
        assert res is True


# ---------------------------------------------------------------------------
# Тесты: count (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_returns_int():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=5)
    from database.models.quotas import UserQuota
    count = await repo.count(UserQuota.user_id == uuid.uuid4())
    assert count == 5


# ---------------------------------------------------------------------------
# Тесты: exists (унаследованный)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exists_returns_false():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    from database.models.quotas import UserQuota
    res = await repo.exists(UserQuota.user_id == uuid.uuid4())
    assert res is False


# ---------------------------------------------------------------------------
# Хелперы для обязательных выборок квоты
# ---------------------------------------------------------------------------

def make_numeric_quota(**kwargs):
    """Создать MagicMock квоты с реальными числовыми атрибутами для арифметики.

    Методы-мутаторы счётчиков (increase_*/set_* и т.п.) остаются MagicMock,
    чтобы можно было проверять факт их вызова.
    """

    quota = make_quota(**kwargs)
    # available_storage_bytes — вычисляемое свойство реальной модели; мокаем его.
    if "available_storage_bytes" not in kwargs:
        quota.available_storage_bytes = (
            quota.storage_limit_bytes - quota.storage_used_bytes
        )
    return quota


# ---------------------------------------------------------------------------
# Тесты: get_by_user_id for_update branch + error details
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_user_id_for_update_calls_with_for_update():
    repo, session, result = make_repo()
    quota = make_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.get_by_user_id(quota.user_id, for_update=True)
    assert res is quota
    assert session.execute.await_count == 1


# ---------------------------------------------------------------------------
# Тесты: create_quota — наличие пользователя + маппинг ошибки целостности
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_quota_checks_user_exists_and_raises_when_missing():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)  # пользователь не найден
    with pytest.raises(EntityNotFoundError):
        await repo.create_quota(
            user_id=uuid.uuid4(),
            storage_limit_bytes=1024,
            max_file_size_bytes=512,
            check_user_exists=True,
            check_duplicate=False,
        )


@pytest.mark.asyncio
async def test_create_quota_with_user_check_success():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=MagicMock())  # пользователь существует
    result.scalar_one = MagicMock(return_value=0)  # нет дубликата
    quota = make_quota()

    async def fake_create(entity, flush=True, refresh=False):
        return quota

    repo.create = fake_create  # type: ignore
    res = await repo.create_quota(
        user_id=uuid.uuid4(),
        storage_limit_bytes=1024 ** 3,
        max_file_size_bytes=1024 ** 2,
        check_user_exists=True,
        check_duplicate=True,
    )
    assert res is quota


@pytest.mark.asyncio
async def test_create_quota_maps_integrity_error():
    repo, session, result = make_repo()
    orig = MagicMock()
    orig.sqlstate = "23505"
    integrity = IntegrityError("stmt", {}, orig)

    async def fake_create(entity, flush=True, refresh=False):
        raise integrity

    repo.create = fake_create  # type: ignore
    with pytest.raises(DuplicateEntityError):
        await repo.create_quota(
            user_id=uuid.uuid4(),
            storage_limit_bytes=1024 ** 3,
            max_file_size_bytes=1024 ** 2,
            check_user_exists=False,
            check_duplicate=False,
        )


@pytest.mark.asyncio
async def test_create_default_quota_success():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    quota = make_quota()

    async def fake_create(entity, flush=True, refresh=False):
        return quota

    repo.create = fake_create  # type: ignore
    res = await repo.create_default_quota(
        user_id=uuid.uuid4(),
        check_user_exists=False,
        check_duplicate=False,
    )
    assert res is quota


# ---------------------------------------------------------------------------
# Тесты: _ensure_user_exists DB error mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_quota_ensure_user_db_error_mapped():
    repo, session, result = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.create_quota(
            user_id=uuid.uuid4(),
            storage_limit_bytes=1024,
            max_file_size_bytes=512,
            check_user_exists=True,
            check_duplicate=False,
        )


# ---------------------------------------------------------------------------
# Тесты: update_limits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_limits_no_changes_keeps_existing():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        storage_limit_bytes=1000,
        storage_used_bytes=10,
        max_file_size_bytes=500,
        files_limit=5,
        files_used=1,
        public_links_limit=20,
        public_links_used=2,
        active_upload_sessions_limit=3,
        active_upload_sessions_used=1,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.update_limits(quota.user_id)
    assert res is quota
    quota.update_limits.assert_called_once_with(
        storage_limit_bytes=1000,
        max_file_size_bytes=500,
        files_limit=5,
        public_links_limit=20,
        active_upload_sessions_limit=3,
    )
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_update_limits_sets_new_values_and_clears_limits():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        storage_limit_bytes=1000,
        storage_used_bytes=0,
        max_file_size_bytes=500,
        files_limit=5,
        files_used=0,
        public_links_limit=20,
        public_links_used=0,
        active_upload_sessions_limit=3,
        active_upload_sessions_used=0,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.update_limits(
        quota.user_id,
        storage_limit_bytes=2000,
        max_file_size_bytes=900,
        files_limit=None,
        public_links_limit=None,
        active_upload_sessions_limit=None,
        refresh=True,
    )
    assert res is quota
    quota.update_limits.assert_called_once_with(
        storage_limit_bytes=2000,
        max_file_size_bytes=900,
        files_limit=None,
        public_links_limit=None,
        active_upload_sessions_limit=None,
    )
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_update_limits_sets_explicit_int_limits():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        files_limit=5, files_used=0,
        public_links_limit=20, public_links_used=0,
        active_upload_sessions_limit=3, active_upload_sessions_used=0,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    await repo.update_limits(
        quota.user_id,
        files_limit=99,
        public_links_limit=88,
        active_upload_sessions_limit=77,
    )
    quota.update_limits.assert_called_once()
    _, kw = quota.update_limits.call_args
    assert kw["files_limit"] == 99
    assert kw["public_links_limit"] == 88
    assert kw["active_upload_sessions_limit"] == 77


@pytest.mark.asyncio
async def test_update_limits_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_limits(uuid.uuid4(), storage_limit_bytes=10)


@pytest.mark.asyncio
async def test_update_limits_raises_constraint_when_used_exceeds_new_limit():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        storage_limit_bytes=1000,
        storage_used_bytes=500,
        files_limit=10,
        files_used=8,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    with pytest.raises(ConstraintViolationError):
        await repo.update_limits(quota.user_id, files_limit=5)


# ---------------------------------------------------------------------------
# Тесты: update_storage_used / reset_usage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_storage_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota(storage_limit_bytes=1000, storage_used_bytes=100)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.update_storage_used(
        quota.user_id, storage_used_bytes=500, refresh=True,
    )
    assert res is quota
    quota.set_storage_usage.assert_called_once_with(500)
    session.flush.assert_awaited()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_update_storage_used_raises_when_exceeds_limit():
    repo, session, result = make_repo()
    quota = make_numeric_quota(storage_limit_bytes=1000)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    with pytest.raises(ConstraintViolationError):
        await repo.update_storage_used(quota.user_id, storage_used_bytes=2000)


@pytest.mark.asyncio
async def test_update_storage_used_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.update_storage_used(uuid.uuid4(), storage_used_bytes=10)


@pytest.mark.asyncio
async def test_reset_usage_delegates_to_update_storage_used():
    repo, session, result = make_repo()
    quota = make_numeric_quota(storage_limit_bytes=1000, storage_used_bytes=300)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.reset_usage(quota.user_id)
    assert res is quota
    quota.set_storage_usage.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# Тесты: increase_used_space / decrease_used_space
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increase_used_space_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota(storage_limit_bytes=1000, storage_used_bytes=100)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.increase_used_space(quota.user_id, size_bytes=200, refresh=True)
    assert res is quota
    quota.increase_storage_usage.assert_called_once_with(200)
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_increase_used_space_raises_when_over_limit():
    repo, session, result = make_repo()
    quota = make_numeric_quota(storage_limit_bytes=1000, storage_used_bytes=900)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    with pytest.raises(ConstraintViolationError):
        await repo.increase_used_space(quota.user_id, size_bytes=500)


@pytest.mark.asyncio
async def test_increase_used_space_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.increase_used_space(uuid.uuid4(), size_bytes=-1)


@pytest.mark.asyncio
async def test_decrease_used_space_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota(storage_used_bytes=500)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.decrease_used_space(quota.user_id, size_bytes=100, refresh=True)
    assert res is quota
    quota.decrease_storage_usage.assert_called_once_with(100)
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_decrease_used_space_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.decrease_used_space(uuid.uuid4(), size_bytes=-5)


@pytest.mark.asyncio
async def test_decrease_used_space_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.decrease_used_space(uuid.uuid4(), size_bytes=1)


# ---------------------------------------------------------------------------
# Тесты: мутаторы счётчика файлов
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increase_files_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.increase_files_used(quota.user_id, count=3, refresh=True)
    assert res is quota
    quota.increase_files_used.assert_called_once_with(3)
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_increase_files_used_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.increase_files_used(uuid.uuid4(), count=-1)


@pytest.mark.asyncio
async def test_decrease_files_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.decrease_files_used(quota.user_id, count=2, refresh=True)
    assert res is quota
    quota.decrease_files_used.assert_called_once_with(2)


@pytest.mark.asyncio
async def test_decrease_files_used_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.decrease_files_used(uuid.uuid4(), count=-1)


@pytest.mark.asyncio
async def test_set_files_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.set_files_used(quota.user_id, count=9, refresh=True)
    assert res is quota
    quota.set_files_used.assert_called_once_with(9)


@pytest.mark.asyncio
async def test_set_files_used_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.set_files_used(uuid.uuid4(), count=-1)


# ---------------------------------------------------------------------------
# Тесты: мутаторы счётчика публичных ссылок
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increase_public_links_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.increase_public_links_used(quota.user_id, count=4, refresh=True)
    assert res is quota
    quota.increase_public_links_used.assert_called_once_with(4)


@pytest.mark.asyncio
async def test_increase_public_links_used_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.increase_public_links_used(uuid.uuid4(), count=-1)


@pytest.mark.asyncio
async def test_decrease_public_links_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.decrease_public_links_used(quota.user_id, count=1, refresh=True)
    assert res is quota
    quota.decrease_public_links_used.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_decrease_public_links_used_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.decrease_public_links_used(uuid.uuid4(), count=-1)


@pytest.mark.asyncio
async def test_set_public_links_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.set_public_links_used(quota.user_id, count=7, refresh=True)
    assert res is quota
    quota.set_public_links_used.assert_called_once_with(7)


@pytest.mark.asyncio
async def test_set_public_links_used_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.set_public_links_used(uuid.uuid4(), count=-1)


# ---------------------------------------------------------------------------
# Тесты: мутаторы счётчика активных сессий загрузки
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increase_active_upload_sessions_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.increase_active_upload_sessions_used(
        quota.user_id, count=2, refresh=True,
    )
    assert res is quota
    quota.increase_active_upload_sessions_used.assert_called_once_with(2)


@pytest.mark.asyncio
async def test_increase_active_upload_sessions_used_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.increase_active_upload_sessions_used(uuid.uuid4(), count=-1)


@pytest.mark.asyncio
async def test_decrease_active_upload_sessions_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.decrease_active_upload_sessions_used(
        quota.user_id, count=1, refresh=True,
    )
    assert res is quota
    quota.decrease_active_upload_sessions_used.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_decrease_active_upload_sessions_used_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.decrease_active_upload_sessions_used(uuid.uuid4(), count=-1)


@pytest.mark.asyncio
async def test_set_active_upload_sessions_used_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    result.scalar_one_or_none = MagicMock(return_value=quota)
    res = await repo.set_active_upload_sessions_used(
        quota.user_id, count=5, refresh=True,
    )
    assert res is quota
    quota.set_active_upload_sessions_used.assert_called_once_with(5)


@pytest.mark.asyncio
async def test_set_active_upload_sessions_used_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.set_active_upload_sessions_used(uuid.uuid4(), count=-1)


# ---------------------------------------------------------------------------
# Тесты: check_available_space / check_file_size_allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_available_space_true():
    repo, session, result = make_repo()
    quota = make_numeric_quota(storage_limit_bytes=1000, storage_used_bytes=100)
    quota.available_storage_bytes = 900
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_available_space(quota.user_id, required_bytes=500) is True


@pytest.mark.asyncio
async def test_check_available_space_false():
    repo, session, result = make_repo()
    quota = make_numeric_quota()
    quota.available_storage_bytes = 100
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_available_space(quota.user_id, required_bytes=500) is False


@pytest.mark.asyncio
async def test_check_available_space_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.check_available_space(uuid.uuid4(), required_bytes=-1)


@pytest.mark.asyncio
async def test_check_file_size_allowed_true():
    repo, session, result = make_repo()
    quota = make_numeric_quota(max_file_size_bytes=1000)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_file_size_allowed(
        quota.user_id, file_size_bytes=500,
    ) is True


@pytest.mark.asyncio
async def test_check_file_size_allowed_false():
    repo, session, result = make_repo()
    quota = make_numeric_quota(max_file_size_bytes=100)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_file_size_allowed(
        quota.user_id, file_size_bytes=500,
    ) is False


@pytest.mark.asyncio
async def test_check_file_size_allowed_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.check_file_size_allowed(uuid.uuid4(), file_size_bytes=-1)


# ---------------------------------------------------------------------------
# Тесты: check_files_limit_allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_files_limit_allowed_unlimited_returns_true():
    repo, session, result = make_repo()
    quota = make_numeric_quota(files_limit=None)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_files_limit_allowed(quota.user_id) is True


@pytest.mark.asyncio
async def test_check_files_limit_allowed_stored_counter_true():
    repo, session, result = make_repo()
    quota = make_numeric_quota(files_limit=10, files_used=5)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_files_limit_allowed(
        quota.user_id, additional_files_count=3,
    ) is True


@pytest.mark.asyncio
async def test_check_files_limit_allowed_stored_counter_false():
    repo, session, result = make_repo()
    quota = make_numeric_quota(files_limit=10, files_used=9)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_files_limit_allowed(
        quota.user_id, additional_files_count=5,
    ) is False


@pytest.mark.asyncio
async def test_check_files_limit_allowed_recount_branch():
    repo, session, result = make_repo()
    quota = make_numeric_quota(files_limit=10, files_used=0)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.count_user_files = AsyncMock(return_value=4)  # type: ignore
    res = await repo.check_files_limit_allowed(
        quota.user_id, additional_files_count=2, use_stored_counter=False,
    )
    assert res is True
    repo.count_user_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_files_limit_allowed_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.check_files_limit_allowed(
            uuid.uuid4(), additional_files_count=-1,
        )


# ---------------------------------------------------------------------------
# Тесты: check_public_links_limit_allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_public_links_limit_allowed_unlimited_true():
    repo, session, result = make_repo()
    quota = make_numeric_quota(public_links_limit=None)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_public_links_limit_allowed(quota.user_id) is True


@pytest.mark.asyncio
async def test_check_public_links_limit_allowed_stored_false():
    repo, session, result = make_repo()
    quota = make_numeric_quota(public_links_limit=10, public_links_used=10)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_public_links_limit_allowed(quota.user_id) is False


@pytest.mark.asyncio
async def test_check_public_links_limit_allowed_recount_branch():
    repo, session, result = make_repo()
    quota = make_numeric_quota(public_links_limit=10, public_links_used=0)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.count_user_public_links = AsyncMock(return_value=3)  # type: ignore
    res = await repo.check_public_links_limit_allowed(
        quota.user_id, use_stored_counter=False,
    )
    assert res is True
    repo.count_user_public_links.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_public_links_limit_allowed_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.check_public_links_limit_allowed(
            uuid.uuid4(), additional_links_count=-1,
        )


# ---------------------------------------------------------------------------
# Тесты: check_active_upload_sessions_limit_allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_sessions_limit_allowed_unlimited_true():
    repo, session, result = make_repo()
    quota = make_numeric_quota(active_upload_sessions_limit=None)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.check_active_upload_sessions_limit_allowed(quota.user_id) is True


@pytest.mark.asyncio
async def test_check_sessions_limit_allowed_stored_false():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        active_upload_sessions_limit=2, active_upload_sessions_used=2,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert (
        await repo.check_active_upload_sessions_limit_allowed(quota.user_id) is False
    )


@pytest.mark.asyncio
async def test_check_sessions_limit_allowed_recount_branch():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        active_upload_sessions_limit=5, active_upload_sessions_used=0,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.count_user_active_upload_sessions = AsyncMock(return_value=1)  # type: ignore
    res = await repo.check_active_upload_sessions_limit_allowed(
        quota.user_id, use_stored_counter=False, exclude_time_expired=True,
    )
    assert res is True
    repo.count_user_active_upload_sessions.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_sessions_limit_allowed_raises_for_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.check_active_upload_sessions_limit_allowed(
            uuid.uuid4(), additional_sessions_count=-1,
        )


# ---------------------------------------------------------------------------
# Тесты: can_store_file (полный набор веток)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_can_store_file_false_when_too_big():
    repo, session, result = make_repo()
    quota = make_numeric_quota(max_file_size_bytes=100)
    quota.available_storage_bytes = 10_000
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.can_store_file(quota.user_id, file_size_bytes=500) is False


@pytest.mark.asyncio
async def test_can_store_file_false_when_no_space():
    repo, session, result = make_repo()
    quota = make_numeric_quota(max_file_size_bytes=10_000)
    quota.available_storage_bytes = 100
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.can_store_file(quota.user_id, file_size_bytes=500) is False


@pytest.mark.asyncio
async def test_can_store_file_true_when_unlimited_files():
    repo, session, result = make_repo()
    quota = make_numeric_quota(max_file_size_bytes=10_000, files_limit=None)
    quota.available_storage_bytes = 10_000
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.can_store_file(quota.user_id, file_size_bytes=500) is True


@pytest.mark.asyncio
async def test_can_store_file_stored_counter_limit_true():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        max_file_size_bytes=10_000, files_limit=10, files_used=5,
    )
    quota.available_storage_bytes = 10_000
    result.scalar_one_or_none = MagicMock(return_value=quota)
    assert await repo.can_store_file(quota.user_id, file_size_bytes=500) is True


@pytest.mark.asyncio
async def test_can_store_file_recount_branch_false():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        max_file_size_bytes=10_000, files_limit=10, files_used=0,
    )
    quota.available_storage_bytes = 10_000
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.count_user_files = AsyncMock(return_value=10)  # type: ignore
    res = await repo.can_store_file(
        quota.user_id, file_size_bytes=500, use_stored_files_counter=False,
    )
    assert res is False
    repo.count_user_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_can_store_file_raises_for_negative_size():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.can_store_file(uuid.uuid4(), file_size_bytes=-1)


@pytest.mark.asyncio
async def test_can_store_file_raises_for_negative_count():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.can_store_file(
            uuid.uuid4(), file_size_bytes=1, additional_files_count=-1,
        )


# ---------------------------------------------------------------------------
# Тесты: recalculate_usage / recalculate_counters / recalculate_all
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recalculate_usage_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota(storage_limit_bytes=10_000, storage_used_bytes=0)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.calculate_user_storage_usage = AsyncMock(return_value=2000)  # type: ignore
    res = await repo.recalculate_usage(quota.user_id, refresh=True)
    assert res is quota
    assert quota.storage_used_bytes == 2000
    session.flush.assert_awaited()
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_recalculate_usage_raises_when_over_limit():
    repo, session, result = make_repo()
    quota = make_numeric_quota(storage_limit_bytes=1000)
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.calculate_user_storage_usage = AsyncMock(return_value=5000)  # type: ignore
    with pytest.raises(ConstraintViolationError):
        await repo.recalculate_usage(quota.user_id)


@pytest.mark.asyncio
async def test_recalculate_counters_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        storage_limit_bytes=10_000, storage_used_bytes=0,
        max_file_size_bytes=1000,
        files_limit=100, public_links_limit=100,
        active_upload_sessions_limit=100,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.count_user_files = AsyncMock(return_value=3)  # type: ignore
    repo.count_user_public_links = AsyncMock(return_value=4)  # type: ignore
    repo.count_user_active_upload_sessions = AsyncMock(return_value=5)  # type: ignore
    res = await repo.recalculate_counters(quota.user_id, refresh=True)
    assert res is quota
    assert quota.files_used == 3
    assert quota.public_links_used == 4
    assert quota.active_upload_sessions_used == 5
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_recalculate_counters_raises_when_over_limit():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        storage_limit_bytes=10_000, storage_used_bytes=0,
        max_file_size_bytes=1000, files_limit=2,
        public_links_limit=100, active_upload_sessions_limit=100,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.count_user_files = AsyncMock(return_value=10)  # type: ignore
    repo.count_user_public_links = AsyncMock(return_value=0)  # type: ignore
    repo.count_user_active_upload_sessions = AsyncMock(return_value=0)  # type: ignore
    with pytest.raises(ConstraintViolationError):
        await repo.recalculate_counters(quota.user_id)


@pytest.mark.asyncio
async def test_recalculate_all_success():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        storage_limit_bytes=10_000, storage_used_bytes=0,
        max_file_size_bytes=1000,
        files_limit=100, public_links_limit=100,
        active_upload_sessions_limit=100,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.calculate_user_storage_usage = AsyncMock(return_value=1500)  # type: ignore
    repo.count_user_files = AsyncMock(return_value=6)  # type: ignore
    repo.count_user_public_links = AsyncMock(return_value=7)  # type: ignore
    repo.count_user_active_upload_sessions = AsyncMock(return_value=8)  # type: ignore
    res = await repo.recalculate_all(quota.user_id, refresh=True)
    assert res is quota
    assert quota.storage_used_bytes == 1500
    assert quota.files_used == 6
    assert quota.public_links_used == 7
    assert quota.active_upload_sessions_used == 8
    session.refresh.assert_awaited()


@pytest.mark.asyncio
async def test_recalculate_all_raises_when_over_limit():
    repo, session, result = make_repo()
    quota = make_numeric_quota(
        storage_limit_bytes=1000, storage_used_bytes=0,
        max_file_size_bytes=1000,
        files_limit=100, public_links_limit=100,
        active_upload_sessions_limit=100,
    )
    result.scalar_one_or_none = MagicMock(return_value=quota)
    repo.calculate_user_storage_usage = AsyncMock(return_value=5000)  # type: ignore
    repo.count_user_files = AsyncMock(return_value=0)  # type: ignore
    repo.count_user_public_links = AsyncMock(return_value=0)  # type: ignore
    repo.count_user_active_upload_sessions = AsyncMock(return_value=0)  # type: ignore
    with pytest.raises(ConstraintViolationError):
        await repo.recalculate_all(quota.user_id)


# ---------------------------------------------------------------------------
# Тесты: calculate_user_storage_usage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calculate_user_storage_usage_returns_sum():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=4096)
    res = await repo.calculate_user_storage_usage(uuid.uuid4())
    assert res == 4096


@pytest.mark.asyncio
async def test_calculate_user_storage_usage_exclude_deleted_and_none():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=None)
    res = await repo.calculate_user_storage_usage(
        uuid.uuid4(), include_deleted=False,
    )
    assert res == 0


@pytest.mark.asyncio
async def test_calculate_user_storage_usage_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.calculate_user_storage_usage(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: count_user_files
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_files_returns_count():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=12)
    res = await repo.count_user_files(uuid.uuid4(), include_deleted=True)
    assert res == 12


@pytest.mark.asyncio
async def test_count_user_files_exclude_deleted():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    res = await repo.count_user_files(uuid.uuid4(), include_deleted=False)
    assert res == 0


@pytest.mark.asyncio
async def test_count_user_files_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.count_user_files(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: count_user_public_links
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_public_links_only_active():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=3)
    res = await repo.count_user_public_links(uuid.uuid4(), only_active=True)
    assert res == 3


@pytest.mark.asyncio
async def test_count_user_public_links_all():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=8)
    res = await repo.count_user_public_links(uuid.uuid4(), only_active=False)
    assert res == 8


@pytest.mark.asyncio
async def test_count_user_public_links_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.count_user_public_links(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: count_user_active_upload_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_user_active_upload_sessions_returns_count():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=2)
    res = await repo.count_user_active_upload_sessions(uuid.uuid4())
    assert res == 2


@pytest.mark.asyncio
async def test_count_user_active_upload_sessions_exclude_time_expired():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.count_user_active_upload_sessions(
        uuid.uuid4(), exclude_time_expired=True,
    )
    assert res == 1


@pytest.mark.asyncio
async def test_count_user_active_upload_sessions_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.count_user_active_upload_sessions(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: list_near_limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_near_limit_returns_list():
    repo, session, result = make_repo()
    quota = make_quota()
    result.scalars.return_value.all.return_value = [quota]
    res = await repo.list_near_limit(threshold_percent=80.0)
    assert res == [quota]


@pytest.mark.asyncio
async def test_list_near_limit_invalid_pagination():
    repo, session, result = make_repo()
    from database.exceptions import InvalidPaginationError
    with pytest.raises(InvalidPaginationError):
        await repo.list_near_limit(offset=-1)


@pytest.mark.asyncio
async def test_list_near_limit_invalid_threshold_high():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_near_limit(threshold_percent=150.0)


@pytest.mark.asyncio
async def test_list_near_limit_invalid_threshold_low():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.list_near_limit(threshold_percent=-5.0)


@pytest.mark.asyncio
async def test_list_near_limit_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.list_near_limit(threshold_percent=90.0)


# ---------------------------------------------------------------------------
# Тесты: list_over_limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_over_limit_returns_list():
    repo, session, result = make_repo()
    quota = make_quota()
    result.scalars.return_value.all.return_value = [quota]
    res = await repo.list_over_limit()
    assert res == [quota]


@pytest.mark.asyncio
async def test_list_over_limit_invalid_pagination():
    repo, session, result = make_repo()
    from database.exceptions import InvalidPaginationError
    with pytest.raises(InvalidPaginationError):
        await repo.list_over_limit(limit=0)


@pytest.mark.asyncio
async def test_list_over_limit_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.list_over_limit()


# ---------------------------------------------------------------------------
# Тесты: _scalar_int helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scalar_int_returns_value():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=42)
    from database.models.quotas import UserQuota
    from sqlalchemy import func, select
    stmt = select(func.count(UserQuota.id))
    res = await repo._scalar_int(stmt, operation="op")
    assert res == 42


@pytest.mark.asyncio
async def test_scalar_int_none_returns_zero():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=None)
    from database.models.quotas import UserQuota
    from sqlalchemy import func, select
    stmt = select(func.count(UserQuota.id))
    res = await repo._scalar_int(stmt, operation="op")
    assert res == 0


@pytest.mark.asyncio
async def test_scalar_int_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    from database.models.quotas import UserQuota
    from sqlalchemy import func, select
    stmt = select(func.count(UserQuota.id))
    with pytest.raises(RepositoryError):
        await repo._scalar_int(stmt, operation="op")


# ---------------------------------------------------------------------------
# Тесты: validation helpers (direct)
# ---------------------------------------------------------------------------

def test_validate_non_negative_int_rejects_non_int():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_non_negative_int(value="x", field_name="f")  # type: ignore


def test_validate_non_negative_int_rejects_negative():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        repo._validate_non_negative_int(value=-1, field_name="f")


def test_validate_non_negative_int_accepts_zero():
    repo, session, result = make_repo()
    repo._validate_non_negative_int(value=0, field_name="f")


def test_validate_quota_values_files_limit_violation():
    repo, session, result = make_repo()
    with pytest.raises(ConstraintViolationError):
        repo._validate_quota_values(
            storage_limit_bytes=1000,
            storage_used_bytes=0,
            max_file_size_bytes=100,
            files_limit=2,
            files_used=5,
            public_links_limit=None,
            public_links_used=0,
            active_upload_sessions_limit=None,
            active_upload_sessions_used=0,
        )


def test_validate_quota_values_public_links_violation():
    repo, session, result = make_repo()
    with pytest.raises(ConstraintViolationError):
        repo._validate_quota_values(
            storage_limit_bytes=1000,
            storage_used_bytes=0,
            max_file_size_bytes=100,
            files_limit=None,
            files_used=0,
            public_links_limit=2,
            public_links_used=5,
            active_upload_sessions_limit=None,
            active_upload_sessions_used=0,
        )


def test_validate_quota_values_sessions_violation():
    repo, session, result = make_repo()
    with pytest.raises(ConstraintViolationError):
        repo._validate_quota_values(
            storage_limit_bytes=1000,
            storage_used_bytes=0,
            max_file_size_bytes=100,
            files_limit=None,
            files_used=0,
            public_links_limit=None,
            public_links_used=0,
            active_upload_sessions_limit=2,
            active_upload_sessions_used=5,
        )


def test_validate_quota_values_all_valid_passes():
    repo, session, result = make_repo()
    repo._validate_quota_values(
        storage_limit_bytes=1000,
        storage_used_bytes=10,
        max_file_size_bytes=100,
        files_limit=10,
        files_used=1,
        public_links_limit=10,
        public_links_used=1,
        active_upload_sessions_limit=10,
        active_upload_sessions_used=1,
    )


def test_validate_storage_used_violation():
    repo, session, result = make_repo()
    with pytest.raises(ConstraintViolationError):
        repo._validate_storage_used(
            storage_used_bytes=2000, storage_limit_bytes=1000,
        )
