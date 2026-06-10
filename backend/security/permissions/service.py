from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Final

from security.permissions.validators import (
    get_object_uuid,
    get_optional_user_id,
    normalize_moment,
    normalize_node_visibility,
    normalize_permission_action,
    normalize_permission_level,
)

from database.models.enums import (
    NodeVisibility,
    PermissionLevel,
    SystemRole,
    UserStatus,
)
from security.permissions.dto import PermissionCheckResult
from security.permissions.enums import PermissionAction, PermissionDeniedReason
from security.permissions.exceptions import PermissionCheckError, PermissionDeniedError
from security.permissions.protocols import (
    SupportsNode,
    SupportsNodePermission,
    SupportsUser,
)

# Приоритеты уровней доступа для сравнения разрешений.
PERMISSION_LEVEL_PRIORITY: Final[dict[PermissionLevel, int]] = {
    PermissionLevel.READ: 10,
    PermissionLevel.DOWNLOAD: 20,
    PermissionLevel.WRITE: 30,
    PermissionLevel.DELETE: 40,
    PermissionLevel.OWNER: 50,
}

# Минимальные уровни доступа, необходимые для выполнения действий.
ACTION_REQUIRED_PERMISSION_LEVEL: Final[dict[PermissionAction, PermissionLevel]] = {
    PermissionAction.READ: PermissionLevel.READ,
    PermissionAction.DOWNLOAD: PermissionLevel.DOWNLOAD,
    PermissionAction.WRITE: PermissionLevel.WRITE,
    PermissionAction.DELETE: PermissionLevel.DELETE,
    PermissionAction.SHARE: PermissionLevel.OWNER,
    PermissionAction.OWNER: PermissionLevel.OWNER,
    PermissionAction.MANAGE: PermissionLevel.OWNER,
    PermissionAction.RESTORE: PermissionLevel.DELETE,
    PermissionAction.PURGE: PermissionLevel.OWNER,
}


def check_node_permission(
    *,
    user: SupportsUser | None,
    node: SupportsNode,
    action: PermissionAction | str,
    permissions: Iterable[SupportsNodePermission] | None = None,
    moment: datetime | None = None,
    allow_deleted: bool = False,
    allow_public: bool = True,
) -> PermissionCheckResult:
    """Проверяет право пользователя на выполнение действия над объектом.

    Args:
        user: Пользователь, для которого выполняется проверка. Может быть None
            для анонимного пользователя.
        node: Объект файловой системы.
        action: Действие, которое нужно проверить.
        permissions: Список разрешений пользователя на объект.
        moment: Момент времени для проверки активности разрешений. Если не
            передан, используется текущее время.
        allow_deleted: Разрешать ли доступ к удалённым объектам.
        allow_public: Разрешать ли доступ к публичным объектам без явного
            разрешения.

    Returns:
        Результат проверки прав доступа.
    """

    normalized_action = normalize_permission_action(action)
    checked_at = normalize_moment(moment)
    node_id = get_object_uuid(node, "id")
    owner_id = get_object_uuid(node, "owner_id")

    if not allow_deleted and bool(getattr(node, "is_deleted", False)):
        return PermissionCheckResult(
            allowed=False,
            action=normalized_action,
            reason=PermissionDeniedReason.DELETED_NODE,
            user_id=get_optional_user_id(user),
            node_id=node_id,
        )

    if user is None:
        if allow_public and public_node_allows_action(node, normalized_action):
            return PermissionCheckResult(
                allowed=True,
                action=normalized_action,
                node_id=node_id,
                details={"source": "public_node"},
            )
        return PermissionCheckResult(
            allowed=False,
            action=normalized_action,
            reason=PermissionDeniedReason.ANONYMOUS_USER,
            node_id=node_id,
        )

    user_id = get_object_uuid(user, "id")

    if not is_active_user(user):
        return PermissionCheckResult(
            allowed=False,
            action=normalized_action,
            reason=PermissionDeniedReason.INACTIVE_USER,
            user_id=user_id,
            node_id=node_id,
            details={"user_status": str(getattr(user, "status", None))},
        )

    if is_admin_user(user):
        return PermissionCheckResult(
            allowed=True,
            action=normalized_action,
            user_id=user_id,
            node_id=node_id,
            is_admin=True,
            permission_level=PermissionLevel.OWNER,
            details={"source": "admin_role"},
        )

    if user_id == owner_id:
        return PermissionCheckResult(
            allowed=True,
            action=normalized_action,
            user_id=user_id,
            node_id=node_id,
            is_owner=True,
            permission_level=PermissionLevel.OWNER,
            details={"source": "node_owner"},
        )

    if allow_public and public_node_allows_action(node, normalized_action):
        return PermissionCheckResult(
            allowed=True,
            action=normalized_action,
            user_id=user_id,
            node_id=node_id,
            details={"source": "public_node"},
        )

    matched_permission = find_user_permission(
        permissions or (),
        user_id=user_id,
        moment=checked_at,
    )

    if matched_permission is None:
        return PermissionCheckResult(
            allowed=False,
            action=normalized_action,
            reason=PermissionDeniedReason.PERMISSION_NOT_FOUND,
            user_id=user_id,
            node_id=node_id,
        )

    if permission_allows_action(
        matched_permission,
        normalized_action,
        moment=checked_at,
    ):
        return PermissionCheckResult(
            allowed=True,
            action=normalized_action,
            user_id=user_id,
            node_id=node_id,
            permission_level=normalize_permission_level(
                matched_permission.permission_level
            ),
            details={"source": "node_permission"},
        )

    return PermissionCheckResult(
        allowed=False,
        action=normalized_action,
        reason=resolve_permission_denied_reason(matched_permission, checked_at),
        user_id=user_id,
        node_id=node_id,
        permission_level=normalize_permission_level(
            matched_permission.permission_level
        ),
    )


