from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.config import Settings, get_settings
from core.constants import StorageConstants
from core.logging import get_logger
from database import (
    DatabaseHealthStatus,
    get_database_health_report,
)
from database.models.enums import HealthStatus
from schemas.health import (
    ApplicationHealthRead,
    ComponentHealthRead,
    DatabaseHealthRead,
    HealthCheckResponse,
    LivenessResponse,
    ReadinessResponse,
    StorageHealthRead,
)
from services.exceptions import ServiceError, service_error_from_exception
from storage import StorageError, StorageHealthStatus, get_storage_service
from storage.service import StorageService

logger = get_logger("services.health")

SERVICE_NAME = "health"
DATABASE_DEFAULT_LATENCY_THRESHOLD_MS = 1000.0


class HealthService:
    """Сервис проверки состояния приложения и его зависимостей.

    Выполняет liveness, readiness и полный health-check. Сервис проверяет
    состояние приложения, базы данных и объектного хранилища, а также вычисляет
    общий статус на основе статусов отдельных компонентов.

    Attributes:
        settings: Настройки приложения.
        started_at: Дата и время запуска сервиса в UTC.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        storage_service: StorageService | None = None,
        started_at: datetime | None = None,
    ) -> None:
        """Инициализирует сервис проверки состояния.

        Если настройки или сервис хранилища не переданы явно, используются значения
        по умолчанию. Время запуска нормализуется к UTC.

        Args:
            settings: Настройки приложения. Если None, загружаются стандартные
                настройки.
            storage_service: Сервис хранилища. Если None, создается лениво при
                первой проверке хранилища.
            started_at: Дата и время запуска приложения. Если None, используется
                текущее время в UTC.
        """

        self.settings = settings or get_settings()
        self._storage_service = storage_service
        self.started_at = _normalize_datetime(started_at or datetime.now(UTC))

    async def get_liveness(self) -> LivenessResponse:
        """Возвращает liveness-статус приложения.

        Liveness-проверка показывает, что приложение запущено и способно отвечать
        на запросы. Эта проверка не обращается к внешним зависимостям.

        Returns:
            Ответ liveness-проверки с названием приложения, версией, статусом,
            временем проверки и uptime.

        Raises:
            ServiceError: Не пробрасывается явно в текущей реализации, но может
                возникнуть на уровне схем ответа или настроек.
        """

        checked_at = datetime.now(UTC)
        return LivenessResponse(
            app_name=self.settings.app.app_name,
            app_version=self.settings.app.app_version,
            status=HealthStatus.OK,
            alive=True,
            checked_at=checked_at,
            uptime_seconds=self._uptime_seconds(checked_at),
            details={"service": SERVICE_NAME},
        )

    async def get_readiness(
        self,
        *,
        check_database: bool = True,
        check_storage: bool = True,
        check_storage_read_write: bool = False,
        database_latency_threshold_ms: float = DATABASE_DEFAULT_LATENCY_THRESHOLD_MS,
        storage_latency_threshold_ms: float = StorageConstants.STORAGE_DEFAULT_LATENCY_THRESHOLD_MS,
    ) -> ReadinessResponse:
        """Возвращает readiness-статус приложения.

        Readiness-проверка определяет, готово ли приложение обрабатывать запросы.
        При необходимости проверяет базу данных и хранилище, затем агрегирует
        статусы выбранных компонентов в общий статус готовности.

        Args:
            check_database: Нужно ли проверять состояние базы данных.
            check_storage: Нужно ли проверять состояние хранилища.
            check_storage_read_write: Нужно ли выполнять read/write-проверку
                хранилища. Если False, выполняется базовая проверка.
            database_latency_threshold_ms: Порог задержки базы данных в
                миллисекундах.
            storage_latency_threshold_ms: Порог задержки хранилища в миллисекундах.

        Returns:
            Ответ readiness-проверки с общим статусом, признаком готовности,
            состоянием базы данных, состоянием хранилища и деталями проверки.

        Raises:
            ServiceError: Если не удалось вычислить readiness-статус или если
                ошибка уже была преобразована в сервисную ошибку.
            StorageError: Если проверка хранилища завершилась ошибкой и не была
                преобразована ниже по стеку.
        """

        operation = "get_readiness"
        checked_at = datetime.now(UTC)
        database_health: DatabaseHealthRead | None = None
        storage_health: StorageHealthRead | None = None

        try:
            if check_database:
                database_status = await get_database_health_report(
                    latency_threshold_ms=database_latency_threshold_ms,
                    raise_on_error=False,
                )
                database_health = _database_health_to_schema(
                    database_status,
                    latency_threshold_ms=database_latency_threshold_ms,
                )

            if check_storage:
                storage_status = await self._get_storage_health(
                    check_read_write=check_storage_read_write,
                    latency_threshold_ms=storage_latency_threshold_ms,
                )
                storage_health = _storage_health_to_schema(storage_status)

            status = _aggregate_status(
                component.status
                for component in (database_health, storage_health)
                if component is not None
            )

            return ReadinessResponse(
                app_name=self.settings.app.app_name,
                app_version=self.settings.app.app_version,
                status=status,
                ready=status == HealthStatus.OK,
                checked_at=checked_at,
                database=database_health,
                storage=storage_health,
                details={
                    "service": SERVICE_NAME,
                    "check_database": check_database,
                    "check_storage": check_storage,
                    "check_storage_read_write": check_storage_read_write,
                },
            )
        except ServiceError:
            raise
        except Exception as exc:
            raise service_error_from_exception(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось рассчитать статус готовности.",
            ) from exc

    async def get_health_check(
        self,
        *,
        check_database: bool = True,
        check_storage: bool = True,
        check_storage_read_write: bool = True,
        database_latency_threshold_ms: float = DATABASE_DEFAULT_LATENCY_THRESHOLD_MS,
        storage_latency_threshold_ms: float = StorageConstants.STORAGE_DEFAULT_LATENCY_THRESHOLD_MS,
    ) -> HealthCheckResponse:
        """Возвращает полный health-check приложения.

        Собирает состояние приложения и, если включены соответствующие флаги,
        состояние базы данных и хранилища. Затем формирует список компонентов
        и вычисляет итоговый статус health-check.

        Args:
            check_database: Нужно ли проверять состояние базы данных.
            check_storage: Нужно ли проверять состояние хранилища.
            check_storage_read_write: Нужно ли выполнять read/write-проверку
                хранилища.
            database_latency_threshold_ms: Порог задержки базы данных в
                миллисекундах.
            storage_latency_threshold_ms: Порог задержки хранилища в миллисекундах.

        Returns:
            Ответ полного health-check с состоянием приложения, базы данных,
            хранилища, списком компонентов и итоговым статусом.

        Raises:
            ServiceError: Если не удалось вычислить health-check статус или если
                ошибка уже была преобразована в сервисную ошибку.
            StorageError: Если проверка хранилища завершилась ошибкой и не была
                преобразована ниже по стеку.
        """

        operation = "get_health_check"
        checked_at = datetime.now(UTC)
        components: list[ComponentHealthRead] = []
        database_health: DatabaseHealthRead | None = None
        storage_health: StorageHealthRead | None = None

        try:
            application = ApplicationHealthRead(
                app_name=self.settings.app.app_name,
                app_version=self.settings.app.app_version,
                status=HealthStatus.OK,
                debug=self.settings.app.debug,
                uptime_seconds=self._uptime_seconds(checked_at),
                checked_at=checked_at,
                details={"service": SERVICE_NAME},
            )

            if check_database:
                database_status = await get_database_health_report(
                    latency_threshold_ms=database_latency_threshold_ms,
                    raise_on_error=False,
                )
                database_health = _database_health_to_schema(
                    database_status,
                    latency_threshold_ms=database_latency_threshold_ms,
                )
                components.append(ComponentHealthRead.model_validate(database_health))

            if check_storage:
                storage_status = await self._get_storage_health(
                    check_read_write=check_storage_read_write,
                    latency_threshold_ms=storage_latency_threshold_ms,
                )
                storage_health = _storage_health_to_schema(storage_status)
                components.append(ComponentHealthRead.model_validate(storage_health))

            status = _aggregate_status(
                [
                    application.status,
                    *[item.status for item in components],
                ]
            )

            return HealthCheckResponse(
                app_name=self.settings.app.app_name,
                app_version=self.settings.app.app_version,
                status=status,
                checked_at=checked_at,
                application=application,
                database=database_health,
                storage=storage_health,
                components=components,
                details={
                    "service": SERVICE_NAME,
                    "check_database": check_database,
                    "check_storage": check_storage,
                    "check_storage_read_write": check_storage_read_write,
                },
            )
        except ServiceError:
            raise
        except Exception as exc:
            raise service_error_from_exception(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось рассчитать статус проверки работоспособности.",
            ) from exc

    async def _get_storage_health(
        self,
        *,
        check_read_write: bool,
        latency_threshold_ms: float,
    ) -> StorageHealthStatus:
        """Проверяет состояние объектного хранилища.

        Получает сервис хранилища, выполняет health-check для bucket файлов и,
        при необходимости, выполняет read/write-проверку. Ошибки хранилища
        логируются и пробрасываются выше.

        Args:
            check_read_write: Нужно ли выполнять read/write-проверку хранилища.
            latency_threshold_ms: Порог задержки хранилища в миллисекундах.

        Returns:
            Статус состояния хранилища.

        Raises:
            StorageError: Если проверка хранилища завершилась ошибкой.
        """

        storage_service = self._get_storage_service()
        try:
            return await storage_service.health.check_storage_health(
                bucket=storage_service.default_files_bucket,
                latency_threshold_ms=latency_threshold_ms,
                check_read_write=check_read_write,
            )
        except StorageError as exc:
            logger.warning(
                "Проверка работоспособности хранилища не удалась.",
                extra={
                    "service": SERVICE_NAME,
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
            )
            raise

    def _get_storage_service(self) -> StorageService:
        """Возвращает сервис хранилища.

        Если сервис хранилища еще не был создан или передан в конструктор,
        создает его лениво на основе настроек хранилища.

        Returns:
            Экземпляр сервиса хранилища.
        """

        if self._storage_service is None:
            self._storage_service = get_storage_service(settings=self.settings.storage)
        return self._storage_service

    def _uptime_seconds(self, checked_at: datetime) -> float:
        """Вычисляет uptime приложения в секундах.

        Нормализует время проверки к UTC и рассчитывает разницу между временем
        проверки и временем запуска сервиса. Если результат отрицательный,
        возвращает 0.0.

        Args:
            checked_at: Дата и время проверки.

        Returns:
            Uptime приложения в секундах, округленный до трех знаков после запятой.
        """

        current = _normalize_datetime(checked_at)
        delta = current - self.started_at
        seconds = delta.total_seconds()
        if seconds < 0:
            return 0.0
        return round(seconds, 3)


def _database_health_to_schema(
    status: DatabaseHealthStatus,
    *,
    latency_threshold_ms: float,
) -> DatabaseHealthRead:
    """Преобразует статус базы данных в схему ответа.

    Нормализует статус базы данных, переносит данные соединения, задержку,
    ошибку, сообщение и детали в DatabaseHealthRead. Если в исходном статусе
    отсутствует порог задержки, использует переданное значение.

    Args:
        status: Результат проверки состояния базы данных.
        latency_threshold_ms: Порог задержки базы данных в миллисекундах.

    Returns:
        Схема состояния базы данных.
    """

    return DatabaseHealthRead(
        component="database",
        status=_normalize_health_value(status.status),
        connection=status.connection,
        latency_ms=status.latency_ms,
        latency_threshold_ms=status.latency_threshold_ms or latency_threshold_ms,
        error=status.error,
        message=status.message,
        details=status.details or None,
        checked_at=datetime.now(UTC),
    )


def _storage_health_to_schema(status: StorageHealthStatus) -> StorageHealthRead:
    """Преобразует статус хранилища в схему ответа.

    Args:
        status: Результат проверки состояния хранилища.

    Returns:
        Схема состояния хранилища.
    """

    return StorageHealthRead.model_validate(status)


def _aggregate_status(items: Any) -> HealthStatus:
    """Агрегирует статусы компонентов в общий статус.

    Игнорирует None-значения, нормализует оставшиеся статусы и применяет
    приоритет: UNAVAILABLE важнее DEGRADED, DEGRADED важнее OK. Если список
    статусов пуст, возвращает OK.

    Args:
        items: Коллекция статусов компонентов или значений, приводимых к
            HealthStatus.

    Returns:
        Итоговый статус health-check.
    """

    statuses = [item for item in items if item is not None]
    if not statuses:
        return HealthStatus.OK
    normalized = [_normalize_health_value(value) for value in statuses]
    if any(value == HealthStatus.UNAVAILABLE for value in normalized):
        return HealthStatus.UNAVAILABLE
    if any(value == HealthStatus.DEGRADED for value in normalized):
        return HealthStatus.DEGRADED
    return HealthStatus.OK


def _normalize_health_value(value: HealthStatus | str) -> HealthStatus:
    """Нормализует значение статуса здоровья.

    Преобразует строковые значения статуса в HealthStatus. Значения ok,
    healthy, success и available считаются OK. Значения degraded, warning и
    slow считаются DEGRADED. Остальные значения считаются UNAVAILABLE.

    Args:
        value: Статус HealthStatus или строковое представление статуса.

    Returns:
        Нормализованный статус здоровья.
    """

    if isinstance(value, HealthStatus):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"ok", "healthy", "success", "available"}:
        return HealthStatus.OK
    if normalized in {"degraded", "warning", "slow"}:
        return HealthStatus.DEGRADED
    return HealthStatus.UNAVAILABLE


def _normalize_datetime(value: datetime) -> datetime:
    """Нормализует дату и время к UTC.

    Если значение не содержит timezone, считает его временем UTC. Если timezone
    указан, переводит значение в UTC.

    Args:
        value: Дата и время для нормализации.

    Returns:
        Дата и время с timezone UTC.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# Глобальный singleton-экземпляр сервиса проверки состояния.
_health_service: HealthService | None = None


def get_health_service(
    *,
    settings: Settings | None = None,
    storage_service: StorageService | None = None,
) -> HealthService:
    """Возвращает экземпляр сервиса проверки состояния.

    Если переданы настройки или сервис хранилища, создает новый экземпляр
    HealthService с указанными зависимостями. Если зависимости не переданы,
    возвращает глобальный singleton-экземпляр, создавая его при первом обращении.

    Args:
        settings: Настройки приложения для нового экземпляра сервиса.
        storage_service: Сервис хранилища для нового экземпляра сервиса.

    Returns:
        Экземпляр HealthService.
    """

    global _health_service

    if settings is not None or storage_service is not None:
        return HealthService(settings=settings, storage_service=storage_service)

    if _health_service is None:
        _health_service = HealthService()

    return _health_service
