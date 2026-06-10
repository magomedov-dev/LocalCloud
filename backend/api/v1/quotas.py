from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.dependencies import get_quotas_service_dependency
from schemas.quotas import (
    QuotaCheckRequest,
    QuotaCheckResponse,
    QuotaRecalculateRequest,
    QuotaUsageRead,
    ServerCapacityRead,
    UserQuotaCreate,
    UserQuotaRead,
    UserQuotaUpdate,
)
from security import CurrentActiveUserDependency, CurrentAdminUserDependency
from services import QuotasService

# Маршрутизатор эндпоинтов для работы с квотами пользователей.
router = APIRouter(prefix="/quotas", tags=["quotas"])


@router.get(
    "/me",
    response_model=QuotaUsageRead,
    status_code=status.HTTP_200_OK,
)
async def get_my_quota_usage(
    current_user: CurrentActiveUserDependency,
    quotas_service: QuotasService = Depends(get_quotas_service_dependency),
) -> QuotaUsageRead:
    """Возвращает квоту и текущее использование ресурсов текущего пользователя.

    Получает сведения о лимитах и фактическом потреблении ресурсов для
    аутентифицированного активного пользователя.

    Args:
        current_user: Текущий активный пользователь, для которого запрашивается
            использование квоты.
        quotas_service: Сервис квот, выполняющий получение данных об
            использовании ресурсов.

    Returns:
        Данные о квоте и текущем использовании ресурсов пользователя.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен
            или данные квоты не могут быть получены.
    """

    return await quotas_service.get_usage(current_user.id)


@router.get(
    "/server/capacity",
    response_model=ServerCapacityRead,
    status_code=status.HTTP_200_OK,
)
async def get_server_capacity(
    _: CurrentAdminUserDependency,
    quotas_service: QuotasService = Depends(get_quotas_service_dependency),
) -> ServerCapacityRead:
    """Возвращает состояние общей ёмкости хранилища сервера.

    Показывает общий пул хранилища, суммарно выделенный объём, свободный остаток
    для новых выдач и физические показатели диска по данным MinIO. Позволяет
    администратору контролировать распределение места и обнаруживать
    переподписку. Эндпоинт доступен только администратору.

    Args:
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        quotas_service: Сервис квот, собирающий состояние ёмкости хранилища.

    Returns:
        Состояние общей ёмкости хранилища сервера.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён
            или ёмкость хранилища не может быть определена.
    """

    return await quotas_service.get_server_capacity()


@router.get(
    "/users/{user_id}",
    response_model=QuotaUsageRead,
    status_code=status.HTTP_200_OK,
)
async def get_user_quota_usage(
    _: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    quotas_service: QuotasService = Depends(get_quotas_service_dependency),
) -> QuotaUsageRead:
    """Возвращает квоту и использование ресурсов указанного пользователя.

    Получает сведения о лимитах и фактическом потреблении ресурсов выбранного
    пользователя. Эндпоинт доступен только администратору.

    Args:
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        user_id: Уникальный идентификатор пользователя, для которого нужно
            получить использование квоты.
        quotas_service: Сервис квот, выполняющий получение данных об
            использовании ресурсов.

    Returns:
        Данные о квоте и текущем использовании ресурсов указанного пользователя.

    Raises:
        HTTPException: Если администратор не аутентифицирован, пользователь
            не найден, доступ запрещён или данные квоты не могут быть получены.
    """

    return await quotas_service.get_usage(user_id)


@router.put(
    "/users/{user_id}",
    response_model=UserQuotaRead,
    status_code=status.HTTP_200_OK,
)
async def upsert_user_quota(
    data: UserQuotaUpdate | UserQuotaCreate,
    admin_user: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    quotas_service: QuotasService = Depends(get_quotas_service_dependency),
) -> UserQuotaRead:
    """Создаёт или обновляет квоту пользователя.

    Если тело запроса соответствует схеме создания квоты, проверяет совпадение
    `user_id` из пути и тела запроса, затем создаёт новую квоту. Если тело
    запроса соответствует схеме обновления, изменяет существующую квоту
    указанного пользователя. Операция доступна только администратору.

    Args:
        data: Данные для создания или обновления пользовательской квоты.
        admin_user: Текущий авторизованный администратор, выполняющий операцию.
        user_id: Уникальный идентификатор пользователя, чья квота создаётся
            или обновляется.
        quotas_service: Сервис квот, выполняющий создание или обновление квоты.

    Returns:
        Данные созданной или обновлённой квоты пользователя.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            пользователь не найден, параметры квоты некорректны или `user_id`
            в пути и теле запроса не совпадают.
    """

    if isinstance(data, UserQuotaCreate):
        if data.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id в пути и в теле запроса должны совпадать.",
            )
        return await quotas_service.create_quota(data, actor_id=admin_user.id)

    return await quotas_service.update_quota(
        user_id,
        data,
        actor_id=admin_user.id,
    )


@router.post(
    "/check",
    response_model=QuotaCheckResponse,
    status_code=status.HTTP_200_OK,
)
async def check_quota(
    data: QuotaCheckRequest,
    current_user: CurrentActiveUserDependency,
    quotas_service: QuotasService = Depends(get_quotas_service_dependency),
) -> QuotaCheckResponse:
    """Проверяет возможность расходования квоты текущего пользователя.

    Подставляет идентификатор текущего пользователя в данные запроса и проверяет,
    разрешено ли выполнить операцию, которая увеличит потребление ресурсов.

    Args:
        data: Параметры проверки расходования квоты.
        current_user: Текущий активный пользователь, для которого выполняется
            проверка квоты.
        quotas_service: Сервис квот, выполняющий проверку доступности ресурсов.

    Returns:
        Результат проверки возможности расходования квоты.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры проверки некорректны или проверку невозможно выполнить.
    """

    request_data = data.model_copy(update={"user_id": current_user.id})
    return await quotas_service.check_quota(request_data)


@router.post(
    "/recalculate",
    response_model=UserQuotaRead,
    status_code=status.HTTP_200_OK,
)
async def recalculate_quota(
    data: QuotaRecalculateRequest,
    admin_user: CurrentAdminUserDependency,
    quotas_service: QuotasService = Depends(get_quotas_service_dependency),
) -> UserQuotaRead:
    """Запускает пересчёт квоты пользователя.

    Передаёт запрос на пересчёт квоты в сервисный слой. Операция выполняется
    от имени текущего администратора и может использоваться для синхронизации
    фактического использования ресурсов с сохранёнными данными квоты.

    Args:
        data: Параметры пересчёта квоты.
        admin_user: Текущий авторизованный администратор, запускающий пересчёт.
        quotas_service: Сервис квот, выполняющий пересчёт квоты.

    Returns:
        Данные квоты пользователя после пересчёта.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            пользователь не найден, параметры пересчёта некорректны или пересчёт
            не может быть выполнен.
    """

    return await quotas_service.recalculate_quota(
        data,
        actor_id=admin_user.id,
    )
