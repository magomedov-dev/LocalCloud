from __future__ import annotations

from typing import cast

from security.password.dto import PasswordValidationError, PasswordValidationResult
from security.password.enums import (
    DEFAULT_MAX_PASSWORD_LENGTH,
    DEFAULT_MIN_PASSWORD_LENGTH,
    SUPPORTED_PASSWORD_HASH_SCHEMES,
    PasswordHashScheme,
    PasswordValidationErrorCode,
)


def normalize_password_hash_scheme(
    scheme: str | PasswordHashScheme,
) -> PasswordHashScheme:
    """Нормализует и проверяет алгоритм хеширования пароля.

    Args:
        scheme: Название алгоритма хеширования пароля.

    Returns:
        Нормализованное название поддерживаемого алгоритма хеширования.

    Raises:
        ValueError: Если алгоритм не является строкой или не входит в список
            поддерживаемых алгоритмов.
    """

    if not isinstance(scheme, str):
        raise ValueError("Алгоритм хеширования пароля должен быть строкой.")

    normalized_scheme = scheme.strip().lower()

    if normalized_scheme not in SUPPORTED_PASSWORD_HASH_SCHEMES:
        raise ValueError(
            "Неподдерживаемый алгоритм хеширования паролей. "
            f"Допустимые значения: {', '.join(SUPPORTED_PASSWORD_HASH_SCHEMES)}."
        )

    return cast(PasswordHashScheme, normalized_scheme)


def validate_password_value(password: str) -> str:
    """Проверяет значение пароля.

    Args:
        password: Пароль для проверки.

    Returns:
        Исходный пароль, если он прошёл базовую проверку.

    Raises:
        ValueError: Если пароль не является строкой или является пустым.
    """

    if not isinstance(password, str):
        raise ValueError("Пароль должен быть строкой.")

    if not password:
        raise ValueError("Пароль не должен быть пустым.")

    return password


def validate_password_strength(
    password: str,
    *,
    min_length: int = DEFAULT_MIN_PASSWORD_LENGTH,
    max_length: int = DEFAULT_MAX_PASSWORD_LENGTH,
    require_letter: bool = True,
    require_digit: bool = True,
    require_special: bool = False,
    allow_whitespace: bool = False,
) -> PasswordValidationResult:
    """Проверяет сложность пароля.

    Args:
        password: Пароль для проверки.
        min_length: Минимально допустимая длина пароля.
        max_length: Максимально допустимая длина пароля.
        require_letter: Требовать ли наличие хотя бы одной буквы.
        require_digit: Требовать ли наличие хотя бы одной цифры.
        require_special: Требовать ли наличие хотя бы одного специального
            символа.
        allow_whitespace: Разрешать ли пробельные символы в пароле.

    Returns:
        Результат валидации пароля со списком найденных ошибок.
    """

    errors: list[PasswordValidationError] = []

    if not isinstance(password, str) or not password:
        return PasswordValidationResult(
            is_valid=False,
            errors=(
                PasswordValidationError(
                    code=PasswordValidationErrorCode.EMPTY,
                    message="Пароль не должен быть пустым.",
                ),
            ),
        )

    if len(password) < min_length:
        errors.append(
            PasswordValidationError(
                code=PasswordValidationErrorCode.TOO_SHORT,
                message=f"Пароль должен быть не короче {min_length} символов.",
            )
        )

    if len(password) > max_length:
        errors.append(
            PasswordValidationError(
                code=PasswordValidationErrorCode.TOO_LONG,
                message=f"Пароль должен быть не длиннее {max_length} символов.",
            )
        )

    if require_letter and not any(char.isalpha() for char in password):
        errors.append(
            PasswordValidationError(
                code=PasswordValidationErrorCode.MISSING_LETTER,
                message="Пароль должен содержать хотя бы одну букву.",
            )
        )

    if require_digit and not any(char.isdigit() for char in password):
        errors.append(
            PasswordValidationError(
                code=PasswordValidationErrorCode.MISSING_DIGIT,
                message="Пароль должен содержать хотя бы одну цифру.",
            )
        )

    if require_special and not any(
        not char.isalnum() and not char.isspace() for char in password
    ):
        errors.append(
            PasswordValidationError(
                code=PasswordValidationErrorCode.MISSING_SPECIAL,
                message="Пароль должен содержать хотя бы один специальный символ.",
            )
        )

    if not allow_whitespace and any(char.isspace() for char in password):
        errors.append(
            PasswordValidationError(
                code=PasswordValidationErrorCode.CONTAINS_WHITESPACE,
                message="Пароль не должен содержать пробельные символы.",
            )
        )

    return PasswordValidationResult(is_valid=not errors, errors=tuple(errors))


def require_strong_password(
    password: str,
    *,
    min_length: int = DEFAULT_MIN_PASSWORD_LENGTH,
    max_length: int = DEFAULT_MAX_PASSWORD_LENGTH,
    require_letter: bool = True,
    require_digit: bool = True,
    require_special: bool = False,
    allow_whitespace: bool = False,
) -> str:
    """Проверяет пароль и выбрасывает исключение, если он недостаточно сложный.

    Args:
        password: Пароль для проверки.
        min_length: Минимально допустимая длина пароля.
        max_length: Максимально допустимая длина пароля.
        require_letter: Требовать ли наличие хотя бы одной буквы.
        require_digit: Требовать ли наличие хотя бы одной цифры.
        require_special: Требовать ли наличие хотя бы одного специального
            символа.
        allow_whitespace: Разрешать ли пробельные символы в пароле.

    Returns:
        Исходный пароль, если он прошёл проверку сложности.

    Raises:
        ValueError: Если пароль не прошёл проверку сложности.
    """

    result = validate_password_strength(
        password,
        min_length=min_length,
        max_length=max_length,
        require_letter=require_letter,
        require_digit=require_digit,
        require_special=require_special,
        allow_whitespace=allow_whitespace,
    )

    if not result.is_valid:
        raise ValueError("; ".join(result.messages))

    return password
