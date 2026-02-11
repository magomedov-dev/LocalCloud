from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base
from database.models.enums import SessionStatus
from database.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from database.models.users import User


class RefreshToken(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Refresh-токен пользователя.

    Представляет refresh-токен, выданный пользователю после успешной
    аутентификации. Модель хранит хэш токена, статус сессии, срок действия,
    сведения об отзыве, ротации, устройстве и клиентском окружении.

    Refresh-токены используются для:
        - продления пользовательской сессии;
        - выпуска новых access-токенов;
        - ротации refresh-токенов;
        - отзыва сессий;
        - выхода из системы на одном или всех устройствах;
        - обнаружения повторного использования старого токена.

    Attributes:
        user_id: Пользователь, которому принадлежит refresh-токен.
        token_hash: Безопасный хэш refresh-токена.
        status: Статус сессии, связанной с refresh-токеном.
        expires_at: Дата и время истечения срока действия refresh-токена.
        revoked_at: Дата и время явного отзыва refresh-токена.
        revoke_reason: Причина отзыва refresh-токена.
        replaced_by_token_id: Новый refresh-токен, заменивший текущий
            при ротации.
        parent_token_id: Предыдущий refresh-токен, из которого получен текущий.
        ip_address: IP-адрес, с которого был выдан refresh-токен.
        user_agent: User-Agent клиентского устройства или браузера.
        device_name: Условное имя устройства или клиента.
        is_active: Признак активности refresh-токена.
        user: Пользователь, которому принадлежит refresh-токен.
        replaced_by_token: Новый refresh-токен, заменивший текущий.
        parent_token: Предыдущий refresh-токен, из которого получен текущий.

    Table:
        refresh_tokens
    """

    __tablename__ = "refresh_tokens"

    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_token_hash", "token_hash"),
        Index("ix_refresh_tokens_user_id_is_active", "user_id", "is_active"),
        Index("ix_refresh_tokens_user_id_status", "user_id", "status"),
        Index("ix_refresh_tokens_user_id_expires_at", "user_id", "expires_at"),
        Index("ix_refresh_tokens_active_expires_at", "is_active", "expires_at"),
        Index("ix_refresh_tokens_status_expires_at", "status", "expires_at"),
        Index("ix_refresh_tokens_revoked_at", "revoked_at"),
        Index("ix_refresh_tokens_replaced_by_token_id", "replaced_by_token_id"),
        Index("ix_refresh_tokens_parent_token_id", "parent_token_id"),
        Index("ix_refresh_tokens_created_at", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        comment="Пользователь, которому принадлежит refresh-токен.",
    )

    token_hash: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False,
        unique=True,
        comment="Безопасный хэш refresh-токена.",
    )

    status: Mapped[SessionStatus] = mapped_column(
        Enum(
            SessionStatus,
            name="session_status",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=SessionStatus.ACTIVE,
        server_default=SessionStatus.ACTIVE.value,
        comment="Статус сессии, связанной с refresh-токеном.",
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Дата и время истечения срока действия refresh-токена.",
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время явного отзыва refresh-токена.",
    )

    revoke_reason: Mapped[str | None] = mapped_column(
        String(length=512),
        nullable=True,
        comment="Причина отзыва refresh-токена.",
    )

    replaced_by_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "refresh_tokens.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        comment="Новый refresh-токен, заменивший текущий при ротации.",
    )

    parent_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "refresh_tokens.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        comment="Предыдущий refresh-токен, из которого получен текущий.",
    )

    ip_address: Mapped[str | None] = mapped_column(
        INET,
        nullable=True,
        comment="IP-адрес, с которого был выдан refresh-токен.",
    )

    user_agent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="User-Agent клиентского устройства или браузера.",
    )

    device_name: Mapped[str | None] = mapped_column(
        String(length=255),
        nullable=True,
        comment="Условное имя устройства или клиента.",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
        comment="Признак активности refresh-токена.",
    )

    # -------------------------------------------------------------------------
    # Связи
    # -------------------------------------------------------------------------

    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="refresh_tokens",
        lazy="selectin",
    )

    replaced_by_token: Mapped[RefreshToken | None] = relationship(
        "RefreshToken",
        foreign_keys=[replaced_by_token_id],
        remote_side="RefreshToken.id",
        lazy="selectin",
        post_update=True,
    )

    parent_token: Mapped[RefreshToken | None] = relationship(
        "RefreshToken",
        foreign_keys=[parent_token_id],
        remote_side="RefreshToken.id",
        lazy="selectin",
        post_update=True,
    )

    # -------------------------------------------------------------------------
    # Вспомогательные свойства
    # -------------------------------------------------------------------------

    @property
    def is_revoked(self) -> bool:
        """Проверяет, был ли токен явно отозван.

        Returns:
            `True`, если у токена задано время отзыва или статус равен
            `SessionStatus.REVOKED`, иначе `False`.
        """

        return self.revoked_at is not None or self.status == SessionStatus.REVOKED

    @property
    def is_replaced(self) -> bool:
        """Проверяет, был ли токен заменён другим refresh-токеном.

        Returns:
            `True`, если у токена задан идентификатор заменяющего токена,
            иначе `False`.
        """

        return self.replaced_by_token_id is not None

    @property
    def is_expired(self) -> bool:
        """Проверяет, помечен ли токен как истёкший.

        Для проверки срока действия относительно конкретного времени
        используйте `is_expired_at`.

        Returns:
            `True`, если статус токена равен `SessionStatus.EXPIRED`,
            иначе `False`.
        """

        return self.status == SessionStatus.EXPIRED

    def is_expired_at(self, moment: datetime) -> bool:
        """Проверяет, истёк ли срок действия токена к указанному моменту.

        Args:
            moment: Дата и время для сравнения со сроком действия токена.

        Returns:
            `True`, если срок действия токена истёк к указанному моменту,
            иначе `False`.
        """

        return self.expires_at <= moment

    def can_be_used_at(self, moment: datetime) -> bool:
        """Проверяет, можно ли использовать токен в указанный момент.

        Токен можно использовать, только если:
            - он активен;
            - имеет статус `ACTIVE`;
            - не был отозван;
            - не был заменён;
            - срок его действия не истёк.

        Args:
            moment: Дата и время, на которое проверяется валидность токена.

        Returns:
            `True`, если токен можно использовать в указанный момент,
            иначе `False`.
        """

        return (
            self.is_active
            and self.status == SessionStatus.ACTIVE
            and self.revoked_at is None
            and self.replaced_by_token_id is None
            and self.expires_at > moment
        )

    # -------------------------------------------------------------------------
    # Методы изменения состояния
    # -------------------------------------------------------------------------

    def revoke(
        self,
        reason: str | None = None,
        revoked_at: datetime | None = None,
    ) -> None:
        """Отзывает refresh-токен.

        Переводит токен в статус `REVOKED`, снимает признак активности,
        сохраняет время и причину отзыва. Если время отзыва не передано,
        используется текущее UTC-время.

        Args:
            reason: Причина отзыва токена.
            revoked_at: Дата и время отзыва. Если не передано, используется
                текущее UTC-время.
        """

        self.status = SessionStatus.REVOKED
        self.is_active = False
        self.revoked_at = revoked_at or datetime.now(UTC)
        self.revoke_reason = reason

    def mark_expired(self) -> None:
        """Помечает refresh-токен как истёкший."""

        self.status = SessionStatus.EXPIRED
        self.is_active = False

    def deactivate(self) -> None:
        """Деактивирует refresh-токен без указания причины отзыва."""

        self.is_active = False

    def replace_with(
        self,
        new_token: RefreshToken,
        replaced_at: datetime | None = None,
    ) -> None:
        """Помечает текущий токен как заменённый новым токеном.

        Используется при ротации refresh-токенов. Текущий токен отзывается,
        связывается с новым токеном, а новый токен получает ссылку на текущий
        как на родительский.

        Args:
            new_token: Новый refresh-токен.
            replaced_at: Время замены. Если не передано, используется текущее
                UTC-время.
        """

        self.replaced_by_token = new_token
        self.replaced_by_token_id = new_token.id
        self.status = SessionStatus.REVOKED
        self.is_active = False
        self.revoked_at = replaced_at or datetime.now(UTC)
        self.revoke_reason = "Заменено ротацией токена"

        new_token.parent_token = self
        new_token.parent_token_id = self.id

    def __repr__(self) -> str:
        """Возвращает строковое представление refresh-токена.

        Returns:
            Строковое представление `RefreshToken` с основными полями.
        """

        return (
            f"<RefreshToken("
            f"id={self.id}, "
            f"user_id={self.user_id}, "
            f"status={self.status.value!r}, "
            f"expires_at={self.expires_at}, "
            f"revoked_at={self.revoked_at}, "
            f"is_active={self.is_active}"
            f")>"
        )
