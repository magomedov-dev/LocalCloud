from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from core.logging import get_logger
from database import (
    DatabaseError,
    EntityNotFoundError,
    UnitOfWorkFactory,
    create_unit_of_work_factory,
)
from database.models.enums import (
    NodeType,
    NodeVisibility,
    PermissionLevel,
    SystemRole,
    UserStatus,
)
from database.models.filesystem import FileSystemNode
from schemas.permissions import (
    EffectivePermissionRead,
    PermissionCheckRequest,
    PermissionCheckResponse,
)
from security.permissions import (
    PermissionAction,
    PermissionCheckResult,
    PermissionDeniedReason,
    SupportsNode,
    SupportsNodePermission,
    SupportsUser,
    check_node_permission,
    permission_level_allows_action,
)
from security.permissions.exceptions import PermissionCheckError, PermissionDeniedError
from services.exceptions import (
    NotFoundServiceError,
    PermissionServiceError,
    ServiceError,
    service_error_from_database,
    service_error_from_exception,
)

logger = get_logger("services.access")

SERVICE_NAME = "access"
REPOSITORY_PAGE_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class AccessUser:
    """Lightweight-представление пользователя для проверки доступа.

    Attributes:
        id: Идентификатор пользователя.
        status: Статус пользователя.
        role: Системная роль пользователя.
    """

    id: UUID
    status: UserStatus | str
    role: SystemRole | str


@dataclass(frozen=True, slots=True)
class AccessNode:
    """Lightweight-представление узла файловой системы для проверки доступа.

    Attributes:
        id: Идентификатор узла.
        owner_id: Идентификатор владельца узла.
        node_type: Тип узла файловой системы.
        visibility: Видимость узла.
        is_deleted: Признак удаления узла.
    """

    id: UUID
    owner_id: UUID
    node_type: NodeType | str
    visibility: NodeVisibility | str
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class AccessPermission:
    """Lightweight-представление разрешения на доступ к узлу.

    Attributes:
        id: Идентификатор разрешения.
        user_id: Идентификатор пользователя, которому выдано разрешение.
        permission_level: Уровень разрешения.
        can_read: Разрешено ли чтение.
        can_download: Разрешено ли скачивание.
        can_write: Разрешена ли запись.
        can_delete: Разрешено ли удаление.
        can_share: Разрешено ли предоставление доступа.
        revoked_at: Дата отзыва разрешения.
        expires_at: Дата истечения срока действия разрешения.
    """

    id: UUID
    user_id: UUID
    permission_level: PermissionLevel | str
    can_read: bool
    can_download: bool
    can_write: bool
    can_delete: bool
    can_share: bool
    revoked_at: datetime | None
    expires_at: datetime | None

    def is_active_at(self, moment: datetime) -> bool:
        """Проверяет, активно ли разрешение в указанный момент времени.

        Args:
            moment: Момент времени для проверки активности разрешения.

        Returns:
            `True`, если разрешение не отозвано и не истекло к указанному
            моменту.
        """

        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= moment:
            return False
        return True


