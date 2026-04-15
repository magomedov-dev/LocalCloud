from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from api.dependencies import get_downloads_service_dependency
from schemas.files import FileDownloadResponse
from schemas.folders import BulkArchiveRequest, FolderArchiveResponse
from security import CurrentActiveUserDependency
from services import DownloadsService

# Маршрутизатор эндпоинтов для скачивания архивов.
router = APIRouter(prefix="/downloads", tags=["downloads"])


@router.post(
    "/archive/{task_id}",
    response_model=FileDownloadResponse,
    status_code=status.HTTP_200_OK,
)
async def get_archive_download_url(
    current_user: CurrentActiveUserDependency,
    task_id: UUID = Path(...),
    force_download: bool = Query(True),
    filename: str | None = Query(None, max_length=255),
    downloads_service: DownloadsService = Depends(get_downloads_service_dependency),
) -> FileDownloadResponse:
    """Создаёт ссылку для скачивания готового архива папки.

    Проверяет, что фоновая задача с указанным идентификатором является задачей
    создания ZIP-архива, принадлежит текущему пользователю и завершена успешно.
    После успешной проверки создаёт предварительно подписанную ссылку на
    скачивание архива из объектного хранилища.

    Для получения task_id необходимо предварительно запросить архивацию папки
    через POST /folders/{folder_id}/archive и дождаться завершения задачи,
    отслеживая её статус через GET /tasks/{task_id}.

    Args:
        current_user: Текущий активный пользователь, запрашивающий скачивание.
        task_id: Уникальный идентификатор завершённой задачи создания архива.
        force_download: Если True, ссылка формирует заголовок Content-Disposition
            с типом attachment, принудительно инициируя скачивание файла браузером.
            Если False, браузер может попытаться открыть архив inline.
        filename: Пользовательское имя файла архива. Если не указано, имя берётся
            из данных задачи или формируется автоматически.
        downloads_service: Сервис скачиваний, создающий ссылку на архив.

    Returns:
        Данные предварительно подписанной ссылки для скачивания ZIP-архива,
        включая URL, срок действия, HTTP-метод, заголовки и метаданные.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, задача не найдена,
            не является задачей создания архива, принадлежит другому пользователю,
            ещё не завершена или ссылка для скачивания не может быть создана.
    """

    return await downloads_service.create_archive_download_url(
        task_id=task_id,
        user_id=current_user.id,
        force_download=force_download,
        filename=filename,
    )


@router.post(
    "/bulk-archive",
    response_model=FolderArchiveResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_bulk_archive(
    data: BulkArchiveRequest,
    current_user: CurrentActiveUserDependency,
    downloads_service: DownloadsService = Depends(get_downloads_service_dependency),
) -> FolderArchiveResponse:
    """Ставит фоновую задачу на создание ZIP-архива из набора файлов и папок.

    Принимает список идентификаторов узлов (файлов и/или папок), проверяет право
    скачивания на каждый из них и ставит фоновую задачу архивации. Готовый архив
    скачивается тем же способом, что и архив папки — через
    POST /downloads/archive/{task_id} после завершения задачи.

    Args:
        data: Данные запроса со списком узлов и желаемым именем архива.
        current_user: Текущий активный пользователь.
        downloads_service: Сервис скачиваний, создающий задачу архивации.

    Returns:
        Идентификатор созданной фоновой задачи и её статус.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, не имеет доступа к
            одному из узлов, или задачу не удалось поставить.
    """

    return await downloads_service.request_bulk_archive(
        data,
        user_id=current_user.id,
    )
