from __future__ import annotations

from enum import StrEnum
from typing import Literal

# Допустимые значения атрибута SameSite для cookie.
CookieSameSite = Literal["lax", "strict", "none"]


class AuthCookieName(StrEnum):
    """Имена cookie для хранения authentication tokens.

    Attributes:
        ACCESS: Имя cookie для access token.
        REFRESH: Имя cookie для refresh token.
    """

    ACCESS = "access"
    REFRESH = "refresh"


class CookieErrorCode(StrEnum):
    """Коды ошибок, связанных с cookie.

    Используется для унифицированного описания ошибок валидации, создания,
    чтения и удаления authentication cookie.

    Attributes:
        INVALID_COOKIE_NAME: Некорректное имя cookie.
        INVALID_TOKEN: Некорректное значение token в cookie.
        INVALID_MAX_AGE: Некорректное значение max age.
        INVALID_SAMESITE: Некорректное значение SameSite.
        INVALID_SETTINGS: Некорректные настройки cookie.
    """

    INVALID_COOKIE_NAME = "invalid_cookie_name"
    INVALID_TOKEN = "invalid_token"
    INVALID_MAX_AGE = "invalid_max_age"
    INVALID_SAMESITE = "invalid_samesite"
    INVALID_SETTINGS = "invalid_settings"
