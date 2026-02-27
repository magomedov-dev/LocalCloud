from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator
from schemas.users import CurrentUserRead

from schemas.common import BaseSchema


class LoginRequest(BaseSchema):
    """Запрос на вход в систему.

    Используется для аутентификации пользователя по email или username и паролю.
    Значение ``email_or_username`` нормализуется: пробелы по краям удаляются,
    пустая строка отклоняется.

    Attributes:
        email_or_username: Email или username пользователя.
        password: Пароль пользователя.
    """

    email_or_username: str = Field(
        ...,
        min_length=1,
        max_length=320,
        description="Email или username пользователя.",
        examples=["user@example.com", "ivan.petrov"],
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Пароль пользователя.",
    )

    @field_validator("email_or_username")
    @classmethod
    def normalize_email_or_username(cls, value: str) -> str:
        """Нормализует email или username пользователя.

        Args:
            value: Исходное значение email или username.

        Returns:
            Строка без пробелов по краям.

        Raises:
            ValueError: Если после удаления пробелов значение становится пустым.
        """

        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError("email_or_username не должен быть пустым.")

        return normalized_value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """Проверяет, что пароль не пустой.

        Args:
            value: Значение пароля.

        Returns:
            Исходное значение пароля.

        Raises:
            ValueError: Если пароль пустой.
        """

        if not value:
            raise ValueError("password не должен быть пустым.")

        return value


class LoginResponse(BaseSchema):
    """Ответ после успешной аутентификации.

    Возвращается после успешного входа пользователя в систему. Содержит
    признак аутентификации, данные текущего пользователя и сообщение о
    результате операции.

    Attributes:
        authenticated: Признак успешной аутентификации.
        user: Текущий аутентифицированный пользователь.
        message: Сообщение о результате входа.
    """

    authenticated: bool = Field(
        default=True,
        description="Признак успешной аутентификации.",
    )
    user: CurrentUserRead = Field(
        ...,
        description="Текущий аутентифицированный пользователь.",
    )
    message: str = Field(
        default="Вход выполнен успешно.",
        description="Сообщение о результате входа.",
    )


class LogoutResponse(BaseSchema):
    """Ответ после выхода из системы.

    Возвращается после завершения пользовательской сессии или удаления
    аутентификационных cookies.

    Attributes:
        authenticated: Признак того, что пользователь остаётся
            аутентифицированным после операции.
        message: Сообщение о результате выхода.
    """

    authenticated: bool = Field(
        default=False,
        description="Признак того, что пользователь остаётся аутентифицированным после операции.",
    )
    message: str = Field(
        default="Выход выполнен успешно.",
        description="Сообщение о результате выхода.",
    )


class RefreshTokenResponse(BaseSchema):
    """Ответ после обновления access/refresh token.

    Возвращается после успешного обновления сессии. В зависимости от реализации
    сервиса может включать данные текущего пользователя.

    Attributes:
        authenticated: Признак успешного обновления сессии.
        user: Текущий пользователь, если сервис возвращает его вместе с
            обновлением токенов.
        message: Сообщение о результате обновления сессии.
    """

    authenticated: bool = Field(
        default=True,
        description="Признак успешного обновления сессии.",
    )
    user: CurrentUserRead | None = Field(
        default=None,
        description="Текущий пользователь, если сервис возвращает его вместе с обновлением токенов.",
    )
    message: str = Field(
        default="Сессия успешно обновлена.",
        description="Сообщение о результате обновления сессии.",
    )


class TokenPair(BaseSchema):
    """Пара access/refresh token.

    Обычно не возвращается клиенту напрямую, потому что токены передаются через
    httpOnly cookies. Схема может использоваться во внутренних тестах или
    сервисных контрактах.

    Attributes:
        access_token: JWT access token.
        refresh_token: JWT refresh token.
        token_type: Тип токена.
        access_expires_at: Дата и время истечения access token.
        refresh_expires_at: Дата и время истечения refresh token.
    """

    access_token: str = Field(
        ...,
        min_length=1,
        description="JWT access token.",
    )
    refresh_token: str = Field(
        ...,
        min_length=1,
        description="JWT refresh token.",
    )
    token_type: str = Field(
        default="bearer",
        description="Тип токена.",
        examples=["bearer"],
    )
    access_expires_at: datetime | None = Field(
        default=None,
        description="Дата и время истечения access token.",
    )
    refresh_expires_at: datetime | None = Field(
        default=None,
        description="Дата и время истечения refresh token.",
    )


