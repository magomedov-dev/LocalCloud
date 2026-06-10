from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, EmailStr, Field, field_validator

from database.models.enums import SystemRole, UserStatus
from schemas.common import BaseSchema, PaginationParams

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class UserBase(BaseSchema):
    """Базовые публичные поля пользователя.

    Используется как общий родитель для схем создания и чтения пользователя.
    Содержит email и уникальное имя пользователя.

    Attributes:
        email: Адрес электронной почты пользователя.
        username: Уникальное имя пользователя.
    """

    email: EmailStr = Field(
        ...,
        description="Адрес электронной почты пользователя.",
        examples=["user@example.com"],
    )
    username: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description="Уникальное имя пользователя.",
        examples=["ivan.petrov"],
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """Проверяет и нормализует username.

        Удаляет пробелы по краям и проверяет, что username содержит только
        латинские буквы, цифры, underscore, точку и дефис.

        Args:
            value: Исходное значение username.

        Returns:
            Нормализованный username.

        Raises:
            ValueError: Если username пустой после нормализации.
            ValueError: Если username содержит недопустимые символы.
        """

        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError("username не должен быть пустым.")

        if not USERNAME_PATTERN.fullmatch(normalized_value):
            raise ValueError(
                "username может содержать только латинские буквы, цифры, "
                "underscore, точку и дефис."
            )

        return normalized_value


class UserCreate(UserBase):
    """Запрос на создание пользователя администратором.

    Используется для административного создания учётной записи с email,
    username, паролем и начальным статусом.
    Пароль передаётся в исходном виде только на уровне DTO, а его хэширование
    выполняется в security/service-слое.

    Attributes:
        email: Адрес электронной почты пользователя.
        username: Уникальное имя пользователя.
        password: Пароль пользователя. Хэширование выполняется в
            security/service-слое.
        status: Начальный статус учётной записи.
    """

    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Пароль пользователя. Хэширование выполняется в security/service-слое.",
    )
    status: UserStatus = Field(
        default=UserStatus.PENDING,
        description="Начальный статус учётной записи.",
    )


