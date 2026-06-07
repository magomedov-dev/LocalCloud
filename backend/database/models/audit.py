from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base
from database.models.enums import AuditAction, AuditResourceType, AuditResult
from database.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from database.models.users import User


class AuditLog(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Журнал аудита.

    Представляет одно событие аудита в системе. События аудита используются
    для отслеживания действий аутентификации, регистрации, операций с файлами
    и папками, изменений разрешений, действий с публичными ссылками, событий
    квот, фоновых задач, проверок целостности хранилища, подозрительной
    активности и отказов доступа.

    Attributes:
        user_id: Пользователь, выполнивший действие. `None` означает системное
            действие.
        action: Тип действия, выполненного в системе.
        result: Результат выполнения действия.
        entity_type: Тип сущности, затронутой действием.
        entity_id: Идентификатор затронутой сущности.
        resource_type: Нормализованный тип ресурса для фильтрации событий
            аудита.
        request_id: Идентификатор HTTP-запроса, в рамках которого создано
            событие.
        correlation_id: Идентификатор корреляции для связывания нескольких
            событий.
        ip_address: IP-адрес, с которого было выполнено действие.
        user_agent: User-Agent клиента, выполнившего действие.
        message: Краткое человекочитаемое описание события.
        error_code: Машиночитаемый код ошибки, если действие завершилось
            неуспешно.
        metadata_: Дополнительные структурированные данные события аудита.
        user: Пользователь, связанный с событием аудита.

    Table:
        audit_logs
    """

    __tablename__ = "audit_logs"

    __table_args__ = (
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_result", "result"),
        Index("ix_audit_logs_entity_type", "entity_type"),
        Index("ix_audit_logs_entity_id", "entity_id"),
        Index("ix_audit_logs_request_id", "request_id"),
        Index("ix_audit_logs_correlation_id", "correlation_id"),
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_ip_address", "ip_address"),
        Index("ix_audit_logs_user_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
        Index("ix_audit_logs_result_created_at", "result", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index(
            "ix_audit_logs_entity_created_at",
            "entity_type",
            "entity_id",
            "created_at",
        ),
        Index(
            "ix_audit_logs_user_action_created_at",
            "user_id",
            "action",
            "created_at",
        ),
        Index(
            "ix_audit_logs_metadata_gin",
            "metadata",
            postgresql_using="gin",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        comment=(
            "Пользователь, выполнивший действие. None означает системное действие."
        ),
    )

    action: Mapped[AuditAction] = mapped_column(
        Enum(
            AuditAction,
            name="audit_action",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        comment="Тип действия, выполненного в системе.",
    )

    result: Mapped[AuditResult] = mapped_column(
        Enum(
            AuditResult,
            name="audit_result",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=AuditResult.SUCCESS,
        server_default=AuditResult.SUCCESS.value,
        comment="Результат выполнения действия.",
    )

    entity_type: Mapped[str | None] = mapped_column(
        String(length=128),
        nullable=True,
        comment="Тип сущности, затронутой действием.",
    )

    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Идентификатор затронутой сущности.",
    )

    resource_type: Mapped[AuditResourceType | None] = mapped_column(
        Enum(
            AuditResourceType,
            name="audit_resource_type",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=True,
        comment="Нормализованный тип ресурса для фильтрации событий аудита.",
    )

    request_id: Mapped[str | None] = mapped_column(
        String(length=128),
        nullable=True,
        comment="Идентификатор HTTP-запроса, в рамках которого создано событие.",
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(length=128),
        nullable=True,
        comment="Идентификатор корреляции для связывания нескольких событий.",
    )

    ip_address: Mapped[str | None] = mapped_column(
        INET,
        nullable=True,
        comment="IP-адрес, с которого было выполнено действие.",
    )

    user_agent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="User-Agent клиента, выполнившего действие.",
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Краткое человекочитаемое описание события.",
    )

    error_code: Mapped[str | None] = mapped_column(
        String(length=128),
        nullable=True,
        comment="Машиночитаемый код ошибки, если действие завершилось неуспешно.",
    )

    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Дополнительные структурированные данные события аудита.",
    )

    # -------------------------------------------------------------------------
    # Связи
    # -------------------------------------------------------------------------

    user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="audit_logs",
        lazy="selectin",
    )

    # -------------------------------------------------------------------------
    # Фабричные методы
    # -------------------------------------------------------------------------

    @classmethod
    def create_user_event(
        cls,
        *,
        user_id: uuid.UUID,
        action: AuditAction,
        result: AuditResult = AuditResult.SUCCESS,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        resource_type: AuditResourceType | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        message: str | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Создаёт событие аудита, связанное с пользователем.

        Args:
            user_id: Идентификатор пользователя, выполнившего действие.
            action: Тип действия, выполненного в системе.
            result: Результат выполнения действия.
            entity_type: Тип сущности, затронутой действием.
            entity_id: Идентификатор затронутой сущности.
            resource_type: Нормализованный тип ресурса.
            ip_address: IP-адрес, с которого было выполнено действие.
            user_agent: User-Agent клиента, выполнившего действие.
            request_id: Идентификатор HTTP-запроса.
            correlation_id: Идентификатор корреляции событий.
            message: Краткое человекочитаемое описание события.
            error_code: Машиночитаемый код ошибки.
            metadata: Дополнительные структурированные данные события аудита.

        Returns:
            Экземпляр `AuditLog` для пользовательского события.
        """

        return cls(
            user_id=user_id,
            action=action,
            result=result,
            entity_type=entity_type,
            entity_id=entity_id,
            resource_type=resource_type,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            correlation_id=correlation_id,
            message=message,
            error_code=error_code,
            metadata_=metadata,
        )

    @classmethod
    def create_system_event(
        cls,
        *,
        action: AuditAction,
        result: AuditResult = AuditResult.SUCCESS,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        resource_type: AuditResourceType | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        message: str | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Создаёт системное событие аудита.

        Используется для фоновых задач, очистки корзины, проверки целостности,
        резервного копирования и других операций без конкретного пользователя.

        Args:
            action: Тип действия, выполненного в системе.
            result: Результат выполнения действия.
            entity_type: Тип сущности, затронутой действием.
            entity_id: Идентификатор затронутой сущности.
            resource_type: Нормализованный тип ресурса.
            request_id: Идентификатор HTTP-запроса.
            correlation_id: Идентификатор корреляции событий.
            message: Краткое человекочитаемое описание события.
            error_code: Машиночитаемый код ошибки.
            metadata: Дополнительные структурированные данные события аудита.

        Returns:
            Экземпляр `AuditLog` для системного события.
        """

        return cls(
            user_id=None,
            action=action,
            result=result,
            entity_type=entity_type,
            entity_id=entity_id,
            resource_type=resource_type,
            request_id=request_id,
            correlation_id=correlation_id,
            message=message,
            error_code=error_code,
            metadata_=metadata,
        )

    @classmethod
    def create_failure_event(
        cls,
        *,
        action: AuditAction,
        error_code: str | None = None,
        message: str | None = None,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        resource_type: AuditResourceType | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Создаёт событие аудита для неуспешного действия.

        Args:
            action: Тип действия, выполненного в системе.
            error_code: Машиночитаемый код ошибки.
            message: Краткое человекочитаемое описание ошибки.
            user_id: Идентификатор пользователя, выполнившего действие.
            entity_type: Тип сущности, затронутой действием.
            entity_id: Идентификатор затронутой сущности.
            resource_type: Нормализованный тип ресурса.
            ip_address: IP-адрес, с которого было выполнено действие.
            user_agent: User-Agent клиента, выполнившего действие.
            request_id: Идентификатор HTTP-запроса.
            correlation_id: Идентификатор корреляции событий.
            metadata: Дополнительные структурированные данные события аудита.

        Returns:
            Экземпляр `AuditLog` для неуспешного события.
        """

        return cls(
            user_id=user_id,
            action=action,
            result=AuditResult.FAILURE,
            entity_type=entity_type,
            entity_id=entity_id,
            resource_type=resource_type,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            correlation_id=correlation_id,
            message=message,
            error_code=error_code,
            metadata_=metadata,
        )

    @classmethod
    def create_denied_event(
        cls,
        *,
        action: AuditAction,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        resource_type: AuditResourceType | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Создаёт событие аудита для отказа в доступе.

        Args:
            action: Тип действия, выполненного в системе.
            user_id: Идентификатор пользователя, выполнившего действие.
            entity_type: Тип сущности, затронутой действием.
            entity_id: Идентификатор затронутой сущности.
            resource_type: Нормализованный тип ресурса.
            ip_address: IP-адрес, с которого было выполнено действие.
            user_agent: User-Agent клиента, выполнившего действие.
            request_id: Идентификатор HTTP-запроса.
            correlation_id: Идентификатор корреляции событий.
            message: Краткое человекочитаемое описание события.
            metadata: Дополнительные структурированные данные события аудита.

        Returns:
            Экземпляр `AuditLog` для события отказа в доступе.
        """

        return cls(
            user_id=user_id,
            action=action,
            result=AuditResult.DENIED,
            entity_type=entity_type,
            entity_id=entity_id,
            resource_type=resource_type,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            correlation_id=correlation_id,
            message=message,
            metadata_=metadata,
        )

    # -------------------------------------------------------------------------
    # Вспомогательные свойства
    # -------------------------------------------------------------------------

    @property
    def is_system_action(self) -> bool:
        """Проверяет, создано ли событие системой.

        Returns:
            `True`, если событие аудита не связано с конкретным пользователем,
            иначе `False`.
        """

        return self.user_id is None

    @property
    def is_user_action(self) -> bool:
        """Проверяет, связано ли событие с пользователем.

        Returns:
            `True`, если у события указан пользователь, иначе `False`.
        """

        return self.user_id is not None

    @property
    def has_entity(self) -> bool:
        """Проверяет связь события с конкретной сущностью.

        Returns:
            `True`, если у события указаны тип и идентификатор сущности,
            иначе `False`.
        """

        return self.entity_type is not None and self.entity_id is not None

    @property
    def is_success(self) -> bool:
        """Проверяет, завершилось ли действие успешно.

        Returns:
            `True`, если результат события равен `AuditResult.SUCCESS`,
            иначе `False`.
        """

        return self.result == AuditResult.SUCCESS

    @property
    def is_failure(self) -> bool:
        """Проверяет, завершилось ли действие ошибкой.

        Returns:
            `True`, если результат события равен `AuditResult.FAILURE`,
            иначе `False`.
        """

        return self.result == AuditResult.FAILURE

    @property
    def is_denied(self) -> bool:
        """Проверяет, было ли действие запрещено.

        Returns:
            `True`, если результат события равен `AuditResult.DENIED`,
            иначе `False`.
        """

        return self.result == AuditResult.DENIED

    @property
    def is_warning(self) -> bool:
        """Проверяет, является ли событие предупреждением.

        Returns:
            `True`, если результат события равен `AuditResult.WARNING`,
            иначе `False`.
        """

        return self.result == AuditResult.WARNING

    @property
    def has_metadata(self) -> bool:
        """Проверяет наличие дополнительных metadata.

        Returns:
            `True`, если у события есть непустые metadata, иначе `False`.
        """

        return bool(self.metadata_)

    def __repr__(self) -> str:
        """Возвращает строковое представление записи аудита.

        Returns:
            Строковое представление `AuditLog` с основными полями события.
        """

        return (
            f"<AuditLog("
            f"id={self.id}, "
            f"user_id={self.user_id}, "
            f"action={self.action.value!r}, "
            f"result={self.result.value!r}, "
            f"entity_type={self.entity_type!r}, "
            f"entity_id={self.entity_id}, "
            f"created_at={self.created_at}"
            f")>"
        )