class JwtPayloadRead(BaseSchema):
    """Безопасное представление полезной нагрузки JWT.

    Используется для передачи наружу только тех claims, которые можно безопасно
    отображать или использовать в диагностике.

    Attributes:
        sub: Subject токена. Обычно содержит идентификатор пользователя.
        user_id: Идентификатор пользователя, если он был извлечён из subject
            или claims.
        token_type: Тип JWT.
        jti: Уникальный идентификатор JWT.
        iss: Issuer токена.
        aud: Audience токена.
        issued_at: Дата и время выпуска токена.
        expires_at: Дата и время истечения токена.
    """

    sub: str = Field(
        ...,
        min_length=1,
        description="Subject токена. Обычно содержит идентификатор пользователя.",
    )
    user_id: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, если он был извлечён из subject или claims.",
    )
    token_type: str = Field(
        ...,
        min_length=1,
        description="Тип JWT.",
        examples=["access", "refresh"],
    )
    jti: str | None = Field(
        default=None,
        description="Уникальный идентификатор JWT.",
    )
    iss: str | None = Field(
        default=None,
        description="Issuer токена.",
    )
    aud: str | list[str] | None = Field(
        default=None,
        description="Audience токена.",
    )
    issued_at: datetime | None = Field(
        default=None,
        description="Дата и время выпуска токена.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Дата и время истечения токена.",
    )


class AuthSessionRead(BaseSchema):
    """Безопасное представление пользовательской refresh-сессии.

    Используется для отображения информации о сессиях пользователя без
    раскрытия значения refresh token.

    Attributes:
        id: Уникальный идентификатор сессии или refresh-токена.
        user_id: Идентификатор пользователя, которому принадлежит сессия.
        status: Статус сессии.
        expires_at: Дата и время истечения refresh-сессии.
        revoked_at: Дата и время отзыва сессии.
        revoke_reason: Причина отзыва сессии.
        replaced_by_token_id: Идентификатор новой сессии, заменившей текущую
            при ротации.
        parent_token_id: Идентификатор предыдущей сессии, из которой была
            создана текущая.
        ip_address: IP-адрес, с которого была создана сессия.
        user_agent: User-Agent клиента.
        device_name: Условное имя устройства или клиента.
        is_active: Признак активности сессии.
        created_at: Дата и время создания сессии.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор сессии или refresh-токена.",
    )
    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, которому принадлежит сессия.",
    )
    status: str = Field(
        ...,
        description="Статус сессии.",
        examples=["active", "revoked", "expired"],
    )
    expires_at: datetime = Field(
        ...,
        description="Дата и время истечения refresh-сессии.",
    )
    revoked_at: datetime | None = Field(
        default=None,
        description="Дата и время отзыва сессии.",
    )
    revoke_reason: str | None = Field(
        default=None,
        description="Причина отзыва сессии.",
    )
    replaced_by_token_id: UUID | None = Field(
        default=None,
        description="Идентификатор новой сессии, заменившей текущую при ротации.",
    )
    parent_token_id: UUID | None = Field(
        default=None,
        description="Идентификатор предыдущей сессии, из которой была создана текущая.",
    )
    ip_address: str | None = Field(
        default=None,
        description="IP-адрес, с которого была создана сессия.",
    )
    user_agent: str | None = Field(
        default=None,
        description="User-Agent клиента.",
    )
    device_name: str | None = Field(
        default=None,
        description="Условное имя устройства или клиента.",
    )
    is_active: bool = Field(
        ...,
        description="Признак активности сессии.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания сессии.",
    )


class PasswordChangeRequest(BaseSchema):
    """Запрос на изменение пароля текущего пользователя.

    Используется аутентифицированным пользователем для смены текущего пароля на
    новый. Оба поля должны быть непустыми.

    Attributes:
        current_password: Текущий пароль пользователя.
        new_password: Новый пароль пользователя.
    """

    current_password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Текущий пароль пользователя.",
    )
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Новый пароль пользователя.",
    )

    @field_validator("current_password")
    @classmethod
    def validate_current_password(cls, value: str) -> str:
        """Проверяет, что текущий пароль не пустой.

        Args:
            value: Значение текущего пароля.

        Returns:
            Исходное значение текущего пароля.

        Raises:
            ValueError: Если текущий пароль пустой.
        """

        if not value:
            raise ValueError("current_password не должен быть пустым.")

        return value

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        """Проверяет, что новый пароль не пустой.

        Args:
            value: Значение нового пароля.

        Returns:
            Исходное значение нового пароля.

        Raises:
            ValueError: Если новый пароль пустой.
        """

        if not value:
            raise ValueError("new_password не должен быть пустым.")

        return value
