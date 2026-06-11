import uuid
from collections.abc import Callable
from typing import Annotated, Any, cast

from fastapi import Depends, Path
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.logging import get_logger
from database.models.filesystem import FileSystemNode
from database.models.permissions import NodePermission
from database.repositories.permissions import NodePermissionsRepository
from security.dependencies.auth import DatabaseSessionDependency, forbidden_exception
from security.dependencies.users import OptionalActiveUserDependency
from security.permissions import (
    PermissionAction,
    PermissionDeniedReason,
    check_node_permission,
)

logger = get_logger(__name__)


async def get_node_by_id(
    session: AsyncSession,
    node_id: uuid.UUID,
    *,
    load_permissions: bool = True,
) -> FileSystemNode | None:
    """Возвращает объект файловой системы по идентификатору.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        node_id: Идентификатор объекта файловой системы.
        load_permissions: Нужно ли заранее загрузить связанные права доступа.

    Returns:
        Объект файловой системы или ``None``, если объект не найден.

    Raises:
        SecurityDependencyError: Если не удалось выполнить запрос к базе данных.
    """

    statement = select(FileSystemNode).where(FileSystemNode.id == node_id)

    if load_permissions:
        statement = statement.options(selectinload(FileSystemNode.permissions))

    try:
        result = await session.execute(statement)
        return result.scalar_one_or_none()

    except SQLAlchemyError as exc:
        logger.warning(
            "Не удалось загрузить узел файловой системы по идентификатору",
            extra={
                "node_id": str(node_id),
                "reason": str(exc),
                "error_type": exc.__class__.__name__,
            },
        )

        raise forbidden_exception("Не удалось проверить доступ к объекту.") from exc


async def get_ancestor_permissions(
    session: AsyncSession,
    node: FileSystemNode,
    user_id: uuid.UUID,
) -> list[NodePermission]:
    """Возвращает активные права пользователя на неудалённых предков объекта.

    Нужно для наследования прав: доступ, выданный на папку, распространяется на
    её содержимое. Одним запросом (рекурсивный CTE + join), а не обходом предков
    по одному. Удалённые предки пропускаются — грант на узел в корзине не должен
    открывать доступ к его потомкам.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        node: Узел, для которого нужно собрать права предков.
        user_id: Идентификатор пользователя.

    Returns:
        Список активных прав пользователя на предков узла.
    """

    repository = NodePermissionsRepository(session)
    return await repository.get_active_ancestor_permissions(
        node_id=node.id,
        user_id=user_id,
    )


async def _check_with_inheritance(
    session: AsyncSession,
    *,
    node: FileSystemNode,
    user: Any,
    action: PermissionAction | str,
    allow_deleted: bool,
    allow_public: bool,
) -> Any:
    """Проверяет доступ к узлу с наследованием прав от папок-предков.

    Сначала проверяет права по самому узлу. Если прямого доступа нет (право не
    найдено или недостаточно), повторяет проверку, добавив гранты предков —
    так доступ к папке распространяется на её содержимое.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        node: Объект файловой системы с загруженными ``permissions``.
        user: Текущий пользователь или ``None``.
        action: Проверяемое действие.
        allow_deleted: Разрешать ли доступ к удалённым объектам.
        allow_public: Разрешать ли публичный доступ.

    Returns:
        Результат проверки прав доступа.
    """

    result = check_node_permission(
        user=cast(Any, user),
        node=cast(Any, node),
        action=action,
        permissions=cast(Any, node.permissions),
        allow_deleted=allow_deleted,
        allow_public=allow_public,
    )
    if (
        result.denied
        and user is not None
        and result.reason
        in (
            PermissionDeniedReason.PERMISSION_NOT_FOUND,
            PermissionDeniedReason.INSUFFICIENT_PERMISSION,
        )
    ):
        inherited = await get_ancestor_permissions(session, node, user.id)
        if inherited:
            result = check_node_permission(
                user=cast(Any, user),
                node=cast(Any, node),
                action=action,
                permissions=cast(Any, list(node.permissions) + inherited),
                allow_deleted=allow_deleted,
                allow_public=allow_public,
            )
    return result


async def get_node_permissions(
    session: AsyncSession,
    node_id: uuid.UUID,
) -> list[NodePermission]:
    """Возвращает список прав доступа для объекта файловой системы.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        node_id: Идентификатор объекта файловой системы.

    Returns:
        Список прав доступа, связанных с объектом файловой системы.

    Raises:
        SecurityDependencyError: Если не удалось загрузить права доступа.
    """

    statement = select(NodePermission).where(NodePermission.node_id == node_id)

    try:
        result = await session.execute(statement)
        return list(result.scalars().all())

    except SQLAlchemyError as exc:
        logger.warning(
            "Не удалось загрузить права доступа узла",
            extra={
                "node_id": str(node_id),
                "reason": str(exc),
                "error_type": exc.__class__.__name__,
            },
        )

        raise forbidden_exception("Не удалось проверить права доступа.") from exc


