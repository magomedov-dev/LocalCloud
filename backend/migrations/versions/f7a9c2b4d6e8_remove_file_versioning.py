"""Удаление функционала версионирования файлов.

Удаляет таблицу ``file_versions`` и колонку ``files.current_version_id``.
Реальный объект файла всегда хранится по ключу ``files.storage_key``, поэтому
удаление версий не затрагивает доступность файлов.

Revision ID: f7a9c2b4d6e8
Revises: e6f8a1b3c4d5
Create Date: 2026-06-10

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a9c2b4d6e8"
down_revision: Union[str, Sequence[str], None] = "e6f8a1b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применяет изменение схемы базы данных.

    Удаляет внешний ключ и колонку ``files.current_version_id``, затем
    удаляет таблицу ``file_versions`` со всеми её индексами.

    Raises:
        SQLAlchemyError: Если база данных не может выполнить одну из операций.
    """

    # DROP COLUMN каскадно удаляет внешний ключ и индекс на колонке, а
    # DROP TABLE — собственные индексы таблицы; явные имена не нужны (и могут
    # отличаться в зависимости от naming convention).
    op.drop_column("files", "current_version_id")
    op.drop_table("file_versions")


def downgrade() -> None:
    """Откатывает изменение схемы базы данных.

    Best-effort: воссоздаёт таблицу ``file_versions`` и колонку
    ``files.current_version_id``. Данные версий не восстанавливаются.

    Raises:
        SQLAlchemyError: Если база данных не может выполнить одну из операций.
    """

    op.create_table(
        "file_versions",
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "archived",
                "deleted",
                name="file_version_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("storage_bucket", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("checksum_algorithm", sa.String(length=32), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("change_comment", sa.Text(), nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name=op.f("ck_file_versions_ck_file_versions_size_bytes_non_negative"),
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name=op.f("ck_file_versions_ck_file_versions_version_number_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_file_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_file_versions_file_id_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_versions")),
        sa.UniqueConstraint(
            "file_id",
            "version_number",
            name="uq_file_versions_file_id_version_number",
        ),
        sa.UniqueConstraint("storage_key", name="uq_file_versions_storage_key"),
    )
    op.create_index(
        "ix_file_versions_file_created_at",
        "file_versions",
        ["file_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_file_versions_file_current",
        "file_versions",
        ["file_id", "is_current"],
        unique=False,
    )
    op.create_index(
        "ix_file_versions_file_id", "file_versions", ["file_id"], unique=False
    )
    op.create_index(
        "ix_file_versions_status", "file_versions", ["status"], unique=False
    )
    op.create_index(
        "ix_file_versions_storage_bucket_key",
        "file_versions",
        ["storage_bucket", "storage_key"],
        unique=False,
    )

    op.add_column(
        "files",
        sa.Column("current_version_id", sa.UUID(), nullable=True),
    )
    op.create_index(
        "ix_files_current_version_id",
        "files",
        ["current_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_files_current_version_id",
        "files",
        "file_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
