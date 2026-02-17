from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Правила именования индексов и ограничений SQLAlchemy.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей.

    Предоставляет общую metadata SQLAlchemy, задаёт naming convention для
    индексов и ограничений, помогает Alembic корректно автогенерировать
    миграции и автоматически формирует имя таблицы из имени ORM-класса.

    Все ORM-модели проекта должны наследоваться от этого класса.

    Attributes:
        metadata: Общая metadata SQLAlchemy с правилами именования индексов,
            ограничений и внешних ключей.
    """

    metadata: ClassVar[MetaData] = MetaData(naming_convention=NAMING_CONVENTION)

    def to_dict(self) -> dict[str, Any]:
        """Преобразует экземпляр ORM-модели в словарь.

        Метод предназначен для внутренней отладки, логирования и тестов.
        Для HTTP-ответов следует использовать Pydantic-схемы, а не возвращать
        ORM-объекты напрямую.

        Returns:
            Словарь вида `{column_name: column_value}`, содержащий значения
            всех колонок текущей ORM-модели.
        """

        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }

    def __repr__(self) -> str:
        """Возвращает компактное отладочное представление ORM-объекта.

        Если у объекта есть атрибут `id`, включает его в строковое
        представление. В противном случае возвращает только имя класса модели.

        Returns:
            Строковое представление ORM-объекта.
        """

        model_name = self.__class__.__name__
        model_id = getattr(self, "id", None)

        if model_id is not None:
            return f"<{model_name}(id={model_id})>"

        return f"<{model_name}>"
