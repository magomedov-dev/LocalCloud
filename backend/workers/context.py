from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass

from core.config import Settings, WorkerSettings, get_settings
from core.constants import WorkerConstants
from database import UnitOfWorkFactory, create_unit_of_work_factory
from services.access import AccessService, get_access_service
from services.audit import AuditService, get_audit_service
from services.downloads import DownloadsService, get_downloads_service
from services.health import HealthService, get_health_service
from services.public_links import PublicLinksService, get_public_links_service
from services.quotas import QuotasService, get_quotas_service
from services.tasks import TasksService, get_tasks_service
from services.trash import TrashService, get_trash_service
from services.uploads import UploadsService, get_uploads_service
from storage import StorageService, get_storage_service


@dataclass(slots=True)
class WorkerServices:
    """Контейнер сервисов worker-процесса.

    Attributes:
        access: Сервис проверки доступа к узлам файловой системы.
        audit: Сервис записи событий аудита.
        tasks: Сервис управления фоновыми задачами.
        trash: Сервис операций с корзиной.
        uploads: Сервис multipart-загрузок.
        public_links: Сервис публичных ссылок.
        quotas: Сервис пользовательских квот.
        downloads: Сервис скачиваний и архивов.
        health: Сервис проверки состояния приложения и зависимостей.
    """

    access: AccessService
    audit: AuditService

    tasks: TasksService
    trash: TrashService
    uploads: UploadsService
    public_links: PublicLinksService
    quotas: QuotasService
    downloads: DownloadsService
    health: HealthService


@dataclass(slots=True)
class WorkerContext:
    """Контекст зависимостей worker-процесса.

    Attributes:
        settings: Общие настройки приложения.
        worker_settings: Настройки worker-процесса.
        uow_factory: Фабрика UnitOfWork для операций с базой данных.
        storage_service: Сервис объектного хранилища.
        services: Контейнер сервисов приложения, доступных worker-процессу.
        worker_id: Уникальный идентификатор текущего worker-процесса.
    """

    settings: Settings
    worker_settings: WorkerSettings
    uow_factory: UnitOfWorkFactory
    storage_service: StorageService
    services: WorkerServices
    worker_id: str


def generate_worker_id(prefix: str | None = None) -> str:
    """Генерирует идентификатор worker-процесса.

    Идентификатор строится из префикса, hostname, PID процесса и короткого
    случайного UUID-фрагмента.

    Args:
        prefix: Префикс идентификатора. Если не передан или пустой после
            обрезки пробелов, используется `WorkerConstants.WORKER_NAME_PREFIX`.

    Returns:
        Строковый идентификатор worker-процесса.
    """

    resolved_prefix = (
        prefix or WorkerConstants.WORKER_NAME_PREFIX
    ).strip() or WorkerConstants.WORKER_NAME_PREFIX
    hostname = socket.gethostname().strip().lower() or "unknown-host"
    pid = os.getpid()
    short_uuid = uuid.uuid4().hex[:8]
    return f"{resolved_prefix}-{hostname}-{pid}-{short_uuid}"


def build_worker_context(worker_id: str | None = None) -> WorkerContext:
    """Собирает полный контекст зависимостей worker-процесса.

    Загружает настройки приложения и worker-слоя, создаёт общую фабрику
    UnitOfWork, сервис хранилища и сервисы приложения с общими зависимостями.
    Если `worker_id` не передан, использует имя worker из настроек или
    генерирует новый идентификатор.

    Args:
        worker_id: Явный идентификатор worker-процесса.

    Returns:
        Контекст зависимостей worker-процесса.
    """

    settings = get_settings()
    worker_settings = settings.workers
    uow_factory = create_unit_of_work_factory()
    storage_service = get_storage_service(settings=settings.storage)

    access_service = get_access_service(uow_factory=uow_factory)
    audit_service = get_audit_service(uow_factory=uow_factory)
    tasks_service = get_tasks_service(
        uow_factory=uow_factory, audit_service=audit_service
    )
    trash_service = get_trash_service(
        settings=settings,
        uow_factory=uow_factory,
        storage_service=storage_service,
        access_service=access_service,
        audit_service=audit_service,
    )
    uploads_service = get_uploads_service(
        settings=settings,
        uow_factory=uow_factory,
        storage_service=storage_service,
        access_service=access_service,
        audit_service=audit_service,
    )
    public_links_service = get_public_links_service(
        settings=settings,
        uow_factory=uow_factory,
        access_service=access_service,
        audit_service=audit_service,
        storage_service=storage_service,
    )
    downloads_service = get_downloads_service(
        settings=settings,
        uow_factory=uow_factory,
        storage_service=storage_service,
        access_service=access_service,
        audit_service=audit_service,
    )
    quotas_service = get_quotas_service(
        uow_factory=uow_factory,
        audit_service=audit_service,
    )
    health_service = get_health_service(
        settings=settings,
        storage_service=storage_service,
    )

    services = WorkerServices(
        access=access_service,
        audit=audit_service,
        tasks=tasks_service,
        trash=trash_service,
        uploads=uploads_service,
        public_links=public_links_service,
        quotas=quotas_service,
        downloads=downloads_service,
        health=health_service,
    )

    resolved_worker_id = (
        worker_id or worker_settings.worker_name or generate_worker_id()
    )
    return WorkerContext(
        settings=settings,
        worker_settings=worker_settings,
        uow_factory=uow_factory,
        storage_service=storage_service,
        services=services,
        worker_id=resolved_worker_id,
    )
