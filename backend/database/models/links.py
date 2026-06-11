from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base
from database.models.enums import PublicLinkPermissionType, PublicLinkStatus
from database.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from database.models.filesystem import FileSystemNode
    from database.models.users import User


class PublicLink(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Публичная ссылка.

    Представляет публичную ссылку, созданную для файла или папки. Модель
    хранит токен доступа, тип разрешения, статус, срок действия, пароль,
    лимиты скачивания, счётчики просмотров, скачиваний и загрузок, а также
    сведения об отзыве ссылки.

    Основные сценарии использования:
        - предоставление публичного доступа к файлу или папке;
        - ограничение доступа паролем;
        - ограничение количества скачиваний;
        - ограничение доступа по сроку действия;
        - отзыв или временное отключение ссылки;
        - учёт просмотров, скачиваний и загрузок.

    Attributes:
        node_id: Узел файловой системы, доступ к которому предоставлен ссылкой.
        created_by: Пользователь, создавший публичную ссылку.
        token: Уникальный публичный токен ссылки.
        password_hash: Хэш пароля публичной ссылки. Открытый пароль
            не хранится.
        permission_type: Тип доступа, предоставляемый публичной ссылкой.
        status: Статус публичной ссылки.
        expires_at: Дата и время истечения срока действия публичной ссылки.
        max_downloads: Максимальное количество скачиваний. `None` означает
            отсутствие лимита.
        download_count: Текущее количество скачиваний по публичной ссылке.
        view_count: Количество просмотров публичной ссылки.
        upload_count: Количество загрузок через публичную ссылку.
        is_active: Признак активности публичной ссылки.
        revoked_at: Дата и время отзыва публичной ссылки.
        revoked_by: Пользователь, отозвавший публичную ссылку.
        revoke_reason: Причина отзыва публичной ссылки.
        last_accessed_at: Дата и время последнего обращения к публичной ссылке.
        last_downloaded_at: Дата и время последнего скачивания по публичной
            ссылке.
        last_uploaded_at: Дата и время последней загрузки через публичную
            ссылку.
        description: Необязательное описание публичной ссылки.
        node: Узел файловой системы, связанный с публичной ссылкой.
        creator: Пользователь, создавший публичную ссылку.
        revoker: Пользователь, отозвавший публичную ссылку.

    Table:
        public_links
    """

    __tablename__ = "public_links"

    __table_args__ = (
        UniqueConstraint("token", name="uq_public_links_token"),
        CheckConstraint(
            "max_downloads IS NULL OR max_downloads >= 0",
            name="ck_public_links_max_downloads_non_negative",
        ),
        CheckConstraint(
            "download_count >= 0",
            name="ck_public_links_download_count_non_negative",
        ),
        CheckConstraint(
            "max_downloads IS NULL OR download_count <= max_downloads",
            name="ck_public_links_download_count_lte_max_downloads",
        ),
        Index("ix_public_links_node_id", "node_id"),
        Index("ix_public_links_created_by", "created_by"),
        Index("ix_public_links_token", "token"),
        Index("ix_public_links_status", "status"),
        Index("ix_public_links_is_active", "is_active"),
        Index("ix_public_links_expires_at", "expires_at"),
        Index("ix_public_links_revoked_at", "revoked_at"),
        Index("ix_public_links_created_at", "created_at"),
        Index("ix_public_links_permission_type", "permission_type"),
        Index("ix_public_links_token_active", "token", "is_active"),
        Index("ix_public_links_node_active", "node_id", "is_active"),
        Index("ix_public_links_created_by_active", "created_by", "is_active"),
        Index("ix_public_links_expires_at_active", "expires_at", "is_active"),
        Index("ix_public_links_status_expires_at", "status", "expires_at"),
    )

    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_system_nodes.id", ondelete="CASCADE"),
        nullable=False,
        comment="Узел файловой системы, доступ к которому предоставлен ссылкой.",
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Пользователь, создавший публичную ссылку.",
    )

    token: Mapped[str] = mapped_column(
        String(length=128),
        nullable=False,
        comment="Уникальный публичный токен ссылки.",
    )

    password_hash: Mapped[str | None] = mapped_column(
        String(length=255),
        nullable=True,
        comment="Хэш пароля публичной ссылки. Открытый пароль не хранится.",
    )

    failed_password_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Число подряд идущих неверных паролей публичной ссылки.",
    )

    password_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Момент, до которого проверки пароля ссылки заблокированы "
            "после исчерпания попыток."
        ),
    )

    permission_type: Mapped[PublicLinkPermissionType] = mapped_column(
        Enum(
            PublicLinkPermissionType,
            name="public_link_permission_type",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=PublicLinkPermissionType.DOWNLOAD,
        server_default=PublicLinkPermissionType.DOWNLOAD.value,
        comment="Тип доступа, предоставляемый публичной ссылкой.",
    )

    status: Mapped[PublicLinkStatus] = mapped_column(
        Enum(
            PublicLinkStatus,
            name="public_link_status",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=PublicLinkStatus.ACTIVE,
        server_default=PublicLinkStatus.ACTIVE.value,
        comment="Статус публичной ссылки.",
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время истечения срока действия публичной ссылки.",
    )

    max_downloads: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Максимальное количество скачиваний. Null означает без лимита.",
    )

    download_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Текущее количество скачиваний по публичной ссылке.",
    )

    view_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Количество просмотров публичной ссылки.",
    )

    upload_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Количество загрузок через публичную ссылку.",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
        comment="Признак активности публичной ссылки.",
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время отзыва публичной ссылки.",
    )

    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Пользователь, отозвавший публичную ссылку.",
    )

    revoke_reason: Mapped[str | None] = mapped_column(
        String(length=512),
        nullable=True,
        comment="Причина отзыва публичной ссылки.",
    )

    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время последнего обращения к публичной ссылке.",
    )

    last_downloaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время последнего скачивания по публичной ссылке.",
    )

    last_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время последней загрузки через публичную ссылку.",
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Необязательное описание публичной ссылки.",
    )

    # -------------------------------------------------------------------------
    # Связи
    # -------------------------------------------------------------------------

    node: Mapped[FileSystemNode] = relationship(
        "FileSystemNode",
        foreign_keys=[node_id],
        back_populates="public_links",
        lazy="selectin",
    )

    creator: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[created_by],
        back_populates="public_links",
        lazy="selectin",
    )

    revoker: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[revoked_by],
        lazy="selectin",
    )

    # -------------------------------------------------------------------------
    # Вспомогательные свойства
    # -------------------------------------------------------------------------

    @property
    def is_revoked(self) -> bool:
        """Проверяет, была ли публичная ссылка отозвана вручную.

        Returns:
            `True`, если у ссылки задано время отзыва или статус равен
            `PublicLinkStatus.REVOKED`, иначе `False`.
        """

        return self.revoked_at is not None or self.status == PublicLinkStatus.REVOKED

    @property
    def is_disabled(self) -> bool:
        """Проверяет, отключена ли публичная ссылка.

        Returns:
            `True`, если статус ссылки равен `PublicLinkStatus.DISABLED`
            или признак активности снят, иначе `False`.
        """

        return self.status == PublicLinkStatus.DISABLED or not self.is_active

    @property
    def is_password_protected(self) -> bool:
        """Проверяет, защищена ли публичная ссылка паролем.

        Returns:
            `True`, если у ссылки сохранён хэш пароля, иначе `False`.
        """

        return self.password_hash is not None

    @property
    def has_download_limit(self) -> bool:
        """Проверяет наличие лимита скачиваний.

        Returns:
            `True`, если у ссылки задан максимальный лимит скачиваний,
            иначе `False`.
        """

        return self.max_downloads is not None

    @property
    def is_download_limit_reached(self) -> bool:
        """Проверяет, достигнут ли лимит скачиваний.

        Returns:
            `True`, если лимит задан и количество скачиваний больше или равно
            лимиту, иначе `False`.
        """

        return (
            self.max_downloads is not None and self.download_count >= self.max_downloads
        )

    @property
    def allows_view(self) -> bool:
        """Проверяет, позволяет ли ссылка просматривать данные.

        Returns:
            `True`, если тип доступа публичной ссылки допускает просмотр,
            иначе `False`.
        """

        return self.permission_type in {
            PublicLinkPermissionType.VIEW,
            PublicLinkPermissionType.DOWNLOAD,
        }

    @property
    def allows_download(self) -> bool:
        """Проверяет, позволяет ли ссылка скачивать данные.

        Returns:
            `True`, если тип доступа равен `PublicLinkPermissionType.DOWNLOAD`,
            иначе `False`.
        """

        return self.permission_type == PublicLinkPermissionType.DOWNLOAD

    @property
    def allows_upload(self) -> bool:
        """Проверяет, позволяет ли ссылка загружать файлы.

        Returns:
            `True`, если тип доступа равен `PublicLinkPermissionType.UPLOAD`,
            иначе `False`.
        """

        return self.permission_type == PublicLinkPermissionType.UPLOAD

    # -------------------------------------------------------------------------
    # Проверки доступности
    # -------------------------------------------------------------------------

    def is_expired_at(self, moment: datetime) -> bool:
        """Проверяет, истёк ли срок действия публичной ссылки.

        Args:
            moment: Момент времени для проверки.

        Returns:
            `True`, если срок действия публичной ссылки истёк к указанному
            моменту, иначе `False`.
        """

        return self.expires_at is not None and self.expires_at <= moment

    def is_available_at(self, moment: datetime) -> bool:
        """Проверяет, может ли публичная ссылка быть использована.

        Ссылка доступна, если она активна, не отключена, не отозвана, срок
        действия не истёк и лимит скачиваний не достигнут.

        Args:
            moment: Момент времени для проверки.

        Returns:
            `True`, если публичная ссылка может быть использована,
            иначе `False`.
        """

        return (
            self.is_active
            and self.status == PublicLinkStatus.ACTIVE
            and self.revoked_at is None
            and not self.is_expired_at(moment)
            and not self.is_download_limit_reached
        )

    def can_view_at(self, moment: datetime) -> bool:
        """Проверяет, разрешён ли просмотр в указанный момент.

        Args:
            moment: Момент времени для проверки.

        Returns:
            `True`, если публичная ссылка доступна и разрешает просмотр,
            иначе `False`.
        """

        return self.is_available_at(moment) and self.allows_view

    def can_download_at(self, moment: datetime) -> bool:
        """Проверяет, разрешено ли скачивание в указанный момент.

        Args:
            moment: Момент времени для проверки.

        Returns:
            `True`, если публичная ссылка доступна и разрешает скачивание,
            иначе `False`.
        """

        return self.is_available_at(moment) and self.allows_download

    def can_upload_at(self, moment: datetime) -> bool:
        """Проверяет, разрешена ли загрузка в указанный момент.

        Args:
            moment: Момент времени для проверки.

        Returns:
            `True`, если публичная ссылка доступна и разрешает загрузку,
            иначе `False`.
        """

        return self.is_available_at(moment) and self.allows_upload

    # -------------------------------------------------------------------------
    # Методы изменения состояния
    # -------------------------------------------------------------------------

    def mark_accessed(self, accessed_at: datetime | None = None) -> None:
        """Фиксирует обращение к публичной ссылке.

        Обновляет время последнего обращения и увеличивает счётчик просмотров.
        Если время обращения не передано, используется текущее UTC-время.

        Args:
            accessed_at: Дата и время обращения.
        """

        self.last_accessed_at = accessed_at or datetime.now(UTC)
        self.view_count += 1

    def register_download(self, downloaded_at: datetime | None = None) -> None:
        """Увеличивает счётчик скачиваний и фиксирует время скачивания.

        Проверяет лимит скачиваний, увеличивает счётчик скачиваний, сохраняет
        время последнего скачивания и синхронизирует время последнего обращения.

        Args:
            downloaded_at: Дата и время скачивания. Если значение не передано,
                используется текущее UTC-время.

        Raises:
            ValueError: Если лимит скачиваний уже достигнут.
        """

        if self.is_download_limit_reached:
            raise ValueError("Лимит скачиваний публичной ссылки достигнут.")

        self.download_count += 1
        self.last_downloaded_at = downloaded_at or datetime.now(UTC)
        self.last_accessed_at = self.last_downloaded_at

    def register_upload(self, uploaded_at: datetime | None = None) -> None:
        """Увеличивает счётчик загрузок через публичную ссылку.

        Обновляет количество загрузок, время последней загрузки и время
        последнего обращения к ссылке.

        Args:
            uploaded_at: Дата и время загрузки. Если значение не передано,
                используется текущее UTC-время.
        """

        self.upload_count += 1
        self.last_uploaded_at = uploaded_at or datetime.now(UTC)
        self.last_accessed_at = self.last_uploaded_at

    def revoke(
        self,
        revoked_by: uuid.UUID | None = None,
        reason: str | None = None,
        revoked_at: datetime | None = None,
    ) -> None:
        """Отзывает публичную ссылку.

        Переводит ссылку в статус `REVOKED`, снимает признак активности,
        сохраняет пользователя, причину и время отзыва. Если время отзыва
        не передано, используется текущее UTC-время.

        Args:
            revoked_by: Идентификатор пользователя, который отозвал ссылку.
            reason: Причина отзыва публичной ссылки.
            revoked_at: Дата и время отзыва.
        """

        self.status = PublicLinkStatus.REVOKED
        self.is_active = False
        self.revoked_by = revoked_by
        self.revoke_reason = reason
        self.revoked_at = revoked_at or datetime.now(UTC)

    def disable(self) -> None:
        """Временно отключает публичную ссылку без отзыва."""

        self.status = PublicLinkStatus.DISABLED
        self.is_active = False

    def activate(self) -> None:
        """Активирует публичную ссылку.

        Переводит ссылку в активный статус и устанавливает признак активности.
        Метод не снимает отзыв: отозванную ссылку нельзя активировать повторно.

        Raises:
            ValueError: Если публичная ссылка уже была отозвана.
        """

        if self.status == PublicLinkStatus.REVOKED:
            raise ValueError("Отозванную публичную ссылку нельзя активировать.")

        self.status = PublicLinkStatus.ACTIVE
        self.is_active = True

    def mark_expired(self) -> None:
        """Помечает публичную ссылку как истёкшую."""

        self.status = PublicLinkStatus.EXPIRED
        self.is_active = False

    def update_password_hash(self, password_hash: str | None) -> None:
        """Устанавливает или удаляет пароль публичной ссылки.

        Args:
            password_hash: Новый хэш пароля. Если передано `None`, пароль
                удаляется.
        """

        self.password_hash = password_hash

    def update_expiration(self, expires_at: datetime | None) -> None:
        """Обновляет срок действия публичной ссылки.

        Args:
            expires_at: Новая дата истечения срока действия. Если передано
                `None`, срок действия становится неограниченным.
        """

        self.expires_at = expires_at

    def update_download_limit(self, max_downloads: int | None) -> None:
        """Обновляет лимит скачиваний.

        Устанавливает новое максимальное количество скачиваний или снимает
        лимит, если передано `None`.

        Args:
            max_downloads: Новый лимит скачиваний. Если передано `None`,
                лимит скачиваний снимается.

        Raises:
            ValueError: Если новый лимит меньше текущего числа скачиваний.
        """

        if max_downloads is not None and max_downloads < self.download_count:
            raise ValueError(
                "Максимальное количество скачиваний не может быть меньше "
                "текущего количества скачиваний."
            )

        self.max_downloads = max_downloads

    def __repr__(self) -> str:
        """Возвращает строковое представление публичной ссылки.

        Returns:
            Строковое представление `PublicLink` с основными полями.
        """

        return (
            f"<PublicLink("
            f"id={self.id}, "
            f"node_id={self.node_id}, "
            f"created_by={self.created_by}, "
            f"permission_type={self.permission_type.value!r}, "
            f"status={self.status.value!r}, "
            f"is_active={self.is_active}, "
            f"expires_at={self.expires_at}, "
            f"download_count={self.download_count}"
            f")>"
        )
