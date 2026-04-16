import json
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status
from fastapi.responses import JSONResponse

from api.dependencies import get_audit_service_dependency
from schemas.audit import (
    AuditExportRequest,
    AuditLogListItem,
    AuditLogRead,
    AuditQueryParams,
    AuditSummaryRead,
)
from schemas.common import PageResponse
from security import CurrentAdminUserDependency
from services import AuditService

# Маршрутизатор эндпоинтов для работы с журналом аудита.
router = APIRouter(prefix="/audit", tags=["audit"])


@router.get(
    "/logs",
    response_model=PageResponse[AuditLogListItem],
    status_code=status.HTTP_200_OK,
)
async def list_audit_logs(
    _: CurrentAdminUserDependency,
    params: AuditQueryParams = Depends(),
    audit_service: AuditService = Depends(get_audit_service_dependency),
) -> PageResponse[AuditLogListItem]:
    """Возвращает страницу событий журнала аудита.

    Получает список событий аудита с учётом параметров фильтрации, сортировки
    и пагинации. Эндпоинт доступен только текущему администратору.

    Args:
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        params: Параметры запроса для фильтрации, сортировки и пагинации
            событий аудита.
        audit_service: Сервис аудита, выполняющий бизнес-логику получения
            журнала событий.

    Returns:
        Страница событий аудита, содержащая элементы журнала и метаданные
        пагинации.
    """

    return await audit_service.list_logs(params)


@router.get(
    "/logs/{log_id}",
    response_model=AuditLogRead,
    status_code=status.HTTP_200_OK,
)
async def get_audit_log(
    _: CurrentAdminUserDependency,
    log_id: UUID = Path(...),
    audit_service: AuditService = Depends(get_audit_service_dependency),
) -> AuditLogRead:
    """Возвращает событие аудита по идентификатору.

    Получает полную информацию об одном событии аудита. Эндпоинт доступен
    только текущему администратору.

    Args:
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        log_id: Уникальный идентификатор события аудита.
        audit_service: Сервис аудита, выполняющий поиск события.

    Returns:
        Подробные данные события аудита.

    Raises:
        HTTPException: Если событие аудита с указанным идентификатором не
            найдено или доступ к ресурсу запрещён. Исключение может быть
            вызвано внутри сервисного слоя или зависимостей безопасности.
    """

    return await audit_service.get_log(log_id)


@router.get(
    "/summary",
    response_model=AuditSummaryRead,
    status_code=status.HTTP_200_OK,
)
async def get_audit_summary(
    _: CurrentAdminUserDependency,
    params: AuditQueryParams = Depends(),
    audit_service: AuditService = Depends(get_audit_service_dependency),
) -> AuditSummaryRead:
    """Возвращает агрегированную сводку по журналу аудита.

    Формирует статистику по событиям аудита с учётом переданных параметров
    фильтрации. Эндпоинт доступен только текущему администратору.

    Args:
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        params: Параметры запроса, ограничивающие набор событий для расчёта
            сводки.
        audit_service: Сервис аудита, выполняющий агрегацию событий.

    Returns:
        Агрегированная сводка по событиям аудита.
    """

    return await audit_service.get_summary(params)


@router.post(
    "/export",
    response_model=None,
    status_code=status.HTTP_200_OK,
)
async def export_audit_logs(
    data: AuditExportRequest,
    _: CurrentAdminUserDependency,
    audit_service: AuditService = Depends(get_audit_service_dependency),
) -> Response:
    """Экспортирует журнал аудита в файл.

    Создаёт экспорт событий аудита в формате, указанном в запросе. Для JSON
    возвращает `JSONResponse` с распарсенным содержимым, для CSV — текстовый
    ответ с MIME-типом `text/csv`, для остальных форматов — обычный HTTP-ответ
    с MIME-типом, полученным от сервисного слоя.

    Args:
        data: Параметры экспорта журнала аудита, включая формат и возможные
            фильтры.
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        audit_service: Сервис аудита, выполняющий подготовку экспортируемого
            содержимого.

    Returns:
        HTTP-ответ с экспортированным содержимым и заголовком
        `Content-Disposition`, указывающим имя скачиваемого файла.

    Raises:
        JSONDecodeError: Если сервис вернул некорректное JSON-содержимое при
            экспорте в формате JSON.
        HTTPException: Если параметры экспорта некорректны или доступ запрещён.
            Исключение может быть вызвано внутри сервисного слоя или
            зависимостей безопасности.
    """

    payload = await audit_service.export_logs(data)
    content = str(payload.get("content", ""))
    filename = str(payload.get("filename", "audit_logs.export"))
    content_type = str(payload.get("content_type", "application/octet-stream"))
    export_format = str(payload.get("format", "")).lower()

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    if export_format == "json":
        parsed = json.loads(content) if content else []
        return JSONResponse(content=parsed, headers=headers)

    if export_format == "csv":
        return Response(content=content, media_type="text/csv", headers=headers)

    return Response(content=content, media_type=content_type, headers=headers)


@router.get(
    "/users/{user_id}/latest",
    response_model=list[AuditLogListItem],
    status_code=status.HTTP_200_OK,
)
async def get_latest_user_audit_logs(
    _: CurrentAdminUserDependency,
    user_id: UUID = Path(...),
    limit: int = 20,
    audit_service: AuditService = Depends(get_audit_service_dependency),
) -> list[AuditLogListItem]:
    """Возвращает последние события аудита пользователя.

    Получает ограниченный список последних событий аудита, связанных с
    указанным пользователем. Эндпоинт доступен только текущему администратору.

    Args:
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        user_id: Уникальный идентификатор пользователя, для которого нужно
            получить последние события аудита.
        limit: Максимальное количество событий в ответе.
        audit_service: Сервис аудита, выполняющий получение последних событий
            пользователя.

    Returns:
        Список последних событий аудита указанного пользователя.

    Raises:
        HTTPException: Если пользователь или связанные события не найдены,
            значение `limit` некорректно либо доступ запрещён. Исключение может
            быть вызвано внутри сервисного слоя или зависимостей безопасности.
    """

    return await audit_service.get_latest_user_logs(user_id, limit=limit)
