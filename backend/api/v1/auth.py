from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from api.dependencies import get_auth_service_dependency, get_users_service_dependency
from app.dependencies import build_request_context
from schemas.auth import (
    AuthSessionRead,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RefreshTokenResponse,
)
from schemas.users import CurrentUserRead
from security import (
    CookieError,
    CurrentActiveUserDependency,
    require_refresh_token_from_cookies,
    unauthorized_exception,
)
from services import AuthService, UsersService

# Маршрутизатор эндпоинтов аутентификации.
router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    """Возвращает IP-адрес клиента из HTTP-запроса.

    Формирует контекст запроса и извлекает из него IP-адрес клиента. Значение
    может отсутствовать, если адрес невозможно определить из входящего запроса.

    Args:
        request: Входящий HTTP-запрос FastAPI.

    Returns:
        IP-адрес клиента или `None`, если адрес не был определён.
    """

    return build_request_context(request).client_ip


def _user_agent(request: Request) -> str | None:
    """Возвращает User-Agent клиента из HTTP-запроса.

    Формирует контекст запроса и извлекает из него строку User-Agent. Значение
    может отсутствовать, если соответствующий заголовок не передан клиентом.

    Args:
        request: Входящий HTTP-запрос FastAPI.

    Returns:
        Строка User-Agent клиента или `None`, если заголовок отсутствует.
    """

    return build_request_context(request).user_agent


