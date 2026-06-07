from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base
from database.models.enums import RegistrationRequestStatus
from database.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from database.models.users import User


class RegistrationRequest(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Заявка на регистрацию пользователя.

    Представляет запрос пользователя на регистрацию в системе LocalCloud.

    Процесс регистрации:
        1. Пользователь отправляет заявку.
        2. Заявка сохраняется со статусом `PENDING`.
        3. Администратор одобряет или отклоняет заявку.
        4. При одобрении создаётся учётная запись пользователя.
        5. Созданный пользователь связывается с заявкой через `created_user_id`.

    Attributes:
        email: Адрес электронной почты, указанный в заявке.
        username: Имя пользователя, указанное в заявке.
        password_hash: Хэшированный пароль, указанный при регистрации.
        status: Текущий статус заявки на регистрацию.
        comment: Комментарий администратора при рассмотрении заявки.
        rejection_reason: Причина отклонения заявки.
        reviewed_at: Дата и время рассмотрения заявки.
        reviewed_by: Администратор, рассмотревший заявку.
        created_user_id: Учётная запись, созданная после одобрения заявки.
        reviewer: Администратор, рассмотревший заявку.
        created_user: Учётная запись, созданная после одобрения заявки.

    Table:
        registration_requests
    """

    __tablename__ = "registration_requests"

    __table_args__ = (
        Index(
            "ix_registration_requests_email_status",
            "email",
            "status",
        ),
        Index(
            "ix_registration_requests_username_status",
            "username",
            "status",
        ),
        Index(
            "ix_registration_requests_status_created_at",
            "status",
            "created_at",
        ),
        Index(
            "ix_registration_requests_reviewed_by",
            "reviewed_by",
        ),
        Index(
            "ix_registration_requests_created_user_id",
            "created_user_id",
        ),
        Index(
            "ix_registration_requests_reviewed_at",
            "reviewed_at",
        ),
        Index(
            "uq_registration_requests_pending_email",
            "email",
            unique=True,
            postgresql_where=("status = 'pending'"),
        ),
        Index(
            "uq_registration_requests_pending_username",
            "username",
            unique=True,
            postgresql_where=("status = 'pending'"),
        ),
    )

    email: Mapped[str] = mapped_column(
        String(length=320),
        nullable=False,
        comment="Адрес электронной почты, указанный в заявке.",
    )

    username: Mapped[str] = mapped_column(
        String(length=64),
        nullable=False,
        comment="Имя пользователя, указанное в заявке.",
    )

    password_hash: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False,
        comment="Хэшированный пароль, указанный при регистрации.",
    )

    status: Mapped[RegistrationRequestStatus] = mapped_column(
        Enum(
            RegistrationRequestStatus,
            name="registration_request_status",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=RegistrationRequestStatus.PENDING,
        server_default=RegistrationRequestStatus.PENDING.value,
        comment="Текущий статус заявки на регистрацию.",
    )

    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Комментарий администратора при рассмотрении заявки.",
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        String(length=512),
        nullable=True,
        comment="Причина отклонения заявки.",
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время рассмотрения заявки.",
    )

    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        comment="Администратор, рассмотревший заявку.",
    )

    created_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        comment="Учётная запись, созданная после одобрения заявки.",
    )

    # -------------------------------------------------------------------------
    # Связи
    # -------------------------------------------------------------------------

    reviewer: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[reviewed_by],
        back_populates="reviewed_registration_requests",
        lazy="selectin",
    )

    created_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[created_user_id],
        back_populates="registration_requests",
        lazy="selectin",
    )

    # -------------------------------------------------------------------------
    # Вспомогательные свойства
    # -------------------------------------------------------------------------

    @property
    def is_pending(self) -> bool:
        """Проверяет, ожидает ли заявка рассмотрения.

        Returns:
            `True`, если заявка находится в статусе `PENDING`, иначе `False`.
        """

        return self.status == RegistrationRequestStatus.PENDING

    @property
    def is_approved(self) -> bool:
        """Проверяет, одобрена ли заявка.

        Returns:
            `True`, если заявка находится в статусе `APPROVED`, иначе `False`.
        """

        return self.status == RegistrationRequestStatus.APPROVED

    @property
    def is_rejected(self) -> bool:
        """Проверяет, отклонена ли заявка.

        Returns:
            `True`, если заявка находится в статусе `REJECTED`, иначе `False`.
        """

        return self.status == RegistrationRequestStatus.REJECTED

    @property
    def is_cancelled(self) -> bool:
        """Проверяет, отменена ли заявка.

        Returns:
            `True`, если заявка находится в статусе `CANCELLED`, иначе `False`.
        """

        return self.status == RegistrationRequestStatus.CANCELLED

    @property
    def is_reviewed(self) -> bool:
        """Проверяет, была ли заявка рассмотрена.

        Returns:
            `True`, если у заявки задано время рассмотрения, иначе `False`.
        """

        return self.reviewed_at is not None

    @property
    def can_be_reviewed(self) -> bool:
        """Проверяет, можно ли рассмотреть заявку.

        Returns:
            `True`, если заявку можно одобрить или отклонить, иначе `False`.
        """

        return self.status == RegistrationRequestStatus.PENDING

    # -------------------------------------------------------------------------
    # Методы изменения состояния
    # -------------------------------------------------------------------------

    def approve(
        self,
        reviewer_id: uuid.UUID,
        created_user_id: uuid.UUID,
        comment: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> None:
        """Одобряет заявку на регистрацию.

        Переводит заявку в статус `APPROVED`, сохраняет администратора,
        созданную учётную запись, комментарий и время рассмотрения. Причина
        отклонения при этом очищается.

        Args:
            reviewer_id: Идентификатор администратора, одобрившего заявку.
            created_user_id: Идентификатор созданной учётной записи.
            comment: Необязательный комментарий администратора.
            reviewed_at: Время рассмотрения. Если не передано, используется
                текущее UTC-время.
        """

        self.status = RegistrationRequestStatus.APPROVED
        self.reviewed_by = reviewer_id
        self.created_user_id = created_user_id
        self.comment = comment
        self.rejection_reason = None
        self.reviewed_at = reviewed_at or datetime.now(UTC)

    def reject(
        self,
        reviewer_id: uuid.UUID,
        reason: str | None = None,
        comment: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> None:
        """Отклоняет заявку на регистрацию.

        Переводит заявку в статус `REJECTED`, сохраняет администратора,
        причину отклонения, комментарий и время рассмотрения.

        Args:
            reviewer_id: Идентификатор администратора, отклонившего заявку.
            reason: Причина отклонения.
            comment: Необязательный комментарий администратора.
            reviewed_at: Время рассмотрения. Если не передано, используется
                текущее UTC-время.
        """

        self.status = RegistrationRequestStatus.REJECTED
        self.reviewed_by = reviewer_id
        self.created_user_id = None
        self.rejection_reason = reason
        self.comment = comment
        self.reviewed_at = reviewed_at or datetime.now(UTC)

    def cancel(
        self,
        comment: str | None = None,
        cancelled_at: datetime | None = None,
    ) -> None:
        """Отменяет заявку на регистрацию.

        Обычно используется, если пользователь повторно отправил заявку,
        передумал регистрироваться или заявка стала неактуальной.

        Args:
            comment: Необязательный комментарий к отмене заявки.
            cancelled_at: Время отмены. Если не передано, используется текущее
                UTC-время.
        """

        self.status = RegistrationRequestStatus.CANCELLED
        self.comment = comment
        self.reviewed_at = cancelled_at or datetime.now(UTC)

    def reset_to_pending(self) -> None:
        """Возвращает заявку в статус ожидания.

        Метод полезен для административного исправления ошибочно отклонённой
        или отменённой заявки. При сбросе очищаются данные рассмотрения,
        созданного пользователя, комментарий и причина отклонения.
        """

        self.status = RegistrationRequestStatus.PENDING
        self.reviewed_by = None
        self.created_user_id = None
        self.reviewed_at = None
        self.comment = None
        self.rejection_reason = None

    def __repr__(self) -> str:
        """Возвращает строковое представление заявки на регистрацию.

        Returns:
            Строковое представление `RegistrationRequest` с основными полями.
        """

        return (
            f"<RegistrationRequest("
            f"id={self.id}, "
            f"email={self.email!r}, "
            f"username={self.username!r}, "
            f"status={self.status.value!r}"
            f")>"
        )
