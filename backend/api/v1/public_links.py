from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from api.dependencies import get_public_links_service_dependency
from schemas.common import PageResponse
from schemas.public_links import (
    PublicLinkAccessRequest,
    PublicLinkAccessResponse,
    PublicLinkCreateRequest,
    PublicLinkDownloadResponse,
    PublicLinkFolderArchiveResponse,
    PublicLinkListItem,
    PublicLinkPublicRead,
    PublicLinkQueryParams,
    PublicLinkRead,
    PublicLinkRevokeRequest,
    PublicLinkUpdateRequest,
)
from security import CurrentActiveUserDependency
from services import PublicLinksService

# Маршрутизатор эндпоинтов для управления публичными ссылками.
router = APIRouter(prefix="/public-links", tags=["public-links"])


@router.post(
    "/",
    response_model=PublicLinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_public_link(
    data: PublicLinkCreateRequest,
    current_user: CurrentActiveUserDependency,
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkRead:
    """Создаёт публичную ссылку на узел.

    Создаёт публичную ссылку для указанного узла файловой системы от имени
    текущего пользователя. Параметры ссылки, такие как срок действия, пароль
    или разрешения доступа, передаются в теле запроса.

    Args:
        data: Данные для создания публичной ссылки.
        current_user: Текущий активный пользователь, создающий ссылку.
        public_links_service: Сервис публичных ссылок, выполняющий создание
            ссылки.

    Returns:
        Данные созданной публичной ссылки.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            узел не найден, доступ к узлу запрещён или параметры ссылки
            некорректны.
    """

    return await public_links_service.create_link(data, actor_id=current_user.id)


@router.get(
    "/",
    response_model=PageResponse[PublicLinkListItem],
    status_code=status.HTTP_200_OK,
)
async def list_public_links(
    current_user: CurrentActiveUserDependency,
    params: PublicLinkQueryParams = Depends(),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PageResponse[PublicLinkListItem]:
    """Возвращает список публичных ссылок пользователя.

    Получает страницу публичных ссылок с учётом параметров фильтрации,
    сортировки и пагинации. Результат формируется в контексте текущего
    пользователя.

    Args:
        current_user: Текущий активный пользователь, запрашивающий список
            публичных ссылок.
        params: Параметры запроса для фильтрации, сортировки и пагинации ссылок.
        public_links_service: Сервис публичных ссылок, выполняющий получение
            списка.

    Returns:
        Страница публичных ссылок с метаданными пагинации.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры запроса некорректны или доступ запрещён.
    """

    return await public_links_service.list_links(params, actor_id=current_user.id)


@router.get(
    "/{link_id}",
    response_model=PublicLinkRead,
    status_code=status.HTTP_200_OK,
)
async def get_public_link(
    current_user: CurrentActiveUserDependency,
    link_id: UUID = Path(...),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkRead:
    """Возвращает публичную ссылку по идентификатору.

    Получает подробные данные публичной ссылки, если текущий пользователь
    имеет право просматривать или управлять этой ссылкой.

    Args:
        current_user: Текущий активный пользователь, запрашивающий ссылку.
        link_id: Уникальный идентификатор публичной ссылки.
        public_links_service: Сервис публичных ссылок, выполняющий получение
            ссылки.

    Returns:
        Подробные данные публичной ссылки.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, ссылка не найдена
            или доступ к ней запрещён.
    """

    return await public_links_service.get_link(link_id, actor_id=current_user.id)


@router.patch(
    "/{link_id}",
    response_model=PublicLinkRead,
    status_code=status.HTTP_200_OK,
)
async def update_public_link(
    data: PublicLinkUpdateRequest,
    current_user: CurrentActiveUserDependency,
    link_id: UUID = Path(...),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkRead:
    """Обновляет параметры публичной ссылки.

    Изменяет настройки существующей публичной ссылки от имени текущего
    пользователя. Может обновлять параметры доступа, срок действия и другие
    доступные настройки ссылки.

    Args:
        data: Новые параметры публичной ссылки.
        current_user: Текущий активный пользователь, обновляющий ссылку.
        link_id: Уникальный идентификатор обновляемой публичной ссылки.
        public_links_service: Сервис публичных ссылок, выполняющий обновление
            ссылки.

    Returns:
        Данные публичной ссылки после обновления.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, ссылка не найдена,
            доступ к ней запрещён или параметры обновления некорректны.
    """

    return await public_links_service.update_link(
        link_id,
        data,
        actor_id=current_user.id,
    )


@router.post(
    "/{link_id}/revoke",
    response_model=PublicLinkRead,
    status_code=status.HTTP_200_OK,
)
async def revoke_public_link(
    data: PublicLinkRevokeRequest,
    current_user: CurrentActiveUserDependency,
    link_id: UUID = Path(...),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkRead:
    """Отзывает публичную ссылку.

    Деактивирует публичную ссылку и делает её недоступной для дальнейшего
    публичного использования. Операция выполняется от имени текущего
    пользователя.

    Args:
        data: Параметры отзыва публичной ссылки.
        current_user: Текущий активный пользователь, отзывающий ссылку.
        link_id: Уникальный идентификатор отзываемой публичной ссылки.
        public_links_service: Сервис публичных ссылок, выполняющий отзыв ссылки.

    Returns:
        Данные отозванной публичной ссылки.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, ссылка не найдена,
            доступ к ней запрещён или ссылка уже не может быть отозвана.
    """

    return await public_links_service.revoke_link(
        link_id,
        data,
        actor_id=current_user.id,
    )


@router.get(
    "/public/{token}",
    response_model=PublicLinkPublicRead,
    status_code=status.HTTP_200_OK,
)
async def get_public_link_by_token(
    token: str = Path(..., min_length=1, max_length=128),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkPublicRead:
    """Возвращает публичные данные ссылки по токену.

    Получает безопасную публичную информацию о ссылке без требования
    пользовательской авторизации. Возвращаемые данные должны быть ограничены
    тем, что разрешено показывать внешнему пользователю.

    Args:
        token: Публичный токен ссылки.
        public_links_service: Сервис публичных ссылок, выполняющий получение
            публичных данных.

    Returns:
        Публичные данные ссылки.

    Raises:
        HTTPException: Если токен некорректен, ссылка не найдена, отозвана,
            истекла или недоступна для публичного просмотра.
    """

    return await public_links_service.get_public_link(token)


@router.post(
    "/public/{token}/access",
    response_model=PublicLinkAccessResponse,
    status_code=status.HTTP_200_OK,
)
async def check_public_link_access(
    data: PublicLinkAccessRequest,
    token: str = Path(..., min_length=1, max_length=128),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkAccessResponse:
    """Проверяет доступ к публичной ссылке.

    Подставляет публичный токен из URL в данные запроса и проверяет, может ли
    внешний пользователь получить доступ к ссылке. Тело запроса может содержать
    пароль или другие данные, необходимые для проверки доступа.

    Args:
        data: Данные для проверки доступа к публичной ссылке.
        token: Публичный токен ссылки.
        public_links_service: Сервис публичных ссылок, выполняющий проверку
            доступа.

    Returns:
        Результат проверки доступа к публичной ссылке.

    Raises:
        HTTPException: Если токен некорректен, ссылка не найдена, отозвана,
            истекла, пароль неверен или доступ запрещён.
    """

    request_data = data.model_copy(update={"token": token})
    return await public_links_service.validate_access(request_data)


@router.post(
    "/public/{token}/download",
    response_model=PublicLinkDownloadResponse,
    status_code=status.HTTP_200_OK,
)
async def download_from_public_link(
    data: PublicLinkAccessRequest,
    token: str = Path(..., min_length=1, max_length=128),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkDownloadResponse:
    """Создаёт ссылку на скачивание по публичному токену.

    Подставляет публичный токен из URL в данные запроса, проверяет доступ
    к публичной ссылке и создаёт временную или подписанную ссылку для
    скачивания связанного ресурса.

    Args:
        data: Данные доступа к публичной ссылке, например пароль.
        token: Публичный токен ссылки.
        public_links_service: Сервис публичных ссылок, создающий ссылку
            для скачивания.

    Returns:
        Данные ссылки для скачивания через публичную ссылку.

    Raises:
        HTTPException: Если токен некорректен, ссылка не найдена, отозвана,
            истекла, пароль неверен, скачивание запрещено или ссылка для
            скачивания не может быть создана.
    """

    request_data = data.model_copy(update={"token": token})
    return await public_links_service.create_public_download_url(request_data)


@router.post(
    "/public/{token}/thumbnail",
    response_model=PublicLinkDownloadResponse,
    status_code=status.HTTP_200_OK,
)
async def public_link_thumbnail(
    data: PublicLinkAccessRequest,
    token: str = Path(..., min_length=1, max_length=128),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkDownloadResponse:
    """Создаёт presigned URL для preview-миниатюры файла по публичному токену.

    Требует только право просмотра ссылки и отдаёт сгенерированный preview-объект
    (webp для изображений/PDF/видео), а не исходный файл. Если preview ещё не
    готов или не поддерживается, возвращает 404, и клиент показывает иконку.

    Args:
        data: Данные доступа к публичной ссылке, например пароль.
        token: Публичный токен ссылки.
        public_links_service: Сервис публичных ссылок, создающий ссылку
            на миниатюру.

    Returns:
        Данные presigned URL для preview-миниатюры.

    Raises:
        HTTPException: Если токен некорректен, ссылка недоступна, пароль неверен,
            тип узла не поддерживается или preview отсутствует.
    """

    request_data = data.model_copy(update={"token": token})
    return await public_links_service.create_public_thumbnail_url(request_data)


@router.post(
    "/public/{token}/folder-download",
    response_model=PublicLinkFolderArchiveResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_public_folder_archive(
    data: PublicLinkAccessRequest,
    token: str = Path(..., min_length=1, max_length=128),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkFolderArchiveResponse:
    """Ставит задачу на создание ZIP-архива папки по публичной ссылке.

    Возвращает идентификатор задачи. Опрашивайте GET /public/{token}/folder-download/{task_id}
    до получения статуса completed и ссылки на скачивание.

    Args:
        data: Токен и необязательный пароль публичной ссылки.
        token: Публичный токен ссылки.
        public_links_service: Сервис публичных ссылок.

    Returns:
        Идентификатор задачи и её начальный статус.
    """

    request_data = data.model_copy(update={"token": token})
    return await public_links_service.create_public_folder_archive(request_data)


@router.get(
    "/public/{token}/folder-download/{task_id}",
    response_model=PublicLinkFolderArchiveResponse,
    status_code=status.HTTP_200_OK,
)
async def get_public_folder_archive_status(
    token: str = Path(..., min_length=1, max_length=128),
    task_id: UUID = Path(...),
    public_links_service: PublicLinksService = Depends(
        get_public_links_service_dependency
    ),
) -> PublicLinkFolderArchiveResponse:
    """Возвращает статус архивной задачи и ссылку для скачивания, когда готово.

    Args:
        token: Публичный токен ссылки.
        task_id: Идентификатор фоновой задачи.
        public_links_service: Сервис публичных ссылок.

    Returns:
        Статус задачи и, если статус completed, presigned URL для скачивания.
    """

    return await public_links_service.get_public_folder_archive_status(token, task_id)