class UserUpdate(BaseSchema):
    """Запрос на обновление собственных данных пользователя.

    Используется для частичного обновления email или username текущего
    пользователя.

    Attributes:
        email: Новый адрес электронной почты пользователя.
        username: Новое имя пользователя.
    """

    email: EmailStr | None = Field(
        default=None,
        description="Новый адрес электронной почты пользователя.",
    )
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
        description="Новое имя пользователя.",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        """Проверяет и нормализует новое имя пользователя.

        Args:
            value: Новое значение username или ``None``.

        Returns:
            Нормализованный username или ``None``, если поле не передано.

        Raises:
            ValueError: Если username пустой после нормализации.
            ValueError: Если username содержит недопустимые символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError("username не должен быть пустым.")

        if not USERNAME_PATTERN.fullmatch(normalized_value):
            raise ValueError(
                "username может содержать только латинские буквы, цифры, "
                "underscore, точку и дефис."
            )

        return normalized_value


class UserAdminUpdate(UserUpdate):
    """Запрос на административное обновление пользователя.

    Расширяет пользовательское обновление полями, доступными администратору:
    статусом учётной записи, причиной блокировки и причиной отклонения.

    Attributes:
        email: Новый адрес электронной почты пользователя.
        username: Новое имя пользователя.
        status: Новый статус учётной записи.
        block_reason: Причина блокировки пользователя.
        rejection_reason: Причина отклонения пользователя.
    """

    status: UserStatus | None = Field(
        default=None,
        description="Новый статус учётной записи.",
    )
    block_reason: str | None = Field(
        default=None,
        max_length=512,
        description="Причина блокировки пользователя.",
    )
    rejection_reason: str | None = Field(
        default=None,
        max_length=512,
        description="Причина отклонения пользователя.",
    )

    @field_validator("block_reason", "rejection_reason")
    @classmethod
    def normalize_optional_reason(cls, value: str | None) -> str | None:
        """Нормализует необязательную причину изменения статуса.

        Args:
            value: Исходная причина блокировки или отклонения.

        Returns:
            Причина без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class UserRead(UserBase):
    """Полное безопасное представление пользователя.

    Используется для возврата подробных публичных данных пользователя без
    пароля и других секретных сведений.

    Attributes:
        email: Адрес электронной почты пользователя.
        username: Уникальное имя пользователя.
        id: Уникальный идентификатор пользователя.
        status: Текущий статус учётной записи.
        last_login_at: Дата и время последнего успешного входа.
        approved_at: Дата и время одобрения регистрации пользователя.
        blocked_at: Дата и время блокировки пользователя.
        rejected_at: Дата и время отклонения пользователя.
        deleted_at: Дата и время логического удаления пользователя.
        block_reason: Причина блокировки пользователя.
        rejection_reason: Причина отклонения пользователя.
        created_at: Дата и время создания пользователя.
        updated_at: Дата и время последнего обновления пользователя.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор пользователя.",
    )
    status: UserStatus = Field(
        ...,
        description="Текущий статус учётной записи.",
    )
    last_login_at: datetime | None = Field(
        default=None,
        description="Дата и время последнего успешного входа.",
    )
    approved_at: datetime | None = Field(
        default=None,
        description="Дата и время одобрения регистрации пользователя.",
    )
    blocked_at: datetime | None = Field(
        default=None,
        description="Дата и время блокировки пользователя.",
    )
    rejected_at: datetime | None = Field(
        default=None,
        description="Дата и время отклонения пользователя.",
    )
    deleted_at: datetime | None = Field(
        default=None,
        description="Дата и время логического удаления пользователя.",
    )
    block_reason: str | None = Field(
        default=None,
        description="Причина блокировки пользователя.",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Причина отклонения пользователя.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания пользователя.",
    )
    updated_at: datetime = Field(
        ...,
        description="Дата и время последнего обновления пользователя.",
    )
    is_primary_admin: bool = Field(
        default=False,
        description=(
            "Признак учётной записи первичного администратора. Такую запись "
            "нельзя удалить."
        ),
    )


class UserListItem(BaseSchema):
    """Краткое представление пользователя для списков.

    Используется в списках пользователей, когда не нужны все временные метки,
    причины блокировки или отклонения и другие подробности полного
    представления.

    Attributes:
        id: Уникальный идентификатор пользователя.
        email: Адрес электронной почты пользователя.
        username: Уникальное имя пользователя.
        status: Текущий статус учётной записи.
        last_login_at: Дата и время последнего успешного входа.
        created_at: Дата и время создания пользователя.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор пользователя.",
    )
    email: EmailStr = Field(
        ...,
        description="Адрес электронной почты пользователя.",
    )
    username: str = Field(
        ...,
        description="Уникальное имя пользователя.",
    )
    status: UserStatus = Field(
        ...,
        description="Текущий статус учётной записи.",
    )
    last_login_at: datetime | None = Field(
        default=None,
        description="Дата и время последнего успешного входа.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания пользователя.",
    )
    is_primary_admin: bool = Field(
        default=False,
        description=(
            "Признак учётной записи первичного администратора. Такую запись "
            "нельзя удалить."
        ),
    )


class CurrentUserRead(BaseSchema):
    """Представление текущего аутентифицированного пользователя.

    Используется для ответа endpoint-ов текущей сессии. Содержит основные
    сведения о пользователе и список его ролей.

    Attributes:
        id: Уникальный идентификатор текущего пользователя.
        email: Адрес электронной почты текущего пользователя.
        username: Имя текущего пользователя.
        status: Текущий статус учётной записи.
        last_login_at: Дата и время последнего успешного входа.
        role: Системная роль текущего пользователя.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор текущего пользователя.",
    )
    email: EmailStr = Field(
        ...,
        description="Адрес электронной почты текущего пользователя.",
    )
    username: str = Field(
        ...,
        description="Имя текущего пользователя.",
    )
    status: UserStatus = Field(
        ...,
        description="Текущий статус учётной записи.",
    )
    last_login_at: datetime | None = Field(
        default=None,
        description="Дата и время последнего успешного входа.",
    )
    role: SystemRole = Field(
        ...,
        description="Системная роль пользователя.",
    )


class UserStatusUpdateRequest(BaseSchema):
    """Запрос на изменение статуса пользователя.

    Используется для изменения статуса учётной записи с необязательной причиной
    такого изменения.

    Attributes:
        status: Новый статус учётной записи.
        reason: Причина изменения статуса.
    """

    status: UserStatus = Field(
        ...,
        description="Новый статус учётной записи.",
    )
    reason: str | None = Field(
        default=None,
        max_length=512,
        description="Причина изменения статуса.",
    )

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        """Нормализует причину изменения статуса.

        Args:
            value: Исходная причина изменения статуса.

        Returns:
            Причина без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class UserBlockRequest(BaseSchema):
    """Запрос на блокировку пользователя.

    Используется для блокировки учётной записи с обязательным указанием
    причины.

    Attributes:
        reason: Причина блокировки пользователя.
    """

    reason: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Причина блокировки пользователя.",
    )

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        """Проверяет и нормализует причину блокировки.

        Args:
            value: Исходная причина блокировки.

        Returns:
            Причина блокировки без пробелов по краям.

        Raises:
            ValueError: Если причина блокировки пустая после нормализации.
        """

        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError("Причина блокировки не должна быть пустой.")

        return normalized_value


