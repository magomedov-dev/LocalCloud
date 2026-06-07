from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from database.client import get_db_session
from security.cookies import (
    CookieError,
    get_access_token_from_cookies,
    get_refresh_token_from_cookies,
    require_access_token_from_cookies,
    require_refresh_token_from_cookies,
)
from security.jwt import (
    JwtExpiredError,
    JwtInvalidClaimsError,
    JwtInvalidTokenTypeError,
    JwtPayload,
    JwtTokenError,
    decode_access_token,
    decode_refresh_token,
)

# HTTP-заголовки для ошибок аутентификации.
AUTHENTICATION_ERROR_HEADERS: dict[str, str] = {"WWW-Authenticate": "Bearer"}

# FastAPI dependency для получения настроек приложения.
SettingsDependency = Annotated[Settings, Depends(get_settings)]

# FastAPI dependency для получения асинхронной сессии базы данных.
DatabaseSessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


class SecurityDependencyError(HTTPException):
    """HTTP-ошибка security dependency.

    Используется для единообразного представления ошибок аутентификации и
    авторизации внутри FastAPI dependencies.
    """

    pass


def unauthorized_exception(
    detail: str = "Не удалось подтвердить учётные данные.",
) -> SecurityDependencyError:
    """Создаёт HTTP 401 ошибку аутентификации.

    Args:
        detail: Описание причины ошибки.

    Returns:
        Исключение ``SecurityDependencyError`` со статусом 401 и заголовком
        ``WWW-Authenticate``.
    """

    return SecurityDependencyError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=AUTHENTICATION_ERROR_HEADERS,
    )


def forbidden_exception(
    detail: str = "Недостаточно прав для выполнения операции.",
) -> SecurityDependencyError:
    """Создаёт HTTP 403 ошибку авторизации.

    Args:
        detail: Описание причины ошибки.

    Returns:
        Исключение ``SecurityDependencyError`` со статусом 403.
    """

    return SecurityDependencyError(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def get_current_access_payload(
    request: Request,
    settings: SettingsDependency,
) -> JwtPayload:
    """Возвращает payload текущего access token из cookie.

    Args:
        request: FastAPI/Starlette request с cookie.
        settings: Настройки приложения.

    Returns:
        Декодированный payload access token.

    Raises:
        SecurityDependencyError: Если access token отсутствует, истёк, имеет
            неверный тип, содержит некорректные claims или недействителен.
    """

    try:
        access_token = require_access_token_from_cookies(request, settings=settings)
        return decode_access_token(access_token, settings=settings)

    except CookieError as exc:
        raise unauthorized_exception("Access token отсутствует.") from exc

    except JwtExpiredError as exc:
        raise unauthorized_exception("Срок действия access token истёк.") from exc

    except JwtInvalidTokenTypeError as exc:
        raise unauthorized_exception("Передан токен недопустимого типа.") from exc

    except JwtInvalidClaimsError as exc:
        raise unauthorized_exception(
            "Access token содержит некорректные данные."
        ) from exc

    except JwtTokenError as exc:
        raise unauthorized_exception("Access token недействителен.") from exc


async def get_optional_access_payload(
    request: Request,
    settings: SettingsDependency,
) -> JwtPayload | None:
    """Возвращает payload access token, если cookie присутствует.

    В отличие от ``get_current_access_payload``, отсутствие access token не
    считается ошибкой и приводит к возврату ``None``.

    Args:
        request: FastAPI/Starlette request с cookie.
        settings: Настройки приложения.

    Returns:
        Декодированный payload access token или ``None``, если cookie
        отсутствует.

    Raises:
        SecurityDependencyError: Если access token присутствует, но истёк,
            имеет неверный тип, содержит некорректные claims или недействителен.
    """

    access_token = get_access_token_from_cookies(request, settings=settings)

    if access_token is None:
        return None

    try:
        return decode_access_token(access_token, settings=settings)

    except JwtExpiredError as exc:
        raise unauthorized_exception("Срок действия access token истёк.") from exc

    except JwtInvalidTokenTypeError as exc:
        raise unauthorized_exception("Передан токен недопустимого типа.") from exc

    except JwtInvalidClaimsError as exc:
        raise unauthorized_exception(
            "Access token содержит некорректные данные."
        ) from exc

    except JwtTokenError as exc:
        raise unauthorized_exception("Access token недействителен.") from exc


async def get_current_refresh_payload(
    request: Request,
    settings: SettingsDependency,
) -> JwtPayload:
    """Возвращает payload текущего refresh token из cookie.

    Args:
        request: FastAPI/Starlette request с cookie.
        settings: Настройки приложения.

    Returns:
        Декодированный payload refresh token.

    Raises:
        SecurityDependencyError: Если refresh token отсутствует, истёк, имеет
            неверный тип, содержит некорректные claims или недействителен.
    """

    try:
        refresh_token = require_refresh_token_from_cookies(request, settings=settings)
        return decode_refresh_token(refresh_token, settings=settings)

    except CookieError as exc:
        raise unauthorized_exception("Refresh token отсутствует.") from exc

    except JwtExpiredError as exc:
        raise unauthorized_exception("Срок действия refresh token истёк.") from exc

    except JwtInvalidTokenTypeError as exc:
        raise unauthorized_exception("Передан токен недопустимого типа.") from exc

    except JwtInvalidClaimsError as exc:
        raise unauthorized_exception(
            "Refresh token содержит некорректные данные."
        ) from exc

    except JwtTokenError as exc:
        raise unauthorized_exception("Refresh token недействителен.") from exc


async def get_optional_refresh_payload(
    request: Request,
    settings: SettingsDependency,
) -> JwtPayload | None:
    """Возвращает payload refresh token, если cookie присутствует.

    В отличие от ``get_current_refresh_payload``, отсутствие refresh token не
    считается ошибкой и приводит к возврату ``None``.

    Args:
        request: FastAPI/Starlette request с cookie.
        settings: Настройки приложения.

    Returns:
        Декодированный payload refresh token или ``None``, если cookie
        отсутствует.

    Raises:
        SecurityDependencyError: Если refresh token присутствует, но истёк,
            имеет неверный тип, содержит некорректные claims или недействителен.
    """

    refresh_token = get_refresh_token_from_cookies(request, settings=settings)

    if refresh_token is None:
        return None

    try:
        return decode_refresh_token(refresh_token, settings=settings)

    except JwtExpiredError as exc:
        raise unauthorized_exception("Срок действия refresh token истёк.") from exc

    except JwtInvalidTokenTypeError as exc:
        raise unauthorized_exception("Передан токен недопустимого типа.") from exc

    except JwtInvalidClaimsError as exc:
        raise unauthorized_exception(
            "Refresh token содержит некорректные данные."
        ) from exc

    except JwtTokenError as exc:
        raise unauthorized_exception("Refresh token недействителен.") from exc


# FastAPI dependency для обязательного access token payload.
CurrentAccessPayloadDependency = Annotated[
    JwtPayload,
    Depends(get_current_access_payload),
]

# FastAPI dependency для необязательного access token payload.
OptionalAccessPayloadDependency = Annotated[
    JwtPayload | None,
    Depends(get_optional_access_payload),
]

# FastAPI dependency для обязательного refresh token payload.
CurrentRefreshPayloadDependency = Annotated[
    JwtPayload,
    Depends(get_current_refresh_payload),
]
