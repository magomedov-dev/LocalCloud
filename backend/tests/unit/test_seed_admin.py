"""Unit-тесты для автономного скрипта инициализации ``seed_admin.py``.

Скрипт выполняет ``asyncio.run(main())`` во время импорта, поэтому каждый тест
импортирует модуль под полным набором патчей: ``asyncpg.connect`` подменяется
на ``AsyncMock`` (никаких реальных обращений к БД), а ``CryptContext.hash`` —
на детерминированную заглушку. Маршрутизация запросов определяется по тексту
SQL, передаваемому в ``fetchval``, что позволяет независимо имитировать ветки
"существует" и "отсутствует".
"""

from __future__ import annotations

import importlib
import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MODULE_NAME = "seed_admin"


class FetchvalRouter:
    """Маршрутизирует вызовы ``conn.fetchval`` к заготовленным ответам по SQL.

    Параметры отражают проверки существования, выполняемые скриптом. ``None``
    означает "строки нет" (срабатывает ветка INSERT); истинное значение —
    "существует" (срабатывает ветка пропуска).
    """

    def __init__(
        self,
        *,
        admin_user_exists: bool = False,
        quota_exists: bool = False,
    ) -> None:
        self.existing_admin_id = uuid.uuid4()
        self._flags = {
            "admin_user_exists": admin_user_exists,
            "quota_exists": quota_exists,
        }
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, sql: str, *args: Any) -> Any:
        self.calls.append((sql, *args))
        normalized = " ".join(sql.split())

        if "FROM users WHERE email=$1" in normalized:
            return (
                self.existing_admin_id
                if self._flags["admin_user_exists"]
                else None
            )
        if "FROM user_quotas WHERE user_id=$1" in normalized:
            return uuid.uuid4() if self._flags["quota_exists"] else None
        raise AssertionError(f"Unexpected fetchval SQL: {normalized!r}")


def _import_seed_admin(connection: AsyncMock) -> Any:
    """Импортирует (заново) ``seed_admin`` со всеми пропатченными зависимостями.

    Возвращает импортированный модуль. Именно ``asyncio.run(main())`` на уровне
    модуля запускает ``main()`` против ``connection``.
    """

    sys.modules.pop(MODULE_NAME, None)
    fake_ctx = MagicMock()
    fake_ctx.hash.return_value = "hashed-password"

    with (
        patch("asyncpg.connect", new=AsyncMock(return_value=connection)) as connect_mock,
        patch(
            "passlib.context.CryptContext.__init__", return_value=None
        ),
        patch("passlib.context.CryptContext.hash", return_value="hashed-password"),
    ):
        module = importlib.import_module(MODULE_NAME)
        module._connect_mock = connect_mock  # type: ignore[attr-defined]
    return module


def make_connection(router: FetchvalRouter) -> AsyncMock:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=router)
    conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    return conn


def _executed_sql(conn: AsyncMock) -> list[str]:
    return [" ".join(call.args[0].split()) for call in conn.execute.await_args_list]


@pytest.fixture(autouse=True)
def _cleanup_module() -> Any:
    """Поддерживает чистоту таблицы модулей до и после каждого теста."""

    sys.modules.pop(MODULE_NAME, None)
    yield
    sys.modules.pop(MODULE_NAME, None)


def test_fresh_database_creates_everything(capsys: pytest.CaptureFixture[str]) -> None:
    router = FetchvalRouter()  # пока ничего не существует
    conn = make_connection(router)

    _import_seed_admin(conn)

    sql = _executed_sql(conn)
    # Один пользователь + одна квота = 2 вставки.
    assert sum("INSERT INTO users" in s for s in sql) == 1
    assert sum("INSERT INTO user_quotas" in s for s in sql) == 1

    out = capsys.readouterr().out
    assert "Created admin user:" in out
    assert "Created default quota for admin" in out
    assert "=== Admin user ready ===" in out
    conn.close.assert_awaited_once()


