from fastapi import APIRouter, Depends, Response, status

from api.dependencies import get_health_service_from_request_dependency
from database.models.enums import HealthStatus
from schemas.health import (
    DatabaseHealthRead,
    HealthCheckResponse,
    LivenessResponse,
    ReadinessResponse,
    StorageHealthRead,
)
from security import CurrentAdminUserDependency
from services import HealthService

# Маршрутизатор эндпоинтов проверки состояния приложения.
router = APIRouter(prefix="/health", tags=["health"])


def _is_ok(status_value: HealthStatus | str) -> bool:
    """Проверяет, соответствует ли статус успешному состоянию.

    Нормализует переданное значение статуса к строке, удаляет пробелы
    по краям, приводит к нижнему регистру и сравнивает со значением
    `HealthStatus.OK`.

    Args:
        status_value: Статус компонента или приложения в виде `HealthStatus`
            либо строки.

    Returns:
        `True`, если статус соответствует `HealthStatus.OK`, иначе `False`.
    """

    return str(status_value).strip().lower() == HealthStatus.OK.value


@router.get(
    "/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
)
async def get_liveness(
    health_service: HealthService = Depends(get_health_service_from_request_dependency),
) -> LivenessResponse:
    """Выполняет проверку жизнеспособности приложения.

    Возвращает базовый liveness-check, который показывает, что приложение
    запущено и способно отвечать на HTTP-запросы. Обычно используется
    оркестраторами и балансировщиками для определения необходимости
    перезапуска процесса.

    Args:
        health_service: Сервис проверки состояния приложения.

    Returns:
        Результат проверки жизнеспособности приложения.
    """

    return await health_service.get_liveness()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
)
async def get_readiness(
    response: Response,
    health_service: HealthService = Depends(get_health_service_from_request_dependency),
) -> ReadinessResponse:
    """Выполняет проверку готовности приложения.

    Проверяет, готово ли приложение принимать пользовательские запросы.
    Дополнительно выполняет проверку чтения и записи в объектное хранилище.
    Если приложение не готово, устанавливает HTTP-статус ответа
    `503 Service Unavailable`.

    Args:
        response: HTTP-ответ FastAPI, в котором при необходимости изменяется
            статус ответа.
        health_service: Сервис проверки состояния приложения.

    Returns:
        Результат проверки готовности приложения.
    """

    readiness = await health_service.get_readiness(check_storage_read_write=True)
    if not readiness.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return readiness


@router.get(
    "/",
    response_model=HealthCheckResponse,
    status_code=status.HTTP_200_OK,
)
async def get_health_check(
    response: Response,
    health_service: HealthService = Depends(get_health_service_from_request_dependency),
) -> HealthCheckResponse:
    """Выполняет общую проверку состояния приложения.

    Получает агрегированную информацию о состоянии приложения и его ключевых
    компонентов. Если общий статус не соответствует `HealthStatus.OK`,
    устанавливает HTTP-статус ответа `503 Service Unavailable`.

    Args:
        response: HTTP-ответ FastAPI, в котором при необходимости изменяется
            статус ответа.
        health_service: Сервис проверки состояния приложения.

    Returns:
        Агрегированный результат проверки состояния приложения.
    """

    health = await health_service.get_health_check()
    if not _is_ok(health.status):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health


@router.get(
    "/database",
    response_model=DatabaseHealthRead,
    status_code=status.HTTP_200_OK,
)
async def get_database_health(
    response: Response,
    _: CurrentAdminUserDependency,
    health_service: HealthService = Depends(get_health_service_from_request_dependency),
) -> DatabaseHealthRead:
    """Выполняет административную проверку состояния базы данных.

    Запускает health-check только для базы данных. Если проверка базы данных
    недоступна или база данных находится в неуспешном состоянии, устанавливает
    HTTP-статус ответа `503 Service Unavailable`.

    Args:
        response: HTTP-ответ FastAPI, в котором при необходимости изменяется
            статус ответа.
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        health_service: Сервис проверки состояния приложения.

    Returns:
        Результат проверки состояния базы данных.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, не является
            администратором или доступ к административной проверке запрещён.
    """

    health = await health_service.get_health_check(
        check_database=True,
        check_storage=False,
        check_storage_read_write=False,
    )
    database = health.database
    if database is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return DatabaseHealthRead(
            component="database",
            status=HealthStatus.UNAVAILABLE,
            connection=False,
            message="Проверка базы данных недоступна.",
        )
    if not _is_ok(database.status):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return database


@router.get(
    "/storage",
    response_model=StorageHealthRead,
    status_code=status.HTTP_200_OK,
)
async def get_storage_health(
    response: Response,
    _: CurrentAdminUserDependency,
    health_service: HealthService = Depends(get_health_service_from_request_dependency),
) -> StorageHealthRead:
    """Выполняет административную проверку объектного хранилища.

    Запускает health-check только для объектного хранилища, включая проверку
    чтения и записи. Если проверка хранилища недоступна или хранилище находится
    в неуспешном состоянии, устанавливает HTTP-статус ответа
    `503 Service Unavailable`.

    Args:
        response: HTTP-ответ FastAPI, в котором при необходимости изменяется
            статус ответа.
        _: Текущий авторизованный администратор. Используется как зависимость
            безопасности и не применяется внутри функции напрямую.
        health_service: Сервис проверки состояния приложения.

    Returns:
        Результат проверки состояния объектного хранилища.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, не является
            администратором или доступ к административной проверке запрещён.
    """

    health = await health_service.get_health_check(
        check_database=False,
        check_storage=True,
        check_storage_read_write=True,
    )
    storage = health.storage
    if storage is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return StorageHealthRead(
            component="storage",
            status=HealthStatus.UNAVAILABLE,
            connection_ok=False,
            details={"reason": "Проверка хранилища недоступна."},
        )
    if not _is_ok(storage.status):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return storage
