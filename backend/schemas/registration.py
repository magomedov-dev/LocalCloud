from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, EmailStr, Field, field_validator

from database.models.enums import RegistrationRequestStatus
from schemas.common import BaseSchema, PaginationParams

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class RegistrationRequestCreate(BaseSchema):
    """Запрос на создание заявки на регистрацию.

    Используется для отправки новой заявки на регистрацию пользователя.
    Пароль передаётся в исходном виде только на уровне DTO, а его хэширование
    должно выполняться в service/security-слое.

    Attributes:
        email: Адрес электронной почты, указанный при регистрации.
        username: Желаемое имя пользователя.
        password: Пароль пользователя. Хэширование выполняется в
            service/security-слое.
    """

    email: EmailStr = Field(
        ...,
        description="Адрес электронной почты, указанный при регистрации.",
        examples=["user@example.com"],
    )
    username: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description="Желаемое имя пользователя.",
        examples=["ivan.petrov"],
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Пароль пользователя. Хэширование выполняется в service/security-слое.",
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


class RegistrationRequestRead(BaseSchema):
    """Полное безопасное представление заявки на регистрацию.

    Используется для возврата подробной информации о заявке без раскрытия
    пароля или его хэша.

    Attributes:
        id: Уникальный идентификатор заявки на регистрацию.
        email: Адрес электронной почты, указанный в заявке.
        username: Имя пользователя, указанное в заявке.
        status: Текущий статус заявки на регистрацию.
        comment: Комментарий администратора при рассмотрении заявки.
        rejection_reason: Причина отклонения заявки.
        reviewed_at: Дата и время рассмотрения заявки.
        reviewed_by: Идентификатор администратора, рассмотревшего заявку.
        created_user_id: Идентификатор созданной учётной записи после
            одобрения заявки.
        created_at: Дата и время создания заявки.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор заявки на регистрацию.",
    )
    email: EmailStr = Field(
        ...,
        description="Адрес электронной почты, указанный в заявке.",
    )
    username: str = Field(
        ...,
        description="Имя пользователя, указанное в заявке.",
    )
    status: RegistrationRequestStatus = Field(
        ...,
        description="Текущий статус заявки на регистрацию.",
    )
    comment: str | None = Field(
        default=None,
        description="Комментарий администратора при рассмотрении заявки.",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Причина отклонения заявки.",
    )
    reviewed_at: datetime | None = Field(
        default=None,
        description="Дата и время рассмотрения заявки.",
    )
    reviewed_by: UUID | None = Field(
        default=None,
        description="Идентификатор администратора, рассмотревшего заявку.",
    )
    created_user_id: UUID | None = Field(
        default=None,
        description="Идентификатор созданной учётной записи после одобрения заявки.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания заявки.",
    )


class RegistrationRequestListItem(BaseSchema):
    """Краткое представление заявки на регистрацию для списков.

    Используется в списках заявок, когда не нужны комментарии администратора и
    причина отклонения.

    Attributes:
        id: Уникальный идентификатор заявки на регистрацию.
        email: Адрес электронной почты, указанный в заявке.
        username: Имя пользователя, указанное в заявке.
        status: Текущий статус заявки на регистрацию.
        reviewed_at: Дата и время рассмотрения заявки.
        reviewed_by: Идентификатор администратора, рассмотревшего заявку.
        created_user_id: Идентификатор созданной учётной записи после
            одобрения заявки.
        created_at: Дата и время создания заявки.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор заявки на регистрацию.",
    )
    email: EmailStr = Field(
        ...,
        description="Адрес электронной почты, указанный в заявке.",
    )
    username: str = Field(
        ...,
        description="Имя пользователя, указанное в заявке.",
    )
    status: RegistrationRequestStatus = Field(
        ...,
        description="Текущий статус заявки на регистрацию.",
    )
    reviewed_at: datetime | None = Field(
        default=None,
        description="Дата и время рассмотрения заявки.",
    )
    reviewed_by: UUID | None = Field(
        default=None,
        description="Идентификатор администратора, рассмотревшего заявку.",
    )
    created_user_id: UUID | None = Field(
        default=None,
        description="Идентификатор созданной учётной записи после одобрения заявки.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания заявки.",
    )