class AccessService:
    """Единая точка входа для проверки доступа к узлам файловой системы.

    Сервис загружает узел, пользователя, роли и разрешения, после чего
    выполняет проверку через `check_node_permission()`. При необходимости
    сервис может возвращать allow/deny DTO или выбрасывать сервисную ошибку
    при отказе в доступе.

    Attributes:
        uow_factory: Фабрика UnitOfWork для создания транзакционных контекстов.
    """

    def __init__(self, *, uow_factory: UnitOfWorkFactory | None = None) -> None:
        """Инициализирует сервис доступа.

        Args:
            uow_factory: Фабрика UnitOfWork. Если не передана, создаётся
                стандартная фабрика через `create_unit_of_work_factory()`.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()

    async def check_node_access(
        self,
        request: PermissionCheckRequest,
        *,
        uow: Any | None = None,
    ) -> PermissionCheckResponse:
        """Проверяет доступ по публичному DTO запроса.

        Args:
            request: DTO с параметрами проверки доступа.
            uow: Опциональный внешний UnitOfWork. Если передан, проверка
                выполняется в его транзакционном контексте.

        Returns:
            DTO с результатом проверки доступа.

        Raises:
            ServiceError: Если проверку доступа не удалось выполнить.
        """

        return await self.check_access(
            node_id=request.node_id,
            user_id=request.user_id,
            action=request.action,
            allow_deleted=request.allow_deleted,
            allow_public=request.allow_public,
            uow=uow,
        )

    async def check_access(
        self,
        *,
        node_id: UUID,
        user_id: UUID | None,
        action: PermissionAction | str,
        allow_deleted: bool = False,
        allow_public: bool = True,
        uow: Any | None = None,
    ) -> PermissionCheckResponse:
        """Возвращает allow/deny результат без исключения при отказе.

        Args:
            node_id: Идентификатор проверяемого узла.
            user_id: Идентификатор пользователя. `None` означает анонимного
                пользователя.
            action: Действие, для которого проверяется доступ.
            allow_deleted: Можно ли проверять доступ к удалённым узлам.
            allow_public: Можно ли учитывать публичную видимость узла.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            DTO с результатом проверки доступа.

        Raises:
            PermissionServiceError: Если произошла ошибка проверки разрешений.
            ServiceError: Если проверку доступа не удалось выполнить.
        """

        operation = "check_access"
        try:
            result = await self._check_access(
                node_id=node_id,
                user_id=user_id,
                action=action,
                allow_deleted=allow_deleted,
                allow_public=allow_public,
                uow=uow,
            )
            return _check_response(result)

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось проверить доступ к узлу."
            ) from exc
        except PermissionCheckError as exc:
            raise self._permission_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при проверке доступа к узлу.",
            ) from exc

    async def require_access(
        self,
        *,
        node_id: UUID,
        user_id: UUID | None,
        action: PermissionAction | str,
        allow_deleted: bool = False,
        allow_public: bool = True,
        uow: Any | None = None,
    ) -> PermissionCheckResponse:
        """Требует доступ и выбрасывает ошибку при отказе.

        Args:
            node_id: Идентификатор проверяемого узла.
            user_id: Идентификатор пользователя. `None` означает анонимного
                пользователя.
            action: Действие, для которого требуется доступ.
            allow_deleted: Можно ли проверять доступ к удалённым узлам.
            allow_public: Можно ли учитывать публичную видимость узла.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            DTO с успешным результатом проверки доступа.

        Raises:
            PermissionServiceError: Если доступ запрещён.
            ServiceError: Если проверку доступа не удалось выполнить.
        """

        operation = "require_access"
        response = await self.check_access(
            node_id=node_id,
            user_id=user_id,
            action=action,
            allow_deleted=allow_deleted,
            allow_public=allow_public,
            uow=uow,
        )
        if response.allowed:
            return response
        raise self._denied_response_error(response, operation=operation)

    async def filter_readable_node_ids(
        self,
        *,
        uow: Any,
        nodes: Iterable[FileSystemNode],
        user_id: UUID | None,
    ) -> set[UUID]:
        """Возвращает id узлов из набора, доступных пользователю на чтение.

        Пакетный аналог одиночной проверки READ-доступа: пользователь
        загружается один раз, прямые разрешения и разрешения предков — двумя
        батч-запросами на весь набор, а сама проверка выполняется in-memory
        тем же ``check_node_permission``, что и в одиночном пути. Семантика
        совпадает с ``require_access(action=READ)`` (без удалённых узлов,
        с учётом публичной видимости): владелец/админ/публичный узел проходят
        без загрузки разрешений, наследование прав от предков учитывается
        только там, где прямых прав не хватило.

        Args:
            uow: Активный UnitOfWork с репозиториями пользователей и разрешений.
            nodes: Уже загруженные ORM-модели узлов файловой системы.
            user_id: Идентификатор пользователя. `None` — анонимный.

        Returns:
            Множество идентификаторов узлов, для которых чтение разрешено.

        Raises:
            ServiceError: Если проверку доступа не удалось выполнить.
        """

        operation = "filter_readable_node_ids"
        inheritable_reasons = (
            PermissionDeniedReason.PERMISSION_NOT_FOUND,
            PermissionDeniedReason.INSUFFICIENT_PERMISSION,
        )

        try:
            snapshots = [_node_snapshot(node) for node in nodes]
            if not snapshots:
                return set()

            access_user = await self._load_access_user(uow, user_id)

            def _check(
                snapshot: AccessNode,
                permissions: tuple[AccessPermission, ...],
            ) -> PermissionCheckResult:
                return check_node_permission(
                    user=cast(SupportsUser | None, access_user),
                    node=cast(SupportsNode, snapshot),
                    action=PermissionAction.READ,
                    permissions=cast(
                        Iterable[SupportsNodePermission], permissions
                    ),
                    allow_deleted=False,
                    allow_public=True,
                )

            allowed: set[UUID] = set()
            # Узлы, которым не хватило fast-path (владелец/админ/публичность)
            # и которые имеет смысл проверять по выданным разрешениям.
            pending: list[AccessNode] = []
            for snapshot in snapshots:
                result = _check(snapshot, ())
                if result.allowed:
                    allowed.add(snapshot.id)
                elif user_id is not None and result.reason in inheritable_reasons:
                    pending.append(snapshot)

            if not pending:
                return allowed

            direct_rows = await uow.permissions.get_permissions_for_nodes(
                node_ids=[snapshot.id for snapshot in pending],
            )
            direct_by_node: dict[UUID, list[AccessPermission]] = {}
            for row in direct_rows:
                direct_by_node.setdefault(row.node_id, []).append(
                    _permission_snapshot(row)
                )

            # Узлы, которым не хватило и прямых разрешений: для них (и только
            # для них) загружаем наследуемые права предков — как в одиночном
            # пути, где предки запрашиваются лишь после отказа по прямым правам.
            still_denied: list[tuple[AccessNode, tuple[AccessPermission, ...]]] = []
            for snapshot in pending:
                direct = tuple(direct_by_node.get(snapshot.id, ()))
                result = _check(snapshot, direct)
                if result.allowed:
                    allowed.add(snapshot.id)
                elif result.reason in inheritable_reasons:
                    still_denied.append((snapshot, direct))

            if not still_denied or user_id is None:
                return allowed

            inherited_rows = (
                await uow.permissions.get_active_ancestor_permissions_for_nodes(
                    node_ids=[snapshot.id for snapshot, _ in still_denied],
                    user_id=user_id,
                )
            )
            inherited_by_node: dict[UUID, list[AccessPermission]] = {}
            for descendant_id, row in inherited_rows:
                inherited_by_node.setdefault(descendant_id, []).append(
                    _permission_snapshot(row)
                )

            for snapshot, direct in still_denied:
                inherited = tuple(inherited_by_node.get(snapshot.id, ()))
                if not inherited:
                    continue
                result = _check(snapshot, direct + inherited)
                if result.allowed:
                    allowed.add(snapshot.id)

            return allowed

        except PermissionCheckError as exc:
            raise self._permission_error(exc, operation=operation) from exc
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось выполнить пакетную проверку доступа к узлам.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка пакетной проверки доступа.",
            ) from exc

    async def get_accessible_node(
        self,
        *,
        node_id: UUID,
        user_id: UUID | None,
        action: PermissionAction | str,
        allow_deleted: bool = False,
        allow_public: bool = True,
        uow: Any | None = None,
    ) -> FileSystemNode:
        """Возвращает узел файловой системы после успешной проверки доступа.

        Если передан внешний `uow`, возвращённый ORM-объект принадлежит тому же
        транзакционному контексту и может безопасно использоваться вызывающим
        кодом.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя. `None` означает анонимного
                пользователя.
            action: Действие, для которого требуется доступ к узлу.
            allow_deleted: Можно ли возвращать удалённый узел.
            allow_public: Можно ли учитывать публичную видимость узла.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            ORM-модель доступного узла файловой системы.

        Raises:
            NotFoundServiceError: Если узел не найден.
            PermissionServiceError: Если доступ к узлу запрещён.
            ServiceError: Если узел не удалось получить.
        """

        operation = "get_accessible_node"
        accessible_node: FileSystemNode | None = None
        try:
            if uow is not None:
                node = await self._load_node(uow, node_id, allow_deleted=allow_deleted)
                result = await self._check_loaded_access(
                    uow=uow,
                    node=node,
                    user_id=user_id,
                    action=action,
                    allow_deleted=allow_deleted,
                    allow_public=allow_public,
                )
                if result.denied:
                    raise self._denied_result_error(result, operation=operation)
                accessible_node = node

            else:
                async with self.uow_factory() as own_uow:
                    node = await self._load_node(
                        own_uow, node_id, allow_deleted=allow_deleted
                    )
                    result = await self._check_loaded_access(
                        uow=own_uow,
                        node=node,
                        user_id=user_id,
                        action=action,
                        allow_deleted=allow_deleted,
                        allow_public=allow_public,
                    )
                    if result.denied:
                        raise self._denied_result_error(result, operation=operation)
                    accessible_node = node

            if accessible_node is None:
                raise ServiceError(
                    "Сервис доступа не вернул узел файловой системы.",
                    service=SERVICE_NAME,
                    operation=operation,
                )
            return accessible_node

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить доступный узел файловой системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении доступного узла.",
            ) from exc

    async def get_effective_permissions(
        self,
        *,
        node_id: UUID,
        user_id: UUID | None,
        allow_deleted: bool = False,
        allow_public: bool = True,
        uow: Any | None = None,
    ) -> EffectivePermissionRead:
        """Формирует эффективные флаги доступа пользователя к узлу.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя. `None` означает анонимного
                пользователя.
            allow_deleted: Можно ли учитывать удалённый узел.
            allow_public: Можно ли учитывать публичную видимость узла.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            DTO с эффективным уровнем доступа и флагами разрешённых действий.

        Raises:
            PermissionServiceError: Если произошла ошибка проверки разрешений.
            ServiceError: Если эффективные права не удалось получить.
        """

        operation = "get_effective_permissions"
        try:
            result = await self._check_access(
                node_id=node_id,
                user_id=user_id,
                action=PermissionAction.READ,
                allow_deleted=allow_deleted,
                allow_public=allow_public,
                uow=uow,
            )
            return _effective_permission_read(result)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить эффективные права доступа.",
            ) from exc
        except PermissionCheckError as exc:
            raise self._permission_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении эффективных прав.",
            ) from exc

    async def can_read_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> bool:
        """Проверяет, может ли пользователь читать узел.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            `True`, если чтение разрешено.
        """

        return await self._can(
            node_id=node_id, user_id=user_id, action=PermissionAction.READ, uow=uow
        )

    async def can_download_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> bool:
        """Проверяет, может ли пользователь скачивать узел.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            `True`, если скачивание разрешено.
        """

        return await self._can(
            node_id=node_id, user_id=user_id, action=PermissionAction.DOWNLOAD, uow=uow
        )

    async def can_write_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> bool:
        """Проверяет, может ли пользователь изменять узел.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            `True`, если запись разрешена.
        """

        return await self._can(
            node_id=node_id, user_id=user_id, action=PermissionAction.WRITE, uow=uow
        )

    async def can_delete_node(
        self,
        *,
        node_id: UUID,
        user_id: UUID | None,
        allow_deleted: bool = False,
        uow: Any | None = None,
    ) -> bool:
        """Проверяет, может ли пользователь удалить узел.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            allow_deleted: Можно ли проверять доступ к уже удалённому узлу.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            `True`, если удаление разрешено.
        """

        return await self._can(
            node_id=node_id,
            user_id=user_id,
            action=PermissionAction.DELETE,
            allow_deleted=allow_deleted,
            uow=uow,
        )

    async def can_share_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> bool:
        """Проверяет, может ли пользователь делиться доступом к узлу.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            `True`, если предоставление доступа разрешено.
        """

        return await self._can(
            node_id=node_id, user_id=user_id, action=PermissionAction.SHARE, uow=uow
        )

    async def can_manage_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> bool:
        """Проверяет, может ли пользователь управлять узлом.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            `True`, если управление узлом разрешено.
        """

        return await self._can(
            node_id=node_id, user_id=user_id, action=PermissionAction.MANAGE, uow=uow
        )

    async def require_read_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> PermissionCheckResponse:
        """Требует право чтения узла.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            DTO успешной проверки доступа.

        Raises:
            PermissionServiceError: Если чтение запрещено.
        """

        return await self.require_access(
            node_id=node_id, user_id=user_id, action=PermissionAction.READ, uow=uow
        )

    async def require_download_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> PermissionCheckResponse:
        """Требует право скачивания узла.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            DTO успешной проверки доступа.

        Raises:
            PermissionServiceError: Если скачивание запрещено.
        """

        return await self.require_access(
            node_id=node_id, user_id=user_id, action=PermissionAction.DOWNLOAD, uow=uow
        )

    async def require_write_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> PermissionCheckResponse:
        """Требует право изменения узла.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            DTO успешной проверки доступа.

        Raises:
            PermissionServiceError: Если запись запрещена.
        """

        return await self.require_access(
            node_id=node_id, user_id=user_id, action=PermissionAction.WRITE, uow=uow
        )

    async def require_delete_node(
        self,
        *,
        node_id: UUID,
        user_id: UUID | None,
        allow_deleted: bool = False,
        uow: Any | None = None,
    ) -> PermissionCheckResponse:
        """Требует право удаления узла.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            allow_deleted: Можно ли проверять доступ к уже удалённому узлу.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            DTO успешной проверки доступа.

        Raises:
            PermissionServiceError: Если удаление запрещено.
        """

        return await self.require_access(
            node_id=node_id,
            user_id=user_id,
            action=PermissionAction.DELETE,
            allow_deleted=allow_deleted,
            uow=uow,
        )

    async def require_share_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> PermissionCheckResponse:
        """Требует право предоставления доступа к узлу.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            DTO успешной проверки доступа.

        Raises:
            PermissionServiceError: Если предоставление доступа запрещено.
        """

        return await self.require_access(
            node_id=node_id, user_id=user_id, action=PermissionAction.SHARE, uow=uow
        )

    async def require_manage_node(
        self, *, node_id: UUID, user_id: UUID | None, uow: Any | None = None
    ) -> PermissionCheckResponse:
        """Требует право управления узлом.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            DTO успешной проверки доступа.

        Raises:
            PermissionServiceError: Если управление узлом запрещено.
        """

        return await self.require_access(
            node_id=node_id, user_id=user_id, action=PermissionAction.MANAGE, uow=uow
        )

    async def _can(
        self,
        *,
        node_id: UUID,
        user_id: UUID | None,
        action: PermissionAction,
        allow_deleted: bool = False,
        allow_public: bool = True,
        uow: Any | None = None,
    ) -> bool:
        """Выполняет bool-проверку доступа для конкретного действия.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            action: Проверяемое действие.
            allow_deleted: Можно ли проверять доступ к удалённым узлам.
            allow_public: Можно ли учитывать публичную видимость узла.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            `True`, если действие разрешено.
        """

        response = await self.check_access(
            node_id=node_id,
            user_id=user_id,
            action=action,
            allow_deleted=allow_deleted,
            allow_public=allow_public,
            uow=uow,
        )
        return response.allowed

    async def _check_access(
        self,
        *,
        node_id: UUID,
        user_id: UUID | None,
        action: PermissionAction | str,
        allow_deleted: bool,
        allow_public: bool,
        uow: Any | None,
    ) -> PermissionCheckResult:
        """Выполняет низкоуровневую проверку доступа к узлу.

        Args:
            node_id: Идентификатор узла.
            user_id: Идентификатор пользователя.
            action: Проверяемое действие.
            allow_deleted: Можно ли проверять доступ к удалённым узлам.
            allow_public: Можно ли учитывать публичную видимость узла.
            uow: Опциональный внешний UnitOfWork.

        Returns:
            Результат проверки доступа из слоя `security.permissions`.

        Raises:
            ServiceError: Если результат проверки не был сформирован.
        """

        result: PermissionCheckResult | None = None

        if uow is not None:
            node = await self._load_node(uow, node_id, allow_deleted=allow_deleted)
            result = await self._check_loaded_access(
                uow=uow,
                node=node,
                user_id=user_id,
                action=action,
                allow_deleted=allow_deleted,
                allow_public=allow_public,
            )
        else:
            async with self.uow_factory() as own_uow:
                node = await self._load_node(
                    own_uow, node_id, allow_deleted=allow_deleted
                )
                result = await self._check_loaded_access(
                    uow=own_uow,
                    node=node,
                    user_id=user_id,
                    action=action,
                    allow_deleted=allow_deleted,
                    allow_public=allow_public,
                )

        if result is None:
            raise ServiceError(
                "Сервис доступа не вернул результат проверки.",
                service=SERVICE_NAME,
                operation="check_access",
            )
        return result

    async def _check_loaded_access(
        self,
        *,
        uow: Any,
        node: FileSystemNode,
        user_id: UUID | None,
        action: PermissionAction | str,
        allow_deleted: bool,
        allow_public: bool,
    ) -> PermissionCheckResult:
        """Проверяет доступ к уже загруженному узлу.

        Args:
            uow: Активный UnitOfWork для загрузки пользователя и разрешений.
            node: Уже загруженная ORM-модель узла файловой системы.
            user_id: Идентификатор пользователя.
            action: Проверяемое действие.
            allow_deleted: Можно ли разрешать доступ к удалённому узлу.
            allow_public: Можно ли учитывать публичную видимость узла.

        Returns:
            Результат проверки доступа.
        """

        access_node = _node_snapshot(node)
        access_user = await self._load_access_user(uow, user_id)
        permissions = await self._load_node_permissions(uow, node.id)

        result = check_node_permission(
            user=cast(SupportsUser | None, access_user),
            node=cast(SupportsNode, access_node),
            action=action,
            permissions=cast(Iterable[SupportsNodePermission], permissions),
            allow_deleted=allow_deleted,
            allow_public=allow_public,
        )

        # Наследование прав от родительских папок: если на самом узле прямого
        # доступа нет (или он недостаточен), учитываем гранты, выданные на
        # узлах-предках — поделиться папкой должно давать доступ к её
        # содержимому. Запрашиваем предков только когда это реально нужно, чтобы
        # не нагружать частый путь владельца/администратора.
        if (
            not result.allowed
            and user_id is not None
            and result.reason
            in (
                PermissionDeniedReason.PERMISSION_NOT_FOUND,
                PermissionDeniedReason.INSUFFICIENT_PERMISSION,
            )
        ):
            inherited = await self._load_ancestor_permissions(uow, node, user_id)
            if inherited:
                inherited_result = check_node_permission(
                    user=cast(SupportsUser | None, access_user),
                    node=cast(SupportsNode, access_node),
                    action=action,
                    permissions=cast(
                        Iterable[SupportsNodePermission], permissions + inherited
                    ),
                    allow_deleted=allow_deleted,
                    allow_public=allow_public,
                )
                if inherited_result.allowed:
                    return inherited_result

        return result

    async def _load_node(
        self, uow: Any, node_id: UUID, *, allow_deleted: bool
    ) -> FileSystemNode:
        """Загружает узел файловой системы для проверки доступа.

        Args:
            uow: Активный UnitOfWork с репозиторием узлов.
            node_id: Идентификатор узла.
            allow_deleted: Если `True`, разрешает загрузку удалённого узла.

        Returns:
            ORM-модель узла файловой системы.

        Raises:
            DatabaseError: Если узел не найден или произошла ошибка базы данных.
        """

        if allow_deleted:
            return await uow.nodes.get_required_by_id(node_id)
        return await uow.nodes.get_required_active_node_by_id(node_id)

    async def _load_access_user(
        self, uow: Any, user_id: UUID | None
    ) -> AccessUser | None:
        """Загружает lightweight-представление пользователя для проверки доступа.

        Args:
            uow: Активный UnitOfWork с репозиторием пользователей.
            user_id: Идентификатор пользователя. Если `None`, пользователь
                считается анонимным.

        Returns:
            `AccessUser` с системной ролью пользователя или `None` для
            анонимного пользователя.

        Raises:
            DatabaseError: Если пользователь не найден или произошла ошибка базы
                данных.
        """

        if user_id is None:
            return None

        user = await uow.users.get_required_user_by_id(user_id)
        return AccessUser(
            id=user.id,
            status=user.status,
            role=user.role,
        )

    async def _load_node_permissions(
        self, uow: Any, node_id: UUID
    ) -> tuple[AccessPermission, ...]:
        """Загружает все разрешения доступа для узла.

        Разрешения загружаются постранично, чтобы не зависеть от ограничений
        репозитория на размер одной выборки.

        Args:
            uow: Активный UnitOfWork с репозиторием разрешений.
            node_id: Идентификатор узла.

        Returns:
            Кортеж lightweight-представлений разрешений узла.
        """

        permissions: list[AccessPermission] = []
        offset = 0
        while True:
            chunk = await uow.permissions.get_node_permissions(
                node_id=node_id,
                active_only=False,
                offset=offset,
                limit=REPOSITORY_PAGE_LIMIT,
            )
            permissions.extend(_permission_snapshot(permission) for permission in chunk)
            if len(chunk) < REPOSITORY_PAGE_LIMIT:
                break
            offset += REPOSITORY_PAGE_LIMIT
        return tuple(permissions)

    async def _load_ancestor_permissions(
        self, uow: Any, node: FileSystemNode, user_id: UUID | None
    ) -> tuple[AccessPermission, ...]:
        """Загружает активные разрешения пользователя на неудалённых предков узла.

        Используется для наследования прав: грант на папку распространяется на
        её содержимое. Одним запросом (рекурсивный CTE + join), а не обходом
        предков по одному. Удалённые предки пропускаются — грант на узел в
        корзине не должен открывать доступ к его потомкам.

        Args:
            uow: Активный UnitOfWork с репозиторием разрешений.
            node: Узел, для которого собираются разрешения предков.
            user_id: Идентификатор пользователя (None — анонимный, без наследования).

        Returns:
            Кортеж lightweight-представлений разрешений предков узла.
        """

        if user_id is None:
            return ()
        permissions = await uow.permissions.get_active_ancestor_permissions(
            node_id=node.id,
            user_id=user_id,
        )
        return tuple(_permission_snapshot(permission) for permission in permissions)

    @staticmethod
    def _denied_response_error(
        response: PermissionCheckResponse, *, operation: str
    ) -> PermissionServiceError:
        """Создаёт сервисную ошибку из deny-ответа проверки доступа.

        Args:
            response: DTO с отрицательным результатом проверки доступа.
            operation: Название операции сервиса.

        Returns:
            Ошибка `PermissionServiceError` с деталями отказа.
        """

        return PermissionServiceError(
            response.message or "Недостаточно прав для доступа к узлу.",
            user_id=response.user_id,
            resource_type="filesystem_node",
            resource_id=response.node_id,
            action=response.action,
            required_permission=response.action,
            reason=response.denied_reason,
            details={"service": SERVICE_NAME, "operation": operation},
        )

    @staticmethod
    def _denied_result_error(
        result: PermissionCheckResult, *, operation: str
    ) -> PermissionServiceError:
        """Создаёт сервисную ошибку из deny-результата проверки доступа.

        Args:
            result: Результат проверки доступа.
            operation: Название операции сервиса.

        Returns:
            Ошибка `PermissionServiceError` с деталями отказа.
        """

        return PermissionServiceError(
            _message_for_denied_reason(result.reason),
            user_id=result.user_id,
            resource_type="filesystem_node",
            resource_id=result.node_id,
            action=result.action,
            required_permission=result.action,
            reason=result.reason,
            details={"service": SERVICE_NAME, "operation": operation},
        )

    @staticmethod
    def _permission_error(
        exc: PermissionCheckError, *, operation: str
    ) -> PermissionServiceError:
        """Преобразует ошибку проверки прав в сервисную ошибку.

        Args:
            exc: Ошибка слоя `security.permissions`.
            operation: Название операции сервиса.

        Returns:
            Ошибка `PermissionServiceError`.
        """

        return PermissionServiceError(
            str(exc),
            details={"service": SERVICE_NAME, "operation": operation, **exc.to_dict()},
            cause=exc,
        )

    @staticmethod
    def _database_error(
        exc: DatabaseError, *, operation: str, message: str
    ) -> ServiceError:
        """Преобразует ошибку базы данных в сервисную ошибку доступа.

        Args:
            exc: Исходная ошибка базы данных.
            operation: Название операции сервиса.
            message: Сообщение для итоговой сервисной ошибки.

        Returns:
            Сервисная ошибка, соответствующая ошибке базы данных.
        """

        if isinstance(exc, EntityNotFoundError):
            return NotFoundServiceError(
                message,
                entity_name="FileSystemNode",
                details={"service": SERVICE_NAME, "operation": operation},
                cause=exc,
            )
        return service_error_from_database(
            exc, operation=operation, message=message, service=SERVICE_NAME
        )

    @staticmethod
    def _unexpected_error(
        exc: Exception, *, operation: str, message: str
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
            exc, operation=operation, message=message, service=SERVICE_NAME
        )


def _node_snapshot(node: FileSystemNode) -> AccessNode:
    """Создаёт lightweight-представление узла файловой системы.

    Args:
        node: ORM-модель узла файловой системы.

    Returns:
        Объект `AccessNode` для передачи в слой проверки прав.
    """

    return AccessNode(
        id=node.id,
        owner_id=node.owner_id,
        node_type=node.node_type,
        visibility=node.visibility,
        is_deleted=bool(node.is_deleted),
    )


def _permission_snapshot(permission: Any) -> AccessPermission:
    """Создаёт lightweight-представление разрешения доступа.

    Args:
        permission: ORM-модель или объект разрешения с ожидаемыми атрибутами.

    Returns:
        Объект `AccessPermission` для передачи в слой проверки прав.
    """

    return AccessPermission(
        id=permission.id,
        user_id=permission.user_id,
        permission_level=permission.permission_level,
        can_read=bool(permission.can_read),
        can_download=bool(permission.can_download),
        can_write=bool(permission.can_write),
        can_delete=bool(permission.can_delete),
        can_share=bool(permission.can_share),
        revoked_at=permission.revoked_at,
        expires_at=permission.expires_at,
    )


def _check_response(result: PermissionCheckResult) -> PermissionCheckResponse:
    """Преобразует результат проверки доступа в DTO ответа.

    Args:
        result: Результат проверки доступа.

    Returns:
        DTO `PermissionCheckResponse`.

    Raises:
        PermissionDeniedError: Если результат не содержит идентификатор узла.
    """

    return PermissionCheckResponse(
        allowed=result.allowed,
        node_id=_require_node_id(result),
        user_id=result.user_id,
        action=result.action,
        permission_level=result.permission_level,
        denied_reason=result.reason,
        message=None if result.allowed else _message_for_denied_reason(result.reason),
    )


def _effective_permission_read(
    result: PermissionCheckResult,
) -> EffectivePermissionRead:
    """Преобразует результат проверки в DTO эффективных прав.

    Args:
        result: Результат проверки доступа, обычно для действия `READ`.

    Returns:
        DTO с эффективными флагами доступа к узлу.

    Raises:
        PermissionDeniedError: Если результат не содержит идентификатор узла.
    """

    can_read = _allows(result, PermissionAction.READ)
    can_download = _allows(result, PermissionAction.DOWNLOAD)
    can_write = _allows(result, PermissionAction.WRITE)
    can_delete = _allows(result, PermissionAction.DELETE)
    can_share = _allows(result, PermissionAction.SHARE)

    return EffectivePermissionRead(
        node_id=_require_node_id(result),
        user_id=result.user_id,
        permission_level=result.permission_level,
        source_permission_id=None,
        is_owner=result.is_owner,
        is_admin=result.is_admin,
        is_public=bool(
            result.details and result.details.get("source") == "public_node"
        ),
        expires_at=None,
        can_read=can_read,
        can_download=can_download,
        can_write=can_write,
        can_delete=can_delete,
        can_share=can_share,
    )


def _allows(result: PermissionCheckResult, action: PermissionAction) -> bool:
    """Проверяет, разрешено ли действие на основе результата проверки.

    Args:
        result: Результат проверки доступа.
        action: Действие, для которого вычисляется эффективный флаг.

    Returns:
        `True`, если действие разрешено с учётом владельца, администратора,
        публичного доступа или уровня разрешения.
    """

    if result.denied:
        return False
    if result.is_admin or result.is_owner:
        return True
    if result.details and result.details.get("source") == "public_node":
        return action in {PermissionAction.READ, PermissionAction.DOWNLOAD}
    if result.permission_level is None:
        return result.allowed and action == result.action
    return permission_level_allows_action(result.permission_level, action)


def _require_node_id(result: PermissionCheckResult) -> UUID:
    """Возвращает идентификатор узла из результата проверки.

    Args:
        result: Результат проверки доступа.

    Returns:
        Идентификатор узла.

    Raises:
        PermissionDeniedError: Если результат проверки не содержит
            идентификатор узла.
    """

    if result.node_id is None:
        raise PermissionDeniedError(
            "Результат проверки доступа не содержит идентификатор узла.",
            action=result.action,
            reason=result.reason,
            user_id=result.user_id,
        )
    return result.node_id


def _message_for_denied_reason(reason: PermissionDeniedReason | None) -> str:
    """Возвращает человекочитаемое сообщение для причины отказа.

    Args:
        reason: Причина отказа в доступе.

    Returns:
        Сообщение об отказе в доступе. Если причина неизвестна или отсутствует,
        возвращается сообщение по умолчанию.
    """

    default_message = "Недостаточно прав для доступа к узлу."
    messages = {
        PermissionDeniedReason.ANONYMOUS_USER: "Требуется авторизация для доступа к узлу.",
        PermissionDeniedReason.INACTIVE_USER: "Учетная запись неактивна или заблокирована.",
        PermissionDeniedReason.DELETED_NODE: "Узел файловой системы удален.",
        PermissionDeniedReason.NOT_OWNER: "Операция доступна только владельцу узла.",
        PermissionDeniedReason.NOT_ADMIN: "Операция доступна только администратору.",
        PermissionDeniedReason.PERMISSION_NOT_FOUND: "Разрешение на доступ к узлу не найдено.",
        PermissionDeniedReason.PERMISSION_REVOKED: "Разрешение на доступ к узлу отозвано.",
        PermissionDeniedReason.PERMISSION_EXPIRED: "Срок действия разрешения истек.",
        PermissionDeniedReason.INSUFFICIENT_PERMISSION: "Недостаточно прав для доступа к узлу.",
        PermissionDeniedReason.PRIVATE_NODE: "Узел закрыт для публичного доступа.",
        PermissionDeniedReason.INVALID_ACTION: "Действие доступа не поддерживается.",
    }
    if reason is None:
        return default_message
    return messages.get(reason, default_message)


def get_access_service(
    *, uow_factory: UnitOfWorkFactory | None = None
) -> AccessService:
    """Создаёт экземпляр сервиса доступа.

    Args:
        uow_factory: Фабрика UnitOfWork. Если не передана, сервис создаст
            стандартную фабрику самостоятельно.

    Returns:
        Экземпляр `AccessService`.
    """

    return AccessService(uow_factory=uow_factory)
