from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from api.dependencies import get_users_service_dependency
from schemas.common import PageResponse
from schemas.users import (
    AdminChangePasswordRequest,
    CurrentUserRead,
    UserAdminUpdate,
    UserBlockRequest,
    UserListItem,
    UserLookupItem,
    UserQueryParams,
    UserRead,
    UserRejectRequest,
    UserUpdate,
    UserWithRolesRead,
)
from security import CurrentActiveUserDependency, CurrentAdminUserDependency
from services import UsersService

# Маршрутизатор эндпоинтов для работы с пользователями.
router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=CurrentUserRead,
    status_code=status.HTTP_200_OK,
)
async def get_me(
    current_user: CurrentActiveUserDependency,
    users_service: UsersService = Depends(get_users_service_dependency),
) -> CurrentUserRead:
    """Возвращает профиль текущего активного пользователя.

    Получает расширенное представление текущего пользователя по его
    идентификатору. Операция выполняется в контексте аутентифицированного
    активного пользователя.

    Args:
        current_user: Текущий активный пользователь, запрашивающий свой профиль.
        users_service: Сервис пользователей, выполняющий получение профиля.

    Returns:
        Данные профиля текущего пользователя.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен
            или его профиль не найден.
    """

    return await users_service.get_current_user_read(current_user.id)


@router.patch(
    "/me",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
)
async def update_me(
    data: UserUpdate,
    current_user: CurrentActiveUserDependency,
    users_service: UsersService = Depends(get_users_service_dependency),
) -> UserRead:
    """Обновляет данные текущего активного пользователя.

    Передаёт изменения профиля в сервисный слой и выполняет обновление
    от имени текущего пользователя.

    Args:
        data: Данные для обновления профиля пользователя.
        current_user: Текущий активный пользователь, обновляющий свой профиль.
        users_service: Сервис пользователей, выполняющий обновление профиля.

    Returns:
        Обновлённые данные пользователя.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            данные обновления некорректны или профиль не найден.
    """

    return await users_service.update_user(
        current_user.id,
        data,
        actor_id=current_user.id,
    )