def test_user_insert_uses_expected_fields() -> None:
    router = FetchvalRouter()
    conn = make_connection(router)

    module = _import_seed_admin(conn)

    # Находим INSERT в users и проверяем, что позиционные аргументы несут
    # заданную личность администратора + заглушку хеша пароля.
    user_calls = [
        call
        for call in conn.execute.await_args_list
        if "INSERT INTO users" in call.args[0]
    ]
    assert len(user_calls) == 1
    args = user_calls[0].args
    # args = (sql, admin_id, email, username, pw_hash, now)
    assert isinstance(args[1], uuid.UUID)
    assert args[2] == module.ADMIN_EMAIL
    assert args[3] == module.ADMIN_USERNAME
    assert args[4] == "hashed-password"


def test_user_insert_sets_admin_role() -> None:
    router = FetchvalRouter()
    conn = make_connection(router)

    _import_seed_admin(conn)

    user_sql = next(
        " ".join(call.args[0].split())
        for call in conn.execute.await_args_list
        if "INSERT INTO users" in call.args[0]
    )
    # Системная роль администратора задаётся прямо в значениях INSERT.
    assert "role" in user_sql
    assert "'admin'" in user_sql


def test_existing_admin_skips_user_insert(
    capsys: pytest.CaptureFixture[str],
) -> None:
    router = FetchvalRouter(
        admin_user_exists=True,
        quota_exists=True,
    )
    conn = make_connection(router)

    _import_seed_admin(conn)

    sql = _executed_sql(conn)
    # Всё уже существует -> вообще нет операторов INSERT.
    assert sql == []

    out = capsys.readouterr().out
    assert "Admin user exists:" in out
    # Нет строк о создании.
    assert "Created admin user" not in out
    assert "Created default quota" not in out
    conn.close.assert_awaited_once()


def test_existing_admin_uses_existing_admin_id() -> None:
    router = FetchvalRouter(admin_user_exists=True)
    conn = make_connection(router)

    _import_seed_admin(conn)

    # Проверка существования квоты опирается на id *существующего* администратора.
    quota_checks = [
        call
        for call in conn.fetchval.await_args_list
        if "FROM user_quotas WHERE user_id=$1" in call.args[0]
    ]
    assert quota_checks, "expected a user_quotas existence check"
    assert quota_checks[0].args[1] == router.existing_admin_id


def test_quota_created_when_missing(capsys: pytest.CaptureFixture[str]) -> None:
    router = FetchvalRouter(
        admin_user_exists=True,
        quota_exists=False,
    )
    conn = make_connection(router)

    _import_seed_admin(conn)

    sql = _executed_sql(conn)
    assert any("INSERT INTO user_quotas" in s for s in sql)
    assert "Created default quota for admin" in capsys.readouterr().out


def test_connection_closed_on_query_error() -> None:
    """Блок ``finally`` должен закрывать соединение даже при ошибке."""

    router = FetchvalRouter()
    conn = make_connection(router)
    boom = RuntimeError("query exploded")
    conn.fetchval = AsyncMock(side_effect=boom)

    with pytest.raises(RuntimeError, match="query exploded"):
        _import_seed_admin(conn)

    conn.close.assert_awaited_once()


def test_connect_invoked_with_dsn() -> None:
    router = FetchvalRouter()
    conn = make_connection(router)

    module = _import_seed_admin(conn)

    module._connect_mock.assert_awaited_once_with(module.DB_DSN)


def test_idempotent_second_run_is_a_pure_skip(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Первый запуск создаёт; второй против уже заполненной БД ничего не делает."""

    # Первый запуск: пустая БД.
    first_conn = make_connection(FetchvalRouter())
    _import_seed_admin(first_conn)
    capsys.readouterr()  # отбрасываем вывод первого запуска

    # Второй запуск: всё уже существует -> вставок нет.
    second_conn = make_connection(
        FetchvalRouter(
            admin_user_exists=True,
            quota_exists=True,
        )
    )
    _import_seed_admin(second_conn)

    assert _executed_sql(second_conn) == []