def _refresh_token_from_request(request: Request) -> str:
    """Извлекает refresh-токен из cookie HTTP-запроса.

    Делегирует получение refresh-токена функции безопасности. Если cookie
    отсутствует или содержит некорректное значение, преобразует ошибку cookie
    в стандартную ошибку неавторизованного доступа.

    Args:
        request: Входящий HTTP-запрос FastAPI.

    Returns:
        Refresh-токен, полученный из cookie запроса.

    Raises:
        HTTPException: Если refresh-токен отсутствует в cookie или не может
            быть извлечён.
    """

    try:
        return require_refresh_token_from_cookies(request)
    except CookieError as exc:
        raise unauthorized_exception("Refresh token отсутствует.") from exc


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> LoginResponse:
    """Выполняет вход пользователя в систему.

    Проверяет переданные учётные данные, создаёт пользовательскую сессию,
    устанавливает необходимые auth cookies в HTTP-ответ и возвращает данные
    успешной аутентификации.

    Args:
        data: Данные для входа пользователя, например логин или email и пароль.
        request: Входящий HTTP-запрос, из которого извлекаются IP-адрес
            и User-Agent клиента.
        response: HTTP-ответ FastAPI, в который сервис может установить
            cookies аутентификации.
        auth_service: Сервис аутентификации, выполняющий бизнес-логику входа.

    Returns:
        Данные успешного входа пользователя.

    Raises:
        HTTPException: Если учётные данные некорректны, пользователь
            заблокирован, неактивен или вход запрещён политиками безопасности.
            Исключение может быть вызвано внутри сервисного слоя.
    """

    return await auth_service.login(
        data,
        response=response,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    status_code=status.HTTP_200_OK,
)
async def refresh_session(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> RefreshTokenResponse:
    """Обновляет пользовательскую сессию по refresh-токену.

    Извлекает refresh-токен из cookie запроса, проверяет его через сервис
    аутентификации, выпускает новую пару токенов и обновляет auth cookies
    в HTTP-ответе.

    Args:
        request: Входящий HTTP-запрос, содержащий refresh-токен в cookie.
        response: HTTP-ответ FastAPI, в который сервис может установить
            обновлённые cookies аутентификации.
        auth_service: Сервис аутентификации, выполняющий обновление сессии.

    Returns:
        Данные обновлённой access/refresh-сессии.

    Raises:
        HTTPException: Если refresh-токен отсутствует, недействителен, истёк,
            был отозван или обновление сессии запрещено.
    """

    refresh_token = _refresh_token_from_request(request)
    return await auth_service.refresh_session(
        refresh_token,
        response=response,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
)
async def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> LogoutResponse:
    """Выполняет выход пользователя из системы.

    Пытается получить refresh-токен из cookie запроса, отзывает связанную
    с ним сессию при наличии токена и очищает auth cookies в HTTP-ответе.
    Отсутствие refresh-токена не прерывает выполнение выхода.

    Args:
        request: Входящий HTTP-запрос, из которого при наличии извлекается
            refresh-токен.
        response: HTTP-ответ FastAPI, в котором сервис очищает auth cookies.
        auth_service: Сервис аутентификации, выполняющий выход пользователя.

    Returns:
        Результат выхода из системы.

    Raises:
        HTTPException: Если сервис аутентификации не смог выполнить выход
            или отзыв сессии по причинам, не связанным с отсутствием cookie.
    """

    refresh_token = None
    try:
        refresh_token = require_refresh_token_from_cookies(request)
    except CookieError:
        refresh_token = None

    return await auth_service.logout(
        refresh_token,
        response=response,
        reason="logout",
    )


@router.get(
    "/me",
    response_model=CurrentUserRead,
    status_code=status.HTTP_200_OK,
)
async def get_me(user: CurrentActiveUserDependency) -> CurrentUserRead:
    """Возвращает данные текущего активного пользователя.

    Преобразует объект текущего пользователя, полученный из зависимости
    безопасности, в публичную схему ответа.

    Args:
        user: Текущий активный пользователь.

    Returns:
        Публичные данные текущего пользователя.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен
            или доступ запрещён.
    """

    return CurrentUserRead.model_validate(user)


@router.get(
    "/sessions",
    response_model=list[AuthSessionRead],
    status_code=status.HTTP_200_OK,
)
async def list_sessions(
    user: CurrentActiveUserDependency,
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> list[AuthSessionRead]:
    """Возвращает список refresh-сессий текущего пользователя.

    Получает активные или все сессии пользователя с поддержкой лимита
    и смещения. По умолчанию возвращаются только активные сессии.

    Args:
        user: Текущий активный пользователь.
        include_inactive: Нужно ли включать в результат неактивные,
            отозванные или завершённые сессии.
        limit: Максимальное количество сессий в ответе.
        offset: Смещение от начала списка сессий.
        auth_service: Сервис аутентификации, выполняющий получение сессий.

    Returns:
        Список refresh-сессий текущего пользователя.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен
            или параметры пагинации не прошли валидацию.
    """

    return await auth_service.list_sessions(
        user_id=user.id,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=AuthSessionRead,
    status_code=status.HTTP_200_OK,
)
async def revoke_session(
    user: CurrentActiveUserDependency,
    session_id: UUID = Path(...),
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> AuthSessionRead:
    """Отзывает refresh-сессию текущего пользователя.

    Завершает указанную refresh-сессию, если она принадлежит текущему
    пользователю. Используется для ручного выхода из отдельной сессии
    на конкретном устройстве или клиенте.

    Args:
        user: Текущий активный пользователь.
        session_id: Уникальный идентификатор refresh-сессии, которую нужно
            отозвать.
        auth_service: Сервис аутентификации, выполняющий отзыв сессии.

    Returns:
        Данные отозванной refresh-сессии.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, сессия не найдена,
            не принадлежит текущему пользователю или уже не может быть отозвана.
    """

    return await auth_service.revoke_session(
        user_id=user.id,
        session_id=session_id,
        reason="session revoked by user",
    )


@router.post(
    "/password/change",
    response_model=CurrentUserRead,
    status_code=status.HTTP_200_OK,
)
async def change_password(
    data: PasswordChangeRequest,
    user: CurrentActiveUserDependency,
    users_service: UsersService = Depends(get_users_service_dependency),
) -> CurrentUserRead:
    """Изменяет пароль текущего активного пользователя.

    Передаёт новый пароль в сервис пользователей и выполняет изменение пароля
    от имени самого пользователя. После успешного изменения возвращает текущие
    публичные данные пользователя.

    Args:
        data: Данные запроса на изменение пароля.
        user: Текущий активный пользователь, для которого меняется пароль.
        users_service: Сервис пользователей, выполняющий изменение пароля.

    Returns:
        Публичные данные текущего пользователя.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            новый пароль не соответствует требованиям безопасности или
            изменение пароля запрещено.
    """

    await users_service.change_password(
        user_id=user.id,
        new_password=data.new_password,
        actor_id=user.id,
    )
    return CurrentUserRead.model_validate(user)


@router.post(
    "/password/reset/request",
    response_model=PasswordResetRequestResponse,
    status_code=status.HTTP_200_OK,
)
async def request_password_reset(
    data: PasswordResetRequest,
    auth_service: AuthService = Depends(get_auth_service_dependency),
) -> PasswordResetRequestResponse:
    """Инициирует сброс пароля пользователя.

    Принимает email и возвращает токен сброса пароля. Ответ намеренно
    одинаков вне зависимости от того, зарегистрирован ли переданный email.

    Args:
        data: Email пользователя, для которого нужно сбросить пароль.
        auth_service: Сервис аутентификации, генерирующий токен сброса.

    Returns:
        Токен сброса пароля и срок его действия.
    """

    return await auth_service.request_password_reset(data)


@router.post(
    "/password/reset/confirm",
    response_model=PasswordResetConfirmResponse,
    status_code=status.HTTP_200_OK,
)
async def confirm_password_reset(
    data: PasswordResetConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service_dependency),
    users_service: UsersService = Depends(get_users_service_dependency),
) -> PasswordResetConfirmResponse:
    """Подтверждает сброс пароля и устанавливает новый пароль.

    Принимает токен сброса пароля и новый пароль, валидирует токен и
    изменяет пароль пользователя.

    Args:
        data: Токен сброса пароля и новый пароль.
        auth_service: Сервис аутентификации, валидирующий токен.
        users_service: Сервис пользователей, применяющий новый пароль.

    Returns:
        Сообщение об успешном изменении пароля.

    Raises:
        HTTPException: Если токен недействителен, истёк или пароль не прошёл
            проверку требований к сложности.
    """

    return await auth_service.confirm_password_reset(data, users_service=users_service)