class UserRejectRequest(BaseSchema):
    """Запрос на отклонение пользователя.

    Используется для отклонения пользователя или его регистрации с обязательным
    указанием причины.

    Attributes:
        reason: Причина отклонения пользователя.
    """

    reason: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Причина отклонения пользователя.",
    )

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        """Проверяет и нормализует причину отклонения.

        Args:
            value: Исходная причина отклонения.

        Returns:
            Причина отклонения без пробелов по краям.

        Raises:
            ValueError: Если причина отклонения пустая после нормализации.
        """

        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError("Причина отклонения не должна быть пустой.")

        return normalized_value


class UserQueryParams(PaginationParams):
    """Параметры фильтрации списка пользователей.

    Используется для постраничного получения пользователей с фильтрацией по
    поисковой строке, статусу, дате создания и настройкам сортировки.

    Attributes:
        query: Поисковая строка по email или username.
        status: Фильтр по статусу пользователя.
        created_from: Фильтр по дате создания: начало диапазона включительно.
        created_to: Фильтр по дате создания: конец диапазона включительно.
        sort_by: Поле сортировки.
        sort_desc: Признак сортировки по убыванию.
    """

    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Поисковая строка по email или username.",
    )
    status: UserStatus | None = Field(
        default=None,
        description="Фильтр по статусу пользователя.",
    )
    created_from: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания: начало диапазона включительно.",
    )
    created_to: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания: конец диапазона включительно.",
    )
    sort_by: str = Field(
        default="created_at",
        max_length=64,
        description="Поле сортировки.",
        examples=["created_at", "updated_at", "email", "username", "last_login_at"],
    )
    sort_desc: bool = Field(
        default=True,
        description="Сортировать по убыванию.",
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        """Нормализует поисковую строку.

        Args:
            value: Исходная поисковая строка.

        Returns:
            Поисковая строка без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("created_to")
    @classmethod
    def validate_created_range(
        cls,
        value: datetime | None,
        info: object,
    ) -> datetime | None:
        """Проверяет корректность диапазона даты создания.

        Args:
            value: Значение верхней границы диапазона ``created_to``.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Значение ``created_to``, если диапазон корректен.

        Raises:
            ValueError: Если ``created_to`` меньше ``created_from``.
        """

        data = getattr(info, "data", {})
        created_from = data.get("created_from")

        if created_from is not None and value is not None and value < created_from:
            raise ValueError("created_to не может быть раньше created_from.")

        return value


class AdminChangePasswordRequest(BaseSchema):
    """Запрос администратора на смену пароля пользователя.

    Attributes:
        new_password: Новый пароль пользователя.
    """

    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Новый пароль пользователя.",
    )


class UserWithRolesRead(UserRead):
    """Полное представление пользователя вместе с ролями.

    Расширяет полное безопасное представление пользователя списком назначенных
    ролей.

    Attributes:
        email: Адрес электронной почты пользователя.
        username: Уникальное имя пользователя.
        id: Уникальный идентификатор пользователя.
        status: Текущий статус учётной записи.
        last_login_at: Дата и время последнего успешного входа.
        approved_at: Дата и время одобрения регистрации пользователя.
        blocked_at: Дата и время блокировки пользователя.
        rejected_at: Дата и время отклонения пользователя.
        deleted_at: Дата и время логического удаления пользователя.
        block_reason: Причина блокировки пользователя.
        rejection_reason: Причина отклонения пользователя.
        created_at: Дата и время создания пользователя.
        updated_at: Дата и время последнего обновления пользователя.
        role: Системная роль пользователя.
    """

    role: SystemRole = Field(
        ...,
        description="Системная роль пользователя.",
    )
