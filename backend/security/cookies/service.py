from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Request, Response

from core.config import Settings, get_settings
from security.cookies.dto import AuthCookieNames, CookieOptions
from security.cookies.enums import AuthCookieName, CookieErrorCode
from security.cookies.exceptions import CookieError
from security.cookies.validators import (
    normalize_cookie_domain,
    normalize_cookie_path,
    normalize_samesite,
    validate_cookie_name,
    validate_cookie_value,
    validate_max_age_seconds,
)


def get_auth_cookie_names(settings: Settings | None = None) -> AuthCookieNames:
    """Возвращает имена authentication cookie из настроек приложения.

    Args:
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        DTO с именами cookie для access и refresh token.

    Raises:
        CookieError: Если имя cookie некорректно.
    """

    app_settings = settings or get_settings()

    return AuthCookieNames(
        access=validate_cookie_name(app_settings.cookies.access_cookie_name),
        refresh=validate_cookie_name(app_settings.cookies.refresh_cookie_name),
    )


def get_cookie_options(settings: Settings | None = None) -> CookieOptions:
    """Возвращает параметры безопасности и области действия cookie.

    Args:
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        DTO с параметрами ``secure``, ``httponly``, ``samesite``, ``domain`` и
        ``path``.

    Raises:
        CookieError: Если настройки cookie некорректны.
    """

    app_settings = settings or get_settings()

    return CookieOptions(
        secure=bool(app_settings.cookies.cookie_secure),
        httponly=bool(app_settings.cookies.cookie_httponly),
        samesite=normalize_samesite(app_settings.cookies.cookie_samesite),
        domain=normalize_cookie_domain(app_settings.cookies.cookie_domain),
        path=normalize_cookie_path(app_settings.cookies.cookie_path),
    )


def set_access_token_cookie(
    response: Response,
    access_token: str,
    *,
    settings: Settings | None = None,
    max_age_seconds: int | None = None,
) -> None:
    """Устанавливает cookie с access token.

    Args:
        response: FastAPI/Starlette response, в который будет добавлена cookie.
        access_token: Access token для сохранения в cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.
        max_age_seconds: Время жизни cookie в секундах. Если не передано,
            используется значение из настроек security.

    Returns:
        ``None``.

    Raises:
        CookieError: Если имя cookie, значение token или max age некорректны.
    """

    app_settings = settings or get_settings()
    names = get_auth_cookie_names(app_settings)
    resolved_max_age = (
        max_age_seconds
        if max_age_seconds is not None
        else app_settings.security.access_token_expire_minutes * 60
    )

    set_auth_cookie(
        response=response,
        name=names.access,
        value=access_token,
        max_age_seconds=resolved_max_age,
        settings=app_settings,
    )


def set_refresh_token_cookie(
    response: Response,
    refresh_token: str,
    *,
    settings: Settings | None = None,
    max_age_seconds: int | None = None,
) -> None:
    """Устанавливает cookie с refresh token.

    Args:
        response: FastAPI/Starlette response, в который будет добавлена cookie.
        refresh_token: Refresh token для сохранения в cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.
        max_age_seconds: Время жизни cookie в секундах. Если не передано,
            используется значение из настроек security.

    Returns:
        ``None``.

    Raises:
        CookieError: Если имя cookie, значение token или max age некорректны.
    """

    app_settings = settings or get_settings()
    names = get_auth_cookie_names(app_settings)
    resolved_max_age = (
        max_age_seconds
        if max_age_seconds is not None
        else app_settings.security.refresh_token_expire_days * 24 * 60 * 60
    )

    set_auth_cookie(
        response=response,
        name=names.refresh,
        value=refresh_token,
        max_age_seconds=resolved_max_age,
        settings=app_settings,
    )


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    settings: Settings | None = None,
    access_max_age_seconds: int | None = None,
    refresh_max_age_seconds: int | None = None,
) -> None:
    """Устанавливает access и refresh token cookie.

    Args:
        response: FastAPI/Starlette response, в который будут добавлены cookie.
        access_token: Access token для сохранения в cookie.
        refresh_token: Refresh token для сохранения в cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.
        access_max_age_seconds: Время жизни access cookie в секундах.
        refresh_max_age_seconds: Время жизни refresh cookie в секундах.

    Returns:
        ``None``.

    Raises:
        CookieError: Если настройки cookie, имена cookie, token или max age
            некорректны.
    """

    app_settings = settings or get_settings()

    set_access_token_cookie(
        response=response,
        access_token=access_token,
        settings=app_settings,
        max_age_seconds=access_max_age_seconds,
    )

    set_refresh_token_cookie(
        response=response,
        refresh_token=refresh_token,
        settings=app_settings,
        max_age_seconds=refresh_max_age_seconds,
    )


def set_auth_cookie(
    response: Response,
    *,
    name: str,
    value: str,
    max_age_seconds: int,
    settings: Settings | None = None,
) -> None:
    """Устанавливает authentication cookie.

    Args:
        response: FastAPI/Starlette response, в который будет добавлена cookie.
        name: Имя cookie.
        value: Значение cookie.
        max_age_seconds: Время жизни cookie в секундах.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        ``None``.

    Raises:
        CookieError: Если имя cookie, значение cookie, max age или настройки
            cookie некорректны.
    """

    cookie_name = validate_cookie_name(name)
    cookie_value = validate_cookie_value(value)
    max_age = validate_max_age_seconds(max_age_seconds)
    options = get_cookie_options(settings)

    response.set_cookie(
        key=cookie_name,
        value=cookie_value,
        max_age=max_age,
        expires=build_cookie_expires(max_age),
        secure=options.secure,
        httponly=options.httponly,
        samesite=options.samesite,
        domain=options.domain,
        path=options.path,
    )