def require_node_permission(
    *,
    user: SupportsUser | None,
    node: SupportsNode,
    action: PermissionAction | str,
    permissions: Iterable[SupportsNodePermission] | None = None,
    moment: datetime | None = None,
    allow_deleted: bool = False,
    allow_public: bool = True,
) -> PermissionCheckResult:
    """Проверяет право пользователя и выбрасывает ошибку при отказе.

    Args:
        user: Пользователь, для которого выполняется проверка.
        node: Объект файловой системы.
        action: Действие, которое нужно проверить.
        permissions: Список разрешений пользователя на объект.
        moment: Момент времени для проверки активности разрешений.
        allow_deleted: Разрешать ли доступ к удалённым объектам.
        allow_public: Разрешать ли доступ к публичным объектам.

    Returns:
        Результат успешной проверки прав доступа.

    Raises:
        PermissionDeniedError: Если доступ запрещён.
    """

    result = check_node_permission(
        user=user,
        node=node,
        action=action,
        permissions=permissions,
        moment=moment,
        allow_deleted=allow_deleted,
        allow_public=allow_public,
    )
    result.raise_if_denied()

    return result


def can_read_node(
    user: SupportsUser | None,
    node: SupportsNode,
    *,
    permissions: Iterable[SupportsNodePermission] | None = None,
    moment: datetime | None = None,
    allow_deleted: bool = False,
) -> bool:
    """Проверяет, может ли пользователь читать объект.

    Args:
        user: Пользователь, для которого выполняется проверка.
        node: Объект файловой системы.
        permissions: Список разрешений пользователя на объект.
        moment: Момент времени для проверки активности разрешений.
        allow_deleted: Разрешать ли доступ к удалённому объекту.

    Returns:
        True, если чтение разрешено, иначе False.
    """

    return check_node_permission(
        user=user,
        node=node,
        action=PermissionAction.READ,
        permissions=permissions,
        moment=moment,
        allow_deleted=allow_deleted,
    ).allowed


def can_download_node(
    user: SupportsUser | None,
    node: SupportsNode,
    *,
    permissions: Iterable[SupportsNodePermission] | None = None,
    moment: datetime | None = None,
    allow_deleted: bool = False,
) -> bool:
    """Проверяет, может ли пользователь скачать объект.

    Args:
        user: Пользователь, для которого выполняется проверка.
        node: Объект файловой системы.
        permissions: Список разрешений пользователя на объект.
        moment: Момент времени для проверки активности разрешений.
        allow_deleted: Разрешать ли доступ к удалённому объекту.

    Returns:
        True, если скачивание разрешено, иначе False.
    """

    return check_node_permission(
        user=user,
        node=node,
        action=PermissionAction.DOWNLOAD,
        permissions=permissions,
        moment=moment,
        allow_deleted=allow_deleted,
    ).allowed


