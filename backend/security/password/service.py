from __future__ import annotations

from functools import lru_cache

from passlib.context import CryptContext
from passlib.exc import UnknownHashError

from core.config import Settings, get_settings
from security.password.enums import PasswordHashScheme
from security.password.validators import (
    normalize_password_hash_scheme,
    validate_password_value,
)


def build_password_context(scheme: str | PasswordHashScheme) -> CryptContext:
    """Создаёт контекст хеширования паролей.

    Args:
        scheme: Основная схема хеширования паролей.

    Returns:
        Настроенный `CryptContext` с основной и deprecated схемой.

    Raises:
        ValueError: Если схема хеширования не поддерживается.
    """

    normalized_scheme = normalize_password_hash_scheme(scheme)
    deprecated_scheme = "argon2" if normalized_scheme == "bcrypt" else "bcrypt"

    return CryptContext(
        schemes=[normalized_scheme, deprecated_scheme],
        deprecated=[deprecated_scheme],
        bcrypt__rounds=12,
        argon2__time_cost=3,
        argon2__memory_cost=65536,
        argon2__parallelism=4,
    )


@lru_cache(maxsize=8)
def get_password_context(
    scheme: str | PasswordHashScheme | None = None,
) -> CryptContext:
    """Возвращает кэшированный контекст хеширования паролей.

    Args:
        scheme: Схема хеширования паролей. Если не передана, используется
            значение из настроек приложения.

    Returns:
        Кэшированный `CryptContext` для выбранной схемы.

    Raises:
        ValueError: Если схема хеширования не поддерживается.
    """

    app_settings = get_settings()
    resolved_scheme = scheme or app_settings.security.password_hash_scheme

    return build_password_context(resolved_scheme)


def hash_password(
    password: str,
    *,
    scheme: str | PasswordHashScheme | None = None,
) -> str:
    """Хеширует пароль.

    Args:
        password: Пароль в открытом виде.
        scheme: Схема хеширования пароля. Если не передана, используется
            значение из настроек приложения.

    Returns:
        Хеш пароля.

    Raises:
        ValueError: Если пароль или схема хеширования некорректны.
    """

    normalized_password = validate_password_value(password)

    return str(get_password_context(scheme).hash(normalized_password))


def verify_password(
    plain_password: str,
    password_hash: str | None,
    *,
    scheme: str | PasswordHashScheme | None = None,
) -> bool:
    """Проверяет пароль на соответствие хешу.

    Args:
        plain_password: Пароль в открытом виде.
        password_hash: Хеш пароля для проверки.
        scheme: Схема хеширования пароля. Если не передана, используется
            значение из настроек приложения.

    Returns:
        True, если пароль соответствует хешу, иначе False.
    """

    if not isinstance(plain_password, str):
        return False

    if not isinstance(password_hash, str) or not password_hash.strip():
        return False

    try:
        return bool(get_password_context(scheme).verify(plain_password, password_hash))

    except (UnknownHashError, ValueError, TypeError):
        return False


def password_needs_rehash(
    password_hash: str | None,
    *,
    scheme: str | PasswordHashScheme | None = None,
) -> bool:
    """Проверяет, нужно ли пересоздать хеш пароля.

    Args:
        password_hash: Текущий хеш пароля.
        scheme: Целевая схема хеширования пароля. Если не передана,
            используется значение из настроек приложения.

    Returns:
        True, если хеш отсутствует, некорректен, устарел или использует
        deprecated схему, иначе False.
    """

    if not isinstance(password_hash, str) or not password_hash.strip():
        return True

    try:
        return bool(get_password_context(scheme).needs_update(password_hash))

    except (UnknownHashError, ValueError, TypeError):
        return True


def verify_and_update_password_hash(
    plain_password: str,
    password_hash: str | None,
    *,
    scheme: str | PasswordHashScheme | None = None,
) -> tuple[bool, str | None]:
    """Проверяет пароль и при необходимости создаёт новый хеш.

    Args:
        plain_password: Пароль в открытом виде.
        password_hash: Текущий хеш пароля.
        scheme: Целевая схема хеширования пароля. Если не передана,
            используется значение из настроек приложения.

    Returns:
        Кортеж из двух значений:
        - результат проверки пароля;
        - новый хеш, если пароль валиден и старый хеш требует обновления,
          иначе None.
    """

    is_valid = verify_password(
        plain_password=plain_password,
        password_hash=password_hash,
        scheme=scheme,
    )

    if not is_valid:
        return False, None

    if password_needs_rehash(password_hash, scheme=scheme):
        return True, hash_password(plain_password, scheme=scheme)

    return True, None


def get_password_hash_scheme_from_settings(
    settings: Settings | None = None,
) -> PasswordHashScheme:
    """Возвращает схему хеширования паролей из настроек приложения.

    Args:
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        Нормализованная схема хеширования паролей.

    Raises:
        ValueError: Если схема хеширования в настройках не поддерживается.
    """

    app_settings = settings or get_settings()

    return normalize_password_hash_scheme(app_settings.security.password_hash_scheme)
