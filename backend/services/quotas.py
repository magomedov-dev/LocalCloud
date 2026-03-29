from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from core.config import get_settings
from core.constants import StorageConstants
from core.logging import get_logger
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import AuditAction, AuditResourceType, QuotaResourceType
from database.models.quotas import UserQuota
from schemas.common import PageMeta, PageResponse
from schemas.quotas import (
    QuotaCheckRequest,
    QuotaCheckResponse,
    QuotaRecalculateRequest,
    QuotaUsageRead,
    ServerCapacityRead,
    UserQuotaCreate,
    UserQuotaRead,
    UserQuotaUpdate,
)
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    InsufficientServerCapacityError,
    QuotaExceededServiceError,
    ServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
)
from storage.capacity import CapacityProvider, get_capacity_provider
from storage.exceptions import StorageCapacityError

logger = get_logger("services.quotas")

SERVICE_NAME = "quotas"
MAX_PAGE_LIMIT = 1000
REPOSITORY_PAGE_LIMIT = 1000


async def enforce_server_capacity(
    *,
    uow: Any,
    capacity_provider: CapacityProvider,
    user_id: UUID | None,
    new_limit: int,
    previous_limit: int | None,
) -> None:
    """Проверяет, что выделение ``new_limit`` помещается в пул сервера.

    Единая точка контроля переподписки для всех путей выдачи квот (создание,
    повышение, выдача новому пользователю). Берёт advisory-блокировку, чтобы
    конкурентные выдачи не превысили пул на устаревшем чтении суммы, затем
    сравнивает прогнозируемый суммарный объём с пулом.

    Понижение или сохранение лимита (``delta <= 0``) разрешено всегда — даже при
    уже существующей переподписке, что позволяет «лечить» её снижением квот.

    Должна вызываться внутри открытой транзакции ``uow`` ДО любых
    ``SELECT ... FOR UPDATE`` по строкам квот (порядок блокировок против
    дедлоков).

    Args:
        uow: Открытый Unit of Work (его сессия используется для блокировки и
            чтения суммы).
        capacity_provider: Провайдер ёмкости хранилища.
        user_id: Идентификатор пользователя, которому выделяется место, или
            ``None`` для ещё не созданного пользователя (тогда из суммы ничего
            не исключается).
        new_limit: Новый лимит хранилища пользователя в байтах.
        previous_limit: Прежний лимит пользователя в байтах (``None`` при
            создании квоты).

    Raises:
        InsufficientServerCapacityError: Если выделение превысит пул сервера или
            если пул невозможно определить (fail-closed).
    """

    delta = new_limit - (previous_limit or 0)
    if delta <= 0:
        return

    await uow.quotas.acquire_capacity_lock()

    try:
        pool = await capacity_provider.get_pool_bytes()
    except StorageCapacityError as exc:
        raise InsufficientServerCapacityError(
            "Невозможно определить ёмкость хранилища сервера; выделение места "
            "временно недоступно.",
            user_id=user_id,
            requested=new_limit,
            cause=exc,
        ) from exc

    allocated_others = await uow.quotas.total_allocated_storage_bytes(
        exclude_user_id=user_id,
    )
    projected = allocated_others + new_limit
    if projected > pool:
        raise InsufficientServerCapacityError(
            user_id=user_id,
            pool=pool,
            allocated=allocated_others,
            requested=new_limit,
            available=max(pool - allocated_others, 0),
        )