@router.get(
    "/",
    response_model=PageResponse[UserListItem],
    status_code=status.HTTP_200_OK,
)
async def list_users(
    _: CurrentAdminUserDependency,
    params: UserQueryParams = Depends(),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> PageResponse[UserListItem]:
    """Возвращает список пользователей для администратора.

    Получает страницу пользователей с учётом параметров фильтрации, сортировки
    и пагинации. Эндпоинт доступен только текущему администратору.

    Args:
        _: Текущий администратор, используемый для проверки прав доступа.
        params: Параметры запроса для фильтрации, сортировки и пагинации
            пользователей.
        users_service: Сервис пользователей, выполняющий получение списка.

    Returns:
        Страница пользователей с метаданными пагинации.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён
            или параметры запроса некорректны.
    """

    return await users_service.list_users(params)


@router.get(
    "/lookup",
    response_model=list[UserLookupItem],
    status_code=status.HTTP_200_OK,
)
async def lookup_users(
    current_user: CurrentActiveUserDependency,
    query: str = Query(..., min_length=1, max_length=255),
    limit: int = Query(default=10, ge=1, le=10),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> list[UserLookupItem]:
    """Ищет активных пользователей по email или username для выдачи доступа.

    Доступен любому авторизованному пользователю (в отличие от админского
    списка `GET /users/`). Отдаёт минимальный набор полей и только активных
    пользователей, исключая самого инициатора. Запрос короче двух непробельных
    символов возвращает пустой список.

    Args:
        current_user: Текущий активный пользователь, выполняющий поиск.
        query: Поисковая строка по email или username.
        limit: Максимальное количество результатов (не более 10).
        users_service: Сервис пользователей, выполняющий поиск.

    Returns:
        Список минимальных представлений найденных пользователей.

    Raises:
        HTTPException: Если пользователь не аутентифицирован или неактивен.
    """

    return await users_service.lookup_users(
        query,
        exclude_user_id=current_user.id,
        limit=limit,
    )


@router.get(
    "/{user_id}",
    response_model=UserWithRolesRead,
    status_code=status.HTTP_200_OK,
)
async def get_user(
    _: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> UserWithRolesRead:
    """Возвращает пользователя с ролями для администратора.

    Получает подробные данные пользователя вместе со списком назначенных ролей.
    Эндпоинт доступен только текущему администратору.

    Args:
        _: Текущий администратор, используемый для проверки прав доступа.
        user_id: Уникальный идентификатор пользователя.
        users_service: Сервис пользователей, выполняющий получение пользователя.

    Returns:
        Данные пользователя вместе с его ролями.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён
            или пользователь не найден.
    """

    return await users_service.get_user_with_roles(user_id)


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
)
async def admin_update_user(
    data: UserAdminUpdate,
    admin_user: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> UserRead:
    """Административно обновляет пользователя.

    Передаёт административные изменения пользователя в сервисный слой.
    Операция выполняется от имени текущего администратора.

    Args:
        data: Данные для административного обновления пользователя.
        admin_user: Текущий администратор, выполняющий обновление.
        user_id: Уникальный идентификатор обновляемого пользователя.
        users_service: Сервис пользователей, выполняющий административное
            обновление.

    Returns:
        Обновлённые данные пользователя.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            пользователь не найден или данные обновления некорректны.
    """

    return await users_service.admin_update_user(
        user_id,
        data,
        actor_id=admin_user.id,
    )


@router.post(
    "/{user_id}/block",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
)
async def block_user(
    data: UserBlockRequest,
    admin_user: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> UserRead:
    """Блокирует пользователя.

    Выполняет административную блокировку пользователя с учётом параметров
    запроса. Операция выполняется от имени текущего администратора.

    Args:
        data: Параметры блокировки пользователя.
        admin_user: Текущий администратор, выполняющий блокировку.
        user_id: Уникальный идентификатор блокируемого пользователя.
        users_service: Сервис пользователей, выполняющий блокировку.

    Returns:
        Данные заблокированного пользователя.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            пользователь не найден или блокировку нельзя выполнить.
    """

    return await users_service.block_user(
        user_id,
        data,
        actor_id=admin_user.id,
    )


@router.post(
    "/{user_id}/unblock",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
)
async def unblock_user(
    admin_user: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> UserRead:
    """Разблокирует пользователя.

    Снимает блокировку с пользователя. Операция выполняется от имени текущего
    администратора.

    Args:
        admin_user: Текущий администратор, выполняющий разблокировку.
        user_id: Уникальный идентификатор разблокируемого пользователя.
        users_service: Сервис пользователей, выполняющий разблокировку.

    Returns:
        Данные разблокированного пользователя.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            пользователь не найден или разблокировку нельзя выполнить.
    """

    return await users_service.unblock_user(
        user_id,
        actor_id=admin_user.id,
    )


@router.post(
    "/{user_id}/approve",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
)
async def approve_user(
    admin_user: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> UserRead:
    """Одобряет пользователя.

    Выполняет административное одобрение пользователя.

    Args:
        admin_user: Текущий администратор, выполняющий одобрение.
        user_id: Уникальный идентификатор одобряемого пользователя.
        users_service: Сервис пользователей, выполняющий одобрение.

    Returns:
        Данные одобренного пользователя.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            пользователь не найден или пользователя нельзя одобрить.
    """

    return await users_service.approve_user(
        user_id,
        actor_id=admin_user.id,
    )


@router.post(
    "/{user_id}/reject",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
)
async def reject_user(
    data: UserRejectRequest,
    admin_user: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> UserRead:
    """Отклоняет пользователя.

    Выполняет административное отклонение пользователя с учётом параметров
    запроса. Операция выполняется от имени текущего администратора.

    Args:
        data: Параметры отклонения пользователя.
        admin_user: Текущий администратор, выполняющий отклонение.
        user_id: Уникальный идентификатор отклоняемого пользователя.
        users_service: Сервис пользователей, выполняющий отклонение.

    Returns:
        Данные отклонённого пользователя.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            пользователь не найден или пользователя нельзя отклонить.
    """

    return await users_service.reject_user(
        user_id,
        data,
        actor_id=admin_user.id,
    )


@router.post(
    "/{user_id}/change-password",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
)
async def admin_change_user_password(
    data: AdminChangePasswordRequest,
    admin_user: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> UserRead:
    """Изменяет пароль пользователя администратором.

    Args:
        data: Данные с новым паролем пользователя.
        admin_user: Текущий администратор, выполняющий смену пароля.
        user_id: Уникальный идентификатор пользователя.
        users_service: Сервис пользователей, выполняющий смену пароля.

    Returns:
        Данные пользователя после смены пароля.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            пользователь не найден или пароль не соответствует требованиям.
    """

    return await users_service.change_password(
        user_id,
        data.new_password,
        actor_id=admin_user.id,
    )


@router.delete(
    "/{user_id}",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
)
async def delete_user(
    admin_user: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> UserRead:
    """Выполняет soft-delete пользователя.

    Помечает пользователя как удалённого без физического удаления записи.
    Операция выполняется от имени текущего администратора.

    Args:
        admin_user: Текущий администратор, выполняющий удаление.
        user_id: Уникальный идентификатор удаляемого пользователя.
        users_service: Сервис пользователей, выполняющий soft-delete.

    Returns:
        Данные пользователя после soft-delete.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            пользователь не найден или удаление нельзя выполнить.
    """

    return await users_service.delete_user(
        user_id,
        actor_id=admin_user.id,
    )
