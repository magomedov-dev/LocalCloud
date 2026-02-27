from __future__ import annotations

from typing import cast

from security.cookies.enums import CookieErrorCode, CookieSameSite
from security.cookies.exceptions import CookieError


def validate_cookie_name(name: str) -> str:
    """Проверяет и нормализует имя cookie.

    Args:
        name: Имя cookie для проверки.

    Returns:
        Нормализованное имя cookie без пробелов по краям.

    Raises:
        CookieError: Если имя cookie не является строкой, пустое или содержит
            недопустимые символы.
    """

    if not isinstance(name, str):
        raise CookieError(
            "Имя cookie должно быть строкой.",
            code=CookieErrorCode.INVALID_COOKIE_NAME,
            details={"value_type": type(name).__name__},
        )

    normalized_name = name.strip()

    if not normalized_name:
        raise CookieError(
            "Имя cookie не должно быть пустым.",
            code=CookieErrorCode.INVALID_COOKIE_NAME,
        )

    if any(char.isspace() for char in normalized_name):
        raise CookieError(
            "Имя cookie не должно содержать пробельные символы.",
            code=CookieErrorCode.INVALID_COOKIE_NAME,
            details={"cookie_name": normalized_name},
        )

    if any(char in normalized_name for char in (";", ",", "=")):
        raise CookieError(
            "Имя cookie содержит недопустимые символы.",
            code=CookieErrorCode.INVALID_COOKIE_NAME,
            details={"cookie_name": normalized_name},
        )

    return normalized_name


def validate_cookie_value(value: str) -> str:
    """Проверяет и нормализует значение cookie.

    Args:
        value: Значение cookie для проверки.

    Returns:
        Нормализованное значение cookie без пробелов по краям.

    Raises:
        CookieError: Если значение cookie не является строкой или является
            пустым.
    """

    if not isinstance(value, str):
        raise CookieError(
            "Значение cookie должно быть строкой.",
            code=CookieErrorCode.INVALID_TOKEN,
            details={"value_type": type(value).__name__},
        )

    normalized_value = value.strip()

    if not normalized_value:
        raise CookieError(
            "Значение cookie не должно быть пустым.",
            code=CookieErrorCode.INVALID_TOKEN,
        )

    return normalized_value


def validate_max_age_seconds(max_age_seconds: int) -> int:
    """Проверяет время жизни cookie в секундах.

    Args:
        max_age_seconds: Время жизни cookie в секундах.

    Returns:
        Проверенное значение ``max_age_seconds``.

    Raises:
        CookieError: Если ``max_age_seconds`` не является целым числом или
            меньше либо равен нулю.
    """

    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool):
        raise CookieError(
            "max_age cookie должен быть целым числом секунд.",
            code=CookieErrorCode.INVALID_MAX_AGE,
            details={
                "max_age_seconds": max_age_seconds,
                "value_type": type(max_age_seconds).__name__,
            },
        )

    if max_age_seconds <= 0:
        raise CookieError(
            "max_age cookie должен быть больше нуля.",
            code=CookieErrorCode.INVALID_MAX_AGE,
            details={"max_age_seconds": max_age_seconds},
        )

    return max_age_seconds


def normalize_samesite(value: str) -> CookieSameSite:
    """Нормализует значение SameSite для cookie.

    Args:
        value: Значение SameSite.

    Returns:
        Нормализованное значение SameSite: ``lax``, ``strict`` или ``none``.

    Raises:
        CookieError: Если значение SameSite не является строкой или не входит в
            список допустимых значений.
    """

    if not isinstance(value, str):
        raise CookieError(
            "SameSite cookie должен быть строкой.",
            code=CookieErrorCode.INVALID_SAMESITE,
            details={"value_type": type(value).__name__},
        )

    normalized_value = value.strip().lower()

    if normalized_value not in {"lax", "strict", "none"}:
        raise CookieError(
            "SameSite cookie имеет недопустимое значение.",
            code=CookieErrorCode.INVALID_SAMESITE,
            details={
                "samesite": value,
                "allowed_values": ["lax", "strict", "none"],
            },
        )

    return cast(CookieSameSite, normalized_value)


def normalize_cookie_domain(value: str | None) -> str | None:
    """Нормализует domain для cookie.

    Args:
        value: Значение domain или ``None``.

    Returns:
        Нормализованный domain без пробелов по краям. Если значение отсутствует
        или после нормализации стало пустым, возвращается ``None``.

    Raises:
        CookieError: Если domain не является строкой или ``None``.
    """

    if value is None:
        return None

    if not isinstance(value, str):
        raise CookieError(
            "Cookie domain должен быть строкой или None.",
            code=CookieErrorCode.INVALID_SETTINGS,
            details={"value_type": type(value).__name__},
        )

    normalized_value = value.strip()

    if not normalized_value:
        return None

    return normalized_value


def normalize_cookie_path(value: str) -> str:
    """Нормализует path для cookie.

    Args:
        value: Значение path.

    Returns:
        Нормализованный path. Если значение не начинается с ``/``, слеш
        добавляется автоматически.

    Raises:
        CookieError: Если path не является строкой или является пустым.
    """

    if not isinstance(value, str):
        raise CookieError(
            "Cookie path должен быть строкой.",
            code=CookieErrorCode.INVALID_SETTINGS,
            details={"value_type": type(value).__name__},
        )

    normalized_value = value.strip()

    if not normalized_value:
        raise CookieError(
            "Cookie path не должен быть пустым.",
            code=CookieErrorCode.INVALID_SETTINGS,
        )

    if not normalized_value.startswith("/"):
        normalized_value = f"/{normalized_value}"

    return normalized_value