class QuotasService:
    """Сервис бизнес-логики для пользовательских квот.

    Управляет лимитами и счетчиками использования ресурсов пользователя.
    Сервис создает квоты, проверяет доступность ресурсов, обновляет счетчики,
    пересчитывает использование по данным базы и записывает события аудита.

    Attributes:
        uow_factory: Фабрика Unit of Work для работы с базой данных.
        audit_service: Сервис записи событий аудита.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
        audit_service: AuditService | None = None,
        capacity_provider: CapacityProvider | None = None,
    ) -> None:
        """Инициализирует сервис квот.

        Если зависимости не переданы явно, создает их через стандартные фабрики
        и функции получения сервисов.

        Args:
            uow_factory: Фабрика Unit of Work. Если None, создается стандартная
                фабрика.
            audit_service: Сервис аудита. Если None, создается стандартный сервис
                аудита.
            capacity_provider: Провайдер ёмкости хранилища для контроля
                переподписки. Если None, создаётся из настроек.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory,
        )
        self.capacity_provider = capacity_provider or get_capacity_provider(
            get_settings().storage,
        )

    async def create_quota(
        self, data: UserQuotaCreate, *, actor_id: UUID | None = None
    ) -> UserQuotaRead:
        """Создает явную квоту пользователя.

        Создает запись UserQuota с переданными лимитами и начальными счетчиками
        использования. После успешного создания записывает событие аудита.

        Args:
            data: Данные для создания квоты пользователя.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие аудита записывается как системное.

        Returns:
            Данные созданной квоты пользователя.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "create_quota"
        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                await enforce_server_capacity(
                    uow=uow,
                    capacity_provider=self.capacity_provider,
                    user_id=data.user_id,
                    new_limit=data.storage_limit_bytes,
                    previous_limit=None,
                )
                quota = await uow.quotas.create_quota(
                    user_id=data.user_id,
                    storage_limit_bytes=data.storage_limit_bytes,
                    max_file_size_bytes=data.max_file_size_bytes,
                    storage_used_bytes=data.storage_used_bytes,
                    files_limit=data.files_limit,
                    files_used=data.files_used,
                    public_links_limit=data.public_links_limit,
                    public_links_used=data.public_links_used,
                    active_upload_sessions_limit=data.active_upload_sessions_limit,
                    active_upload_sessions_used=data.active_upload_sessions_used,
                    flush=True,
                    refresh=True,
                )
                snapshot = _quota_snapshot(quota)
                await uow.commit()

            await self._safe_log_quota_event(
                actor_id=actor_id,
                user_id=data.user_id,
                action=AuditAction.QUOTA_CREATED,
                entity_id=snapshot["id"],
                message="Пользовательская квота была создана.",
                metadata={"operation": operation, "quota": _audit_quota(snapshot)},
            )
            return _quota_read(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось создать квоту пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при создании квоты пользователя.",
            ) from exc

    async def create_default_quota(
        self,
        user_id: UUID,
        *,
        actor_id: UUID | None = None,
        storage_limit_bytes: int = StorageConstants.DEFAULT_STORAGE_LIMIT_BYTES,
        max_file_size_bytes: int = 1024 * 1024 * 1024,
        files_limit: int | None = None,
        public_links_limit: int | None = 100,
        active_upload_sessions_limit: int | None = 10,
    ) -> UserQuotaRead:
        """Создает стандартную квоту пользователя.

        Создает квоту с дефолтными лимитами LocalCloud или с лимитами, переданными
        явно. Начальные счетчики использования задаются репозиторием квот.

        Args:
            user_id: Идентификатор пользователя, для которого создается квота.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие аудита записывается как системное.
            storage_limit_bytes: Лимит общего объема хранилища в байтах.
            max_file_size_bytes: Максимальный размер одного файла в байтах.
            files_limit: Лимит количества файлов. Если None, количество файлов
                не ограничено.
            public_links_limit: Лимит количества публичных ссылок. Если None,
                количество публичных ссылок не ограничено.
            active_upload_sessions_limit: Лимит активных upload-сессий. Если None,
                количество активных сессий не ограничено.

        Returns:
            Данные созданной стандартной квоты.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "create_default_quota"
        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                await enforce_server_capacity(
                    uow=uow,
                    capacity_provider=self.capacity_provider,
                    user_id=user_id,
                    new_limit=storage_limit_bytes,
                    previous_limit=None,
                )
                quota = await uow.quotas.create_default_quota(
                    user_id=user_id,
                    storage_limit_bytes=storage_limit_bytes,
                    max_file_size_bytes=max_file_size_bytes,
                    files_limit=files_limit,
                    public_links_limit=public_links_limit,
                    active_upload_sessions_limit=active_upload_sessions_limit,
                    flush=True,
                    refresh=True,
                )
                snapshot = _quota_snapshot(quota)
                await uow.commit()

            await self._safe_log_quota_event(
                actor_id=actor_id,
                user_id=user_id,
                action=AuditAction.QUOTA_CREATED,
                entity_id=snapshot["id"],
                message="Создана пользовательская квота по умолчанию.",
                metadata={"operation": operation, "quota": _audit_quota(snapshot)},
            )
            return _quota_read(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось создать стандартную квоту пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при создании стандартной квоты.",
            ) from exc

    async def ensure_default_quota(
        self,
        user_id: UUID,
        *,
        actor_id: UUID | None = None,
        storage_limit_bytes: int = StorageConstants.DEFAULT_STORAGE_LIMIT_BYTES,
        max_file_size_bytes: int = 1024 * 1024 * 1024,
        files_limit: int | None = None,
        public_links_limit: int | None = 100,
        active_upload_sessions_limit: int | None = 10,
    ) -> UserQuotaRead:
        """Возвращает существующую квоту или создает стандартную.

        Сначала пытается найти квоту пользователя. Если квота существует,
        возвращает ее. Если квота отсутствует, создает новую стандартную квоту.

        Args:
            user_id: Идентификатор пользователя.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                создание квоты логируется как системное событие.
            storage_limit_bytes: Лимит общего объема хранилища в байтах для новой
                квоты.
            max_file_size_bytes: Максимальный размер одного файла в байтах для новой
                квоты.
            files_limit: Лимит количества файлов для новой квоты.
            public_links_limit: Лимит количества публичных ссылок для новой квоты.
            active_upload_sessions_limit: Лимит активных upload-сессий для новой
                квоты.

        Returns:
            Существующая или созданная стандартная квота пользователя.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        existing = await self.get_quota_or_none(user_id)
        if existing is not None:
            return existing
        return await self.create_default_quota(
            user_id,
            actor_id=actor_id,
            storage_limit_bytes=storage_limit_bytes,
            max_file_size_bytes=max_file_size_bytes,
            files_limit=files_limit,
            public_links_limit=public_links_limit,
            active_upload_sessions_limit=active_upload_sessions_limit,
        )

    async def get_quota(self, user_id: UUID) -> UserQuotaRead:
        """Возвращает квоту пользователя.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Данные квоты пользователя.

        Raises:
            ServiceError: Если квота не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "get_quota"
        result: UserQuotaRead | None = None
        try:
            async with self.uow_factory() as uow:
                quota = await uow.quotas.get_required_by_user_id(user_id)
                result = _quota_read(_quota_snapshot(quota))
            return self._require_result(result, operation=operation)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Квота пользователя не найдена."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении квоты пользователя.",
            ) from exc

    async def get_quota_or_none(self, user_id: UUID) -> UserQuotaRead | None:
        """Возвращает квоту пользователя или None.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Данные квоты пользователя или None, если квота отсутствует.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "get_quota_or_none"
        try:
            async with self.uow_factory() as uow:
                quota = await uow.quotas.get_by_user_id(user_id)
                if quota is None:
                    return None
                return _quota_read(_quota_snapshot(quota))

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить квоту пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении квоты пользователя.",
            ) from exc

    async def get_usage(self, user_id: UUID) -> QuotaUsageRead:
        """Возвращает текущее использование квоты пользователя.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Данные использования ресурсов пользователя.

        Raises:
            ServiceError: Если квота не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "get_usage"
        result: QuotaUsageRead | None = None
        try:
            async with self.uow_factory() as uow:
                quota = await uow.quotas.get_required_by_user_id(user_id)
                result = _usage_read(_quota_snapshot(quota))
            return self._require_result(result, operation=operation)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить использование квоты.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении использования квоты.",
            ) from exc

    async def update_quota(
        self,
        user_id: UUID,
        data: UserQuotaUpdate,
        *,
        actor_id: UUID | None = None,
    ) -> UserQuotaRead:
        """Обновляет лимиты и счетчики квоты пользователя.

        Обновляет только явно переданные поля. Лимиты обновляются отдельно от
        счетчиков использования. Если данные обновления пустые, возвращает текущую
        квоту без изменений. После успешного обновления записывает событие аудита.

        Args:
            user_id: Идентификатор пользователя, чья квота обновляется.
            data: Данные обновления квоты.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие аудита записывается как системное.

        Returns:
            Обновленная квота пользователя.

        Raises:
            ServiceError: Если квота не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "update_quota"
        values = data.model_dump(exclude_unset=True)
        if not values:
            return await self.get_quota(user_id)

        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                # Контроль переподписки нужен только при повышении лимита
                # хранилища. Advisory-блокировку берём ДО чтения прежнего лимита
                # и ДО строкового for_update-чтения квоты, чтобы и прежний лимит,
                # и сумма читались согласованно, и не было дедлоков.
                if values.get("storage_limit_bytes") is not None:
                    await uow.quotas.acquire_capacity_lock()
                    current = await uow.quotas.get_required_by_user_id(user_id)
                    await enforce_server_capacity(
                        uow=uow,
                        capacity_provider=self.capacity_provider,
                        user_id=user_id,
                        new_limit=values["storage_limit_bytes"],
                        previous_limit=current.storage_limit_bytes,
                    )

                quota = await uow.quotas.get_required_by_user_id(
                    user_id, for_update=True
                )

                limit_kwargs: dict[str, Any] = {}
                for field_name in (
                    "storage_limit_bytes",
                    "max_file_size_bytes",
                    "files_limit",
                    "public_links_limit",
                    "active_upload_sessions_limit",
                ):
                    if field_name in values:
                        limit_kwargs[field_name] = values[field_name]

                if limit_kwargs:
                    quota = await uow.quotas.update_limits(
                        user_id,
                        **limit_kwargs,
                        flush=True,
                        refresh=False,
                        for_update=False,
                    )

                if (
                    "storage_used_bytes" in values
                    and values["storage_used_bytes"] is not None
                ):
                    quota = await uow.quotas.update_storage_used(
                        user_id,
                        storage_used_bytes=values["storage_used_bytes"],
                        flush=True,
                        refresh=False,
                        for_update=False,
                    )
                if "files_used" in values and values["files_used"] is not None:
                    quota = await uow.quotas.set_files_used(
                        user_id,
                        count=values["files_used"],
                        flush=True,
                        refresh=False,
                        for_update=False,
                    )
                if (
                    "public_links_used" in values
                    and values["public_links_used"] is not None
                ):
                    quota = await uow.quotas.set_public_links_used(
                        user_id,
                        count=values["public_links_used"],
                        flush=True,
                        refresh=False,
                        for_update=False,
                    )
                if (
                    "active_upload_sessions_used" in values
                    and values["active_upload_sessions_used"] is not None
                ):
                    quota = await uow.quotas.set_active_upload_sessions_used(
                        user_id,
                        count=values["active_upload_sessions_used"],
                        flush=True,
                        refresh=False,
                        for_update=False,
                    )

                quota = await uow.flush_and_refresh(quota)
                snapshot = _quota_snapshot(quota)
                await uow.commit()

            await self._safe_log_quota_event(
                actor_id=actor_id,
                user_id=user_id,
                action=AuditAction.QUOTA_UPDATED,
                entity_id=snapshot["id"],
                message="Пользовательская квота была обновлена.",
                metadata={
                    "operation": operation,
                    "updated_fields": sorted(values),
                    "quota": _audit_quota(snapshot),
                },
            )
            return _quota_read(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось обновить квоту пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при обновлении квоты пользователя.",
            ) from exc

    async def get_server_capacity(self) -> ServerCapacityRead:
        """Возвращает состояние общей ёмкости хранилища сервера.

        Собирает снимок пула (из конфига или MinIO) и суммарно выделенный объём
        по всем активным пользователям, чтобы администратор видел распределение
        места и факт переподписки.

        Returns:
            Состояние ёмкости хранилища сервера.

        Raises:
            ServiceError: Если ёмкость нельзя определить, произошла ошибка базы
                данных или непредвиденная ошибка сервиса.
        """

        operation = "get_server_capacity"
        try:
            status = await self.capacity_provider.resolve()
            async with self.uow_factory() as uow:
                allocated = await uow.quotas.total_allocated_storage_bytes()
            available = max(status.pool_bytes - allocated, 0)
            return ServerCapacityRead(
                pool_bytes=status.pool_bytes,
                allocated_bytes=allocated,
                available_bytes=available,
                physical_total_bytes=status.physical_total_bytes,
                physical_available_bytes=status.physical_available_bytes,
                source=status.source,
                is_overcommitted=allocated > status.pool_bytes,
                minio_reachable=status.minio_reachable,
            )

        except StorageCapacityError as exc:
            raise InsufficientServerCapacityError(
                "Невозможно определить ёмкость хранилища сервера.",
                cause=exc,
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить состояние ёмкости хранилища.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении ёмкости хранилища.",
            ) from exc

    async def check_quota(self, data: QuotaCheckRequest) -> QuotaCheckResponse:
        """Проверяет, помещается ли запрошенный ресурс в текущую квоту.

        Загружает квоту пользователя и сравнивает requested_amount с доступным
        остатком по указанному типу ресурса.

        Args:
            data: Данные проверки квоты.

        Returns:
            Результат проверки с признаком allowed, лимитом, текущим использованием,
            доступным остатком и причиной отказа.

        Raises:
            ValidationServiceError: Если тип ресурса квоты не поддерживается.
            ServiceError: Если квота не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "check_quota"
        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                quota = await uow.quotas.get_required_by_user_id(data.user_id)
                snapshot = _quota_snapshot(quota)
            return _check_response(snapshot, data.resource_type, data.requested_amount)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось проверить квоту пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при проверке квоты пользователя.",
            ) from exc

    async def require_quota(
        self,
        data: QuotaCheckRequest,
        *,
        actor_id: UUID | None = None,
    ) -> QuotaCheckResponse:
        """Проверяет квоту и выбрасывает ошибку при отказе.

        Если квота позволяет операцию, возвращает результат проверки. Если лимит
        превышен, записывает событие аудита и выбрасывает QuotaExceededServiceError.

        Args:
            data: Данные проверки квоты.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие аудита записывается как системное.

        Returns:
            Успешный результат проверки квоты.

        Raises:
            QuotaExceededServiceError: Если запрошенный ресурс превышает доступную
                квоту.
            ValidationServiceError: Если тип ресурса квоты не поддерживается.
            ServiceError: Если квота не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        response = await self.check_quota(data)
        if response.allowed:
            return response

        await self._safe_log_quota_event(
            actor_id=actor_id,
            user_id=data.user_id,
            action=AuditAction.QUOTA_EXCEEDED,
            entity_id=None,
            message="Превышена пользовательская квота.",
            metadata={
                "operation": "require_quota",
                "check": response.model_dump(mode="json"),
            },
        )
        raise QuotaExceededServiceError(
            response.reason,
            user_id=data.user_id,
            resource_type=response.resource_type.value,
            requested=response.requested_amount,
            used=response.used,
            limit=response.limit,
            available=response.available,
            details={"service": SERVICE_NAME, "operation": "require_quota"},
        )

    async def increase_usage(
        self,
        user_id: UUID,
        resource_type: QuotaResourceType,
        amount: int = 1,
        *,
        actor_id: UUID | None = None,
        check_limit: bool = True,
    ) -> UserQuotaRead:
        """Атомарно увеличивает счетчик использования ресурса.

        При check_limit=True сначала проверяет, что увеличение не превысит лимит.
        Затем увеличивает соответствующий счетчик квоты и возвращает обновленную
        квоту.

        Args:
            user_id: Идентификатор пользователя.
            resource_type: Тип ресурса квоты.
            amount: Количество ресурса, на которое нужно увеличить счетчик.
            actor_id: Идентификатор пользователя, выполняющего операцию. Используется
                для аудита при превышении квоты.
            check_limit: Нужно ли проверять лимит перед увеличением.

        Returns:
            Обновленная квота пользователя.

        Raises:
            ValidationServiceError: Если amount некорректен или тип ресурса не
                поддерживается.
            QuotaExceededServiceError: Если check_limit=True и лимит будет превышен.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "increase_usage"
        self._validate_amount(amount, operation=operation)

        if check_limit:
            await self.require_quota(
                QuotaCheckRequest(
                    user_id=user_id,
                    resource_type=resource_type,
                    requested_amount=amount,
                ),
                actor_id=actor_id,
            )

        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                quota = await self._increase_counter(
                    uow=uow,
                    user_id=user_id,
                    resource_type=resource_type,
                    amount=amount,
                )
                quota = await uow.flush_and_refresh(quota)
                snapshot = _quota_snapshot(quota)
                await uow.commit()

            return _quota_read(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось увеличить использование квоты.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при увеличении использования квоты.",
            ) from exc

    async def decrease_usage(
        self,
        user_id: UUID,
        resource_type: QuotaResourceType,
        amount: int = 1,
    ) -> UserQuotaRead:
        """Атомарно уменьшает счетчик использования ресурса.

        Уменьшает соответствующий счетчик квоты без ухода ниже нуля. Точное
        поведение ограничения до нуля реализуется репозиторием квот.

        Args:
            user_id: Идентификатор пользователя.
            resource_type: Тип ресурса квоты.
            amount: Количество ресурса, на которое нужно уменьшить счетчик.

        Returns:
            Обновленная квота пользователя.

        Raises:
            ValidationServiceError: Если amount некорректен или тип ресурса не
                поддерживается.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "decrease_usage"
        self._validate_amount(amount, operation=operation)
        snapshot: dict[str, Any] = {}

        try:
            async with self.uow_factory() as uow:
                quota = await self._decrease_counter(
                    uow=uow,
                    user_id=user_id,
                    resource_type=resource_type,
                    amount=amount,
                )
                quota = await uow.flush_and_refresh(quota)
                snapshot = _quota_snapshot(quota)
                await uow.commit()

            return _quota_read(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось уменьшить использование квоты.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при уменьшении использования квоты.",
            ) from exc

    async def can_store_file(self, user_id: UUID, file_size_bytes: int) -> bool:
        """Проверяет, можно ли сохранить файл заданного размера.

        Проверяет размер файла на корректность и делегирует расчет репозиторию квот.

        Args:
            user_id: Идентификатор пользователя.
            file_size_bytes: Размер файла в байтах.

        Returns:
            True, если файл можно сохранить в рамках квоты, иначе False.

        Raises:
            ValidationServiceError: Если размер файла некорректен.
            ServiceError: Если репозиторий не вернул результат, произошла ошибка
                базы данных или непредвиденная ошибка сервиса.
        """

        operation = "can_store_file"
        self._validate_amount(file_size_bytes, operation=operation, allow_zero=True)
        result: bool | None = None
        try:
            async with self.uow_factory() as uow:
                result = await uow.quotas.can_store_file(
                    user_id,
                    file_size_bytes=file_size_bytes,
                )
            if result is None:
                raise ServiceError(
                    "Сервис квот не вернул результат проверки загрузки файла.",
                    service=SERVICE_NAME,
                    operation=operation,
                )
            return result

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось проверить возможность загрузки файла.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при проверке загрузки файла.",
            ) from exc

    async def require_file_can_be_stored(
        self,
        user_id: UUID,
        file_size_bytes: int,
        *,
        actor_id: UUID | None = None,
    ) -> None:
        """Проверяет возможность сохранить файл и выбрасывает ошибку при отказе.

        Если файл можно сохранить, метод завершается без результата. Если лимиты
        превышены, выполняет подробную проверку квоты, записывает событие аудита
        и выбрасывает QuotaExceededServiceError.

        Args:
            user_id: Идентификатор пользователя.
            file_size_bytes: Размер файла в байтах.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие аудита записывается как системное.

        Raises:
            ValidationServiceError: Если размер файла некорректен.
            QuotaExceededServiceError: Если файл нельзя сохранить из-за лимитов.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        allowed = await self.can_store_file(user_id, file_size_bytes)
        if allowed:
            return

        check = await self.check_quota(
            QuotaCheckRequest(
                user_id=user_id,
                resource_type=QuotaResourceType.STORAGE_BYTES,
                requested_amount=file_size_bytes,
            )
        )
        await self._safe_log_quota_event(
            actor_id=actor_id,
            user_id=user_id,
            action=AuditAction.QUOTA_EXCEEDED,
            entity_id=None,
            message="Файл не может быть сохранен, поскольку были превышены лимиты квоты.",
            metadata={
                "operation": "require_file_can_be_stored",
                "check": check.model_dump(mode="json"),
            },
        )
        raise QuotaExceededServiceError(
            check.reason or "Файл превышает доступные лимиты пользователя.",
            user_id=user_id,
            resource_type=QuotaResourceType.STORAGE_BYTES.value,
            requested=file_size_bytes,
            used=check.used,
            limit=check.limit,
            available=check.available,
            details={
                "service": SERVICE_NAME,
                "operation": "require_file_can_be_stored",
            },
        )

    async def recalculate_quota(
        self,
        data: QuotaRecalculateRequest,
        *,
        actor_id: UUID | None = None,
    ) -> UserQuotaRead:
        """Пересчитывает счетчики квоты по данным базы.

        В зависимости от списка resource_types пересчитывает все счетчики, только
        использование хранилища, только счетчики количества ресурсов или обе группы
        по отдельности. После пересчета записывает событие аудита.

        Args:
            data: Данные запроса на пересчет квоты.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие аудита записывается как системное.

        Returns:
            Пересчитанная квота пользователя.

        Raises:
            ValidationServiceError: Если тип ресурса квоты не поддерживается.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "recalculate_quota"
        resource_types = set(data.resource_types or list(QuotaResourceType))
        snapshot: dict[str, Any] = {}

        try:
            async with self.uow_factory() as uow:
                if resource_types == set(QuotaResourceType):
                    quota = await uow.quotas.recalculate_all(data.user_id)
                elif resource_types == {QuotaResourceType.STORAGE_BYTES}:
                    quota = await uow.quotas.recalculate_usage(data.user_id)
                elif resource_types.isdisjoint({QuotaResourceType.STORAGE_BYTES}):
                    quota = await uow.quotas.recalculate_counters(data.user_id)
                else:
                    quota = await uow.quotas.recalculate_usage(data.user_id)
                    quota = await uow.quotas.recalculate_counters(
                        data.user_id,
                        for_update=False,
                    )

                quota = await uow.flush_and_refresh(quota)
                snapshot = _quota_snapshot(quota)
                await uow.commit()

            await self._safe_log_quota_event(
                actor_id=actor_id,
                user_id=data.user_id,
                action=AuditAction.QUOTA_RECALCULATED,
                entity_id=snapshot["id"],
                message="Пользовательская квота была пересчитана.",
                metadata={
                    "operation": operation,
                    "resource_types": [
                        resource_type.value for resource_type in resource_types
                    ],
                    "force": data.force,
                    "quota": _audit_quota(snapshot),
                },
            )
            return _quota_read(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось пересчитать квоту пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при пересчете квоты пользователя.",
            ) from exc

    async def list_near_limit(
        self,
        *,
        threshold_percent: float = 90.0,
        offset: int = 0,
        limit: int = 100,
    ) -> PageResponse[UserQuotaRead]:
        """Возвращает квоты, близкие к лимиту.

        Загружает все квоты, использование которых достигло заданного процента
        лимита, затем формирует страницу результата.

        Args:
            threshold_percent: Порог использования квоты в процентах.
            offset: Смещение для постраничной выдачи.
            limit: Максимальное количество элементов в ответе.

        Returns:
            Страница квот, близких к лимиту.

        Raises:
            ValidationServiceError: Если offset или limit некорректны.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_near_limit"
        self._validate_pagination(offset=offset, limit=limit)
        snapshots: list[dict[str, Any]] = []

        try:
            async with self.uow_factory() as uow:
                snapshots = await self._collect_near_limit_snapshots(
                    uow=uow,
                    threshold_percent=threshold_percent,
                )

            total = len(snapshots)
            page = snapshots[offset : offset + limit]
            return PageResponse[UserQuotaRead](
                items=[_quota_read(snapshot) for snapshot in page],
                meta=PageMeta(limit=limit, offset=offset, total=total, count=len(page)),
            )

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить квоты, близкие к лимиту.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении квот, близких к лимиту.",
            ) from exc

    async def list_over_limit(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> PageResponse[UserQuotaRead]:
        """Возвращает квоты с превышением лимита.

        Загружает все квоты, которые превысили хотя бы один лимит, затем формирует
        страницу результата.

        Args:
            offset: Смещение для постраничной выдачи.
            limit: Максимальное количество элементов в ответе.

        Returns:
            Страница квот с превышением лимита.

        Raises:
            ValidationServiceError: Если offset или limit некорректны.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_over_limit"
        self._validate_pagination(offset=offset, limit=limit)
        snapshots: list[dict[str, Any]] = []

        try:
            async with self.uow_factory() as uow:
                snapshots = await self._collect_over_limit_snapshots(uow=uow)

            total = len(snapshots)
            page = snapshots[offset : offset + limit]
            return PageResponse[UserQuotaRead](
                items=[_quota_read(snapshot) for snapshot in page],
                meta=PageMeta(limit=limit, offset=offset, total=total, count=len(page)),
            )

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить квоты с превышением лимита.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении квот с превышением лимита.",
            ) from exc

    async def _increase_counter(
        self,
        *,
        uow: Any,
        user_id: UUID,
        resource_type: QuotaResourceType,
        amount: int,
    ) -> UserQuota:
        """Увеличивает счетчик указанного ресурса.

        Выбирает метод репозитория квот по resource_type и увеличивает
        соответствующий счетчик.

        Args:
            uow: Unit of Work с репозиторием квот.
            user_id: Идентификатор пользователя.
            resource_type: Тип ресурса квоты.
            amount: Количество ресурса для увеличения.

        Returns:
            ORM-модель обновленной квоты.

        Raises:
            ValidationServiceError: Если тип ресурса не поддерживается.
        """

        if resource_type == QuotaResourceType.STORAGE_BYTES:
            return await uow.quotas.increase_used_space(
                user_id,
                size_bytes=amount,
                flush=True,
                refresh=False,
            )
        if resource_type == QuotaResourceType.FILE_COUNT:
            return await uow.quotas.increase_files_used(
                user_id,
                count=amount,
                flush=True,
                refresh=False,
            )
        if resource_type == QuotaResourceType.PUBLIC_LINK_COUNT:
            return await uow.quotas.increase_public_links_used(
                user_id,
                count=amount,
                flush=True,
                refresh=False,
            )
        if resource_type == QuotaResourceType.UPLOAD_SESSION_COUNT:
            return await uow.quotas.increase_active_upload_sessions_used(
                user_id,
                count=amount,
                flush=True,
                refresh=False,
            )
        raise self._invalid_resource_type(resource_type)

    async def _decrease_counter(
        self,
        *,
        uow: Any,
        user_id: UUID,
        resource_type: QuotaResourceType,
        amount: int,
    ) -> UserQuota:
        """Уменьшает счетчик указанного ресурса.

        Выбирает метод репозитория квот по resource_type и уменьшает
        соответствующий счетчик.

        Args:
            uow: Unit of Work с репозиторием квот.
            user_id: Идентификатор пользователя.
            resource_type: Тип ресурса квоты.
            amount: Количество ресурса для уменьшения.

        Returns:
            ORM-модель обновленной квоты.

        Raises:
            ValidationServiceError: Если тип ресурса не поддерживается.
        """

        if resource_type == QuotaResourceType.STORAGE_BYTES:
            return await uow.quotas.decrease_used_space(
                user_id,
                size_bytes=amount,
                flush=True,
                refresh=False,
            )
        if resource_type == QuotaResourceType.FILE_COUNT:
            return await uow.quotas.decrease_files_used(
                user_id,
                count=amount,
                flush=True,
                refresh=False,
            )
        if resource_type == QuotaResourceType.PUBLIC_LINK_COUNT:
            return await uow.quotas.decrease_public_links_used(
                user_id,
                count=amount,
                flush=True,
                refresh=False,
            )
        if resource_type == QuotaResourceType.UPLOAD_SESSION_COUNT:
            return await uow.quotas.decrease_active_upload_sessions_used(
                user_id,
                count=amount,
                flush=True,
                refresh=False,
            )
        raise self._invalid_resource_type(resource_type)

    async def _collect_near_limit_snapshots(
        self, *, uow: Any, threshold_percent: float
    ) -> list[dict[str, Any]]:
        """Загружает снимки квот, близких к лимиту.

        Читает данные батчами до тех пор, пока очередной батч не станет меньше
        REPOSITORY_PAGE_LIMIT.

        Args:
            uow: Unit of Work с репозиторием квот.
            threshold_percent: Порог использования квоты в процентах.

        Returns:
            Список снимков квот, близких к лимиту.
        """

        snapshots: list[dict[str, Any]] = []
        offset = 0
        while True:
            quotas = await uow.quotas.list_near_limit(
                threshold_percent=threshold_percent,
                offset=offset,
                limit=REPOSITORY_PAGE_LIMIT,
            )
            snapshots.extend(_quota_snapshot(quota) for quota in quotas)
            if len(quotas) < REPOSITORY_PAGE_LIMIT:
                break
            offset += REPOSITORY_PAGE_LIMIT
        return snapshots

    async def _collect_over_limit_snapshots(self, *, uow: Any) -> list[dict[str, Any]]:
        """Загружает снимки квот с превышением лимита.

        Читает данные батчами до тех пор, пока очередной батч не станет меньше
        REPOSITORY_PAGE_LIMIT.

        Args:
            uow: Unit of Work с репозиторием квот.

        Returns:
            Список снимков квот с превышением лимита.
        """

        snapshots: list[dict[str, Any]] = []
        offset = 0
        while True:
            quotas = await uow.quotas.list_over_limit(
                offset=offset,
                limit=REPOSITORY_PAGE_LIMIT,
            )
            snapshots.extend(_quota_snapshot(quota) for quota in quotas)
            if len(quotas) < REPOSITORY_PAGE_LIMIT:
                break
            offset += REPOSITORY_PAGE_LIMIT
        return snapshots

    @staticmethod
    def _validate_amount(
        amount: int, *, operation: str, allow_zero: bool = False
    ) -> None:
        """Проверяет корректность количества ресурса.

        Значение должно быть int, но не bool. По умолчанию значение должно быть
        больше нуля. Если allow_zero=True, ноль считается допустимым.

        Args:
            amount: Проверяемое количество ресурса.
            operation: Название операции для контекста ошибок.
            allow_zero: Разрешен ли ноль.

        Raises:
            ValidationServiceError: Если amount имеет неверный тип или значение.
        """

        if not isinstance(amount, int) or isinstance(amount, bool):
            raise ValidationServiceError(
                "Количество ресурса должно быть целым числом.",
                field="amount",
                value=amount,
                reason="invalid_amount_type",
                details={"service": SERVICE_NAME, "operation": operation},
            )
        if amount < 0 or (amount == 0 and not allow_zero):
            raise ValidationServiceError(
                "Количество ресурса должно быть больше нуля.",
                field="amount",
                value=amount,
                reason="invalid_amount",
                details={"service": SERVICE_NAME, "operation": operation},
            )

    @staticmethod
    def _validate_pagination(*, offset: int, limit: int) -> None:
        """Проверяет параметры пагинации.

        Args:
            offset: Смещение страницы.
            limit: Размер страницы.

        Raises:
            ValidationServiceError: Если offset отрицательный или limit находится
                вне диапазона от 1 до MAX_PAGE_LIMIT.
        """

        if offset < 0:
            raise ValidationServiceError(
                "offset не может быть отрицательным.",
                field="offset",
                value=offset,
                reason="negative_offset",
                details={"service": SERVICE_NAME, "operation": "validate_pagination"},
            )
        if limit < 1 or limit > MAX_PAGE_LIMIT:
            raise ValidationServiceError(
                f"limit должен быть от 1 до {MAX_PAGE_LIMIT}.",
                field="limit",
                value=limit,
                reason="invalid_limit",
                details={"service": SERVICE_NAME, "operation": "validate_pagination"},
            )

    @staticmethod
    def _invalid_resource_type(resource_type: Any) -> ValidationServiceError:
        """Создает ошибку неподдерживаемого типа ресурса квоты.

        Args:
            resource_type: Значение типа ресурса.

        Returns:
            Ошибка валидации для неподдерживаемого типа ресурса.
        """

        return ValidationServiceError(
            "Тип ресурса квоты не поддерживается.",
            field="resource_type",
            value=str(resource_type),
            reason="invalid_resource_type",
            details={"service": SERVICE_NAME},
        )

    @staticmethod
    def _require_result(result: Any | None, *, operation: str) -> Any:
        """Возвращает результат или выбрасывает ошибку при его отсутствии.

        Args:
            result: Результат операции.
            operation: Название операции для контекста ошибки.

        Returns:
            Переданный результат, если он не None.

        Raises:
            ServiceError: Если result равен None.
        """

        if result is None:
            raise ServiceError(
                "Сервис квот не вернул результат операции.",
                service=SERVICE_NAME,
                operation=operation,
            )
        return result

    @staticmethod
    def _database_error(
        exc: DatabaseError, *, operation: str, message: str
    ) -> ServiceError:
        """Преобразует ошибку базы данных в ошибку сервиса квот.

        Args:
            exc: Исходная ошибка базы данных.
            operation: Название операции, во время которой возникла ошибка.
            message: Сообщение для создаваемой ошибки сервиса.

        Returns:
            Ошибка сервисного уровня с контекстом сервиса квот.
        """

        return service_error_from_database(
            exc, operation=operation, message=message, service=SERVICE_NAME
        )

    @staticmethod
    def _unexpected_error(
        exc: Exception, *, operation: str, message: str
    ) -> ServiceError:
        """Преобразует непредвиденное исключение в ошибку сервиса.

        Дополнительно пишет исключение в лог с названием операции и типом ошибки.

        Args:
            exc: Исходное исключение.
            operation: Название операции, во время которой возникла ошибка.
            message: Сообщение для лога и создаваемой ошибки сервиса.

        Returns:
            Ошибка сервисного уровня с контекстом исходного исключения.
        """

        logger.exception(
            message,
            extra={"operation": operation, "error_type": exc.__class__.__name__},
        )
        return service_error_from_exception(
            exc, operation=operation, message=message, service=SERVICE_NAME
        )

    async def _safe_log_quota_event(
        self,
        *,
        actor_id: UUID | None,
        user_id: UUID,
        action: AuditAction,
        entity_id: UUID | None,
        message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Безопасно записывает событие квоты в аудит.

        Если actor_id равен None, записывает системное событие. Иначе записывает
        пользовательское событие от имени actor_id. Ошибки аудита не пробрасываются
        выше.

        Args:
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие считается системным.
            user_id: Идентификатор пользователя, чья квота затронута.
            action: Действие аудита.
            entity_id: Идентификатор сущности квоты, если доступен.
            message: Сообщение события аудита.
            metadata: Дополнительные метаданные события.
        """

        try:
            if actor_id is None:
                await self.audit_service.log_system_event(
                    action=action,
                    entity_type=AuditResourceType.QUOTA.value,
                    entity_id=entity_id,
                    resource_type=AuditResourceType.QUOTA,
                    message=message,
                    metadata={"target_user_id": str(user_id), **dict(metadata or {})},
                )
                return
            await self.audit_service.log_user_event(
                user_id=actor_id,
                action=action,
                entity_type=AuditResourceType.QUOTA.value,
                entity_id=entity_id,
                resource_type=AuditResourceType.QUOTA,
                message=message,
                metadata={"target_user_id": str(user_id), **dict(metadata or {})},
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита для службы квот.",
                extra={
                    "action": action.value,
                    "entity_id": str(entity_id) if entity_id else None,
                    "actor_id": str(actor_id) if actor_id else None,
                    "target_user_id": str(user_id),
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )


def _quota_snapshot(quota: UserQuota) -> dict[str, Any]:
    """Создает снимок квоты пользователя.

    Рассчитывает доступный объем хранилища, процент использования и признак
    заполненности хранилища.

    Args:
        quota: ORM-модель квоты пользователя.

    Returns:
        Словарь с лимитами, счетчиками использования, расчетными полями и
        временными метками квоты.
    """

    storage_limit = int(quota.storage_limit_bytes)
    storage_used = int(quota.storage_used_bytes)
    available_storage = max(storage_limit - storage_used, 0)
    usage_percent = 100.0 if storage_limit <= 0 and storage_used > 0 else 0.0
    if storage_limit > 0:
        usage_percent = round(min((storage_used / storage_limit) * 100, 100.0), 2)

    return {
        "id": quota.id,
        "user_id": quota.user_id,
        "storage_limit_bytes": storage_limit,
        "storage_used_bytes": storage_used,
        "max_file_size_bytes": int(quota.max_file_size_bytes),
        "files_limit": quota.files_limit,
        "files_used": int(quota.files_used),
        "public_links_limit": quota.public_links_limit,
        "public_links_used": int(quota.public_links_used),
        "active_upload_sessions_limit": quota.active_upload_sessions_limit,
        "active_upload_sessions_used": int(quota.active_upload_sessions_used),
        "available_storage_bytes": available_storage,
        "usage_percent": usage_percent,
        "is_storage_full": storage_used >= storage_limit,
        "created_at": quota.created_at,
        "updated_at": quota.updated_at,
    }


def _quota_read(snapshot: Mapping[str, Any]) -> UserQuotaRead:
    """Преобразует снимок квоты в схему ответа.

    Args:
        snapshot: Снимок квоты пользователя.

    Returns:
        Схема чтения квоты пользователя.
    """

    return UserQuotaRead.model_validate(dict(snapshot))


def _usage_read(snapshot: Mapping[str, Any]) -> QuotaUsageRead:
    """Преобразует снимок квоты в схему использования ресурсов.

    Args:
        snapshot: Снимок квоты пользователя.

    Returns:
        Схема текущего использования ресурсов пользователя.
    """

    return QuotaUsageRead.model_validate(
        {
            "user_id": snapshot["user_id"],
            "storage_limit_bytes": snapshot["storage_limit_bytes"],
            "storage_used_bytes": snapshot["storage_used_bytes"],
            "max_file_size_bytes": snapshot["max_file_size_bytes"],
            "files_limit": snapshot["files_limit"],
            "files_used": snapshot["files_used"],
            "public_links_limit": snapshot["public_links_limit"],
            "public_links_used": snapshot["public_links_used"],
            "active_upload_sessions_limit": snapshot["active_upload_sessions_limit"],
            "active_upload_sessions_used": snapshot["active_upload_sessions_used"],
        }
    )


def _check_response(
    snapshot: Mapping[str, Any], resource_type: QuotaResourceType, requested_amount: int
) -> QuotaCheckResponse:
    """Формирует результат проверки квоты.

    Определяет лимит и текущее использование ресурса. Если лимит отсутствует,
    разрешает операцию. Если лимит задан, сравнивает requested_amount с
    доступным остатком.

    Args:
        snapshot: Снимок квоты пользователя.
        resource_type: Тип проверяемого ресурса.
        requested_amount: Запрошенный объем ресурса.

    Returns:
        Результат проверки квоты.

    Raises:
        ValidationServiceError: Если тип ресурса не поддерживается.
    """

    limit, used = _resource_limit_and_used(snapshot, resource_type)
    if limit is None:
        return QuotaCheckResponse(
            allowed=True,
            user_id=snapshot["user_id"],
            resource_type=resource_type,
            requested_amount=requested_amount,
            limit=None,
            used=used,
            available=None,
            reason=None,
        )

    available = max(limit - used, 0)
    allowed = requested_amount <= available
    return QuotaCheckResponse(
        allowed=allowed,
        user_id=snapshot["user_id"],
        resource_type=resource_type,
        requested_amount=requested_amount,
        limit=limit,
        used=used,
        available=available,
        reason=None
        if allowed
        else "Запрошенный объем ресурса превышает доступную квоту.",
    )


def _resource_limit_and_used(
    snapshot: Mapping[str, Any], resource_type: QuotaResourceType
) -> tuple[int | None, int]:
    """Возвращает лимит и текущее использование ресурса.

    Args:
        snapshot: Снимок квоты пользователя.
        resource_type: Тип ресурса квоты.

    Returns:
        Кортеж из лимита ресурса и текущего использования. Лимит может быть
        None, если ресурс не ограничен.

    Raises:
        ValidationServiceError: Если тип ресурса не поддерживается.
    """

    if resource_type == QuotaResourceType.STORAGE_BYTES:
        return int(snapshot["storage_limit_bytes"]), int(snapshot["storage_used_bytes"])
    if resource_type == QuotaResourceType.FILE_COUNT:
        return _optional_int(snapshot["files_limit"]), int(snapshot["files_used"])
    if resource_type == QuotaResourceType.PUBLIC_LINK_COUNT:
        return _optional_int(snapshot["public_links_limit"]), int(
            snapshot["public_links_used"]
        )
    if resource_type == QuotaResourceType.UPLOAD_SESSION_COUNT:
        return _optional_int(snapshot["active_upload_sessions_limit"]), int(
            snapshot["active_upload_sessions_used"]
        )
    raise ValidationServiceError(
        "Тип ресурса квоты не поддерживается.",
        field="resource_type",
        value=str(resource_type),
        reason="invalid_resource_type",
        details={"service": SERVICE_NAME},
    )


def _optional_int(value: Any) -> int | None:
    """Преобразует значение в int или None.

    Args:
        value: Значение для преобразования.

    Returns:
        None, если value равен None, иначе int(value).
    """

    return None if value is None else int(value)


def _audit_quota(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует метаданные квоты для аудита.

    Args:
        snapshot: Снимок квоты пользователя.

    Returns:
        Словарь с основными лимитами, счетчиками и расчетными полями квоты.
    """

    return {
        "id": str(snapshot["id"]),
        "user_id": str(snapshot["user_id"]),
        "storage_limit_bytes": snapshot["storage_limit_bytes"],
        "storage_used_bytes": snapshot["storage_used_bytes"],
        "usage_percent": snapshot["usage_percent"],
        "max_file_size_bytes": snapshot["max_file_size_bytes"],
        "files_limit": snapshot["files_limit"],
        "files_used": snapshot["files_used"],
        "public_links_limit": snapshot["public_links_limit"],
        "public_links_used": snapshot["public_links_used"],
        "active_upload_sessions_limit": snapshot["active_upload_sessions_limit"],
        "active_upload_sessions_used": snapshot["active_upload_sessions_used"],
    }


def get_quotas_service(
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    audit_service: AuditService | None = None,
    capacity_provider: CapacityProvider | None = None,
) -> QuotasService:
    """Создаёт экземпляр сервиса квот.

    Args:
        uow_factory: Фабрика UnitOfWork. Если не передана, сервис создаст
            стандартную фабрику самостоятельно.
        audit_service: Сервис аудита. Если не передан, будет создан стандартный
            сервис аудита.
        capacity_provider: Провайдер ёмкости хранилища. Если не передан,
            создаётся из настроек.

    Returns:
        Экземпляр `QuotasService`.
    """

    return QuotasService(
        uow_factory=uow_factory,
        audit_service=audit_service,
        capacity_provider=capacity_provider,
    )
