from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID

from core.config import Settings, get_settings
from core.logging import get_logger
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    AuditResult,
    NodeType,
    TrashItemStatus,
)
from database.models.filesystem import File, FileSystemNode, FileVersion, TrashItem
from schemas.common import PageMeta, PageResponse
from schemas.nodes import NodeListItem
from schemas.trash import (
    TrashCleanupRequest,
    TrashEmptyRequest,
    TrashItemListItem,
    TrashItemRead,
    TrashPurgeRequest,
    TrashPurgeResponse,
    TrashQueryParams,
    TrashRestoreRequest,
    TrashRestoreResponse,
)
from security.permissions import PermissionAction
from services.access import AccessService, get_access_service
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    NotFoundServiceError,
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
    service_error_from_storage,
)
from storage import StorageError, StorageService, get_storage_service

logger = get_logger("services.trash")

SERVICE_NAME = "trash"
ALLOWED_TRASH_SORT_FIELDS: set[str] = {
    "deleted_at",
    "expires_at",
    "original_path",
    "status",
    "purged_at",
    "restore_available",
}


@dataclass(frozen=True, slots=True)
class StorageObjectRef:
    """Ссылка на физический объект в хранилище.

    Используется при окончательном удалении файлов и версий файлов, чтобы
    удалить соответствующие объекты из storage backend.

    Attributes:
        bucket: Имя bucket, в котором расположен объект.
        object_key: Ключ объекта внутри bucket.
    """

    bucket: str
    object_key: str


@dataclass(frozen=True, slots=True)
class PurgePlan:
    """План окончательного удаления элемента корзины.

    Содержит информацию, собранную до удаления: идентификаторы, тип узла,
    владельца, суммарный размер файлов, количество файлов и список физических
    объектов хранилища, которые нужно удалить.

    Attributes:
        trash_item_id: Идентификатор элемента корзины.
        node_id: Идентификатор удаляемого узла файловой системы.
        owner_id: Идентификатор владельца узла.
        node_type: Тип удаляемого узла.
        total_size_bytes: Суммарный размер файлов, которые будут окончательно
            удалены.
        file_count: Количество файлов, которые будут окончательно удалены.
        storage_objects: Объекты хранилища, которые нужно удалить.
    """

    trash_item_id: UUID
    node_id: UUID
    owner_id: UUID
    node_type: NodeType
    total_size_bytes: int
    file_count: int
    storage_objects: tuple[StorageObjectRef, ...]


