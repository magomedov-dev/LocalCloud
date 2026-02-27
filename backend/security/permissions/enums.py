from __future__ import annotations

from enum import StrEnum


class PermissionAction(StrEnum):
    """Действия, для которых проверяются права доступа.

    Attributes:
        READ: Чтение metadata или содержимого объекта.
        DOWNLOAD: Скачивание файла.
        WRITE: Изменение или запись данных.
        DELETE: Удаление объекта.
        SHARE: Выдача доступа другим пользователям.
        OWNER: Проверка владения объектом.
        MANAGE: Управление объектом и его настройками.
        RESTORE: Восстановление объекта из корзины.
        PURGE: Безвозвратное удаление объекта.
    """

    READ = "read"
    DOWNLOAD = "download"
    WRITE = "write"
    DELETE = "delete"
    SHARE = "share"
    OWNER = "owner"
    MANAGE = "manage"
    RESTORE = "restore"
    PURGE = "purge"


class PermissionDeniedReason(StrEnum):
    """Причины отказа в доступе.

    Attributes:
        ANONYMOUS_USER: Пользователь не авторизован.
        INACTIVE_USER: Пользователь неактивен или заблокирован.
        DELETED_NODE: Объект файловой системы удалён.
        NOT_OWNER: Пользователь не является владельцем объекта.
        NOT_ADMIN: Пользователь не имеет прав администратора.
        PERMISSION_NOT_FOUND: Подходящее разрешение не найдено.
        PERMISSION_REVOKED: Разрешение было отозвано.
        PERMISSION_EXPIRED: Срок действия разрешения истёк.
        INSUFFICIENT_PERMISSION: Уровень разрешения недостаточен.
        PRIVATE_NODE: Объект закрыт для публичного доступа.
        INVALID_ACTION: Передано недопустимое действие.
    """

    ANONYMOUS_USER = "anonymous_user"
    INACTIVE_USER = "inactive_user"
    DELETED_NODE = "deleted_node"
    NOT_OWNER = "not_owner"
    NOT_ADMIN = "not_admin"
    PERMISSION_NOT_FOUND = "permission_not_found"
    PERMISSION_REVOKED = "permission_revoked"
    PERMISSION_EXPIRED = "permission_expired"
    INSUFFICIENT_PERMISSION = "insufficient_permission"
    PRIVATE_NODE = "private_node"
    INVALID_ACTION = "invalid_action"


class PermissionErrorCode(StrEnum):
    """Коды ошибок системы прав доступа.

    Attributes:
        PERMISSION_DENIED: Доступ запрещён.
        INVALID_ACTION: Передано некорректное действие.
        INVALID_PERMISSION_LEVEL: Передан некорректный уровень прав.
        INVALID_USER: Пользователь отсутствует или некорректен.
        INVALID_NODE: Объект файловой системы отсутствует или некорректен.
    """

    PERMISSION_DENIED = "permission_denied"
    INVALID_ACTION = "invalid_action"
    INVALID_PERMISSION_LEVEL = "invalid_permission_level"
    INVALID_USER = "invalid_user"
    INVALID_NODE = "invalid_node"
