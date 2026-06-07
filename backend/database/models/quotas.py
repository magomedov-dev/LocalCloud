from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base
from database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from database.models.users import User


class UserQuota(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Квота пользователя.

    Представляет лимиты ресурсов, назначенные конкретному пользователю,
    и текущие значения использования этих ресурсов.

    Основные сценарии использования:
        - проверка возможности загрузки файла;
        - запрет загрузки при превышении лимита хранилища;
        - ограничение максимального размера одного файла;
        - ограничение количества файлов;
        - ограничение количества публичных ссылок;
        - ограничение количества активных upload-сессий;
        - пересчёт использования при восстановлении или очистке корзины.

    Attributes:
        user_id: Пользователь, которому принадлежит квота.
        storage_limit_bytes: Максимальный размер хранилища пользователя
            в байтах.
        storage_used_bytes: Текущий использованный объём хранилища в байтах.
        max_file_size_bytes: Максимально допустимый размер одного файла
            в байтах.
        files_limit: Максимальное количество файлов. `None` означает
            отсутствие лимита.
        files_used: Текущее количество файлов пользователя.
        public_links_limit: Максимальное количество публичных ссылок. `None`
            означает отсутствие лимита.
        public_links_used: Текущее количество публичных ссылок пользователя.
        active_upload_sessions_limit: Максимальное количество активных
            upload-сессий. `None` означает отсутствие лимита.
        active_upload_sessions_used: Текущее количество активных upload-сессий
            пользователя.
        user: Пользователь, которому принадлежит квота.

    Table:
        user_quotas
    """

    __tablename__ = "user_quotas"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            name="uq_user_quotas_user_id",
        ),
        CheckConstraint(
            "storage_limit_bytes >= 0",
            name="ck_user_quotas_storage_limit_bytes_non_negative",
        ),
        CheckConstraint(
            "storage_used_bytes >= 0",
            name="ck_user_quotas_storage_used_bytes_non_negative",
        ),
        CheckConstraint(
            "storage_used_bytes <= storage_limit_bytes",
            name="ck_user_quotas_storage_used_lte_limit",
        ),
        CheckConstraint(
            "max_file_size_bytes >= 0",
            name="ck_user_quotas_max_file_size_bytes_non_negative",
        ),
        CheckConstraint(
            "files_used >= 0",
            name="ck_user_quotas_files_used_non_negative",
        ),
        CheckConstraint(
            "files_limit IS NULL OR files_limit >= 0",
            name="ck_user_quotas_files_limit_non_negative",
        ),
        CheckConstraint(
            "files_limit IS NULL OR files_used <= files_limit",
            name="ck_user_quotas_files_used_lte_limit",
        ),
        CheckConstraint(
            "public_links_used >= 0",
            name="ck_user_quotas_public_links_used_non_negative",
        ),
        CheckConstraint(
            "public_links_limit IS NULL OR public_links_limit >= 0",
            name="ck_user_quotas_public_links_limit_non_negative",
        ),
        CheckConstraint(
            "public_links_limit IS NULL OR public_links_used <= public_links_limit",
            name="ck_user_quotas_public_links_used_lte_limit",
        ),
        CheckConstraint(
            "active_upload_sessions_used >= 0",
            name="ck_user_quotas_active_upload_sessions_used_non_negative",
        ),
        CheckConstraint(
            "active_upload_sessions_limit IS NULL OR active_upload_sessions_limit >= 0",
            name="ck_user_quotas_active_upload_sessions_limit_non_negative",
        ),
        CheckConstraint(
            """
            active_upload_sessions_limit IS NULL
            OR active_upload_sessions_used <= active_upload_sessions_limit
            """,
            name="ck_user_quotas_active_upload_sessions_used_lte_limit",
        ),
        Index("ix_user_quotas_user_id", "user_id"),
        Index("ix_user_quotas_storage_used_bytes", "storage_used_bytes"),
        Index("ix_user_quotas_storage_limit_bytes", "storage_limit_bytes"),
        Index("ix_user_quotas_files_used", "files_used"),
        Index("ix_user_quotas_public_links_used", "public_links_used"),
        Index(
            "ix_user_quotas_active_upload_sessions_used",
            "active_upload_sessions_used",
        ),
        Index("ix_user_quotas_created_at", "created_at"),
        Index("ix_user_quotas_updated_at", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        comment="Пользователь, которому принадлежит квота.",
    )

    storage_limit_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Максимальный размер хранилища пользователя в байтах.",
    )

    storage_used_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
        comment="Текущий использованный объём хранилища в байтах.",
    )

    max_file_size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Максимально допустимый размер одного файла в байтах.",
    )

    files_limit: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Максимальное количество файлов. Null означает отсутствие лимита.",
    )

    files_used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Текущее количество файлов пользователя.",
    )

    public_links_limit: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Максимальное количество публичных ссылок. Null означает отсутствие лимита.",
    )

    public_links_used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Текущее количество публичных ссылок пользователя.",
    )

    active_upload_sessions_limit: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment=(
            "Максимальное количество активных upload-сессий. "
            "Null означает отсутствие лимита."
        ),
    )

    active_upload_sessions_used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Текущее количество активных upload-сессий пользователя.",
    )

    # -------------------------------------------------------------------------
    # Связи
    # -------------------------------------------------------------------------

    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="quota",
        lazy="selectin",
    )

    # -------------------------------------------------------------------------
    # Фабричные методы
    # -------------------------------------------------------------------------

    @classmethod
    def create_default(
        cls,
        user_id: uuid.UUID,
        storage_limit_bytes: int = 10 * 1024 * 1024 * 1024,
        max_file_size_bytes: int = 1024 * 1024 * 1024,
        files_limit: int | None = None,
        public_links_limit: int | None = 100,
        active_upload_sessions_limit: int | None = 10,
    ) -> UserQuota:
        """Создаёт стандартную квоту пользователя.

        Значения по умолчанию:
            - 10 ГБ общего хранилища;
            - 1 ГБ как максимальный размер одного файла;
            - без ограничения количества файлов;
            - 100 публичных ссылок;
            - 10 активных upload-сессий.

        Args:
            user_id: Идентификатор пользователя.
            storage_limit_bytes: Общий лимит хранилища в байтах.
            max_file_size_bytes: Максимальный размер одного файла в байтах.
            files_limit: Максимальное количество файлов.
            public_links_limit: Максимальное количество публичных ссылок.
            active_upload_sessions_limit: Максимальное количество активных
                upload-сессий.

        Returns:
            Экземпляр `UserQuota` со стандартными значениями.
        """

        return cls(
            user_id=user_id,
            storage_limit_bytes=storage_limit_bytes,
            storage_used_bytes=0,
            max_file_size_bytes=max_file_size_bytes,
            files_limit=files_limit,
            files_used=0,
            public_links_limit=public_links_limit,
            public_links_used=0,
            active_upload_sessions_limit=active_upload_sessions_limit,
            active_upload_sessions_used=0,
        )

    # -------------------------------------------------------------------------
    # Свойства хранилища
    # -------------------------------------------------------------------------

    @property
    def available_storage_bytes(self) -> int:
        """Возвращает доступное дисковое пространство в байтах.

        Returns:
            Неотрицательное количество доступных байт.
        """

        return max(self.storage_limit_bytes - self.storage_used_bytes, 0)

    @property
    def usage_percent(self) -> float:
        """Возвращает процент использования хранилища.

        Если `storage_limit_bytes` равен нулю, возвращает 100.0 при ненулевом
        использовании и 0.0 при отсутствии использования.

        Returns:
            Процент использования хранилища, округлённый до двух знаков.
        """

        if self.storage_limit_bytes <= 0:
            return 100.0 if self.storage_used_bytes > 0 else 0.0

        percent = (self.storage_used_bytes / self.storage_limit_bytes) * 100
        return round(min(percent, 100.0), 2)

    @property
    def is_storage_full(self) -> bool:
        """Проверяет, достигнут ли лимит хранилища.

        Returns:
            `True`, если использованный объём хранилища достиг лимита,
            иначе `False`.
        """

        return self.storage_used_bytes >= self.storage_limit_bytes

    # -------------------------------------------------------------------------
    # Свойства лимитов
    # -------------------------------------------------------------------------

    @property
    def has_files_limit(self) -> bool:
        """Проверяет наличие лимита количества файлов.

        Returns:
            `True`, если лимит количества файлов задан, иначе `False`.
        """

        return self.files_limit is not None

    @property
    def has_public_links_limit(self) -> bool:
        """Проверяет наличие лимита публичных ссылок.

        Returns:
            `True`, если лимит публичных ссылок задан, иначе `False`.
        """

        return self.public_links_limit is not None

    @property
    def has_active_upload_sessions_limit(self) -> bool:
        """Проверяет наличие лимита активных upload-сессий.

        Returns:
            `True`, если лимит активных upload-сессий задан, иначе `False`.
        """

        return self.active_upload_sessions_limit is not None

    @property
    def is_files_limit_reached(self) -> bool:
        """Проверяет, достигнут ли лимит количества файлов.

        Returns:
            `True`, если лимит файлов задан и уже достигнут, иначе `False`.
        """

        return self.files_limit is not None and self.files_used >= self.files_limit

    @property
    def is_public_links_limit_reached(self) -> bool:
        """Проверяет, достигнут ли лимит количества публичных ссылок.

        Returns:
            `True`, если лимит публичных ссылок задан и уже достигнут,
            иначе `False`.
        """

        return (
            self.public_links_limit is not None
            and self.public_links_used >= self.public_links_limit
        )

    @property
    def is_active_upload_sessions_limit_reached(self) -> bool:
        """Проверяет, достигнут ли лимит активных upload-сессий.

        Returns:
            `True`, если лимит активных upload-сессий задан и уже достигнут,
            иначе `False`.
        """

        return (
            self.active_upload_sessions_limit is not None
            and self.active_upload_sessions_used >= self.active_upload_sessions_limit
        )

    # -------------------------------------------------------------------------
    # Проверки возможности операций
    # -------------------------------------------------------------------------

    def can_store_file_size(self, file_size_bytes: int) -> bool:
        """Проверяет, можно ли сохранить файл указанного размера.

        Проверка включает:
            - размер файла не должен быть отрицательным;
            - размер файла не должен превышать `max_file_size_bytes`;
            - должно быть достаточно свободного места;
            - лимит количества файлов не должен быть достигнут.

        Args:
            file_size_bytes: Размер файла в байтах.

        Returns:
            `True`, если файл можно сохранить, иначе `False`.
        """

        return (
            file_size_bytes >= 0
            and file_size_bytes <= self.max_file_size_bytes
            and file_size_bytes <= self.available_storage_bytes
            and not self.is_files_limit_reached
        )

    def can_increase_usage_by(self, size_bytes: int) -> bool:
        """Проверяет, можно ли увеличить использование хранилища.

        Args:
            size_bytes: Количество байт для добавления.

        Returns:
            `True`, если увеличение не превысит лимит хранилища,
            иначе `False`.
        """

        return (
            size_bytes >= 0
            and self.storage_used_bytes + size_bytes <= self.storage_limit_bytes
        )

    def can_decrease_usage_by(self, size_bytes: int) -> bool:
        """Проверяет, можно ли уменьшить использование хранилища.

        Args:
            size_bytes: Количество байт для вычитания.

        Returns:
            `True`, если уменьшение не приведёт к отрицательному значению,
            иначе `False`.
        """

        return size_bytes >= 0 and self.storage_used_bytes - size_bytes >= 0

    def can_create_file(self, file_size_bytes: int) -> bool:
        """Проверяет, может ли пользователь создать файл.

        Args:
            file_size_bytes: Размер создаваемого файла в байтах.

        Returns:
            `True`, если пользователь может создать файл указанного размера,
            иначе `False`.
        """

        return self.can_store_file_size(file_size_bytes)

    def can_create_public_link(self) -> bool:
        """Проверяет, может ли пользователь создать публичную ссылку.

        Returns:
            `True`, если лимит публичных ссылок не достигнут, иначе `False`.
        """

        return not self.is_public_links_limit_reached

    def can_create_upload_session(self) -> bool:
        """Проверяет, может ли пользователь создать upload-сессию.

        Returns:
            `True`, если лимит активных upload-сессий не достигнут,
            иначе `False`.
        """

        return not self.is_active_upload_sessions_limit_reached

    # -------------------------------------------------------------------------
    # Изменение использования хранилища
    # -------------------------------------------------------------------------

    def increase_storage_usage(self, size_bytes: int) -> None:
        """Увеличивает использованный объём хранилища.

        Args:
            size_bytes: Количество байт для добавления.

        Raises:
            ValueError: Если значение отрицательное или превышает лимит.
        """

        if size_bytes < 0:
            raise ValueError(
                "Увеличение использования хранилища не может быть отрицательным."
            )

        if not self.can_increase_usage_by(size_bytes):
            raise ValueError("Превышена квота хранилища.")

        self.storage_used_bytes += size_bytes

    def decrease_storage_usage(self, size_bytes: int) -> None:
        """Уменьшает использованный объём хранилища.

        Args:
            size_bytes: Количество байт для вычитания.

        Raises:
            ValueError: Если значение отрицательное.
        """

        if size_bytes < 0:
            raise ValueError(
                "Уменьшение использования хранилища не может быть отрицательным."
            )

        self.storage_used_bytes = max(self.storage_used_bytes - size_bytes, 0)

    def set_storage_usage(self, size_bytes: int) -> None:
        """Устанавливает точное значение использованного хранилища.

        Используется при пересчёте квоты фоновым процессом.

        Args:
            size_bytes: Новое значение использованного хранилища в байтах.

        Raises:
            ValueError: Если значение отрицательное или превышает лимит.
        """

        if size_bytes < 0:
            raise ValueError("Использование хранилища не может быть отрицательным.")

        if size_bytes > self.storage_limit_bytes:
            raise ValueError(
                "Использование хранилища не может превышать лимит хранилища."
            )

        self.storage_used_bytes = size_bytes

    # -------------------------------------------------------------------------
    # Изменение количества файлов
    # -------------------------------------------------------------------------

    def increase_files_used(self, count: int = 1) -> None:
        """Увеличивает счётчик файлов.

        Args:
            count: Количество файлов для добавления.

        Raises:
            ValueError: Если значение отрицательное или превышает лимит.
        """

        if count < 0:
            raise ValueError(
                "Увеличение количества файлов не может быть отрицательным."
            )

        if self.files_limit is not None and self.files_used + count > self.files_limit:
            raise ValueError("Превышена квота файлов.")

        self.files_used += count

    def decrease_files_used(self, count: int = 1) -> None:
        """Уменьшает счётчик файлов.

        Args:
            count: Количество файлов для вычитания.

        Raises:
            ValueError: Если значение отрицательное.
        """

        if count < 0:
            raise ValueError(
                "Уменьшение количества файлов не может быть отрицательным."
            )

        self.files_used = max(self.files_used - count, 0)

    def set_files_used(self, count: int) -> None:
        """Устанавливает точное количество файлов.

        Используется при пересчёте квоты.

        Args:
            count: Новое количество файлов.

        Raises:
            ValueError: Если значение отрицательное или превышает лимит.
        """

        if count < 0:
            raise ValueError("Количество файлов не может быть отрицательным.")

        if self.files_limit is not None and count > self.files_limit:
            raise ValueError("Количество файлов не может превышать лимит файлов.")

        self.files_used = count

    # -------------------------------------------------------------------------
    # Изменение количества публичных ссылок
    # -------------------------------------------------------------------------

    def increase_public_links_used(self, count: int = 1) -> None:
        """Увеличивает счётчик публичных ссылок.

        Args:
            count: Количество публичных ссылок для добавления.

        Raises:
            ValueError: Если значение отрицательное или превышает лимит.
        """

        if count < 0:
            raise ValueError(
                "Увеличение количества публичных ссылок не может быть отрицательным."
            )

        if (
            self.public_links_limit is not None
            and self.public_links_used + count > self.public_links_limit
        ):
            raise ValueError("Превышена квота публичных ссылок.")

        self.public_links_used += count

    def decrease_public_links_used(self, count: int = 1) -> None:
        """Уменьшает счётчик публичных ссылок.

        Args:
            count: Количество публичных ссылок для вычитания.

        Raises:
            ValueError: Если значение отрицательное.
        """

        if count < 0:
            raise ValueError(
                "Уменьшение количества публичных ссылок не может быть отрицательным."
            )

        self.public_links_used = max(self.public_links_used - count, 0)

    def set_public_links_used(self, count: int) -> None:
        """Устанавливает точное количество публичных ссылок.

        Args:
            count: Новое количество публичных ссылок.

        Raises:
            ValueError: Если значение отрицательное или превышает лимит.
        """

        if count < 0:
            raise ValueError("Количество публичных ссылок не может быть отрицательным.")

        if self.public_links_limit is not None and count > self.public_links_limit:
            raise ValueError(
                "Количество публичных ссылок не может превышать лимит публичных ссылок."
            )

        self.public_links_used = count

    # -------------------------------------------------------------------------
    # Изменение количества активных upload-сессий
    # -------------------------------------------------------------------------

    def increase_active_upload_sessions_used(self, count: int = 1) -> None:
        """Увеличивает счётчик активных upload-сессий.

        Args:
            count: Количество upload-сессий для добавления.

        Raises:
            ValueError: Если значение отрицательное или превышает лимит.
        """

        if count < 0:
            raise ValueError(
                "Увеличение количества сессий загрузки не может быть отрицательным."
            )

        if (
            self.active_upload_sessions_limit is not None
            and self.active_upload_sessions_used + count
            > self.active_upload_sessions_limit
        ):
            raise ValueError("Превышена квота активных сессий загрузки.")

        self.active_upload_sessions_used += count

    def decrease_active_upload_sessions_used(self, count: int = 1) -> None:
        """Уменьшает счётчик активных upload-сессий.

        Args:
            count: Количество upload-сессий для вычитания.

        Raises:
            ValueError: Если значение отрицательное.
        """

        if count < 0:
            raise ValueError(
                "Уменьшение количества сессий загрузки не может быть отрицательным."
            )

        self.active_upload_sessions_used = max(
            self.active_upload_sessions_used - count,
            0,
        )

    def set_active_upload_sessions_used(self, count: int) -> None:
        """Устанавливает точное количество активных upload-сессий.

        Args:
            count: Новое количество активных upload-сессий.

        Raises:
            ValueError: Если значение отрицательное или превышает лимит.
        """

        if count < 0:
            raise ValueError(
                "Количество активных сессий загрузки не может быть отрицательным."
            )

        if (
            self.active_upload_sessions_limit is not None
            and count > self.active_upload_sessions_limit
        ):
            raise ValueError(
                "Количество активных сессий загрузки не может превышать лимит активных сессий загрузки."
            )

        self.active_upload_sessions_used = count

    # -------------------------------------------------------------------------
    # Обновление лимитов
    # -------------------------------------------------------------------------

    def update_limits(
        self,
        storage_limit_bytes: int | None = None,
        max_file_size_bytes: int | None = None,
        files_limit: int | None = None,
        public_links_limit: int | None = None,
        active_upload_sessions_limit: int | None = None,
    ) -> None:
        """Обновляет лимиты пользователя.

        `None` для `storage_limit_bytes` и `max_file_size_bytes` означает, что
        соответствующий лимит не изменяется.

        `None` для `files_limit`, `public_links_limit` и
        `active_upload_sessions_limit` означает снятие ограничения.

        Args:
            storage_limit_bytes: Новый общий лимит хранилища в байтах.
            max_file_size_bytes: Новый максимальный размер одного файла.
            files_limit: Новый лимит количества файлов или `None`.
            public_links_limit: Новый лимит публичных ссылок или `None`.
            active_upload_sessions_limit: Новый лимит активных upload-сессий
                или `None`.

        Raises:
            ValueError: Если новый лимит отрицательный или меньше текущего
                использования.
        """

        if storage_limit_bytes is not None:
            if storage_limit_bytes < 0:
                raise ValueError("Лимит хранилища не может быть отрицательным.")

            if storage_limit_bytes < self.storage_used_bytes:
                raise ValueError(
                    "Лимит хранилища не может быть меньше текущего использования."
                )

            self.storage_limit_bytes = storage_limit_bytes

        if max_file_size_bytes is not None:
            if max_file_size_bytes < 0:
                raise ValueError(
                    "Максимальный размер файла не может быть отрицательным."
                )

            self.max_file_size_bytes = max_file_size_bytes

        if files_limit is not None and files_limit < self.files_used:
            raise ValueError(
                "Лимит файлов не может быть меньше текущего количества файлов."
            )

        if (
            public_links_limit is not None
            and public_links_limit < self.public_links_used
        ):
            raise ValueError(
                "Лимит публичных ссылок не может быть меньше текущего количества публичных ссылок."
            )

        if (
            active_upload_sessions_limit is not None
            and active_upload_sessions_limit < self.active_upload_sessions_used
        ):
            raise ValueError(
                "Лимит активных сессий загрузки не может быть меньше текущего количества."
            )

        self.files_limit = files_limit
        self.public_links_limit = public_links_limit
        self.active_upload_sessions_limit = active_upload_sessions_limit

    def __repr__(self) -> str:
        """Возвращает строковое представление квоты пользователя.

        Returns:
            Строковое представление `UserQuota` с основными лимитами
            и значениями использования.
        """

        return (
            f"<UserQuota("
            f"id={self.id}, "
            f"user_id={self.user_id}, "
            f"storage_used_bytes={self.storage_used_bytes}, "
            f"storage_limit_bytes={self.storage_limit_bytes}, "
            f"max_file_size_bytes={self.max_file_size_bytes}, "
            f"files_used={self.files_used}, "
            f"files_limit={self.files_limit}, "
            f"public_links_used={self.public_links_used}, "
            f"public_links_limit={self.public_links_limit}, "
            f"active_upload_sessions_used={self.active_upload_sessions_used}, "
            f"active_upload_sessions_limit={self.active_upload_sessions_limit}"
            f")>"
        )
