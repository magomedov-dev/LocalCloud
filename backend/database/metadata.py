from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import MetaData, Table

# Импорты ниже нужны не ради прямого использования классов в этом файле,
# а для регистрации всех таблиц в Base.metadata.
#
# Если не импортировать модели до обращения к metadata, SQLAlchemy может
# не знать о части таблиц, и Alembic autogenerate создаст неполную миграцию.
from database.models import audit as _audit_models  # noqa: F401
from database.models import filesystem as _filesystem_models  # noqa: F401
from database.models import links as _links_models  # noqa: F401
from database.models import permissions as _permissions_models  # noqa: F401
from database.models import quotas as _quotas_models  # noqa: F401
from database.models import registration as _registration_models  # noqa: F401
from database.models import roles as _roles_models  # noqa: F401
from database.models import tasks as _tasks_models  # noqa: F401
from database.models import tokens as _tokens_models  # noqa: F401
from database.models import uploads as _uploads_models  # noqa: F401
from database.models import users as _users_models  # noqa: F401
from database.models.base import NAMING_CONVENTION, Base

db_metadata: MetaData = Base.metadata
metadata: MetaData = db_metadata


def get_metadata() -> MetaData:
    """Возвращает единую SQLAlchemy metadata приложения.

    Используется в:
        - `migrations/env.py`;
        - тестах;
        - диагностических командах;
        - инфраструктурных функциях создания или удаления схемы.

    Returns:
        Единый объект `MetaData` приложения.
    """

    return db_metadata


def get_naming_convention() -> dict[str, str]:
    """Возвращает naming convention для ограничений и индексов.

    Naming convention важен для стабильной генерации Alembic-миграций.

    Returns:
        Копия словаря с правилами именования ограничений и индексов.
    """

    return dict(NAMING_CONVENTION)


def get_table_names(
    *,
    sorted_: bool = True,
) -> list[str]:
    """Возвращает имена таблиц, зарегистрированных в metadata.

    Args:
        sorted_: Если `True`, возвращает имена таблиц в алфавитном порядке.

    Returns:
        Список имён таблиц.
    """

    table_names = list(db_metadata.tables.keys())

    if sorted_:
        table_names.sort()

    return table_names


def get_tables(
    *,
    sorted_: bool = False,
) -> list[Table]:
    """Возвращает SQLAlchemy `Table`-объекты.

    Args:
        sorted_: Если `True`, возвращает таблицы в порядке зависимостей
            SQLAlchemy. Это полезно при создании схемы через
            `metadata.create_all`.

    Returns:
        Список объектов `Table`.
    """

    if sorted_:
        return list(db_metadata.sorted_tables)

    return list(db_metadata.tables.values())


def get_table(table_name: str) -> Table:
    """Возвращает таблицу по имени.

    Args:
        table_name: Имя таблицы.

    Returns:
        Объект `Table` с указанным именем.

    Raises:
        KeyError: Если таблица с таким именем не зарегистрирована в metadata.
    """

    return db_metadata.tables[table_name]


def has_table(table_name: str) -> bool:
    """Проверяет, зарегистрирована ли таблица в metadata.

    Args:
        table_name: Имя таблицы.

    Returns:
        `True`, если таблица зарегистрирована в metadata, иначе `False`.
    """

    return table_name in db_metadata.tables


def require_tables(table_names: Iterable[str]) -> None:
    """Проверяет, что указанные таблицы зарегистрированы в metadata.

    Args:
        table_names: Имена таблиц, наличие которых нужно проверить.

    Raises:
        RuntimeError: Если одна или несколько таблиц отсутствуют.
    """

    missing_tables = [
        table_name for table_name in table_names if table_name not in db_metadata.tables
    ]

    if missing_tables:
        raise RuntimeError(
            "В SQLAlchemy metadata отсутствуют обязательные таблицы: "
            + ", ".join(sorted(missing_tables))
        )


def get_metadata_summary() -> dict[str, Any]:
    """Возвращает краткую диагностическую информацию о metadata.

    Метод полезен для логирования при старте приложения, health-check
    или отладочных CLI-команд.

    Returns:
        Словарь с количеством таблиц, списком таблиц и naming convention.
    """

    table_names = get_table_names(sorted_=True)

    return {
        "tables_count": len(table_names),
        "tables": table_names,
        "naming_convention": get_naming_convention(),
    }


def clear_metadata() -> None:
    """Очищает metadata.

    В обычном приложении этот метод использовать не нужно. Он может быть
    полезен только в изолированных тестах или при динамической пересборке
    моделей.

    Важно:
        После очистки metadata таблицы моделей перестанут быть доступны
        до повторного импорта или инициализации моделей.
    """

    db_metadata.clear()