def can_write_node(
    user: SupportsUser | None,
    node: SupportsNode,
    *,
    permissions: Iterable[SupportsNodePermission] | None = None,
    moment: datetime | None = None,
    allow_deleted: bool = False,
) -> bool:
    """Проверяет, может ли пользователь изменять объект.

    Args:
        user: Пользователь, для которого выполняется проверка.
        node: Объект файловой системы.
        permissions: Список разрешений пользователя на объект.
        moment: Момент времени для проверки активности разрешений.
        allow_deleted: Разрешать ли доступ к удалённому объекту.

    Returns:
        True, если запись разрешена, иначе False.
    """

    return check_node_permission(
        user=user,
        node=node,
        action=PermissionAction.WRITE,
        permissions=permissions,
        moment=moment,
        allow_deleted=allow_deleted,
    ).allowed


def can_delete_node(
    user: SupportsUser | None,
    node: SupportsNode,
    *,
    permissions: Iterable[SupportsNodePermission] | None = None,
    moment: datetime | None = None,
    allow_deleted: bool = False,
) -> bool:
    """Проверяет, может ли пользователь удалить объект.

    Args:
        user: Пользователь, для которого выполняется проверка.
        node: Объект файловой системы.
        permissions: Список разрешений пользователя на объект.
        moment: Момент времени для проверки активности разрешений.
        allow_deleted: Разрешать ли доступ к уже удалённому объекту.

    Returns:
        True, если удаление разрешено, иначе False.
    """

    return check_node_permission(
        user=user,
        node=node,
        action=PermissionAction.DELETE,
        permissions=permissions,
        moment=moment,
        allow_deleted=allow_deleted,
    ).allowed


def can_share_node(
    user: SupportsUser | None,
    node: SupportsNode,
    *,
    permissions: Iterable[SupportsNodePermission] | None = None,
    moment: datetime | None = None,
    allow_deleted: bool = False,
) -> bool:
    """Проверяет, может ли пользователь выдавать доступ к объекту.

    Args:
        user: Пользователь, для которого выполняется проверка.
        node: Объект файловой системы.
        permissions: Список разрешений пользователя на объект.
        moment: Момент времени для проверки активности разрешений.
        allow_deleted: Разрешать ли доступ к удалённому объекту.

    Returns:
        True, если выдача доступа разрешена, иначе False.
    """

    return check_node_permission(
        user=user,
        node=node,
        action=PermissionAction.SHARE,
        permissions=permissions,
        moment=moment,
        allow_deleted=allow_deleted,
    ).allowed


def can_manage_node(
    user: SupportsUser | None,
    node: SupportsNode,
    *,
    permissions: Iterable[SupportsNodePermission] | None = None,
    moment: datetime | None = None,
    allow_deleted: bool = False,
) -> bool:
    """Проверяет, может ли пользователь управлять объектом.

    Args:
        user: Пользователь, для которого выполняется проверка.
        node: Объект файловой системы.
        permissions: Список разрешений пользователя на объект.
        moment: Момент времени для проверки активности разрешений.
        allow_deleted: Разрешать ли доступ к удалённому объекту.

    Returns:
        True, если управление объектом разрешено, иначе False.
    """

    return check_node_permission(
        user=user,
        node=node,
        action=PermissionAction.MANAGE,
        permissions=permissions,
        moment=moment,
        allow_deleted=allow_deleted,
    ).allowed


def require_admin(user: SupportsUser | None) -> None:
    """Проверяет, что пользователь является активным администратором.

    Args:
        user: Пользователь для проверки.

    Raises:
        PermissionDeniedError: Если пользователь отсутствует, неактивен или не
            имеет роли администратора.
    """

    if user is None:
        raise PermissionDeniedError(
            action=PermissionAction.MANAGE,
            reason=PermissionDeniedReason.ANONYMOUS_USER,
        )

    if not is_active_user(user):
        raise PermissionDeniedError(
            action=PermissionAction.MANAGE,
            reason=PermissionDeniedReason.INACTIVE_USER,
            user_id=get_optional_user_id(user),
            details={"user_status": str(getattr(user, "status", None))},
        )

    if not is_admin_user(user):
        raise PermissionDeniedError(
            action=PermissionAction.MANAGE,
            reason=PermissionDeniedReason.NOT_ADMIN,
            user_id=get_optional_user_id(user),
        )


