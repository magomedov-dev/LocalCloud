from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy.exc import InvalidRequestError as _SAInvalidRequestError

from core.config import get_settings
from core.logging import get_logger
from core.preview_mime import preview_required
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    AuditResult,
    BackgroundTaskStatus,
    BackgroundTaskType,
    FilePreviewStatus,
    FileProcessingStatus,
    NodeType,
    NodeVisibility,
    StorageObjectStatus,
)
from database.models.filesystem import FileSystemNode
from database.repositories.nodes import NodeSortDirection, NodeSortField
from schemas.common import PageMeta, PageResponse
from schemas.nodes import (
    NodeBreadcrumbItem,
    NodeCopyRequest,
    NodeCreate,
    NodeListItem,
    NodeMoveRequest,
    NodeOperationResponse,
    NodeQueryParams,
    NodeRead,
    NodeRenameRequest,
    NodeSearchQuery,
    NodeTreeItem,
    NodeUpdate,
)
from security.permissions import PermissionAction
from services.access import AccessService, get_access_service
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    PermissionServiceError,
    QuotaExceededServiceError,
    ServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
)
from storage import StorageService, get_storage_service
from storage.keys import build_file_object_key

logger = get_logger("services.nodes")

SERVICE_NAME = "nodes"
REPOSITORY_PAGE_LIMIT = 1000
ALLOWED_SORT_FIELDS: set[str] = {
    "name",
    "created_at",
    "updated_at",
    "deleted_at",
    "depth",
    "node_type",
}


