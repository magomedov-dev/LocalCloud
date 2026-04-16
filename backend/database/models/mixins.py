from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    """Mixin с UUID-первичным ключом.

    Добавляет колонку `id`, которая используется как первичный ключ ORM-модели.
    Значение UUID генерируется автоматически при создании объекта.

    Attributes:
        id: Уникальный идентификатор записи.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )


class TimestampMixin:
    """Mixin с временными метками создания и обновления.

    Добавляет поля `created_at` и `updated_at`. Время создания устанавливается
    на уровне базы данных, а время обновления автоматически изменяется при
    обновлении записи.

    Attributes:
        created_at: Дата и время создания записи.
        updated_at: Дата и время последнего обновления записи.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CreatedAtMixin:
    """Mixin с временной меткой создания.

    Добавляет поле `created_at`, которое устанавливается на уровне базы данных
    при создании записи.

    Attributes:
        created_at: Дата и время создания записи.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin с полями для мягкого удаления.

    Добавляет признак удаления и дату удаления. Мягкое удаление позволяет
    скрывать объект из активных выборок без физического удаления записи
    из базы данных.

    Attributes:
        is_deleted: Признак мягкого удаления записи.
        deleted_at: Дата и время мягкого удаления записи.
    """

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
