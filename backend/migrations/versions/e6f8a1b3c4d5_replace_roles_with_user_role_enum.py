"""Замена таблиц ролей на enum-колонку users.role.

Идентификатор ревизии: e6f8a1b3c4d5
Предыдущая ревизия: d5e7f9a0b1c2
Дата создания: 2026-06-10 00:00:00.000000

Revision ID: e6f8a1b3c4d5
Revises: d5e7f9a0b1c2
Create Date: 2026-06-10 00:00:00.000000

Роль пользователя больше не хранится в таблицах `roles` и `user_roles`, а
переносится в единственную enum-колонку `users.role`. Миграция добавляет
колонку, переносит признак администратора из старой структуры и удаляет
таблицы `user_roles` и `roles`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Идентификаторы ревизии, используемые Alembic.
revision: str = "e6f8a1b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d5e7f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применяет изменение схемы базы данных.

    Добавляет enum-колонку `role` в таблицу `users`, переносит администраторов
    из таблиц `user_roles`/`roles` и удаляет эти таблицы.

    Raises:
        SQLAlchemyError: Если база данных не может выполнить одну из операций.
    """

    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.Enum(
                "admin",
                "user",
                name="user_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default="user",
            comment="Системная роль пользователя.",
        ),
    )

    op.execute(
        "UPDATE users SET role='admin' WHERE id IN ("
        "SELECT ur.user_id FROM user_roles ur "
        "JOIN roles r ON r.id = ur.role_id "
        "WHERE r.code = 'admin')"
    )

    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_index("ix_user_roles_assigned_by", table_name="user_roles")
    op.drop_index("ix_user_roles_assigned_at", table_name="user_roles")
    op.drop_table("user_roles")

    op.drop_index("ix_roles_name", table_name="roles")
    op.drop_index("ix_roles_is_system", table_name="roles")
    op.drop_index("ix_roles_is_active", table_name="roles")
    op.drop_index("ix_roles_created_at", table_name="roles")
    op.drop_index("ix_roles_code", table_name="roles")
    op.drop_table("roles")


def downgrade() -> None:
    """Откатывает изменение схемы базы данных.

    Воссоздаёт таблицы `roles` и `user_roles`, добавляет системные роли,
    переносит назначения ролей из колонки `users.role` и удаляет саму колонку.
    Это best-effort откат: служебные поля назначения (`assigned_by`,
    `assigned_at`) заполняются значениями по умолчанию.

    Raises:
        SQLAlchemyError: Если база данных не может выполнить одну из операций.
    """

    op.create_table(
        "roles",
        sa.Column(
            "name",
            sa.String(length=64),
            nullable=False,
            comment="Уникальное техническое имя роли.",
        ),
        sa.Column(
            "code",
            sa.String(length=64),
            nullable=False,
            comment="Стабильный код роли для бизнес-логики.",
        ),
        sa.Column(
            "display_name",
            sa.String(length=128),
            nullable=False,
            comment="Человекочитаемое имя роли.",
        ),
        sa.Column(
            "description",
            sa.String(length=512),
            nullable=True,
            comment="Описание назначения роли.",
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="Признак системной роли, которую нельзя удалить обычным способом.",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default="true",
            nullable=False,
            comment="Признак активности роли.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("code", name="uq_roles_code"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_index("ix_roles_code", "roles", ["code"], unique=False)
    op.create_index("ix_roles_created_at", "roles", ["created_at"], unique=False)
    op.create_index("ix_roles_is_active", "roles", ["is_active"], unique=False)
    op.create_index("ix_roles_is_system", "roles", ["is_system"], unique=False)
    op.create_index("ix_roles_name", "roles", ["name"], unique=False)

    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Пользователь, которому назначена роль.",
        ),
        sa.Column("role_id", sa.UUID(), nullable=False, comment="Назначенная роль."),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Дата и время назначения роли.",
        ),
        sa.Column(
            "assigned_by",
            sa.UUID(),
            nullable=True,
            comment="Администратор или системный пользователь, назначивший роль.",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["users.id"],
            name=op.f("fk_user_roles_assigned_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_user_roles_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_roles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_roles")),
        sa.UniqueConstraint(
            "user_id", "role_id", name="uq_user_roles_user_id_role_id"
        ),
    )
    op.create_index(
        "ix_user_roles_assigned_at", "user_roles", ["assigned_at"], unique=False
    )
    op.create_index(
        "ix_user_roles_assigned_by", "user_roles", ["assigned_by"], unique=False
    )
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"], unique=False)
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"], unique=False)

    # Воссоздаём системные роли.
    op.execute(
        "INSERT INTO roles "
        "(id, name, code, display_name, description, is_system, is_active, created_at) "
        "VALUES "
        "(gen_random_uuid(), 'admin', 'admin', 'Администратор', "
        "'Системная роль Администратор', true, true, now()), "
        "(gen_random_uuid(), 'user', 'user', 'Пользователь', "
        "'Системная роль Пользователь', true, true, now())"
    )

    # Переносим назначения ролей из колонки users.role.
    op.execute(
        "INSERT INTO user_roles (user_id, role_id, assigned_at, assigned_by) "
        "SELECT u.id, r.id, now(), NULL "
        "FROM users u JOIN roles r ON r.code = u.role"
    )

    op.drop_column("users", "role")
