from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base
from database.models.enums import SystemRole, UserStatus
from database.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from database.models.audit import AuditLog
    from database.models.filesystem import FileSystemNode
    from database.models.links import PublicLink
    from database.models.quotas import UserQuota
    from database.models.registration import RegistrationRequest
    from database.models.roles import Role, UserRole
    from database.models.tasks import BackgroundTask
    from database.models.tokens import RefreshToken


class User(Base, TimestampMixin):
    """Пользователь приложения.

    Представляет зарегистрированного пользователя системы LocalCloud.

    Пользователь может:
        - проходить аутентификацию;
        - иметь одну или несколько ролей;
        - владеть файлами и папками;
        - создавать публичные ссылки;
        - иметь refresh-токены;
        - иметь индивидуальную квоту хранилища;
        - выполнять действия, подлежащие аудиту.

    Attributes:
        id: Уникальный идентификатор пользователя.
        email: Адрес электронной почты пользователя.
        username: Уникальное имя пользователя, отображаемое в системе.
        password_hash: Хэшированный пароль пользователя.
        status: Текущий статус учётной записи.
        is_email_verified: Признак подтверждения адреса электронной почты.
        last_login_at: Дата и время последнего успешного входа в систему.
        approved_at: Дата и время одобрения регистрации пользователя.
        blocked_at: Дата и время блокировки пользователя.
        rejected_at: Дата и время отклонения регистрации пользователя.
        deleted_at: Дата и время логического удаления пользователя.
        block_reason: Причина блокировки пользователя.
        rejection_reason: Причина отклонения регистрации пользователя.
        user_roles: Связи пользователя с ролями.
        roles: Активные и неактивные роли пользователя.
        assigned_user_roles: Роли, назначенные этим пользователем другим
            пользователям.
        refresh_tokens: Refresh-токены пользователя.
        registration_requests: Заявки на регистрацию, связанные с созданием
            этого пользователя.
        reviewed_registration_requests: Заявки на регистрацию, рассмотренные
            этим пользователем.
        file_system_nodes: Файлы и папки, принадлежащие пользователю.
        public_links: Публичные ссылки, созданные пользователем.
        quota: Индивидуальная квота пользователя.
        audit_logs: Записи аудита, связанные с пользователем.
        background_tasks: Фоновые задачи, инициированные пользователем.

    Table:
        users
    """

    __tablename__ = "users"

    __table_args__ = (
        Index("ix_users_email_status", "email", "status"),
        Index("ix_users_username_status", "username", "status"),
        Index("ix_users_status_created_at", "status", "created_at"),
        Index("ix_users_last_login_at", "last_login_at"),
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Уникальный идентификатор пользователя.",
    )

    email: Mapped[str] = mapped_column(
        String(length=320),
        nullable=False,
        comment="Адрес электронной почты пользователя.",
    )

    username: Mapped[str] = mapped_column(
        String(length=64),
        nullable=False,
        comment="Уникальное имя пользователя, отображаемое в системе.",
    )

    password_hash: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False,
        comment="Хэшированный пароль пользователя.",
    )

    status: Mapped[UserStatus] = mapped_column(
        Enum(
            UserStatus,
            name="user_status",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=UserStatus.PENDING,
        server_default=UserStatus.PENDING.value,
        comment="Текущий статус учётной записи.",
    )

    is_email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Признак подтверждения адреса электронной почты.",
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время последнего успешного входа в систему.",
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время одобрения регистрации пользователя.",
    )

    blocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время блокировки пользователя.",
    )

    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время отклонения регистрации пользователя.",
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Дата и время логического удаления пользователя.",
    )

    block_reason: Mapped[str | None] = mapped_column(
        String(length=512),
        nullable=True,
        comment="Причина блокировки пользователя.",
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        String(length=512),
        nullable=True,
        comment="Причина отклонения регистрации пользователя.",
    )

    # -------------------------------------------------------------------------
    # Связи
    # -------------------------------------------------------------------------

    user_roles: Mapped[list[UserRole]] = relationship(
        "UserRole",
        foreign_keys="UserRole.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary="user_roles",
        primaryjoin="User.id == UserRole.user_id",
        secondaryjoin="Role.id == UserRole.role_id",
        back_populates="users",
        viewonly=True,
        lazy="selectin",
    )

    assigned_user_roles: Mapped[list[UserRole]] = relationship(
        "UserRole",
        foreign_keys="UserRole.assigned_by",
        back_populates="assigner",
        lazy="selectin",
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        "RefreshToken",
        foreign_keys="RefreshToken.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    registration_requests: Mapped[list[RegistrationRequest]] = relationship(
        "RegistrationRequest",
        foreign_keys="RegistrationRequest.created_user_id",
        back_populates="created_user",
        lazy="selectin",
    )

    reviewed_registration_requests: Mapped[list[RegistrationRequest]] = relationship(
        "RegistrationRequest",
        foreign_keys="RegistrationRequest.reviewed_by",
        back_populates="reviewer",
        lazy="selectin",
    )

    file_system_nodes: Mapped[list[FileSystemNode]] = relationship(
        "FileSystemNode",
        foreign_keys="FileSystemNode.owner_id",
        back_populates="owner",
        lazy="selectin",
    )

    public_links: Mapped[list[PublicLink]] = relationship(
        "PublicLink",
        foreign_keys="PublicLink.created_by",
        back_populates="creator",
        lazy="selectin",
    )

    quota: Mapped[UserQuota | None] = relationship(
        "UserQuota",
        foreign_keys="UserQuota.user_id",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    audit_logs: Mapped[list[AuditLog]] = relationship(
        "AuditLog",
        foreign_keys="AuditLog.user_id",
        back_populates="user",
        lazy="selectin",
    )

    background_tasks: Mapped[list[BackgroundTask]] = relationship(
        "BackgroundTask",
        foreign_keys="BackgroundTask.created_by",
        back_populates="creator",
        lazy="selectin",
    )

    # -------------------------------------------------------------------------
    # Вспомогательные свойства
    # -------------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """Проверяет, может ли пользователь использовать систему.

        Returns:
            `True`, если пользователь находится в статусе `ACTIVE`,
            иначе `False`.
        """

        return self.status == UserStatus.ACTIVE

    @property
    def is_blocked(self) -> bool:
        """Проверяет, заблокирована ли учётная запись пользователя.

        Returns:
            `True`, если пользователь находится в статусе `BLOCKED`,
            иначе `False`.
        """

        return self.status == UserStatus.BLOCKED

    @property
    def is_pending(self) -> bool:
        """Проверяет, ожидает ли пользователь одобрения.

        Returns:
            `True`, если пользователь находится в статусе `PENDING`,
            иначе `False`.
        """

        return self.status == UserStatus.PENDING

    @property
    def is_rejected(self) -> bool:
        """Проверяет, отклонена ли регистрация пользователя.

        Returns:
            `True`, если пользователь находится в статусе `REJECTED`,
            иначе `False`.
        """

        return self.status == UserStatus.REJECTED

    @property
    def is_deleted(self) -> bool:
        """Проверяет, удалена ли учётная запись логически.

        Returns:
            `True`, если пользователь находится в статусе `DELETED`,
            иначе `False`.
        """

        return self.status == UserStatus.DELETED

    @property
    def can_login(self) -> bool:
        """Проверяет, имеет ли пользователь право войти в систему.

        Returns:
            `True`, если пользователь активен и не удалён, иначе `False`.
        """

        return self.status == UserStatus.ACTIVE and not self.is_deleted

    @property
    def role_codes(self) -> set[str]:
        """Возвращает множество кодов активных ролей пользователя.

        Свойство работает корректно, если связь `roles` уже загружена.

        Returns:
            Множество кодов активных ролей пользователя.
        """

        return {role.code for role in self.roles if role.is_active}

    @property
    def is_admin(self) -> bool:
        """Проверяет, есть ли у пользователя роль администратора.

        Returns:
            `True`, если у пользователя есть активная роль `admin`,
            иначе `False`.
        """

        return SystemRole.ADMIN.value in self.role_codes

    @property
    def is_regular_user(self) -> bool:
        """Проверяет, есть ли у пользователя базовая роль пользователя.

        Returns:
            `True`, если у пользователя есть активная роль `user`,
            иначе `False`.
        """

        return SystemRole.USER.value in self.role_codes

    # -------------------------------------------------------------------------
    # Методы изменения состояния
    # -------------------------------------------------------------------------

    def mark_login(self, logged_in_at: datetime | None = None) -> None:
        """Обновляет время последнего успешного входа.

        Args:
            logged_in_at: Дата и время успешного входа. Если значение не
                передано, используется текущее UTC-время.
        """

        self.last_login_at = logged_in_at or datetime.now(UTC)

    def verify_email(self) -> None:
        """Помечает адрес электронной почты как подтверждённый."""

        self.is_email_verified = True

    def approve(self, approved_at: datetime | None = None) -> None:
        """Одобряет пользователя и переводит его в активное состояние.

        Переводит пользователя в статус `ACTIVE`, сохраняет время одобрения
        и очищает данные отклонения регистрации.

        Args:
            approved_at: Дата и время одобрения пользователя. Если значение не
                передано, используется текущее UTC-время.
        """

        self.status = UserStatus.ACTIVE
        self.approved_at = approved_at or datetime.now(UTC)
        self.rejected_at = None
        self.rejection_reason = None

    def reject(
        self,
        reason: str | None = None,
        rejected_at: datetime | None = None,
    ) -> None:
        """Отклоняет регистрацию пользователя.

        Переводит пользователя в статус `REJECTED`, сохраняет время и причину
        отклонения регистрации.

        Args:
            reason: Причина отклонения регистрации пользователя.
            rejected_at: Дата и время отклонения. Если значение не передано,
                используется текущее UTC-время.
        """

        self.status = UserStatus.REJECTED
        self.rejected_at = rejected_at or datetime.now(UTC)
        self.rejection_reason = reason

    def block(
        self,
        reason: str | None = None,
        blocked_at: datetime | None = None,
    ) -> None:
        """Блокирует пользователя.

        Переводит пользователя в статус `BLOCKED`, сохраняет время и причину
        блокировки.

        Args:
            reason: Причина блокировки пользователя.
            blocked_at: Дата и время блокировки. Если значение не передано,
                используется текущее UTC-время.
        """

        self.status = UserStatus.BLOCKED
        self.blocked_at = blocked_at or datetime.now(UTC)
        self.block_reason = reason

    def unblock(self) -> None:
        """Снимает блокировку и возвращает пользователя в активное состояние."""

        self.status = UserStatus.ACTIVE
        self.blocked_at = None
        self.block_reason = None

    def mark_deleted(self, deleted_at: datetime | None = None) -> None:
        """Логически удаляет пользователя.

        Физическое удаление лучше выполнять только через отдельную
        административную процедуру, чтобы не нарушить аудит и связи.

        Args:
            deleted_at: Дата и время логического удаления. Если значение не
                передано, используется текущее UTC-время.
        """

        self.status = UserStatus.DELETED
        self.deleted_at = deleted_at or datetime.now(UTC)

    def change_password_hash(self, password_hash: str) -> None:
        """Обновляет хэш пароля пользователя.

        Args:
            password_hash: Новый хэш пароля пользователя.
        """

        self.password_hash = password_hash

    def has_role(self, role_code: str | SystemRole) -> bool:
        """Проверяет наличие активной роли у пользователя.

        Args:
            role_code: Код роли. Можно передать строку или `SystemRole`.

        Returns:
            `True`, если у пользователя есть указанная активная роль,
            иначе `False`.
        """

        normalized_role_code = (
            role_code.value if isinstance(role_code, SystemRole) else role_code
        )

        return normalized_role_code in self.role_codes

    def __repr__(self) -> str:
        """Возвращает строковое представление пользователя.

        Returns:
            Строковое представление `User` с основными полями.
        """

        return (
            f"<User("
            f"id={self.id}, "
            f"email={self.email!r}, "
            f"username={self.username!r}, "
            f"status={self.status.value!r}"
            f")>"
        )
