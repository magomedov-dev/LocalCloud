from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from database.models.enums import (
    NodeVisibility,
    PermissionLevel,
    SystemRole,
    UserStatus,
)


class SupportsUser(Protocol):
    """Протокол пользователя для проверки прав доступа.

    Описывает минимальный интерфейс объекта пользователя, который требуется
    security-слою без жёсткой привязки к конкретной ORM-модели.

    Attributes:
        id: Идентификатор пользователя.
        status: Статус пользователя.
        role: Системная роль пользователя.
    """

    id: uuid.UUID
    status: UserStatus | str
    role: SystemRole | str


class SupportsNode(Protocol):
    """Протокол объекта файловой системы.

    Описывает минимальный интерфейс файла или папки, необходимый для проверки
    владельца, видимости и состояния удаления.

    Attributes:
        id: Идентификатор объекта файловой системы.
        owner_id: Идентификатор владельца объекта.
        visibility: Видимость объекта.
        is_deleted: True, если объект помечен как удалённый.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    visibility: NodeVisibility | str
    is_deleted: bool


class SupportsNodePermission(Protocol):
    """Протокол разрешения на объект файловой системы.

    Описывает минимальный интерфейс записи прав доступа пользователя к объекту.

    Attributes:
        user_id: Идентификатор пользователя, которому выдано разрешение.
        permission_level: Уровень прав доступа.
        can_read: Разрешено ли чтение.
        can_download: Разрешено ли скачивание.
        can_write: Разрешена ли запись.
        can_delete: Разрешено ли удаление.
        can_share: Разрешена ли выдача доступа другим пользователям.
        revoked_at: Дата отзыва разрешения или None.
        expires_at: Дата истечения разрешения или None.
    """

    user_id: uuid.UUID
    permission_level: PermissionLevel | str
    can_read: bool
    can_download: bool
    can_write: bool
    can_delete: bool
    can_share: bool
    revoked_at: datetime | None
    expires_at: datetime | None

    def is_active_at(self, moment: datetime) -> bool:
        """Проверяет, активно ли разрешение на указанный момент времени.

        Args:
            moment: Момент времени для проверки активности разрешения.

        Returns:
            True, если разрешение активно на указанный момент, иначе False.
        """
        ...
