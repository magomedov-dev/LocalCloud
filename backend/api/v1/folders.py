from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from api.dependencies import get_folders_service_dependency
from schemas.folders import (
    FolderArchiveRequest,
    FolderArchiveResponse,
    FolderContentRead,
    FolderCreateRequest,
    FolderRead,
    FolderUpdateRequest,
)
from security import CurrentActiveUserDependency
from services import FoldersService

# Маршрутизатор эндпоинтов для работы с папками.
router = APIRouter(prefix="/folders", tags=["folders"])


@router.post(
    "/",
    response_model=FolderRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    data: FolderCreateRequest,
    current_user: CurrentActiveUserDependency,
    folders_service: FoldersService = Depends(get_folders_service_dependency),
) -> FolderRead:
    """Создаёт новую папку.

    Создаёт папку с переданными параметрами от имени текущего пользователя.
    Текущий пользователь назначается владельцем папки и одновременно
    используется как актор операции.

    Args:
        data: Данные для создания папки.
        current_user: Текущий активный пользователь, создающий папку.
        folders_service: Сервис папок, выполняющий создание папки.

    Returns:
        Данные созданной папки.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры создания некорректны, родительская папка недоступна
            или создание папки запрещено.
    """

    return await folders_service.create_folder(
        data,
        owner_id=current_user.id,
        actor_id=current_user.id,
    )


@router.get(
    "/{folder_id}",
    response_model=FolderRead,
    status_code=status.HTTP_200_OK,
)
async def get_folder(
    current_user: CurrentActiveUserDependency,
    folder_id: UUID = Path(...),
    folders_service: FoldersService = Depends(get_folders_service_dependency),
) -> FolderRead:
    """Возвращает папку по идентификатору.

    Получает внутренний идентификатор узла папки по публичному идентификатору,
    затем возвращает данные папки с учётом прав доступа текущего пользователя.

    Args:
        current_user: Текущий активный пользователь, запрашивающий папку.
        folder_id: Уникальный публичный идентификатор папки.
        folders_service: Сервис папок, выполняющий получение папки и проверку
            доступа.

    Returns:
        Данные запрошенной папки.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, папка не найдена
            или доступ к ней запрещён.
    """

    node_id = await folders_service.get_folder_node_id(folder_id)
    return await folders_service.get_folder(
        node_id,
        user_id=current_user.id,
    )


@router.patch(
    "/{folder_id}",
    response_model=FolderRead,
    status_code=status.HTTP_200_OK,
)
async def update_folder(
    data: FolderUpdateRequest,
    current_user: CurrentActiveUserDependency,
    folder_id: UUID = Path(...),
    folders_service: FoldersService = Depends(get_folders_service_dependency),
) -> FolderRead:
    """Обновляет метаданные папки.

    Получает внутренний идентификатор узла папки по публичному идентификатору,
    затем обновляет метаданные папки от имени текущего пользователя.

    Args:
        data: Новые значения метаданных папки.
        current_user: Текущий активный пользователь, выполняющий обновление.
        folder_id: Уникальный публичный идентификатор папки.
        folders_service: Сервис папок, выполняющий обновление папки.

    Returns:
        Данные папки после обновления.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, папка не найдена,
            доступ запрещён или переданные метаданные некорректны.
    """

    node_id = await folders_service.get_folder_node_id(folder_id)
    return await folders_service.update_folder(
        node_id,
        data,
        actor_id=current_user.id,
    )


@router.get(
    "/{folder_id}/content",
    response_model=FolderContentRead,
    status_code=status.HTTP_200_OK,
)
async def get_folder_content(
    current_user: CurrentActiveUserDependency,
    folder_id: UUID = Path(...),
    folders_service: FoldersService = Depends(get_folders_service_dependency),
) -> FolderContentRead:
    """Возвращает содержимое папки.

    Получает внутренний идентификатор узла папки по публичному идентификатору,
    затем возвращает список вложенных элементов с учётом прав доступа текущего
    пользователя.

    Args:
        current_user: Текущий активный пользователь, запрашивающий содержимое.
        folder_id: Уникальный публичный идентификатор папки.
        folders_service: Сервис папок, выполняющий получение содержимого
            и проверку доступа.

    Returns:
        Содержимое указанной папки.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, папка не найдена
            или доступ к её содержимому запрещён.
    """

    node_id = await folders_service.get_folder_node_id(folder_id)
    return await folders_service.get_folder_content(
        node_id,
        user_id=current_user.id,
    )


@router.post(
    "/{folder_id}/archive",
    response_model=FolderArchiveResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_folder_archive(
    data: FolderArchiveRequest,
    current_user: CurrentActiveUserDependency,
    folder_id: UUID = Path(...),
    folders_service: FoldersService = Depends(get_folders_service_dependency),
) -> FolderArchiveResponse:
    """Создаёт задачу на архивацию папки.

    Получает внутренний идентификатор узла папки по публичному идентификатору,
    подставляет его в данные запроса и запускает фоновую задачу подготовки
    архива папки.

    Args:
        data: Параметры архивации папки.
        current_user: Текущий активный пользователь, запрашивающий архивацию.
        folder_id: Уникальный публичный идентификатор папки.
        folders_service: Сервис папок, создающий задачу архивации.

    Returns:
        Данные созданной задачи архивации папки.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, папка не найдена,
            доступ запрещён или задачу архивации невозможно создать.
    """

    node_id = await folders_service.get_folder_node_id(folder_id)
    request_data = data.model_copy(update={"folder_id": node_id})
    return await folders_service.request_folder_archive(
        request_data,
        actor_id=current_user.id,
    )
