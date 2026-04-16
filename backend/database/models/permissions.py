from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base
from database.models.enums import PermissionLevel, PermissionSubjectType
from database.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from database.models.filesystem import FileSystemNode
    from database.models.users import User


class NodePermission(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Разрешение на узел файловой системы.

    Представляет разрешение, предоставленное пользователю на конкретный файл
    или папку. Разрешение хранит общий уровень доступа, отдельные boolean-флаги
    доступных действий, срок действия и сведения об отзыве.

    Разрешения могут включать:
        - чтение метаданных;
        - просмотр содержимого папки;
        - скачивание файла или архива папки;
        - изменение узла;
        - удаление узла;
        - дальнейшую передачу доступа.

    Attributes:
        node_id: Узел файловой системы, для которого выданы разрешения.
        user_id: Пользователь, получающий разрешение доступа.
        subject_type: Тип субъекта доступа. Для этой таблицы обычно
            используется `PermissionSubjectType.USER`.
        permission_level: Обобщённый уровень доступа.
        granted_by: Пользователь, предоставивший разрешение.
        can_read: Признак разрешения просмотра метаданных узла и содержимого
            папки.
        can_download: Признак разрешения скачивания файла или архива папки.
        can_write: Признак разрешения изменения, переименования или загрузки
            в узел.
        can_delete: Признак разрешения перемещения узла в корзину или
            окончательного удаления.
        can_share: Признак разрешения выдачи разрешений и создания публичных
            ссылок.
        expires_at: Дата и время истечения срока действия разрешения.
        revoked_at: Дата и время отзыва разрешения.
        revoke_reason: Причина отзыва разрешения.
        node: Узел файловой системы, для которого выдано разрешение.
        user: Пользователь, получающий разрешение.
        grantor: Пользователь, предоставивший разрешение.

    Table:
        node_permissions
    """

    __tablename__ = "node_permissions"

    __table_args__ = (
        UniqueConstraint(
            "node_id",
            "user_id",
            name="uq_node_permissions_node_id_user_id",
        ),
        Index("ix_node_permissions_node_id", "node_id"),
        Index("ix_node_permissions_user_id", "user_id"),
        Index("ix_node_permissions_granted_by", "granted_by"),
        Index("ix_node_permissions_subject_type", "subject_type"),
        Index("ix_node_permissions_permission_level", "permission_level"),
        Index("ix_node_permissions_revoked_at", "revoked_at"),
        Index("ix_node_permissions_expires_at", "expires_at"),
        Index("ix_node_permissions_created_at", "created_at"),
        Index("ix_node_permissions_node_user", "node_id", "user_id"),
        Index("ix_node_permissions_user_node", "user_id", "node_id"),
        Index(
            "ix_node_permissions_user_active",
            "user_id",
            "revoked_at",
            "expires_at",
        ),
        Index(
            "ix_node_permissions_node_active",
            "node_id",
            "revoked_at",
            "expires_at",
        ),
        Index(
            "ix_node_permissions_granted_by_created_at",
            "granted_by",
            "created_at",
        ),
    )

    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "file_system_nodes.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        comment="Узел файловой системы, для которого выданы разрешения.",
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        comment="Пользователь, получающий разрешение доступа.",
    )

    subject_type: Mapped[PermissionSubjectType] = mapped_column(
        Enum(
            PermissionSubjectType,
            name="permission_subject_type",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=PermissionSubjectType.USER,
        server_default=PermissionSubjectType.USER.value,
        comment="Тип субъекта доступа. Для этой таблицы обычно используется user.",
    )

    permission_level: Mapped[PermissionLevel] = mapped_column(
        Enum(
            PermissionLevel,
            name="permission_level",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=PermissionLevel.READ,
        server_default=PermissionLevel.READ.value,
        comment="Обобщённый уровень доступа.",
    )

    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        comment="Пользователь, предоставивший разрешение.",
    )

    can_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
        comment="Разрешает просмотр метаданных узла и содержимого папки.",
    )

    can_download: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Разрешает скачивание файла или архива папки.",
    )

    can_write: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Разрешает изменение, переименование или загрузку в узел.",
    )

    can_delete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Разрешает перемещение узла в корзину или окончательное удаление.",
    )

    can_share: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Разрешает выдачу разрешений и создание публичных ссылок.",
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время истечения срока действия разрешения.",
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время отзыва разрешения.",
    )

    revoke_reason: Mapped[str | None] = mapped_column(
        String(length=512),
        nullable=True,
        comment="Причина отзыва разрешения.",
    )

    # -------------------------------------------------------------------------
    # Связи
    # -------------------------------------------------------------------------

    node: Mapped[FileSystemNode] = relationship(
        "FileSystemNode",
        foreign_keys=[node_id],
        back_populates="permissions",
        lazy="selectin",
    )

    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="selectin",
    )

    grantor: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[granted_by],
        lazy="selectin",
    )

    # -------------------------------------------------------------------------
    # Вспомогательные свойства
    # -------------------------------------------------------------------------

    @property
    def is_revoked(self) -> bool:
        """Проверяет, было ли разрешение явно отозвано.

        Returns:
            `True`, если у разрешения задано время отзыва, иначе `False`.
        """

        return self.revoked_at is not None

    @property
    def has_any_permission(self) -> bool:
        """Проверяет наличие хотя бы одного флага разрешения.

        Returns:
            `True`, если включён хотя бы один флаг разрешения, иначе `False`.
        """

        return any(
            (
                self.can_read,
                self.can_download,
                self.can_write,
                self.can_delete,
                self.can_share,
            )
        )

    @property
    def is_read_only(self) -> bool:
        """Проверяет, позволяет ли разрешение только чтение.

        Returns:
            `True`, если разрешено только чтение и остальные действия
            запрещены, иначе `False`.
        """

        return (
            self.can_read
            and not self.can_download
            and not self.can_write
            and not self.can_delete
            and not self.can_share
        )

    @property
    def is_owner_like(self) -> bool:
        """Проверяет, включает ли разрешение все доступные действия.

        Returns:
            `True`, если включены чтение, скачивание, запись, удаление
            и передача доступа, иначе `False`.
        """

        return all(
            (
                self.can_read,
                self.can_download,
                self.can_write,
                self.can_delete,
                self.can_share,
            )
        )

    # -------------------------------------------------------------------------
    # Проверки доступа
    # -------------------------------------------------------------------------

    def is_expired_at(self, moment: datetime) -> bool:
        """Проверяет, истёк ли срок действия разрешения.

        Args:
            moment: Дата и время для проверки срока действия.

        Returns:
            `True`, если срок действия разрешения истёк к указанному моменту,
            иначе `False`.
        """

        return self.expires_at is not None and self.expires_at <= moment

    def is_active_at(self, moment: datetime) -> bool:
        """Проверяет, активно ли разрешение в указанный момент.

        Разрешение активно, когда оно не отозвано, срок действия не истёк
        и включено хотя бы одно действие.

        Args:
            moment: Дата и время для проверки активности разрешения.

        Returns:
            `True`, если разрешение может использоваться, иначе `False`.
        """

        return (
            self.revoked_at is None
            and not self.is_expired_at(moment)
            and self.has_any_permission
        )

    def allows_read_at(self, moment: datetime) -> bool:
        """Проверяет, разрешено ли чтение в указанный момент.

        Args:
            moment: Дата и время для проверки доступа.

        Returns:
            `True`, если разрешение активно и чтение разрешено, иначе `False`.
        """

        return self.is_active_at(moment) and self.can_read

    def allows_download_at(self, moment: datetime) -> bool:
        """Проверяет, разрешено ли скачивание в указанный момент.

        Args:
            moment: Дата и время для проверки доступа.

        Returns:
            `True`, если разрешение активно и скачивание разрешено,
            иначе `False`.
        """

        return self.is_active_at(moment) and self.can_download

    def allows_write_at(self, moment: datetime) -> bool:
        """Проверяет, разрешена ли запись в указанный момент.

        Args:
            moment: Дата и время для проверки доступа.

        Returns:
            `True`, если разрешение активно и запись разрешена, иначе `False`.
        """

        return self.is_active_at(moment) and self.can_write

    def allows_delete_at(self, moment: datetime) -> bool:
        """Проверяет, разрешено ли удаление в указанный момент.

        Args:
            moment: Дата и время для проверки доступа.

        Returns:
            `True`, если разрешение активно и удаление разрешено, иначе `False`.
        """

        return self.is_active_at(moment) and self.can_delete

    def allows_share_at(self, moment: datetime) -> bool:
        """Проверяет, разрешена ли передача доступа в указанный момент.

        Args:
            moment: Дата и время для проверки доступа.

        Returns:
            `True`, если разрешение активно и передача доступа разрешена,
            иначе `False`.
        """

        return self.is_active_at(moment) and self.can_share

    # -------------------------------------------------------------------------
    # Методы изменения состояния
    # -------------------------------------------------------------------------

    def revoke(
        self,
        reason: str | None = None,
        revoked_at: datetime | None = None,
    ) -> None:
        """Отзывает разрешение.

        Устанавливает дату отзыва разрешения и сохраняет причину отзыва.
        Если дата отзыва не передана, используется текущее UTC-время.

        Args:
            reason: Причина отзыва разрешения.
            revoked_at: Дата и время отзыва. Если не передано, используется
                текущее UTC-время.
        """

        self.revoked_at = revoked_at or datetime.now(UTC)
        self.revoke_reason = reason

    def update_permissions(
        self,
        *,
        can_read: bool | None = None,
        can_download: bool | None = None,
        can_write: bool | None = None,
        can_delete: bool | None = None,
        can_share: bool | None = None,
        permission_level: PermissionLevel | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """Обновляет набор разрешений.

        Аргументы со значением `None` для флагов не изменяют соответствующий
        флаг. `expires_at` обновляется всегда, включая установку в `None`.

        Args:
            can_read: Новое значение флага чтения.
            can_download: Новое значение флага скачивания.
            can_write: Новое значение флага записи.
            can_delete: Новое значение флага удаления.
            can_share: Новое значение флага передачи доступа.
            permission_level: Новый обобщённый уровень доступа.
            expires_at: Новая дата истечения срока действия разрешения.
        """

        if can_read is not None:
            self.can_read = can_read

        if can_download is not None:
            self.can_download = can_download

        if can_write is not None:
            self.can_write = can_write

        if can_delete is not None:
            self.can_delete = can_delete

        if can_share is not None:
            self.can_share = can_share

        if permission_level is not None:
            self.permission_level = permission_level

        self.expires_at = expires_at

    def sync_permission_level_from_flags(self) -> None:
        """Синхронизирует `permission_level` с текущими boolean-флагами.

        Используется, если разрешения изменялись напрямую через флаги.
        Метод подбирает наиболее близкий обобщённый уровень доступа на основе
        включённых действий.
        """

        if self.is_owner_like:
            self.permission_level = PermissionLevel.OWNER
            return

        if self.can_read and not any(
            (self.can_download, self.can_write, self.can_delete, self.can_share)
        ):
            self.permission_level = PermissionLevel.READ
            return

        if (
            self.can_read
            and self.can_download
            and not any((self.can_write, self.can_delete, self.can_share))
        ):
            self.permission_level = PermissionLevel.DOWNLOAD
            return

        if (
            self.can_read
            and self.can_download
            and self.can_write
            and not any((self.can_delete, self.can_share))
        ):
            self.permission_level = PermissionLevel.WRITE
            return

        if (
            self.can_read
            and self.can_download
            and self.can_write
            and self.can_delete
            and not self.can_share
        ):
            self.permission_level = PermissionLevel.DELETE
            return

        self.permission_level = PermissionLevel.READ

    def __repr__(self) -> str:
        """Возвращает строковое представление разрешения.

        Returns:
            Строковое представление `NodePermission` с основными полями
            и флагами доступа.
        """

        return (
            f"<NodePermission("
            f"id={self.id}, "
            f"node_id={self.node_id}, "
            f"user_id={self.user_id}, "
            f"permission_level={self.permission_level.value!r}, "
            f"can_read={self.can_read}, "
            f"can_download={self.can_download}, "
            f"can_write={self.can_write}, "
            f"can_delete={self.can_delete}, "
            f"can_share={self.can_share}, "
            f"revoked_at={self.revoked_at}"
            f")>"
        )
