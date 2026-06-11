from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from core.logging import get_logger
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import AuditAction, AuditResourceType, AuditResult
from database.models.permissions import NodePermission
from schemas.common import PageMeta, PageResponse
from schemas.permissions import (
    EffectivePermissionRead,
    NodePermissionListItem,
    NodePermissionRead,
    PermissionCheckRequest,
    PermissionCheckResponse,
    PermissionGrantRequest,
    PermissionRevokeRequest,
    PermissionUpdateRequest,
    SharedNodeItem,
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
)

logger = get_logger("services.permissions")

SERVICE_NAME = "permissions"
MAX_PAGE_LIMIT = 1000


class PermissionsService:
    """Сервис бизнес-логики для явных прав доступа к узлам.

    Управляет записями NodePermission: выдает, обновляет, отзывает и читает
    явные права доступа. Для проверки прав на выполнение операций использует
    AccessService, а после успешных изменений записывает события аудита.

    Attributes:
        uow_factory: Фабрика Unit of Work для работы с базой данных.
        access_service: Сервис проверки эффективного доступа к узлам.
        audit_service: Сервис записи событий аудита.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
        access_service: AccessService | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        """Инициализирует сервис прав доступа.

        Если зависимости не переданы явно, создает их через стандартные фабрики
        и функции получения сервисов.

        Args:
            uow_factory: Фабрика Unit of Work. Если None, создается стандартная
                фабрика.
            access_service: Сервис проверки доступа. Если None, создается
                стандартный сервис доступа.
            audit_service: Сервис аудита. Если None, создается стандартный сервис
                аудита.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.access_service = access_service or get_access_service(
            uow_factory=self.uow_factory
        )
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory
        )

    async def grant_permission(
        self,
        data: PermissionGrantRequest,
        *,
        actor_id: UUID,
    ) -> NodePermissionRead:
        """Выдает или заменяет явное право пользователя на узел.

        Проверяет, что actor_id имеет право делиться узлом, что целевой пользователь
        существует и что право не выдается владельцу узла, так как владелец уже
        имеет полный доступ. Затем создает или заменяет запись NodePermission.

        Args:
            data: Данные для выдачи права доступа.
            actor_id: Идентификатор пользователя, выдающего право.

        Returns:
            Данные созданной или замененной записи права доступа.

        Raises:
            PermissionServiceError: Если actor_id не имеет права делиться узлом.
            ValidationServiceError: Если право выдается владельцу узла.
            NotFoundServiceError: Если целевой пользователь или узел не найден.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "grant_permission"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=data.node_id,
                    user_id=actor_id,
                    action=PermissionAction.SHARE,
                    allow_deleted=False,
                    allow_public=False,
                    uow=uow,
                )
                await uow.users.get_required_user_by_id(data.user_id)
                if data.user_id == node.owner_id:
                    raise ValidationServiceError(
                        "Владелец уже имеет полный доступ к узлу.",
                        field="user_id",
                        value=data.user_id,
                        reason="target_is_owner",
                        details=_error_details(operation),
                    )

                permission = await uow.permissions.grant_permission(
                    node_id=data.node_id,
                    user_id=data.user_id,
                    granted_by=actor_id,
                    can_read=data.can_read,
                    can_download=data.can_download,
                    can_write=data.can_write,
                    can_delete=data.can_delete,
                    can_share=data.can_share,
                    expires_at=data.expires_at,
                    flush=True,
                    refresh=True,
                )
                permission.permission_level = data.permission_level
                permission.revoke_reason = None
                await uow.flush()
                await uow.refresh(permission)
                snapshot = _permission_snapshot(permission)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_permission_event(
                actor_id=actor_id,
                action=AuditAction.PERMISSION_GRANTED,
                permission_snapshot=snapshot,
                message="Разрешение на узел было выдано.",
            )
            return NodePermissionRead.model_validate(snapshot)

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

    async def update_permission(
        self,
        data: PermissionUpdateRequest,
        *,
        actor_id: UUID,
    ) -> NodePermissionRead:
        """Обновляет существующее явное право доступа к узлу.

        Находит запись права по permission_id или паре node_id/user_id, проверяет
        право actor_id делиться соответствующим узлом, применяет изменения флагов,
        срока действия и уровня доступа, затем сохраняет обновление.

        Args:
            data: Данные обновления права доступа.
            actor_id: Идентификатор пользователя, выполняющего обновление.

        Returns:
            Данные обновленной записи права доступа.

        Raises:
            PermissionServiceError: Если actor_id не имеет права делиться узлом.
            NotFoundServiceError: Если запись NodePermission не найдена.
            ValidationServiceError: Если после обновления право не разрешает ни
                одного действия.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "update_permission"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                permission = await _resolve_permission(uow=uow, data=data)
                await self.access_service.require_access(
                    node_id=permission.node_id,
                    user_id=actor_id,
                    action=PermissionAction.SHARE,
                    allow_deleted=False,
                    allow_public=False,
                    uow=uow,
                )

                _apply_permission_update(permission, data)
                await uow.flush()
                await uow.refresh(permission)
                snapshot = _permission_snapshot(permission)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_permission_event(
                actor_id=actor_id,
                action=AuditAction.PERMISSION_UPDATED,
                permission_snapshot=snapshot,
                message="Разрешение узла было обновлено.",
            )
            return NodePermissionRead.model_validate(snapshot)

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

    async def revoke_permission(
        self,
        data: PermissionRevokeRequest,
        *,
        actor_id: UUID,
    ) -> NodePermissionRead:
        """Отзывает явное право доступа к узлу.

        Находит запись права по permission_id или паре node_id/user_id, проверяет
        право actor_id делиться соответствующим узлом и помечает право как
        отозванное без удаления записи из базы данных.

        Args:
            data: Данные отзыва права доступа.
            actor_id: Идентификатор пользователя, выполняющего отзыв.

        Returns:
            Данные отозванной записи права доступа.

        Raises:
            PermissionServiceError: Если actor_id не имеет права делиться узлом.
            NotFoundServiceError: Если запись NodePermission не найдена.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "revoke_permission"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                permission = await _resolve_permission(uow=uow, data=data)
                await self.access_service.require_access(
                    node_id=permission.node_id,
                    user_id=actor_id,
                    action=PermissionAction.SHARE,
                    allow_deleted=False,
                    allow_public=False,
                    uow=uow,
                )
                permission.revoke(
                    reason=data.revoke_reason,
                    revoked_at=datetime.now(UTC),
                )
                await uow.flush()
                await uow.refresh(permission)
                snapshot = _permission_snapshot(permission)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_permission_event(
                actor_id=actor_id,
                action=AuditAction.PERMISSION_REVOKED,
                permission_snapshot=snapshot,
                message="Разрешение узла было отозвано.",
            )
            return NodePermissionRead.model_validate(snapshot)

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

    async def get_permission(
        self,
        permission_id: UUID,
        *,
        actor_id: UUID,
    ) -> NodePermissionRead:
        """Возвращает одну запись права доступа.

        Загружает NodePermission по идентификатору и проверяет, что actor_id имеет
        право управлять доступом к узлу, связанному с этой записью.

        Args:
            permission_id: Идентификатор записи NodePermission.
            actor_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Данные найденной записи права доступа.

        Raises:
            NotFoundServiceError: Если запись NodePermission не найдена.
            PermissionServiceError: Если actor_id не имеет права делиться узлом.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "get_permission"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                permission = await uow.permissions.get_permission_by_id(permission_id)
                if permission is None:
                    raise NotFoundServiceError(
                        entity_name="NodePermission",
                        entity_id=permission_id,
                        details=_error_details(operation),
                    )
                await self.access_service.require_access(
                    node_id=permission.node_id,
                    user_id=actor_id,
                    action=PermissionAction.SHARE,
                    allow_deleted=False,
                    allow_public=False,
                    uow=uow,
                )
                snapshot = _permission_snapshot(permission)
            if snapshot is None:
                raise _empty_result_error(operation)
            return NodePermissionRead.model_validate(snapshot)

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

    async def list_node_permissions(
        self,
        *,
        node_id: UUID,
        actor_id: UUID,
        active_only: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> PageResponse[NodePermissionListItem]:
        """Возвращает список явных прав, выданных на узел.

        Проверяет, что actor_id имеет право делиться указанным узлом, затем
        возвращает страницу записей NodePermission для этого узла.

        Args:
            node_id: Идентификатор узла файловой системы.
            actor_id: Идентификатор пользователя, выполняющего запрос.
            active_only: Нужно ли возвращать только активные права.
            offset: Смещение для постраничной выдачи.
            limit: Максимальное количество элементов в ответе.

        Returns:
            Страница записей прав доступа и метаданные пагинации.

        Raises:
            PermissionServiceError: Если actor_id не имеет права делиться узлом.
            ValidationServiceError: Если limit меньше 1.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_node_permissions"
        limit = _validate_limit(limit)
        snapshots: list[dict] = []
        total = 0
        try:
            async with self.uow_factory() as uow:
                await self.access_service.require_access(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.SHARE,
                    allow_deleted=False,
                    allow_public=False,
                    uow=uow,
                )
                items = await uow.permissions.get_node_permissions(
                    node_id=node_id,
                    active_only=active_only,
                    offset=offset,
                    limit=limit,
                )
                total = await uow.permissions.count_node_permissions(
                    node_id=node_id,
                    active_only=active_only,
                )
                snapshots = [_permission_snapshot(item) for item in items]

            dto_items = [
                NodePermissionListItem.model_validate(snapshot)
                for snapshot in snapshots
            ]
            return PageResponse(
                items=dto_items,
                meta=PageMeta(
                    limit=limit,
                    offset=offset,
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

    async def list_user_permissions(
        self,
        *,
        user_id: UUID,
        actor_id: UUID,
        active_only: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> PageResponse[NodePermissionListItem]:
        """Возвращает список явных прав, выданных пользователю.

        Обычный пользователь может просматривать только собственные права. Проверки
        административного доступа должны добавляться на уровне API-зависимостей.

        Args:
            user_id: Идентификатор пользователя, чьи права нужно получить.
            actor_id: Идентификатор пользователя, выполняющего запрос.
            active_only: Нужно ли возвращать только активные права.
            offset: Смещение для постраничной выдачи.
            limit: Максимальное количество элементов в ответе.

        Returns:
            Страница записей прав доступа и метаданные пагинации.

        Raises:
            PermissionServiceError: Если actor_id пытается получить права другого
                пользователя.
            ValidationServiceError: Если limit меньше 1.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_user_permissions"
        if actor_id != user_id:
            raise PermissionServiceError(
                "Пользователь может указать только свои собственные явные разрешения.",
                user_id=actor_id,
                resource_type="user",
                resource_id=user_id,
                action="list_permissions",
                details=_error_details(operation),
            )
        limit = _validate_limit(limit)
        items: list[NodePermission] = []
        total = 0
        try:
            async with self.uow_factory() as uow:
                items = await uow.permissions.get_user_permissions(
                    user_id=user_id,
                    active_only=active_only,
                    offset=offset,
                    limit=limit,
                )
                total = await uow.permissions.count_user_permissions(
                    user_id=user_id,
                    active_only=active_only,
                )

            dto_items = [
                NodePermissionListItem.model_validate(_permission_snapshot(item))
                for item in items
            ]
            return PageResponse(
                items=dto_items,
                meta=PageMeta(
                    limit=limit,
                    offset=offset,
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

    async def list_shared_with_me(
        self,
        *,
        user_id: UUID,
        actor_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> PageResponse[SharedNodeItem]:
        """Возвращает узлы, к которым пользователю выдан явный активный доступ.

        В отличие от ``list_user_permissions`` отдаёт метаданные самих узлов
        (имя, тип, путь, mime/размер, владелец) вместе с параметрами права —
        чтобы фронтенд мог отрисовать вкладку «Доступно мне» одним запросом.
        Удалённые узлы и узлы без доступной метаинформации пропускаются.

        Args:
            user_id: Идентификатор пользователя, чей доступ нужно показать.
            actor_id: Идентификатор пользователя, выполняющего запрос.
            offset: Смещение для постраничной выдачи.
            limit: Максимальное количество элементов в ответе.

        Returns:
            Страница узлов «Доступно мне» и метаданные пагинации.

        Raises:
            PermissionServiceError: Если actor_id запрашивает чужой доступ.
            ValidationServiceError: Если limit меньше 1.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_shared_with_me"
        if actor_id != user_id:
            raise PermissionServiceError(
                "Пользователь может запросить только собственный доступ.",
                user_id=actor_id,
                resource_type="user",
                resource_id=user_id,
                action="list_shared_with_me",
                details=_error_details(operation),
            )
        limit = _validate_limit(limit)
        snapshots: list[dict[str, Any]] = []
        total = 0
        try:
            async with self.uow_factory() as uow:
                items = await uow.permissions.get_user_permissions(
                    user_id=user_id,
                    active_only=True,
                    offset=offset,
                    limit=limit,
                )
                total = await uow.permissions.count_user_permissions(
                    user_id=user_id,
                    active_only=True,
                )
                snapshots = [
                    snapshot
                    for permission in items
                    if (snapshot := _shared_node_snapshot(permission)) is not None
                ]

            dto_items = [
                SharedNodeItem.model_validate(snapshot) for snapshot in snapshots
            ]
            return PageResponse(
                items=dto_items,
                meta=PageMeta(
                    limit=limit,
                    offset=offset,
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

    async def list_nodes_shared_by_me(self, *, user_id: UUID) -> list[UUID]:
        """Возвращает идентификаторы узлов, к которым пользователь выдал доступ.

        Используется фронтендом для бейджа «доступ выдан»: список узлов, на
        которые у пользователя есть активные выданные им гранты. Дубликаты
        (несколько грантов на один узел) схлопываются.

        Args:
            user_id: Идентификатор пользователя, выдавшего доступ.

        Returns:
            Список уникальных идентификаторов узлов с активными грантами.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_nodes_shared_by_me"
        try:
            async with self.uow_factory() as uow:
                # Одним лёгким запросом (DISTINCT node_id), без постраничного
                # обхода и гидрации ORM-объектов на каждый грант.
                node_ids = await uow.permissions.get_distinct_active_granted_node_ids(
                    granted_by=user_id,
                )
            return node_ids

        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def check_permission(
        self,
        data: PermissionCheckRequest,
    ) -> PermissionCheckResponse:
        """Проверяет эффективный доступ к узлу без ошибки при отказе.

        Делегирует проверку AccessService и возвращает структурированный результат,
        показывающий, разрешено ли запрошенное действие.

        Args:
            data: Данные проверки доступа.

        Returns:
            Результат проверки эффективного доступа.
        """

        return await self.access_service.check_node_access(data)

    async def get_effective_permissions(
        self,
        *,
        node_id: UUID,
        user_id: UUID | None,
        allow_deleted: bool = False,
        allow_public: bool = True,
    ) -> EffectivePermissionRead:
        """Возвращает эффективные права пользователя на узел.

        Делегирует вычисление AccessService. Учитываются владелец, публичный доступ,
        явные права и дополнительные правила доступа, реализованные в AccessService.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя. Может быть None для публичного
                доступа.
            allow_deleted: Нужно ли разрешать проверку для удаленных узлов.
            allow_public: Нужно ли учитывать публичный доступ.

        Returns:
            Эффективные флаги доступа пользователя к узлу.
        """

        return await self.access_service.get_effective_permissions(
            node_id=node_id,
            user_id=user_id,
            allow_deleted=allow_deleted,
            allow_public=allow_public,
        )

    async def _safe_log_permission_event(
        self,
        *,
        actor_id: UUID,
        action: AuditAction,
        permission_snapshot: Mapping[str, Any],
        message: str,
    ) -> None:
        """Безопасно записывает событие изменения права в аудит.

        Ошибки записи аудита не пробрасываются выше, чтобы не ломать основную
        операцию управления правами. При ошибке пишет предупреждение в лог.

        Args:
            actor_id: Идентификатор пользователя, выполнившего операцию.
            action: Действие аудита.
            permission_snapshot: Снимок записи NodePermission.
            message: Сообщение события аудита.
        """

        try:
            await self.audit_service.log_event(
                action=action,
                result=AuditResult.SUCCESS,
                user_id=actor_id,
                entity_type=AuditResourceType.PERMISSION.value,
                entity_id=_snapshot_uuid(permission_snapshot, "id"),
                resource_type=AuditResourceType.PERMISSION,
                message=message,
                metadata=_audit_permission(permission_snapshot),
            )
        except ServiceError:
            logger.warning(
                "Не удалось выполнить проверку разрешения на запись",
                extra={
                    "action": action.value,
                    "permission_id": str(permission_snapshot.get("id")),
                },
                exc_info=True,
            )


async def _resolve_permission(*, uow: Any, data: Any) -> NodePermission:
    """Находит запись NodePermission по данным запроса.

    Если в data есть permission_id, ищет право по идентификатору. Иначе ищет
    право по паре node_id/user_id.

    Args:
        uow: Unit of Work с репозиторием прав.
        data: Объект запроса, содержащий permission_id или node_id и user_id.

    Returns:
        Найденная запись NodePermission.

    Raises:
        NotFoundServiceError: Если запись права доступа не найдена.
    """

    permission_id = getattr(data, "permission_id", None)
    if permission_id is not None:
        permission = await uow.permissions.get_permission_by_id(permission_id)
    else:
        node_id = getattr(data, "node_id", None)
        user_id = getattr(data, "user_id", None)
        permission = await uow.permissions.get_by_node_and_user(
            node_id=node_id,
            user_id=user_id,
        )

    if permission is None:
        raise NotFoundServiceError(
            entity_name="NodePermission",
            lookup={
                "permission_id": str(permission_id) if permission_id else None,
                "node_id": str(getattr(data, "node_id", None))
                if getattr(data, "node_id", None)
                else None,
                "user_id": str(getattr(data, "user_id", None))
                if getattr(data, "user_id", None)
                else None,
            },
            details=_error_details("_resolve_permission"),
        )
    return permission


def _apply_permission_update(
    permission: NodePermission,
    data: PermissionUpdateRequest,
) -> None:
    """Применяет изменения к записи NodePermission.

    Обновляет флаги доступа, срок действия и уровень прав. Сбрасывает признаки
    отзыва. Если permission_level не указан явно, синхронизирует его на основе
    флагов доступа. Проверяет, что после обновления разрешено хотя бы одно
    действие.

    Args:
        permission: Изменяемая запись NodePermission.
        data: Данные обновления права доступа.

    Raises:
        ValidationServiceError: Если после обновления не разрешено ни одно
            действие.
    """

    if data.can_read is not None:
        permission.can_read = data.can_read
    if data.can_download is not None:
        permission.can_download = data.can_download
    if data.can_write is not None:
        permission.can_write = data.can_write
    if data.can_delete is not None:
        permission.can_delete = data.can_delete
    if data.can_share is not None:
        permission.can_share = data.can_share
    if "expires_at" in data.model_fields_set:
        permission.expires_at = data.expires_at

    permission.revoked_at = None
    permission.revoke_reason = None

    if data.permission_level is not None:
        permission.permission_level = data.permission_level
    else:
        permission.sync_permission_level_from_flags()

    if not any(
        (
            permission.can_read,
            permission.can_download,
            permission.can_write,
            permission.can_delete,
            permission.can_share,
        )
    ):
        raise ValidationServiceError(
            "Разрешение должно разрешать по крайней мере одно действие.",
            field="permission_flags",
            reason="empty_permission",
            details=_error_details("_apply_permission_update"),
        )


def _permission_snapshot(permission: NodePermission) -> dict[str, Any]:
    """Создает снимок записи NodePermission.

    Args:
        permission: ORM-модель права доступа к узлу.

    Returns:
        Словарь с идентификаторами, типом субъекта, уровнем прав, флагами
        доступа, сроком действия, данными отзыва и временем создания.
    """

    return {
        "id": permission.id,
        "node_id": permission.node_id,
        "user_id": permission.user_id,
        "subject_type": permission.subject_type,
        "permission_level": permission.permission_level,
        "granted_by": permission.granted_by,
        "can_read": bool(permission.can_read),
        "can_download": bool(permission.can_download),
        "can_write": bool(permission.can_write),
        "can_delete": bool(permission.can_delete),
        "can_share": bool(permission.can_share),
        "expires_at": permission.expires_at,
        "revoked_at": permission.revoked_at,
        "revoke_reason": permission.revoke_reason,
        "created_at": permission.created_at,
    }


def _shared_node_snapshot(permission: NodePermission) -> dict[str, Any] | None:
    """Создает снимок узла «Доступно мне» из записи права доступа.

    Объединяет метаданные eager-загруженного узла (и его File) с параметрами
    самой записи права. Возвращает ``None``, если узел не загружен или удалён —
    такие записи в выдаче «Доступно мне» не показываем.

    Args:
        permission: ORM-модель права доступа с загруженными ``node`` (+``file``)
            и ``grantor``.

    Returns:
        Словарь полей ``SharedNodeItem`` либо ``None``, если узел недоступен.
    """

    node = permission.node
    if node is None or bool(node.is_deleted):
        return None

    # Отношение file загружено через selectinload; читаем из __dict__, чтобы не
    # спровоцировать ленивую подгрузку, если по какой-то причине его нет.
    file = node.__dict__.get("file")
    grantor = permission.__dict__.get("grantor")

    return {
        "id": node.id,
        "owner_id": node.owner_id,
        "parent_id": node.parent_id,
        "name": node.name,
        "node_type": node.node_type,
        "visibility": node.visibility,
        "path": node.path,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "file_size_bytes": file.size_bytes if file is not None else None,
        "file_mime_type": file.mime_type if file is not None else None,
        "permission_id": permission.id,
        "permission_level": permission.permission_level,
        "can_read": bool(permission.can_read),
        "can_download": bool(permission.can_download),
        "can_write": bool(permission.can_write),
        "can_delete": bool(permission.can_delete),
        "can_share": bool(permission.can_share),
        "expires_at": permission.expires_at,
        "granted_at": permission.created_at,
        "granted_by": permission.granted_by,
        "granted_by_username": grantor.username if grantor is not None else None,
    }


def _audit_permission(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует JSON-совместимые метаданные права для аудита.

    Args:
        snapshot: Снимок записи NodePermission.

    Returns:
        Словарь с основными полями права доступа, приведенными к
        JSON-совместимым значениям.
    """

    return {
        "permission_id": _jsonable(snapshot.get("id")),
        "node_id": _jsonable(snapshot.get("node_id")),
        "user_id": _jsonable(snapshot.get("user_id")),
        "permission_level": _jsonable(snapshot.get("permission_level")),
        "can_read": _jsonable(snapshot.get("can_read")),
        "can_download": _jsonable(snapshot.get("can_download")),
        "can_write": _jsonable(snapshot.get("can_write")),
        "can_delete": _jsonable(snapshot.get("can_delete")),
        "can_share": _jsonable(snapshot.get("can_share")),
        "expires_at": _jsonable(snapshot.get("expires_at")),
        "revoked_at": _jsonable(snapshot.get("revoked_at")),
        "revoke_reason": _jsonable(snapshot.get("revoke_reason")),
    }


def _snapshot_uuid(snapshot: Mapping[str, Any], field: str) -> UUID | None:
    """Возвращает UUID из снимка по имени поля.

    Args:
        snapshot: Снимок данных.
        field: Имя поля, значение которого нужно получить.

    Returns:
        UUID-значение поля или None, если значение отсутствует либо не является
        UUID.
    """

    value = snapshot.get(field)
    return value if isinstance(value, UUID) else None


def _validate_limit(limit: int) -> int:
    """Проверяет и ограничивает размер страницы.

    Args:
        limit: Запрошенный размер страницы.

    Returns:
        Значение limit, ограниченное MAX_PAGE_LIMIT.

    Raises:
        ValidationServiceError: Если limit меньше 1.
    """

    if limit < 1:
        raise ValidationServiceError(
            "Предел должен быть больше нуля.",
            field="limit",
            value=limit,
            details=_error_details("_validate_limit"),
        )
    return min(limit, MAX_PAGE_LIMIT)


def _empty_result_error(operation: str) -> ServiceError:
    """Создает ошибку отсутствующего снимка результата.

    Args:
        operation: Название операции, завершившейся без снимка результата.

    Returns:
        Ошибка сервиса с описанием отсутствующего результата.
    """

    return ServiceError(
        "Операция завершена, но снимок разрешения создан не был.",
        service=SERVICE_NAME,
        operation=operation,
    )


def _error_details(operation: str) -> dict[str, str]:
    """Формирует стандартные details для сервисных ошибок.

    Args:
        operation: Название операции, в которой возникла ошибка.

    Returns:
        Словарь с именем сервиса и названием операции.
    """

    return {"service": SERVICE_NAME, "operation": operation}


def _jsonable(value: Any) -> Any:
    """Преобразует значение в JSON-совместимый формат.

    Поддерживает примитивы, UUID, datetime и Enum. Для остальных объектов
    возвращает строковое представление.

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
    return str(value)


def get_permissions_service(
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    access_service: AccessService | None = None,
    audit_service: AuditService | None = None,
) -> PermissionsService:
    """Создаёт экземпляр сервиса прав доступа.

    Args:
        uow_factory: Фабрика UnitOfWork. Если не передана, сервис создаст
            стандартную фабрику самостоятельно.
        access_service: Сервис проверки доступа. Если не передан, будет создан
            стандартный сервис доступа.
        audit_service: Сервис аудита. Если не передан, будет создан стандартный
            сервис аудита.

    Returns:
        Экземпляр `PermissionsService`.
    """

    return PermissionsService(
        uow_factory=uow_factory,
        access_service=access_service,
        audit_service=audit_service,
    )
