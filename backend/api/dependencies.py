from fastapi import Request

from services import (
    AuditService,
    AuthService,
    DownloadsService,
    FilesService,
    FoldersService,
    HealthService,
    NodesService,
    PermissionsService,
    PublicLinksService,
    QuotasService,
    RegistrationService,
    TasksService,
    TrashService,
    UploadsService,
    UsersService,
)
from services.audit import get_audit_service
from services.auth import get_auth_service
from services.downloads import get_downloads_service
from services.files import get_files_service
from services.folders import get_folders_service
from services.health import get_health_service
from services.nodes import get_nodes_service
from services.permissions import get_permissions_service
from services.public_links import get_public_links_service
from services.quotas import get_quotas_service
from services.registration import get_registration_service
from services.tasks import get_tasks_service
from services.trash import get_trash_service
from services.uploads import get_uploads_service
from services.users import get_users_service
from storage.capacity import CapacityProvider


def _capacity_provider_from_request(request: Request) -> CapacityProvider | None:
    """Возвращает провайдер ёмкости хранилища из состояния приложения.

    Args:
        request: Текущий HTTP-запрос FastAPI.

    Returns:
        Провайдер ёмкости из ``app.state`` или ``None``, если он не сконструирован
        (тогда сервис создаст его самостоятельно из настроек).
    """

    provider = getattr(request.app.state, "capacity_provider", None)
    return provider if isinstance(provider, CapacityProvider) else None


def get_auth_service_dependency() -> AuthService:
    """Возвращает сервис аутентификации.

    Получает экземпляр `AuthService` через фабричную функцию сервисного слоя.
    Используется как зависимость FastAPI в эндпоинтах аутентификации.

    Returns:
        Сервис аутентификации.
    """

    return get_auth_service()


def get_registration_service_dependency(request: Request) -> RegistrationService:
    """Возвращает сервис регистрации.

    Получает экземпляр `RegistrationService` через фабричную функцию
    сервисного слоя, передавая провайдер ёмкости хранилища из состояния
    приложения для контроля переподписки при одобрении заявок. Используется как
    зависимость FastAPI в эндпоинтах регистрации пользователей.

    Args:
        request: Текущий HTTP-запрос FastAPI, содержащий ссылку на приложение.

    Returns:
        Сервис регистрации.
    """

    return get_registration_service(
        capacity_provider=_capacity_provider_from_request(request),
    )


def get_users_service_dependency() -> UsersService:
    """Возвращает сервис пользователей.

    Получает экземпляр `UsersService` через фабричную функцию сервисного слоя.
    Используется как зависимость FastAPI в эндпоинтах работы с пользователями.

    Returns:
        Сервис пользователей.
    """

    return get_users_service()


def get_quotas_service_dependency(request: Request) -> QuotasService:
    """Возвращает сервис квот.

    Получает экземпляр `QuotasService` через фабричную функцию сервисного слоя,
    передавая провайдер ёмкости хранилища из состояния приложения для контроля
    переподписки. Используется как зависимость FastAPI в эндпоинтах работы с
    квотами.

    Args:
        request: Текущий HTTP-запрос FastAPI, содержащий ссылку на приложение.

    Returns:
        Сервис квот.
    """

    return get_quotas_service(
        capacity_provider=_capacity_provider_from_request(request),
    )


def get_nodes_service_dependency() -> NodesService:
    """Возвращает сервис узлов файловой структуры.

    Получает экземпляр `NodesService` через фабричную функцию сервисного слоя.
    Используется как зависимость FastAPI в эндпоинтах работы с узлами.

    Returns:
        Сервис узлов файловой структуры.
    """

    return get_nodes_service()


def get_folders_service_dependency() -> FoldersService:
    """Возвращает сервис папок.

    Получает экземпляр `FoldersService` через фабричную функцию сервисного слоя.
    Используется как зависимость FastAPI в эндпоинтах работы с папками.

    Returns:
        Сервис папок.
    """

    return get_folders_service()


def get_files_service_dependency() -> FilesService:
    """Возвращает сервис файлов.

    Получает экземпляр `FilesService` через фабричную функцию сервисного слоя.
    Используется как зависимость FastAPI в эндпоинтах работы с файлами.

    Returns:
        Сервис файлов.
    """

    return get_files_service()


def get_uploads_service_dependency() -> UploadsService:
    """Возвращает сервис загрузок.

    Получает экземпляр `UploadsService` через фабричную функцию сервисного слоя.
    Используется как зависимость FastAPI в эндпоинтах multipart-загрузок.

    Returns:
        Сервис загрузок.
    """

    return get_uploads_service()


def get_downloads_service_dependency() -> DownloadsService:
    """Возвращает сервис скачиваний.

    Получает экземпляр `DownloadsService` через фабричную функцию сервисного
    слоя. Используется как зависимость FastAPI в эндпоинтах скачивания файлов.

    Returns:
        Сервис скачиваний.
    """

    return get_downloads_service()


def get_trash_service_dependency() -> TrashService:
    """Возвращает сервис корзины.

    Получает экземпляр `TrashService` через фабричную функцию сервисного слоя.
    Используется как зависимость FastAPI в эндпоинтах работы с корзиной.

    Returns:
        Сервис корзины.
    """

    return get_trash_service()


def get_permissions_service_dependency() -> PermissionsService:
    """Возвращает сервис прав доступа.

    Получает экземпляр `PermissionsService` через фабричную функцию сервисного
    слоя. Используется как зависимость FastAPI в эндпоинтах управления правами
    доступа.

    Returns:
        Сервис прав доступа.
    """

    return get_permissions_service()


def get_public_links_service_dependency() -> PublicLinksService:
    """Возвращает сервис публичных ссылок.

    Получает экземпляр `PublicLinksService` через фабричную функцию сервисного
    слоя. Используется как зависимость FastAPI в эндпоинтах работы с публичными
    ссылками.

    Returns:
        Сервис публичных ссылок.
    """

    return get_public_links_service()


def get_audit_service_dependency() -> AuditService:
    """Возвращает сервис аудита.

    Получает экземпляр `AuditService` через фабричную функцию сервисного слоя.
    Используется как зависимость FastAPI в эндпоинтах просмотра событий аудита.

    Returns:
        Сервис аудита.
    """

    return get_audit_service()


def get_tasks_service_dependency() -> TasksService:
    """Возвращает сервис задач.

    Получает экземпляр `TasksService` через фабричную функцию сервисного слоя.
    Используется как зависимость FastAPI в эндпоинтах работы с фоновыми
    задачами.

    Returns:
        Сервис задач.
    """

    return get_tasks_service()


def get_health_service_from_request_dependency(request: Request) -> HealthService:
    """Возвращает сервис проверки состояния из состояния приложения.

    Пытается получить экземпляр `HealthService` из `request.app.state`.
    Если сервис отсутствует в состоянии приложения или имеет неподходящий тип,
    возвращает экземпляр через стандартную фабричную функцию сервисного слоя.

    Args:
        request: Текущий HTTP-запрос FastAPI, содержащий ссылку на приложение.

    Returns:
        Сервис проверки состояния приложения.
    """

    health_service = getattr(request.app.state, "health_service", None)
    if isinstance(health_service, HealthService):
        return health_service
    return get_health_service()
