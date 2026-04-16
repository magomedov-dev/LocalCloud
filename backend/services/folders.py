from __future__ import annotations

from enum import Enum
from typing import Any, cast
from uuid import UUID

from sqlalchemy.exc import InvalidRequestError as _SAInvalidRequestError

from core.logging import get_logger
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    AuditResult,
    BackgroundTaskStatus,
    BackgroundTaskType,
    NodeType,
    NodeVisibility,
)
from database.models.filesystem import FileSystemNode, Folder
from database.models.tasks import BackgroundTask
from database.repositories.folders import FolderSortField
from database.repositories.nodes import NodeSortDirection
from schemas.common import PageMeta, PageResponse
from schemas.folders import (
    FolderArchiveRequest,
    FolderArchiveResponse,
    FolderContentRead,
    FolderCreateRequest,
    FolderListItem,
    FolderRead,
    FolderUpdateRequest,
)
from schemas.nodes import NodeListItem
from security.permissions import PermissionAction
from services.access import AccessService, get_access_service
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
)

logger = get_logger("services.folders")

SERVICE_NAME = "folders"
ALLOWED_FOLDER_SORT_FIELDS: set[str] = {
    "name",
    "created_at",
    "updated_at",
    "deleted_at",
    "depth",
    "color",
}


class FoldersService:
    """Сервис бизнес-логики для работы с папками файловой системы.

    Управляет папками как отдельными сущностями, связанными с FileSystemNode.
    Сервис проверяет права доступа, выполняет операции через Unit of Work,
    преобразует ORM-модели в схемы ответа и записывает события аудита.

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
    ) -> None:
        """Инициализирует сервис папок.

        Если зависимости не переданы явно, создает их через стандартные фабрики
        и функции получения сервисов.

        Args:
            uow_factory: Фабрика Unit of Work. Если не передана, создается
                стандартная фабрика.
            access_service: Сервис проверки доступа. Если не передан, создается
                стандартный сервис доступа.
            audit_service: Сервис аудита. Если не передан, создается стандартный
                сервис аудита.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.access_service = access_service or get_access_service(
            uow_factory=self.uow_factory
        )
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory
        )

    async def create_folder(
        self,
        data: FolderCreateRequest,
        *,
        owner_id: UUID,
        actor_id: UUID | None = None,
        visibility: NodeVisibility = NodeVisibility.PRIVATE,
    ) -> FolderRead:
        """Создает новую папку.

        Если указан parent_id, проверяет доступ актера к родительской папке и
        соответствие владельца. Если parent_id не указан, разрешает создание
        корневой папки только владельцу.

        Args:
            data: Данные для создания папки.
            owner_id: Идентификатор владельца создаваемой папки.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                используется owner_id.
            visibility: Видимость создаваемого узла файловой системы.

        Returns:
            Данные созданной папки.

        Raises:
            PermissionServiceError: Если пользователь не может создать корневую
                папку или не имеет прав на родительскую папку.
            ValidationServiceError: Если родительский узел не является папкой или
                принадлежит другому владельцу.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "create_folder"
        snapshot: dict[str, Any] | None = None
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
                    _ensure_folder_node(parent, operation=operation)
                    if parent.owner_id != owner_id:
                        raise ValidationServiceError(
                            "Родительская папка принадлежит другому владельцу.",
                            field="parent_id",
                            value=data.parent_id,
                            reason="owner_mismatch",
                            details={"service": SERVICE_NAME, "operation": operation},
                        )
                elif resolved_actor_id != owner_id:
                    raise PermissionServiceError(
                        "Только владелец может создавать папки корневого уровня.",
                        user_id=resolved_actor_id,
                        resource_type="filesystem_root",
                        resource_id=owner_id,
                        action=PermissionAction.WRITE,
                        reason="not_owner",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                folder = await uow.folders.create_folder(
                    owner_id=owner_id,
                    name=data.name,
                    parent_id=data.parent_id,
                    description=data.description,
                    color=data.color,
                    visibility=visibility,
                    created_by=resolved_actor_id,
                    check_owner_exists=True,
                    check_conflict=True,
                    flush=True,
                    refresh=True,
                )
                folder = await uow.folders.get_required_by_node_id(folder.node_id)
                snapshot = _folder_snapshot(folder)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_folder_event(
                user_id=resolved_actor_id,
                action=AuditAction.FOLDER_CREATED,
                snapshot=snapshot,
                message="Папка создана.",
            )
            return FolderRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось создать папку."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось создать папку."
            ) from exc

    async def get_folder_node_id(self, folder_id: UUID) -> UUID:
        """Возвращает идентификатор узла файловой системы для записи папки.

        Args:
            folder_id: Идентификатор записи папки.

        Returns:
            Идентификатор связанного узла файловой системы.

        Raises:
            ServiceError: Если идентификатор узла не удалось получить.
        """

        operation = "get_folder_node_id"
        node_id: UUID | None = None

        try:
            async with self.uow_factory() as uow:
                folder = await uow.folders.get_required_folder_by_id(folder_id)
                node_id = folder.node_id

            if node_id is None:
                raise _empty_result_error(operation)
            return node_id

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось разрешить идентификатор узла папки.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось разрешить идентификатор узла папки.",
            ) from exc

    async def get_folder(
        self,
        node_id: UUID,
        *,
        user_id: UUID | None,
        allow_deleted: bool = False,
        allow_public: bool = True,
    ) -> FolderRead:
        """Возвращает папку по идентификатору узла.

        Проверяет доступ пользователя к узлу, убеждается, что узел является папкой,
        и загружает связанную сущность Folder.

        Args:
            node_id: Идентификатор узла папки.
            user_id: Идентификатор пользователя. Может быть None для публичного
                доступа, если allow_public равен True.
            allow_deleted: Нужно ли разрешать получение удаленных папок.
            allow_public: Нужно ли разрешать доступ к публичным папкам без владельца.

        Returns:
            Данные найденной папки.

        Raises:
            PermissionServiceError: Если у пользователя нет доступа к папке.
            ValidationServiceError: Если узел не является папкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "get_folder"
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
                _ensure_folder_node(node, operation=operation)
                folder = await uow.folders.get_required_by_node_id(
                    node.id,
                    include_deleted=allow_deleted,
                )
                snapshot = _folder_snapshot(folder)

            if snapshot is None:
                raise _empty_result_error(operation)
            return FolderRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось загрузить папку."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось загрузить папку."
            ) from exc

    async def get_folder_content(
        self,
        node_id: UUID,
        *,
        user_id: UUID | None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "name",
        sort_desc: bool = False,
    ) -> FolderContentRead:
        """Возвращает содержимое папки.

        Загружает данные папки, хлебные крошки и дочерние узлы. Дочерние элементы
        сортируются и затем обрезаются по limit и offset.

        Args:
            node_id: Идентификатор узла папки.
            user_id: Идентификатор пользователя, запрашивающего содержимое.
            include_deleted: Нужно ли включать удаленные узлы.
            limit: Максимальное количество дочерних элементов в ответе.
            offset: Смещение для постраничной выдачи.
            sort_by: Поле сортировки дочерних узлов.
            sort_desc: Нужно ли сортировать по убыванию.

        Returns:
            Содержимое папки: данные папки, хлебные крошки, элементы текущей страницы
            и общее количество дочерних узлов.

        Raises:
            PermissionServiceError: Если у пользователя нет доступа к папке.
            ValidationServiceError: Если узел не является папкой или поле сортировки
                не поддерживается.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "get_folder_content"
        content: FolderContentRead | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=user_id,
                    action=PermissionAction.READ,
                    allow_deleted=include_deleted,
                    uow=uow,
                )
                _ensure_folder_node(node, operation=operation)

                folder = await uow.folders.get_required_by_node_id(
                    node.id,
                    include_deleted=include_deleted,
                )
                children = await uow.nodes.get_children(
                    parent_id=node.id,
                    include_deleted=include_deleted,
                    offset=offset,
                    limit=limit,
                    sort_by=cast(Any, _normalize_node_sort_by(sort_by)),
                    sort_direction=_sort_direction(sort_desc),
                )
                total = await uow.nodes.count_children(
                    parent_id=node.id,
                    include_deleted=include_deleted,
                )
                breadcrumbs = await uow.nodes.get_breadcrumbs(
                    node_id=node.id,
                    include_self=True,
                    include_deleted=include_deleted,
                )
                content = FolderContentRead(
                    folder=FolderRead.model_validate(_folder_snapshot(folder)),
                    breadcrumbs=[
                        NodeListItem.model_validate(_node_snapshot(item))
                        for item in breadcrumbs
                    ],
                    items=[
                        NodeListItem.model_validate(_node_snapshot(item))
                        for item in children
                    ],
                    total=total,
                )

            if content is None:
                raise _empty_result_error(operation)
            return content

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось загрузить содержимое папки.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось загрузить содержимое папки.",
            ) from exc

    async def list_folders(
        self,
        *,
        owner_id: UUID | None = None,
        parent_id: UUID | None = None,
        user_id: UUID | None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "name",
        sort_desc: bool = False,
    ) -> PageResponse[FolderListItem]:
        """Возвращает список папок с постраничной выдачей.

        Если указан parent_id, возвращает папки внутри родительской папки после
        проверки доступа к ней. Если parent_id не указан, возвращает корневые папки
        владельца и требует, чтобы пользователь был владельцем.

        Args:
            owner_id: Идентификатор владельца папок. Если None, используется user_id
                или владелец родительской папки.
            parent_id: Идентификатор родительской папки. Если None, выбираются
                корневые папки.
            user_id: Идентификатор пользователя, выполняющего запрос.
            include_deleted: Нужно ли включать удаленные папки.
            limit: Максимальное количество элементов в ответе.
            offset: Смещение для постраничной выдачи.
            sort_by: Поле сортировки папок.
            sort_desc: Нужно ли сортировать по убыванию.

        Returns:
            Страница со списком папок и метаданными пагинации.

        Raises:
            PermissionServiceError: Если пользователь не может просматривать
                корневые папки указанного владельца.
            ValidationServiceError: Если родительский узел не является папкой,
                владелец не совпадает с родительской папкой или поле сортировки
                не поддерживается.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_folders"
        page: PageResponse[FolderListItem] | None = None

        try:
            async with self.uow_factory() as uow:
                resolved_owner_id = owner_id or user_id

                if parent_id is not None:
                    parent = await self.access_service.get_accessible_node(
                        node_id=parent_id,
                        user_id=user_id,
                        action=PermissionAction.READ,
                        allow_deleted=include_deleted,
                        uow=uow,
                    )
                    _ensure_folder_node(parent, operation=operation)
                    resolved_owner_id = resolved_owner_id or parent.owner_id
                    if resolved_owner_id != parent.owner_id:
                        raise ValidationServiceError(
                            "Фильтр владельца не соответствует владельцу родительской папки.",
                            field="owner_id",
                            value=resolved_owner_id,
                            reason="owner_parent_mismatch",
                            details={"service": SERVICE_NAME, "operation": operation},
                        )
                elif resolved_owner_id is None:
                    raise PermissionServiceError(
                        "Для перечисления корневых папок требуется владелец, прошедший проверку подлинности.",
                        action=PermissionAction.READ,
                        reason="anonymous_user",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                elif user_id != resolved_owner_id:
                    raise PermissionServiceError(
                        "Список корневых папок доступен только владельцу.",
                        user_id=user_id,
                        resource_type="filesystem_root",
                        resource_id=resolved_owner_id,
                        action=PermissionAction.READ,
                        reason="not_owner",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                folders = await uow.folders.list_user_folders(
                    owner_id=resolved_owner_id,
                    parent_id=parent_id,
                    include_deleted=include_deleted,
                    offset=offset,
                    limit=limit,
                    sort_by=_normalize_folder_sort_by(sort_by),
                    sort_direction=_sort_direction(sort_desc),
                )
                total = await uow.folders.count_user_folders_filtered(
                    owner_id=resolved_owner_id,
                    parent_id=parent_id,
                    include_deleted=include_deleted,
                )
                page = PageResponse(
                    items=[
                        FolderListItem.model_validate(_folder_snapshot(f))
                        for f in folders
                    ],
                    meta=PageMeta(
                        limit=limit,
                        offset=offset,
                        total=total,
                        count=len(folders),
                    ),
                )

            if page is None:
                raise _empty_result_error(operation)
            return page

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось отобразить список папок."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось отобразить список папок."
            ) from exc

    async def update_folder(
        self,
        node_id: UUID,
        data: FolderUpdateRequest,
        *,
        actor_id: UUID,
    ) -> FolderRead:
        """Обновляет метаданные папки.

        Проверяет право записи к папке и обновляет редактируемые поля метаданных,
        такие как описание и цвет.

        Args:
            node_id: Идентификатор узла папки.
            data: Новые данные метаданных папки.
            actor_id: Идентификатор пользователя, выполняющего обновление.

        Returns:
            Обновленные данные папки.

        Raises:
            PermissionServiceError: Если у пользователя нет права записи.
            ValidationServiceError: Если узел не является папкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "update_folder"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.WRITE,
                    uow=uow,
                )
                _ensure_folder_node(node, operation=operation)
                folder = await uow.folders.update_metadata_by_node_id(
                    node_id=node.id,
                    description=data.description,
                    color=data.color,
                    updated_by=actor_id,
                    flush=True,
                    refresh=True,
                )
                snapshot = _folder_snapshot(folder)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_folder_event(
                user_id=actor_id,
                action=AuditAction.FOLDER_MOVED,
                snapshot=snapshot,
                message="Обновлены метаданные папки.",
            )
            return FolderRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось обновить папку."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось обновить папку."
            ) from exc

    async def rename_folder(
        self,
        node_id: UUID,
        *,
        new_name: str,
        actor_id: UUID,
    ) -> FolderRead:
        """Переименовывает папку.

        Выполняет общую мутацию папки через _mutate_folder, проверяя право записи
        и записывая событие аудита после успешного переименования.

        Args:
            node_id: Идентификатор узла папки.
            new_name: Новое имя папки.
            actor_id: Идентификатор пользователя, выполняющего переименование.

        Returns:
            Обновленные данные папки.

        Raises:
            PermissionServiceError: Если у пользователя нет права записи.
            ValidationServiceError: Если узел не является папкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        return await self._mutate_folder(
            node_id=node_id,
            actor_id=actor_id,
            access_action=PermissionAction.WRITE,
            audit_action=AuditAction.FOLDER_RENAMED,
            message="Папка переименована.",
            operation="rename_folder",
            mutate=lambda uow: uow.folders.rename_folder(
                node_id=node_id,
                new_name=new_name,
                updated_by=actor_id,
                flush=True,
                refresh=True,
            ),
        )

    async def move_folder(
        self,
        node_id: UUID,
        *,
        target_parent_id: UUID | None,
        actor_id: UUID,
    ) -> FolderRead:
        """Перемещает папку в новую родительскую папку или в корень.

        Проверяет право записи к перемещаемой папке. Если target_parent_id указан,
        дополнительно проверяет право записи к целевой родительской папке.

        Args:
            node_id: Идентификатор узла перемещаемой папки.
            target_parent_id: Идентификатор новой родительской папки. Если None,
                папка перемещается в корень.
            actor_id: Идентификатор пользователя, выполняющего перемещение.

        Returns:
            Обновленные данные перемещенной папки.

        Raises:
            PermissionServiceError: Если у пользователя нет права записи к папке
                или целевой родительской папке.
            ValidationServiceError: Если исходный или целевой узел не является
                папкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "move_folder"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.WRITE,
                    uow=uow,
                )
                _ensure_folder_node(node, operation=operation)
                if target_parent_id is not None:
                    target = await self.access_service.get_accessible_node(
                        node_id=target_parent_id,
                        user_id=actor_id,
                        action=PermissionAction.WRITE,
                        uow=uow,
                    )
                    _ensure_folder_node(target, operation=operation)

                folder = await uow.folders.move_folder(
                    node_id=node_id,
                    new_parent_id=target_parent_id,
                    updated_by=actor_id,
                    flush=True,
                    refresh=True,
                )
                snapshot = _folder_snapshot(folder)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_folder_event(
                user_id=actor_id,
                action=AuditAction.FOLDER_MOVED,
                snapshot=snapshot,
                message="Папка перемещена.",
            )
            return FolderRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось переместить папку."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось переместить папку."
            ) from exc

    async def delete_folder(
        self,
        node_id: UUID,
        *,
        actor_id: UUID,
        recursive: bool = True,
    ) -> FolderRead:
        """Мягко удаляет папку.

        Перемещает папку в корзину через репозиторий. При recursive=True удаление
        применяется рекурсивно к дочерним узлам.

        Args:
            node_id: Идентификатор узла папки.
            actor_id: Идентификатор пользователя, выполняющего удаление.
            recursive: Нужно ли удалять вложенные элементы рекурсивно.

        Returns:
            Данные удаленной папки.

        Raises:
            PermissionServiceError: Если у пользователя нет права удаления.
            ValidationServiceError: Если узел не является папкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        return await self._mutate_folder(
            node_id=node_id,
            actor_id=actor_id,
            access_action=PermissionAction.DELETE,
            audit_action=AuditAction.FOLDER_DELETED,
            message="Папка перемещена в корзину.",
            operation="delete_folder",
            mutate=lambda uow: uow.folders.soft_delete_folder(
                node_id=node_id,
                deleted_by=actor_id,
                recursive=recursive,
                flush=True,
                refresh=True,
            ),
        )

    async def restore_folder(
        self,
        node_id: UUID,
        *,
        actor_id: UUID,
        recursive: bool = True,
    ) -> FolderRead:
        """Восстанавливает мягко удаленную папку.

        Восстанавливает папку через репозиторий. При recursive=True восстановление
        применяется рекурсивно к дочерним узлам.

        Args:
            node_id: Идентификатор узла папки.
            actor_id: Идентификатор пользователя, выполняющего восстановление.
            recursive: Нужно ли восстанавливать вложенные элементы рекурсивно.

        Returns:
            Данные восстановленной папки.

        Raises:
            PermissionServiceError: Если у пользователя нет права на операцию.
            ValidationServiceError: Если узел не является папкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        return await self._mutate_folder(
            node_id=node_id,
            actor_id=actor_id,
            access_action=PermissionAction.DELETE,
            audit_action=AuditAction.FOLDER_RESTORED,
            message="Папка восстановлена.",
            operation="restore_folder",
            allow_deleted=True,
            mutate=lambda uow: uow.folders.restore_folder(
                node_id=node_id,
                updated_by=actor_id,
                recursive=recursive,
                flush=True,
                refresh=True,
            ),
        )

    async def purge_folder(self, node_id: UUID, *, actor_id: UUID) -> None:
        """Окончательно удаляет папку.

        Проверяет право управления папкой, загружает снимок папки для аудита,
        помечает узел как окончательно удаленный и записывает событие аудита.

        Args:
            node_id: Идентификатор узла папки.
            actor_id: Идентификатор пользователя, выполняющего окончательное удаление.

        Raises:
            PermissionServiceError: Если у пользователя нет права управления.
            ValidationServiceError: Если узел не является папкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "purge_folder"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.MANAGE,
                    allow_deleted=True,
                    uow=uow,
                )
                _ensure_folder_node(node, operation=operation)
                folder = await uow.folders.get_required_by_node_id(
                    node.id,
                    include_deleted=True,
                )
                snapshot = _folder_snapshot(folder)
                await uow.nodes.mark_purged(node_id=node.id, flush=True)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)
            await self._safe_log_folder_event(
                user_id=actor_id,
                action=AuditAction.FOLDER_PURGED,
                snapshot=snapshot,
                message="Папка удалена безвозвратно.",
            )

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось очистить папку."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось очистить папку."
            ) from exc

    async def search_folders(
        self,
        *,
        query: str | None,
        user_id: UUID | None,
        owner_id: UUID | None = None,
        parent_id: UUID | None = None,
        include_deleted: bool = False,
        color: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "name",
        sort_desc: bool = False,
    ) -> PageResponse[FolderListItem]:
        """Ищет папки по фильтрам.

        Поддерживает поиск по текстовому запросу, владельцу, родительской папке,
        признаку удаления и цвету. Для поиска в корне требует, чтобы пользователь
        искал только собственные папки.

        Args:
            query: Поисковая строка. Может быть None.
            user_id: Идентификатор пользователя, выполняющего поиск.
            owner_id: Идентификатор владельца папок. Если None, используется user_id
                или владелец родительской папки.
            parent_id: Идентификатор родительской папки для ограничения поиска.
            include_deleted: Нужно ли включать удаленные папки.
            color: Фильтр по цвету папки.
            limit: Максимальное количество элементов в ответе.
            offset: Смещение для постраничной выдачи.
            sort_by: Поле сортировки.
            sort_desc: Нужно ли сортировать по убыванию.

        Returns:
            Страница найденных папок и метаданные пагинации.

        Raises:
            PermissionServiceError: Если поиск выполняется без владельца или
                пользователь пытается искать чужие корневые папки.
            ValidationServiceError: Если parent_id указывает не на папку или поле
                сортировки не поддерживается.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "search_folders"
        page: PageResponse[FolderListItem] | None = None

        try:
            async with self.uow_factory() as uow:
                resolved_owner_id = owner_id or user_id
                if parent_id is not None:
                    parent = await self.access_service.get_accessible_node(
                        node_id=parent_id,
                        user_id=user_id,
                        action=PermissionAction.READ,
                        allow_deleted=include_deleted,
                        uow=uow,
                    )
                    _ensure_folder_node(parent, operation=operation)
                    resolved_owner_id = resolved_owner_id or parent.owner_id
                if resolved_owner_id is None:
                    raise PermissionServiceError(
                        "Для поиска по папкам требуется аутентифицированный владелец или родительская папка.",
                        action=PermissionAction.READ,
                        reason="anonymous_user",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                if parent_id is None and resolved_owner_id != user_id:
                    raise PermissionServiceError(
                        "Пользователь может выполнять поиск только в собственных корневых папках без родительской папки.",
                        user_id=user_id,
                        resource_type="filesystem_root",
                        resource_id=resolved_owner_id,
                        action=PermissionAction.READ,
                        reason="not_owner",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                folders = await uow.folders.search_folders(
                    owner_id=resolved_owner_id,
                    query=query,
                    parent_id=parent_id,
                    include_deleted=include_deleted,
                    color=color,
                    offset=offset,
                    limit=limit,
                    sort_by=_normalize_folder_sort_by(sort_by),
                    sort_direction=_sort_direction(sort_desc),
                )
                total = await uow.folders.count_search_results(
                    owner_id=resolved_owner_id,
                    query=query,
                    parent_id=parent_id,
                    include_deleted=include_deleted,
                    color=color,
                )
                page = PageResponse(
                    items=[
                        FolderListItem.model_validate(_folder_snapshot(f))
                        for f in folders
                    ],
                    meta=PageMeta(
                        limit=limit,
                        offset=offset,
                        total=total,
                        count=len(folders),
                    ),
                )

            if page is None:
                raise _empty_result_error(operation)
            return page

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось выполнить поиск по папкам.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось выполнить поиск по папкам.",
            ) from exc

    async def request_folder_archive(
        self,
        data: FolderArchiveRequest,
        *,
        actor_id: UUID,
    ) -> FolderArchiveResponse:
        """Создает фоновую задачу на архивацию папки.

        Проверяет право скачивания папки, создает задачу типа CREATE_FOLDER_ARCHIVE
        и сохраняет основные параметры архива в result_data задачи.

        Args:
            data: Данные запроса на создание архива папки.
            actor_id: Идентификатор пользователя, запрашивающего архив.

        Returns:
            Ответ с идентификатором созданной задачи и ее текущим статусом.

        Raises:
            PermissionServiceError: Если у пользователя нет права скачивания папки.
            ValidationServiceError: Если указанный узел не является папкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "request_folder_archive"
        task_snapshot: dict[str, Any] | None = None
        folder_snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=data.folder_id,
                    user_id=actor_id,
                    action=PermissionAction.DOWNLOAD,
                    allow_deleted=data.include_deleted,
                    uow=uow,
                )
                _ensure_folder_node(node, operation=operation)
                folder = await uow.folders.get_required_by_node_id(
                    node.id,
                    include_deleted=data.include_deleted,
                )
                task = await uow.tasks.create_user_task(
                    task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
                    created_by=actor_id,
                    related_entity_type="folder",
                    related_entity_id=folder.node_id,
                    flush=True,
                    refresh=True,
                )
                task = await uow.tasks.update(
                    task,
                    {
                        "payload": {
                            "folder_id": str(folder.node_id),
                            "include_deleted": data.include_deleted,
                            "archive_name": data.archive_name or node.name,
                            "password": data.password,
                        },
                        "result_data": {
                            "folder_id": str(folder.node_id),
                            "archive_name": data.archive_name or node.name,
                            "include_deleted": data.include_deleted,
                            "password_protected": data.password is not None,
                        },
                    },
                    flush=True,
                    refresh=True,
                    allowed_fields={"payload", "result_data"},
                )
                folder_snapshot = _folder_snapshot(folder)
                task_snapshot = _task_snapshot(task)
                await uow.commit()

            if task_snapshot is None or folder_snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_folder_event(
                user_id=actor_id,
                action=AuditAction.FOLDER_ARCHIVE_REQUESTED,
                snapshot=folder_snapshot,
                message="Запрошен архив папок.",
                metadata={"task_id": task_snapshot["id"]},
            )
            return FolderArchiveResponse(
                task_id=cast(UUID, task_snapshot["id"]),
                status=cast(BackgroundTaskStatus, task_snapshot["status"]),
            )

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось запросить архив папок."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось запросить архив папок."
            ) from exc

    async def count_folders(
        self,
        *,
        owner_id: UUID,
        user_id: UUID,
        include_deleted: bool = False,
    ) -> int:
        """Возвращает количество папок пользователя.

        Разрешает подсчет только собственных папок пользователя.

        Args:
            owner_id: Идентификатор владельца папок.
            user_id: Идентификатор пользователя, выполняющего запрос.
            include_deleted: Нужно ли учитывать удаленные папки.

        Returns:
            Количество папок пользователя.

        Raises:
            PermissionServiceError: Если пользователь пытается считать папки другого
                владельца.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "count_folders"
        count: int | None = None

        try:
            if owner_id != user_id:
                raise PermissionServiceError(
                    "Пользователь может считать только свои собственные папки.",
                    user_id=user_id,
                    resource_type="filesystem_root",
                    resource_id=owner_id,
                    action=PermissionAction.READ,
                    reason="not_owner",
                    details={"service": SERVICE_NAME, "operation": operation},
                )

            async with self.uow_factory() as uow:
                count = await uow.folders.count_user_folders(
                    owner_id=owner_id,
                    include_deleted=include_deleted,
                )

            if count is None:
                raise _empty_result_error(operation)
            return count

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось подсчитать папки."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось подсчитать папки."
            ) from exc

    async def _mutate_folder(
        self,
        *,
        node_id: UUID,
        actor_id: UUID,
        access_action: PermissionAction,
        audit_action: AuditAction,
        message: str,
        operation: str,
        mutate: Any,
        allow_deleted: bool = False,
    ) -> FolderRead:
        """Выполняет общую мутацию папки.

        Используется для операций, которые имеют одинаковый шаблон: проверка доступа,
        проверка типа узла, выполнение функции изменения, commit и запись события
        аудита.

        Args:
            node_id: Идентификатор узла папки.
            actor_id: Идентификатор пользователя, выполняющего операцию.
            access_action: Действие доступа, которое нужно проверить.
            audit_action: Действие аудита для записи после успешной операции.
            message: Сообщение для аудита и ошибок.
            operation: Название операции для контекста ошибок.
            mutate: Асинхронная функция, выполняющая изменение через Unit of Work.
            allow_deleted: Нужно ли разрешать доступ к удаленной папке.

        Returns:
            Данные измененной папки.

        Raises:
            PermissionServiceError: Если у пользователя нет нужного права доступа.
            ValidationServiceError: Если узел не является папкой.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=access_action,
                    allow_deleted=allow_deleted,
                    uow=uow,
                )
                _ensure_folder_node(node, operation=operation)
                folder = await mutate(uow)
                snapshot = _folder_snapshot(folder)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_folder_event(
                user_id=actor_id,
                action=audit_action,
                snapshot=snapshot,
                message=message,
            )
            return FolderRead.model_validate(snapshot)

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

    async def _safe_log_folder_event(
        self,
        *,
        user_id: UUID,
        action: AuditAction,
        snapshot: dict[str, Any],
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Безопасно записывает событие папки в аудит.

        Ошибки записи аудита не пробрасываются выше, чтобы не ломать основную
        операцию с папкой. При ошибке пишет предупреждение в лог.

        Args:
            user_id: Идентификатор пользователя, связанного с событием.
            action: Действие аудита.
            snapshot: Снимок папки, на основе которого формируются метаданные.
            message: Сообщение события аудита.
            metadata: Дополнительные метаданные события.
        """

        try:
            merged_metadata = _audit_metadata(snapshot)
            if metadata:
                merged_metadata.update(metadata)
            await self.audit_service.log_user_event(
                user_id=user_id,
                action=action,
                result=AuditResult.SUCCESS,
                entity_type="folder",
                entity_id=cast(UUID, snapshot["node_id"]),
                resource_type=AuditResourceType.FOLDER,
                message=message,
                metadata=merged_metadata,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита папки",
                extra={
                    "action": action.value,
                    "folder_node_id": str(snapshot.get("node_id")),
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
        """Преобразует ошибку базы данных в ошибку сервиса папок.

        Args:
            exc: Исходная ошибка базы данных.
            operation: Название операции, во время которой возникла ошибка.
            message: Сообщение для создаваемой ошибки сервиса.

        Returns:
            Ошибка сервисного уровня с контекстом сервиса папок.
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


def _folder_snapshot(folder: Folder) -> dict[str, Any]:
    """Создает снимок метаданных папки.

    Args:
        folder: ORM-модель папки.

    Returns:
        Словарь с идентификаторами папки и узла, описанием, цветом, временными
        метками и снимком связанного узла, если он загружен.
    """

    return {
        "id": folder.id,
        "node_id": folder.node_id,
        "description": folder.description,
        "color": folder.color,
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
        "node": _node_snapshot(folder.node) if folder.node is not None else None,
    }


def _node_snapshot(node: FileSystemNode) -> dict[str, Any]:
    """Создает снимок метаданных узла файловой системы.

    Args:
        node: ORM-модель узла файловой системы.

    Returns:
        Словарь с идентификаторами, именем, типом, видимостью, путем, глубиной,
        авторами изменений, флагом удаления и временными метками узла.
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


def _task_snapshot(task: BackgroundTask) -> dict[str, Any]:
    """Создает краткий снимок фоновой задачи.

    Args:
        task: ORM-модель фоновой задачи.

    Returns:
        Словарь с идентификатором задачи и ее статусом.
    """

    return {
        "id": task.id,
        "status": task.status,
    }


def _ensure_folder_node(node: FileSystemNode, *, operation: str) -> None:
    """Проверяет, что узел файловой системы является папкой.

    Args:
        node: Узел файловой системы для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        ValidationServiceError: Если узел не является папкой.
    """

    if node.node_type == NodeType.FOLDER:
        return
    raise ValidationServiceError(
        "Узел файловой системы - это не папка.",
        field="node_id",
        value=node.id,
        reason="not_folder",
        details={
            "service": SERVICE_NAME,
            "operation": operation,
            "node_type": node.node_type.value,
        },
    )


def _normalize_folder_sort_by(sort_by: str) -> FolderSortField:
    """Нормализует и проверяет поле сортировки папок.

    Args:
        sort_by: Исходное поле сортировки.

    Returns:
        Нормализованное поле сортировки папок.

    Raises:
        ValidationServiceError: Если поле сортировки не поддерживается.
    """

    normalized = sort_by.strip().lower()
    if normalized not in ALLOWED_FOLDER_SORT_FIELDS:
        raise ValidationServiceError(
            "Поле сортировки неподдерживаемых папок.",
            field="sort_by",
            value=sort_by,
            reason="unsupported_sort_field",
            details={
                "service": SERVICE_NAME,
                "allowed_values": sorted(ALLOWED_FOLDER_SORT_FIELDS),
            },
        )
    return cast(FolderSortField, normalized)


def _normalize_node_sort_by(sort_by: str) -> str:
    """Нормализует и проверяет поле сортировки узлов.

    Args:
        sort_by: Исходное поле сортировки.

    Returns:
        Нормализованное поле сортировки узлов.

    Raises:
        ValidationServiceError: Если поле сортировки не поддерживается.
    """

    normalized = sort_by.strip().lower()
    allowed = {"name", "created_at", "updated_at", "deleted_at", "depth", "node_type"}
    if normalized not in allowed:
        raise ValidationServiceError(
            "Поле сортировки неподдерживаемых узлов.",
            field="sort_by",
            value=sort_by,
            reason="unsupported_sort_field",
            details={"service": SERVICE_NAME, "allowed_values": sorted(allowed)},
        )
    return normalized


def _sort_direction(sort_desc: bool) -> NodeSortDirection:
    """Возвращает направление сортировки по флагу убывания.

    Args:
        sort_desc: Нужно ли сортировать по убыванию.

    Returns:
        "desc", если sort_desc равен True, иначе "asc".
    """

    return "desc" if sort_desc else "asc"


def _audit_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Формирует метаданные папки для аудита.

    Args:
        snapshot: Снимок папки, возможно содержащий вложенный снимок узла.

    Returns:
        Словарь с JSON-совместимыми метаданными папки и связанного узла.
    """

    node = snapshot.get("node")
    metadata: dict[str, Any] = {
        "folder_id": _jsonable(snapshot.get("id")),
        "node_id": _jsonable(snapshot.get("node_id")),
        "description": snapshot.get("description"),
        "color": snapshot.get("color"),
    }
    if isinstance(node, dict):
        metadata.update(
            {
                "name": node.get("name"),
                "path": node.get("path"),
                "parent_id": _jsonable(node.get("parent_id")),
                "owner_id": _jsonable(node.get("owner_id")),
                "is_deleted": node.get("is_deleted"),
            }
        )
    return metadata


def _jsonable(value: Any) -> Any:
    """Преобразует значение в JSON-совместимый формат.

    Поддерживает примитивы, UUID и Enum. Для остальных объектов возвращает
    строковое представление.

    Args:
        value: Значение для преобразования.

    Returns:
        JSON-совместимое представление значения.
    """

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
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
        "Сервисная операция завершена без результата.",
        service=SERVICE_NAME,
        operation=operation,
    )


# Глобальный singleton-экземпляр сервиса папок.
_folders_service: FoldersService | None = None


def get_folders_service(
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    access_service: AccessService | None = None,
    audit_service: AuditService | None = None,
) -> FoldersService:
    """Возвращает экземпляр сервиса папок.

    Если передана хотя бы одна зависимость, создает новый экземпляр сервиса с
    указанными зависимостями. Если зависимости не переданы, возвращает
    глобальный singleton-экземпляр, создавая его при первом обращении.

    Args:
        uow_factory: Фабрика Unit of Work для нового экземпляра сервиса.
        access_service: Сервис доступа для нового экземпляра сервиса.
        audit_service: Сервис аудита для нового экземпляра сервиса.

    Returns:
        Экземпляр FoldersService.
    """

    if (
        uow_factory is not None
        or access_service is not None
        or audit_service is not None
    ):
        return FoldersService(
            uow_factory=uow_factory,
            access_service=access_service,
            audit_service=audit_service,
        )

    global _folders_service
    if _folders_service is None:
        _folders_service = FoldersService()
    return _folders_service
