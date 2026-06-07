from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from api.dependencies import get_registration_service_dependency
from schemas.common import PageResponse
from schemas.registration import (
    RegistrationApproveRequest,
    RegistrationCancelRequest,
    RegistrationDecisionResponse,
    RegistrationQueryParams,
    RegistrationRejectRequest,
    RegistrationRequestCreate,
    RegistrationRequestListItem,
    RegistrationRequestRead,
)
from security import CurrentAdminUserDependency, OptionalCurrentUserDependency
from services import RegistrationService

# Маршрутизатор эндпоинтов для работы с заявками на регистрацию.
router = APIRouter(prefix="/registration", tags=["registration"])


@router.post(
    "/requests",
    response_model=RegistrationRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_registration_request(
    data: RegistrationRequestCreate,
    registration_service: RegistrationService = Depends(
        get_registration_service_dependency
    ),
) -> RegistrationRequestRead:
    """Создаёт новую заявку на регистрацию.

    Принимает данные будущего пользователя и передаёт их в сервисный слой
    для создания заявки на регистрацию. Эндпоинт не требует обязательной
    пользовательской авторизации.

    Args:
        data: Данные для создания заявки на регистрацию.
        registration_service: Сервис регистрации, выполняющий создание заявки.

    Returns:
        Данные созданной заявки на регистрацию.

    Raises:
        HTTPException: Если данные заявки некорректны, заявка с такими
            параметрами уже существует или создание заявки запрещено.
    """

    return await registration_service.submit_request(data)


@router.get(
    "/requests",
    response_model=PageResponse[RegistrationRequestListItem],
    status_code=status.HTTP_200_OK,
)
async def list_registration_requests(
    _: CurrentAdminUserDependency,
    params: RegistrationQueryParams = Depends(),
    registration_service: RegistrationService = Depends(
        get_registration_service_dependency
    ),
) -> PageResponse[RegistrationRequestListItem]:
    """Возвращает список заявок на регистрацию.

    Получает страницу заявок на регистрацию с учётом параметров фильтрации,
    сортировки и пагинации. Эндпоинт доступен только текущему администратору.

    Args:
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        params: Параметры запроса для фильтрации, сортировки и пагинации заявок.
        registration_service: Сервис регистрации, выполняющий получение списка
            заявок.

    Returns:
        Страница заявок на регистрацию с метаданными пагинации.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, не является
            администратором, параметры запроса некорректны или доступ запрещён.
    """

    return await registration_service.list_requests(params)


@router.get(
    "/requests/{request_id}",
    response_model=RegistrationRequestRead,
    status_code=status.HTTP_200_OK,
)
async def get_registration_request(
    _: CurrentAdminUserDependency,
    request_id: UUID = Path(...),
    registration_service: RegistrationService = Depends(
        get_registration_service_dependency
    ),
) -> RegistrationRequestRead:
    """Возвращает заявку на регистрацию по идентификатору.

    Получает подробные данные одной заявки на регистрацию. Эндпоинт доступен
    только текущему администратору.

    Args:
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        request_id: Уникальный идентификатор заявки на регистрацию.
        registration_service: Сервис регистрации, выполняющий получение заявки.

    Returns:
        Подробные данные заявки на регистрацию.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, не является
            администратором, заявка не найдена или доступ запрещён.
    """

    return await registration_service.get_request(request_id)


@router.post(
    "/requests/{request_id}/approve",
    response_model=RegistrationDecisionResponse,
    status_code=status.HTTP_200_OK,
)
async def approve_registration_request(
    data: RegistrationApproveRequest,
    admin_user: CurrentAdminUserDependency,
    request_id: UUID = Path(...),
    registration_service: RegistrationService = Depends(
        get_registration_service_dependency
    ),
) -> RegistrationDecisionResponse:
    """Одобряет заявку на регистрацию.

    Передаёт решение об одобрении заявки в сервисный слой и фиксирует текущего
    администратора как пользователя, рассмотревшего заявку.

    Args:
        data: Данные для одобрения заявки на регистрацию.
        admin_user: Текущий авторизованный администратор, принимающий решение.
        request_id: Уникальный идентификатор одобряемой заявки.
        registration_service: Сервис регистрации, выполняющий одобрение заявки.

    Returns:
        Результат принятого решения по заявке.

    Raises:
        HTTPException: Если администратор не аутентифицирован, заявка не найдена,
            уже обработана, не может быть одобрена или параметры решения
            некорректны.
    """

    return await registration_service.approve_request(
        request_id,
        data,
        reviewed_by=admin_user.id,
    )


@router.post(
    "/requests/{request_id}/reject",
    response_model=RegistrationDecisionResponse,
    status_code=status.HTTP_200_OK,
)
async def reject_registration_request(
    data: RegistrationRejectRequest,
    admin_user: CurrentAdminUserDependency,
    request_id: UUID = Path(...),
    registration_service: RegistrationService = Depends(
        get_registration_service_dependency
    ),
) -> RegistrationDecisionResponse:
    """Отклоняет заявку на регистрацию.

    Передаёт решение об отклонении заявки в сервисный слой и фиксирует текущего
    администратора как пользователя, рассмотревшего заявку.

    Args:
        data: Данные для отклонения заявки на регистрацию.
        admin_user: Текущий авторизованный администратор, принимающий решение.
        request_id: Уникальный идентификатор отклоняемой заявки.
        registration_service: Сервис регистрации, выполняющий отклонение заявки.

    Returns:
        Результат принятого решения по заявке.

    Raises:
        HTTPException: Если администратор не аутентифицирован, заявка не найдена,
            уже обработана, не может быть отклонена или параметры решения
            некорректны.
    """

    return await registration_service.reject_request(
        request_id,
        data,
        reviewed_by=admin_user.id,
    )


@router.post(
    "/requests/{request_id}/cancel",
    response_model=RegistrationDecisionResponse,
    status_code=status.HTTP_200_OK,
)
async def cancel_registration_request(
    data: RegistrationCancelRequest,
    request_id: UUID = Path(...),
    current_user: OptionalCurrentUserDependency = None,
    registration_service: RegistrationService = Depends(
        get_registration_service_dependency
    ),
) -> RegistrationDecisionResponse:
    """Отменяет заявку на регистрацию.

    Передаёт запрос на отмену заявки в сервисный слой. Авторизация пользователя
    является необязательной: если пользователь присутствует, зависимость может
    использоваться для контекста безопасности, но внутри функции напрямую
    не применяется.

    Args:
        data: Данные для отмены заявки на регистрацию.
        request_id: Уникальный идентификатор отменяемой заявки.
        current_user: Текущий пользователь, если он был определён. Может быть
            `None`, если запрос выполняется без авторизации.
        registration_service: Сервис регистрации, выполняющий отмену заявки.

    Returns:
        Результат отмены заявки на регистрацию.

    Raises:
        HTTPException: Если заявка не найдена, уже обработана, не может быть
            отменена или параметры отмены некорректны.
    """

    _ = current_user
    return await registration_service.cancel_request(request_id, data)
