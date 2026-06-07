"""Добавление индекса для поиска активных узлов по родителю и имени.

Идентификатор ревизии: b3f1c2d4e5a6
Предыдущая ревизия: ac57ae7d7abd
Дата создания: 2026-05-28 00:00:00.000000

Revision ID: b3f1c2d4e5a6
Revises: ac57ae7d7abd
Create Date: 2026-05-28 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии, используемые Alembic.
revision: str = "b3f1c2d4e5a6"
down_revision: Union[str, Sequence[str], None] = "ac57ae7d7abd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применяет изменение схемы базы данных.

    Создаёт частичный индекс "ix_fsn_parent_active_name" для таблицы
    "file_system_nodes" по колонкам "parent_id" и "name".

    Индекс применяется только к активным узлам, у которых "is_deleted = false".
    Он ускоряет поиск неудалённых файлов и папок внутри конкретной родительской
    папки по имени.

    Raises:
        SQLAlchemyError: Если база данных не может создать индекс.
    """

    op.create_index(
        "ix_fsn_parent_active_name",
        "file_system_nodes",
        ["parent_id", "name"],
        unique=False,
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    """Откатывает изменение схемы базы данных.

    Удаляет частичный индекс "ix_fsn_parent_active_name" из таблицы
    "file_system_nodes".

    Используется Alembic при откате базы данных с ревизии "b3f1c2d4e5a6" на
    ревизию "ac57ae7d7abd".

    Raises:
        SQLAlchemyError: Если база данных не может удалить индекс.
    """

    op.drop_index(
        "ix_fsn_parent_active_name",
        table_name="file_system_nodes",
        postgresql_where=sa.text("is_deleted = false"),
    )
