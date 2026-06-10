"""Юнит-тесты контроля переподписки enforce_server_capacity."""
from __future__ import annotations

import uuid
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.exceptions import InsufficientServerCapacityError
from services.quotas import enforce_server_capacity
from storage.exceptions import StorageCapacityError


def make_uow(*, allocated: int = 0):
    """UoW с моком репозитория квот для контроля ёмкости."""
    quotas = MagicMock()
    quotas.acquire_capacity_lock = AsyncMock()
    quotas.total_allocated_storage_bytes = AsyncMock(return_value=allocated)
    uow = MagicMock()
    uow.quotas = quotas
    return uow


def make_provider(*, pool: int | None = None, error: Exception | None = None):
    """Мок провайдера ёмкости с заданным пулом или ошибкой."""
    provider = MagicMock()
    if error is not None:
        provider.get_pool_bytes = AsyncMock(side_effect=error)
    else:
        provider.get_pool_bytes = AsyncMock(return_value=pool)
    return provider


# ---------------------------------------------------------------------------
# Разрешение / запрет
# ---------------------------------------------------------------------------


async def test_allows_when_within_pool():
    """Выделение в пределах пула проходит."""
    uow = make_uow(allocated=100)
    provider = make_provider(pool=1000)

    await enforce_server_capacity(
        uow=uow,
        capacity_provider=provider,
        user_id=uuid.uuid4(),
        new_limit=500,
        previous_limit=None,
    )

    uow.quotas.acquire_capacity_lock.assert_awaited_once()


async def test_raises_when_exceeding_pool():
    """Выделение сверх пула поднимает 507 с деталями."""
    uow = make_uow(allocated=800)
    provider = make_provider(pool=1000)

    with pytest.raises(InsufficientServerCapacityError) as exc_info:
        await enforce_server_capacity(
            uow=uow,
            capacity_provider=provider,
            user_id=uuid.uuid4(),
            new_limit=500,
            previous_limit=None,
        )

    assert exc_info.value.status_code == HTTPStatus.INSUFFICIENT_STORAGE
    assert exc_info.value.details["available"] == 200


async def test_decrease_always_allowed_even_when_overcommitted():
    """Понижение лимита разрешено даже при переподписке (delta <= 0)."""
    uow = make_uow(allocated=10_000)
    provider = make_provider(pool=1000)  # уже переподписка

    await enforce_server_capacity(
        uow=uow,
        capacity_provider=provider,
        user_id=uuid.uuid4(),
        new_limit=200,
        previous_limit=500,
    )

    # Понижение не должно даже брать блокировку или читать пул.
    uow.quotas.acquire_capacity_lock.assert_not_awaited()
    provider.get_pool_bytes.assert_not_awaited()


async def test_equal_limit_is_noop():
    """Сохранение того же лимита (delta == 0) — без проверки."""
    uow = make_uow(allocated=10_000)
    provider = make_provider(pool=1000)

    await enforce_server_capacity(
        uow=uow,
        capacity_provider=provider,
        user_id=uuid.uuid4(),
        new_limit=500,
        previous_limit=500,
    )

    provider.get_pool_bytes.assert_not_awaited()


async def test_raise_existing_quota_uses_previous_limit():
    """Повышение существующей квоты учитывает прежний лимит как занятый чужими."""
    # Чужими занято 600, у пользователя было 300 (не входит в allocated_others),
    # пул 1000. Повышение до 500 -> 600 + 500 = 1100 > 1000 -> запрет.
    uow = make_uow(allocated=600)
    provider = make_provider(pool=1000)

    with pytest.raises(InsufficientServerCapacityError):
        await enforce_server_capacity(
            uow=uow,
            capacity_provider=provider,
            user_id=uuid.uuid4(),
            new_limit=500,
            previous_limit=300,
        )

    # Сумма читается с исключением собственной квоты пользователя.
    _, kwargs = uow.quotas.total_allocated_storage_bytes.call_args
    assert "exclude_user_id" in kwargs


async def test_fails_closed_when_pool_undeterminable():
    """Если пул нельзя определить — выделение блокируется (507)."""
    uow = make_uow(allocated=0)
    provider = make_provider(error=StorageCapacityError("no minio"))

    with pytest.raises(InsufficientServerCapacityError):
        await enforce_server_capacity(
            uow=uow,
            capacity_provider=provider,
            user_id=None,
            new_limit=500,
            previous_limit=None,
        )


def test_error_status_is_507():
    """InsufficientServerCapacityError имеет статус 507."""
    assert (
        InsufficientServerCapacityError().status_code
        == HTTPStatus.INSUFFICIENT_STORAGE
    )