def require_active_user(user: SupportsUser | None) -> None:
    """Проверяет, что пользователь авторизован и активен.

    Args:
        user: Пользователь для проверки.

    Raises:
        PermissionDeniedError: Если пользователь отсутствует или неактивен.
    """

    if user is None:
        raise PermissionDeniedError(
            action=PermissionAction.READ,
            reason=PermissionDeniedReason.ANONYMOUS_USER,
        )

    if not is_active_user(user):
        raise PermissionDeniedError(
            action=PermissionAction.READ,
            reason=PermissionDeniedReason.INACTIVE_USER,
            user_id=get_optional_user_id(user),
            details={"user_status": str(getattr(user, "status", None))},
        )


def is_active_user(user: SupportsUser | None) -> bool:
    """Проверяет, является ли пользователь активным.

    Args:
        user: Пользователь для проверки.

    Returns:
        True, если пользователь существует и имеет статус `active`, иначе False.
    """

    if user is None:
        return False

    status = getattr(user, "status", None)

    if isinstance(status, UserStatus):
        return status == UserStatus.ACTIVE

    return str(status) == UserStatus.ACTIVE.value


def is_admin_user(user: SupportsUser | None) -> bool:
    """Проверяет наличие роли администратора у пользователя.

    Args:
        user: Пользователь для проверки.

    Returns:
        True, если у пользователя есть системная роль администратора, иначе
        False.
    """

    return _has_role(user, SystemRole.ADMIN)


def is_regular_user(user: SupportsUser | None) -> bool:
    """Проверяет наличие обычной пользовательской роли.

    Args:
        user: Пользователь для проверки.

    Returns:
        True, если у пользователя есть системная роль обычного пользователя,
        иначе False.
    """

    return _has_role(user, SystemRole.USER)


def is_node_owner(user: SupportsUser | None, node: SupportsNode) -> bool:
    """Проверяет, является ли пользователь владельцем объекта.

    Args:
        user: Пользователь для проверки.
        node: Объект файловой системы.

    Returns:
        True, если пользователь является владельцем объекта, иначе False.
    """

    if user is None:
        return False

    return get_object_uuid(user, "id") == get_object_uuid(node, "owner_id")


def public_node_allows_action(
    node: SupportsNode, action: PermissionAction | str
) -> bool:
    """Проверяет, разрешает ли публичный объект указанное действие.

    Args:
        node: Объект файловой системы.
        action: Действие для проверки.

    Returns:
        True, если объект публичный и действие разрешено публично, иначе False.
    """

    normalized_action = normalize_permission_action(action)
    visibility = normalize_node_visibility(getattr(node, "visibility", None))

    if visibility != NodeVisibility.PUBLIC:
        return False

    return normalized_action in {PermissionAction.READ, PermissionAction.DOWNLOAD}


def permission_allows_action(
    permission: SupportsNodePermission,
    action: PermissionAction | str,
    *,
    moment: datetime | None = None,
) -> bool:
    """Проверяет, разрешает ли конкретное разрешение выполнить действие.

    Args:
        permission: Разрешение пользователя на объект.
        action: Действие для проверки.
        moment: Момент времени для проверки активности разрешения.

    Returns:
        True, если разрешение активно и позволяет действие, иначе False.

    Raises:
        PermissionCheckError: Если передано неизвестное действие.
    """

    normalized_action = normalize_permission_action(action)
    checked_at = normalize_moment(moment)

    if not permission_is_active_at(permission, checked_at):
        return False

    if normalized_action == PermissionAction.READ:
        return bool(permission.can_read)

    if normalized_action == PermissionAction.DOWNLOAD:
        return bool(permission.can_download)

    if normalized_action == PermissionAction.WRITE:
        return bool(permission.can_write)

    if normalized_action == PermissionAction.DELETE:
        return bool(permission.can_delete)

    if normalized_action in {
        PermissionAction.SHARE,
        PermissionAction.OWNER,
        PermissionAction.MANAGE,
        PermissionAction.PURGE,
    }:
        return bool(permission.can_share) and permission_level_at_least(
            permission.permission_level,
            PermissionLevel.OWNER,
        )

    if normalized_action == PermissionAction.RESTORE:
        return bool(permission.can_delete)

    raise PermissionCheckError("Неизвестное действие проверки доступа.")


