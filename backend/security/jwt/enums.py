from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

# Допустимые типы JWT token.
JwtTokenType = Literal["access", "refresh"]


class JwtClaimName(StrEnum):
    """Имена стандартных и прикладных JWT claims.

    Attributes:
        SUBJECT: Subject token. Обычно содержит идентификатор пользователя.
        TOKEN_TYPE: Тип token: access или refresh.
        JWT_ID: Уникальный идентификатор token.
        ISSUED_AT: Время выпуска token.
        NOT_BEFORE: Время, раньше которого token считается недействительным.
        EXPIRES_AT: Время истечения срока действия token.
        ISSUER: Издатель token.
        AUDIENCE: Получатель token.
    """

    SUBJECT = "sub"
    TOKEN_TYPE = "type"
    JWT_ID = "jti"
    ISSUED_AT = "iat"
    NOT_BEFORE = "nbf"
    EXPIRES_AT = "exp"
    ISSUER = "iss"
    AUDIENCE = "aud"


class JwtErrorCode(StrEnum):
    """Коды ошибок JWT.

    Используется для унифицированного описания ошибок создания, декодирования и
    валидации JWT token.

    Attributes:
        INVALID_TOKEN: Token недействителен или имеет некорректный формат.
        EXPIRED_TOKEN: Срок действия token истёк.
        INVALID_CLAIMS: Token содержит некорректные claims.
        INVALID_TOKEN_TYPE: Token имеет недопустимый тип.
        MISSING_SUBJECT: В token отсутствует subject.
        MISSING_JTI: В token отсутствует JWT ID.
        INVALID_SUBJECT: Subject token имеет некорректное значение.
        INVALID_SETTINGS: Некорректные настройки JWT.
    """

    INVALID_TOKEN = "invalid_token"
    EXPIRED_TOKEN = "expired_token"
    INVALID_CLAIMS = "invalid_claims"
    INVALID_TOKEN_TYPE = "invalid_token_type"
    MISSING_SUBJECT = "missing_subject"
    MISSING_JTI = "missing_jti"
    INVALID_SUBJECT = "invalid_subject"
    INVALID_SETTINGS = "invalid_settings"


# Поддерживаемые типы JWT token.
SUPPORTED_JWT_TOKEN_TYPES: Final[tuple[JwtTokenType, ...]] = (
    "access",
    "refresh",
)