class TrashService:
    """Сервис бизнес-логики для операций с корзиной.

    Управляет перемещением узлов в корзину, восстановлением и окончательным
    удалением. Сервис проверяет права доступа, изменяет метаданные через
    Unit of Work, удаляет физические объекты из хранилища, обновляет счетчики
    квоты и записывает события аудита.

    Attributes:
        settings: Настройки приложения.
        uow_factory: Фабрика Unit of Work для работы с базой данных.
        storage_service: Сервис хранилища для удаления физических объектов.
        access_service: Сервис проверки доступа к узлам файловой системы.
        audit_service: Сервис записи событий аудита.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        uow_factory: UnitOfWorkFactory | None = None,
        storage_service: StorageService | None = None,
        access_service: AccessService | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        """Инициализирует сервис корзины.

        Если зависимости не переданы явно, создает их через стандартные фабрики
        и функции получения сервисов.

        Args:
            settings: Настройки приложения. Если None, используются стандартные
                настройки.
            uow_factory: Фабрика Unit of Work. Если None, создается стандартная
                фабрика.
            storage_service: Сервис хранилища. Если None, создается стандартный
                сервис хранилища.
            access_service: Сервис проверки доступа. Если None, создается
                стандартный сервис доступа.
            audit_service: Сервис аудита. Если None, создается стандартный сервис
                аудита.
        """

        self.settings = settings or get_settings()
        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.storage_service = storage_service or get_storage_service(
            settings=self.settings.storage
        )
        self.access_service = access_service or get_access_service(
            uow_factory=self.uow_factory
        )
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory
        )

    async def move_to_trash(
        self,
        *,
        node_id: UUID,
        actor_id: UUID,
        expires_at: datetime | None = None,
        restore_available: bool = True,
        recursive: bool = True,
    ) -> TrashItemRead:
        """Перемещает узел файловой системы в корзину.

        Проверяет право удаления, создает элемент корзины и мягко удаляет связанный
        узел. Для папок может рекурсивно пометить дочерние узлы удаленными.
        После успешной операции записывает событие аудита.

        Args:
            node_id: Идентификатор узла, который нужно переместить в корзину.
            actor_id: Идентификатор пользователя, выполняющего удаление.
            expires_at: Дата истечения периода хранения в корзине. Если None,
                срок не задается явно.
            restore_available: Можно ли восстановить элемент из корзины.
            recursive: Нужно ли рекурсивно мягко удалить дочерние узлы.

        Returns:
            Данные созданного элемента корзины.

        Raises:
            PermissionServiceError: Если у пользователя нет права удаления узла.
            ValidationServiceError: Если узел уже находится в корзине.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "move_to_trash"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.DELETE,
                    allow_deleted=False,
                    allow_public=False,
                    uow=uow,
                )
                if node.is_deleted:
                    raise ValidationServiceError(
                        "Узел уже находится в корзине.",
                        field="node_id",
                        value=node_id,
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                trash_item = await uow.trash.create_trash_item(
                    node_id=node.id,
                    deleted_by=actor_id,
                    owner_id=node.owner_id,
                    original_parent_id=node.parent_id,
                    original_path=node.path,
                    expires_at=expires_at,
                    restore_available=restore_available,
                    soft_delete_node=True,
                    recursive_soft_delete=recursive,
                    flush=True,
                    refresh=True,
                )
                snapshot = _trash_item_snapshot(trash_item)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_trash_event(
                actor_id=actor_id,
                action=_deleted_action_from_node_snapshot(snapshot),
                resource_type=_resource_type_from_node_snapshot(snapshot),
                entity_id=node_id,
                message="Узел был перемещён в корзину.",
                metadata=_audit_trash(snapshot),
            )
            return TrashItemRead.model_validate(snapshot)

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def get_trash_item(
        self,
        trash_item_id: UUID,
        *,
        actor_id: UUID,
    ) -> TrashItemRead:
        """Возвращает элемент корзины по идентификатору.

        Загружает элемент корзины и проверяет право чтения к связанному удаленному
        узлу.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            actor_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Данные найденного элемента корзины.

        Raises:
            NotFoundServiceError: Если элемент корзины не найден.
            PermissionServiceError: Если у пользователя нет права чтения связанного
                узла.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "get_trash_item"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                trash_item = await uow.trash.get_by_id(trash_item_id)
                if trash_item is None:
                    raise NotFoundServiceError(
                        entity_name="TrashItem",
                        entity_id=trash_item_id,
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                await self.access_service.require_access(
                    node_id=trash_item.node_id,
                    user_id=actor_id,
                    action=PermissionAction.READ,
                    allow_deleted=True,
                    allow_public=False,
                    uow=uow,
                )
                snapshot = _trash_item_snapshot(trash_item)

            if snapshot is None:
                raise _empty_result_error(operation)
            return TrashItemRead.model_validate(snapshot)

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def list_trash(
        self,
        params: TrashQueryParams,
        *,
        actor_id: UUID,
    ) -> PageResponse[TrashItemListItem]:
        """Возвращает список элементов корзины.

        Обычный пользователь может просматривать только собственную корзину. Метод
        применяет фильтры по статусу, доступности восстановления, датам удаления,
        сроку хранения и поисковому запросу, а также сортирует результат.

        Args:
            params: Параметры фильтрации, сортировки и пагинации корзины.
            actor_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Страница элементов корзины и метаданные пагинации.

        Raises:
            PermissionServiceError: Если пользователь пытается просмотреть корзину
                другого владельца.
            ValidationServiceError: Если поле сортировки не поддерживается.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_trash"
        owner_id = params.owner_id or actor_id
        if owner_id != actor_id:
            raise PermissionServiceError(
                "Только администратор может просматривать корзину другого пользователя.",
                user_id=actor_id,
                resource_type="trash",
                resource_id=owner_id,
                action="list",
                details={"service": SERVICE_NAME, "operation": operation},
            )

        try:
            sort_by = _validate_sort_field(params.sort_by)
            total = 0
            snapshots: list[dict[str, Any]] = []
            async with self.uow_factory() as uow:
                total = await uow.trash.count_user_trash_filtered(
                    owner_id=owner_id,
                    include_purged=False,
                    status=params.status,
                    restore_available=params.restore_available,
                    deleted_from=params.deleted_from,
                    deleted_to=params.deleted_to,
                    expires_before=params.expires_before,
                    query=params.query,
                )
                items = await uow.trash.search_user_trash(
                    owner_id=owner_id,
                    include_purged=False,
                    status=params.status,
                    restore_available=params.restore_available,
                    deleted_from=params.deleted_from,
                    deleted_to=params.deleted_to,
                    expires_before=params.expires_before,
                    query=params.query,
                    sort_by=cast(Any, sort_by),
                    sort_direction="desc" if params.sort_desc else "asc",
                    offset=params.offset,
                    limit=params.limit,
                )
                snapshots = [_trash_item_snapshot(item) for item in items]

            dto_items = [
                TrashItemListItem.model_validate(snapshot) for snapshot in snapshots
            ]
            return PageResponse(
                items=dto_items,
                meta=PageMeta(
                    limit=params.limit,
                    offset=params.offset,
                    total=total,
                    count=len(dto_items),
                ),
            )

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def restore(
        self,
        data: TrashRestoreRequest,
        *,
        actor_id: UUID,
    ) -> TrashRestoreResponse:
        """Восстанавливает узел из корзины.

        Находит элемент корзины по trash_item_id или node_id, проверяет возможность
        восстановления, право RESTORE и, если указан новый родитель, право WRITE
        к целевой папке. Затем восстанавливает узел и записывает событие аудита.

        Args:
            data: Данные восстановления элемента корзины.
            actor_id: Идентификатор пользователя, выполняющего восстановление.

        Returns:
            Ответ восстановления с элементом корзины и восстановленным узлом.

        Raises:
            NotFoundServiceError: Если элемент корзины не найден.
            PermissionServiceError: Если у пользователя нет права восстановления
                или записи в целевого родителя.
            ValidationServiceError: Если элемент нельзя восстановить.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "restore"
        trash_snapshot: dict[str, Any] | None = None
        node_snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                trash_item = await _get_trash_item_for_request(
                    uow=uow,
                    trash_item_id=data.trash_item_id,
                    node_id=data.node_id,
                )
                _ensure_restorable(trash_item)

                await self.access_service.require_access(
                    node_id=trash_item.node_id,
                    user_id=actor_id,
                    action=PermissionAction.RESTORE,
                    allow_deleted=True,
                    allow_public=False,
                    uow=uow,
                )

                if data.target_parent_id is not None:
                    await self.access_service.require_access(
                        node_id=data.target_parent_id,
                        user_id=actor_id,
                        action=PermissionAction.WRITE,
                        allow_deleted=False,
                        allow_public=False,
                        uow=uow,
                    )
                    await uow.nodes.move_node(
                        node_id=trash_item.node_id,
                        new_parent_id=data.target_parent_id,
                        updated_by=actor_id,
                        flush=True,
                        refresh=False,
                    )

                await uow.trash.mark_restored(
                    trash_item_id=trash_item.id,
                    restored_by=actor_id,
                    restore_node=True,
                    recursive=True,
                    flush=True,
                    refresh=False,
                )
                # Повторите выборку после сброса, чтобы получить новый updated_at (на стороне сервера
                # onupdate) и убедиться, что .node доступен для моментального снимка
                restored = await uow.trash.get_by_id(trash_item.id)
                if restored is None:
                    raise _empty_result_error(operation)
                trash_snapshot = _trash_item_snapshot(restored)
                node_snapshot = _node_snapshot(restored.node)
                await uow.commit()

            if trash_snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_trash_event(
                actor_id=actor_id,
                action=_restored_action_from_node_snapshot(trash_snapshot),
                resource_type=_resource_type_from_node_snapshot(trash_snapshot),
                entity_id=trash_snapshot["node_id"],
                message="Узел был восстановлен из корзины.",
                metadata=_audit_trash(trash_snapshot),
            )
            return TrashRestoreResponse(
                success=True,
                trash_item=TrashItemRead.model_validate(trash_snapshot),
                node=(
                    None
                    if node_snapshot is None
                    else NodeListItem.model_validate(node_snapshot)
                ),
            )

        except ServiceError:
            raise
        except DatabaseError as exc:
            logger.exception("restore failed", extra={"operation": operation})
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            logger.exception("restore failed", extra={"operation": operation})
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def purge(
        self,
        data: TrashPurgeRequest,
        *,
        actor_id: UUID,
    ) -> TrashPurgeResponse:
        """Окончательно удаляет выбранные элементы корзины.

        Разрешает идентификаторы элементов корзины и узлов, затем по одному удаляет
        каждый элемент. Ошибка удаления одного элемента не прерывает обработку
        остальных: такие элементы попадают в failed_trash_item_ids.

        Args:
            data: Данные запроса на окончательное удаление.
            actor_id: Идентификатор пользователя, выполняющего purge.

        Returns:
            Сводный результат purge с количеством запрошенных, удаленных и
            ошибочных элементов.

        Raises:
            NotFoundServiceError: Если по переданному node_id не найден активный
                элемент корзины на этапе разрешения идентификаторов.
        """

        trash_item_ids = await self._resolve_purge_ids(data)
        purged_ids: list[UUID] = []
        failed_ids: list[UUID] = []

        for trash_item_id in trash_item_ids:
            try:
                await self._purge_one(trash_item_id, actor_id=actor_id)
                purged_ids.append(trash_item_id)
            except ServiceError:
                failed_ids.append(trash_item_id)
                logger.exception(
                    "Не удалось удалить элемент из корзины",
                    extra={"trash_item_id": str(trash_item_id)},
                )

        return TrashPurgeResponse(
            success=not failed_ids,
            requested_count=len(trash_item_ids),
            purged_count=len(purged_ids),
            failed_count=len(failed_ids),
            purged_trash_item_ids=purged_ids,
            failed_trash_item_ids=failed_ids,
            message=(
                "Окончательное удаление из корзины завершено."
                if not failed_ids
                else "Окончательное удаление из корзины завершено с ошибками."
            ),
        )

    async def empty_trash(
        self,
        data: TrashEmptyRequest,
        *,
        actor_id: UUID,
    ) -> TrashPurgeResponse:
        """Очищает корзину пользователя.

        Находит активные элементы корзины владельца и окончательно удаляет их.
        Обычный пользователь может очищать только собственную корзину.

        Args:
            data: Данные запроса очистки корзины.
            actor_id: Идентификатор пользователя, выполняющего очистку.

        Returns:
            Сводный результат очистки корзины.

        Raises:
            PermissionServiceError: Если пользователь пытается очистить корзину
                другого владельца.
            ServiceError: Если поиск кандидатов или purge завершились ошибкой.
        """

        operation = "empty_trash"
        owner_id = data.owner_id or actor_id
        if owner_id != actor_id:
            raise PermissionServiceError(
                "Только администратор может очищать корзину другого пользователя.",
                user_id=actor_id,
                resource_type="trash",
                resource_id=owner_id,
                action="empty",
                details={"service": SERVICE_NAME, "operation": operation},
            )

        if data.only_expired:
            trash_item_ids = await self._find_purge_candidates(
                owner_id=owner_id,
                only_expired=True,
            )
        else:
            trash_item_ids = await self._find_all_active(owner_id=owner_id)

        if not trash_item_ids:
            return _purge_response(
                requested_count=0,
                purged_ids=[],
                failed_ids=[],
                message="Корзина уже пуста.",
            )
        return await self.purge(
            TrashPurgeRequest(trash_item_ids=trash_item_ids, reason=data.reason),
            actor_id=actor_id,
        )

    async def _find_all_active(self, *, owner_id: UUID) -> list[UUID]:
        """Возвращает идентификаторы всех активных элементов корзины пользователя.

        Пагинирует по batch=1000, чтобы не превышать MAX_LIMIT репозитория.

        Args:
            owner_id: Идентификатор владельца корзины.

        Returns:
            Список идентификаторов элементов корзины.
        """

        _BATCH = 1000
        candidate_ids: list[UUID] = []
        offset = 0

        while True:
            async with self.uow_factory() as uow:
                items = await uow.trash.get_user_active_trash(
                    owner_id=owner_id,
                    exclude_expired=False,
                    offset=offset,
                    limit=_BATCH,
                )
                candidate_ids.extend(item.id for item in items)
                batch_len = len(items)
                offset += batch_len
                if batch_len < _BATCH:
                    break

        return candidate_ids

    async def cleanup_expired(
        self,
        data: TrashCleanupRequest,
        *,
        actor_id: UUID | None = None,
    ) -> TrashPurgeResponse:
        """Очищает истекшие или старые элементы корзины.

        Находит элементы корзины по условиям срока хранения и возраста. Если
        dry_run=True, возвращает список кандидатов без удаления. Если actor_id
        не указан, выполняет системное удаление без пользовательской проверки
        доступа.

        Args:
            data: Данные запроса очистки истекших элементов.
            actor_id: Идентификатор пользователя, выполняющего очистку. Если None,
                используется системный purge.

        Returns:
            Сводный результат очистки или dry-run.

        Raises:
            PermissionServiceError: Если пользователь пытается очистить корзину
                другого владельца.
            ServiceError: Если поиск кандидатов или purge завершились ошибкой.
        """

        operation = "cleanup_expired"
        owner_id = data.owner_id
        if actor_id is not None and owner_id is not None and owner_id != actor_id:
            raise PermissionServiceError(
                "Только администратор может очищать корзину другого пользователя.",
                user_id=actor_id,
                resource_type="trash",
                resource_id=owner_id,
                action="cleanup",
                details={"service": SERVICE_NAME, "operation": operation},
            )

        trash_item_ids = await self._find_purge_candidates(
            owner_id=owner_id,
            older_than=data.older_than,
            expired_before=data.expired_before,
            limit=data.limit,
        )
        if data.dry_run:
            return _purge_response(
                requested_count=len(trash_item_ids),
                purged_ids=[],
                failed_ids=[],
                message="Пробная очистка корзины завершена.",
            )
        if not trash_item_ids:
            return _purge_response(
                requested_count=0,
                purged_ids=[],
                failed_ids=[],
                message="Нет элементов корзины, соответствующих условиям очистки.",
            )

        purge_actor_id = actor_id
        if purge_actor_id is None:
            return await self._system_purge(trash_item_ids)
        return await self.purge(
            TrashPurgeRequest(trash_item_ids=trash_item_ids),
            actor_id=purge_actor_id,
        )

    async def _resolve_purge_ids(self, data: TrashPurgeRequest) -> list[UUID]:
        """Разрешает идентификаторы элементов корзины для purge.

        Использует явно переданные trash_item_ids и дополнительно ищет активные
        элементы корзины по node_ids. Дубликаты удаляются с сохранением порядка.

        Args:
            data: Данные запроса purge.

        Returns:
            Список уникальных идентификаторов элементов корзины.

        Raises:
            NotFoundServiceError: Если по одному из node_ids не найден активный
                элемент корзины.
        """

        ids: list[UUID] = []
        if data.trash_item_ids:
            ids.extend(data.trash_item_ids)
        if data.node_ids:
            async with self.uow_factory() as uow:
                for node_id in data.node_ids:
                    trash_item = await uow.trash.get_active_by_node_id(node_id)
                    if trash_item is None:
                        raise NotFoundServiceError(
                            entity_name="TrashItem",
                            lookup={"node_id": str(node_id)},
                            details={
                                "service": SERVICE_NAME,
                                "operation": "_resolve_purge_ids",
                            },
                        )
                    ids.append(trash_item.id)
        return list(dict.fromkeys(ids))

    async def _purge_one(self, trash_item_id: UUID, *, actor_id: UUID) -> None:
        """Окончательно удаляет один элемент корзины.

        Проверяет право PURGE, строит план удаления, удаляет физические объекты
        из хранилища, помечает элемент корзины и узел как окончательно удаленные,
        уменьшает счетчики квоты и записывает событие аудита.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            actor_id: Идентификатор пользователя, выполняющего purge.

        Raises:
            NotFoundServiceError: Если элемент корзины не найден.
            PermissionServiceError: Если у пользователя нет права PURGE.
            StorageError: Если удаление объекта из хранилища завершилось ошибкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "_purge_one"
        plan: PurgePlan | None = None
        try:
            async with self.uow_factory() as uow:
                trash_item = await uow.trash.get_by_id(trash_item_id)
                if trash_item is None:
                    raise NotFoundServiceError(
                        entity_name="TrashItem",
                        entity_id=trash_item_id,
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                await self.access_service.require_access(
                    node_id=trash_item.node_id,
                    user_id=actor_id,
                    action=PermissionAction.PURGE,
                    allow_deleted=True,
                    allow_public=False,
                    uow=uow,
                )
                plan = await _build_purge_plan(uow=uow, trash_item=trash_item)

            if plan is None:
                raise _empty_result_error(operation)
            await self._delete_storage_objects(plan.storage_objects)

            async with self.uow_factory() as uow:
                trash_item = await uow.trash.get_by_id(trash_item_id)
                if trash_item is None:
                    raise NotFoundServiceError(
                        entity_name="TrashItem",
                        entity_id=trash_item_id,
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                trash_item.status = TrashItemStatus.PURGED
                trash_item.purged_at = datetime.now(UTC)
                trash_item.restore_available = False
                await uow.links.delete_links_by_node(
                    plan.node_id,
                    flush=True,
                )
                await uow.trash.mark_purged(
                    trash_item_id=trash_item.id,
                    purged_at=trash_item.purged_at,
                    purge_node=True,
                    flush=True,
                    refresh=False,
                )
                if plan.total_size_bytes > 0:
                    await uow.quotas.decrease_used_space(
                        user_id=plan.owner_id,
                        size_bytes=plan.total_size_bytes,
                        flush=True,
                        refresh=False,
                    )
                if plan.file_count > 0:
                    await uow.quotas.decrease_files_used(
                        user_id=plan.owner_id,
                        count=plan.file_count,
                        flush=True,
                        refresh=False,
                    )
                await uow.commit()

            await self._safe_log_trash_event(
                actor_id=actor_id,
                action=_purged_action(plan.node_type),
                resource_type=_resource_type(plan.node_type),
                entity_id=plan.node_id,
                message="Узел был окончательно удалён из корзины.",
                metadata={
                    "trash_item_id": str(plan.trash_item_id),
                    "node_id": str(plan.node_id),
                    "file_count": plan.file_count,
                    "total_size_bytes": plan.total_size_bytes,
                    "storage_object_count": len(plan.storage_objects),
                },
            )

        except ServiceError:
            raise
        except StorageError as exc:
            raise service_error_from_storage(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def _system_purge(self, trash_item_ids: Iterable[UUID]) -> TrashPurgeResponse:
        """Окончательно удаляет элементы корзины от имени системы.

        Используется для автоматической очистки без actor_id. Для каждого элемента
        строит план, удаляет объекты хранилища, помечает элемент как PURGED,
        уменьшает квоты и фиксирует успешные и ошибочные идентификаторы.

        Args:
            trash_item_ids: Идентификаторы элементов корзины для удаления.

        Returns:
            Сводный результат системного purge.
        """

        requested_ids = list(trash_item_ids)
        purged_ids: list[UUID] = []
        failed_ids: list[UUID] = []
        for trash_item_id in requested_ids:
            try:
                plan = await self._build_system_plan(trash_item_id)
                await self._delete_storage_objects(plan.storage_objects)
                async with self.uow_factory() as uow:
                    trash_item = await uow.trash.get_by_id(trash_item_id)
                    if trash_item is None:
                        raise NotFoundServiceError(
                            entity_name="TrashItem",
                            entity_id=trash_item_id,
                            details={
                                "service": SERVICE_NAME,
                                "operation": "_system_purge",
                            },
                        )
                    trash_item.status = TrashItemStatus.PURGED
                    trash_item.purged_at = datetime.now(UTC)
                    trash_item.restore_available = False
                    await uow.links.delete_links_by_node(
                        plan.node_id,
                        flush=True,
                    )
                    await uow.trash.mark_purged(
                        trash_item_id=trash_item.id,
                        purged_at=trash_item.purged_at,
                        purge_node=True,
                        flush=True,
                        refresh=False,
                    )
                    if plan.total_size_bytes > 0:
                        await uow.quotas.decrease_used_space(
                            user_id=plan.owner_id,
                            size_bytes=plan.total_size_bytes,
                            flush=True,
                            refresh=False,
                        )
                    if plan.file_count > 0:
                        await uow.quotas.decrease_files_used(
                            user_id=plan.owner_id,
                            count=plan.file_count,
                            flush=True,
                            refresh=False,
                        )
                    await uow.commit()
                purged_ids.append(trash_item_id)
            except ServiceError:
                failed_ids.append(trash_item_id)

        return _purge_response(
            requested_count=len(requested_ids),
            purged_ids=purged_ids,
            failed_ids=failed_ids,
            message=(
                "Очистка корзины завершена."
                if not failed_ids
                else "Очистка корзины завершена с ошибками."
            ),
        )

    async def _build_system_plan(self, trash_item_id: UUID) -> PurgePlan:
        """Строит план системного purge для элемента корзины.

        Args:
            trash_item_id: Идентификатор элемента корзины.

        Returns:
            План окончательного удаления элемента корзины.

        Raises:
            NotFoundServiceError: Если элемент корзины не найден.
        """

        plan: PurgePlan | None = None
        async with self.uow_factory() as uow:
            trash_item = await uow.trash.get_by_id(trash_item_id)
            if trash_item is None:
                raise NotFoundServiceError(
                    entity_name="TrashItem",
                    entity_id=trash_item_id,
                    details={
                        "service": SERVICE_NAME,
                        "operation": "_build_system_plan",
                    },
                )
            plan = await _build_purge_plan(uow=uow, trash_item=trash_item)
        if plan is None:
            raise _empty_result_error("_build_system_plan")
        return plan

    async def _find_purge_candidates(
        self,
        *,
        owner_id: UUID | None = None,
        older_than: datetime | None = None,
        expired_before: datetime | None = None,
        only_expired: bool = False,
        limit: int = 5000,
    ) -> list[UUID]:
        """Находит кандидатов для окончательного удаления.

        Получает истекшие элементы корзины, дополнительно фильтрует их по времени
        удаления и возвращает идентификаторы.

        Args:
            owner_id: Идентификатор владельца корзины. Если None, поиск выполняется
                без ограничения по владельцу.
            older_than: Оставить только элементы, удаленные не позже этой даты.
            expired_before: Момент времени, относительно которого проверяется
                истечение срока хранения. Если None, используется текущее время UTC.
            only_expired: Нужно ли включать только истекшие элементы.
            limit: Максимальное количество кандидатов.

        Returns:
            Список идентификаторов элементов корзины для purge.
        """

        _BATCH = 1000
        candidate_ids: list[UUID] = []
        now = expired_before or datetime.now(UTC)
        offset = 0

        while len(candidate_ids) < limit:
            batch_limit = min(_BATCH, limit - len(candidate_ids))
            async with self.uow_factory() as uow:
                items = await uow.trash.get_expired_items(
                    now=now,
                    owner_id=owner_id,
                    include_non_restorable=not only_expired,
                    offset=offset,
                    limit=batch_limit,
                )
                if older_than is not None:
                    candidate_ids.extend(
                        item.id
                        for item in items
                        if item.deleted_at is not None and item.deleted_at <= older_than
                    )
                else:
                    candidate_ids.extend(item.id for item in items)
                raw_len = len(items)
                offset += raw_len
                if raw_len < batch_limit:
                    break

        return candidate_ids

    async def _delete_storage_objects(
        self,
        storage_objects: Iterable[StorageObjectRef],
    ) -> None:
        """Удаляет физические объекты из хранилища.

        Дедуплицирует объекты по паре bucket/object_key и удаляет каждый объект
        через StorageService с missing_ok=True.

        Args:
            storage_objects: Ссылки на объекты хранилища для удаления.

        Raises:
            StorageError: Если StorageService не смог удалить объект.
        """

        seen: set[tuple[str, str]] = set()
        for ref in storage_objects:
            identity = (ref.bucket, ref.object_key)
            if identity in seen:
                continue
            seen.add(identity)
            await self.storage_service.delete_file_object(
                bucket=ref.bucket,
                object_key=ref.object_key,
                missing_ok=True,
            )

    async def _safe_log_trash_event(
        self,
        *,
        actor_id: UUID | None,
        action: AuditAction,
        resource_type: AuditResourceType,
        entity_id: UUID | None,
        message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Безопасно записывает событие корзины в аудит.

        Ошибки аудита не пробрасываются выше, чтобы не ломать основную операцию
        корзины. При ошибке записи пишет предупреждение в лог.

        Args:
            actor_id: Идентификатор пользователя, связанного с событием. Может быть
                None для системных операций.
            action: Действие аудита.
            resource_type: Тип ресурса аудита.
            entity_id: Идентификатор сущности, связанной с событием.
            message: Сообщение события аудита.
            metadata: Дополнительные метаданные события.
        """

        try:
            await self.audit_service.log_event(
                action=action,
                result=AuditResult.SUCCESS,
                user_id=actor_id,
                entity_type=resource_type.value,
                entity_id=entity_id,
                resource_type=resource_type,
                message=message,
                metadata=metadata,
            )
        except ServiceError:
            logger.warning(
                "Не удалось записать событие аудита корзины",
                extra={"action": action.value, "entity_id": str(entity_id)},
                exc_info=True,
            )


async def _get_trash_item_for_request(
    *,
    uow: Any,
    trash_item_id: UUID | None,
    node_id: UUID | None,
) -> TrashItem:
    """Находит элемент корзины по trash_item_id или node_id.

    Args:
        uow: Unit of Work с репозиторием корзины.
        trash_item_id: Идентификатор элемента корзины. Может быть None.
        node_id: Идентификатор узла, находящегося в корзине. Может быть None.

    Returns:
        Найденный элемент корзины.

    Raises:
        NotFoundServiceError: Если элемент корзины не найден.
    """

    if trash_item_id is not None:
        trash_item = await uow.trash.get_by_id(trash_item_id)
    elif node_id is not None:
        trash_item = await uow.trash.get_active_by_node_id(node_id)
    else:
        trash_item = None

    if trash_item is None:
        raise NotFoundServiceError(
            entity_name="TrashItem",
            lookup={
                "trash_item_id": str(trash_item_id) if trash_item_id else None,
                "node_id": str(node_id) if node_id else None,
            },
            details={
                "service": SERVICE_NAME,
                "operation": "_get_trash_item_for_request",
            },
        )
    return cast(TrashItem, trash_item)


def _ensure_restorable(trash_item: TrashItem) -> None:
    """Проверяет, что элемент корзины можно восстановить.

    Элемент должен находиться в статусе IN_TRASH, не быть purged, иметь
    restore_available=True и не иметь истекший срок хранения.

    Args:
        trash_item: Элемент корзины для проверки.

    Raises:
        ValidationServiceError: Если элемент нельзя восстановить.
    """

    if (
        trash_item.status != TrashItemStatus.IN_TRASH
        or trash_item.purged_at is not None
    ):
        raise ValidationServiceError(
            "Элемент корзины нельзя восстановить, потому что он не активен.",
            field="trash_item_id",
            value=trash_item.id,
            reason="not_in_trash",
            details={"service": SERVICE_NAME, "operation": "restore"},
        )
    if not trash_item.restore_available:
        raise ValidationServiceError(
            "Элемент корзины недоступен для восстановления.",
            field="trash_item_id",
            value=trash_item.id,
            reason="restore_disabled",
            details={"service": SERVICE_NAME, "operation": "restore"},
        )
    if trash_item.expires_at is not None and _normalize_datetime(
        trash_item.expires_at
    ) <= datetime.now(UTC):
        raise ValidationServiceError(
            "Срок хранения элемента корзины истёк.",
            field="trash_item_id",
            value=trash_item.id,
            reason="expired",
            details={"service": SERVICE_NAME, "operation": "restore"},
        )


async def _build_purge_plan(*, uow: Any, trash_item: TrashItem) -> PurgePlan:
    """Строит план окончательного удаления элемента корзины.

    Для файла собирает его объект хранилища и объекты всех версий. Для папки
    загружает всех потомков и собирает объекты хранилища всех вложенных файлов.
    Также считает суммарный размер и количество файлов.

    Args:
        uow: Unit of Work с репозиториями узлов и файлов.
        trash_item: Элемент корзины, для которого строится план.

    Returns:
        План окончательного удаления.
    """

    node = trash_item.node
    if node is None:
        node = await uow.nodes.get_required_by_id(trash_item.node_id)
    if node is None:
        raise _empty_result_error("_build_purge_plan")

    nodes = [node]
    if node.node_type == NodeType.FOLDER:
        nodes = await uow.nodes.get_descendants(
            node_id=node.id,
            include_self=True,
            include_deleted=True,
            order_by_depth=False,
        )

    storage_objects: list[StorageObjectRef] = []
    total_size_bytes = 0
    file_count = 0
    for current_node in nodes:
        if current_node.node_type != NodeType.FILE:
            continue
        file = await uow.files.get_by_node_id(
            current_node.id,
            include_deleted_node=True,
        )
        if file is None:
            continue
        file_count += 1
        total_size_bytes += int(file.size_bytes)
        storage_objects.extend(_file_storage_objects(file))

    return PurgePlan(
        trash_item_id=trash_item.id,
        node_id=trash_item.node_id,
        owner_id=trash_item.owner_id,
        node_type=node.node_type,
        total_size_bytes=total_size_bytes,
        file_count=file_count,
        storage_objects=tuple(storage_objects),
    )


def _file_storage_objects(file: File) -> list[StorageObjectRef]:
    """Возвращает объекты хранилища файла и его версий.

    Args:
        file: ORM-модель файла.

    Returns:
        Список ссылок на физические объекты файла и его версий.
    """

    refs: list[StorageObjectRef] = []
    if file.storage_key:
        refs.append(
            StorageObjectRef(bucket=file.storage_bucket, object_key=file.storage_key)
        )
    for version in file.versions:
        refs.extend(_version_storage_objects(version))
    return refs


def _version_storage_objects(version: FileVersion) -> list[StorageObjectRef]:
    """Возвращает объект хранилища версии файла.

    Args:
        version: ORM-модель версии файла.

    Returns:
        Список из одной ссылки на объект версии или пустой список, если
        storage_key отсутствует.
    """

    if not version.storage_key:
        return []
    return [
        StorageObjectRef(bucket=version.storage_bucket, object_key=version.storage_key)
    ]


def _validate_sort_field(sort_by: str) -> str:
    """Проверяет и нормализует поле сортировки корзины.

    Args:
        sort_by: Исходное поле сортировки.

    Returns:
        Нормализованное поле сортировки.

    Raises:
        ValidationServiceError: Если поле сортировки не поддерживается.
    """

    normalized = sort_by.strip().lower()
    if normalized not in ALLOWED_TRASH_SORT_FIELDS:
        raise ValidationServiceError(
            "Поле сортировки корзины не поддерживается.",
            field="sort_by",
            value=sort_by,
            details={
                "allowed_values": sorted(ALLOWED_TRASH_SORT_FIELDS),
                "service": SERVICE_NAME,
                "operation": "list_trash",
            },
        )
    return normalized


def _trash_item_snapshot(trash_item: TrashItem) -> dict[str, Any]:
    """Создает снимок элемента корзины.

    Args:
        trash_item: ORM-модель элемента корзины.

    Returns:
        Словарь с идентификаторами элемента, узла, владельца, исходным
        расположением, статусом, датами удаления, истечения и purge, признаком
        доступности восстановления и снимком связанного узла.
    """

    node = trash_item.node
    return {
        "id": trash_item.id,
        "node_id": trash_item.node_id,
        "owner_id": trash_item.owner_id,
        "deleted_by": trash_item.deleted_by,
        "original_parent_id": trash_item.original_parent_id,
        "original_path": trash_item.original_path,
        "status": trash_item.status,
        "deleted_at": trash_item.deleted_at,
        "expires_at": trash_item.expires_at,
        "restore_available": bool(trash_item.restore_available),
        "purged_at": trash_item.purged_at,
        "node": None if node is None else _node_snapshot(node),
    }


def _node_snapshot(node: FileSystemNode | None) -> dict[str, Any] | None:
    """Создает снимок узла файловой системы.

    Args:
        node: ORM-модель узла файловой системы или None.

    Returns:
        Словарь с основными полями узла или None, если узел отсутствует.
    """

    if node is None:
        return None
    return {
        "id": node.id,
        "owner_id": node.owner_id,
        "parent_id": node.parent_id,
        "name": node.name,
        "node_type": node.node_type,
        "visibility": node.visibility,
        "path": node.path,
        "depth": node.depth,
        "created_by": node.created_by,
        "updated_by": node.updated_by,
        "deleted_by": node.deleted_by,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "is_deleted": node.is_deleted,
        "deleted_at": node.deleted_at,
    }


def _deleted_action_from_node_snapshot(snapshot: Mapping[str, Any]) -> AuditAction:
    """Определяет audit-действие удаления по типу узла.

    Args:
        snapshot: Снимок элемента корзины со вложенным снимком узла.

    Returns:
        FILE_DELETED для файла, FOLDER_DELETED для папки или NODE_DELETED для
        остальных типов.
    """

    node = snapshot.get("node")
    node_type = node.get("node_type") if isinstance(node, Mapping) else None
    if node_type == NodeType.FILE:
        return AuditAction.FILE_DELETED
    if node_type == NodeType.FOLDER:
        return AuditAction.FOLDER_DELETED
    return AuditAction.NODE_DELETED


def _restored_action_from_node_snapshot(snapshot: Mapping[str, Any]) -> AuditAction:
    """Определяет audit-действие восстановления по типу узла.

    Args:
        snapshot: Снимок элемента корзины со вложенным снимком узла.

    Returns:
        FILE_RESTORED для файла, FOLDER_RESTORED для папки или NODE_RESTORED
        для остальных типов.
    """

    node = snapshot.get("node")
    node_type = node.get("node_type") if isinstance(node, Mapping) else None
    if node_type == NodeType.FILE:
        return AuditAction.FILE_RESTORED
    if node_type == NodeType.FOLDER:
        return AuditAction.FOLDER_RESTORED
    return AuditAction.NODE_RESTORED


def _resource_type_from_node_snapshot(snapshot: Mapping[str, Any]) -> AuditResourceType:
    """Определяет тип audit-ресурса по типу узла из снимка.

    Args:
        snapshot: Снимок элемента корзины со вложенным снимком узла.

    Returns:
        FILE для файла, FOLDER для папки или NODE для остальных типов.
    """

    node = snapshot.get("node")
    node_type = node.get("node_type") if isinstance(node, Mapping) else None
    if node_type == NodeType.FILE:
        return AuditResourceType.FILE
    if node_type == NodeType.FOLDER:
        return AuditResourceType.FOLDER
    return AuditResourceType.NODE


def _purged_action(node_type: NodeType) -> AuditAction:
    """Определяет audit-действие purge по типу узла.

    Args:
        node_type: Тип узла файловой системы.

    Returns:
        FILE_PURGED для файла, FOLDER_PURGED для папки или NODE_PURGED для
        остальных типов.
    """

    if node_type == NodeType.FILE:
        return AuditAction.FILE_PURGED
    if node_type == NodeType.FOLDER:
        return AuditAction.FOLDER_PURGED
    return AuditAction.NODE_PURGED


def _resource_type(node_type: NodeType) -> AuditResourceType:
    """Определяет тип audit-ресурса по типу узла.

    Args:
        node_type: Тип узла файловой системы.

    Returns:
        FILE для файла, FOLDER для папки или NODE для остальных типов.
    """

    if node_type == NodeType.FILE:
        return AuditResourceType.FILE
    if node_type == NodeType.FOLDER:
        return AuditResourceType.FOLDER
    return AuditResourceType.NODE


def _audit_trash(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует метаданные элемента корзины для аудита.

    Args:
        snapshot: Снимок элемента корзины.

    Returns:
        Словарь с JSON-совместимыми метаданными корзины.
    """

    return {
        "trash_item_id": _jsonable(snapshot.get("id")),
        "node_id": _jsonable(snapshot.get("node_id")),
        "owner_id": _jsonable(snapshot.get("owner_id")),
        "status": _jsonable(snapshot.get("status")),
        "original_path": _jsonable(snapshot.get("original_path")),
        "deleted_at": _jsonable(snapshot.get("deleted_at")),
        "expires_at": _jsonable(snapshot.get("expires_at")),
        "purged_at": _jsonable(snapshot.get("purged_at")),
    }


def _purge_response(
    *,
    requested_count: int,
    purged_ids: list[UUID],
    failed_ids: list[UUID],
    message: str,
) -> TrashPurgeResponse:
    """Формирует ответ операции purge.

    Args:
        requested_count: Количество запрошенных к удалению элементов.
        purged_ids: Идентификаторы успешно удаленных элементов корзины.
        failed_ids: Идентификаторы элементов, которые не удалось удалить.
        message: Итоговое сообщение операции.

    Returns:
        Ответ purge с количеством успешных и ошибочных элементов.
    """

    return TrashPurgeResponse(
        success=not failed_ids,
        requested_count=requested_count,
        purged_count=len(purged_ids),
        failed_count=len(failed_ids),
        purged_trash_item_ids=purged_ids,
        failed_trash_item_ids=failed_ids,
        message=message,
    )


def _empty_result_error(operation: str) -> ServiceError:
    """Создает ошибку отсутствующего снимка результата.

    Args:
        operation: Название операции, завершившейся без снимка результата.

    Returns:
        Ошибка сервиса с описанием отсутствующего результата.
    """

    return ServiceError(
        "Операция завершена, но снимок результата не был создан.",
        service=SERVICE_NAME,
        operation=operation,
    )


def _normalize_datetime(value: datetime) -> datetime:
    """Нормализует дату и время к UTC.

    Если значение не содержит timezone, считает его временем UTC. Если timezone
    указан, переводит значение в UTC.

    Args:
        value: Дата и время для нормализации.

    Returns:
        Дата и время с timezone UTC.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    """Преобразует значение в JSON-совместимый формат.

    Поддерживает примитивы, UUID, datetime, Enum, Mapping и Iterable. Для
    остальных объектов возвращает строковое представление.

    Args:
        value: Значение для преобразования.

    Returns:
        JSON-совместимое представление значения.
    """

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Iterable):
        return [_jsonable(item) for item in value]
    return str(value)


def get_trash_service(
    *,
    settings: Settings | None = None,
    uow_factory: UnitOfWorkFactory | None = None,
    storage_service: StorageService | None = None,
    access_service: AccessService | None = None,
    audit_service: AuditService | None = None,
) -> TrashService:
    """Создаёт экземпляр сервиса корзины.

    Args:
        settings: Настройки приложения. Если не переданы, сервис загрузит
            стандартные настройки самостоятельно.
        uow_factory: Фабрика UnitOfWork. Если не передана, сервис создаст
            стандартную фабрику самостоятельно.
        storage_service: Сервис хранилища. Если не передан, будет создан
            стандартный сервис хранилища.
        access_service: Сервис проверки доступа. Если не передан, будет создан
            стандартный сервис доступа.
        audit_service: Сервис аудита. Если не передан, будет создан стандартный
            сервис аудита.

    Returns:
        Экземпляр `TrashService`.
    """

    return TrashService(
        settings=settings,
        uow_factory=uow_factory,
        storage_service=storage_service,
        access_service=access_service,
        audit_service=audit_service,
    )
