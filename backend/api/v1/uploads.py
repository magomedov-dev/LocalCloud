from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from api.dependencies import get_uploads_service_dependency
from app.dependencies import build_request_context
from schemas.common import PageResponse
from schemas.uploads import (
    UploadAbortRequest,
    UploadCompleteRequest,
    UploadCompleteResponse,
    UploadPartCompleteRequest,
    UploadPartRead,
    UploadPresignedUrlsResponse,
    UploadProgressRead,
    UploadQueryParams,
    UploadSessionCreateRequest,
    UploadSessionListItem,
    UploadSessionRead,
)
from security import CurrentActiveUserDependency
from services import UploadsService

# Маршрутизатор эндпоинтов для работы с multipart-загрузками.
router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post(
    "/",
    response_model=UploadSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload_session(
    data: UploadSessionCreateRequest,
    request: Request,
    current_user: CurrentActiveUserDependency,
    uploads_service: UploadsService = Depends(get_uploads_service_dependency),
) -> UploadSessionRead:
    """Создаёт upload-сессию multipart-загрузки.

    Формирует контекст HTTP-запроса, извлекает IP-адрес клиента и User-Agent,
    после чего передаёт создание upload-сессии в сервисный слой. Операция
    выполняется от имени текущего активного пользователя.

    Args:
        data: Данные для создания upload-сессии multipart-загрузки.
        request: Текущий HTTP-запрос, из которого формируется контекст клиента.
        current_user: Текущий активный пользователь, создающий upload-сессию.
        uploads_service: Сервис загрузок, выполняющий инициализацию
            multipart-загрузки.

    Returns:
        Созданная upload-сессия.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры создания некорректны или upload-сессию нельзя создать.
    """

    context = build_request_context(request)
    upload_session, _ = await uploads_service.initiate_upload(
        data,
        user_id=current_user.id,
        client_ip=context.client_ip,
        user_agent=context.user_agent,
    )
    return upload_session


@router.get(
    "/",
    response_model=PageResponse[UploadSessionListItem],
    status_code=status.HTTP_200_OK,
)
async def list_upload_sessions(
    current_user: CurrentActiveUserDependency,
    params: UploadQueryParams = Depends(),
    uploads_service: UploadsService = Depends(get_uploads_service_dependency),
) -> PageResponse[UploadSessionListItem]:
    """Возвращает список upload-сессий пользователя.

    Получает страницу upload-сессий текущего пользователя с учётом параметров
    фильтрации, сортировки и пагинации.

    Args:
        current_user: Текущий активный пользователь, запрашивающий список
            upload-сессий.
        params: Параметры запроса для фильтрации, сортировки и пагинации
            upload-сессий.
        uploads_service: Сервис загрузок, выполняющий получение списка
            upload-сессий.

    Returns:
        Страница upload-сессий с метаданными пагинации.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры запроса некорректны или доступ запрещён.
    """

    return await uploads_service.list_uploads(params, user_id=current_user.id)


@router.get(
    "/{upload_id}",
    response_model=UploadSessionRead,
    status_code=status.HTTP_200_OK,
)
async def get_upload_session(
    current_user: CurrentActiveUserDependency,
    upload_id: UUID = Path(...),
    uploads_service: UploadsService = Depends(get_uploads_service_dependency),
) -> UploadSessionRead:
    """Возвращает upload-сессию по идентификатору.

    Получает данные конкретной upload-сессии в контексте текущего пользователя.

    Args:
        current_user: Текущий активный пользователь, запрашивающий
            upload-сессию.
        upload_id: Уникальный идентификатор upload-сессии.
        uploads_service: Сервис загрузок, выполняющий получение upload-сессии.

    Returns:
        Данные найденной upload-сессии.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, upload-сессия
            не найдена или доступ к ней запрещён.
    """

    return await uploads_service.get_upload_session(upload_id, user_id=current_user.id)


@router.post(
    "/{upload_id}/parts/presigned",
    response_model=UploadPresignedUrlsResponse,
    status_code=status.HTTP_200_OK,
)
async def create_upload_part_presigned_urls(
    current_user: CurrentActiveUserDependency,
    upload_id: UUID = Path(...),
    uploads_service: UploadsService = Depends(get_uploads_service_dependency),
) -> UploadPresignedUrlsResponse:
    """Создаёт pre-signed URL для загрузки частей файла.

    Генерирует набор pre-signed URL, которые используются клиентом для загрузки
    частей multipart-файла во внешнее файловое хранилище.

    Args:
        current_user: Текущий активный пользователь, запрашивающий URL
            для загрузки частей.
        upload_id: Уникальный идентификатор upload-сессии.
        uploads_service: Сервис загрузок, выполняющий генерацию URL.

    Returns:
        Ответ со списком pre-signed URL для загрузки частей файла.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, upload-сессия
            не найдена, доступ запрещён или URL нельзя создать.
    """

    return await uploads_service.create_part_urls(upload_id, user_id=current_user.id)


@router.post(
    "/{upload_id}/parts/{part_number}/complete",
    response_model=UploadPartRead,
    status_code=status.HTTP_200_OK,
)
async def complete_upload_part(
    data: UploadPartCompleteRequest,
    current_user: CurrentActiveUserDependency,
    upload_id: UUID = Path(...),
    part_number: int = Path(..., ge=1),
    uploads_service: UploadsService = Depends(get_uploads_service_dependency),
) -> UploadPartRead:
    """Подтверждает успешную загрузку части multipart-сессии.

    Подставляет номер части из URL в данные запроса, подтверждает загрузку
    части через сервисный слой и возвращает данные подтверждённой части.

    Args:
        data: Данные подтверждения загруженной части.
        current_user: Текущий активный пользователь, подтверждающий часть
            загрузки.
        upload_id: Уникальный идентификатор upload-сессии.
        part_number: Порядковый номер подтверждаемой части файла.
        uploads_service: Сервис загрузок, выполняющий подтверждение части.

    Returns:
        Данные подтверждённой части multipart-загрузки.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, upload-сессия
            не найдена, часть некорректна, доступ запрещён или подтверждение
            невозможно.
        ValueError: Если после подтверждения не удалось получить данные
            подтверждённой части загрузки.
    """

    request_data = data.model_copy(update={"part_number": part_number})
    await uploads_service.confirm_part(
        upload_id,
        request_data,
        user_id=current_user.id,
    )
    parts = await uploads_service.get_upload_parts(upload_id, user_id=current_user.id)
    for part in parts:
        if part.part_number == part_number:
            return part
    raise ValueError("Не удалось получить подтверждённую часть загрузки.")


@router.post(
    "/{upload_id}/complete",
    response_model=UploadCompleteResponse,
    status_code=status.HTTP_200_OK,
)
async def complete_upload(
    data: UploadCompleteRequest,
    current_user: CurrentActiveUserDependency,
    upload_id: UUID = Path(...),
    uploads_service: UploadsService = Depends(get_uploads_service_dependency),
) -> UploadCompleteResponse:
    """Завершает multipart-загрузку файла.

    Подставляет идентификатор upload-сессии из URL в данные запроса и передаёт
    завершение multipart-загрузки в сервисный слой.

    Args:
        data: Данные для завершения multipart-загрузки.
        current_user: Текущий активный пользователь, завершающий загрузку.
        upload_id: Уникальный идентификатор upload-сессии.
        uploads_service: Сервис загрузок, выполняющий завершение загрузки.

    Returns:
        Результат завершения multipart-загрузки.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, upload-сессия
            не найдена, доступ запрещён, части загрузки некорректны или загрузку
            нельзя завершить.
    """

    request_data = data.model_copy(update={"upload_session_id": upload_id})
    return await uploads_service.complete_upload(
        request_data,
        user_id=current_user.id,
    )


@router.post(
    "/{upload_id}/abort",
    response_model=UploadSessionRead,
    status_code=status.HTTP_200_OK,
)
async def abort_upload(
    data: UploadAbortRequest,
    current_user: CurrentActiveUserDependency,
    upload_id: UUID = Path(...),
    uploads_service: UploadsService = Depends(get_uploads_service_dependency),
) -> UploadSessionRead:
    """Отменяет upload-сессию.

    Подставляет идентификатор upload-сессии из URL в данные запроса и передаёт
    отмену multipart-загрузки в сервисный слой. Операция выполняется в контексте
    текущего пользователя.

    Args:
        data: Данные для отмены upload-сессии.
        current_user: Текущий активный пользователь, отменяющий загрузку.
        upload_id: Уникальный идентификатор upload-сессии.
        uploads_service: Сервис загрузок, выполняющий отмену upload-сессии.

    Returns:
        Данные отменённой upload-сессии.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, upload-сессия
            не найдена, доступ запрещён или upload-сессию нельзя отменить.
    """

    request_data = data.model_copy(update={"upload_session_id": upload_id})
    return await uploads_service.abort_upload(
        request_data,
        user_id=current_user.id,
    )


@router.get(
    "/{upload_id}/progress",
    response_model=UploadProgressRead,
    status_code=status.HTTP_200_OK,
)
async def get_upload_progress(
    current_user: CurrentActiveUserDependency,
    upload_id: UUID = Path(...),
    uploads_service: UploadsService = Depends(get_uploads_service_dependency),
) -> UploadProgressRead:
    """Возвращает прогресс upload-сессии.

    Получает текущее состояние multipart-загрузки, включая сведения о прогрессе
    загрузки частей файла.

    Args:
        current_user: Текущий активный пользователь, запрашивающий прогресс
            загрузки.
        upload_id: Уникальный идентификатор upload-сессии.
        uploads_service: Сервис загрузок, выполняющий получение прогресса.

    Returns:
        Данные о прогрессе upload-сессии.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, upload-сессия
            не найдена или доступ к ней запрещён.
    """

    return await uploads_service.get_progress(upload_id, user_id=current_user.id)
