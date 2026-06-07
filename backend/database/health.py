from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError, TimeoutError

from database.client import get_async_session_factory
from database.exceptions import (
    DatabaseConnectionError,
    DatabaseHealthCheckError,
    DatabaseTimeoutError,
)


@dataclass(frozen=True, slots=True)
class DatabaseHealthStatus:
    """Результат проверки работоспособности PostgreSQL.

    Используется как DTO для передачи состояния базы данных в health endpoint
    или внутренние сервисы мониторинга.

    Attributes:
        component: Название проверяемого компонента.
        status: Текущий статус компонента: `healthy`, `degraded`
            или `unavailable`.
        connection: Признак успешного подключения к базе данных.
        latency_ms: Измеренная задержка ответа базы данных в миллисекундах.
        latency_threshold_ms: Максимально допустимая задержка ответа
            в миллисекундах.
        error: Название ошибки, если проверка завершилась неуспешно.
        message: Человекочитаемое описание ошибки или состояния.
        details: Дополнительные диагностические данные.
    """

    component: str = "database"
    status: str = "healthy"
    connection: bool = True
    latency_ms: float | None = None
    latency_threshold_ms: float | None = None
    error: str | None = None
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Проверяет, что база данных доступна и работает штатно.

        Returns:
            `True`, если статус равен `healthy` и подключение доступно,
            иначе `False`.
        """

        return self.status == "healthy" and self.connection


async def check_database_connection() -> bool:
    """Проверяет доступность подключения к PostgreSQL.

    Выполняет простой запрос `SELECT 1`. Если запрос успешен и результат
    равен `1`, база данных считается доступной.

    Returns:
        `True`, если база данных доступна.

    Raises:
        DatabaseConnectionError: Если клиент базы данных не инициализирован,
            соединение недоступно или PostgreSQL вернул неожиданный результат.
        DatabaseTimeoutError: Если запрос завершился по timeout.
    """

    session_factory = get_async_session_factory()

    try:
        async with session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            value = result.scalar_one()

            if value != 1:
                raise DatabaseConnectionError(
                    "Проверка подключения к базе данных вернула неожиданный результат.",
                    details={
                        "expected": 1,
                        "actual": value,
                    },
                )

        return True

    except DatabaseConnectionError:
        raise

    except TimeoutError as exc:
        raise DatabaseTimeoutError(
            "Время проверки подключения к базе данных истекло.",
            operation="database_connection_check",
            details={
                "reason": str(exc),
            },
            cause=exc,
        ) from exc

    except DBAPIError as exc:
        raise DatabaseConnectionError(
            "Не удалось проверить подключение к базе данных из-за ошибки соединения.",
            details={
                "reason": str(exc),
                "connection_invalidated": exc.connection_invalidated,
            },
            cause=exc,
        ) from exc

    except SQLAlchemyError as exc:
        raise DatabaseConnectionError(
            "Не удалось проверить подключение к базе данных.",
            details={
                "reason": str(exc),
            },
            cause=exc,
        ) from exc


async def check_database_latency() -> float:
    """Измеряет задержку ответа PostgreSQL.

    Выполняет простой запрос `SELECT 1` и измеряет длительность операции
    с помощью монотонного таймера `time.perf_counter`.

    Returns:
        Задержка базы данных в миллисекундах, округлённая до трёх знаков.

    Raises:
        DatabaseHealthCheckError: Если проверка задержки не удалась.
        DatabaseTimeoutError: Если запрос завершился по timeout.
    """

    session_factory = get_async_session_factory()
    started_at = time.perf_counter()

    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))

    except TimeoutError as exc:
        raise DatabaseTimeoutError(
            "Время проверки задержки базы данных истекло.",
            operation="database_latency_check",
            details={
                "reason": str(exc),
            },
            cause=exc,
        ) from exc

    except DBAPIError as exc:
        raise DatabaseHealthCheckError(
            "Не удалось выполнить проверку задержки базы данных из-за ошибки соединения.",
            details={
                "reason": str(exc),
                "connection_invalidated": exc.connection_invalidated,
            },
            cause=exc,
        ) from exc

    except SQLAlchemyError as exc:
        raise DatabaseHealthCheckError(
            "Не удалось выполнить проверку задержки базы данных.",
            details={
                "reason": str(exc),
            },
            cause=exc,
        ) from exc

    finished_at = time.perf_counter()
    latency_ms = (finished_at - started_at) * 1000

    return round(latency_ms, 3)


async def check_database_health(
    *,
    latency_threshold_ms: float | None = 1000.0,
) -> DatabaseHealthStatus:
    """Проверяет общее состояние PostgreSQL.

    Выполняет проверку доступности соединения, измеряет задержку ответа базы
    данных и сравнивает её с допустимым порогом, если порог задан.

    Args:
        latency_threshold_ms: Максимально допустимая задержка в миллисекундах.
            Если значение равно `None`, проверка порога не выполняется.

    Returns:
        DTO с информацией о состоянии базы данных.

    Raises:
        DatabaseTimeoutError: Если задержка превышает `latency_threshold_ms`.
        DatabaseHealthCheckError: Если проверка состояния не удалась.
    """

    try:
        connection_ok = await check_database_connection()
        latency_ms = await check_database_latency()

        if latency_threshold_ms is not None and latency_ms > latency_threshold_ms:
            raise DatabaseTimeoutError(
                "Задержка базы данных слишком высока.",
                timeout_seconds=latency_threshold_ms / 1000,
                operation="database_health_check",
                details={
                    "latency_ms": latency_ms,
                    "latency_threshold_ms": latency_threshold_ms,
                },
            )

        return DatabaseHealthStatus(
            status="healthy",
            connection=connection_ok,
            latency_ms=latency_ms,
            latency_threshold_ms=latency_threshold_ms,
        )

    except DatabaseTimeoutError:
        raise

    except DatabaseConnectionError as exc:
        raise DatabaseHealthCheckError(
            "Проверка работоспособности базы данных не удалась из-за недоступности подключения.",
            details={
                "reason": str(exc),
            },
            cause=exc,
        ) from exc

    except DatabaseHealthCheckError:
        raise

    except Exception as exc:
        raise DatabaseHealthCheckError(
            "Непредвиденная ошибка при проверке работоспособности базы данных.",
            details={
                "reason": str(exc),
                "error_type": exc.__class__.__name__,
            },
            cause=exc,
        ) from exc


async def get_database_health_report(
    *,
    latency_threshold_ms: float | None = 1000.0,
    raise_on_error: bool = False,
) -> DatabaseHealthStatus:
    """Возвращает health-отчёт базы данных.

    Оборачивает `check_database_health` и преобразует исключения в
    `DatabaseHealthStatus`, если `raise_on_error` равен `False`. Функция
    удобна для health endpoint-ов, где вместо проброса исключения нужно
    вернуть статус `degraded` или `unavailable`.

    Args:
        latency_threshold_ms: Максимально допустимая задержка в миллисекундах.
            Если значение равно `None`, проверка порога не выполняется.
        raise_on_error: Если `True`, исключения пробрасываются выше. Если
            `False`, ошибка преобразуется в DTO health-отчёта.

    Returns:
        DTO с результатом проверки работоспособности базы данных.

    Raises:
        DatabaseTimeoutError: Если `raise_on_error` равен `True` и проверка
            завершилась по timeout или задержка превысила допустимый порог.
        DatabaseHealthCheckError: Если `raise_on_error` равен `True` и общая
            проверка состояния базы данных завершилась ошибкой.
        DatabaseConnectionError: Если `raise_on_error` равен `True` и возникла
            ошибка подключения к базе данных.
    """

    try:
        return await check_database_health(
            latency_threshold_ms=latency_threshold_ms,
        )

    except DatabaseTimeoutError as exc:
        if raise_on_error:
            raise

        return DatabaseHealthStatus(
            status="degraded",
            connection=True,
            latency_ms=exc.details.get("latency_ms"),
            latency_threshold_ms=exc.details.get("latency_threshold_ms"),
            error=exc.__class__.__name__,
            message=exc.message,
            details=exc.details,
        )

    except DatabaseHealthCheckError as exc:
        if raise_on_error:
            raise

        return DatabaseHealthStatus(
            status="unavailable",
            connection=False,
            latency_ms=None,
            latency_threshold_ms=latency_threshold_ms,
            error=exc.__class__.__name__,
            message=exc.message,
            details=exc.details,
        )

    except DatabaseConnectionError as exc:
        if raise_on_error:
            raise

        return DatabaseHealthStatus(
            status="unavailable",
            connection=False,
            latency_ms=None,
            latency_threshold_ms=latency_threshold_ms,
            error=exc.__class__.__name__,
            message=exc.message,
            details=exc.details,
        )
