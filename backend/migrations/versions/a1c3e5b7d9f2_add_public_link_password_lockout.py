"""Добавление счётчика неудачных паролей и блокировки публичных ссылок.

Идентификатор ревизии: a1c3e5b7d9f2
Предыдущая ревизия: f7a9c2b4d6e8
Дата создания: 2026-06-11 00:00:00.000000

Revision ID: a1c3e5b7d9f2
Revises: f7a9c2b4d6e8
Create Date: 2026-06-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии, используемые Alembic.
revision: str = "a1c3e5b7d9f2"
down_revision: Union[str, Sequence[str], None] = "f7a9c2b4d6e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применяет изменение схемы базы данных.

    Добавляет в таблицу "public_links" колонки для защиты пароля ссылки от
    перебора: "failed_password_attempts" — счётчик подряд идущих неверных
    паролей, "password_locked_until" — момент, до которого проверки пароля
    блокируются после исчерпания попыток.

    Raises:
        SQLAlchemyError: Если база данных не может добавить колонки.
    """

    op.add_column(
        "public_links",
        sa.Column(
            "failed_password_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Число подряд идущих неверных паролей публичной ссылки.",
        ),
    )
    op.add_column(
        "public_links",
        sa.Column(
            "password_locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Момент, до которого проверки пароля ссылки заблокированы "
                "после исчерпания попыток."
            ),
        ),
    )


def downgrade() -> None:
    """Откатывает изменение схемы базы данных.

    Удаляет колонки "failed_password_attempts" и "password_locked_until"
    из таблицы "public_links".

    Raises:
        SQLAlchemyError: Если база данных не может удалить колонки.
    """

    op.drop_column("public_links", "password_locked_until")
    op.drop_column("public_links", "failed_password_attempts")
