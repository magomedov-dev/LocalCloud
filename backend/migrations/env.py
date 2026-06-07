from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from core.config import get_settings
from database.metadata import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def get_database_url() -> str:
    """Возвращает URL подключения к базе данных.

    URL берётся из настроек приложения, а не из статического значения
    "sqlalchemy.url" в alembic.ini. Это позволяет использовать единый источник
    конфигурации для приложения и миграций.

    Returns:
        Строка подключения к базе данных.
    """

    settings = get_settings()
    return settings.database.database_url


def run_migrations_offline() -> None:
    """Запускает миграции Alembic в offline-режиме.

    В offline-режиме Alembic не создаёт подключение к базе данных. Вместо этого
    он генерирует SQL-выражения на основе URL подключения и переданной metadata.

    Используется, когда "context.is_offline_mode()" возвращает True.
    """

    url = get_database_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Выполняет миграции Alembic через синхронное подключение SQLAlchemy.

    Функция вызывается внутри "AsyncConnection.run_sync()", потому что Alembic
    работает с синхронным объектом Connection даже при использовании
    асинхронного SQLAlchemy engine.

    Args:
        connection: Синхронное подключение SQLAlchemy, через которое Alembic
            выполняет миграции.
    """

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Запускает миграции Alembic в online-режиме.

    В online-режиме создаётся асинхронный SQLAlchemy engine, открывается
    подключение к базе данных, после чего миграции выполняются через
    синхронный адаптер "connection.run_sync()".

    URL подключения подставляется из настроек приложения в секцию конфигурации
    Alembic перед созданием engine.
    """

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
