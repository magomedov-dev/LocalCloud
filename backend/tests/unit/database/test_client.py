"""Модульные тесты клиента БД: инициализация и закрытие движка, выдача сессий,
проверка соединения (ping) и жизненный цикл подключения."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as SATimeoutError

import database.client as client
from database.client import (
    close_db_client,
    get_async_engine,
    get_async_session_factory,
    get_db_session,
    init_db_client,
    is_db_client_initialized,
    ping_database,
)
from database.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    DatabaseTimeoutError,
)


def make_settings(**overrides: object) -> SimpleNamespace:
    """Создаёт лёгкую замену ``DatabaseSettings``.

    ``init_db_client`` читает только обычные атрибуты, поэтому namespace
    позволяет обойти валидацию pydantic, предоставляя ровно те поля, к которым
    обращается исходный код.
    """

    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
        "postgres_echo": False,
        "postgres_pool_size": 5,
        "postgres_max_overflow": 10,
        "postgres_pool_timeout": 30,
        "postgres_pool_recycle": 1800,
        "postgres_pool_pre_ping": True,
        "postgres_db": "testdb",
        "postgres_host": "localhost",
        "postgres_port": 5432,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture(autouse=True)
def reset_client_globals() -> object:
    """Гарантирует, что каждый тест начинается и заканчивается с неинициализированным клиентом."""

    client.async_engine = None
    client.async_session_factory = None
    yield
    client.async_engine = None
    client.async_session_factory = None


# ---------------------------------------------------------------------------
# is_db_client_initialized
# ---------------------------------------------------------------------------


class TestIsDbClientInitialized:
    def test_false_when_nothing_set(self) -> None:
        assert is_db_client_initialized() is False

    def test_false_when_only_engine_set(self) -> None:
        client.async_engine = MagicMock()
        client.async_session_factory = None
        assert is_db_client_initialized() is False

    def test_false_when_only_factory_set(self) -> None:
        client.async_engine = None
        client.async_session_factory = MagicMock()
        assert is_db_client_initialized() is False

    def test_true_when_both_set(self) -> None:
        client.async_engine = MagicMock()
        client.async_session_factory = MagicMock()
        assert is_db_client_initialized() is True


# ---------------------------------------------------------------------------
# init_db_client
# ---------------------------------------------------------------------------


class TestInitDbClient:
    def test_creates_engine_with_expected_args(self) -> None:
        settings = make_settings(
            postgres_echo=True,
            postgres_pool_size=7,
            postgres_max_overflow=3,
            postgres_pool_timeout=15,
            postgres_pool_recycle=900,
            postgres_pool_pre_ping=False,
        )
        fake_engine = MagicMock()
        fake_factory = MagicMock()

        with (
            patch(
                "database.client.create_async_engine",
                return_value=fake_engine,
            ) as mock_create_engine,
            patch(
                "database.client.async_sessionmaker",
                return_value=fake_factory,
            ) as mock_sessionmaker,
        ):
            init_db_client(settings)

        mock_create_engine.assert_called_once_with(
            settings.database_url,
            echo=True,
            pool_size=7,
            max_overflow=3,
            pool_timeout=15,
            pool_recycle=900,
            pool_pre_ping=False,
        )
        # sessionmaker привязан к только что созданному движку.
        _, kwargs = mock_sessionmaker.call_args
        assert kwargs["bind"] is fake_engine
        assert kwargs["expire_on_commit"] is False
        assert kwargs["autoflush"] is False
        assert kwargs["autocommit"] is False

    def test_sets_globals_on_success(self) -> None:
        settings = make_settings()
        fake_engine = MagicMock()
        fake_factory = MagicMock()

        with (
            patch("database.client.create_async_engine", return_value=fake_engine),
            patch("database.client.async_sessionmaker", return_value=fake_factory),
        ):
            init_db_client(settings)

        assert client.async_engine is fake_engine
        assert client.async_session_factory is fake_factory
        assert is_db_client_initialized() is True

    def test_raises_when_already_initialized(self) -> None:
        client.async_engine = MagicMock()
        client.async_session_factory = MagicMock()

        with pytest.raises(DatabaseConnectionError):
            init_db_client(make_settings())

    def test_already_initialized_does_not_recreate_engine(self) -> None:
        client.async_engine = MagicMock()
        client.async_session_factory = MagicMock()

        with patch("database.client.create_async_engine") as mock_create_engine:
            with pytest.raises(DatabaseConnectionError):
                init_db_client(make_settings())

        mock_create_engine.assert_not_called()

    def test_sqlalchemy_error_raises_connection_error(self) -> None:
        settings = make_settings()
        with patch(
            "database.client.create_async_engine",
            side_effect=SQLAlchemyError("boom"),
        ):
            with pytest.raises(DatabaseConnectionError) as exc_info:
                init_db_client(settings)

        assert exc_info.value.cause is not None
        # При ошибке глобальные переменные сбрасываются в None.
        assert client.async_engine is None
        assert client.async_session_factory is None

    def test_import_error_raises_connection_error(self) -> None:
        settings = make_settings()
        with patch(
            "database.client.create_async_engine",
            side_effect=ImportError("no driver"),
        ):
            with pytest.raises(DatabaseConnectionError):
                init_db_client(settings)

        assert client.async_engine is None
        assert client.async_session_factory is None

    def test_error_details_include_connection_metadata(self) -> None:
        settings = make_settings(
            postgres_db="mydb",
            postgres_host="dbhost",
            postgres_port=6543,
        )
        original = SQLAlchemyError("fail")
        with patch(
            "database.client.create_async_engine",
            side_effect=original,
        ):
            with pytest.raises(DatabaseConnectionError) as exc_info:
                init_db_client(settings)

        assert exc_info.value.cause is original
        assert "fail" in str(exc_info.value.details)


# ---------------------------------------------------------------------------
# close_db_client
# ---------------------------------------------------------------------------


class TestCloseDbClient:
    async def test_disposes_engine_and_resets_globals(self) -> None:
        engine = MagicMock()
        engine.dispose = AsyncMock()
        client.async_engine = engine
        client.async_session_factory = MagicMock()

        await close_db_client()

        engine.dispose.assert_awaited_once()
        assert client.async_engine is None
        assert client.async_session_factory is None

    async def test_noop_when_not_initialized(self) -> None:
        client.async_engine = None
        client.async_session_factory = MagicMock()

        await close_db_client()

        # Фабрика сброшена, исключение не возникает.
        assert client.async_session_factory is None
        assert client.async_engine is None

    async def test_dispose_error_raises_database_error(self) -> None:
        engine = MagicMock()
        engine.dispose = AsyncMock(side_effect=SQLAlchemyError("dispose failed"))
        client.async_engine = engine
        client.async_session_factory = MagicMock()

        with pytest.raises(DatabaseError) as exc_info:
            await close_db_client()

        assert exc_info.value.cause is not None
        # Блок finally всё равно сбрасывает глобальные переменные.
        assert client.async_engine is None
        assert client.async_session_factory is None


# ---------------------------------------------------------------------------
# get_async_engine / get_async_session_factory
# ---------------------------------------------------------------------------


class TestGetAsyncEngine:
    def test_returns_engine_when_initialized(self) -> None:
        engine = MagicMock()
        client.async_engine = engine
        assert get_async_engine() is engine

    def test_raises_when_not_initialized(self) -> None:
        client.async_engine = None
        with pytest.raises(DatabaseConnectionError):
            get_async_engine()


class TestGetAsyncSessionFactory:
    def test_returns_factory_when_initialized(self) -> None:
        factory = MagicMock()
        client.async_session_factory = factory
        assert get_async_session_factory() is factory

    def test_raises_when_not_initialized(self) -> None:
        client.async_session_factory = None
        with pytest.raises(DatabaseConnectionError):
            get_async_session_factory()


# ---------------------------------------------------------------------------
# get_db_session
# ---------------------------------------------------------------------------


def _make_session_ctx() -> tuple[AsyncMock, MagicMock]:
    """Возвращает (session, factory), где factory() — асинхронный контекстный менеджер."""

    session = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    return session, factory


class TestGetDbSession:
    async def test_yields_session(self) -> None:
        session, factory = _make_session_ctx()
        with patch(
            "database.client.get_async_session_factory",
            return_value=factory,
        ):
            agen = get_db_session()
            yielded = await anext(agen)
            assert yielded is session
            # Исчерпываем генератор, чтобы сработал выход из контекстного менеджера.
            with pytest.raises(StopAsyncIteration):
                await anext(agen)

        factory.assert_called_once()
        session.rollback.assert_not_awaited()

    async def test_full_iteration_with_async_for(self) -> None:
        session, factory = _make_session_ctx()
        seen = []
        with patch(
            "database.client.get_async_session_factory",
            return_value=factory,
        ):
            async for s in get_db_session():
                seen.append(s)

        assert seen == [session]

    async def test_timeout_error_rolls_back_and_raises(self) -> None:
        session, factory = _make_session_ctx()
        with patch(
            "database.client.get_async_session_factory",
            return_value=factory,
        ):
            agen = get_db_session()
            await anext(agen)
            with pytest.raises(DatabaseTimeoutError):
                await agen.athrow(SATimeoutError("timed out"))

        session.rollback.assert_awaited_once()

    async def test_dbapi_error_rolls_back_and_raises_connection_error(self) -> None:
        session, factory = _make_session_ctx()
        dbapi_exc = DBAPIError("stmt", {}, Exception("orig"))
        with patch(
            "database.client.get_async_session_factory",
            return_value=factory,
        ):
            agen = get_db_session()
            await anext(agen)
            with pytest.raises(DatabaseConnectionError) as exc_info:
                await agen.athrow(dbapi_exc)

        session.rollback.assert_awaited_once()
        assert "connection_invalidated" in str(exc_info.value.details)

    async def test_sqlalchemy_error_rolls_back_and_raises_database_error(self) -> None:
        session, factory = _make_session_ctx()
        with patch(
            "database.client.get_async_session_factory",
            return_value=factory,
        ):
            agen = get_db_session()
            await anext(agen)
            with pytest.raises(DatabaseError) as exc_info:
                await agen.athrow(SQLAlchemyError("query failed"))

        session.rollback.assert_awaited_once()
        assert exc_info.value.cause is not None

    async def test_propagates_factory_not_initialized_error(self) -> None:
        client.async_session_factory = None
        with pytest.raises(DatabaseConnectionError):
            await anext(get_db_session())


# ---------------------------------------------------------------------------
# ping_database
# ---------------------------------------------------------------------------


def _make_engine_connect_ctx(
    *,
    scalar_value: int = 1,
    execute_side_effect: Exception | None = None,
) -> MagicMock:
    """Создаёт движок, чей connect() выдаёт соединение с методом execute()."""

    result = MagicMock()
    result.scalar_one = MagicMock(return_value=scalar_value)

    connection = MagicMock()
    if execute_side_effect is not None:
        connection.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        connection.execute = AsyncMock(return_value=result)

    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=connection)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect = MagicMock(return_value=conn_ctx)
    return engine


class TestPingDatabase:
    async def test_success_returns_true(self) -> None:
        engine = _make_engine_connect_ctx(scalar_value=1)
        client.async_engine = engine

        result = await ping_database()

        assert result is True
        engine.connect.assert_called_once()

    async def test_raises_when_engine_not_initialized(self) -> None:
        client.async_engine = None
        with pytest.raises(DatabaseConnectionError):
            await ping_database()

    async def test_unexpected_value_raises_connection_error(self) -> None:
        engine = _make_engine_connect_ctx(scalar_value=42)
        client.async_engine = engine

        with pytest.raises(DatabaseConnectionError) as exc_info:
            await ping_database()

        assert "actual" in str(exc_info.value.details)

    async def test_timeout_raises_timeout_error(self) -> None:
        engine = _make_engine_connect_ctx(
            execute_side_effect=SATimeoutError("timed out"),
        )
        client.async_engine = engine

        with pytest.raises(DatabaseTimeoutError):
            await ping_database()

    async def test_dbapi_error_raises_connection_error(self) -> None:
        dbapi_exc = DBAPIError("stmt", {}, Exception("orig"))
        engine = _make_engine_connect_ctx(execute_side_effect=dbapi_exc)
        client.async_engine = engine

        with pytest.raises(DatabaseConnectionError) as exc_info:
            await ping_database()

        assert "connection_invalidated" in str(exc_info.value.details)

    async def test_sqlalchemy_error_raises_connection_error(self) -> None:
        engine = _make_engine_connect_ctx(
            execute_side_effect=SQLAlchemyError("query failed"),
        )
        client.async_engine = engine

        with pytest.raises(DatabaseConnectionError) as exc_info:
            await ping_database()

        assert exc_info.value.cause is not None


# ---------------------------------------------------------------------------
# init -> close lifecycle round trip
# ---------------------------------------------------------------------------


class TestLifecycleRoundTrip:
    async def test_init_then_close(self) -> None:
        settings = make_settings()
        engine = MagicMock()
        engine.dispose = AsyncMock()
        factory = MagicMock()

        with (
            patch("database.client.create_async_engine", return_value=engine),
            patch("database.client.async_sessionmaker", return_value=factory),
        ):
            init_db_client(settings)
            assert is_db_client_initialized() is True

            await close_db_client()

        engine.dispose.assert_awaited_once()
        assert is_db_client_initialized() is False

    async def test_reinit_allowed_after_close(self) -> None:
        settings = make_settings()
        engine = MagicMock()
        engine.dispose = AsyncMock()
        factory = MagicMock()

        with (
            patch("database.client.create_async_engine", return_value=engine),
            patch("database.client.async_sessionmaker", return_value=factory),
        ):
            init_db_client(settings)
            await close_db_client()
            # Не должно выбрасывать ошибку «уже инициализирован».
            init_db_client(settings)
            assert is_db_client_initialized() is True
