from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

# Поддерживаемые схемы хеширования паролей.
PasswordHashScheme = Literal["bcrypt", "argon2"]


class PasswordValidationErrorCode(StrEnum):
    """Коды ошибок валидации пароля.

    Attributes:
        EMPTY: Пароль пустой.
        TOO_SHORT: Пароль короче минимально допустимой длины.
        TOO_LONG: Пароль длиннее максимально допустимой длины.
        MISSING_LETTER: Пароль не содержит букв.
        MISSING_DIGIT: Пароль не содержит цифр.
        MISSING_SPECIAL: Пароль не содержит специальных символов.
        CONTAINS_WHITESPACE: Пароль содержит пробельные символы.
    """

    EMPTY = "empty"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    MISSING_LETTER = "missing_letter"
    MISSING_DIGIT = "missing_digit"
    MISSING_SPECIAL = "missing_special"
    CONTAINS_WHITESPACE = "contains_whitespace"


# Список поддерживаемых схем хеширования паролей.
SUPPORTED_PASSWORD_HASH_SCHEMES: Final[tuple[PasswordHashScheme, ...]] = (
    "bcrypt",
    "argon2",
)

# Минимальная длина пароля по умолчанию.
DEFAULT_MIN_PASSWORD_LENGTH: Final[int] = 8

# Максимальная длина пароля по умолчанию.
DEFAULT_MAX_PASSWORD_LENGTH: Final[int] = 128
