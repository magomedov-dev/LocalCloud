from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base
from database.models.enums import SystemRole
from database.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from database.models.users import User


class Role(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Роль пользователя.

    Роли определяют общий уровень доступа пользователя в системе.

    Базовые системные роли:
        - `user`: обычный пользователь;
        - `admin`: администратор.

    Attributes:
        name: Уникальное техническое имя роли.
        code: Стабильный код роли для бизнес-логики.
        display_name: Человекочитаемое имя роли.
        description: Описание назначения роли.
        is_system: Признак системной роли, которую нельзя удалить обычным
            способом.
        is_active: Признак активности роли.
        user_roles: Связи пользователей с этой ролью.
        users: Пользователи, которым назначена эта роль.

    Table:
        roles
    """

    __tablename__ = "roles"

    __table_args__ = (
        Index("ix_roles_name", "name"),
        Index("ix_roles_code", "code"),
        Index("ix_roles_is_system", "is_system"),
        Index("ix_roles_is_active", "is_active"),
        Index("ix_roles_created_at", "created_at"),
        UniqueConstraint("name", name="uq_roles_name"),
        UniqueConstraint("code", name="uq_roles_code"),
    )

    name: Mapped[str] = mapped_column(
        String(length=64),
        nullable=False,
        comment="Уникальное техническое имя роли.",
    )

    code: Mapped[str] = mapped_column(
        String(length=64),
        nullable=False,
        comment="Стабильный код роли для бизнес-логики.",
    )

    display_name: Mapped[str] = mapped_column(
        String(length=128),
        nullable=False,
        comment="Человекочитаемое имя роли.",
    )

    description: Mapped[str | None] = mapped_column(
        String(length=512),
        nullable=True,
        comment="Описание назначения роли.",
    )

    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        comment="Признак системной роли, которую нельзя удалить обычным способом.",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        comment="Признак активности роли.",
    )

    # -------------------------------------------------------------------------
    # Связи
    # -------------------------------------------------------------------------

    user_roles: Mapped[list[UserRole]] = relationship(
        "UserRole",
        foreign_keys="UserRole.role_id",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    users: Mapped[list[User]] = relationship(
        "User",
        secondary="user_roles",
        primaryjoin="Role.id == UserRole.role_id",
        secondaryjoin="User.id == UserRole.user_id",
        back_populates="roles",
        viewonly=True,
        lazy="selectin",
    )

    # -------------------------------------------------------------------------
    # Фабричные методы
    # -------------------------------------------------------------------------

    @classmethod
    def create_user_role(cls) -> Role:
        """Создаёт стандартную роль обычного пользователя.

        Returns:
            Системная роль обычного пользователя.
        """

        return cls(
            name=SystemRole.USER.value,
            code=SystemRole.USER.value,
            display_name="Пользователь",
            description="Базовая роль пользователя LocalCloud.",
            is_system=True,
            is_active=True,
        )

    @classmethod
    def create_admin_role(cls) -> Role:
        """Создаёт стандартную роль администратора.

        Returns:
            Системная роль администратора.
        """

        return cls(
            name=SystemRole.ADMIN.value,
            code=SystemRole.ADMIN.value,
            display_name="Администратор",
            description="Роль администратора LocalCloud с расширенными правами.",
            is_system=True,
            is_active=True,
        )

    # -------------------------------------------------------------------------
    # Удобные проверки
    # -------------------------------------------------------------------------

    def activate(self) -> None:
        """Активирует роль."""

        self.is_active = True

    def deactivate(self) -> None:
        """Деактивирует роль."""

        self.is_active = False

    def __repr__(self) -> str:
        """Возвращает строковое представление роли.

        Returns:
            Строковое представление `Role` с основными полями.
        """

        return (
            f"<Role("
            f"id={self.id}, "
            f"name={self.name!r}, "
            f"code={self.code!r}, "
            f"display_name={self.display_name!r}, "
            f"is_system={self.is_system}, "
            f"is_active={self.is_active}"
            f")>"
        )


class UserRole(Base):
    """Связь пользователя с ролью.

    Таблица связывает пользователей и роли отношением «многие ко многим».
    Дополнительно хранит служебную информацию о назначении роли.

    Attributes:
        user_id: Пользователь, которому назначена роль.
        role_id: Назначенная роль.
        assigned_at: Дата и время назначения роли.
        assigned_by: Администратор или системный пользователь, назначивший роль.
        user: Пользователь, которому назначена роль.
        role: Назначенная роль.
        assigner: Пользователь, назначивший роль.

    Table:
        user_roles
    """

    __tablename__ = "user_roles"

    __table_args__ = (
        Index("ix_user_roles_user_id", "user_id"),
        Index("ix_user_roles_role_id", "role_id"),
        Index("ix_user_roles_assigned_by", "assigned_by"),
        Index("ix_user_roles_assigned_at", "assigned_at"),
        UniqueConstraint(
            "user_id",
            "role_id",
            name="uq_user_roles_user_id_role_id",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
        comment="Пользователь, которому назначена роль.",
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "roles.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
        comment="Назначенная роль.",
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Дата и время назначения роли.",
    )

    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        comment="Администратор или системный пользователь, назначивший роль.",
    )

    # -------------------------------------------------------------------------
    # Связи
    # -------------------------------------------------------------------------

    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="user_roles",
        lazy="selectin",
    )

    role: Mapped[Role] = relationship(
        "Role",
        foreign_keys=[role_id],
        back_populates="user_roles",
        lazy="selectin",
    )

    assigner: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[assigned_by],
        back_populates="assigned_user_roles",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        """Возвращает строковое представление связи пользователя с ролью.

        Returns:
            Строковое представление `UserRole` с основными полями.
        """

        return (
            f"<UserRole("
            f"user_id={self.user_id}, "
            f"role_id={self.role_id}, "
            f"assigned_by={self.assigned_by}, "
            f"assigned_at={self.assigned_at}"
            f")>"
        )
