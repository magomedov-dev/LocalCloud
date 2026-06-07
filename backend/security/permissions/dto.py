from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from security.permissions.enums import PermissionAction, PermissionDeniedReason
from security.permissions.exceptions import PermissionDeniedError

from database.models.enums import PermissionLevel


@dataclass(frozen=True, slots=True)
class PermissionCheckResult:
    """Результат проверки прав доступа к объекту файловой системы.

    Attributes:
        allowed: True, если доступ разрешён, иначе False.
        action: Действие, для которого выполнялась проверка прав.
        reason: Причина отказа в доступе, если доступ запрещён.
        user_id: Идентификатор пользователя, для которого выполнялась проверка.
        node_id: Идентификатор объекта файловой системы.
        permission_level: Уровень прав доступа пользователя к объекту.
        is_admin: True, если пользователь имеет права администратора.
        is_owner: True, если пользователь является владельцем объекта.
        details: Дополнительные диагностические данные проверки.
    """

    allowed: bool
    action: PermissionAction
    reason: PermissionDeniedReason | None = None
    user_id: uuid.UUID | None = None
    node_id: uuid.UUID | None = None
    permission_level: PermissionLevel | None = None
    is_admin: bool = False
    is_owner: bool = False
    details: dict[str, Any] | None = None

    @property
    def denied(self) -> bool:
        """Проверяет, был ли доступ запрещён.

        Returns:
            True, если доступ запрещён, иначе False.
        """

        return not self.allowed

    def raise_if_denied(self) -> None:
        """Выбрасывает исключение, если доступ запрещён.

        Raises:
            PermissionDeniedError: Если результат проверки запрещает доступ.
        """

        if self.allowed:
            return

        raise PermissionDeniedError(
            action=self.action,
            reason=self.reason,
            user_id=self.user_id,
            node_id=self.node_id,
            details=self.details,
        )
