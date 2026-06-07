import uuid
from typing import Annotated, Any, cast

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.logging import get_logger
from database.models.users import User
from security.dependencies.auth import (
    CurrentAccessPayloadDependency,
    CurrentRefreshPayloadDependency,
    DatabaseSessionDependency,
    OptionalAccessPayloadDependency,
    forbidden_exception,
    unauthorized_exception,
)
from security.permissions import (
    PermissionDeniedError,
    is_active_user,
    require_active_user,
    require_admin,
)

logger = get_logger(__name__)


async def get_user_by_id(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    load_roles: bool = True,
) -> User | None:
    """Возвращает пользователя по идентификатору.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        user_id: Идентификатор пользователя.
        load_roles: Нужно ли заранее загрузить связанные роли пользователя.

    Returns:
        Пользователь или None, если пользователь не найден.

    Raises:
        SecurityDependencyError: Если не удалось выполнить запрос к базе данных.
    """

    statement = select(User).where(User.id == user_id)

    if load_roles:
        statement = statement.options(selectinload(User.roles))

    try:
        result = await session.execute(statement)
        return result.scalar_one_or_none()

    except SQLAlchemyError as exc:
        logger.warning(
            "Failed to load user by id",
            extra={
                "user_id": str(user_id),
                "reason": str(exc),
                "error_type": exc.__class__.__name__,
            },
        )

        raise unauthorized_exception("Не удалось загрузить пользователя.") from exc


async def get_current_user(
    payload: CurrentAccessPayloadDependency,
    session: DatabaseSessionDependency,
) -> User:
    """Возвращает текущего пользователя из access token.

    Args:
        payload: Payload текущего access token.
        session: Асинхронная SQLAlchemy-сессия.

    Returns:
        Пользователь, связанный с access token.

    Raises:
        SecurityDependencyError: Если пользователь из token не найден или не
            удалось загрузить пользователя из базы данных.
    """

    user = await get_user_by_id(session, payload.user_id)

    if user is None:
        raise unauthorized_exception("Пользователь из токена не найден.")

    return user


async def get_optional_current_user(
    payload: OptionalAccessPayloadDependency,
    session: DatabaseSessionDependency,
) -> User | None:
    """Возвращает текущего пользователя, если access token присутствует.

    Args:
        payload: Payload access token или None, если token отсутствует.
        session: Асинхронная SQLAlchemy-сессия.

    Returns:
        Пользователь, связанный с access token, или None, если token
        отсутствует.

    Raises:
        SecurityDependencyError: Если token присутствует, но пользователь из
            token не найден или не удалось загрузить пользователя из базы данных.
    """

    if payload is None:
        return None

    user = await get_user_by_id(session, payload.user_id)

    if user is None:
        raise unauthorized_exception("Пользователь из токена не найден.")

    return user


async def get_current_user_from_refresh_token(
    payload: CurrentRefreshPayloadDependency,
    session: DatabaseSessionDependency,
) -> User:
    """Возвращает текущего пользователя из refresh token.

    Args:
        payload: Payload текущего refresh token.
        session: Асинхронная SQLAlchemy-сессия.

    Returns:
        Пользователь, связанный с refresh token.

    Raises:
        SecurityDependencyError: Если пользователь из refresh token не найден
            или не удалось загрузить пользователя из базы данных.
    """

    user = await get_user_by_id(session, payload.user_id)

    if user is None:
        raise unauthorized_exception("Пользователь из refresh token не найден.")

    return user


# FastAPI dependency для получения текущего пользователя.
CurrentUserDependency = Annotated[User, Depends(get_current_user)]

# FastAPI dependency для получения текущего пользователя, если он авторизован.
OptionalCurrentUserDependency = Annotated[
    User | None, Depends(get_optional_current_user)
]

# FastAPI dependency для получения пользователя из refresh token.
CurrentRefreshUserDependency = Annotated[
    User,
    Depends(get_current_user_from_refresh_token),
]


async def get_current_active_user(user: CurrentUserDependency) -> User:
    """Возвращает текущего активного пользователя.

    Args:
        user: Текущий авторизованный пользователь.

    Returns:
        Текущий активный пользователь.

    Raises:
        SecurityDependencyError: Если пользователь неактивен или заблокирован.
    """

    try:
        require_active_user(cast(Any, user))

    except PermissionDeniedError as exc:
        raise forbidden_exception(
            "Учётная запись неактивна или заблокирована."
        ) from exc

    return user


async def get_optional_active_user(
    user: OptionalCurrentUserDependency,
) -> User | None:
    """Возвращает активного пользователя, если он авторизован.

    Args:
        user: Текущий пользователь или None, если пользователь не авторизован.

    Returns:
        Активный пользователь или None, если пользователь не авторизован.

    Raises:
        SecurityDependencyError: Если пользователь авторизован, но неактивен
            или заблокирован.
    """

    if user is None:
        return None

    if not is_active_user(cast(Any, user)):
        raise forbidden_exception("Учётная запись неактивна или заблокирована.")

    return user


async def get_current_admin_user(user: CurrentUserDependency) -> User:
    """Возвращает текущего пользователя с правами администратора.

    Args:
        user: Текущий авторизованный пользователь.

    Returns:
        Текущий пользователь с правами администратора.

    Raises:
        SecurityDependencyError: Если у пользователя нет прав администратора.
    """

    try:
        require_admin(cast(Any, user))

    except PermissionDeniedError as exc:
        raise forbidden_exception("Требуются права администратора.") from exc

    return user


# FastAPI dependency для получения текущего активного пользователя.
CurrentActiveUserDependency = Annotated[User, Depends(get_current_active_user)]

# FastAPI dependency для получения активного пользователя, если он авторизован.
OptionalActiveUserDependency = Annotated[
    User | None,
    Depends(get_optional_active_user),
]

# FastAPI dependency для получения текущего администратора.
CurrentAdminUserDependency = Annotated[User, Depends(get_current_admin_user)]


def require_authenticated_user(user: CurrentUserDependency) -> User:
    """Возвращает обязательного авторизованного пользователя.

    Args:
        user: Текущий авторизованный пользователь.

    Returns:
        Текущий авторизованный пользователь.
    """

    return user


def require_active_authenticated_user(user: CurrentActiveUserDependency) -> User:
    """Возвращает обязательного активного авторизованного пользователя.

    Args:
        user: Текущий активный пользователь.

    Returns:
        Текущий активный пользователь.
    """

    return user


def require_admin_user(user: CurrentAdminUserDependency) -> User:
    """Возвращает обязательного пользователя-администратора.

    Args:
        user: Текущий пользователь с правами администратора.

    Returns:
        Текущий пользователь с правами администратора.
    """

    return user