class NodesService:
    """Сервис бизнес-логики для операций с иерархией файловой системы.

    Управляет общими операциями над FileSystemNode: созданием, чтением,
    поиском, обновлением, перемещением, удалением, восстановлением и построением
    древовидных представлений. Сервис проверяет права доступа, выполняет
    изменения через Unit of Work и записывает события аудита.

    Attributes:
        uow_factory: Фабрика Unit of Work для работы с базой данных.
        access_service: Сервис проверки доступа к узлам файловой системы.
        audit_service: Сервис записи событий аудита.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
        access_service: AccessService | None = None,
        audit_service: AuditService | None = None,
        storage_service: StorageService | None = None,
    ) -> None:
        """Инициализирует сервис узлов файловой системы.

        Если зависимости не переданы явно, создает их через стандартные фабрики
        и функции получения сервисов.

        Args:
            uow_factory: Фабрика Unit of Work. Если None, создается стандартная
                фабрика.
            access_service: Сервис проверки доступа. Если None, создается
                стандартный сервис доступа.
            audit_service: Сервис аудита. Если None, создается стандартный сервис
                аудита.
            storage_service: Сервис объектного хранилища. Если None, создается
                стандартный сервис хранилища.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.access_service = access_service or get_access_service(
            uow_factory=self.uow_factory
        )
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory
        )
        self.storage_service = storage_service or get_storage_service(
            settings=get_settings().storage
        )

    async def create_node(
        self,
        data: NodeCreate,
        *,
        owner_id: UUID,
        actor_id: UUID | None = None,
    ) -> NodeOperationResponse:
        """Создает новый узел файловой системы.

        Если указан parent_id, проверяет право записи к родительскому узлу и
        соответствие владельца. Если parent_id не указан, разрешает создание
        корневого узла только владельцу.

        Args:
            data: Данные для создания узла.
            owner_id: Идентификатор владельца создаваемого узла.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                используется owner_id.

        Returns:
            Ответ операции с созданным узлом и сообщением об успехе.

        Raises:
            PermissionServiceError: Если пользователь не может создать корневой узел
                или не имеет права записи к родительскому узлу.
            ValidationServiceError: Если родительский узел принадлежит другому
                владельцу.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "create_node"
        created_snapshot: dict[str, Any] | None = None
        resolved_actor_id = actor_id or owner_id

        try:
            async with self.uow_factory() as uow:
                if data.parent_id is not None:
                    parent = await self.access_service.get_accessible_node(
                        node_id=data.parent_id,
                        user_id=resolved_actor_id,
                        action=PermissionAction.WRITE,
                        uow=uow,
                    )
                    if parent.owner_id != owner_id:
                        raise ValidationServiceError(
                            "Родительский узел принадлежит другому владельцу.",
                            field="parent_id",
                            value=data.parent_id,
                            reason="owner_mismatch",
                            details={"service": SERVICE_NAME, "operation": operation},
                        )
                elif resolved_actor_id != owner_id:
                    raise PermissionServiceError(
                        "Только владелец может создавать узлы корневого уровня.",
                        user_id=resolved_actor_id,
                        resource_type="filesystem_root",
                        resource_id=owner_id,
                        action=PermissionAction.WRITE,
                        reason="not_owner",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                node = await uow.nodes.create_node(
                    owner_id=owner_id,
                    name=data.name,
                    node_type=data.node_type,
                    parent_id=data.parent_id,
                    visibility=data.visibility,
                    created_by=resolved_actor_id,
                    updated_by=resolved_actor_id,
                    check_owner_exists=True,
                    check_conflict=True,
                    flush=True,
                    refresh=True,
                )
                created_snapshot = _node_snapshot(node)
                await uow.commit()

            if created_snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_node_event(
                user_id=resolved_actor_id,
                action=AuditAction.NODE_CREATED,
                snapshot=created_snapshot,
                message="Узел файловой системы создан.",
            )
            return _operation_response(
                created_snapshot, "Узел файловой системы создан."
            )

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось создать узел файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось создать узел файловой системы.",
            ) from exc

    async def get_node(
        self,
        node_id: UUID,
        *,
        user_id: UUID | None,
        allow_deleted: bool = False,
        allow_public: bool = True,
    ) -> NodeRead:
        """Возвращает узел файловой системы по идентификатору.

        Проверяет доступ пользователя к узлу и возвращает его сериализованное
        представление.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя. Может быть None для публичного
                доступа, если allow_public равен True.
            allow_deleted: Нужно ли разрешать получение удаленного узла.
            allow_public: Нужно ли разрешать доступ к публичным узлам.

        Returns:
            Данные найденного узла.

        Raises:
            PermissionServiceError: Если у пользователя нет доступа к узлу.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "get_node"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=user_id,
                    action=PermissionAction.READ,
                    allow_deleted=allow_deleted,
                    allow_public=allow_public,
                    uow=uow,
                )
                snapshot = _node_snapshot(node)

            if snapshot is None:
                raise _empty_result_error(operation)
            return NodeRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось загрузить узел файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось загрузить узел файловой системы.",
            ) from exc

    async def list_nodes(
        self,
        params: NodeQueryParams,
        *,
        user_id: UUID | None,
    ) -> PageResponse[NodeListItem]:
        """Возвращает список узлов файловой системы.

        Загружает корневые узлы владельца или дочерние узлы указанного parent_id.
        После загрузки дополнительно фильтрует результат по параметрам запроса
        и формирует страницу ответа.

        Args:
            params: Параметры списка, включая владельца, родителя, тип узла,
                сортировку, пагинацию и фильтры.
            user_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Страница узлов и метаданные пагинации.

        Raises:
            PermissionServiceError: Если пользователь не может просматривать
                корневые узлы указанного владельца или запрос выполняется без
                аутентифицированного владельца.
            ValidationServiceError: Если владелец не совпадает с владельцем
                родительского узла или поле сортировки не поддерживается.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_nodes"
        page: PageResponse[NodeListItem] | None = None

        try:
            async with self.uow_factory() as uow:
                owner_id = params.owner_id or user_id
                parent_id = params.parent_id

                if parent_id is not None:
                    parent = await self.access_service.get_accessible_node(
                        node_id=parent_id,
                        user_id=user_id,
                        action=PermissionAction.READ,
                        allow_deleted=params.is_deleted is not False,
                        uow=uow,
                    )
                    if owner_id is None:
                        owner_id = parent.owner_id
                    elif owner_id != parent.owner_id:
                        raise ValidationServiceError(
                            "Фильтр владельца не соответствует родительскому владельцу.",
                            field="owner_id",
                            value=owner_id,
                            reason="owner_parent_mismatch",
                            details={"service": SERVICE_NAME, "operation": operation},
                        )
                elif owner_id is None:
                    raise PermissionServiceError(
                        "Для регистрации на корневом уровне требуется аутентифицированный владелец.",
                        action=PermissionAction.READ,
                        reason="anonymous_user",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                elif user_id != owner_id:
                    raise PermissionServiceError(
                        "Список на корневом уровне доступен только владельцу.",
                        user_id=user_id,
                        resource_type="filesystem_root",
                        resource_id=owner_id,
                        action=PermissionAction.READ,
                        reason="not_owner",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                if _can_paginate_list_in_sql(params):
                    # Быстрый путь: один постраничный запрос + один счетчик, без загрузки - все.
                    include_deleted = params.is_deleted is not False
                    sort_by = _normalize_sort_by(params.sort_by)
                    sort_direction = _sort_direction(params.sort_desc)
                    if params.parent_id is None:
                        chunk = await uow.nodes.get_root_nodes(
                            owner_id=cast(UUID, owner_id),
                            include_deleted=include_deleted,
                            node_type=params.node_type,
                            offset=params.offset,
                            limit=params.limit,
                            sort_by=sort_by,
                            sort_direction=sort_direction,
                        )
                        total = await uow.nodes.count_root_nodes(
                            owner_id=cast(UUID, owner_id),
                            include_deleted=include_deleted,
                            node_type=params.node_type,
                        )
                    else:
                        chunk = await uow.nodes.get_children(
                            parent_id=params.parent_id,
                            include_deleted=include_deleted,
                            node_type=params.node_type,
                            offset=params.offset,
                            limit=params.limit,
                            sort_by=sort_by,
                            sort_direction=sort_direction,
                        )
                        total = await uow.nodes.count_children(
                            parent_id=params.parent_id,
                            include_deleted=include_deleted,
                            node_type=params.node_type,
                        )
                    items = [
                        NodeListItem.model_validate(_node_snapshot(node))
                        for node in chunk
                    ]
                    page = PageResponse(
                        items=items,
                        meta=PageMeta(
                            limit=params.limit,
                            offset=params.offset,
                            total=total,
                            count=len(items),
                        ),
                    )
                else:
                    # Медленный путь: фильтры, применяемые в Python, требуют загрузки
                    # полного уровня, затем filter + slice.
                    nodes = await self._load_list_nodes(
                        uow=uow, params=params, owner_id=owner_id
                    )
                    filtered_nodes = _filter_query_nodes(nodes, params)
                    page = _nodes_page(
                        filtered_nodes,
                        limit=params.limit,
                        offset=params.offset,
                    )

            if page is None:
                raise _empty_result_error(operation)
            return page

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось вывести список узлов файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось вывести список узлов файловой системы.",
            ) from exc

    async def search_nodes(
        self,
        params: NodeSearchQuery,
        *,
        user_id: UUID | None,
    ) -> PageResponse[NodeListItem]:
        """Ищет узлы файловой системы.

        Выполняет поиск по параметрам запроса в пределах владельца или родительского
        узла. Для поиска в корневой иерархии требует, чтобы пользователь искал
        только собственные узлы.

        Args:
            params: Параметры поиска, включая строку запроса, владельца, родителя,
                тип узла, видимость, сортировку, пагинацию и флаг удаленных узлов.
            user_id: Идентификатор пользователя, выполняющего поиск.

        Returns:
            Страница найденных узлов и метаданные пагинации.

        Raises:
            PermissionServiceError: Если поиск выполняется без владельца или
                пользователь пытается искать чужую корневую иерархию.
            ValidationServiceError: Если владелец не совпадает с владельцем
                родительского узла или поле сортировки не поддерживается.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "search_nodes"
        page: PageResponse[NodeListItem] | None = None

        try:
            async with self.uow_factory() as uow:
                owner_id = params.owner_id or user_id

                if params.parent_id is not None:
                    parent = await self.access_service.get_accessible_node(
                        node_id=params.parent_id,
                        user_id=user_id,
                        action=PermissionAction.READ,
                        allow_deleted=params.include_deleted,
                        uow=uow,
                    )
                    if owner_id is None:
                        owner_id = parent.owner_id
                    elif owner_id != parent.owner_id:
                        raise ValidationServiceError(
                            "Фильтр владельца не соответствует родительскому владельцу.",
                            field="owner_id",
                            value=owner_id,
                            reason="owner_parent_mismatch",
                            details={"service": SERVICE_NAME, "operation": operation},
                        )
                elif owner_id is None:
                    raise PermissionServiceError(
                        "Для поиска требуется аутентифицированный владелец или родительский узел.",
                        action=PermissionAction.READ,
                        reason="anonymous_user",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                elif user_id != owner_id:
                    raise PermissionServiceError(
                        "Пользователь может выполнять поиск только в собственной корневой иерархии без родительского узла.",
                        user_id=user_id,
                        resource_type="filesystem_root",
                        resource_id=owner_id,
                        action=PermissionAction.READ,
                        reason="not_owner",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                nodes = await self._load_search_nodes(
                    uow=uow,
                    params=params,
                    owner_id=owner_id,
                )
                filtered_nodes = _filter_search_nodes(nodes, params)
                page = _nodes_page(
                    filtered_nodes,
                    limit=params.limit,
                    offset=params.offset,
                )

            if page is None:
                raise _empty_result_error(operation)
            return page

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось выполнить поиск в узлах файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось выполнить поиск в узлах файловой системы.",
            ) from exc

    async def update_node(
        self,
        node_id: UUID,
        data: NodeUpdate,
        *,
        actor_id: UUID,
        recursive_visibility: bool = False,
    ) -> NodeOperationResponse:
        """Обновляет узел файловой системы.

        Может переименовать узел, переместить его в другого родителя и изменить
        видимость. Для изменения имени и родителя проверяет право записи, а для
        изменения видимости — право управления доступом.

        Args:
            node_id: Идентификатор обновляемого узла.
            data: Данные обновления узла.
            actor_id: Идентификатор пользователя, выполняющего обновление.
            recursive_visibility: Нужно ли применять изменение видимости
                рекурсивно к потомкам.

        Returns:
            Ответ операции с обновленным узлом и сообщением об успехе.

        Raises:
            PermissionServiceError: Если у пользователя нет нужного права доступа.
            ValidationServiceError: Если поле сортировки или данные операции
                некорректны на уровне нижележащих сервисов или репозиториев.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "update_node"
        snapshot: dict[str, Any] | None = None
        audit_action = AuditAction.NODE_MOVED

        try:
            async with self.uow_factory() as uow:
                await self.access_service.require_access(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.WRITE,
                    uow=uow,
                )

                node = await uow.nodes.get_required_by_id(node_id)
                if data.name is not None:
                    node = await uow.nodes.rename_node(
                        node_id=node.id,
                        new_name=data.name,
                        updated_by=actor_id,
                        flush=True,
                        refresh=False,
                    )
                    audit_action = AuditAction.NODE_RENAMED

                if "parent_id" in data.model_fields_set:
                    if data.parent_id is not None:
                        await self.access_service.require_access(
                            node_id=data.parent_id,
                            user_id=actor_id,
                            action=PermissionAction.WRITE,
                            uow=uow,
                        )
                    node = await uow.nodes.move_node(
                        node_id=node.id,
                        new_parent_id=data.parent_id,
                        updated_by=actor_id,
                        flush=True,
                        refresh=False,
                    )
                    audit_action = AuditAction.NODE_MOVED

                if data.visibility is not None:
                    await self.access_service.require_access(
                        node_id=node.id,
                        user_id=actor_id,
                        action=PermissionAction.SHARE,
                        uow=uow,
                    )
                    node = await uow.nodes.update_visibility(
                        node_id=node.id,
                        visibility=data.visibility,
                        recursive=recursive_visibility,
                        updated_by=actor_id,
                        flush=True,
                        refresh=False,
                    )
                    if audit_action == AuditAction.NODE_MOVED:
                        audit_action = AuditAction.NODE_UPDATED

                node = await uow.nodes.get_required_by_id(node_id)
                snapshot = _node_snapshot(node)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_node_event(
                user_id=actor_id,
                action=audit_action,
                snapshot=snapshot,
                message="Узел файловой системы обновлен.",
            )
            return _operation_response(snapshot, "Узел файловой системы обновлен.")

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось обновить узел файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось обновить узел файловой системы.",
            ) from exc

    async def rename_node(
        self,
        node_id: UUID,
        data: NodeRenameRequest,
        *,
        actor_id: UUID,
    ) -> NodeOperationResponse:
        """Переименовывает узел файловой системы.

        Выполняет общую мутацию узла через _mutate_node, проверяя право записи
        и записывая событие аудита после успешного переименования.

        Args:
            node_id: Идентификатор переименовываемого узла.
            data: Данные с новым именем узла.
            actor_id: Идентификатор пользователя, выполняющего переименование.

        Returns:
            Ответ операции с переименованным узлом.

        Raises:
            PermissionServiceError: Если у пользователя нет права записи.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        return await self._mutate_node(
            node_id=node_id,
            actor_id=actor_id,
            access_action=PermissionAction.WRITE,
            audit_action=AuditAction.NODE_RENAMED,
            message="Узел файловой системы переименован.",
            mutate=lambda uow: uow.nodes.rename_node(
                node_id=node_id,
                new_name=data.name,
                updated_by=actor_id,
                flush=True,
                refresh=True,
            ),
            operation="rename_node",
        )

    async def move_node(
        self,
        node_id: UUID,
        data: NodeMoveRequest,
        *,
        actor_id: UUID,
    ) -> NodeOperationResponse:
        """Перемещает узел файловой системы.

        Проверяет право записи к перемещаемому узлу. Если указан целевой родитель,
        дополнительно проверяет право записи к целевому родительскому узлу.

        Args:
            node_id: Идентификатор перемещаемого узла.
            data: Данные перемещения с целевым родительским узлом.
            actor_id: Идентификатор пользователя, выполняющего перемещение.

        Returns:
            Ответ операции с перемещенным узлом.

        Raises:
            PermissionServiceError: Если у пользователя нет права записи к узлу
                или целевому родителю.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "move_node"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                await self.access_service.require_access(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.WRITE,
                    uow=uow,
                )
                if data.target_parent_id is not None:
                    await self.access_service.require_access(
                        node_id=data.target_parent_id,
                        user_id=actor_id,
                        action=PermissionAction.WRITE,
                        uow=uow,
                    )

                node = await uow.nodes.move_node(
                    node_id=node_id,
                    new_parent_id=data.target_parent_id,
                    updated_by=actor_id,
                    flush=True,
                    refresh=True,
                )
                snapshot = _node_snapshot(node)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_node_event(
                user_id=actor_id,
                action=AuditAction.NODE_MOVED,
                snapshot=snapshot,
                message="Узел файловой системы перемещен.",
            )
            return _operation_response(snapshot, "Узел файловой системы перемещен.")

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось переместить узел файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось переместить узел файловой системы.",
            ) from exc

    async def copy_node(
        self,
        node_id: UUID,
        data: NodeCopyRequest,
        *,
        actor_id: UUID,
    ) -> NodeOperationResponse:
        """Копирует (дублирует) узел файловой системы.

        Создаёт независимую копию файла или папки. Для папки копирование
        выполняется рекурсивно: создаётся новая иерархия узлов, а для каждого
        файла содержимое физически копируется в объектном хранилище под новым
        ключом. Перед копированием проверяется доступ к исходному узлу и целевой
        папке, а также квоты пользователя по объёму и количеству файлов.

        Args:
            node_id: Идентификатор копируемого узла.
            data: Данные копирования с целевой папкой и необязательным новым
                именем.
            actor_id: Идентификатор пользователя, выполняющего копирование.

        Returns:
            Ответ операции с корневым узлом созданной копии.

        Raises:
            PermissionServiceError: Если у пользователя нет права чтения исходного
                узла или права записи в целевую папку.
            QuotaExceededServiceError: Если копирование превышает квоту по объёму
                хранилища или количеству файлов.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "copy_node"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                await self.access_service.require_access(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.READ,
                    uow=uow,
                )
                if data.target_parent_id is not None:
                    await self.access_service.require_access(
                        node_id=data.target_parent_id,
                        user_id=actor_id,
                        action=PermissionAction.WRITE,
                        uow=uow,
                    )

                nodes = await uow.nodes.get_descendants(
                    node_id=node_id,
                    include_self=True,
                    include_deleted=False,
                    order_by_depth=True,
                )
                if not nodes:
                    raise _empty_result_error(operation)
                root = nodes[0]

                file_rows: dict[UUID, Any] = {}
                total_bytes = 0
                file_count = 0
                for current in nodes:
                    if current.node_type == NodeType.FILE:
                        file = await uow.files.get_required_by_node_id(current.id)
                        file_rows[current.id] = file
                        total_bytes += file.size_bytes or 0
                        file_count += 1

                quota = await uow.quotas.get_required_by_user_id(actor_id)
                files_over_limit = (
                    quota.files_limit is not None
                    and quota.files_used + file_count > quota.files_limit
                )
                if quota.available_storage_bytes < total_bytes or files_over_limit:
                    raise QuotaExceededServiceError(
                        "Копирование превышает доступную квоту пользователя.",
                        user_id=actor_id,
                        requested=total_bytes,
                        used=quota.storage_used_bytes,
                        limit=quota.storage_limit_bytes,
                        available=quota.available_storage_bytes,
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                existing_children = await uow.nodes.get_children(
                    parent_id=data.target_parent_id,
                    include_deleted=False,
                    limit=REPOSITORY_PAGE_LIMIT,
                ) if data.target_parent_id is not None else await uow.nodes.get_root_nodes(
                    owner_id=actor_id,
                    include_deleted=False,
                    limit=REPOSITORY_PAGE_LIMIT,
                )
                existing_names = {child.name for child in existing_children}
                desired_name = data.new_name or root.name
                new_root_name = _unique_copy_name(
                    existing_names,
                    desired_name,
                    is_file=root.node_type == NodeType.FILE,
                )

                id_map: dict[UUID, UUID] = {}
                copied: list[tuple[str, str]] = []
                try:
                    for current in nodes:
                        if current.id == root.id:
                            new_parent = data.target_parent_id
                            name = new_root_name
                        else:
                            new_parent = id_map[current.parent_id]
                            name = current.name

                        if current.node_type == NodeType.FOLDER:
                            # Создаём узел И запись `folders` (иначе загрузка
                            # содержимого скопированной папки падает с
                            # EntityNotFoundError). Заодно переносим описание и
                            # цвет исходной папки.
                            src_folder = await uow.folders.get_required_by_node_id(
                                current.id,
                            )
                            new_folder = await uow.folders.create_folder(
                                owner_id=actor_id,
                                name=name,
                                parent_id=new_parent,
                                description=src_folder.description,
                                color=src_folder.color,
                                created_by=actor_id,
                                check_conflict=False,
                                check_owner_exists=False,
                                flush=True,
                                refresh=True,
                            )
                            id_map[current.id] = new_folder.node_id
                            continue

                        src = file_rows[current.id]
                        new_key = build_file_object_key(
                            user_id=actor_id,
                            file_id=uuid4(),
                            version_id=uuid4(),
                        )
                        await self.storage_service.copy_file_object(
                            source_object_key=src.storage_key,
                            destination_object_key=new_key,
                            source_bucket=src.storage_bucket,
                            destination_bucket=src.storage_bucket,
                        )
                        copied.append((src.storage_bucket, new_key))
                        preview_status = (
                            FilePreviewStatus.PENDING
                            if preview_required(src.mime_type)
                            else FilePreviewStatus.NOT_REQUIRED
                        )
                        new_file = await uow.files.create_file_with_node(
                            owner_id=actor_id,
                            parent_id=new_parent,
                            name=name,
                            storage_bucket=src.storage_bucket,
                            storage_key=new_key,
                            size_bytes=src.size_bytes,
                            mime_type=src.mime_type,
                            extension=src.extension,
                            checksum=src.checksum,
                            checksum_algorithm=src.checksum_algorithm,
                            storage_status=StorageObjectStatus.AVAILABLE,
                            processing_status=FileProcessingStatus.READY,
                            preview_status=preview_status,
                            created_by=actor_id,
                            check_owner_exists=False,
                            check_conflict=False,
                            flush=True,
                            refresh=True,
                        )
                        if preview_status == FilePreviewStatus.PENDING:
                            preview_task = await uow.tasks.create_task(
                                task_type=BackgroundTaskType.GENERATE_FILE_PREVIEW,
                                created_by=actor_id,
                                related_entity_type="file",
                                related_entity_id=new_file.id,
                                status=BackgroundTaskStatus.PENDING,
                                flush=True,
                                refresh=False,
                            )
                            preview_task.payload = {"file_id": str(new_file.id)}
                        id_map[current.id] = new_file.node_id
                except Exception:
                    for bucket, object_key in copied:
                        await self._delete_copied_object_safely(
                            bucket=bucket,
                            object_key=object_key,
                        )
                    raise

                if file_count:
                    await uow.quotas.increase_used_space(
                        user_id=actor_id,
                        size_bytes=total_bytes,
                        flush=True,
                    )
                    await uow.quotas.increase_files_used(
                        user_id=actor_id,
                        count=file_count,
                        flush=True,
                    )

                new_root_node = await uow.nodes.get_required_by_id(id_map[root.id])
                snapshot = _node_snapshot(new_root_node)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_node_event(
                user_id=actor_id,
                action=AuditAction.NODE_CREATED,
                snapshot=snapshot,
                message="Узел файловой системы скопирован.",
            )
            return _operation_response(snapshot, "Узел файловой системы скопирован.")

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось скопировать узел файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось скопировать узел файловой системы.",
            ) from exc

    async def _delete_copied_object_safely(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> None:
        """Безопасно удаляет скопированный объект при откате копирования.

        Используется для best-effort очистки объектов, уже скопированных в
        хранилище, когда копирование завершилось ошибкой. Ошибки удаления не
        пробрасываются выше и только логируются.

        Args:
            bucket: Bucket объектного хранилища.
            object_key: Ключ скопированного объекта.
        """

        try:
            await self.storage_service.delete_file_object(
                bucket=bucket,
                object_key=object_key,
                missing_ok=True,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось удалить скопированный объект при откате копирования.",
                extra={
                    "service": SERVICE_NAME,
                    "bucket": bucket,
                    "object_key": object_key,
                    "error_type": exc.__class__.__name__,
                },
            )

    async def update_visibility(
        self,
        node_id: UUID,
        visibility: NodeVisibility,
        *,
        actor_id: UUID,
        recursive: bool = False,
    ) -> NodeOperationResponse:
        """Обновляет видимость узла файловой системы.

        Проверяет право управления доступом и применяет новую видимость к узлу.
        При recursive=True изменение также применяется к дочерним узлам.

        Args:
            node_id: Идентификатор узла.
            visibility: Новое значение видимости.
            actor_id: Идентификатор пользователя, выполняющего операцию.
            recursive: Нужно ли применять изменение рекурсивно.

        Returns:
            Ответ операции с обновленным узлом.

        Raises:
            PermissionServiceError: Если у пользователя нет права SHARE.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        return await self._mutate_node(
            node_id=node_id,
            actor_id=actor_id,
            access_action=PermissionAction.SHARE,
            audit_action=AuditAction.NODE_UPDATED,
            message="Обновлена видимость узла файловой системы.",
            mutate=lambda uow: uow.nodes.update_visibility(
                node_id=node_id,
                visibility=visibility,
                recursive=recursive,
                updated_by=actor_id,
                flush=True,
                refresh=True,
            ),
            operation="update_visibility",
        )

    async def delete_node(
        self,
        node_id: UUID,
        *,
        actor_id: UUID,
        recursive: bool = True,
    ) -> NodeOperationResponse:
        """Мягко удаляет узел файловой системы.

        Перемещает узел в корзину. При recursive=True удаление применяется
        рекурсивно к дочерним узлам.

        Args:
            node_id: Идентификатор удаляемого узла.
            actor_id: Идентификатор пользователя, выполняющего удаление.
            recursive: Нужно ли удалять дочерние узлы рекурсивно.

        Returns:
            Ответ операции с удаленным узлом.

        Raises:
            PermissionServiceError: Если у пользователя нет права удаления.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        async def move_to_trash(uow: Any) -> FileSystemNode:
            await uow.trash.create_trash_item(
                node_id=node_id,
                deleted_by=actor_id,
                soft_delete_node=True,
                recursive_soft_delete=recursive,
                flush=True,
            )
            node = await uow.nodes.get_required_by_id(node_id)
            await uow.nodes.refresh(node)
            return node

        return await self._mutate_node(
            node_id=node_id,
            actor_id=actor_id,
            access_action=PermissionAction.DELETE,
            audit_action=AuditAction.NODE_DELETED,
            message="Узел файловой системы перемещен в корзину.",
            mutate=move_to_trash,
            operation="delete_node",
        )

    async def restore_node(
        self,
        node_id: UUID,
        *,
        actor_id: UUID,
        recursive: bool = True,
    ) -> NodeOperationResponse:
        """Восстанавливает мягко удаленный узел файловой системы.

        Восстанавливает удаленный узел. При recursive=True восстановление применяется
        рекурсивно к дочерним узлам.

        Args:
            node_id: Идентификатор восстанавливаемого узла.
            actor_id: Идентификатор пользователя, выполняющего восстановление.
            recursive: Нужно ли восстанавливать дочерние узлы рекурсивно.

        Returns:
            Ответ операции с восстановленным узлом.

        Raises:
            PermissionServiceError: Если у пользователя нет нужного права доступа.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        return await self._mutate_node(
            node_id=node_id,
            actor_id=actor_id,
            access_action=PermissionAction.DELETE,
            audit_action=AuditAction.NODE_RESTORED,
            message="Узел файловой системы восстановлен.",
            allow_deleted=True,
            mutate=lambda uow: uow.nodes.restore_node(
                node_id=node_id,
                updated_by=actor_id,
                recursive=recursive,
                flush=True,
                refresh=True,
            ),
            operation="restore_node",
        )

    async def purge_node(
        self, node_id: UUID, *, actor_id: UUID
    ) -> NodeOperationResponse:
        """Окончательно удаляет узел файловой системы.

        Проверяет право управления узлом, сохраняет снимок для аудита, помечает
        узел как окончательно удаленный и возвращает успешный ответ без данных узла.

        Args:
            node_id: Идентификатор окончательно удаляемого узла.
            actor_id: Идентификатор пользователя, выполняющего окончательное
                удаление.

        Returns:
            Ответ операции с success=True, node=None и сообщением об удалении.

        Raises:
            PermissionServiceError: Если у пользователя нет права управления.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "purge_node"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                await self.access_service.require_access(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.MANAGE,
                    allow_deleted=True,
                    uow=uow,
                )
                node = await uow.nodes.get_required_by_id(node_id)
                snapshot = _node_snapshot(node)
                await uow.nodes.mark_purged(node_id=node_id, flush=True)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_node_event(
                user_id=actor_id,
                action=AuditAction.NODE_PURGED,
                snapshot=snapshot,
                message="Узел файловой системы удален безвозвратно.",
            )
            return NodeOperationResponse(
                success=True,
                node=None,
                message="Узел файловой системы удален безвозвратно.",
            )

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось очистить узел файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось очистить узел файловой системы.",
            ) from exc

    async def get_breadcrumbs(
        self,
        node_id: UUID,
        *,
        user_id: UUID | None,
        allow_deleted: bool = False,
    ) -> list[NodeBreadcrumbItem]:
        """Возвращает хлебные крошки для узла файловой системы.

        Проверяет право чтения к узлу и загружает цепочку предков, включая сам узел.

        Args:
            node_id: Идентификатор узла, для которого строятся хлебные крошки.
            user_id: Идентификатор пользователя, выполняющего запрос.
            allow_deleted: Нужно ли разрешать построение хлебных крошек для
                удаленного узла.

        Returns:
            Список элементов хлебных крошек от корня до указанного узла.

        Raises:
            PermissionServiceError: Если у пользователя нет права чтения.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "get_breadcrumbs"
        breadcrumbs: list[NodeBreadcrumbItem] | None = None

        try:
            async with self.uow_factory() as uow:
                await self.access_service.require_access(
                    node_id=node_id,
                    user_id=user_id,
                    action=PermissionAction.READ,
                    allow_deleted=allow_deleted,
                    uow=uow,
                )
                nodes = await uow.nodes.get_breadcrumbs(
                    node_id=node_id,
                    include_self=True,
                    include_deleted=allow_deleted,
                )
                breadcrumbs = [
                    NodeBreadcrumbItem.model_validate(_breadcrumb_snapshot(node))
                    for node in nodes
                ]

            if breadcrumbs is None:
                raise _empty_result_error(operation)
            return breadcrumbs

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось собрать хлебные крошки."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось собрать хлебные крошки."
            ) from exc

    async def get_tree(
        self,
        root_node_id: UUID,
        *,
        user_id: UUID | None,
        include_deleted: bool = False,
    ) -> NodeTreeItem:
        """Возвращает дерево узлов от указанного корня.

        Проверяет право чтения к корневому узлу, загружает всех потомков вместе
        с корнем и строит вложенное дерево NodeTreeItem.

        Args:
            root_node_id: Идентификатор корневого узла дерева.
            user_id: Идентификатор пользователя, выполняющего запрос.
            include_deleted: Нужно ли включать удаленные узлы.

        Returns:
            Дерево файловой системы, начинающееся с root_node_id.

        Raises:
            PermissionServiceError: Если у пользователя нет права чтения.
            ServiceError: Если корневой узел отсутствует в результате потомков,
                произошла ошибка базы данных или непредвиденная ошибка сервиса.
        """

        operation = "get_tree"
        tree: NodeTreeItem | None = None

        try:
            async with self.uow_factory() as uow:
                await self.access_service.require_access(
                    node_id=root_node_id,
                    user_id=user_id,
                    action=PermissionAction.READ,
                    allow_deleted=include_deleted,
                    uow=uow,
                )
                nodes = await uow.nodes.get_descendants(
                    node_id=root_node_id,
                    include_self=True,
                    include_deleted=include_deleted,
                    order_by_depth=True,
                )
                tree = _build_tree(nodes, root_node_id=root_node_id)

            if tree is None:
                raise _empty_result_error(operation)
            return tree

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось построить дерево файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось построить дерево файловой системы.",
            ) from exc

    async def count_user_nodes(
        self,
        *,
        owner_id: UUID,
        user_id: UUID,
        include_deleted: bool = False,
    ) -> dict[NodeType | str, int]:
        """Возвращает количество узлов пользователя.

        Считает общее количество узлов, количество файлов и количество папок.
        Разрешает подсчет только для собственного owner_id пользователя.

        Args:
            owner_id: Идентификатор владельца узлов.
            user_id: Идентификатор пользователя, выполняющего запрос.
            include_deleted: Нужно ли учитывать удаленные узлы.

        Returns:
            Словарь с количеством всех узлов, файлов и папок.

        Raises:
            PermissionServiceError: Если пользователь пытается считать узлы другого
                владельца.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "count_user_nodes"
        counts: dict[NodeType | str, int] | None = None

        try:
            if owner_id != user_id:
                raise PermissionServiceError(
                    "Пользователь может подсчитывать только собственные узлы файловой системы.",
                    user_id=user_id,
                    resource_type="filesystem_root",
                    resource_id=owner_id,
                    action=PermissionAction.READ,
                    reason="not_owner",
                    details={"service": SERVICE_NAME, "operation": operation},
                )

            async with self.uow_factory() as uow:
                counts = {
                    "total": await uow.nodes.count_user_nodes(
                        owner_id=owner_id,
                        include_deleted=include_deleted,
                    ),
                    NodeType.FILE: await uow.nodes.count_user_files(
                        owner_id=owner_id,
                        include_deleted=include_deleted,
                    ),
                    NodeType.FOLDER: await uow.nodes.count_user_folders(
                        owner_id=owner_id,
                        include_deleted=include_deleted,
                    ),
                }

            if counts is None:
                raise _empty_result_error(operation)
            return counts

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось подсчитать узлы файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось подсчитать узлы файловой системы.",
            ) from exc

    async def _mutate_node(
        self,
        *,
        node_id: UUID,
        actor_id: UUID,
        access_action: PermissionAction,
        audit_action: AuditAction,
        message: str,
        mutate: Any,
        operation: str,
        allow_deleted: bool = False,
    ) -> NodeOperationResponse:
        """Выполняет общую мутацию узла файловой системы.

        Используется для операций с одинаковым шаблоном: проверка доступа,
        выполнение функции изменения, commit, запись аудита и формирование ответа.

        Args:
            node_id: Идентификатор изменяемого узла.
            actor_id: Идентификатор пользователя, выполняющего операцию.
            access_action: Действие доступа, которое нужно проверить.
            audit_action: Действие аудита для записи после успешной операции.
            message: Сообщение операции и текст ошибки.
            mutate: Асинхронная функция изменения, принимающая Unit of Work.
            operation: Название операции для контекста ошибок.
            allow_deleted: Нужно ли разрешать доступ к удаленному узлу.

        Returns:
            Ответ операции с измененным узлом.

        Raises:
            PermissionServiceError: Если у пользователя нет нужного права доступа.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                await self.access_service.require_access(
                    node_id=node_id,
                    user_id=actor_id,
                    action=access_action,
                    allow_deleted=allow_deleted,
                    uow=uow,
                )
                node = await mutate(uow)
                snapshot = _node_snapshot(node)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_node_event(
                user_id=actor_id,
                action=audit_action,
                snapshot=snapshot,
                message=message,
            )
            return _operation_response(snapshot, message)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message=message
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message=message
            ) from exc

    async def _load_list_nodes(
        self,
        *,
        uow: Any,
        params: NodeQueryParams,
        owner_id: UUID,
    ) -> list[FileSystemNode]:
        """Загружает узлы для операции списка батчами.

        В зависимости от params.parent_id загружает либо корневые узлы владельца,
        либо дочерние узлы указанного родителя. Читает данные страницами до тех пор,
        пока очередной батч не станет меньше REPOSITORY_PAGE_LIMIT.

        Args:
            uow: Unit of Work с репозиторием узлов.
            params: Параметры списка узлов.
            owner_id: Идентификатор владельца узлов.

        Returns:
            Полный список загруженных узлов.

        Raises:
            ValidationServiceError: Если поле сортировки не поддерживается.
        """

        sort_by = _normalize_sort_by(params.sort_by)
        sort_direction = _sort_direction(params.sort_desc)
        include_deleted = params.is_deleted is not False
        nodes: list[FileSystemNode] = []
        offset = 0

        while True:
            if params.parent_id is None:
                chunk = await uow.nodes.get_root_nodes(
                    owner_id=owner_id,
                    include_deleted=include_deleted,
                    node_type=params.node_type,
                    offset=offset,
                    limit=REPOSITORY_PAGE_LIMIT,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                )
            else:
                chunk = await uow.nodes.get_children(
                    parent_id=params.parent_id,
                    include_deleted=include_deleted,
                    node_type=params.node_type,
                    offset=offset,
                    limit=REPOSITORY_PAGE_LIMIT,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                )

            nodes.extend(chunk)
            if len(chunk) < REPOSITORY_PAGE_LIMIT:
                return nodes
            offset += REPOSITORY_PAGE_LIMIT

    async def _load_search_nodes(
        self,
        *,
        uow: Any,
        params: NodeSearchQuery,
        owner_id: UUID,
    ) -> list[FileSystemNode]:
        """Загружает результаты поиска узлов батчами.

        Последовательно запрашивает страницы результатов поиска из репозитория,
        пока очередной батч не станет меньше REPOSITORY_PAGE_LIMIT.

        Args:
            uow: Unit of Work с репозиторием узлов.
            params: Параметры поиска узлов.
            owner_id: Идентификатор владельца узлов.

        Returns:
            Полный список найденных узлов.

        Raises:
            ValidationServiceError: Если поле сортировки не поддерживается.
        """

        sort_by = _normalize_sort_by(params.sort_by)
        sort_direction = _sort_direction(params.sort_desc)
        nodes: list[FileSystemNode] = []
        offset = 0

        while True:
            chunk = await uow.nodes.search_nodes(
                owner_id=owner_id,
                query=params.query,
                parent_id=params.parent_id,
                node_type=params.node_type,
                include_deleted=params.include_deleted,
                offset=offset,
                limit=REPOSITORY_PAGE_LIMIT,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
            nodes.extend(chunk)
            if len(chunk) < REPOSITORY_PAGE_LIMIT:
                return nodes
            offset += REPOSITORY_PAGE_LIMIT

    async def _safe_log_node_event(
        self,
        *,
        user_id: UUID,
        action: AuditAction,
        snapshot: dict[str, Any],
        message: str,
    ) -> None:
        """Безопасно записывает событие узла в аудит.

        Ошибки записи аудита не пробрасываются выше, чтобы не ломать основную
        операцию с узлом. При ошибке пишет предупреждение в лог.

        Args:
            user_id: Идентификатор пользователя, связанного с событием.
            action: Действие аудита.
            snapshot: Снимок узла, на основе которого формируются метаданные.
            message: Сообщение события аудита.
        """

        try:
            await self.audit_service.log_user_event(
                user_id=user_id,
                action=action,
                result=AuditResult.SUCCESS,
                entity_type="filesystem_node",
                entity_id=cast(UUID, snapshot["id"]),
                resource_type=AuditResourceType.NODE,
                message=message,
                metadata=_audit_metadata(snapshot),
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита узла",
                extra={
                    "action": action.value,
                    "node_id": str(snapshot.get("id")),
                    "error_type": exc.__class__.__name__,
                },
            )

    @staticmethod
    def _database_error(
        exc: DatabaseError,
        *,
        operation: str,
        message: str,
    ) -> ServiceError:
        """Преобразует ошибку базы данных в ошибку сервиса узлов.

        Args:
            exc: Исходная ошибка базы данных.
            operation: Название операции, во время которой возникла ошибка.
            message: Сообщение для создаваемой ошибки сервиса.

        Returns:
            Ошибка сервисного уровня с контекстом сервиса узлов.
        """

        return service_error_from_database(
            exc,
            operation=operation,
            message=message,
            service=SERVICE_NAME,
        )

    @staticmethod
    def _unexpected_error(
        exc: Exception,
        *,
        operation: str,
        message: str,
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
            exc,
            operation=operation,
            message=message,
            service=SERVICE_NAME,
        )


def _node_snapshot(node: FileSystemNode) -> dict[str, Any]:
    """Создает снимок метаданных узла файловой системы.

    Args:
        node: ORM-модель узла файловой системы.

    Returns:
        Словарь с идентификаторами, именем, типом, видимостью, путем, глубиной,
        авторами изменений, признаком удаления и временными метками узла.
    """

    try:
        file = node.file
    except _SAInvalidRequestError:
        file = None
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
        "is_deleted": bool(node.is_deleted),
        "deleted_at": node.deleted_at,
        "file_size_bytes": file.size_bytes if file is not None else None,
        "file_mime_type": file.mime_type if file is not None else None,
    }


def _breadcrumb_snapshot(node: FileSystemNode) -> dict[str, Any]:
    """Создает краткий снимок узла для хлебных крошек.

    Args:
        node: ORM-модель узла файловой системы.

    Returns:
        Словарь с идентификатором, именем, типом, путем и глубиной узла.
    """

    return {
        "id": node.id,
        "name": node.name,
        "node_type": node.node_type,
        "path": node.path,
        "depth": node.depth,
    }


def _tree_snapshot(
    node: FileSystemNode,
    *,
    children: Iterable[NodeTreeItem] = (),
) -> dict[str, Any]:
    """Создает снимок узла для древовидного представления.

    Args:
        node: ORM-модель узла файловой системы.
        children: Дочерние элементы дерева.

    Returns:
        Словарь с данными узла и списком дочерних элементов.
    """

    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "name": node.name,
        "node_type": node.node_type,
        "visibility": node.visibility,
        "path": node.path,
        "depth": node.depth,
        "children": list(children),
    }


def _operation_response(
    snapshot: dict[str, Any], message: str
) -> NodeOperationResponse:
    """Формирует стандартный ответ успешной операции над узлом.

    Args:
        snapshot: Снимок узла файловой системы.
        message: Сообщение об успешной операции.

    Returns:
        Ответ операции с success=True, сериализованным узлом и сообщением.
    """

    return NodeOperationResponse(
        success=True,
        node=NodeRead.model_validate(snapshot),
        message=message,
    )


def _unique_copy_name(existing: set[str], desired: str, *, is_file: bool) -> str:
    """Подбирает уникальное имя копии узла среди существующих имён.

    Если ``desired`` не конфликтует с именами в ``existing``, возвращает его без
    изменений. Иначе добавляет суффикс ``(копия)``, затем ``(копия 2)`` и т.д.,
    пока имя не станет уникальным. Для файлов суффикс вставляется перед
    расширением (последний сегмент после точки), чтобы сохранить расширение.

    Args:
        existing: Множество имён, уже занятых в целевой папке.
        desired: Желаемое имя копии.
        is_file: Является ли узел файлом. Для файлов сохраняется расширение.

    Returns:
        Уникальное имя копии узла.
    """

    if desired not in existing:
        return desired

    stem = desired
    suffix = ""
    if is_file and "." in desired:
        dot_index = desired.rfind(".")
        if dot_index > 0:
            stem = desired[:dot_index]
            suffix = desired[dot_index:]

    candidate = f"{stem} (копия){suffix}"
    if candidate not in existing:
        return candidate

    counter = 2
    while True:
        candidate = f"{stem} (копия {counter}){suffix}"
        if candidate not in existing:
            return candidate
        counter += 1


def _nodes_page(
    nodes: list[FileSystemNode],
    *,
    limit: int,
    offset: int,
) -> PageResponse[NodeListItem]:
    """Формирует страницу узлов из полного списка.

    Args:
        nodes: Полный список узлов.
        limit: Максимальное количество элементов на странице.
        offset: Смещение начала страницы.

    Returns:
        Ответ со списком элементов текущей страницы и метаданными пагинации.
    """

    page_nodes = nodes[offset : offset + limit]
    items = [NodeListItem.model_validate(_node_snapshot(node)) for node in page_nodes]
    return PageResponse(
        items=items,
        meta=PageMeta(
            limit=limit,
            offset=offset,
            total=len(nodes),
            count=len(items),
        ),
    )


def _can_paginate_list_in_sql(params: NodeQueryParams) -> bool:
    """Проверяет, можно ли выполнить пагинацию списка на уровне SQL.

    SQL-пагинация возможна, если не заданы фильтры, которые применяются в
    Python через `_filter_query_nodes()`: видимость, диапазоны дат и режим
    «только удалённые». В таком случае `get_root_nodes()` или `get_children()`
    вместе с соответствующим `count_*()` дают тот же результат без загрузки
    всего уровня в память.

    Args:
        params: Параметры запроса списка узлов.

    Returns:
        `True`, если список можно получить одним постраничным SQL-запросом и
        отдельным запросом подсчёта.
    """

    return (
        params.visibility is None
        and params.created_from is None
        and params.created_to is None
        and params.updated_from is None
        and params.updated_to is None
        and params.is_deleted is not True
    )


def _filter_query_nodes(
    nodes: list[FileSystemNode],
    params: NodeQueryParams,
) -> list[FileSystemNode]:
    """Фильтрует узлы для обычного списка.

    Применяет фильтры по признаку удаления, видимости, дате создания и дате
    обновления.

    Args:
        nodes: Список узлов для фильтрации.
        params: Параметры фильтрации списка узлов.

    Returns:
        Список узлов, соответствующих фильтрам.
    """

    return [
        node
        for node in nodes
        if _matches_deleted(node, params.is_deleted)
        and _matches_visibility(node, params.visibility)
        and _matches_range(node.created_at, params.created_from, params.created_to)
        and _matches_range(node.updated_at, params.updated_from, params.updated_to)
    ]


def _filter_search_nodes(
    nodes: list[FileSystemNode],
    params: NodeSearchQuery,
) -> list[FileSystemNode]:
    """Фильтрует найденные узлы.

    Применяет фильтр по видимости и исключает удаленные узлы, если
    include_deleted равен False.

    Args:
        nodes: Список найденных узлов.
        params: Параметры поиска узлов.

    Returns:
        Список найденных узлов, соответствующих фильтрам.
    """

    return [
        node
        for node in nodes
        if _matches_visibility(node, params.visibility)
        and (params.include_deleted or not bool(node.is_deleted))
    ]


def _matches_deleted(node: FileSystemNode, is_deleted: bool | None) -> bool:
    """Проверяет соответствие узла фильтру удаления.

    Args:
        node: Узел файловой системы.
        is_deleted: Ожидаемое состояние удаления. Если None, фильтр не
            применяется.

    Returns:
        True, если узел соответствует фильтру удаления.
    """

    if is_deleted is None:
        return True
    return bool(node.is_deleted) is is_deleted


def _matches_visibility(
    node: FileSystemNode,
    visibility: NodeVisibility | None,
) -> bool:
    """Проверяет соответствие узла фильтру видимости.

    Args:
        node: Узел файловой системы.
        visibility: Ожидаемая видимость. Если None, фильтр не применяется.

    Returns:
        True, если узел соответствует фильтру видимости.
    """

    if visibility is None:
        return True
    return node.visibility == visibility


def _matches_range(
    value: datetime | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    """Проверяет попадание даты в указанный диапазон.

    Если value равен None, совпадение возможно только при отсутствии обеих
    границ диапазона. Все даты нормализуются к UTC перед сравнением.

    Args:
        value: Проверяемая дата.
        start: Начало диапазона. Если None, нижняя граница не применяется.
        end: Конец диапазона. Если None, верхняя граница не применяется.

    Returns:
        True, если значение попадает в диапазон.
    """

    if value is None:
        return start is None and end is None
    normalized_value = _normalize_datetime(value)
    if start is not None and normalized_value < _normalize_datetime(start):
        return False
    if end is not None and normalized_value > _normalize_datetime(end):
        return False
    return True


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


def _normalize_sort_by(sort_by: str) -> NodeSortField:
    """Нормализует и проверяет поле сортировки узлов.

    Args:
        sort_by: Исходное поле сортировки.

    Returns:
        Нормализованное поле сортировки узлов.

    Raises:
        ValidationServiceError: Если поле сортировки не поддерживается.
    """

    normalized = sort_by.strip().lower()
    if normalized not in ALLOWED_SORT_FIELDS:
        raise ValidationServiceError(
            "Поле сортировки неподдерживаемых узлов.",
            field="sort_by",
            value=sort_by,
            reason="unsupported_sort_field",
            details={
                "service": SERVICE_NAME,
                "allowed_values": sorted(ALLOWED_SORT_FIELDS),
            },
        )
    return cast(NodeSortField, normalized)


def _sort_direction(sort_desc: bool) -> NodeSortDirection:
    """Возвращает направление сортировки по флагу убывания.

    Args:
        sort_desc: Нужно ли сортировать по убыванию.

    Returns:
        "desc", если sort_desc равен True, иначе "asc".
    """

    return "desc" if sort_desc else "asc"


def _build_tree(nodes: list[FileSystemNode], *, root_node_id: UUID) -> NodeTreeItem:
    """Строит дерево узлов файловой системы.

    Находит корневой узел, группирует остальные узлы по parent_id и рекурсивно
    строит NodeTreeItem. Дочерние узлы сортируются по типу, имени и
    идентификатору.

    Args:
        nodes: Список узлов, включающий корень и его потомков.
        root_node_id: Идентификатор корневого узла дерева.

    Returns:
        Дерево узлов, начиная с root_node_id.

    Raises:
        ServiceError: Если корневой узел отсутствует в списке nodes.
    """

    node_by_id = {node.id: node for node in nodes}
    root = node_by_id.get(root_node_id)
    if root is None:
        raise ServiceError(
            "Корневой узел отсутствует в результатах поиска потомков.",
            service=SERVICE_NAME,
            operation="get_tree",
        )

    children_by_parent: dict[UUID | None, list[FileSystemNode]] = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node)

    def build(node: FileSystemNode) -> NodeTreeItem:
        children = [
            build(child)
            for child in sorted(
                children_by_parent.get(node.id, []),
                key=lambda item: (
                    item.node_type.value,
                    item.name.casefold(),
                    str(item.id),
                ),
            )
        ]
        return NodeTreeItem.model_validate(_tree_snapshot(node, children=children))

    return build(root)


def _audit_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Формирует метаданные узла для аудита.

    Выбирает из снимка только поля, значимые для аудита, и преобразует значения
    в JSON-совместимый формат.

    Args:
        snapshot: Снимок узла файловой системы.

    Returns:
        Словарь JSON-совместимых метаданных для аудита.
    """

    return {
        key: _jsonable(value)
        for key, value in snapshot.items()
        if key
        in {
            "id",
            "owner_id",
            "parent_id",
            "name",
            "node_type",
            "visibility",
            "path",
            "depth",
            "is_deleted",
        }
    }


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