def permission_level_allows_action(
    permission_level: PermissionLevel | str,
    action: PermissionAction | str,
) -> bool:
    """Проверяет, достаточен ли уровень прав для действия.

    Args:
        permission_level: Фактический уровень прав.
        action: Действие, которое нужно выполнить.

    Returns:
        True, если уровень прав достаточен для действия, иначе False.
    """

    normalized_level = normalize_permission_level(permission_level)
    required_level = ACTION_REQUIRED_PERMISSION_LEVEL[
        normalize_permission_action(action)
    ]

    return permission_level_at_least(normalized_level, required_level)


def permission_level_at_least(
    actual: PermissionLevel | str,
    required: PermissionLevel | str,
) -> bool:
    """Сравнивает два уровня прав доступа.

    Args:
        actual: Фактический уровень прав.
        required: Минимально необходимый уровень прав.

    Returns:
        True, если фактический уровень больше или равен требуемому, иначе False.
    """

    actual_level = normalize_permission_level(actual)
    required_level = normalize_permission_level(required)

    return (
        PERMISSION_LEVEL_PRIORITY[actual_level]
        >= PERMISSION_LEVEL_PRIORITY[required_level]
    )


def find_user_permission(
    permissions: Iterable[SupportsNodePermission],
    *,
    user_id: uuid.UUID,
    moment: datetime | None = None,
) -> SupportsNodePermission | None:
    """Находит наиболее сильное активное разрешение пользователя.

    Args:
        permissions: Список разрешений на объект.
        user_id: Идентификатор пользователя.
        moment: Момент времени для проверки активности разрешений.

    Returns:
        Активное разрешение пользователя с максимальным уровнем доступа или
        None, если подходящее разрешение не найдено.
    """

    checked_at = normalize_moment(moment)

    matched_permissions = [
        permission
        for permission in permissions
        if get_object_uuid(permission, "user_id") == user_id
        and permission_is_active_at(permission, checked_at)
    ]

    if not matched_permissions:
        return None

    return max(
        matched_permissions,
        key=lambda permission: PERMISSION_LEVEL_PRIORITY[
            normalize_permission_level(permission.permission_level)
        ],
    )


def permission_is_active_at(
    permission: SupportsNodePermission,
    moment: datetime | None = None,
) -> bool:
    """Проверяет активность разрешения на указанный момент времени.

    Args:
        permission: Разрешение для проверки.
        moment: Момент времени проверки.

    Returns:
        True, если разрешение не отозвано и не истекло, иначе False.
    """

    checked_at = normalize_moment(moment)
    is_active_at = getattr(permission, "is_active_at", None)

    if callable(is_active_at):
        return bool(is_active_at(checked_at))

    revoked_at = getattr(permission, "revoked_at", None)
    expires_at = getattr(permission, "expires_at", None)

    if revoked_at is not None:
        return False

    if expires_at is not None and normalize_moment(expires_at) <= checked_at:
        return False

    return True


def resolve_permission_denied_reason(
    permission: SupportsNodePermission,
    moment: datetime | None = None,
) -> PermissionDeniedReason:
    """Определяет причину отказа по состоянию разрешения.

    Args:
        permission: Разрешение, по которому нужно определить причину отказа.
        moment: Момент времени проверки.

    Returns:
        Причина отказа в доступе.
    """

    checked_at = normalize_moment(moment)

    if getattr(permission, "revoked_at", None) is not None:
        return PermissionDeniedReason.PERMISSION_REVOKED

    expires_at = getattr(permission, "expires_at", None)

    if expires_at is not None and normalize_moment(expires_at) <= checked_at:
        return PermissionDeniedReason.PERMISSION_EXPIRED

    return PermissionDeniedReason.INSUFFICIENT_PERMISSION


def _has_role(user: SupportsUser | None, system_role: SystemRole) -> bool:
    """Проверяет наличие системной роли у пользователя.

    Args:
        user: Пользователь для проверки.
        system_role: Системная роль.

    Returns:
        True, если системная роль пользователя совпадает с указанной, иначе
        False.
    """

    if user is None:
        return False

    role = getattr(user, "role", None)

    if role is None:
        return False

    role_value = getattr(role, "value", role)
    return str(role_value).strip().lower() == system_role.value
