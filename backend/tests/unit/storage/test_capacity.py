"""Юнит-тесты для провайдера ёмкости хранилища CapacityProvider."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from core.config import StorageSettings
from storage.capacity import CapacityProvider, get_capacity_provider
from storage.exceptions import StorageCapacityError


def _info_json(drives: list[dict], *, key: str = "drives") -> str:
    """Собирает JSON ответа MinIO ``info()`` с указанными дисками."""
    return json.dumps({"servers": [{key: drives}]})


def _provider(
    *,
    configured: int | None = None,
    info_value: str | None = None,
    info_error: Exception | None = None,
    **kwargs,
) -> CapacityProvider:
    """Создаёт провайдер с подставным MinIO admin-клиентом."""
    admin = MagicMock()
    if info_error is not None:
        admin.info = MagicMock(side_effect=info_error)
    else:
        admin.info = MagicMock(return_value=info_value)
    return CapacityProvider(
        settings=StorageSettings(),
        configured_capacity_bytes=configured,
        admin=admin,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# _parse_physical
# ---------------------------------------------------------------------------


def test_parse_physical_sums_drives():
    """Суммирует total/available по всем дискам всех серверов."""
    payload = _info_json(
        [
            {"totalspace": 1000, "availablespace": 400},
            {"totalspace": 2000, "availablespace": 500},
        ]
    )
    assert CapacityProvider._parse_physical(payload) == (3000, 900)


def test_parse_physical_disks_alias_and_string_sizes():
    """Понимает ключ ``disks`` и строковые размеры."""
    payload = _info_json([{"total": "500", "available": "100"}], key="disks")
    assert CapacityProvider._parse_physical(payload) == (500, 100)


def test_parse_physical_garbage_returns_none():
    """Невалидный JSON и пустой ответ дают (None, None)."""
    assert CapacityProvider._parse_physical("not json") == (None, None)
    assert CapacityProvider._parse_physical("{}") == (None, None)
    assert CapacityProvider._parse_physical('{"servers": []}') == (None, None)


def test_parse_physical_skips_unparsable_fields():
    """Пропускает диски без размеров, но суммирует валидные."""
    payload = _info_json(
        [
            {"totalspace": 1000, "availablespace": 400},
            {"totalspace": None, "availablespace": "oops"},
        ]
    )
    assert CapacityProvider._parse_physical(payload) == (1000, 400)


def test_parse_physical_availspace_field():
    """Понимает реальное имя поля MinIO ``availspace``."""
    payload = _info_json(
        [{"totalspace": 220026445824, "usedspace": 30497861632, "availspace": 189528584192}]
    )
    assert CapacityProvider._parse_physical(payload) == (220026445824, 189528584192)


def test_parse_physical_derives_available_from_used():
    """Без поля свободного места выводит его из total - used."""
    payload = _info_json([{"totalspace": 1000, "usedspace": 300}])
    assert CapacityProvider._parse_physical(payload) == (1000, 700)


def test_parse_physical_used_exceeding_total_clamps_to_zero():
    """Если used > total, свободное не уходит в минус."""
    payload = _info_json([{"totalspace": 1000, "usedspace": 1500}])
    assert CapacityProvider._parse_physical(payload) == (1000, 0)


# ---------------------------------------------------------------------------
# Вычисление пула
# ---------------------------------------------------------------------------


async def test_auto_pool_is_85_percent_of_physical():
    """Без конфига пул = floor(85% от физической ёмкости)."""
    provider = _provider(
        info_value=_info_json([{"totalspace": 1000, "availablespace": 600}]),
    )
    status = await provider.resolve()
    assert status.pool_bytes == 850
    assert status.source == "auto"
    assert status.physical_total_bytes == 1000
    assert status.physical_available_bytes == 600
    assert status.minio_reachable is True


async def test_config_pool_within_physical_is_used():
    """Заданная ёмкость в пределах диска используется как пул."""
    provider = _provider(
        configured=700,
        info_value=_info_json([{"totalspace": 1000, "availablespace": 600}]),
    )
    status = await provider.resolve()
    assert status.pool_bytes == 700
    assert status.source == "config"


async def test_config_exceeding_physical_raises():
    """Заданная ёмкость больше физической — ошибка."""
    provider = _provider(
        configured=2000,
        info_value=_info_json([{"totalspace": 1000, "availablespace": 600}]),
    )
    with pytest.raises(StorageCapacityError):
        await provider.resolve()


async def test_unreachable_with_config_uses_config():
    """MinIO недоступен, но ёмкость задана — используется конфиг."""
    provider = _provider(configured=500, info_error=RuntimeError("down"))
    status = await provider.resolve()
    assert status.pool_bytes == 500
    assert status.source == "config"
    assert status.physical_total_bytes is None
    assert status.minio_reachable is False


async def test_unreachable_without_config_raises():
    """MinIO недоступен и ёмкость не задана — ошибка (fail-closed)."""
    provider = _provider(info_error=RuntimeError("down"))
    with pytest.raises(StorageCapacityError):
        await provider.get_pool_bytes()


# ---------------------------------------------------------------------------
# Кэширование
# ---------------------------------------------------------------------------


async def test_cache_reuses_within_ttl():
    """В пределах TTL info() запрашивается один раз; refresh обновляет."""
    provider = _provider(
        info_value=_info_json([{"totalspace": 1000, "availablespace": 600}]),
        cache_ttl_seconds=1000.0,
    )
    await provider.resolve()
    await provider.resolve()
    assert provider._admin.info.call_count == 1

    await provider.refresh()
    assert provider._admin.info.call_count == 2


# ---------------------------------------------------------------------------
# Фабрика
# ---------------------------------------------------------------------------


def test_factory_reads_configured_capacity():
    """Фабрика переносит STORAGE_CAPACITY_BYTES из настроек."""
    settings = StorageSettings(STORAGE_CAPACITY_BYTES=12345)
    provider = get_capacity_provider(settings)
    assert provider._configured == 12345