def _empty_result_error(operation: str) -> ServiceError:
    """Создает ошибку пустого результата сервисной операции.

    Args:
        operation: Название операции, завершившейся без результата.

    Returns:
        Ошибка сервиса с описанием отсутствующего результата.
    """

    return ServiceError(
        "Сервисная операция завершена безрезультатно.",
        service=SERVICE_NAME,
        operation=operation,
    )


# Глобальный singleton-экземпляр сервиса узлов файловой системы.
_nodes_service: NodesService | None = None


def get_nodes_service(
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    access_service: AccessService | None = None,
    audit_service: AuditService | None = None,
    storage_service: StorageService | None = None,
) -> NodesService:
    """Возвращает экземпляр сервиса узлов файловой системы.

    Если передана хотя бы одна зависимость, создает новый экземпляр сервиса с
    указанными зависимостями. Если зависимости не переданы, возвращает
    глобальный singleton-экземпляр, создавая его при первом обращении.

    Args:
        uow_factory: Фабрика Unit of Work для нового экземпляра сервиса.
        access_service: Сервис доступа для нового экземпляра сервиса.
        audit_service: Сервис аудита для нового экземпляра сервиса.
        storage_service: Сервис хранилища для нового экземпляра сервиса.

    Returns:
        Экземпляр NodesService.
    """

    if (
        uow_factory is not None
        or access_service is not None
        or audit_service is not None
        or storage_service is not None
    ):
        return NodesService(
            uow_factory=uow_factory,
            access_service=access_service,
            audit_service=audit_service,
            storage_service=storage_service,
        )

    global _nodes_service
    if _nodes_service is None:
        _nodes_service = NodesService()
    return _nodes_service
