"""Удаление колонки is_email_verified из таблицы users.

Идентификатор ревизии: d5e7f9a0b1c2
Предыдущая ревизия: c4d2e6f8a1b3
Дата создания: 2026-06-10 00:00:00.000000

Revision ID: d5e7f9a0b1c2
Revises: c4d2e6f8a1b3
Create Date: 2026-06-10 00:00:00.000000

Признак подтверждения email больше не используется в приложении, поэтому
соответствующая колонка `is_email_verified` удаляется из таблицы `users`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии, используемые Alembic.
revision: str = "d5e7f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c4d2e6f8a1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применяет изменение схемы базы данных.

    Удаляет колонку `is_email_verified` из таблицы `users`.

    Raises:
        SQLAlchemyError: Если база данных не может удалить колонку.
    """

    op.drop_column("users", "is_email_verified")


def downgrade() -> None:
    """Откатывает изменение схемы базы данных.

    Возвращает колонку `is_email_verified` в таблицу `users`.

    Raises:
        SQLAlchemyError: Если база данных не может добавить колонку.
    """

    op.add_column(
        "users",
        sa.Column(
            "is_email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
