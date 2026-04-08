"""Удаление backup-значений из CHECK-ограничений enum'ов.

Идентификатор ревизии: c4d2e6f8a1b3
Предыдущая ревизия: b3f1c2d4e5a6
Дата создания: 2026-06-03 00:00:00.000000

Revision ID: c4d2e6f8a1b3
Revises: b3f1c2d4e5a6
Create Date: 2026-06-03 00:00:00.000000

Фича резервного копирования не реализована, поэтому значения backup удалены из
Python-перечислений `BackgroundTaskType` и `AuditAction`. Эти enum'ы объявлены с
`native_enum=False`, то есть в базе данных им соответствуют не нативные ENUM-типы
PostgreSQL, а строковые колонки с CHECK-ограничениями. Миграция пересоздаёт эти
CHECK-ограничения без backup-значений.

Имена ограничений соответствуют naming convention проекта
(`ck_%(table_name)s_%(constraint_name)s`), где `constraint_name` — имя enum'а.
"""

from typing import Sequence, Union

from alembic import op

# Идентификаторы ревизии, используемые Alembic.
revision: str = "c4d2e6f8a1b3"
down_revision: Union[str, Sequence[str], None] = "b3f1c2d4e5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Значения CHECK-ограничения action в audit_logs (без backup-значений).
AUDIT_ACTION_VALUES: tuple[str, ...] = (
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
    "security.permission_denied",
    "security.suspicious_activity",
    "security.public_link_password_failed",
)

# Backup-значения action, существовавшие до этой ревизии.
AUDIT_ACTION_BACKUP_VALUES: tuple[str, ...] = (
    "backup.started",
    "backup.completed",
    "backup.failed",
)

# Значения CHECK-ограничения task_type в background_tasks (без backup-значений).
BACKGROUND_TASK_TYPE_VALUES: tuple[str, ...] = (
    "create_folder_archive",
    "clean_trash",
    "clean_expired_uploads",
    "clean_expired_public_links",
    "delete_object_from_storage",
    "check_storage_integrity",
    "generate_file_preview",
    "recalculate_user_quota",
)

# Backup-значения task_type, существовавшие до этой ревизии.
BACKGROUND_TASK_TYPE_BACKUP_VALUES: tuple[str, ...] = (
    "backup_database",
    "backup_storage",
)


def _recreate_check_constraint(
    *,
    table: str,
    constraint: str,
    column: str,
    values: Sequence[str],
) -> None:
    """Пересоздаёт CHECK-ограничение с указанным набором допустимых значений.

    Args:
        table: Имя таблицы.
        constraint: Полное имя CHECK-ограничения.
        column: Имя колонки, для которой задаётся ограничение.
        values: Допустимые значения колонки.
    """

    in_list = ", ".join(f"'{value}'" for value in values)
    op.execute(f'ALTER TABLE {table} DROP CONSTRAINT {constraint}')
    op.execute(
        f'ALTER TABLE {table} ADD CONSTRAINT {constraint} '
        f'CHECK ("{column}" IN ({in_list}))'
    )


def upgrade() -> None:
    """Применяет изменение схемы базы данных.

    Пересоздаёт CHECK-ограничения `ck_audit_logs_audit_action` и
    `ck_background_tasks_background_task_type` без backup-значений.

    Raises:
        SQLAlchemyError: Если база данных не может пересоздать ограничения.
    """

    _recreate_check_constraint(
        table="audit_logs",
        constraint="ck_audit_logs_audit_action",
        column="action",
        values=AUDIT_ACTION_VALUES,
    )
    _recreate_check_constraint(
        table="background_tasks",
        constraint="ck_background_tasks_background_task_type",
        column="task_type",
        values=BACKGROUND_TASK_TYPE_VALUES,
    )


def downgrade() -> None:
    """Откатывает изменение схемы базы данных.

    Возвращает backup-значения в CHECK-ограничения `ck_audit_logs_audit_action`
    и `ck_background_tasks_background_task_type`.

    Raises:
        SQLAlchemyError: Если база данных не может пересоздать ограничения.
    """

    _recreate_check_constraint(
        table="audit_logs",
        constraint="ck_audit_logs_audit_action",
        column="action",
        values=(*AUDIT_ACTION_VALUES, *AUDIT_ACTION_BACKUP_VALUES),
    )
    _recreate_check_constraint(
        table="background_tasks",
        constraint="ck_background_tasks_background_task_type",
        column="task_type",
        values=(*BACKGROUND_TASK_TYPE_VALUES, *BACKGROUND_TASK_TYPE_BACKUP_VALUES),
    )
