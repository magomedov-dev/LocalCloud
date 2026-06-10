from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID

from core.logging import get_logger
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    AuditResult,
    FilePreviewStatus,
    FileProcessingStatus,
    NodeType,
    NodeVisibility,
    StorageObjectStatus,
)
from database.models.filesystem import File, FileSystemNode
from schemas.common import PageMeta, PageResponse
from schemas.files import (
    FileListItem,
    FileMoveRequest,
    FilePreviewRead,
    FileRead,
    FileRenameRequest,
    FileSearchQuery,
    FileUpdateRequest,
)
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

logger = get_logger("services.files")

SERVICE_NAME = "files"
REPOSITORY_PAGE_LIMIT = 1000
ALLOWED_FILE_SORT_FIELDS: set[str] = {
    "name",
    "path",
    "size_bytes",
    "mime_type",
    "extension",
    "created_at",
    "updated_at",
}


@dataclass(frozen=True, slots=True)
class FileMetadataCreate:
    """Входные данные для фиксации загруженного объекта как файлового узла.

    Attributes:
        name: Имя создаваемого файла.
        storage_bucket: Имя storage bucket, где лежит физический объект.
        storage_key: Ключ физического объекта в storage.
        size_bytes: Размер файла в байтах.
        parent_id: Идентификатор родительской папки. Если `None`, файл
            создаётся в корне владельца.
        mime_type: MIME-тип файла.
        extension: Расширение файла.
        checksum: Контрольная сумма файла.
        checksum_algorithm: Алгоритм контрольной суммы.
        preview_status: Начальный статус preview.
        visibility: Видимость создаваемого файлового узла.
        change_comment: Комментарий к начальной версии файла.
    """

    name: str
    storage_bucket: str
    storage_key: str
    size_bytes: int
    parent_id: UUID | None = None
    mime_type: str | None = None
    extension: str | None = None
    checksum: str | None = None
    checksum_algorithm: str | None = None
    preview_status: FilePreviewStatus = FilePreviewStatus.NOT_REQUIRED
    visibility: NodeVisibility = NodeVisibility.PRIVATE
    change_comment: str | None = None