def require_node_permission_dependency(
    action: PermissionAction | str,
    *,
    allow_deleted: bool = False,
    allow_public: bool = True,
) -> Callable[..., Any]:
    """Создаёт FastAPI dependency для обязательной проверки прав на объект.

    Dependency загружает объект файловой системы по ``node_id`` из path
    parameters, проверяет права текущего пользователя и выбрасывает ошибку
    доступа, если действие запрещено.

    Args:
        action: Действие, для которого нужно проверить права доступа.
        allow_deleted: Разрешать ли доступ к удалённым объектам.
        allow_public: Разрешать ли публичный доступ, если объект публичный.

    Returns:
        FastAPI dependency, которая проверяет право доступа и ничего не
        возвращает при успешной проверке.

    Raises:
        SecurityDependencyError: Если объект не найден или доступ запрещён.
    """

    async def dependency(
        node_id: Annotated[uuid.UUID, Path()],
        user: OptionalActiveUserDependency,
        session: DatabaseSessionDependency,
    ) -> None:
        """Проверяет право текущего пользователя на объект файловой системы.

        Args:
            node_id: Идентификатор объекта файловой системы из path parameters.
            user: Текущий активный пользователь или ``None``.
            session: Асинхронная SQLAlchemy-сессия.

        Returns:
            ``None``.

        Raises:
            SecurityDependencyError: Если объект не найден, права не удалось
                проверить или доступ запрещён.
        """

        node = await get_node_by_id(session, node_id)

        if node is None:
            raise forbidden_exception("Объект файловой системы не найден.")

        result = await _check_with_inheritance(
            session,
            node=node,
            user=user,
            action=action,
            allow_deleted=allow_deleted,
            allow_public=allow_public,
        )

        if result.denied:
            raise forbidden_exception("Недостаточно прав для доступа к объекту.")

    return dependency


def get_accessible_node_dependency(
    action: PermissionAction | str,
    *,
    allow_deleted: bool = False,
    allow_public: bool = True,
) -> Callable[..., Any]:
    """Создаёт FastAPI dependency для получения доступного объекта.

    Dependency загружает объект файловой системы, проверяет права текущего
    пользователя и возвращает объект, если доступ разрешён.

    Args:
        action: Действие, для которого нужно проверить права доступа.
        allow_deleted: Разрешать ли доступ к удалённым объектам.
        allow_public: Разрешать ли публичный доступ, если объект публичный.

    Returns:
        FastAPI dependency, которая возвращает доступный объект файловой
        системы.

    Raises:
        SecurityDependencyError: Если объект не найден или доступ запрещён.
    """

    async def dependency(
        node_id: Annotated[uuid.UUID, Path()],
        user: OptionalActiveUserDependency,
        session: DatabaseSessionDependency,
    ) -> FileSystemNode:
        """Возвращает объект файловой системы после проверки доступа.

        Args:
            node_id: Идентификатор объекта файловой системы из path parameters.
            user: Текущий активный пользователь или ``None``.
            session: Асинхронная SQLAlchemy-сессия.

        Returns:
            Объект файловой системы, к которому разрешён доступ.

        Raises:
            SecurityDependencyError: Если объект не найден, права не удалось
                проверить или доступ запрещён.
        """

        node = await get_node_by_id(session, node_id)

        if node is None:
            raise forbidden_exception("Объект файловой системы не найден.")

        result = await _check_with_inheritance(
            session,
            node=node,
            user=user,
            action=action,
            allow_deleted=allow_deleted,
            allow_public=allow_public,
        )

        if result.denied:
            raise forbidden_exception("Недостаточно прав для доступа к объекту.")

        return node

    return dependency


# FastAPI dependency для проверки права чтения объекта.
RequireReadNodeDependency = Depends(
    require_node_permission_dependency(PermissionAction.READ)
)

# FastAPI dependency для проверки права скачивания объекта.
RequireDownloadNodeDependency = Depends(
    require_node_permission_dependency(PermissionAction.DOWNLOAD)
)

# FastAPI dependency для проверки права записи в объект.
RequireWriteNodeDependency = Depends(
    require_node_permission_dependency(PermissionAction.WRITE)
)

# FastAPI dependency для проверки права удаления объекта.
RequireDeleteNodeDependency = Depends(
    require_node_permission_dependency(PermissionAction.DELETE)
)

# FastAPI dependency для проверки права выдачи доступа к объекту.
RequireShareNodeDependency = Depends(
    require_node_permission_dependency(PermissionAction.SHARE)
)
