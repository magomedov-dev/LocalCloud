from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError, TimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import DatabaseSettings
from core.logging import get_logger
from database.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    DatabaseTimeoutError,
)

logger = get_logger("database.client")

async_engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


def is_db_client_initialized() -> bool:
    """Проверяет, был ли инициализирован клиент базы данных.

    Returns:
        `True`, если engine и фабрика сессий инициализированы, иначе `False`.
    """

    return async_engine is not None and async_session_factory is not None


def init_db_client(settings: DatabaseSettings) -> None:
    """Инициализирует глобальный асинхронный клиент базы данных.

    Создаёт `AsyncEngine` и фабрику асинхронных сессий на основе настроек
    подключения к PostgreSQL. Функцию следует вызывать один раз при старте
    приложения.

    Args:
        settings: Настройки подключения к базе данных.

    Raises:
        DatabaseConnectionError: Если клиент уже инициализирован или
            инициализация завершилась ошибкой.
    """

    global async_engine
    global async_session_factory

    if is_db_client_initialized():
        raise DatabaseConnectionError(
            "Клиент базы данных уже инициализирован.",
            details={
                "hint": "Повторная инициализация запрещена. "
                "Сначала вызовите close_db_client().",
            },
        )

    try:
        new_async_engine = create_async_engine(
            settings.database_url,
            echo=settings.postgres_echo,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
            pool_timeout=settings.postgres_pool_timeout,
            pool_recycle=settings.postgres_pool_recycle,
            pool_pre_ping=settings.postgres_pool_pre_ping,
        )

        new_async_session_factory = async_sessionmaker(
            bind=new_async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    except (ImportError, SQLAlchemyError) as exc:
        async_engine = None
        async_session_factory = None

        raise DatabaseConnectionError(
            "Не удалось инициализировать клиент базы данных.",
            database=settings.postgres_db,
            host=settings.postgres_host,
            port=settings.postgres_port,
            details={
                "reason": str(exc),
                "error_type": exc.__class__.__name__,
            },
            cause=exc,
        ) from exc

    async_engine = new_async_engine
    async_session_factory = new_async_session_factory

    logger.info(
        "Клиент базы данных инициализирован",
        extra={
            "pool_size": settings.postgres_pool_size,
            "max_overflow": settings.postgres_max_overflow,
            "pool_timeout": settings.postgres_pool_timeout,
            "pool_recycle": settings.postgres_pool_recycle,
            "pool_pre_ping": settings.postgres_pool_pre_ping,
            "echo": settings.postgres_echo,
        },
    )


async def close_db_client() -> None:
    """Закрывает клиент базы данных и освобождает пул соединений.

    Если клиент не был инициализирован, функция сбрасывает фабрику сессий,
    пишет debug-сообщение и завершает выполнение без ошибки.

    Raises:
        DatabaseError: Если клиент не удалось закрыть.
    """

    global async_engine
    global async_session_factory

    if async_engine is None:
        async_session_factory = None
        logger.debug("Клиент базы данных не инициализирован; закрывать нечего")
        return

    try:
        await async_engine.dispose()
        logger.info("Клиент базы данных закрыт")

    except SQLAlchemyError as exc:
        raise DatabaseError(
            "Не удалось закрыть клиент базы данных.",
            details={"reason": str(exc)},
            cause=exc,
        ) from exc

    finally:
        async_engine = None
        async_session_factory = None


def get_async_engine() -> AsyncEngine:
    """Возвращает инициализированный `AsyncEngine`.

    Returns:
        Глобальный асинхронный SQLAlchemy engine.

    Raises:
        DatabaseConnectionError: Если клиент базы данных не был
            инициализирован.
    """

    if async_engine is None:
        raise DatabaseConnectionError(
            "Движок базы данных не инициализирован.",
            details={
                "hint": "Вызовите init_db_client() при запуске приложения.",
            },
        )

    return async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Возвращает фабрику асинхронных сессий.

    Returns:
        Глобальная фабрика `AsyncSession`.

    Raises:
        DatabaseConnectionError: Если фабрика сессий не была
            инициализирована.
    """

    if async_session_factory is None:
        raise DatabaseConnectionError(
            "Фабрика сессий базы данных не инициализирована.",
            details={
                "hint": "Вызовите init_db_client() при запуске приложения.",
            },
        )

    return async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Создаёт FastAPI dependency для получения ``AsyncSession``.

    Зависимость не выполняет commit автоматически. Commit и rollback должны
    контролироваться сервисным слоем, Unit of Work или конкретным обработчиком
    сценария.

    Yields:
        Асинхронная SQLAlchemy-сессия.

    Raises:
        DatabaseTimeoutError: Если операция с сессией завершилась по timeout.
        DatabaseConnectionError: Если возникла ошибка соединения.
        DatabaseError: Если операция с сессией завершилась ошибкой SQLAlchemy.
    """

    session_factory = get_async_session_factory()

    async with session_factory() as session:
        try:
            yield session

        except TimeoutError as exc:
            await session.rollback()

            raise DatabaseTimeoutError(
                "Время выполнения операции с сессией базы данных истекло.",
                operation="session",
                details={"reason": str(exc)},
                cause=exc,
            ) from exc

        except DBAPIError as exc:
            await session.rollback()

            raise DatabaseConnectionError(
                "Ошибка соединения при выполнении операции с базой данных.",
                details={
                    "reason": str(exc),
                    "connection_invalidated": exc.connection_invalidated,
                },
                cause=exc,
            ) from exc

        except SQLAlchemyError as exc:
            await session.rollback()

            raise DatabaseError(
                "Операция с сессией базы данных не удалась.",
                details={"reason": str(exc)},
                cause=exc,
            ) from exc


async def ping_database() -> bool:
    """Проверяет доступность базы данных запросом `SELECT 1`.

    Открывает соединение через глобальный engine, выполняет простой запрос
    `SELECT 1` и проверяет, что база данных вернула ожидаемое значение.

    Returns:
        `True`, если база данных доступна и вернула ожидаемый результат.

    Raises:
        DatabaseConnectionError: Если клиент не инициализирован, соединение
            недоступно или запрос вернул неожиданный результат.
        DatabaseTimeoutError: Если соединение или запрос завершились по
            timeout.
    """

    engine = get_async_engine()

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            value = result.scalar_one()

    except TimeoutError as exc:
        raise DatabaseTimeoutError(
            "Время выполнения ping базы данных истекло.",
            operation="ping",
            details={"reason": str(exc)},
            cause=exc,
        ) from exc

    except DBAPIError as exc:
        raise DatabaseConnectionError(
            "Не удалось выполнить ping базы данных из-за ошибки соединения.",
            details={
                "reason": str(exc),
                "connection_invalidated": exc.connection_invalidated,
            },
            cause=exc,
        ) from exc

    except SQLAlchemyError as exc:
        raise DatabaseConnectionError(
            "Не удалось выполнить ping базы данных.",
            details={"reason": str(exc)},
            cause=exc,
        ) from exc

    if value != 1:
        raise DatabaseConnectionError(
            "Ping базы данных вернул неожиданный результат.",
            details={
                "expected": 1,
                "actual": value,
            },
        )

    return True
