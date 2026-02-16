"""Начальная схема базы данных.

Идентификатор ревизии: ac57ae7d7abd
Предыдущая ревизия:
Дата создания: 2026-05-23 17:33:59.973911

Миграция создаёт базовую структуру базы данных приложения:
таблицы пользователей, ролей, файловой системы, файлов, папок, прав доступа,
публичных ссылок, корзины, upload-сессий, фоновых задач, аудита и связанных
служебных сущностей.

Revision ID: ac57ae7d7abd
Revises:
Create Date: 2026-05-23 17:33:59.973911

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Идентификаторы ревизии, используемые Alembic.
revision: str = "ac57ae7d7abd"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применяет начальную схему базы данных.

    Создаёт все таблицы, ограничения, внешние ключи и индексы, необходимые для
    работы базовой версии приложения.

    В миграции создаются:
        - роли и связи пользователей с ролями;
        - пользователи и заявки на регистрацию;
        - refresh-токены пользовательских сессий;
        - узлы файловой системы, файлы, папки и версии файлов;
        - права доступа к узлам и публичные ссылки;
        - элементы корзины;
        - upload-сессии и части multipart-загрузок;
        - пользовательские квоты;
        - фоновые задачи;
        - журнал аудита.

    Raises:
        SQLAlchemyError: Если база данных не может выполнить одну из операций
            создания схемы.
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
        "users",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            comment="Уникальный идентификатор пользователя.",
        ),
        sa.Column(
            "email",
            sa.String(length=320),
            nullable=False,
            comment="Адрес электронной почты пользователя.",
        ),
        sa.Column(
            "username",
            sa.String(length=64),
            nullable=False,
            comment="Уникальное имя пользователя, отображаемое в системе.",
        ),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
            comment="Хэшированный пароль пользователя.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "active",
                "blocked",
                "rejected",
                "deleted",
                name="user_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
            comment="Текущий статус учётной записи.",
        ),
        sa.Column(
            "is_email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Признак подтверждения адреса электронной почты.",
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время последнего успешного входа в систему.",
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время одобрения регистрации пользователя.",
        ),
        sa.Column(
            "blocked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время блокировки пользователя.",
        ),
        sa.Column(
            "rejected_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время отклонения регистрации пользователя.",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время логического удаления пользователя.",
        ),
        sa.Column(
            "block_reason",
            sa.String(length=512),
            nullable=True,
            comment="Причина блокировки пользователя.",
        ),
        sa.Column(
            "rejection_reason",
            sa.String(length=512),
            nullable=True,
            comment="Причина отклонения регистрации пользователя.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_email_status", "users", ["email", "status"], unique=False)
    op.create_index("ix_users_last_login_at", "users", ["last_login_at"], unique=False)
    op.create_index(
        "ix_users_status_created_at", "users", ["status", "created_at"], unique=False
    )
    op.create_index(
        "ix_users_username_status", "users", ["username", "status"], unique=False
    )
    op.create_table(
        "audit_logs",
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, выполнивший действие. None означает системное действие.",
        ),
        sa.Column(
            "action",
            sa.Enum(
                "user.login",
                "user.logout",
                "user.login_failed",
                "user.refresh_token_rotated",
                "user.session_revoked",
                "user.created",
                "user.updated",
                "user.blocked",
                "user.unblocked",
                "user.deleted",
                "user.role_assigned",
                "user.role_removed",
                "registration.request_created",
                "registration.request_approved",
                "registration.request_rejected",
                "registration.request_cancelled",
                "folder.created",
                "folder.renamed",
                "folder.moved",
                "folder.deleted",
                "folder.restored",
                "folder.purged",
                "folder.archive_requested",
                "folder.archive_created",
                "file.upload_started",
                "file.uploaded",
                "file.upload_failed",
                "file.downloaded",
                "file.renamed",
                "file.moved",
                "file.updated",
                "file.deleted",
                "file.restored",
                "file.purged",
                "file.version_created",
                "file.version_restored",
                "file.preview_generated",
                "node.created",
                "node.renamed",
                "node.moved",
                "node.deleted",
                "node.restored",
                "node.purged",
                "permission.granted",
                "permission.updated",
                "permission.revoked",
                "public_link.created",
                "public_link.opened",
                "public_link.downloaded",
                "public_link.revoked",
                "public_link.expired",
                "upload_session.created",
                "upload_session.completed",
                "upload_session.failed",
                "upload_session.aborted",
                "upload_session.expired",
                "quota.created",
                "quota.updated",
                "quota.exceeded",
                "quota.recalculated",
                "background_task.created",
                "background_task.started",
                "background_task.completed",
                "background_task.failed",
                "background_task.cancelled",
                "storage.object_deleted",
                "storage.object_delete_failed",
                "storage.integrity_check_started",
                "storage.integrity_check_completed",
                "storage.integrity_problem_found",
                "backup.started",
                "backup.completed",
                "backup.failed",
                "security.permission_denied",
                "security.suspicious_activity",
                "security.public_link_password_failed",
                name="audit_action",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            comment="Тип действия, выполненного в системе.",
        ),
        sa.Column(
            "result",
            sa.Enum(
                "success",
                "failure",
                "denied",
                "warning",
                name="audit_result",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="success",
            nullable=False,
            comment="Результат выполнения действия.",
        ),
        sa.Column(
            "entity_type",
            sa.String(length=128),
            nullable=True,
            comment="Тип сущности, затронутой действием.",
        ),
        sa.Column(
            "entity_id",
            sa.UUID(),
            nullable=True,
            comment="Идентификатор затронутой сущности.",
        ),
        sa.Column(
            "resource_type",
            sa.Enum(
                "user",
                "role",
                "registration_request",
                "session",
                "file",
                "folder",
                "node",
                "upload_session",
                "public_link",
                "permission",
                "quota",
                "background_task",
                "storage_object",
                "system",
                name="audit_resource_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
            comment="Нормализованный тип ресурса для фильтрации событий аудита.",
        ),
        sa.Column(
            "request_id",
            sa.String(length=128),
            nullable=True,
            comment="Идентификатор HTTP-запроса, в рамках которого создано событие.",
        ),
        sa.Column(
            "correlation_id",
            sa.String(length=128),
            nullable=True,
            comment="Идентификатор корреляции для связывания нескольких событий.",
        ),
        sa.Column(
            "ip_address",
            postgresql.INET(),
            nullable=True,
            comment="IP-адрес, с которого было выполнено действие.",
        ),
        sa.Column(
            "user_agent",
            sa.Text(),
            nullable=True,
            comment="User-Agent клиента, выполнившего действие.",
        ),
        sa.Column(
            "message",
            sa.Text(),
            nullable=True,
            comment="Краткое человекочитаемое описание события.",
        ),
        sa.Column(
            "error_code",
            sa.String(length=128),
            nullable=True,
            comment="Машиночитаемый код ошибки, если действие завершилось неуспешно.",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Дополнительные структурированные данные события аудита.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index(
        "ix_audit_logs_action_created_at",
        "audit_logs",
        ["action", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"], unique=False
    )
    op.create_index(
        "ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False
    )
    op.create_index(
        "ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"], unique=False
    )
    op.create_index(
        "ix_audit_logs_entity_created_at",
        "audit_logs",
        ["entity_type", "entity_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_entity_id", "audit_logs", ["entity_id"], unique=False
    )
    op.create_index(
        "ix_audit_logs_entity_type", "audit_logs", ["entity_type"], unique=False
    )
    op.create_index(
        "ix_audit_logs_ip_address", "audit_logs", ["ip_address"], unique=False
    )
    op.create_index(
        "ix_audit_logs_metadata_gin",
        "audit_logs",
        ["metadata"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_audit_logs_request_id", "audit_logs", ["request_id"], unique=False
    )
    op.create_index("ix_audit_logs_result", "audit_logs", ["result"], unique=False)
    op.create_index(
        "ix_audit_logs_result_created_at",
        "audit_logs",
        ["result", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_user_action_created_at",
        "audit_logs",
        ["user_id", "action", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_user_created_at",
        "audit_logs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)
    op.create_table(
        "background_tasks",
        sa.Column(
            "task_type",
            sa.Enum(
                "create_folder_archive",
                "clean_trash",
                "clean_expired_uploads",
                "clean_expired_public_links",
                "delete_object_from_storage",
                "check_storage_integrity",
                "generate_file_preview",
                "recalculate_user_quota",
                "backup_database",
                "backup_storage",
                name="background_task_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            comment="Тип фоновой задачи.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="background_task_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
            comment="Текущий статус выполнения задачи.",
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "low",
                "normal",
                "high",
                "critical",
                name="task_priority",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="normal",
            nullable=False,
            comment="Приоритет выполнения задачи.",
        ),
        sa.Column(
            "created_by",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, инициировавший задачу. Null означает системную задачу.",
        ),
        sa.Column(
            "related_entity_type",
            sa.String(length=128),
            nullable=True,
            comment="Тип сущности, связанной с задачей.",
        ),
        sa.Column(
            "related_entity_id",
            sa.UUID(),
            nullable=True,
            comment="Идентификатор сущности, связанной с задачей.",
        ),
        sa.Column(
            "progress_percent",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Прогресс выполнения задачи от 0 до 100 процентов.",
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Входные параметры задачи.",
        ),
        sa.Column(
            "result_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Структурированные данные результата задачи.",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Сообщение об ошибке, если задача завершилась неудачно.",
        ),
        sa.Column(
            "error_code",
            sa.String(length=128),
            nullable=True,
            comment="Машиночитаемый код ошибки.",
        ),
        sa.Column(
            "attempts_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Количество выполненных попыток запуска задачи.",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="Максимальное количество попыток выполнения задачи.",
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=True,
            comment="Ключ идемпотентности для предотвращения дублирования задач.",
        ),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время, не раньше которого задача может быть запущена.",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время начала выполнения задачи.",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время завершения выполнения задачи.",
        ),
        sa.Column(
            "locked_by",
            sa.String(length=255),
            nullable=True,
            comment="Идентификатор worker-процесса, заблокировавшего задачу.",
        ),
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время окончания блокировки задачи worker-процессом.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\n            finished_at IS NULL\n            OR started_at IS NULL\n            OR finished_at >= started_at\n            ",
            name=op.f(
                "ck_background_tasks_ck_background_tasks_finished_at_gte_started_at"
            ),
        ),
        sa.CheckConstraint(
            "attempts_count <= max_attempts",
            name=op.f(
                "ck_background_tasks_ck_background_tasks_attempts_count_lte_max_attempts"
            ),
        ),
        sa.CheckConstraint(
            "attempts_count >= 0",
            name=op.f(
                "ck_background_tasks_ck_background_tasks_attempts_count_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "max_attempts > 0",
            name=op.f("ck_background_tasks_ck_background_tasks_max_attempts_positive"),
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name=op.f("ck_background_tasks_ck_background_tasks_progress_percent_range"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_background_tasks_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_tasks")),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_background_tasks_idempotency_key"
        ),
    )
    op.create_index(
        "ix_background_tasks_created_at",
        "background_tasks",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_created_by",
        "background_tasks",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_created_by_status",
        "background_tasks",
        ["created_by", "status"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_finished_at",
        "background_tasks",
        ["finished_at"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_idempotency_key",
        "background_tasks",
        ["idempotency_key"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_locked_until",
        "background_tasks",
        ["locked_until"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_payload_gin",
        "background_tasks",
        ["payload"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_background_tasks_priority", "background_tasks", ["priority"], unique=False
    )
    op.create_index(
        "ix_background_tasks_related_entity",
        "background_tasks",
        ["related_entity_type", "related_entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_result_data_gin",
        "background_tasks",
        ["result_data"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_background_tasks_scheduled_at",
        "background_tasks",
        ["scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_started_at",
        "background_tasks",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_status", "background_tasks", ["status"], unique=False
    )
    op.create_index(
        "ix_background_tasks_status_created_at",
        "background_tasks",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_status_priority_scheduled",
        "background_tasks",
        ["status", "priority", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_task_type", "background_tasks", ["task_type"], unique=False
    )
    op.create_index(
        "ix_background_tasks_type_status",
        "background_tasks",
        ["task_type", "status"],
        unique=False,
    )
    op.create_table(
        "file_system_nodes",
        sa.Column(
            "owner_id",
            sa.UUID(),
            nullable=False,
            comment="Пользователь, которому принадлежит узел файловой системы.",
        ),
        sa.Column(
            "parent_id",
            sa.UUID(),
            nullable=True,
            comment="Родительская папка. Null означает, что узел находится на корневом уровне.",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="Имя файла или папки, отображаемое пользователю.",
        ),
        sa.Column(
            "node_type",
            sa.Enum(
                "file",
                "folder",
                name="node_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            comment="Тип узла файловой системы.",
        ),
        sa.Column(
            "visibility",
            sa.Enum(
                "private",
                "shared",
                "public",
                name="node_visibility",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="private",
            nullable=False,
            comment="Видимость узла: private, shared или public.",
        ),
        sa.Column(
            "path",
            sa.Text(),
            nullable=False,
            comment="Материализованный логический путь узла.",
        ),
        sa.Column(
            "depth",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Глубина вложенности узла.",
        ),
        sa.Column(
            "created_by",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, создавший узел.",
        ),
        sa.Column(
            "updated_by",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, последним изменивший узел.",
        ),
        sa.Column(
            "deleted_by",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, удаливший узел.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "depth >= 0",
            name=op.f("ck_file_system_nodes_ck_file_system_nodes_depth_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_file_system_nodes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by"],
            ["users.id"],
            name=op.f("fk_file_system_nodes_deleted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_file_system_nodes_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["file_system_nodes.id"],
            name=op.f("fk_file_system_nodes_parent_id_file_system_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_file_system_nodes_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_system_nodes")),
    )
    op.create_index(
        "ix_file_system_nodes_created_at",
        "file_system_nodes",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_deleted_at",
        "file_system_nodes",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_is_deleted",
        "file_system_nodes",
        ["is_deleted"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_name", "file_system_nodes", ["name"], unique=False
    )
    op.create_index(
        "ix_file_system_nodes_node_type",
        "file_system_nodes",
        ["node_type"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_owner_deleted",
        "file_system_nodes",
        ["owner_id", "is_deleted"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_owner_id", "file_system_nodes", ["owner_id"], unique=False
    )
    op.create_index(
        "ix_file_system_nodes_owner_parent",
        "file_system_nodes",
        ["owner_id", "parent_id"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_owner_parent_name",
        "file_system_nodes",
        ["owner_id", "parent_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_owner_path",
        "file_system_nodes",
        ["owner_id", "path"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_owner_type_deleted",
        "file_system_nodes",
        ["owner_id", "node_type", "is_deleted"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_parent_deleted",
        "file_system_nodes",
        ["parent_id", "is_deleted"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_parent_id",
        "file_system_nodes",
        ["parent_id"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_updated_at",
        "file_system_nodes",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_file_system_nodes_visibility",
        "file_system_nodes",
        ["visibility"],
        unique=False,
    )
    op.create_index(
        "uq_file_system_nodes_active_name_in_parent",
        "file_system_nodes",
        ["owner_id", "parent_id", "name"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false AND parent_id IS NOT NULL"),
    )
    op.create_index(
        "uq_file_system_nodes_active_root_name",
        "file_system_nodes",
        ["owner_id", "name"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false AND parent_id IS NULL"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Пользователь, которому принадлежит refresh-токен.",
        ),
        sa.Column(
            "token_hash",
            sa.String(length=255),
            nullable=False,
            comment="Безопасный хэш refresh-токена.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "revoked",
                "expired",
                name="session_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="active",
            nullable=False,
            comment="Статус сессии, связанной с refresh-токеном.",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Дата и время истечения срока действия refresh-токена.",
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время явного отзыва refresh-токена.",
        ),
        sa.Column(
            "revoke_reason",
            sa.String(length=512),
            nullable=True,
            comment="Причина отзыва refresh-токена.",
        ),
        sa.Column(
            "replaced_by_token_id",
            sa.UUID(),
            nullable=True,
            comment="Новый refresh-токен, заменивший текущий при ротации.",
        ),
        sa.Column(
            "parent_token_id",
            sa.UUID(),
            nullable=True,
            comment="Предыдущий refresh-токен, из которого получен текущий.",
        ),
        sa.Column(
            "ip_address",
            postgresql.INET(),
            nullable=True,
            comment="IP-адрес, с которого был выдан refresh-токен.",
        ),
        sa.Column(
            "user_agent",
            sa.Text(),
            nullable=True,
            comment="User-Agent клиентского устройства или браузера.",
        ),
        sa.Column(
            "device_name",
            sa.String(length=255),
            nullable=True,
            comment="Условное имя устройства или клиента.",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="Признак активности refresh-токена.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_token_id"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_parent_token_id_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_token_id"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_token_id_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        "ix_refresh_tokens_active_expires_at",
        "refresh_tokens",
        ["is_active", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_refresh_tokens_created_at", "refresh_tokens", ["created_at"], unique=False
    )
    op.create_index(
        "ix_refresh_tokens_parent_token_id",
        "refresh_tokens",
        ["parent_token_id"],
        unique=False,
    )
    op.create_index(
        "ix_refresh_tokens_replaced_by_token_id",
        "refresh_tokens",
        ["replaced_by_token_id"],
        unique=False,
    )
    op.create_index(
        "ix_refresh_tokens_revoked_at", "refresh_tokens", ["revoked_at"], unique=False
    )
    op.create_index(
        "ix_refresh_tokens_status_expires_at",
        "refresh_tokens",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=False
    )
    op.create_index(
        "ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False
    )
    op.create_index(
        "ix_refresh_tokens_user_id_expires_at",
        "refresh_tokens",
        ["user_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_refresh_tokens_user_id_is_active",
        "refresh_tokens",
        ["user_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_refresh_tokens_user_id_status",
        "refresh_tokens",
        ["user_id", "status"],
        unique=False,
    )
    op.create_table(
        "registration_requests",
        sa.Column(
            "email",
            sa.String(length=320),
            nullable=False,
            comment="Адрес электронной почты, указанный в заявке.",
        ),
        sa.Column(
            "username",
            sa.String(length=64),
            nullable=False,
            comment="Имя пользователя, указанное в заявке.",
        ),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
            comment="Хэшированный пароль, указанный при регистрации.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "cancelled",
                name="registration_request_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
            comment="Текущий статус заявки на регистрацию.",
        ),
        sa.Column(
            "comment",
            sa.Text(),
            nullable=True,
            comment="Комментарий администратора при рассмотрении заявки.",
        ),
        sa.Column(
            "rejection_reason",
            sa.String(length=512),
            nullable=True,
            comment="Причина отклонения заявки.",
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время рассмотрения заявки.",
        ),
        sa.Column(
            "reviewed_by",
            sa.UUID(),
            nullable=True,
            comment="Администратор, рассмотревший заявку.",
        ),
        sa.Column(
            "created_user_id",
            sa.UUID(),
            nullable=True,
            comment="Учётная запись, созданная после одобрения заявки.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_user_id"],
            ["users.id"],
            name=op.f("fk_registration_requests_created_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name=op.f("fk_registration_requests_reviewed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_requests")),
    )
    op.create_index(
        "ix_registration_requests_created_user_id",
        "registration_requests",
        ["created_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_registration_requests_email_status",
        "registration_requests",
        ["email", "status"],
        unique=False,
    )
    op.create_index(
        "ix_registration_requests_reviewed_at",
        "registration_requests",
        ["reviewed_at"],
        unique=False,
    )
    op.create_index(
        "ix_registration_requests_reviewed_by",
        "registration_requests",
        ["reviewed_by"],
        unique=False,
    )
    op.create_index(
        "ix_registration_requests_status_created_at",
        "registration_requests",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_registration_requests_username_status",
        "registration_requests",
        ["username", "status"],
        unique=False,
    )
    op.create_index(
        "uq_registration_requests_pending_email",
        "registration_requests",
        ["email"],
        unique=True,
        postgresql_where="status = 'pending'",
    )
    op.create_index(
        "uq_registration_requests_pending_username",
        "registration_requests",
        ["username"],
        unique=True,
        postgresql_where="status = 'pending'",
    )
    op.create_table(
        "user_quotas",
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Пользователь, которому принадлежит квота.",
        ),
        sa.Column(
            "storage_limit_bytes",
            sa.BigInteger(),
            nullable=False,
            comment="Максимальный размер хранилища пользователя в байтах.",
        ),
        sa.Column(
            "storage_used_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
            comment="Текущий использованный объём хранилища в байтах.",
        ),
        sa.Column(
            "max_file_size_bytes",
            sa.BigInteger(),
            nullable=False,
            comment="Максимально допустимый размер одного файла в байтах.",
        ),
        sa.Column(
            "files_limit",
            sa.Integer(),
            nullable=True,
            comment="Максимальное количество файлов. Null означает отсутствие лимита.",
        ),
        sa.Column(
            "files_used",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Текущее количество файлов пользователя.",
        ),
        sa.Column(
            "public_links_limit",
            sa.Integer(),
            nullable=True,
            comment="Максимальное количество публичных ссылок. Null означает отсутствие лимита.",
        ),
        sa.Column(
            "public_links_used",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Текущее количество публичных ссылок пользователя.",
        ),
        sa.Column(
            "active_upload_sessions_limit",
            sa.Integer(),
            nullable=True,
            comment="Максимальное количество активных upload-сессий. Null означает отсутствие лимита.",
        ),
        sa.Column(
            "active_upload_sessions_used",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Текущее количество активных upload-сессий пользователя.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\n            active_upload_sessions_limit IS NULL\n            OR active_upload_sessions_used <= active_upload_sessions_limit\n            ",
            name=op.f(
                "ck_user_quotas_ck_user_quotas_active_upload_sessions_used_lte_limit"
            ),
        ),
        sa.CheckConstraint(
            "active_upload_sessions_limit IS NULL OR active_upload_sessions_limit >= 0",
            name=op.f(
                "ck_user_quotas_ck_user_quotas_active_upload_sessions_limit_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "active_upload_sessions_used >= 0",
            name=op.f(
                "ck_user_quotas_ck_user_quotas_active_upload_sessions_used_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "files_limit IS NULL OR files_limit >= 0",
            name=op.f("ck_user_quotas_ck_user_quotas_files_limit_non_negative"),
        ),
        sa.CheckConstraint(
            "files_limit IS NULL OR files_used <= files_limit",
            name=op.f("ck_user_quotas_ck_user_quotas_files_used_lte_limit"),
        ),
        sa.CheckConstraint(
            "files_used >= 0",
            name=op.f("ck_user_quotas_ck_user_quotas_files_used_non_negative"),
        ),
        sa.CheckConstraint(
            "max_file_size_bytes >= 0",
            name=op.f("ck_user_quotas_ck_user_quotas_max_file_size_bytes_non_negative"),
        ),
        sa.CheckConstraint(
            "public_links_limit IS NULL OR public_links_limit >= 0",
            name=op.f("ck_user_quotas_ck_user_quotas_public_links_limit_non_negative"),
        ),
        sa.CheckConstraint(
            "public_links_limit IS NULL OR public_links_used <= public_links_limit",
            name=op.f("ck_user_quotas_ck_user_quotas_public_links_used_lte_limit"),
        ),
        sa.CheckConstraint(
            "public_links_used >= 0",
            name=op.f("ck_user_quotas_ck_user_quotas_public_links_used_non_negative"),
        ),
        sa.CheckConstraint(
            "storage_limit_bytes >= 0",
            name=op.f("ck_user_quotas_ck_user_quotas_storage_limit_bytes_non_negative"),
        ),
        sa.CheckConstraint(
            "storage_used_bytes <= storage_limit_bytes",
            name=op.f("ck_user_quotas_ck_user_quotas_storage_used_lte_limit"),
        ),
        sa.CheckConstraint(
            "storage_used_bytes >= 0",
            name=op.f("ck_user_quotas_ck_user_quotas_storage_used_bytes_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_quotas_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_quotas")),
        sa.UniqueConstraint("user_id", name="uq_user_quotas_user_id"),
    )
    op.create_index(
        "ix_user_quotas_active_upload_sessions_used",
        "user_quotas",
        ["active_upload_sessions_used"],
        unique=False,
    )
    op.create_index(
        "ix_user_quotas_created_at", "user_quotas", ["created_at"], unique=False
    )
    op.create_index(
        "ix_user_quotas_files_used", "user_quotas", ["files_used"], unique=False
    )
    op.create_index(
        "ix_user_quotas_public_links_used",
        "user_quotas",
        ["public_links_used"],
        unique=False,
    )
    op.create_index(
        "ix_user_quotas_storage_limit_bytes",
        "user_quotas",
        ["storage_limit_bytes"],
        unique=False,
    )
    op.create_index(
        "ix_user_quotas_storage_used_bytes",
        "user_quotas",
        ["storage_used_bytes"],
        unique=False,
    )
    op.create_index(
        "ix_user_quotas_updated_at", "user_quotas", ["updated_at"], unique=False
    )
    op.create_index("ix_user_quotas_user_id", "user_quotas", ["user_id"], unique=False)
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
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_id_role_id"),
    )
    op.create_index(
        "ix_user_roles_assigned_at", "user_roles", ["assigned_at"], unique=False
    )
    op.create_index(
        "ix_user_roles_assigned_by", "user_roles", ["assigned_by"], unique=False
    )
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"], unique=False)
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"], unique=False)
    op.create_table(
        "files",
        sa.Column(
            "node_id",
            sa.UUID(),
            nullable=False,
            comment="Узел файловой системы, связанный с этим файлом.",
        ),
        sa.Column(
            "storage_bucket",
            sa.String(length=128),
            nullable=False,
            comment="Bucket MinIO/S3, в котором хранится объект файла.",
        ),
        sa.Column(
            "storage_key",
            sa.Text(),
            nullable=False,
            comment="Ключ объекта MinIO/S3 для текущего содержимого файла.",
        ),
        sa.Column(
            "size_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
            comment="Размер файла в байтах.",
        ),
        sa.Column(
            "mime_type", sa.String(length=255), nullable=True, comment="MIME-тип файла."
        ),
        sa.Column(
            "extension",
            sa.String(length=32),
            nullable=True,
            comment="Расширение файла без ведущей точки.",
        ),
        sa.Column(
            "checksum",
            sa.String(length=128),
            nullable=True,
            comment="Контрольная сумма файла.",
        ),
        sa.Column(
            "checksum_algorithm",
            sa.String(length=32),
            nullable=True,
            comment="Алгоритм контрольной суммы, например sha256.",
        ),
        sa.Column(
            "storage_status",
            sa.Enum(
                "pending",
                "available",
                "missing",
                "corrupted",
                "deleting",
                "deleted",
                name="storage_object_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="available",
            nullable=False,
            comment="Статус физического объекта в MinIO/S3.",
        ),
        sa.Column(
            "processing_status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "failed",
                name="file_processing_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="ready",
            nullable=False,
            comment="Статус постобработки файла.",
        ),
        sa.Column(
            "preview_status",
            sa.Enum(
                "not_required",
                "pending",
                "generating",
                "ready",
                "failed",
                name="file_preview_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="not_required",
            nullable=False,
            comment="Статус генерации предпросмотра.",
        ),
        sa.Column(
            "preview_storage_key",
            sa.Text(),
            nullable=True,
            comment="Ключ объекта предпросмотра в MinIO/S3.",
        ),
        sa.Column(
            "current_version_id",
            sa.UUID(),
            nullable=True,
            comment="Текущая активная версия файла.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_files_ck_files_size_bytes_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["current_version_id"],
            ["file_versions.id"],
            name="fk_files_current_version_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["file_system_nodes.id"],
            name=op.f("fk_files_node_id_file_system_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("node_id", name="uq_files_node_id"),
        sa.UniqueConstraint("storage_key", name="uq_files_storage_key"),
    )
    op.create_index(
        "ix_files_checksum_algorithm_checksum",
        "files",
        ["checksum_algorithm", "checksum"],
        unique=False,
    )
    op.create_index("ix_files_created_at", "files", ["created_at"], unique=False)
    op.create_index(
        "ix_files_current_version_id", "files", ["current_version_id"], unique=False
    )
    op.create_index(
        "ix_files_extension_mime_type",
        "files",
        ["extension", "mime_type"],
        unique=False,
    )
    op.create_index("ix_files_node_id", "files", ["node_id"], unique=False)
    op.create_index(
        "ix_files_preview_status", "files", ["preview_status"], unique=False
    )
    op.create_index(
        "ix_files_processing_status", "files", ["processing_status"], unique=False
    )
    op.create_index(
        "ix_files_storage_bucket_key",
        "files",
        ["storage_bucket", "storage_key"],
        unique=False,
    )
    op.create_index(
        "ix_files_storage_status", "files", ["storage_status"], unique=False
    )
    op.create_index("ix_files_updated_at", "files", ["updated_at"], unique=False)
    op.create_table(
        "folders",
        sa.Column(
            "node_id",
            sa.UUID(),
            nullable=False,
            comment="Узел файловой системы, связанный с этой папкой.",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
            comment="Необязательное описание папки.",
        ),
        sa.Column(
            "color",
            sa.String(length=32),
            nullable=True,
            comment="Цветовая метка папки в интерфейсе.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["file_system_nodes.id"],
            name=op.f("fk_folders_node_id_file_system_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_folders")),
        sa.UniqueConstraint("node_id", name="uq_folders_node_id"),
    )
    op.create_index("ix_folders_created_at", "folders", ["created_at"], unique=False)
    op.create_index("ix_folders_node_id", "folders", ["node_id"], unique=False)
    op.create_index("ix_folders_updated_at", "folders", ["updated_at"], unique=False)
    op.create_table(
        "node_permissions",
        sa.Column(
            "node_id",
            sa.UUID(),
            nullable=False,
            comment="Узел файловой системы, для которого выданы разрешения.",
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Пользователь, получающий разрешение доступа.",
        ),
        sa.Column(
            "subject_type",
            sa.Enum(
                "user",
                "role",
                "public_link",
                name="permission_subject_type",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="user",
            nullable=False,
            comment="Тип субъекта доступа. Для этой таблицы обычно используется user.",
        ),
        sa.Column(
            "permission_level",
            sa.Enum(
                "read",
                "download",
                "write",
                "delete",
                "owner",
                name="permission_level",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="read",
            nullable=False,
            comment="Обобщённый уровень доступа.",
        ),
        sa.Column(
            "granted_by",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, предоставивший разрешение.",
        ),
        sa.Column(
            "can_read",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="Разрешает просмотр метаданных узла и содержимого папки.",
        ),
        sa.Column(
            "can_download",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Разрешает скачивание файла или архива папки.",
        ),
        sa.Column(
            "can_write",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Разрешает изменение, переименование или загрузку в узел.",
        ),
        sa.Column(
            "can_delete",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Разрешает перемещение узла в корзину или окончательное удаление.",
        ),
        sa.Column(
            "can_share",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Разрешает выдачу разрешений и создание публичных ссылок.",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время истечения срока действия разрешения.",
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время отзыва разрешения.",
        ),
        sa.Column(
            "revoke_reason",
            sa.String(length=512),
            nullable=True,
            comment="Причина отзыва разрешения.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name=op.f("fk_node_permissions_granted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["file_system_nodes.id"],
            name=op.f("fk_node_permissions_node_id_file_system_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_node_permissions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_node_permissions")),
        sa.UniqueConstraint(
            "node_id", "user_id", name="uq_node_permissions_node_id_user_id"
        ),
    )
    op.create_index(
        "ix_node_permissions_created_at",
        "node_permissions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_expires_at",
        "node_permissions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_granted_by",
        "node_permissions",
        ["granted_by"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_granted_by_created_at",
        "node_permissions",
        ["granted_by", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_node_active",
        "node_permissions",
        ["node_id", "revoked_at", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_node_id", "node_permissions", ["node_id"], unique=False
    )
    op.create_index(
        "ix_node_permissions_node_user",
        "node_permissions",
        ["node_id", "user_id"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_permission_level",
        "node_permissions",
        ["permission_level"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_revoked_at",
        "node_permissions",
        ["revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_subject_type",
        "node_permissions",
        ["subject_type"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_user_active",
        "node_permissions",
        ["user_id", "revoked_at", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_node_permissions_user_id", "node_permissions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_node_permissions_user_node",
        "node_permissions",
        ["user_id", "node_id"],
        unique=False,
    )
    op.create_table(
        "public_links",
        sa.Column(
            "node_id",
            sa.UUID(),
            nullable=False,
            comment="Узел файловой системы, доступ к которому предоставлен ссылкой.",
        ),
        sa.Column(
            "created_by",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, создавший публичную ссылку.",
        ),
        sa.Column(
            "token",
            sa.String(length=128),
            nullable=False,
            comment="Уникальный публичный токен ссылки.",
        ),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=True,
            comment="Хэш пароля публичной ссылки. Открытый пароль не хранится.",
        ),
        sa.Column(
            "permission_type",
            sa.Enum(
                "view",
                "download",
                "upload",
                name="public_link_permission_type",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="download",
            nullable=False,
            comment="Тип доступа, предоставляемый публичной ссылкой.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "disabled",
                "expired",
                "revoked",
                name="public_link_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="active",
            nullable=False,
            comment="Статус публичной ссылки.",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время истечения срока действия публичной ссылки.",
        ),
        sa.Column(
            "max_downloads",
            sa.Integer(),
            nullable=True,
            comment="Максимальное количество скачиваний. Null означает без лимита.",
        ),
        sa.Column(
            "download_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Текущее количество скачиваний по публичной ссылке.",
        ),
        sa.Column(
            "view_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Количество просмотров публичной ссылки.",
        ),
        sa.Column(
            "upload_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Количество загрузок через публичную ссылку.",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="Признак активности публичной ссылки.",
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время отзыва публичной ссылки.",
        ),
        sa.Column(
            "revoked_by",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, отозвавший публичную ссылку.",
        ),
        sa.Column(
            "revoke_reason",
            sa.String(length=512),
            nullable=True,
            comment="Причина отзыва публичной ссылки.",
        ),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время последнего обращения к публичной ссылке.",
        ),
        sa.Column(
            "last_downloaded_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время последнего скачивания по публичной ссылке.",
        ),
        sa.Column(
            "last_uploaded_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время последней загрузки через публичную ссылку.",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
            comment="Необязательное описание публичной ссылки.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "download_count >= 0",
            name=op.f("ck_public_links_ck_public_links_download_count_non_negative"),
        ),
        sa.CheckConstraint(
            "max_downloads IS NULL OR download_count <= max_downloads",
            name=op.f(
                "ck_public_links_ck_public_links_download_count_lte_max_downloads"
            ),
        ),
        sa.CheckConstraint(
            "max_downloads IS NULL OR max_downloads >= 0",
            name=op.f("ck_public_links_ck_public_links_max_downloads_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_public_links_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["file_system_nodes.id"],
            name=op.f("fk_public_links_node_id_file_system_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["users.id"],
            name=op.f("fk_public_links_revoked_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_public_links")),
        sa.UniqueConstraint("token", name="uq_public_links_token"),
    )
    op.create_index(
        "ix_public_links_created_at", "public_links", ["created_at"], unique=False
    )
    op.create_index(
        "ix_public_links_created_by", "public_links", ["created_by"], unique=False
    )
    op.create_index(
        "ix_public_links_created_by_active",
        "public_links",
        ["created_by", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_public_links_expires_at", "public_links", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_public_links_expires_at_active",
        "public_links",
        ["expires_at", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_public_links_is_active", "public_links", ["is_active"], unique=False
    )
    op.create_index(
        "ix_public_links_node_active",
        "public_links",
        ["node_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_public_links_node_id", "public_links", ["node_id"], unique=False
    )
    op.create_index(
        "ix_public_links_permission_type",
        "public_links",
        ["permission_type"],
        unique=False,
    )
    op.create_index(
        "ix_public_links_revoked_at", "public_links", ["revoked_at"], unique=False
    )
    op.create_index("ix_public_links_status", "public_links", ["status"], unique=False)
    op.create_index(
        "ix_public_links_status_expires_at",
        "public_links",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index("ix_public_links_token", "public_links", ["token"], unique=False)
    op.create_index(
        "ix_public_links_token_active",
        "public_links",
        ["token", "is_active"],
        unique=False,
    )
    op.create_table(
        "trash_items",
        sa.Column(
            "node_id",
            sa.UUID(),
            nullable=False,
            comment="Удалённый узел файловой системы.",
        ),
        sa.Column(
            "owner_id", sa.UUID(), nullable=False, comment="Владелец удалённого узла."
        ),
        sa.Column(
            "deleted_by",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, который переместил узел в корзину.",
        ),
        sa.Column(
            "original_parent_id",
            sa.UUID(),
            nullable=True,
            comment="Исходная родительская папка до удаления.",
        ),
        sa.Column(
            "original_path",
            sa.Text(),
            nullable=False,
            comment="Исходный логический путь до удаления.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "in_trash",
                "restored",
                "purged",
                name="trash_item_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="in_trash",
            nullable=False,
            comment="Статус элемента корзины.",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Дата и время перемещения узла в корзину.",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата, после которой элемент может быть окончательно удалён.",
        ),
        sa.Column(
            "restore_available",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="Признак возможности восстановления.",
        ),
        sa.Column(
            "purged_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время окончательного удаления.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["deleted_by"],
            ["users.id"],
            name=op.f("fk_trash_items_deleted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["file_system_nodes.id"],
            name=op.f("fk_trash_items_node_id_file_system_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["original_parent_id"],
            ["file_system_nodes.id"],
            name=op.f("fk_trash_items_original_parent_id_file_system_nodes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_trash_items_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trash_items")),
        sa.UniqueConstraint("node_id", name="uq_trash_items_node_id"),
    )
    op.create_index(
        "ix_trash_items_deleted_at", "trash_items", ["deleted_at"], unique=False
    )
    op.create_index(
        "ix_trash_items_deleted_by", "trash_items", ["deleted_by"], unique=False
    )
    op.create_index(
        "ix_trash_items_expires_at", "trash_items", ["expires_at"], unique=False
    )
    op.create_index("ix_trash_items_node_id", "trash_items", ["node_id"], unique=False)
    op.create_index(
        "ix_trash_items_original_parent_id",
        "trash_items",
        ["original_parent_id"],
        unique=False,
    )
    op.create_index(
        "ix_trash_items_owner_deleted_at",
        "trash_items",
        ["owner_id", "deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_trash_items_owner_expires_at",
        "trash_items",
        ["owner_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_trash_items_owner_id", "trash_items", ["owner_id"], unique=False
    )
    op.create_index(
        "ix_trash_items_purged_at", "trash_items", ["purged_at"], unique=False
    )
    op.create_index(
        "ix_trash_items_restore_available",
        "trash_items",
        ["restore_available"],
        unique=False,
    )
    op.create_index("ix_trash_items_status", "trash_items", ["status"], unique=False)
    op.create_table(
        "upload_sessions",
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Пользователь, инициировавший загрузку.",
        ),
        sa.Column(
            "parent_node_id",
            sa.UUID(),
            nullable=False,
            comment="Папка назначения, в которой будет создан загруженный файл.",
        ),
        sa.Column(
            "file_name",
            sa.String(length=255),
            nullable=False,
            comment="Оригинальное имя загружаемого файла.",
        ),
        sa.Column(
            "file_size_bytes",
            sa.BigInteger(),
            nullable=False,
            comment="Общий размер файла в байтах.",
        ),
        sa.Column(
            "part_size_bytes",
            sa.BigInteger(),
            nullable=False,
            comment="Размер одной части multipart upload в байтах.",
        ),
        sa.Column(
            "mime_type",
            sa.String(length=255),
            nullable=True,
            comment="MIME-тип загружаемого файла.",
        ),
        sa.Column(
            "checksum",
            sa.String(length=128),
            nullable=True,
            comment="Контрольная сумма всего файла.",
        ),
        sa.Column(
            "checksum_algorithm",
            sa.String(length=32),
            nullable=True,
            comment="Алгоритм контрольной суммы, например sha256.",
        ),
        sa.Column(
            "storage_bucket",
            sa.String(length=128),
            nullable=False,
            comment="Bucket MinIO/S3, используемый для загрузки.",
        ),
        sa.Column(
            "storage_key",
            sa.Text(),
            nullable=False,
            comment="Ключ объекта MinIO/S3 для итогового файла.",
        ),
        sa.Column(
            "upload_id",
            sa.String(length=512),
            nullable=False,
            comment="Идентификатор multipart upload, возвращённый MinIO/S3.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "created",
                "uploading",
                "completed",
                "failed",
                "aborted",
                "expired",
                name="upload_session_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="created",
            nullable=False,
            comment="Текущий статус сеанса загрузки.",
        ),
        sa.Column(
            "parts_count",
            sa.Integer(),
            nullable=False,
            comment="Общее количество частей загрузки.",
        ),
        sa.Column(
            "uploaded_parts_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Количество успешно загруженных частей.",
        ),
        sa.Column(
            "uploaded_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
            comment="Количество байтов, подтверждённых как загруженные.",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Дата и время истечения срока действия сеанса загрузки.",
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время завершения загрузки.",
        ),
        sa.Column(
            "aborted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время отмены загрузки.",
        ),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время ошибки загрузки.",
        ),
        sa.Column(
            "failure_reason",
            sa.Text(),
            nullable=True,
            comment="Описание причины ошибки загрузки.",
        ),
        sa.Column(
            "client_ip",
            sa.String(length=64),
            nullable=True,
            comment="IP-адрес клиента, инициировавшего загрузку.",
        ),
        sa.Column(
            "user_agent",
            sa.Text(),
            nullable=True,
            comment="User-Agent клиента, инициировавшего загрузку.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_size_bytes >= 0",
            name=op.f(
                "ck_upload_sessions_ck_upload_sessions_file_size_bytes_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "part_size_bytes > 0",
            name=op.f("ck_upload_sessions_ck_upload_sessions_part_size_bytes_positive"),
        ),
        sa.CheckConstraint(
            "parts_count > 0",
            name=op.f("ck_upload_sessions_ck_upload_sessions_parts_count_positive"),
        ),
        sa.CheckConstraint(
            "uploaded_parts_count <= parts_count",
            name=op.f(
                "ck_upload_sessions_ck_upload_sessions_uploaded_parts_count_lte_parts_count"
            ),
        ),
        sa.CheckConstraint(
            "uploaded_parts_count >= 0",
            name=op.f(
                "ck_upload_sessions_ck_upload_sessions_uploaded_parts_count_non_negative"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["parent_node_id"],
            ["file_system_nodes.id"],
            name=op.f("fk_upload_sessions_parent_node_id_file_system_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_upload_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_sessions")),
        sa.UniqueConstraint("upload_id", name="uq_upload_sessions_upload_id"),
    )
    op.create_index(
        "ix_upload_sessions_aborted_at", "upload_sessions", ["aborted_at"], unique=False
    )
    op.create_index(
        "ix_upload_sessions_completed_at",
        "upload_sessions",
        ["completed_at"],
        unique=False,
    )
    op.create_index(
        "ix_upload_sessions_created_at", "upload_sessions", ["created_at"], unique=False
    )
    op.create_index(
        "ix_upload_sessions_expires_at", "upload_sessions", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_upload_sessions_failed_at", "upload_sessions", ["failed_at"], unique=False
    )
    op.create_index(
        "ix_upload_sessions_parent_node_id",
        "upload_sessions",
        ["parent_node_id"],
        unique=False,
    )
    op.create_index(
        "ix_upload_sessions_parent_status",
        "upload_sessions",
        ["parent_node_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_upload_sessions_status", "upload_sessions", ["status"], unique=False
    )
    op.create_index(
        "ix_upload_sessions_status_expires_at",
        "upload_sessions",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_upload_sessions_storage_bucket_key",
        "upload_sessions",
        ["storage_bucket", "storage_key"],
        unique=False,
    )
    op.create_index(
        "ix_upload_sessions_upload_id", "upload_sessions", ["upload_id"], unique=False
    )
    op.create_index(
        "ix_upload_sessions_user_created_at",
        "upload_sessions",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_upload_sessions_user_id", "upload_sessions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_upload_sessions_user_status",
        "upload_sessions",
        ["user_id", "status"],
        unique=False,
    )
    op.create_table(
        "file_versions",
        sa.Column(
            "file_id",
            sa.UUID(),
            nullable=False,
            comment="Файл, к которому относится версия.",
        ),
        sa.Column(
            "version_number",
            sa.Integer(),
            nullable=False,
            comment="Порядковый номер версии внутри файла.",
        ),
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
            comment="Статус версии файла.",
        ),
        sa.Column(
            "storage_bucket",
            sa.String(length=128),
            nullable=False,
            comment="Bucket MinIO/S3, в котором хранится объект версии.",
        ),
        sa.Column(
            "storage_key",
            sa.Text(),
            nullable=False,
            comment="Ключ объекта MinIO/S3 для версии файла.",
        ),
        sa.Column(
            "size_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
            comment="Размер версии файла в байтах.",
        ),
        sa.Column(
            "checksum",
            sa.String(length=128),
            nullable=True,
            comment="Контрольная сумма версии файла.",
        ),
        sa.Column(
            "checksum_algorithm",
            sa.String(length=32),
            nullable=True,
            comment="Алгоритм контрольной суммы версии.",
        ),
        sa.Column(
            "mime_type",
            sa.String(length=255),
            nullable=True,
            comment="MIME-тип версии файла.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Дата и время создания версии.",
        ),
        sa.Column(
            "created_by",
            sa.UUID(),
            nullable=True,
            comment="Пользователь, создавший версию файла.",
        ),
        sa.Column(
            "change_comment",
            sa.Text(),
            nullable=True,
            comment="Комментарий к изменению версии.",
        ),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Признак текущей активной версии файла.",
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
            "file_id", "version_number", name="uq_file_versions_file_id_version_number"
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
    op.create_index(
        "uq_file_versions_current_per_file",
        "file_versions",
        ["file_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )
    op.create_table(
        "upload_parts",
        sa.Column(
            "upload_session_id",
            sa.UUID(),
            nullable=False,
            comment="Сеанс загрузки, к которому относится часть.",
        ),
        sa.Column(
            "part_number",
            sa.Integer(),
            nullable=False,
            comment="Номер части multipart upload.",
        ),
        sa.Column(
            "size_bytes",
            sa.BigInteger(),
            nullable=False,
            comment="Размер части в байтах.",
        ),
        sa.Column(
            "etag",
            sa.String(length=512),
            nullable=True,
            comment="ETag, возвращённый MinIO/S3 после успешной загрузки части.",
        ),
        sa.Column(
            "checksum",
            sa.String(length=128),
            nullable=True,
            comment="Необязательная контрольная сумма части.",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "uploaded",
                "failed",
                name="upload_part_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
            comment="Текущий статус части загрузки.",
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время успешной загрузки части.",
        ),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Дата и время ошибки загрузки части.",
        ),
        sa.Column(
            "failure_reason",
            sa.Text(),
            nullable=True,
            comment="Описание причины ошибки загрузки части.",
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "part_number > 0",
            name=op.f("ck_upload_parts_ck_upload_parts_part_number_positive"),
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name=op.f("ck_upload_parts_ck_upload_parts_size_bytes_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["upload_session_id"],
            ["upload_sessions.id"],
            name=op.f("fk_upload_parts_upload_session_id_upload_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_parts")),
        sa.UniqueConstraint(
            "upload_session_id",
            "part_number",
            name="uq_upload_parts_session_part_number",
        ),
    )
    op.create_index(
        "ix_upload_parts_created_at", "upload_parts", ["created_at"], unique=False
    )
    op.create_index(
        "ix_upload_parts_part_number", "upload_parts", ["part_number"], unique=False
    )
    op.create_index(
        "ix_upload_parts_session_part_number",
        "upload_parts",
        ["upload_session_id", "part_number"],
        unique=False,
    )
    op.create_index(
        "ix_upload_parts_session_status",
        "upload_parts",
        ["upload_session_id", "status"],
        unique=False,
    )
    op.create_index("ix_upload_parts_status", "upload_parts", ["status"], unique=False)
    op.create_index(
        "ix_upload_parts_status_uploaded_at",
        "upload_parts",
        ["status", "uploaded_at"],
        unique=False,
    )
    op.create_index(
        "ix_upload_parts_upload_session_id",
        "upload_parts",
        ["upload_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_upload_parts_uploaded_at", "upload_parts", ["uploaded_at"], unique=False
    )


def downgrade() -> None:
    """Откатывает начальную схему базы данных.

    Удаляет объекты схемы, созданные в "upgrade", в обратном порядке с учётом
    зависимостей между таблицами, внешними ключами и индексами.

    Используется Alembic при откате базы данных с ревизии "ac57ae7d7abd" на
    состояние до применения начальной схемы.

    Raises:
        SQLAlchemyError: Если база данных не может выполнить одну из операций
            удаления схемы.
    """

    op.drop_index("ix_upload_parts_uploaded_at", table_name="upload_parts")
    op.drop_index("ix_upload_parts_upload_session_id", table_name="upload_parts")
    op.drop_index("ix_upload_parts_status_uploaded_at", table_name="upload_parts")
    op.drop_index("ix_upload_parts_status", table_name="upload_parts")
    op.drop_index("ix_upload_parts_session_status", table_name="upload_parts")
    op.drop_index("ix_upload_parts_session_part_number", table_name="upload_parts")
    op.drop_index("ix_upload_parts_part_number", table_name="upload_parts")
    op.drop_index("ix_upload_parts_created_at", table_name="upload_parts")
    op.drop_table("upload_parts")
    op.drop_index(
        "uq_file_versions_current_per_file",
        table_name="file_versions",
        postgresql_where=sa.text("is_current = true"),
    )
    op.drop_index("ix_file_versions_storage_bucket_key", table_name="file_versions")
    op.drop_index("ix_file_versions_status", table_name="file_versions")
    op.drop_index("ix_file_versions_file_id", table_name="file_versions")
    op.drop_index("ix_file_versions_file_current", table_name="file_versions")
    op.drop_index("ix_file_versions_file_created_at", table_name="file_versions")
    op.drop_table("file_versions")
    op.drop_index("ix_upload_sessions_user_status", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_user_id", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_user_created_at", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_upload_id", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_storage_bucket_key", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_status_expires_at", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_status", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_parent_status", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_parent_node_id", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_failed_at", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_expires_at", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_created_at", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_completed_at", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_aborted_at", table_name="upload_sessions")
    op.drop_table("upload_sessions")
    op.drop_index("ix_trash_items_status", table_name="trash_items")
    op.drop_index("ix_trash_items_restore_available", table_name="trash_items")
    op.drop_index("ix_trash_items_purged_at", table_name="trash_items")
    op.drop_index("ix_trash_items_owner_id", table_name="trash_items")
    op.drop_index("ix_trash_items_owner_expires_at", table_name="trash_items")
    op.drop_index("ix_trash_items_owner_deleted_at", table_name="trash_items")
    op.drop_index("ix_trash_items_original_parent_id", table_name="trash_items")
    op.drop_index("ix_trash_items_node_id", table_name="trash_items")
    op.drop_index("ix_trash_items_expires_at", table_name="trash_items")
    op.drop_index("ix_trash_items_deleted_by", table_name="trash_items")
    op.drop_index("ix_trash_items_deleted_at", table_name="trash_items")
    op.drop_table("trash_items")
    op.drop_index("ix_public_links_token_active", table_name="public_links")
    op.drop_index("ix_public_links_token", table_name="public_links")
    op.drop_index("ix_public_links_status_expires_at", table_name="public_links")
    op.drop_index("ix_public_links_status", table_name="public_links")
    op.drop_index("ix_public_links_revoked_at", table_name="public_links")
    op.drop_index("ix_public_links_permission_type", table_name="public_links")
    op.drop_index("ix_public_links_node_id", table_name="public_links")
    op.drop_index("ix_public_links_node_active", table_name="public_links")
    op.drop_index("ix_public_links_is_active", table_name="public_links")
    op.drop_index("ix_public_links_expires_at_active", table_name="public_links")
    op.drop_index("ix_public_links_expires_at", table_name="public_links")
    op.drop_index("ix_public_links_created_by_active", table_name="public_links")
    op.drop_index("ix_public_links_created_by", table_name="public_links")
    op.drop_index("ix_public_links_created_at", table_name="public_links")
    op.drop_table("public_links")
    op.drop_index("ix_node_permissions_user_node", table_name="node_permissions")
    op.drop_index("ix_node_permissions_user_id", table_name="node_permissions")
    op.drop_index("ix_node_permissions_user_active", table_name="node_permissions")
    op.drop_index("ix_node_permissions_subject_type", table_name="node_permissions")
    op.drop_index("ix_node_permissions_revoked_at", table_name="node_permissions")
    op.drop_index("ix_node_permissions_permission_level", table_name="node_permissions")
    op.drop_index("ix_node_permissions_node_user", table_name="node_permissions")
    op.drop_index("ix_node_permissions_node_id", table_name="node_permissions")
    op.drop_index("ix_node_permissions_node_active", table_name="node_permissions")
    op.drop_index(
        "ix_node_permissions_granted_by_created_at", table_name="node_permissions"
    )
    op.drop_index("ix_node_permissions_granted_by", table_name="node_permissions")
    op.drop_index("ix_node_permissions_expires_at", table_name="node_permissions")
    op.drop_index("ix_node_permissions_created_at", table_name="node_permissions")
    op.drop_table("node_permissions")
    op.drop_index("ix_folders_updated_at", table_name="folders")
    op.drop_index("ix_folders_node_id", table_name="folders")
    op.drop_index("ix_folders_created_at", table_name="folders")
    op.drop_table("folders")
    op.drop_index("ix_files_updated_at", table_name="files")
    op.drop_index("ix_files_storage_status", table_name="files")
    op.drop_index("ix_files_storage_bucket_key", table_name="files")
    op.drop_index("ix_files_processing_status", table_name="files")
    op.drop_index("ix_files_preview_status", table_name="files")
    op.drop_index("ix_files_node_id", table_name="files")
    op.drop_index("ix_files_extension_mime_type", table_name="files")
    op.drop_index("ix_files_current_version_id", table_name="files")
    op.drop_index("ix_files_created_at", table_name="files")
    op.drop_index("ix_files_checksum_algorithm_checksum", table_name="files")
    op.drop_table("files")
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_index("ix_user_roles_assigned_by", table_name="user_roles")
    op.drop_index("ix_user_roles_assigned_at", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index("ix_user_quotas_user_id", table_name="user_quotas")
    op.drop_index("ix_user_quotas_updated_at", table_name="user_quotas")
    op.drop_index("ix_user_quotas_storage_used_bytes", table_name="user_quotas")
    op.drop_index("ix_user_quotas_storage_limit_bytes", table_name="user_quotas")
    op.drop_index("ix_user_quotas_public_links_used", table_name="user_quotas")
    op.drop_index("ix_user_quotas_files_used", table_name="user_quotas")
    op.drop_index("ix_user_quotas_created_at", table_name="user_quotas")
    op.drop_index(
        "ix_user_quotas_active_upload_sessions_used", table_name="user_quotas"
    )
    op.drop_table("user_quotas")
    op.drop_index(
        "uq_registration_requests_pending_username",
        table_name="registration_requests",
        postgresql_where="status = 'pending'",
    )
    op.drop_index(
        "uq_registration_requests_pending_email",
        table_name="registration_requests",
        postgresql_where="status = 'pending'",
    )
    op.drop_index(
        "ix_registration_requests_username_status", table_name="registration_requests"
    )
    op.drop_index(
        "ix_registration_requests_status_created_at", table_name="registration_requests"
    )
    op.drop_index(
        "ix_registration_requests_reviewed_by", table_name="registration_requests"
    )
    op.drop_index(
        "ix_registration_requests_reviewed_at", table_name="registration_requests"
    )
    op.drop_index(
        "ix_registration_requests_email_status", table_name="registration_requests"
    )
    op.drop_index(
        "ix_registration_requests_created_user_id", table_name="registration_requests"
    )
    op.drop_table("registration_requests")
    op.drop_index("ix_refresh_tokens_user_id_status", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id_is_active", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_status_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_revoked_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_replaced_by_token_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_parent_token_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_created_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_active_expires_at", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(
        "uq_file_system_nodes_active_root_name",
        table_name="file_system_nodes",
        postgresql_where=sa.text("is_deleted = false AND parent_id IS NULL"),
    )
    op.drop_index(
        "uq_file_system_nodes_active_name_in_parent",
        table_name="file_system_nodes",
        postgresql_where=sa.text("is_deleted = false AND parent_id IS NOT NULL"),
    )
    op.drop_index("ix_file_system_nodes_visibility", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_updated_at", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_parent_id", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_parent_deleted", table_name="file_system_nodes")
    op.drop_index(
        "ix_file_system_nodes_owner_type_deleted", table_name="file_system_nodes"
    )
    op.drop_index("ix_file_system_nodes_owner_path", table_name="file_system_nodes")
    op.drop_index(
        "ix_file_system_nodes_owner_parent_name", table_name="file_system_nodes"
    )
    op.drop_index("ix_file_system_nodes_owner_parent", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_owner_id", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_owner_deleted", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_node_type", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_name", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_is_deleted", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_deleted_at", table_name="file_system_nodes")
    op.drop_index("ix_file_system_nodes_created_at", table_name="file_system_nodes")
    op.drop_table("file_system_nodes")
    op.drop_index("ix_background_tasks_type_status", table_name="background_tasks")
    op.drop_index("ix_background_tasks_task_type", table_name="background_tasks")
    op.drop_index(
        "ix_background_tasks_status_priority_scheduled", table_name="background_tasks"
    )
    op.drop_index(
        "ix_background_tasks_status_created_at", table_name="background_tasks"
    )
    op.drop_index("ix_background_tasks_status", table_name="background_tasks")
    op.drop_index("ix_background_tasks_started_at", table_name="background_tasks")
    op.drop_index("ix_background_tasks_scheduled_at", table_name="background_tasks")
    op.drop_index(
        "ix_background_tasks_result_data_gin",
        table_name="background_tasks",
        postgresql_using="gin",
    )
    op.drop_index("ix_background_tasks_related_entity", table_name="background_tasks")
    op.drop_index("ix_background_tasks_priority", table_name="background_tasks")
    op.drop_index(
        "ix_background_tasks_payload_gin",
        table_name="background_tasks",
        postgresql_using="gin",
    )
    op.drop_index("ix_background_tasks_locked_until", table_name="background_tasks")
    op.drop_index("ix_background_tasks_idempotency_key", table_name="background_tasks")
    op.drop_index("ix_background_tasks_finished_at", table_name="background_tasks")
    op.drop_index(
        "ix_background_tasks_created_by_status", table_name="background_tasks"
    )
    op.drop_index("ix_background_tasks_created_by", table_name="background_tasks")
    op.drop_index("ix_background_tasks_created_at", table_name="background_tasks")
    op.drop_table("background_tasks")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_action_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_result_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_result", table_name="audit_logs")
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index(
        "ix_audit_logs_metadata_gin", table_name="audit_logs", postgresql_using="gin"
    )
    op.drop_index("ix_audit_logs_ip_address", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_correlation_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_users_username_status", table_name="users")
    op.drop_index("ix_users_status_created_at", table_name="users")
    op.drop_index("ix_users_last_login_at", table_name="users")
    op.drop_index("ix_users_email_status", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_roles_name", table_name="roles")
    op.drop_index("ix_roles_is_system", table_name="roles")
    op.drop_index("ix_roles_is_active", table_name="roles")
    op.drop_index("ix_roles_created_at", table_name="roles")
    op.drop_index("ix_roles_code", table_name="roles")
    op.drop_table("roles")
