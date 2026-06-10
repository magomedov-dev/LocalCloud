from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from minio import MinioAdmin
from minio.credentials import StaticProvider

from core.config import StorageSettings
from core.constants import StorageConstants
from storage.exceptions import StorageCapacityError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CapacityStatus:
    """Снимок состояния ёмкости хранилища сервера.

    Attributes:
        pool_bytes: Общий пул хранилища, доступный для выдачи в квоты, в байтах.
        physical_total_bytes: Физическая ёмкость диска по данным MinIO (или
            ``None``, если MinIO admin API недоступен).
        physical_available_bytes: Свободное место на диске по данным MinIO (или
            ``None``).
        source: Источник значения пула: ``"config"`` (задан явно) или
            ``"auto"`` (вычислен как доля физической ёмкости).
        minio_reachable: Доступен ли MinIO admin API на момент снимка.
    """

    pool_bytes: int
    physical_total_bytes: int | None
    physical_available_bytes: int | None
    source: str
    minio_reachable: bool


class CapacityProvider:
    """Определяет общий пул хранилища сервера.

    Пул — это максимальный суммарный объём, который можно распределить по
    квотам пользователей. Источник пула:

    * если в конфиге задан ``storage_capacity_bytes`` — он используется как пул
      (с проверкой, что он не превышает физическую ёмкость диска);
    * иначе пул вычисляется как доля (по умолчанию 85%) от физической ёмкости,
      которую MinIO видит на диске.

    Значение пула кэшируется на ``cache_ttl_seconds`` и обновляется при
    обращении после истечения TTL или вручную через :meth:`refresh`. Запросы к
    MinIO admin API выполняются в отдельном потоке, чтобы не блокировать
    event loop.
    """

    def __init__(
        self,
        *,
        settings: StorageSettings,
        configured_capacity_bytes: int | None = None,
        auto_fraction: float = StorageConstants.STORAGE_AUTO_CAPACITY_FRACTION,
        cache_ttl_seconds: float = StorageConstants.CAPACITY_CACHE_TTL_SECONDS,
        admin: MinioAdmin | None = None,
    ) -> None:
        """Инициализирует провайдер ёмкости хранилища.

        Args:
            settings: Настройки подключения к MinIO.
            configured_capacity_bytes: Явно заданная ёмкость пула в байтах.
                Если ``None``, пул определяется автоматически.
            auto_fraction: Доля физической ёмкости, используемая как пул при
                автоопределении (например, ``0.85`` — 85%).
            cache_ttl_seconds: Время жизни кэша вычисленного снимка ёмкости.
            admin: Готовый клиент MinIO admin (для тестов). Если ``None``,
                создаётся из ``settings``.
        """

        self._settings = settings
        self._configured = configured_capacity_bytes
        self._auto_fraction = auto_fraction
        self._cache_ttl_seconds = cache_ttl_seconds
        self._admin = admin
        self._lock = asyncio.Lock()
        self._cached: CapacityStatus | None = None
        self._cached_at: float | None = None

    def _build_admin(self) -> MinioAdmin:
        """Создаёт клиент MinIO admin из настроек.

        Returns:
            Клиент MinIO admin.
        """

        if self._admin is not None:
            return self._admin
        self._admin = MinioAdmin(
            endpoint=self._settings.minio_endpoint,
            credentials=StaticProvider(
                self._settings.minio_access_key,
                self._settings.minio_secret_key,
            ),
            secure=self._settings.minio_secure,
            region=self._settings.minio_region or "",
        )
        return self._admin

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        """Приводит значение размера к неотрицательному ``int`` или ``None``."""

        if value is None or isinstance(value, bool):
            return None
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        return result if result >= 0 else None

    @classmethod
    def _parse_physical(cls, info_json: str) -> tuple[int | None, int | None]:
        """Извлекает суммарные total/available байты из ответа ``info()``.

        Разбор устойчив к различиям версий MinIO: дисковый список может
        называться ``drives`` или ``disks``, а поля размеров — ``totalspace``/
        ``availablespace`` или ``total``/``available``. Отсутствующие и
        непарсибельные значения игнорируются.

        Args:
            info_json: JSON-строка, возвращённая ``MinioAdmin.info()``.

        Returns:
            Кортеж ``(total_bytes, available_bytes)``. Любой элемент равен
            ``None``, если соответствующую величину определить не удалось.
        """

        try:
            payload = json.loads(info_json)
        except (TypeError, ValueError):
            return None, None
        if not isinstance(payload, dict):
            return None, None

        servers = payload.get("servers")
        if not isinstance(servers, list):
            return None, None

        total = 0
        available = 0
        saw_total = False
        saw_available = False

        for server in servers:
            if not isinstance(server, dict):
                continue
            drives = server.get("drives")
            if not isinstance(drives, list):
                drives = server.get("disks")
            if not isinstance(drives, list):
                continue
            for drive in drives:
                if not isinstance(drive, dict):
                    continue
                total_value = cls._coerce_int(
                    drive.get("totalspace", drive.get("total")),
                )
                available_value = cls._coerce_int(
                    drive.get("availablespace", drive.get("available")),
                )
                if total_value is not None:
                    total += total_value
                    saw_total = True
                if available_value is not None:
                    available += available_value
                    saw_available = True

        return (
            total if saw_total else None,
            available if saw_available else None,
        )

    async def _query_physical(self) -> tuple[int | None, int | None]:
        """Запрашивает у MinIO физические total/available байты.

        Returns:
            Кортеж ``(total_bytes, available_bytes)``; ``(None, None)``, если
            MinIO admin API недоступен или ответ не удалось разобрать.
        """

        try:
            admin = self._build_admin()
            info_json = await asyncio.to_thread(admin.info)
        except Exception as exc:  # noqa: BLE001 - degraded mode, не валим запрос
            logger.warning(
                "Не удалось получить ёмкость диска из MinIO admin API: %s",
                exc,
            )
            return None, None
        return self._parse_physical(info_json)

    def _compute_pool(
        self,
        *,
        physical_total: int | None,
    ) -> tuple[int, str]:
        """Вычисляет пул хранилища и его источник.

        Args:
            physical_total: Физическая ёмкость диска в байтах или ``None``.

        Returns:
            Кортеж ``(pool_bytes, source)``.

        Raises:
            StorageCapacityError: Если заданная в конфиге ёмкость превышает
                физическую, либо если ёмкость нельзя определить (нет ни конфига,
                ни данных MinIO).
        """

        if self._configured is not None:
            if physical_total is not None and self._configured > physical_total:
                raise StorageCapacityError(
                    "Заданная ёмкость хранилища превышает физический объём "
                    "диска, доступный MinIO.",
                    configured_bytes=self._configured,
                    physical_bytes=physical_total,
                )
            return self._configured, "config"

        if physical_total is None:
            raise StorageCapacityError(
                "Не удалось определить ёмкость хранилища: MinIO admin API "
                "недоступен, а STORAGE_CAPACITY_BYTES не задан в конфиге.",
            )
        return math.floor(physical_total * self._auto_fraction), "auto"

    async def _resolve_uncached(self) -> CapacityStatus:
        """Вычисляет снимок ёмкости без учёта кэша."""

        physical_total, physical_available = await self._query_physical()
        pool, source = self._compute_pool(physical_total=physical_total)
        return CapacityStatus(
            pool_bytes=pool,
            physical_total_bytes=physical_total,
            physical_available_bytes=physical_available,
            source=source,
            minio_reachable=physical_total is not None,
        )

    def _cache_valid(self) -> bool:
        """Проверяет, актуален ли кэшированный снимок."""

        if self._cached is None or self._cached_at is None:
            return False
        return (time.monotonic() - self._cached_at) < self._cache_ttl_seconds

    async def resolve(self) -> CapacityStatus:
        """Возвращает снимок ёмкости, используя кэш в пределах TTL.

        Returns:
            Текущий снимок ёмкости хранилища.

        Raises:
            StorageCapacityError: Если пул нельзя определить (см.
                :meth:`_compute_pool`).
        """

        if self._cache_valid():
            assert self._cached is not None
            return self._cached

        async with self._lock:
            # Повторная проверка под блокировкой против стампиды.
            if self._cache_valid():
                assert self._cached is not None
                return self._cached
            status = await self._resolve_uncached()
            self._cached = status
            self._cached_at = time.monotonic()
            return status

    async def refresh(self) -> CapacityStatus:
        """Принудительно обновляет снимок ёмкости, минуя кэш.

        Returns:
            Свежий снимок ёмкости хранилища.
        """

        async with self._lock:
            status = await self._resolve_uncached()
            self._cached = status
            self._cached_at = time.monotonic()
            return status

    async def get_pool_bytes(self) -> int:
        """Возвращает размер пула хранилища в байтах.

        Returns:
            Пул хранилища в байтах.

        Raises:
            StorageCapacityError: Если пул нельзя определить.
        """

        status = await self.resolve()
        return status.pool_bytes

    async def validate_on_startup(self) -> CapacityStatus:
        """Проверяет корректность конфигурации ёмкости при старте приложения.

        Заполняет кэш и валидирует, что заданная ёмкость не превышает
        физическую. Должна вызываться один раз на старте, чтобы упасть быстро
        при неверной конфигурации.

        Returns:
            Снимок ёмкости хранилища.

        Raises:
            StorageCapacityError: Если конфигурация некорректна или ёмкость
                нельзя определить.
        """

        status = await self.refresh()
        logger.info(
            "Ёмкость хранилища: пул=%s байт (источник=%s), физически=%s, "
            "свободно=%s",
            status.pool_bytes,
            status.source,
            status.physical_total_bytes,
            status.physical_available_bytes,
        )
        return status


def get_capacity_provider(
    settings: StorageSettings,
) -> CapacityProvider:
    """Создаёт провайдер ёмкости из настроек хранилища.

    Args:
        settings: Настройки объектного хранилища.

    Returns:
        Экземпляр :class:`CapacityProvider`.
    """

    return CapacityProvider(
        settings=settings,
        configured_capacity_bytes=settings.storage_capacity_bytes,
    )