class RegistrationApproveRequest(BaseSchema):
    """Запрос на одобрение заявки на регистрацию.

    Используется администратором для одобрения заявки и, при необходимости,
    добавления комментария к решению.

    Attributes:
        comment: Комментарий администратора к одобрению заявки.
        is_email_verified: Считать ли email пользователя подтверждённым после
            одобрения.
    """

    comment: str | None = Field(
        default=None,
        max_length=512,
        description="Комментарий администратора к одобрению заявки.",
    )
    is_email_verified: bool = Field(
        default=True,
        description="Считать ли email пользователя подтверждённым после одобрения.",
    )

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        """Нормализует комментарий администратора.

        Args:
            value: Исходный комментарий.

        Returns:
            Комментарий без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class RegistrationRejectRequest(BaseSchema):
    """Запрос на отклонение заявки на регистрацию.

    Используется администратором для отклонения заявки с обязательной причиной
    и необязательным дополнительным комментарием.

    Attributes:
        rejection_reason: Причина отклонения заявки.
        comment: Дополнительный комментарий администратора.
    """

    rejection_reason: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Причина отклонения заявки.",
    )
    comment: str | None = Field(
        default=None,
        max_length=512,
        description="Дополнительный комментарий администратора.",
    )

    @field_validator("rejection_reason")
    @classmethod
    def validate_rejection_reason(cls, value: str) -> str:
        """Проверяет и нормализует причину отклонения заявки.

        Args:
            value: Исходная причина отклонения.

        Returns:
            Причина отклонения без пробелов по краям.

        Raises:
            ValueError: Если причина отклонения пустая после нормализации.
        """

        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError("Причина отклонения заявки не должна быть пустой.")

        return normalized_value

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        """Нормализует дополнительный комментарий администратора.

        Args:
            value: Исходный комментарий.

        Returns:
            Комментарий без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class RegistrationCancelRequest(BaseSchema):
    """Запрос на отмену заявки на регистрацию.

    Используется для отмены заявки с необязательным указанием причины.

    Attributes:
        reason: Причина отмены заявки.
    """

    reason: str | None = Field(
        default=None,
        max_length=512,
        description="Причина отмены заявки.",
    )

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        """Нормализует причину отмены заявки.

        Args:
            value: Исходная причина отмены.

        Returns:
            Причина отмены без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class RegistrationQueryParams(PaginationParams):
    """Параметры фильтрации списка заявок на регистрацию.

    Используется для постраничного получения заявок с фильтрацией по поисковой
    строке, статусу, администратору, датам создания и рассмотрения, а также с
    настройками сортировки.

    Attributes:
        query: Поисковая строка по email или username.
        status: Фильтр по статусу заявки.
        reviewed_by: Фильтр по администратору, рассмотревшему заявку.
        created_from: Фильтр по дате создания: начало диапазона включительно.
        created_to: Фильтр по дате создания: конец диапазона включительно.
        reviewed_from: Фильтр по дате рассмотрения: начало диапазона
            включительно.
        reviewed_to: Фильтр по дате рассмотрения: конец диапазона
            включительно.
        sort_by: Поле сортировки.
        sort_desc: Признак сортировки по убыванию.
    """

    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Поисковая строка по email или username.",
    )
    status: RegistrationRequestStatus | None = Field(
        default=None,
        description="Фильтр по статусу заявки.",
    )
    reviewed_by: UUID | None = Field(
        default=None,
        description="Фильтр по администратору, рассмотревшему заявку.",
    )
    created_from: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания: начало диапазона включительно.",
    )
    created_to: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания: конец диапазона включительно.",
    )
    reviewed_from: datetime | None = Field(
        default=None,
        description="Фильтр по дате рассмотрения: начало диапазона включительно.",
    )
    reviewed_to: datetime | None = Field(
        default=None,
        description="Фильтр по дате рассмотрения: конец диапазона включительно.",
    )
    sort_by: str = Field(
        default="created_at",
        max_length=64,
        description="Поле сортировки.",
        examples=["created_at", "reviewed_at", "email", "username", "status"],
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

    @field_validator("reviewed_to")
    @classmethod
    def validate_reviewed_range(
        cls,
        value: datetime | None,
        info: object,
    ) -> datetime | None:
        """Проверяет корректность диапазона даты рассмотрения.

        Args:
            value: Значение верхней границы диапазона ``reviewed_to``.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Значение ``reviewed_to``, если диапазон корректен.

        Raises:
            ValueError: Если ``reviewed_to`` меньше ``reviewed_from``.
        """

        data = getattr(info, "data", {})
        reviewed_from = data.get("reviewed_from")

        if reviewed_from is not None and value is not None and value < reviewed_from:
            raise ValueError("reviewed_to не может быть раньше reviewed_from.")

        return value


class RegistrationDecisionResponse(BaseSchema):
    """Результат рассмотрения заявки на регистрацию.

    Используется для возврата результата одобрения, отклонения или отмены
    заявки на регистрацию.

    Attributes:
        request: Заявка на регистрацию после изменения статуса.
        created_user_id: Идентификатор созданного пользователя, если заявка
            была одобрена.
        message: Человекочитаемое сообщение о результате рассмотрения заявки.
    """

    request: RegistrationRequestRead = Field(
        ...,
        description="Заявка на регистрацию после изменения статуса.",
    )
    created_user_id: UUID | None = Field(
        default=None,
        description="Идентификатор созданного пользователя, если заявка была одобрена.",
    )
    message: str = Field(
        ...,
        min_length=1,
        description="Человекочитаемое сообщение о результате рассмотрения заявки.",
    )
