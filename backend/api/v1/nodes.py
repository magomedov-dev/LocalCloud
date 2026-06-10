from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from api.dependencies import (
    get_downloads_service_dependency,
    get_files_service_dependency,
    get_folders_service_dependency,
    get_nodes_service_dependency,
)
from schemas.common import PageResponse
from schemas.files import FileDownloadRequest, FileDownloadResponse
from schemas.folders import FolderContentRead
from schemas.nodes import (
    NodeBreadcrumbItem,
    NodeCopyRequest,
    NodeListItem,
    NodeMoveRequest,
    NodeOperationResponse,
    NodeQueryParams,
    NodeRead,
    NodeRenameRequest,
    NodeSearchQuery,
    NodeTreeItem,
    NodeUpdate,
    ThumbnailBatchRequest,
    ThumbnailBatchResponse,
)
from security import (
    CurrentActiveUserDependency,
    RequireDeleteNodeDependency,
    RequireReadNodeDependency,
    RequireWriteNodeDependency,
)
from services import DownloadsService, FilesService, FoldersService, NodesService

# Маршрутизатор эндпоинтов для работы с узлами файловой системы.
router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get(
    "/",
    response_model=PageResponse[NodeListItem],
    status_code=status.HTTP_200_OK,
)
async def list_nodes(
    current_user: CurrentActiveUserDependency,
    params: NodeQueryParams = Depends(),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> PageResponse[NodeListItem]:
    """Возвращает список узлов файловой системы.

    Получает страницу узлов с учётом параметров фильтрации, сортировки
    и пагинации. Результат ограничивается правами доступа текущего пользователя.

    Args:
        current_user: Текущий активный пользователь, запрашивающий список узлов.
        params: Параметры запроса для фильтрации, сортировки и пагинации узлов.
        nodes_service: Сервис узлов, выполняющий получение списка и проверку
            доступа.

    Returns:
        Страница узлов файловой системы с метаданными пагинации.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры запроса некорректны или доступ запрещён.
    """

    return await nodes_service.list_nodes(params, user_id=current_user.id)


@router.get(
    "/tree",
    response_model=NodeTreeItem,
    status_code=status.HTTP_200_OK,
)
async def get_nodes_tree(
    current_user: CurrentActiveUserDependency,
    root_node_id: UUID = Query(...),
    include_deleted: bool = Query(default=False),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> NodeTreeItem:
    """Возвращает дерево узлов от указанного корневого узла.

    Строит дерево файловой системы, начиная с переданного корневого узла.
    При необходимости может включать удалённые узлы, если это поддерживается
    сервисным слоем и разрешено правами пользователя.

    Args:
        current_user: Текущий активный пользователь, запрашивающий дерево.
        root_node_id: Уникальный идентификатор корневого узла дерева.
        include_deleted: Нужно ли включать soft-deleted узлы в результат.
        nodes_service: Сервис узлов, выполняющий построение дерева и проверку
            доступа.

    Returns:
        Дерево узлов файловой системы от указанного корневого узла.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, корневой узел
            не найден, параметры запроса некорректны или доступ запрещён.
    """

    return await nodes_service.get_tree(
        root_node_id,
        user_id=current_user.id,
        include_deleted=include_deleted,
    )


@router.get(
    "/search",
    response_model=PageResponse[NodeListItem],
    status_code=status.HTTP_200_OK,
)
async def search_nodes(
    current_user: CurrentActiveUserDependency,
    params: NodeSearchQuery = Depends(),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> PageResponse[NodeListItem]:
    """Выполняет поиск по узлам файловой системы.

    Ищет узлы по переданным параметрам поиска и возвращает страницу результатов.
    Поиск выполняется в контексте текущего пользователя и учитывает его права
    доступа к найденным узлам.

    Args:
        current_user: Текущий активный пользователь, выполняющий поиск.
        params: Параметры поиска узлов.
        nodes_service: Сервис узлов, выполняющий поиск и проверку доступа.

    Returns:
        Страница найденных узлов с метаданными пагинации.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры поиска некорректны или доступ запрещён.
    """

    return await nodes_service.search_nodes(params, user_id=current_user.id)


@router.post(
    "/thumbnails/batch",
    response_model=ThumbnailBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def get_thumbnails_batch(
    data: ThumbnailBatchRequest,
    current_user: CurrentActiveUserDependency,
    downloads_service: DownloadsService = Depends(get_downloads_service_dependency),
) -> ThumbnailBatchResponse:
    """Возвращает presigned URL для thumbnail каждого из запрошенных узлов.

    Принимает список идентификаторов узлов и параллельно генерирует presigned URL
    для каждого из них. Для недоступных или неизображений узлов возвращает null.
    Позволяет загружать все thumbnail папки одним запросом вместо N запросов.

    Args:
        data: Запрос со списком идентификаторов узлов (не более 100).
        current_user: Текущий активный пользователь.
        downloads_service: Сервис скачивания, выполняющий генерацию URL.

    Returns:
        Словарь node_id → presigned URL (null если узел недоступен).
    """

    thumbnails = await downloads_service.create_thumbnail_urls_batch(
        node_ids=data.node_ids,
        user_id=current_user.id,
    )
    return ThumbnailBatchResponse(thumbnails=thumbnails)


@router.get(
    "/{node_id}",
    response_model=NodeRead,
    status_code=status.HTTP_200_OK,
)
async def get_node(
    current_user: CurrentActiveUserDependency,
    _: None = RequireReadNodeDependency,
    node_id: UUID = Path(...),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> NodeRead:
    """Возвращает узел файловой системы по идентификатору.

    Получает подробные данные узла, если текущий пользователь имеет право
    на чтение этого узла.

    Args:
        current_user: Текущий активный пользователь, запрашивающий узел.
        _: Зависимость проверки права чтения узла. Используется только для
            авторизации и не применяется внутри функции напрямую.
        node_id: Уникальный идентификатор узла.
        nodes_service: Сервис узлов, выполняющий получение данных узла.

    Returns:
        Подробные данные узла файловой системы.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, узел не найден
            или у пользователя нет права на чтение узла.
    """

    return await nodes_service.get_node(node_id, user_id=current_user.id)


@router.patch(
    "/{node_id}",
    response_model=NodeOperationResponse,
    status_code=status.HTTP_200_OK,
)
async def update_node(
    data: NodeUpdate,
    current_user: CurrentActiveUserDependency,
    _: None = RequireWriteNodeDependency,
    node_id: UUID = Path(...),
    recursive_visibility: bool = Query(default=False),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> NodeOperationResponse:
    """Обновляет узел файловой системы.

    Изменяет данные узла от имени текущего пользователя. При включённом
    параметре `recursive_visibility` изменение видимости может быть применено
    рекурсивно к дочерним узлам, если это поддерживается сервисным слоем.

    Args:
        data: Данные для обновления узла.
        current_user: Текущий активный пользователь, выполняющий обновление.
        _: Зависимость проверки права записи в узел. Используется только для
            авторизации и не применяется внутри функции напрямую.
        node_id: Уникальный идентификатор обновляемого узла.
        recursive_visibility: Нужно ли рекурсивно применить изменение видимости
            к дочерним узлам.
        nodes_service: Сервис узлов, выполняющий обновление узла.

    Returns:
        Результат операции обновления узла.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, узел не найден,
            у пользователя нет права записи или данные обновления некорректны.
    """

    return await nodes_service.update_node(
        node_id,
        data,
        actor_id=current_user.id,
        recursive_visibility=recursive_visibility,
    )


@router.post(
    "/{node_id}/rename",
    response_model=NodeOperationResponse,
    status_code=status.HTTP_200_OK,
)
async def rename_node(
    data: NodeRenameRequest,
    current_user: CurrentActiveUserDependency,
    _: None = RequireWriteNodeDependency,
    node_id: UUID = Path(...),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> NodeOperationResponse:
    """Переименовывает узел файловой системы.

    Изменяет имя указанного узла от имени текущего пользователя после проверки
    права записи.

    Args:
        data: Данные для переименования узла.
        current_user: Текущий активный пользователь, выполняющий переименование.
        _: Зависимость проверки права записи в узел. Используется только для
            авторизации и не применяется внутри функции напрямую.
        node_id: Уникальный идентификатор переименовываемого узла.
        nodes_service: Сервис узлов, выполняющий переименование узла.

    Returns:
        Результат операции переименования узла.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, узел не найден,
            у пользователя нет права записи или новое имя узла некорректно.
    """

    return await nodes_service.rename_node(
        node_id,
        data,
        actor_id=current_user.id,
    )


@router.post(
    "/{node_id}/move",
    response_model=NodeOperationResponse,
    status_code=status.HTTP_200_OK,
)
async def move_node(
    data: NodeMoveRequest,
    current_user: CurrentActiveUserDependency,
    _: None = RequireWriteNodeDependency,
    node_id: UUID = Path(...),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> NodeOperationResponse:
    """Перемещает узел файловой системы.

    Переносит указанный узел в новое расположение от имени текущего пользователя
    после проверки права записи.

    Args:
        data: Данные для перемещения узла, включая целевое расположение.
        current_user: Текущий активный пользователь, выполняющий перемещение.
        _: Зависимость проверки права записи в узел. Используется только для
            авторизации и не применяется внутри функции напрямую.
        node_id: Уникальный идентификатор перемещаемого узла.
        nodes_service: Сервис узлов, выполняющий перемещение узла.

    Returns:
        Результат операции перемещения узла.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, узел или целевое
            расположение не найдены, у пользователя нет права записи либо
            перемещение невозможно.
    """

    return await nodes_service.move_node(
        node_id,
        data,
        actor_id=current_user.id,
    )


@router.post(
    "/{node_id}/copy",
    response_model=NodeOperationResponse,
    status_code=status.HTTP_200_OK,
)
async def copy_node(
    data: NodeCopyRequest,
    current_user: CurrentActiveUserDependency,
    _: None = RequireReadNodeDependency,
    node_id: UUID = Path(...),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> NodeOperationResponse:
    """Копирует (дублирует) узел файловой системы.

    Создаёт независимую копию файла или папки от имени текущего пользователя.
    Папка копируется рекурсивно вместе со всем содержимым, а файлы физически
    дублируются в объектном хранилище. При необходимости копия может быть
    помещена в другую папку и/или получить новое имя.

    Args:
        data: Данные копирования, включая целевую папку и необязательное новое
            имя.
        current_user: Текущий активный пользователь, выполняющий копирование.
        _: Зависимость проверки права чтения узла. Используется только для
            авторизации и не применяется внутри функции напрямую.
        node_id: Уникальный идентификатор копируемого узла.
        nodes_service: Сервис узлов, выполняющий копирование узла.

    Returns:
        Результат операции копирования узла с корневым узлом созданной копии.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, узел или целевая
            папка не найдены, у пользователя нет нужных прав либо превышена
            квота.
    """

    return await nodes_service.copy_node(
        node_id,
        data,
        actor_id=current_user.id,
    )


@router.delete(
    "/{node_id}",
    response_model=NodeOperationResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_node(
    current_user: CurrentActiveUserDependency,
    _: None = RequireDeleteNodeDependency,
    node_id: UUID = Path(...),
    recursive: bool = Query(default=True),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> NodeOperationResponse:
    """Выполняет soft delete узла файловой системы.

    Помечает узел как удалённый без физического удаления данных. При включённом
    параметре `recursive` удаление может быть применено к дочерним узлам.

    Args:
        current_user: Текущий активный пользователь, выполняющий удаление.
        _: Зависимость проверки права удаления узла. Используется только для
            авторизации и не применяется внутри функции напрямую.
        node_id: Уникальный идентификатор удаляемого узла.
        recursive: Нужно ли рекурсивно удалить дочерние узлы.
        nodes_service: Сервис узлов, выполняющий soft delete узла.

    Returns:
        Результат операции удаления узла.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, узел не найден,
            у пользователя нет права удаления или удаление невозможно.
    """

    return await nodes_service.delete_node(
        node_id,
        actor_id=current_user.id,
        recursive=recursive,
    )


@router.post(
    "/{node_id}/download",
    response_model=FileDownloadResponse,
    status_code=status.HTTP_200_OK,
)
async def download_node(
    current_user: CurrentActiveUserDependency,
    _: None = RequireReadNodeDependency,
    node_id: UUID = Path(...),
    force_download: bool = Query(default=True),
    files_service: FilesService = Depends(get_files_service_dependency),
    downloads_service: DownloadsService = Depends(get_downloads_service_dependency),
) -> FileDownloadResponse:
    """Создаёт ссылку для скачивания файла по идентификатору узла."""

    file_read = await files_service.get_file(node_id, user_id=current_user.id)
    request_data = FileDownloadRequest(
        file_id=file_read.id, force_download=force_download
    )
    return await downloads_service.create_file_download_url(
        request_data, user_id=current_user.id
    )


@router.get(
    "/{node_id}/stream",
    status_code=status.HTTP_200_OK,
)
async def stream_node(
    request: Request,
    current_user: CurrentActiveUserDependency,
    _: None = RequireReadNodeDependency,
    node_id: UUID = Path(...),
    downloads_service: DownloadsService = Depends(get_downloads_service_dependency),
) -> StreamingResponse:
    """Стримит файл напрямую через backend с поддержкой Range-запросов.

    Обходит все проблемы с заголовками presigned URL: Content-Type,
    Content-Disposition, CORS. Поддерживает Range-запросы для перемотки видео.
    """

    range_header = request.headers.get("Range")
    offset = 0
    length = 0
    status_code = 200
    content_range: str | None = None

    stream, mime_type, name, total_size = await downloads_service.stream_file(
        node_id=node_id,
        user_id=current_user.id,
    )

    if range_header and total_size > 0:
        try:
            unit, ranges = range_header.split("=", 1)
            if unit.strip() == "bytes":
                first_range = ranges.split(",")[0].strip()
                start_str, end_str = first_range.split("-", 1)
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else total_size - 1
                end = min(end, total_size - 1)
                offset = start
                length = end - start + 1
                status_code = 206
                content_range = f"bytes {start}-{end}/{total_size}"
        except Exception:
            pass

    # Only reopen the stream when the client needs data from a non-zero offset
    # (i.e. seeking).  For offset=0 ranges (Chrome's initial Range: bytes=0- probe
    # or a small first-chunk request), we reuse the already-open stream and cap
    # the generator output to avoid a second MinIO round-trip.
    gen_limit: int | None = None
    if offset > 0:
        stream.close()
        stream.release_conn()
        stream, mime_type, name, total_size = await downloads_service.stream_file(
            node_id=node_id,
            user_id=current_user.id,
            offset=offset,
            length=length,
        )
    elif 0 < length < total_size:
        gen_limit = length

    async def generator():
        remaining = gen_limit
        try:
            for chunk in stream:
                if remaining is not None:
                    if len(chunk) >= remaining:
                        yield chunk[:remaining]
                        break
                    yield chunk
                    remaining -= len(chunk)
                else:
                    yield chunk
        finally:
            stream.close()
            stream.release_conn()

    headers: dict[str, str] = {
        "Content-Disposition": f'inline; filename="{name}"',
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=300",
    }
    if content_range:
        headers["Content-Range"] = content_range
    if length > 0:
        headers["Content-Length"] = str(length)
    elif total_size > 0:
        headers["Content-Length"] = str(total_size)

    return StreamingResponse(
        generator(),
        status_code=status_code,
        media_type=mime_type,
        headers=headers,
    )


@router.get(
    "/{node_id}/thumbnail",
    response_model=FileDownloadResponse,
    status_code=status.HTTP_200_OK,
)
async def get_node_thumbnail(
    current_user: CurrentActiveUserDependency,
    response: Response,
    _: None = RequireReadNodeDependency,
    node_id: UUID = Path(...),
    downloads_service: DownloadsService = Depends(get_downloads_service_dependency),
) -> FileDownloadResponse:
    """Возвращает presigned URL для thumbnail или полного файла-изображения.

    Если у файла есть готовый предпросмотр (preview_status=READY), возвращает
    ссылку на preview-объект (~50 KB). Иначе — ссылку на полный файл.
    Ответ кэшируется браузером на 4 минуты.
    """

    result = await downloads_service.create_thumbnail_url(
        node_id=node_id,
        user_id=current_user.id,
    )
    response.headers["Cache-Control"] = "private, max-age=240"
    return result


@router.get(
    "/{node_id}/breadcrumbs",
    response_model=list[NodeBreadcrumbItem],
    status_code=status.HTTP_200_OK,
)
async def get_node_breadcrumbs(
    current_user: CurrentActiveUserDependency,
    _: None = RequireReadNodeDependency,
    node_id: UUID = Path(...),
    include_deleted: bool = Query(default=False),
    nodes_service: NodesService = Depends(get_nodes_service_dependency),
) -> list[NodeBreadcrumbItem]:
    """Возвращает хлебные крошки для узла.

    Формирует путь от корневого узла до указанного узла. При необходимости
    может включать удалённые элементы пути, если это разрешено параметрами
    запроса и поддерживается сервисным слоем.

    Args:
        current_user: Текущий активный пользователь, запрашивающий путь к узлу.
        _: Зависимость проверки права чтения узла. Используется только для
            авторизации и не применяется внутри функции напрямую.
        node_id: Уникальный идентификатор узла.
        include_deleted: Нужно ли разрешить удалённые узлы в хлебных крошках.
        nodes_service: Сервис узлов, выполняющий построение хлебных крошек.

    Returns:
        Список элементов хлебных крошек от корня до указанного узла.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, узел не найден
            или у пользователя нет права на чтение узла.
    """

    return await nodes_service.get_breadcrumbs(
        node_id,
        user_id=current_user.id,
        allow_deleted=include_deleted,
    )


@router.get(
    "/{node_id}/content",
    response_model=FolderContentRead,
    status_code=status.HTTP_200_OK,
)
async def get_folder_content_by_node(
    current_user: CurrentActiveUserDependency,
    _: None = RequireReadNodeDependency,
    node_id: UUID = Path(...),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    folders_service: FoldersService = Depends(get_folders_service_dependency),
) -> FolderContentRead:
    """Возвращает содержимое папки по идентификатору узла.

    Позволяет получить содержимое папки, используя идентификатор узла
    файловой системы вместо идентификатора папки. Поддерживает постраничную
    выдачу дочерних элементов через параметры ``limit`` и ``offset``; поле
    ``total`` в ответе содержит полное количество дочерних узлов.

    Args:
        current_user: Текущий активный пользователь, запрашивающий содержимое.
        _: Зависимость проверки права чтения узла.
        node_id: Уникальный идентификатор узла папки.
        limit: Максимальное количество дочерних элементов в ответе.
        offset: Смещение от начала выборки дочерних элементов.
        folders_service: Сервис папок, выполняющий получение содержимого.

    Returns:
        Содержимое указанной папки с учётом постраничной выдачи.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, узел не найден,
            узел не является папкой или доступ к содержимому запрещён.
    """

    return await folders_service.get_folder_content(
        node_id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