def clear_access_token_cookie(
    response: Response,
    *,
    settings: Settings | None = None,
) -> None:
    """Удаляет cookie с access token.

    Args:
        response: FastAPI/Starlette response, в который будет добавлена команда
            удаления cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        ``None``.

    Raises:
        CookieError: Если имя cookie или настройки cookie некорректны.
    """

    app_settings = settings or get_settings()

    delete_auth_cookie(
        response=response,
        name=get_auth_cookie_names(app_settings).access,
        settings=app_settings,
    )


def clear_refresh_token_cookie(
    response: Response,
    *,
    settings: Settings | None = None,
) -> None:
    """Удаляет cookie с refresh token.

    Args:
        response: FastAPI/Starlette response, в который будет добавлена команда
            удаления cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        ``None``.

    Raises:
        CookieError: Если имя cookie или настройки cookie некорректны.
    """

    app_settings = settings or get_settings()

    delete_auth_cookie(
        response=response,
        name=get_auth_cookie_names(app_settings).refresh,
        settings=app_settings,
    )


def clear_auth_cookies(response: Response, *, settings: Settings | None = None) -> None:
    """Удаляет access и refresh token cookie.

    Args:
        response: FastAPI/Starlette response, в который будут добавлены команды
            удаления cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        ``None``.

    Raises:
        CookieError: Если имена cookie или настройки cookie некорректны.
    """

    app_settings = settings or get_settings()

    clear_access_token_cookie(response, settings=app_settings)
    clear_refresh_token_cookie(response, settings=app_settings)


def delete_auth_cookie(
    response: Response,
    *,
    name: str,
    settings: Settings | None = None,
) -> None:
    """Удаляет authentication cookie по имени.

    Args:
        response: FastAPI/Starlette response, в который будет добавлена команда
            удаления cookie.
        name: Имя cookie для удаления.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        ``None``.

    Raises:
        CookieError: Если имя cookie или настройки cookie некорректны.
    """

    cookie_name = validate_cookie_name(name)
    options = get_cookie_options(settings)

    response.delete_cookie(
        key=cookie_name,
        path=options.path,
        domain=options.domain,
        secure=options.secure,
        httponly=options.httponly,
        samesite=options.samesite,
    )


def get_access_token_from_cookies(
    request: Request,
    *,
    settings: Settings | None = None,
) -> str | None:
    """Возвращает access token из cookie запроса.

    Args:
        request: FastAPI/Starlette request с cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        Access token из cookie или ``None``, если cookie отсутствует или пуста.

    Raises:
        CookieError: Если имя cookie некорректно.
    """

    app_settings = settings or get_settings()

    return get_cookie_value(request, get_auth_cookie_names(app_settings).access)


def get_refresh_token_from_cookies(
    request: Request,
    *,
    settings: Settings | None = None,
) -> str | None:
    """Возвращает refresh token из cookie запроса.

    Args:
        request: FastAPI/Starlette request с cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        Refresh token из cookie или ``None``, если cookie отсутствует или пуста.

    Raises:
        CookieError: Если имя cookie некорректно.
    """

    app_settings = settings or get_settings()

    return get_cookie_value(request, get_auth_cookie_names(app_settings).refresh)


def require_access_token_from_cookies(
    request: Request,
    *,
    settings: Settings | None = None,
) -> str:
    """Возвращает access token из cookie или выбрасывает ошибку.

    Args:
        request: FastAPI/Starlette request с cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        Access token из cookie.

    Raises:
        CookieError: Если access token cookie отсутствует, пуста или имя cookie
            некорректно.
    """

    token = get_access_token_from_cookies(request, settings=settings)

    if token is None:
        raise CookieError(
            "Access token cookie отсутствует.",
            code=CookieErrorCode.INVALID_TOKEN,
            details={"cookie": AuthCookieName.ACCESS.value},
        )

    return token


def require_refresh_token_from_cookies(
    request: Request,
    *,
    settings: Settings | None = None,
) -> str:
    """Возвращает refresh token из cookie или выбрасывает ошибку.

    Args:
        request: FastAPI/Starlette request с cookie.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через ``get_settings()``.

    Returns:
        Refresh token из cookie.

    Raises:
        CookieError: Если refresh token cookie отсутствует, пуста или имя
            cookie некорректно.
    """

    token = get_refresh_token_from_cookies(request, settings=settings)

    if token is None:
        raise CookieError(
            "Refresh token cookie отсутствует.",
            code=CookieErrorCode.INVALID_TOKEN,
            details={"cookie": AuthCookieName.REFRESH.value},
        )

    return token


def get_cookie_value(request: Request, name: str) -> str | None:
    """Возвращает нормализованное значение cookie по имени.

    Args:
        request: FastAPI/Starlette request с cookie.
        name: Имя cookie.

    Returns:
        Значение cookie без пробелов по краям или ``None``, если cookie
        отсутствует либо содержит пустую строку.

    Raises:
        CookieError: Если имя cookie некорректно.
    """

    cookie_name = validate_cookie_name(name)
    value = request.cookies.get(cookie_name)

    if value is None:
        return None

    normalized_value = value.strip()

    if not normalized_value:
        return None

    return normalized_value


def build_cookie_expires(max_age_seconds: int) -> datetime:
    """Создаёт дату истечения cookie на основе max age.

    Args:
        max_age_seconds: Время жизни cookie в секундах.

    Returns:
        UTC datetime, соответствующий моменту истечения cookie.

    Raises:
        CookieError: Если max age некорректен.
    """

    return datetime.now(UTC) + timedelta(
        seconds=validate_max_age_seconds(max_age_seconds)
    )