class FilesService:
    """Бизнес-сервис для файловых метаданных, перемещений и preview.

    Сервис отвечает за операции над файловыми узлами и связанными строками
    `File`. Перед изменением или чтением данных сервис проверяет доступ к узлам
    через `AccessService`, а после успешных изменений пытается записать событие
    аудита.

    Attributes:
        uow_factory: Фабрика UnitOfWork для создания транзакционных контекстов.
        access_service: Сервис проверки доступа к узлам файловой системы.
        audit_service: Сервис аудита для записи событий файлов.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
        access_service: AccessService | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        """Инициализирует сервис файлов.

        Args:
            uow_factory: Фабрика UnitOfWork. Если не передана, создаётся
                стандартная фабрика через `create_unit_of_work_factory()`.
            access_service: Сервис проверки доступа. Если не передан, создаётся
                сервис доступа с той же фабрикой UnitOfWork.
            audit_service: Сервис аудита. Если не передан, создаётся сервис
                аудита с той же фабрикой UnitOfWork.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.access_service = access_service or get_access_service(
            uow_factory=self.uow_factory
        )
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory
        )

    async def create_file_metadata(
        self,
        data: FileMetadataCreate,
        *,
        owner_id: UUID,
        actor_id: UUID | None = None,
    ) -> FileRead:
        """Создаёт файловый узел и метаданные файла.

        Args:
            data: Данные создаваемого файла и его физического объекта.
            owner_id: Идентификатор владельца файла.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если
                не передан, используется `owner_id`.

        Returns:
            DTO созданного файла.

        Raises:
            PermissionServiceError: Если пользователь не может создать файл в
                корне или в указанной папке.
            ValidationServiceError: Если родительский узел не является папкой
                или принадлежит другому владельцу.
            ServiceError: Если метаданные файла не удалось создать.
        """

        operation = "create_file_metadata"
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
                        "Только владелец может создавать файлы корневого уровня.",
                        user_id=resolved_actor_id,
                        resource_type="filesystem_root",
                        resource_id=owner_id,
                        action=PermissionAction.WRITE,
                        reason="not_owner",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                file = await uow.files.create_file_with_node(
                    owner_id=owner_id,
                    parent_id=data.parent_id,
                    name=data.name,
                    storage_bucket=data.storage_bucket,
                    storage_key=data.storage_key,
                    size_bytes=data.size_bytes,
                    mime_type=data.mime_type,
                    extension=data.extension,
                    checksum=data.checksum,
                    checksum_algorithm=data.checksum_algorithm,
                    storage_status=StorageObjectStatus.AVAILABLE,
                    processing_status=FileProcessingStatus.READY,
                    preview_status=data.preview_status,
                    visibility=data.visibility,
                    created_by=resolved_actor_id,
                    check_owner_exists=True,
                    check_conflict=True,
                    flush=True,
                    refresh=True,
                )
                file = await uow.files.get_required_by_id(file.id)
                snapshot = _file_snapshot(file)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_file_event(
                user_id=resolved_actor_id,
                action=AuditAction.FILE_UPLOADED,
                snapshot=snapshot,
                message="Созданы метаданные файла.",
            )
            return FileRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось создать метаданные файла.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось создать метаданные файла.",
            ) from exc

    async def get_file(
        self,
        node_id: UUID,
        *,
        user_id: UUID | None,
        allow_deleted: bool = False,
        allow_public: bool = True,
    ) -> FileRead:
        """Возвращает файл по идентификатору узла.

        Args:
            node_id: Идентификатор файлового узла.
            user_id: Идентификатор пользователя. `None` означает анонимного
                пользователя.
            allow_deleted: Можно ли читать удалённый узел.
            allow_public: Можно ли учитывать публичную видимость узла.

        Returns:
            DTO найденного файла.

        Raises:
            ValidationServiceError: Если узел не является файлом.
            PermissionServiceError: Если доступ к файлу запрещён.
            ServiceError: Если файл не удалось загрузить.
        """

        operation = "get_file"
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
                _ensure_file_node(node, operation=operation)
                file = await uow.files.get_required_by_node_id(
                    node.id,
                    include_deleted_node=allow_deleted,
                )
                snapshot = _file_snapshot(file)

            if snapshot is None:
                raise _empty_result_error(operation)
            return FileRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось загрузить файл.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось загрузить файл.",
            ) from exc

    async def get_file_by_id(
        self,
        file_id: UUID,
        *,
        user_id: UUID | None,
        allow_deleted: bool = False,
        allow_public: bool = True,
    ) -> FileRead:
        """Возвращает файл по идентификатору строки `File`.

        Args:
            file_id: Идентификатор файла.
            user_id: Идентификатор пользователя. `None` означает анонимного
                пользователя.
            allow_deleted: Можно ли читать файл с удалённым узлом.
            allow_public: Можно ли учитывать публичную видимость узла.

        Returns:
            DTO найденного файла.

        Raises:
            ValidationServiceError: Если связанный узел не является файлом.
            PermissionServiceError: Если доступ к файлу запрещён.
            ServiceError: Если файл не удалось загрузить.
        """

        operation = "get_file_by_id"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                file = await uow.files.get_required_by_id(file_id)
                await self.access_service.require_access(
                    node_id=file.node_id,
                    user_id=user_id,
                    action=PermissionAction.READ,
                    allow_deleted=allow_deleted,
                    allow_public=allow_public,
                    uow=uow,
                )
                if file.node is not None:
                    _ensure_file_node(file.node, operation=operation)
                snapshot = _file_snapshot(file)

            if snapshot is None:
                raise _empty_result_error(operation)
            return FileRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось загрузить файл."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось загрузить файл."
            ) from exc

    async def update_file(
        self,
        node_id: UUID,
        data: FileUpdateRequest,
        *,
        actor_id: UUID,
    ) -> FileRead:
        """Обновляет технические метаданные файла.

        Args:
            node_id: Идентификатор файлового узла.
            data: Данные обновления метаданных файла.
            actor_id: Идентификатор пользователя, выполняющего обновление.

        Returns:
            DTO обновлённого файла.

        Raises:
            ValidationServiceError: Если узел не является файлом.
            PermissionServiceError: Если у пользователя нет права записи.
            ServiceError: Если метаданные файла не удалось обновить.
        """

        operation = "update_file"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.WRITE,
                    uow=uow,
                )
                _ensure_file_node(node, operation=operation)
                file = await uow.files.update_metadata(
                    node_id=node.id,
                    mime_type=data.mime_type,
                    extension=data.extension,
                    checksum=data.checksum,
                    checksum_algorithm=data.checksum_algorithm,
                    flush=True,
                    refresh=True,
                )
                snapshot = _file_snapshot(file)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_file_event(
                user_id=actor_id,
                action=AuditAction.FILE_UPDATED,
                snapshot=snapshot,
                message="Обновлены метаданные файла.",
            )
            return FileRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось обновить метаданные файла.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось обновить метаданные файла.",
            ) from exc

    async def rename_file(
        self,
        node_id: UUID,
        data: FileRenameRequest,
        *,
        actor_id: UUID,
    ) -> FileRead:
        """Переименовывает файл.

        Args:
            node_id: Идентификатор файлового узла.
            data: Данные с новым именем файла.
            actor_id: Идентификатор пользователя, выполняющего переименование.

        Returns:
            DTO переименованного файла.

        Raises:
            ValidationServiceError: Если узел не является файлом.
            PermissionServiceError: Если у пользователя нет права записи.
            ServiceError: Если файл не удалось переименовать.
        """

        operation = "rename_file"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.WRITE,
                    uow=uow,
                )
                _ensure_file_node(node, operation=operation)
                await uow.nodes.rename_node(
                    node_id=node.id,
                    new_name=data.name,
                    updated_by=actor_id,
                    flush=True,
                    refresh=False,
                )
                file = await uow.files.get_required_by_node_id(node.id)
                snapshot = _file_snapshot(file)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_file_event(
                user_id=actor_id,
                action=AuditAction.FILE_RENAMED,
                snapshot=snapshot,
                message="Файл переименован.",
            )
            return FileRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось переименовать файл."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось переименовать файл."
            ) from exc

    async def move_file(
        self,
        node_id: UUID,
        data: FileMoveRequest,
        *,
        actor_id: UUID,
    ) -> FileRead:
        """Перемещает файл в другую папку или в корень владельца.

        Args:
            node_id: Идентификатор файлового узла.
            data: Данные перемещения файла.
            actor_id: Идентификатор пользователя, выполняющего перемещение.

        Returns:
            DTO перемещённого файла.

        Raises:
            PermissionServiceError: Если пользователь не может переместить файл
                в целевое расположение.
            ValidationServiceError: Если целевой родитель не является папкой или
                принадлежит другому владельцу.
            ServiceError: Если файл не удалось переместить.
        """

        operation = "move_file"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.WRITE,
                    uow=uow,
                )
                _ensure_file_node(node, operation=operation)

                if data.target_parent_id is not None:
                    parent = await self.access_service.get_accessible_node(
                        node_id=data.target_parent_id,
                        user_id=actor_id,
                        action=PermissionAction.WRITE,
                        uow=uow,
                    )
                    _ensure_folder_node(parent, operation=operation)
                    if parent.owner_id != node.owner_id:
                        raise ValidationServiceError(
                            "Целевая папка принадлежит другому владельцу.",
                            field="target_parent_id",
                            value=data.target_parent_id,
                            reason="owner_mismatch",
                            details={"service": SERVICE_NAME, "operation": operation},
                        )
                elif actor_id != node.owner_id:
                    raise PermissionServiceError(
                        "Только владелец может переместить файл на корневой уровень.",
                        user_id=actor_id,
                        resource_type="filesystem_root",
                        resource_id=node.owner_id,
                        action=PermissionAction.WRITE,
                        reason="not_owner",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                await uow.nodes.move_node(
                    node_id=node.id,
                    new_parent_id=data.target_parent_id,
                    updated_by=actor_id,
                    flush=True,
                    refresh=False,
                )
                file = await uow.files.get_required_by_node_id(node.id)
                snapshot = _file_snapshot(file)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_file_event(
                user_id=actor_id,
                action=AuditAction.FILE_MOVED,
                snapshot=snapshot,
                message="Файл перемещен.",
            )
            return FileRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось переместить файл."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось переместить файл."
            ) from exc

    async def delete_file(self, node_id: UUID, *, actor_id: UUID) -> FileRead:
        """Мягко удаляет файл, перемещая его в корзину.

        Args:
            node_id: Идентификатор файлового узла.
            actor_id: Идентификатор пользователя, выполняющего удаление.

        Returns:
            DTO удалённого файла.

        Raises:
            ValidationServiceError: Если узел не является файлом.
            PermissionServiceError: Если у пользователя нет права удаления.
            ServiceError: Если файл не удалось удалить.
        """

        operation = "delete_file"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.DELETE,
                    uow=uow,
                )
                _ensure_file_node(node, operation=operation)
                await uow.nodes.soft_delete_node(
                    node_id=node.id,
                    deleted_by=actor_id,
                    flush=True,
                    refresh=False,
                )
                file = await uow.files.get_required_by_node_id(
                    node.id,
                    include_deleted_node=True,
                )
                snapshot = _file_snapshot(file)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_file_event(
                user_id=actor_id,
                action=AuditAction.FILE_DELETED,
                snapshot=snapshot,
                message="Файл перемещен в корзину.",
            )
            return FileRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось удалить файл."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось удалить файл."
            ) from exc

    async def restore_file(self, node_id: UUID, *, actor_id: UUID) -> FileRead:
        """Восстанавливает файл из корзины.

        Args:
            node_id: Идентификатор файлового узла.
            actor_id: Идентификатор пользователя, выполняющего восстановление.

        Returns:
            DTO восстановленного файла.

        Raises:
            ValidationServiceError: Если узел не является файлом.
            PermissionServiceError: Если у пользователя нет права восстановления.
            ServiceError: Если файл не удалось восстановить.
        """

        operation = "restore_file"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.DELETE,
                    allow_deleted=True,
                    uow=uow,
                )
                _ensure_file_node(node, operation=operation)
                await uow.nodes.restore_node(
                    node_id=node.id,
                    updated_by=actor_id,
                    flush=True,
                    refresh=False,
                )
                file = await uow.files.get_required_by_node_id(node.id)
                snapshot = _file_snapshot(file)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_file_event(
                user_id=actor_id,
                action=AuditAction.FILE_RESTORED,
                snapshot=snapshot,
                message="Файл восстановлен из корзины.",
            )
            return FileRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось восстановить файл."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation=operation, message="Не удалось восстановить файл."
            ) from exc

    async def purge_file(self, node_id: UUID, *, actor_id: UUID) -> None:
        """Окончательно удаляет метаданные файла и его версии.

        Метод удаляет версии файла, строку `File` и помечает связанный узел как
        окончательно очищенный.

        Args:
            node_id: Идентификатор файлового узла.
            actor_id: Идентификатор пользователя, выполняющего очистку.

        Raises:
            ValidationServiceError: Если узел не является файлом.
            PermissionServiceError: Если у пользователя нет права управления.
            ServiceError: Если файл не удалось окончательно удалить.
        """

        operation = "purge_file"
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
                _ensure_file_node(node, operation=operation)
                file = await uow.files.get_required_by_node_id(
                    node.id,
                    include_deleted_node=True,
                )
                snapshot = _file_snapshot(file)
                await uow.files.delete_by_node_id(node.id, flush=False, required=True)
                await uow.nodes.mark_purged(node_id=node.id, flush=True)
                await uow.commit()

            if snapshot is not None:
                await self._safe_log_file_event(
                    user_id=actor_id,
                    action=AuditAction.FILE_PURGED,
                    snapshot=snapshot,
                    message="Метаданные файла удалены.",
                )

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось очистить файл.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось очистить файл.",
            ) from exc

    async def search_files(
        self,
        params: FileSearchQuery,
        *,
        user_id: UUID | None,
    ) -> PageResponse[FileListItem]:
        """Ищет файлы с фильтрацией, сортировкой и пагинацией.

        При поиске внутри папки сервис проверяет доступ на чтение к этой папке.
        При поиске в корне требуется аутентифицированный владелец.

        Args:
            params: Параметры поиска файлов.
            user_id: Идентификатор пользователя, выполняющего поиск.

        Returns:
            Страница найденных файлов.

        Raises:
            PermissionServiceError: Если пользователь не может выполнять поиск
                в указанной области.
            ValidationServiceError: Если фильтр владельца не совпадает с
                владельцем родительской папки или параметры сортировки
                некорректны.
            ServiceError: Если поиск файлов не удалось выполнить.
        """

        operation = "search_files"
        page: PageResponse[FileListItem] | None = None

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
                    _ensure_folder_node(parent, operation=operation)
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
                        "Для поиска файлов на корневом уровне требуется аутентифицированный владелец.",
                        action=PermissionAction.READ,
                        reason="anonymous_user",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                elif user_id != owner_id:
                    raise PermissionServiceError(
                        "Поиск файлов на корневом уровне доступен только владельцу.",
                        user_id=user_id,
                        resource_type="filesystem_root",
                        resource_id=owner_id,
                        action=PermissionAction.READ,
                        reason="not_owner",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                sort_by = _validate_file_sort_field(params.sort_by)
                total = await uow.files.count_user_files_filtered(
                    owner_id=owner_id,
                    parent_id=params.parent_id,
                    include_deleted_nodes=params.include_deleted,
                    query=params.query,
                    mime_type=params.mime_type,
                    extension=params.extension,
                    storage_status=params.storage_status,
                    processing_status=params.processing_status,
                    preview_status=params.preview_status,
                    min_size_bytes=params.min_size_bytes,
                    max_size_bytes=params.max_size_bytes,
                    created_from=params.created_from,
                    created_to=params.created_to,
                    updated_from=params.updated_from,
                    updated_to=params.updated_to,
                )
                files = await uow.files.search_user_files(
                    owner_id=owner_id,
                    parent_id=params.parent_id,
                    include_deleted_nodes=params.include_deleted,
                    query=params.query,
                    mime_type=params.mime_type,
                    extension=params.extension,
                    storage_status=params.storage_status,
                    processing_status=params.processing_status,
                    preview_status=params.preview_status,
                    min_size_bytes=params.min_size_bytes,
                    max_size_bytes=params.max_size_bytes,
                    created_from=params.created_from,
                    created_to=params.created_to,
                    updated_from=params.updated_from,
                    updated_to=params.updated_to,
                    sort_by=sort_by,
                    sort_direction="desc" if params.sort_desc else "asc",
                    offset=params.offset,
                    limit=params.limit,
                )
                items = [
                    FileListItem.model_validate(_file_snapshot(file)) for file in files
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

            if page is None:
                raise _empty_result_error(operation)
            return page

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось выполнить поиск по файлам.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось выполнить поиск по файлам.",
            ) from exc

    async def get_preview(
        self,
        node_id: UUID,
        *,
        user_id: UUID | None,
    ) -> FilePreviewRead:
        """Возвращает состояние preview файла.

        Args:
            node_id: Идентификатор файлового узла.
            user_id: Идентификатор пользователя, запрашивающего preview.

        Returns:
            DTO состояния preview файла.

        Raises:
            ValidationServiceError: Если узел не является файлом.
            PermissionServiceError: Если у пользователя нет права чтения.
            ServiceError: Если состояние preview не удалось получить.
        """

        operation = "get_preview"
        preview: FilePreviewRead | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=user_id,
                    action=PermissionAction.READ,
                    uow=uow,
                )
                _ensure_file_node(node, operation=operation)
                file = await uow.files.get_required_by_node_id(node.id)
                preview = FilePreviewRead(
                    file_id=file.id,
                    preview_status=file.preview_status,
                    preview_available=bool(file.preview_available),
                    presigned_url=None,
                    expires_at=None,
                    mime_type=file.mime_type,
                    message=_preview_message(file),
                )

            if preview is None:
                raise _empty_result_error(operation)
            return preview

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось загрузить состояние предварительного просмотра файла.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось загрузить состояние предварительного просмотра файла.",
            ) from exc

    async def mark_preview_pending(
        self,
        node_id: UUID,
        *,
        actor_id: UUID,
    ) -> FileRead:
        """Помечает preview файла как ожидающее генерации.

        Args:
            node_id: Идентификатор файлового узла.
            actor_id: Идентификатор пользователя, выполняющего операцию.

        Returns:
            DTO файла с обновлённым статусом preview.

        Raises:
            ServiceError: Если статус preview не удалось обновить.
        """

        return await self._update_preview_state(
            node_id=node_id,
            actor_id=actor_id,
            operation="mark_preview_pending",
            status=FilePreviewStatus.PENDING,
            message="Предварительный просмотр файлов поставлен в очередь.",
        )

    async def mark_preview_generating(
        self,
        node_id: UUID,
        *,
        actor_id: UUID,
    ) -> FileRead:
        """Помечает preview файла как находящееся в процессе генерации.

        Args:
            node_id: Идентификатор файлового узла.
            actor_id: Идентификатор пользователя, выполняющего операцию.

        Returns:
            DTO файла с обновлённым статусом preview.

        Raises:
            ServiceError: Если статус preview не удалось обновить.
        """

        return await self._update_preview_state(
            node_id=node_id,
            actor_id=actor_id,
            operation="mark_preview_generating",
            status=FilePreviewStatus.GENERATING,
            message="Запущена генерация предварительного просмотра файла.",
        )

    async def mark_preview_failed(
        self,
        node_id: UUID,
        *,
        actor_id: UUID,
    ) -> FileRead:
        """Помечает генерацию preview файла как неуспешную.

        Args:
            node_id: Идентификатор файлового узла.
            actor_id: Идентификатор пользователя, выполняющего операцию.

        Returns:
            DTO файла с обновлённым статусом preview.

        Raises:
            ServiceError: Если статус preview не удалось обновить.
        """

        return await self._update_preview_state(
            node_id=node_id,
            actor_id=actor_id,
            operation="mark_preview_failed",
            status=FilePreviewStatus.FAILED,
            message="Не удалось создать предварительный просмотр файла.",
        )

    async def set_preview_ready(
        self,
        node_id: UUID,
        *,
        preview_storage_key: str,
        actor_id: UUID,
    ) -> FileRead:
        """Помечает preview файла как готовое.

        Args:
            node_id: Идентификатор файлового узла.
            preview_storage_key: Storage key сгенерированного preview.
            actor_id: Идентификатор пользователя, выполняющего операцию.

        Returns:
            DTO файла с готовым preview.

        Raises:
            ServiceError: Если preview не удалось пометить готовым.
        """

        return await self._update_preview_state(
            node_id=node_id,
            actor_id=actor_id,
            operation="set_preview_ready",
            status=FilePreviewStatus.READY,
            preview_storage_key=preview_storage_key,
            audit_action=AuditAction.FILE_PREVIEW_GENERATED,
            message="Создан предварительный просмотр файла.",
        )

    async def _update_preview_state(
        self,
        *,
        node_id: UUID,
        actor_id: UUID,
        operation: str,
        status: FilePreviewStatus,
        message: str,
        preview_storage_key: str | None = None,
        audit_action: AuditAction = AuditAction.FILE_UPDATED,
    ) -> FileRead:
        """Обновляет статус preview файла.

        Args:
            node_id: Идентификатор файлового узла.
            actor_id: Идентификатор пользователя, выполняющего операцию.
            operation: Название операции сервиса.
            status: Новый статус preview.
            message: Сообщение для audit-события.
            preview_storage_key: Storage key preview-объекта.
            audit_action: Audit action для записи события.

        Returns:
            DTO файла с обновлённым состоянием preview.

        Raises:
            ValidationServiceError: Если узел не является файлом.
            PermissionServiceError: Если у пользователя нет права записи.
            ServiceError: Если состояние preview не удалось обновить.
        """

        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=node_id,
                    user_id=actor_id,
                    action=PermissionAction.WRITE,
                    uow=uow,
                )
                _ensure_file_node(node, operation=operation)
                if status == FilePreviewStatus.READY:
                    file = await uow.files.set_preview_ready(
                        node_id=node.id,
                        preview_storage_key=cast(str, preview_storage_key),
                        flush=True,
                        refresh=True,
                    )
                else:
                    file = await uow.files.update_preview(
                        node_id=node.id,
                        preview_status=status,
                        preview_storage_key=preview_storage_key,
                        flush=True,
                        refresh=True,
                    )
                snapshot = _file_snapshot(file)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_file_event(
                user_id=actor_id,
                action=audit_action,
                snapshot=snapshot,
                message=message,
            )
            return FileRead.model_validate(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось обновить состояние предварительного просмотра.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось обновить состояние предварительного просмотра.",
            ) from exc

    async def _safe_log_file_event(
        self,
        *,
        user_id: UUID,
        action: AuditAction,
        snapshot: dict[str, Any],
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Безопасно записывает audit-событие файла.

        Ошибки записи аудита не прерывают основную файловую операцию и
        логируются как предупреждения.

        Args:
            user_id: Идентификатор пользователя, связанного с событием.
            action: Тип audit-события.
            snapshot: Снимок файла, по которому формируются audit metadata.
            message: Сообщение события аудита.
            metadata: Дополнительные metadata, которые нужно добавить к
                стандартным данным файла.
        """

        try:
            merged_metadata = _audit_metadata(snapshot)
            if metadata:
                merged_metadata.update(metadata)
            await self.audit_service.log_user_event(
                user_id=user_id,
                action=action,
                result=AuditResult.SUCCESS,
                entity_type="file",
                entity_id=cast(UUID, snapshot["node_id"]),
                resource_type=AuditResourceType.FILE,
                message=message,
                metadata=merged_metadata,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита файла",
                extra={
                    "action": action.value,
                    "file_node_id": str(snapshot.get("node_id")),
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
        """Преобразует ошибку базы данных в сервисную ошибку файлов.

        Args:
            exc: Исходная ошибка базы данных.
            operation: Название операции сервиса.
            message: Сообщение для итоговой сервисной ошибки.

        Returns:
            Сервисная ошибка, соответствующая ошибке базы данных.
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
        """Логирует непредвиденную ошибку и преобразует её в `ServiceError`.

        Args:
            exc: Исходное исключение.
            operation: Название операции сервиса.
            message: Сообщение для логирования и итоговой сервисной ошибки.

        Returns:
            Сервисная ошибка, созданная из исходного исключения.
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


async def _query_files(
    uow: Any,
    *,
    params: FileSearchQuery,
    owner_id: UUID,
) -> list[File]:
    """Выполняет SQL-запрос поиска файлов.

    Args:
        uow: Активный UnitOfWork с SQLAlchemy session.
        params: Параметры фильтрации, сортировки и поиска файлов.
        owner_id: Идентификатор владельца, в области которого выполняется
            поиск.

    Returns:
        Список ORM-моделей файлов, соответствующих фильтрам.

    Raises:
        ValidationServiceError: Если поле сортировки не поддерживается.
        DatabaseError: Если выполнение запроса завершилось ошибкой.
    """

    sort_by = _validate_file_sort_field(params.sort_by)
    return await uow.files.search_user_files(
        owner_id=owner_id,
        parent_id=params.parent_id,
        include_deleted_nodes=params.include_deleted,
        query=params.query,
        mime_type=params.mime_type,
        extension=params.extension,
        storage_status=params.storage_status,
        processing_status=params.processing_status,
        preview_status=params.preview_status,
        min_size_bytes=params.min_size_bytes,
        max_size_bytes=params.max_size_bytes,
        created_from=params.created_from,
        created_to=params.created_to,
        updated_from=params.updated_from,
        updated_to=params.updated_to,
        sort_by=sort_by,
        sort_direction="desc" if params.sort_desc else "asc",
        offset=0,
        limit=REPOSITORY_PAGE_LIMIT,
    )


def _file_snapshot(file: File) -> dict[str, Any]:
    """Создаёт словарный снимок файла для DTO.

    Args:
        file: ORM-модель файла.

    Returns:
        Словарь с полями файла и вложенным снимком узла, если узел загружен.
    """

    return {
        "id": file.id,
        "node_id": file.node_id,
        "size_bytes": file.size_bytes,
        "mime_type": file.mime_type,
        "extension": file.extension,
        "checksum": file.checksum,
        "checksum_algorithm": file.checksum_algorithm,
        "storage_status": file.storage_status,
        "processing_status": file.processing_status,
        "preview_status": file.preview_status,
        "created_at": file.created_at,
        "updated_at": file.updated_at,
        "node": _node_snapshot(file.node) if file.node is not None else None,
    }


def _node_snapshot(node: FileSystemNode) -> dict[str, Any]:
    """Создаёт словарный снимок узла файловой системы.

    Args:
        node: ORM-модель узла файловой системы.

    Returns:
        Словарь с полями узла.
    """

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
    }


def _files_page(
    files: list[File],
    *,
    limit: int,
    offset: int,
) -> PageResponse[FileListItem]:
    """Создаёт страницу файлов из полного списка результатов.

    Args:
        files: Полный список найденных файлов.
        limit: Максимальное количество элементов на странице.
        offset: Смещение первой записи.

    Returns:
        DTO страницы файлов с метаданными пагинации.
    """

    page_files = files[offset : offset + limit]
    items = [FileListItem.model_validate(_file_snapshot(file)) for file in page_files]
    return PageResponse(
        items=items,
        meta=PageMeta(
            limit=limit,
            offset=offset,
            total=len(files),
            count=len(items),
        ),
    )


def _ensure_file_node(node: FileSystemNode, *, operation: str) -> None:
    """Проверяет, что узел файловой системы является файлом.

    Args:
        node: Проверяемый узел файловой системы.
        operation: Название операции сервиса для деталей ошибки.

    Raises:
        ValidationServiceError: Если узел не является файлом.
    """

    if node.node_type == NodeType.FILE:
        return
    raise ValidationServiceError(
        "Узел файловой системы - это не файл.",
        field="node_id",
        value=node.id,
        reason="not_file",
        details={
            "service": SERVICE_NAME,
            "operation": operation,
            "node_type": node.node_type.value,
        },
    )


def _ensure_folder_node(node: FileSystemNode, *, operation: str) -> None:
    """Проверяет, что узел файловой системы является папкой.

    Args:
        node: Проверяемый узел файловой системы.
        operation: Название операции сервиса для деталей ошибки.

    Raises:
        ValidationServiceError: Если узел не является папкой.
    """

    if node.node_type == NodeType.FOLDER:
        return
    raise ValidationServiceError(
        "Узел файловой системы - это не папка.",
        field="parent_id",
        value=node.id,
        reason="not_folder",
        details={
            "service": SERVICE_NAME,
            "operation": operation,
            "node_type": node.node_type.value,
        },
    )


def _validate_file_sort_field(sort_by: str) -> str:
    """Проверяет и нормализует поле сортировки файлов.

    Args:
        sort_by: Имя поля сортировки.

    Returns:
        Нормализованное имя поля сортировки.

    Raises:
        ValidationServiceError: Если поле сортировки не входит в
            `ALLOWED_FILE_SORT_FIELDS`.
    """

    normalized = sort_by.strip().lower()
    if normalized not in ALLOWED_FILE_SORT_FIELDS:
        raise ValidationServiceError(
            "Поле сортировки неподдерживаемых файлов.",
            field="sort_by",
            value=sort_by,
            reason="unsupported_sort_field",
            details={
                "service": SERVICE_NAME,
                "allowed_values": sorted(ALLOWED_FILE_SORT_FIELDS),
            },
        )

    return normalized


def _validate_pagination(*, limit: int, offset: int) -> None:
    """Проверяет параметры пагинации.

    Args:
        limit: Максимальное количество элементов.
        offset: Смещение первой записи.

    Raises:
        ValidationServiceError: Если `limit` меньше 1, превышает
            `REPOSITORY_PAGE_LIMIT` или `offset` отрицательный.
    """

    if limit < 1 or limit > REPOSITORY_PAGE_LIMIT:
        raise ValidationServiceError(
            "Недопустимое ограничение на разбивку на страницы.",
            field="limit",
            value=limit,
            reason="out_of_range",
            details={"service": SERVICE_NAME, "max_limit": REPOSITORY_PAGE_LIMIT},
        )
    if offset < 0:
        raise ValidationServiceError(
            "Недопустимое смещение разбивки на страницы.",
            field="offset",
            value=offset,
            reason="negative_offset",
            details={"service": SERVICE_NAME},
        )


def _preview_message(file: File) -> str:
    """Возвращает человекочитаемое сообщение для статуса preview.

    Args:
        file: ORM-модель файла.

    Returns:
        Сообщение, соответствующее `file.preview_status`.
    """

    messages: dict[FilePreviewStatus, str] = {
        FilePreviewStatus.NOT_REQUIRED: "Предварительный просмотр этого файла не требуется.",
        FilePreviewStatus.PENDING: "Генерация предварительного просмотра поставлена в очередь.",
        FilePreviewStatus.GENERATING: "Выполняется генерация предварительного просмотра.",
        FilePreviewStatus.READY: "Предварительный просмотр готов.",
        FilePreviewStatus.FAILED: "Не удалось создать предварительный просмотр.",
    }
    return messages[file.preview_status]


def _audit_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Создаёт metadata для audit-события файла.

    Args:
        snapshot: Словарный снимок файла.

    Returns:
        JSON-сериализуемый словарь с ключевыми метаданными файла и связанным
        узлом, если он присутствует в снимке.
    """

    node = snapshot.get("node")
    metadata: dict[str, Any] = {
        "file_id": _jsonable(snapshot.get("id")),
        "node_id": _jsonable(snapshot.get("node_id")),
        "size_bytes": snapshot.get("size_bytes"),
        "mime_type": snapshot.get("mime_type"),
        "extension": snapshot.get("extension"),
        "checksum_algorithm": snapshot.get("checksum_algorithm"),
        "storage_status": _jsonable(snapshot.get("storage_status")),
        "processing_status": _jsonable(snapshot.get("processing_status")),
        "preview_status": _jsonable(snapshot.get("preview_status")),
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
    """Преобразует значение в JSON-сериализуемый формат.

    Args:
        value: Значение для преобразования.

    Returns:
        JSON-сериализуемое представление значения.
    """

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Iterable):
        return [_jsonable(item) for item in value]
    return str(value)


def _empty_result_error(operation: str) -> ServiceError:
    """Создаёт ошибку отсутствующего результата сервисной операции.

    Args:
        operation: Название операции сервиса.

    Returns:
        Ошибка `ServiceError` с информацией о сервисе и операции.
    """

    return ServiceError(
        "Сервисная операция завершена безрезультатно.",
        service=SERVICE_NAME,
        operation=operation,
    )


# Глобальный singleton-экземпляр сервиса файлов.
_files_service: FilesService | None = None


def get_files_service(
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    access_service: AccessService | None = None,
    audit_service: AuditService | None = None,
) -> FilesService:
    """Создаёт или возвращает singleton экземпляр сервиса файлов.

    Если передана хотя бы одна зависимость, создаётся новый экземпляр
    `FilesService`. Если зависимости не переданы, используется ленивый
    singleton `_files_service`.

    Args:
        uow_factory: Фабрика UnitOfWork.
        access_service: Сервис проверки доступа.
        audit_service: Сервис аудита.

    Returns:
        Экземпляр `FilesService`.
    """

    if (
        uow_factory is not None
        or access_service is not None
        or audit_service is not None
    ):
        return FilesService(
            uow_factory=uow_factory,
            access_service=access_service,
            audit_service=audit_service,
        )

    global _files_service
    if _files_service is None:
        _files_service = FilesService()
    return _files_service
