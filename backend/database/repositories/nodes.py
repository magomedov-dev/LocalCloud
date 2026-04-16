from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import NodeType, NodeVisibility
from database.models.filesystem import FileSystemNode
from database.models.users import User
from database.repositories.base import BaseRepository

NodeSortField = Literal[
    "name",
    "created_at",
    "updated_at",
    "deleted_at",
    "depth",
    "node_type",
]

NodeSortDirection = Literal["asc", "desc"]


class FileSystemNodeRepository(BaseRepository[FileSystemNode]):
    """Репозиторий для работы с узлами файловой системы.

    Инкапсулирует операции получения, создания, поиска, перемещения,
    переименования, изменения видимости, soft delete, восстановления,
    окончательного удаления и подсчёта узлов файловой системы.

    Работает с моделью ``FileSystemNode`` через асинхронную SQLAlchemy-сессию.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий узлов файловой системы.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """
        super().__init__(session=session, model=FileSystemNode)

    # ------------------------------------------------------------------
    # Получение узлов
    # ------------------------------------------------------------------

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> FileSystemNode | None:
        """Возвращает узел файловой системы по идентификатору.

        Дополнительно загружает связанные сущности: родителя, файл, папку
        и элемент корзины.

        Args:
            entity_id: Идентификатор узла файловой системы.

        Returns:
            Узел файловой системы, если он найден, иначе `None`.
        """

        statement = (
            select(FileSystemNode)
            .where(FileSystemNode.id == entity_id)
            .options(
                selectinload(FileSystemNode.parent),
                selectinload(FileSystemNode.file),
                selectinload(FileSystemNode.folder),
                selectinload(FileSystemNode.trash_item),
                selectinload(FileSystemNode.owner),
                selectinload(FileSystemNode.creator),
                selectinload(FileSystemNode.updater),
                selectinload(FileSystemNode.deleter),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_id",
        )

    async def get_required_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> FileSystemNode:
        """Возвращает узел файловой системы по идентификатору.

        Args:
            entity_id: Идентификатор узла файловой системы.

        Returns:
            Найденный узел файловой системы.

        Raises:
            EntityNotFoundError: Если узел не найден.
        """

        node = await self.get_by_id(entity_id)

        if node is None:
            raise EntityNotFoundError(
                "FileSystemNode",
                entity_id=entity_id,
                repository=self.repository_name,
            )

        return node

    async def get_active_node_by_id(
        self,
        node_id: uuid.UUID,
    ) -> FileSystemNode | None:
        """Возвращает активный неудалённый узел файловой системы.

        Дополнительно загружает связанные сущности: родителя, файл и папку.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            Активный узел, если он найден, иначе `None`.
        """

        statement = (
            select(FileSystemNode)
            .where(
                FileSystemNode.id == node_id,
                FileSystemNode.is_deleted.is_(False),
            )
            .options(
                selectinload(FileSystemNode.parent),
                selectinload(FileSystemNode.file),
                selectinload(FileSystemNode.folder),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_active_node_by_id",
        )

    async def get_required_active_node_by_id(
        self,
        node_id: uuid.UUID,
    ) -> FileSystemNode:
        """Возвращает активный неудалённый узел файловой системы.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            Найденный активный узел.

        Raises:
            EntityNotFoundError: Если активный узел не найден.
        """

        node = await self.get_active_node_by_id(node_id)

        if node is None:
            raise EntityNotFoundError(
                "FileSystemNode",
                entity_id=node_id,
                repository=self.repository_name,
                message="Активный узел файловой системы не найден.",
            )

        return node

    async def get_by_owner_and_path(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        include_deleted: bool = False,
    ) -> FileSystemNode | None:
        """Возвращает узел пользователя по материализованному пути.

        Args:
            owner_id: Идентификатор владельца узла.
            path: Материализованный путь узла.
            include_deleted: Учитывать ли удалённые узлы.

        Returns:
            Узел файловой системы, если он найден, иначе `None`.

        Raises:
            InvalidQueryError: Если путь пустой или некорректный.
        """

        normalized_path = self._normalize_path(path)

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.path == normalized_path,
        ]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        statement = (
            select(FileSystemNode)
            .where(*conditions)
            .options(
                selectinload(FileSystemNode.parent),
                selectinload(FileSystemNode.file),
                selectinload(FileSystemNode.folder),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_owner_and_path",
        )

    async def get_nodes_by_ids(
        self,
        node_ids: list[uuid.UUID],
        *,
        include_deleted: bool = True,
    ) -> list[FileSystemNode]:
        """Возвращает список узлов по набору идентификаторов.

        Args:
            node_ids: Список идентификаторов узлов.
            include_deleted: Включать ли удалённые узлы.

        Returns:
            Список найденных узлов. Если список ID пустой, возвращается пустой список.
        """

        if not node_ids:
            return []

        conditions: list[Any] = [FileSystemNode.id.in_(node_ids)]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        statement = (
            select(FileSystemNode)
            .where(*conditions)
            .options(
                selectinload(FileSystemNode.file),
                selectinload(FileSystemNode.folder),
            )
        )

        return await self.scalars_all(
            statement,
            operation="get_nodes_by_ids",
        )

    # ------------------------------------------------------------------
    # Списки
    # ------------------------------------------------------------------

    async def get_root_nodes(
        self,
        *,
        owner_id: uuid.UUID,
        include_deleted: bool = False,
        node_type: NodeType | None = None,
        offset: int = 0,
        limit: int = 100,
        sort_by: NodeSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[FileSystemNode]:
        """Возвращает корневые узлы пользователя.

        Корневыми считаются узлы без родительского узла.

        Args:
            owner_id: Идентификатор владельца узлов.
            include_deleted: Включать ли удалённые узлы.
            node_type: Фильтр по типу узла.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список корневых узлов пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.parent_id.is_(None),
        ]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        if node_type is not None:
            conditions.append(FileSystemNode.node_type == node_type)

        statement = (
            select(FileSystemNode)
            .options(
                selectinload(FileSystemNode.file),
                selectinload(FileSystemNode.folder),
            )
            .where(*conditions)
            .order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_root_nodes",
        )

    async def get_children(
        self,
        *,
        parent_id: uuid.UUID,
        include_deleted: bool = False,
        node_type: NodeType | None = None,
        offset: int = 0,
        limit: int = 100,
        sort_by: NodeSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[FileSystemNode]:
        """Возвращает дочерние узлы указанной папки.

        Args:
            parent_id: Идентификатор родительского узла.
            include_deleted: Включать ли удалённые узлы.
            node_type: Фильтр по типу узла.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список дочерних узлов.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions: list[Any] = [FileSystemNode.parent_id == parent_id]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        if node_type is not None:
            conditions.append(FileSystemNode.node_type == node_type)

        statement = (
            select(FileSystemNode)
            .options(
                selectinload(FileSystemNode.file),
                selectinload(FileSystemNode.folder),
            )
            .where(*conditions)
            .order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_children",
        )

    async def get_active_children(
        self,
        *,
        parent_id: uuid.UUID,
        node_type: NodeType | None = None,
        offset: int = 0,
        limit: int = 100,
        sort_by: NodeSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[FileSystemNode]:
        """Возвращает неудалённые дочерние узлы.

        Args:
            parent_id: Идентификатор родительского узла.
            node_type: Фильтр по типу узла.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список активных дочерних узлов.
        """

        return await self.get_children(
            parent_id=parent_id,
            include_deleted=False,
            node_type=node_type,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def get_deleted_children(
        self,
        *,
        parent_id: uuid.UUID,
        node_type: NodeType | None = None,
        offset: int = 0,
        limit: int = 100,
        sort_by: NodeSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[FileSystemNode]:
        """Возвращает дочерние узлы с учётом удалённых записей.

        Args:
            parent_id: Идентификатор родительского узла.
            node_type: Фильтр по типу узла.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список дочерних узлов, включая удалённые.
        """

        return await self.get_children(
            parent_id=parent_id,
            include_deleted=True,
            node_type=node_type,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_deleted_nodes(
        self,
        *,
        owner_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
        sort_by: NodeSortField = "deleted_at",
        sort_direction: NodeSortDirection = "desc",
    ) -> list[FileSystemNode]:
        """Возвращает удалённые узлы пользователя.

        Args:
            owner_id: Идентификатор владельца узлов.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список удалённых узлов пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(FileSystemNode)
            .where(
                FileSystemNode.owner_id == owner_id,
                FileSystemNode.is_deleted.is_(True),
            )
            .options(
                selectinload(FileSystemNode.file),
                selectinload(FileSystemNode.folder),
            )
            .order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="list_deleted_nodes",
        )

    # ------------------------------------------------------------------
    # Иерархия
    # ------------------------------------------------------------------

    async def get_descendants(
        self,
        *,
        node_id: uuid.UUID,
        include_self: bool = False,
        include_deleted: bool = True,
        order_by_depth: bool = True,
    ) -> list[FileSystemNode]:
        """Возвращает всех потомков узла через рекурсивный CTE.

        Args:
            node_id: Идентификатор корневого узла.
            include_self: Включать ли сам корневой узел в результат.
            include_deleted: Включать ли удалённые узлы.
            order_by_depth: Сортировать ли результат по глубине и имени.

        Returns:
            Список потомков узла.

        Raises:
            EntityNotFoundError: Если исходный узел не найден.
        """

        root_node = await self.get_required_by_id(node_id)

        base_conditions: list[Any]

        if include_self:
            base_conditions = [FileSystemNode.id == root_node.id]
        else:
            base_conditions = [FileSystemNode.parent_id == root_node.id]

        if not include_deleted:
            base_conditions.append(FileSystemNode.is_deleted.is_(False))

        base_query = select(FileSystemNode).where(*base_conditions)

        descendants_cte = base_query.cte(
            name="file_system_descendants",
            recursive=True,
        )

        child_alias = aliased(FileSystemNode)

        recursive_conditions: list[Any] = [
            child_alias.parent_id == descendants_cte.c.id,
        ]

        if not include_deleted:
            recursive_conditions.append(child_alias.is_deleted.is_(False))

        descendants_cte = descendants_cte.union_all(
            select(child_alias).where(*recursive_conditions),
        )

        statement = select(FileSystemNode).join(
            descendants_cte,
            FileSystemNode.id == descendants_cte.c.id,
        )

        if order_by_depth:
            statement = statement.order_by(
                FileSystemNode.depth.asc(),
                FileSystemNode.name.asc(),
            )

        return await self.scalars_all(
            statement,
            operation="get_descendants",
        )

    async def get_ancestors(
        self,
        *,
        node_id: uuid.UUID,
        include_self: bool = False,
        include_deleted: bool = True,
    ) -> list[FileSystemNode]:
        """Возвращает предков узла от родителя до корневого уровня.

        Args:
            node_id: Идентификатор узла.
            include_self: Включать ли сам узел в результат.
            include_deleted: Включать ли удалённые узлы.

        Returns:
            Список предков от ближайшего родителя к корню.

        Raises:
            EntityNotFoundError: Если исходный узел не найден.
        """

        node = await self.get_required_by_id(node_id)

        ancestors: list[FileSystemNode] = []

        if include_self and (include_deleted or not node.is_deleted):
            ancestors.append(node)

        current_parent_id = node.parent_id

        while current_parent_id is not None:
            parent = await self.get_by_id(current_parent_id)

            if parent is None:
                break

            if include_deleted or not parent.is_deleted:
                ancestors.append(parent)

            current_parent_id = parent.parent_id

        return ancestors

    async def get_breadcrumbs(
        self,
        *,
        node_id: uuid.UUID,
        include_self: bool = True,
        include_deleted: bool = True,
    ) -> list[FileSystemNode]:
        """Возвращает путь от корня до указанного узла.

        Args:
            node_id: Идентификатор узла.
            include_self: Включать ли сам узел в результат.
            include_deleted: Включать ли удалённые узлы.

        Returns:
            Список узлов от корня до указанного узла.

        Raises:
            EntityNotFoundError: Если исходный узел не найден.
        """

        ancestors = await self.get_ancestors(
            node_id=node_id,
            include_self=include_self,
            include_deleted=include_deleted,
        )

        return list(reversed(ancestors))

    # ------------------------------------------------------------------
    # Создание узлов
    # ------------------------------------------------------------------

    async def create_node(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        node_type: NodeType,
        parent_id: uuid.UUID | None = None,
        path: str | None = None,
        depth: int | None = None,
        visibility: NodeVisibility = NodeVisibility.PRIVATE,
        created_by: uuid.UUID | None = None,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_owner_exists: bool = False,
        check_conflict: bool = True,
    ) -> FileSystemNode:
        """Создаёт новый узел файловой системы.

        Метод создаёт только запись в ``file_system_nodes``. Связанные записи
        в таблицах ``files`` или ``folders`` должны создаваться соответствующими
        репозиториями.

        Args:
            owner_id: Идентификатор владельца узла.
            name: Имя узла.
            node_type: Тип узла.
            parent_id: Идентификатор родительской папки.
            path: Явно заданный материализованный путь.
            depth: Явно заданная глубина узла.
            visibility: Видимость узла.
            created_by: Идентификатор пользователя, создавшего узел.
            updated_by: Идентификатор пользователя, обновившего узел.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_owner_exists: Проверять ли существование владельца.
            check_conflict: Проверять ли конфликт имени в папке.

        Returns:
            Созданный узел файловой системы.

        Raises:
            InvalidQueryError: Если имя, путь, глубина или родительский узел
                некорректны.
            EntityNotFoundError: Если владелец или родительский узел не найден.
            DuplicateEntityError: Если в папке уже существует активный узел
                с таким именем.
        """

        normalized_name = self._validate_node_name(name)

        if check_owner_exists:
            await self._ensure_user_exists(owner_id)

        parent: FileSystemNode | None = None

        if parent_id is not None:
            parent = await self.get_required_by_id(parent_id)
            self._validate_parent_for_new_node(
                parent=parent,
                owner_id=owner_id,
            )

        if check_conflict:
            conflict_exists = await self.check_name_conflict(
                owner_id=owner_id,
                parent_id=parent_id,
                name=normalized_name,
            )

            if conflict_exists:
                raise DuplicateEntityError(
                    "FileSystemNode",
                    field="name",
                    value=normalized_name,
                    repository=self.repository_name,
                    message="Узел с таким именем уже существует в указанной папке.",
                )

        calculated_path = (
            self._normalize_path(path)
            if path is not None
            else self._build_node_path(parent=parent, name=normalized_name)
        )

        calculated_depth = (
            depth if depth is not None else self._build_node_depth(parent=parent)
        )

        self._validate_depth(calculated_depth)

        node = FileSystemNode(
            owner_id=owner_id,
            parent_id=parent_id,
            name=normalized_name,
            node_type=node_type,
            visibility=visibility,
            path=calculated_path,
            depth=calculated_depth,
            created_by=created_by,
            updated_by=updated_by,
        )

        return await self.create(
            node,
            flush=flush,
            refresh=refresh,
        )

    async def create_file_node(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        parent_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileSystemNode:
        """Создаёт узел типа `FILE`.

        Args:
            owner_id: Идентификатор владельца узла.
            name: Имя файла.
            parent_id: Идентификатор родительской папки.
            created_by: Идентификатор пользователя, создавшего узел.
            flush: Выполнить ли `flush` после создания.
            refresh: Выполнить ли `refresh` после создания.

        Returns:
            Созданный файловый узел.
        """

        return await self.create_node(
            owner_id=owner_id,
            name=name,
            node_type=NodeType.FILE,
            parent_id=parent_id,
            created_by=created_by,
            updated_by=created_by,
            flush=flush,
            refresh=refresh,
        )

    async def create_folder_node(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        parent_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileSystemNode:
        """Создаёт узел типа `FOLDER`.

        Args:
            owner_id: Идентификатор владельца узла.
            name: Имя папки.
            parent_id: Идентификатор родительской папки.
            created_by: Идентификатор пользователя, создавшего узел.
            flush: Выполнить ли `flush` после создания.
            refresh: Выполнить ли `refresh` после создания.

        Returns:
            Созданный узел папки.
        """

        return await self.create_node(
            owner_id=owner_id,
            name=name,
            node_type=NodeType.FOLDER,
            parent_id=parent_id,
            created_by=created_by,
            updated_by=created_by,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Переименование, перемещение и пути
    # ------------------------------------------------------------------

    async def rename_node(
        self,
        *,
        node_id: uuid.UUID,
        new_name: str,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileSystemNode:
        """Переименовывает узел и обновляет пути всех его потомков.

        Args:
            node_id: Идентификатор узла.
            new_name: Новое имя узла.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            flush: Выполнить ли `flush` после обновления.
            refresh: Выполнить ли `refresh` после обновления.

        Returns:
            Обновлённый узел.

        Raises:
            EntityNotFoundError: Если узел не найден.
            InvalidQueryError: Если новое имя некорректно.
            DuplicateEntityError: Если в той же папке уже есть активный узел с таким именем.
        """

        node = await self.get_required_by_id(node_id)
        normalized_name = self._validate_node_name(new_name)

        if node.name == normalized_name:
            return node

        conflict_exists = await self.check_name_conflict(
            owner_id=node.owner_id,
            parent_id=node.parent_id,
            name=normalized_name,
            exclude_node_id=node.id,
        )

        if conflict_exists:
            raise DuplicateEntityError(
                "FileSystemNode",
                field="name",
                value=normalized_name,
                repository=self.repository_name,
                message="Узел с таким именем уже существует в указанной папке.",
            )

        old_path = node.path
        parent = None

        if node.parent_id is not None:
            parent = await self.get_required_by_id(node.parent_id)

        new_path = self._build_node_path(parent=parent, name=normalized_name)

        node.rename(normalized_name, updated_by=updated_by)
        node.path = new_path

        await self.update_descendant_paths(
            node_id=node.id,
            old_path_prefix=old_path,
            new_path_prefix=new_path,
            depth_delta=0,
            flush=False,
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(node)

        return node

    async def move_node(
        self,
        *,
        node_id: uuid.UUID,
        new_parent_id: uuid.UUID | None,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileSystemNode:
        """Перемещает узел в другую папку или на корневой уровень.

        Метод обновляет ``parent_id``, ``path`` и ``depth`` у самого узла,
        а также пересчитывает пути и глубину всех потомков.

        Args:
            node_id: Идентификатор перемещаемого узла.
            new_parent_id: Идентификатор новой родительской папки или ``None``
                для корневого уровня.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Перемещённый узел.

        Raises:
            EntityNotFoundError: Если узел или новая родительская папка
                не найдены.
            InvalidQueryError: Если перемещение некорректно.
            DuplicateEntityError: Если в целевой папке уже есть активный узел
                с таким именем.
        """

        node = await self.get_required_by_id(node_id)

        if node.parent_id == new_parent_id:
            return node

        if new_parent_id == node.id:
            raise InvalidQueryError(
                "Нельзя переместить узел внутрь самого себя.",
                repository=self.repository_name,
                operation="move_node",
                details={
                    "node_id": str(node.id),
                    "new_parent_id": str(new_parent_id),
                },
            )

        new_parent: FileSystemNode | None = None

        if new_parent_id is not None:
            new_parent = await self.get_required_by_id(new_parent_id)

            self._validate_parent_for_new_node(
                parent=new_parent,
                owner_id=node.owner_id,
            )

            await self._ensure_not_moving_into_descendant(
                node_id=node.id,
                new_parent_id=new_parent_id,
            )

        conflict_exists = await self.check_name_conflict(
            owner_id=node.owner_id,
            parent_id=new_parent_id,
            name=node.name,
            exclude_node_id=node.id,
        )

        if conflict_exists:
            raise DuplicateEntityError(
                "FileSystemNode",
                field="name",
                value=node.name,
                repository=self.repository_name,
                message="В целевой папке уже существует узел с таким именем.",
            )

        old_path = node.path
        old_depth = node.depth

        new_path = self._build_node_path(parent=new_parent, name=node.name)
        new_depth = self._build_node_depth(parent=new_parent)
        depth_delta = new_depth - old_depth

        node.move(
            new_parent_id=new_parent_id,
            new_path=new_path,
            new_depth=new_depth,
            updated_by=updated_by,
        )

        await self.update_descendant_paths(
            node_id=node.id,
            old_path_prefix=old_path,
            new_path_prefix=new_path,
            depth_delta=depth_delta,
            flush=False,
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(node)

        return node

    async def update_path(
        self,
        *,
        node_id: uuid.UUID,
        new_path: str,
        new_depth: int | None = None,
        updated_by: uuid.UUID | None = None,
        update_descendants: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileSystemNode:
        """Обновляет путь узла.

        Обычно используется внутри сервисов при сложных операциях перемещения,
        восстановления или синхронизации дерева.

        Args:
            node_id: Идентификатор узла.
            new_path: Новый материализованный путь.
            new_depth: Новая глубина узла. Если не передана, сохраняется текущая.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            update_descendants: Обновлять ли пути потомков.
            flush: Выполнить ли `flush` после обновления.
            refresh: Выполнить ли `refresh` после обновления.

        Returns:
            Обновлённый узел.

        Raises:
            EntityNotFoundError: Если узел не найден.
            InvalidQueryError: Если путь или глубина некорректны.
        """

        node = await self.get_required_by_id(node_id)

        normalized_path = self._normalize_path(new_path)

        old_path = node.path
        old_depth = node.depth

        calculated_depth = new_depth if new_depth is not None else old_depth
        self._validate_depth(calculated_depth)

        depth_delta = calculated_depth - old_depth

        node.path = normalized_path
        node.depth = calculated_depth
        node.updated_by = updated_by

        if update_descendants:
            await self.update_descendant_paths(
                node_id=node.id,
                old_path_prefix=old_path,
                new_path_prefix=normalized_path,
                depth_delta=depth_delta,
                flush=False,
            )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(node)

        return node

    async def update_descendant_paths(
        self,
        *,
        node_id: uuid.UUID,
        old_path_prefix: str,
        new_path_prefix: str,
        depth_delta: int = 0,
        flush: bool = True,
    ) -> list[FileSystemNode]:
        """Обновляет пути и глубину всех потомков узла.

        Args:
            node_id: Идентификатор корневого узла.
            old_path_prefix: Старый префикс пути.
            new_path_prefix: Новый префикс пути.
            depth_delta: Изменение глубины, которое нужно применить к потомкам.
            flush: Выполнить ли `flush` после обновления.

        Returns:
            Список обновлённых потомков.

        Raises:
            EntityNotFoundError: Если исходный узел не найден.
            InvalidQueryError: Если префиксы путей некорректны.
        """

        old_prefix = self._normalize_path(old_path_prefix)
        new_prefix = self._normalize_path(new_path_prefix)

        descendants = await self.get_descendants(
            node_id=node_id,
            include_self=False,
            include_deleted=True,
            order_by_depth=True,
        )

        for descendant in descendants:
            if descendant.path == old_prefix:
                descendant.path = new_prefix
            elif descendant.path.startswith(f"{old_prefix}/"):
                suffix = descendant.path[len(old_prefix) :]
                descendant.path = f"{new_prefix}{suffix}"

            descendant.depth = max(descendant.depth + depth_delta, 0)

        if flush:
            await self.flush()

        return descendants

    # ------------------------------------------------------------------
    # Видимость
    # ------------------------------------------------------------------

    async def update_visibility(
        self,
        *,
        node_id: uuid.UUID,
        visibility: NodeVisibility,
        recursive: bool = False,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileSystemNode:
        """Обновляет видимость узла.

        Если `recursive=True`, новая видимость применяется ко всему поддереву.

        Args:
            node_id: Идентификатор узла.
            visibility: Новое значение видимости.
            recursive: Применять ли изменение ко всем потомкам.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            flush: Выполнить ли `flush` после обновления.
            refresh: Выполнить ли `refresh` после обновления.

        Returns:
            Обновлённый корневой узел.

        Raises:
            EntityNotFoundError: Если узел не найден.
        """

        node = await self.get_required_by_id(node_id)

        nodes = [node]

        if recursive:
            nodes.extend(
                await self.get_descendants(
                    node_id=node_id,
                    include_self=False,
                    include_deleted=True,
                    order_by_depth=True,
                )
            )

        for item in nodes:
            item.visibility = visibility
            item.updated_by = updated_by

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(node)

        return node

    async def make_private(
        self,
        *,
        node_id: uuid.UUID,
        recursive: bool = False,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
    ) -> FileSystemNode:
        """Делает узел приватным.

        Args:
            node_id: Идентификатор узла.
            recursive: Применять ли изменение ко всем потомкам.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            flush: Выполнить ли `flush` после обновления.

        Returns:
            Обновлённый узел.
        """

        return await self.update_visibility(
            node_id=node_id,
            visibility=NodeVisibility.PRIVATE,
            recursive=recursive,
            updated_by=updated_by,
            flush=flush,
        )

    async def make_shared(
        self,
        *,
        node_id: uuid.UUID,
        recursive: bool = False,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
    ) -> FileSystemNode:
        """Делает узел общим.

        Args:
            node_id: Идентификатор узла.
            recursive: Применять ли изменение ко всем потомкам.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            flush: Выполнить ли `flush` после обновления.

        Returns:
            Обновлённый узел.
        """

        return await self.update_visibility(
            node_id=node_id,
            visibility=NodeVisibility.SHARED,
            recursive=recursive,
            updated_by=updated_by,
            flush=flush,
        )

    async def make_public(
        self,
        *,
        node_id: uuid.UUID,
        recursive: bool = False,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
    ) -> FileSystemNode:
        """Делает узел публичным.

        Args:
            node_id: Идентификатор узла.
            recursive: Применять ли изменение ко всем потомкам.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            flush: Выполнить ли `flush` после обновления.

        Returns:
            Обновлённый узел.
        """

        return await self.update_visibility(
            node_id=node_id,
            visibility=NodeVisibility.PUBLIC,
            recursive=recursive,
            updated_by=updated_by,
            flush=flush,
        )

    # ------------------------------------------------------------------
    # Soft delete, restore, purge
    # ------------------------------------------------------------------

    async def soft_delete_node(
        self,
        *,
        node_id: uuid.UUID,
        deleted_by: uuid.UUID | None = None,
        deleted_at: datetime | None = None,
        recursive: bool = False,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileSystemNode:
        """Помечает узел как удалённый.

        Если ``recursive=True``, также помечает удалёнными всех потомков узла.

        Args:
            node_id: Идентификатор узла.
            deleted_by: Идентификатор пользователя, удалившего узел.
            deleted_at: Дата удаления. Если не передана, используется текущее
                UTC-время.
            recursive: Удалять ли всё поддерево.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Удалённый узел.

        Raises:
            EntityNotFoundError: Если узел не найден.
        """

        if recursive:
            nodes = await self.soft_delete_subtree(
                node_id=node_id,
                deleted_by=deleted_by,
                deleted_at=deleted_at,
                flush=flush,
            )
            if refresh and nodes:
                await self.refresh(nodes[0])
            return nodes[0]

        node = await self.get_required_by_id(node_id)

        self._apply_soft_delete(
            node=node,
            deleted_by=deleted_by,
            deleted_at=deleted_at,
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(node)

        return node

    async def soft_delete_subtree(
        self,
        *,
        node_id: uuid.UUID,
        deleted_by: uuid.UUID | None = None,
        deleted_at: datetime | None = None,
        flush: bool = True,
    ) -> list[FileSystemNode]:
        """Помечает удалённым узел и всё его поддерево.

        Args:
            node_id: Идентификатор корневого узла поддерева.
            deleted_by: Идентификатор пользователя, удалившего узлы.
            deleted_at: Дата удаления. Если не передана, используется текущее UTC-время.
            flush: Выполнить ли `flush` после обновления.

        Returns:
            Список удалённых узлов, включая корневой.

        Raises:
            EntityNotFoundError: Если корневой узел не найден.
        """

        moment = deleted_at or self._utc_now()

        nodes = await self.get_descendants(
            node_id=node_id,
            include_self=True,
            include_deleted=True,
            order_by_depth=True,
        )

        for node in nodes:
            self._apply_soft_delete(
                node=node,
                deleted_by=deleted_by,
                deleted_at=moment,
            )

        if flush:
            await self.flush()

        return nodes

    async def restore_node(
        self,
        *,
        node_id: uuid.UUID,
        updated_by: uuid.UUID | None = None,
        recursive: bool = False,
        flush: bool = True,
        refresh: bool = False,
        check_conflict: bool = True,
    ) -> FileSystemNode:
        """Восстанавливает удалённый узел.

        Если ``recursive=True``, восстанавливается всё поддерево.
        При необходимости проверяет конфликт имени в родительской папке.

        Args:
            node_id: Идентификатор узла.
            updated_by: Идентификатор пользователя, выполнившего восстановление.
            recursive: Восстанавливать ли всё поддерево.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            check_conflict: Проверять ли конфликт имени при восстановлении.

        Returns:
            Восстановленный узел.

        Raises:
            EntityNotFoundError: Если узел не найден.
            DuplicateEntityError: Если восстановление создаёт конфликт имени.
        """

        if recursive:
            nodes = await self.restore_subtree(
                node_id=node_id,
                updated_by=updated_by,
                flush=flush,
                check_conflict=check_conflict,
            )
            if refresh and nodes:
                await self.refresh(nodes[0])
            return nodes[0]

        node = await self.get_required_by_id(node_id)

        if check_conflict:
            conflict_exists = await self.check_name_conflict(
                owner_id=node.owner_id,
                parent_id=node.parent_id,
                name=node.name,
                exclude_node_id=node.id,
            )

            if conflict_exists:
                raise DuplicateEntityError(
                    "FileSystemNode",
                    field="name",
                    value=node.name,
                    repository=self.repository_name,
                    message=(
                        "Невозможно восстановить узел: в папке уже есть "
                        "активный объект с таким именем."
                    ),
                )

        self._apply_restore(node=node, updated_by=updated_by)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(node)

        return node

    async def restore_subtree(
        self,
        *,
        node_id: uuid.UUID,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        check_conflict: bool = True,
    ) -> list[FileSystemNode]:
        """Восстанавливает узел и всех его потомков.

        Args:
            node_id: Идентификатор корневого узла поддерева.
            updated_by: Идентификатор пользователя, выполнившего восстановление.
            flush: Выполнить ли `flush` после обновления.
            check_conflict: Проверять ли конфликт имени корневого узла.

        Returns:
            Список восстановленных узлов, включая корневой.

        Raises:
            EntityNotFoundError: Если корневой узел не найден.
            DuplicateEntityError: Если восстановление создаёт конфликт имени.
        """

        root = await self.get_required_by_id(node_id)

        if check_conflict:
            conflict_exists = await self.check_name_conflict(
                owner_id=root.owner_id,
                parent_id=root.parent_id,
                name=root.name,
                exclude_node_id=root.id,
            )

            if conflict_exists:
                raise DuplicateEntityError(
                    "FileSystemNode",
                    field="name",
                    value=root.name,
                    repository=self.repository_name,
                    message=(
                        "Невозможно восстановить поддерево: в папке уже есть "
                        "активный объект с таким именем."
                    ),
                )

        nodes = await self.get_descendants(
            node_id=node_id,
            include_self=True,
            include_deleted=True,
            order_by_depth=True,
        )

        for node in nodes:
            self._apply_restore(node=node, updated_by=updated_by)

        if flush:
            await self.flush()

        return nodes

    async def mark_purged(
        self,
        *,
        node_id: uuid.UUID,
        flush: bool = True,
    ) -> None:
        """Окончательно удаляет узел из базы данных.

        Так как в модели `FileSystemNode` нет отдельного поля `purged_at`,
        окончательная очистка выполняется физическим удалением строки.

        Args:
            node_id: Идентификатор узла.
            flush: Выполнить ли `flush` после удаления.

        Raises:
            EntityNotFoundError: Если узел не найден.
        """

        stmt = sa_delete(FileSystemNode).where(FileSystemNode.id == node_id)
        result = await self.session.execute(stmt)
        if result.rowcount == 0:  # pyright: ignore[reportAttributeAccessIssue]
            raise EntityNotFoundError(
                self.model_name,
                entity_id=node_id,
                repository=self.repository_name,
            )
        if flush:
            await self.flush()

    # ------------------------------------------------------------------
    # Проверки конфликтов и существования
    # ------------------------------------------------------------------

    async def check_name_conflict(
        self,
        *,
        owner_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        name: str,
        exclude_node_id: uuid.UUID | None = None,
        include_deleted: bool = False,
    ) -> bool:
        """Проверяет, существует ли узел с таким именем в указанной папке.

        По умолчанию проверяются только активные неудалённые узлы.

        Args:
            owner_id: Идентификатор владельца узла.
            parent_id: Идентификатор родительской папки или `None` для корня.
            name: Имя узла.
            exclude_node_id: Идентификатор узла, который нужно исключить из проверки.
            include_deleted: Учитывать ли удалённые узлы.

        Returns:
            `True`, если конфликт имени существует, иначе `False`.

        Raises:
            InvalidQueryError: Если имя узла некорректно.
        """

        normalized_name = self._validate_node_name(name)

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.name == normalized_name,
        ]

        if parent_id is None:
            conditions.append(FileSystemNode.parent_id.is_(None))
        else:
            conditions.append(FileSystemNode.parent_id == parent_id)

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        if exclude_node_id is not None:
            conditions.append(FileSystemNode.id != exclude_node_id)

        return await self.exists(*conditions)

    async def get_path_exists(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        include_deleted: bool = False,
    ) -> bool:
        """Проверяет существование узла по материализованному пути.

        Args:
            owner_id: Идентификатор владельца узла.
            path: Материализованный путь узла.
            include_deleted: Учитывать ли удалённые узлы.

        Returns:
            `True`, если узел с таким путём существует, иначе `False`.

        Raises:
            InvalidQueryError: Если путь пустой или некорректный.
        """

        normalized_path = self._normalize_path(path)

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.path == normalized_path,
        ]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        return await self.exists(*conditions)

    # ------------------------------------------------------------------
    # Поиск
    # ------------------------------------------------------------------

    async def search_by_name(
        self,
        *,
        owner_id: uuid.UUID,
        query: str,
        parent_id: uuid.UUID | None = None,
        node_type: NodeType | None = None,
        include_deleted: bool = False,
        offset: int = 0,
        limit: int = 100,
        sort_by: NodeSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[FileSystemNode]:
        """Выполняет поиск узлов пользователя по имени.

        Метод является удобной обёрткой над `search_nodes`.

        Args:
            owner_id: Идентификатор владельца узлов.
            query: Поисковая строка.
            parent_id: Ограничение поиска конкретной папкой.
            node_type: Фильтр по типу узла.
            include_deleted: Включать ли удалённые узлы.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список найденных узлов.
        """

        return await self.search_nodes(
            owner_id=owner_id,
            query=query,
            parent_id=parent_id,
            node_type=node_type,
            include_deleted=include_deleted,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def search_nodes(
        self,
        *,
        owner_id: uuid.UUID,
        query: str | None = None,
        parent_id: uuid.UUID | None = None,
        node_type: NodeType | None = None,
        include_deleted: bool = False,
        offset: int = 0,
        limit: int = 100,
        sort_by: NodeSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[FileSystemNode]:
        """Ищет узлы файловой системы по набору фильтров.

        Поиск выполняется по имени и материализованному пути.

        Args:
            owner_id: Идентификатор владельца узлов.
            query: Поисковая строка.
            parent_id: Ограничение поиска конкретной папкой.
            node_type: Фильтр по типу узла.
            include_deleted: Включать ли удалённые узлы.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список найденных узлов.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
        ]

        if parent_id is not None:
            conditions.append(FileSystemNode.parent_id == parent_id)

        if node_type is not None:
            conditions.append(FileSystemNode.node_type == node_type)

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        if query is not None and query.strip():
            normalized_query = query.strip()
            pattern = f"%{normalized_query}%"

            conditions.append(
                or_(
                    FileSystemNode.name.ilike(pattern),
                    FileSystemNode.path.ilike(pattern),
                )
            )

        statement = (
            select(FileSystemNode)
            .where(and_(*conditions))
            .options(
                selectinload(FileSystemNode.file),
                selectinload(FileSystemNode.folder),
            )
            .order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="search_nodes",
        )

    # ------------------------------------------------------------------
    # Подсчёты
    # ------------------------------------------------------------------

    async def count_user_nodes(
        self,
        *,
        owner_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> int:
        """Возвращает количество узлов пользователя.

        Args:
            owner_id: Идентификатор владельца узлов.
            include_deleted: Учитывать ли удалённые узлы.

        Returns:
            Количество узлов пользователя.
        """

        conditions: list[Any] = [FileSystemNode.owner_id == owner_id]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        return await self.count(*conditions)

    async def count_user_files(
        self,
        *,
        owner_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> int:
        """Возвращает количество файлов пользователя.

        Args:
            owner_id: Идентификатор владельца узлов.
            include_deleted: Учитывать ли удалённые файлы.

        Returns:
            Количество файлов пользователя.
        """

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.node_type == NodeType.FILE,
        ]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        return await self.count(*conditions)

    async def count_user_folders(
        self,
        *,
        owner_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> int:
        """Возвращает количество папок пользователя.

        Args:
            owner_id: Идентификатор владельца узлов.
            include_deleted: Учитывать ли удалённые папки.

        Returns:
            Количество папок пользователя.
        """

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.node_type == NodeType.FOLDER,
        ]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        return await self.count(*conditions)

    async def count_children(
        self,
        *,
        parent_id: uuid.UUID,
        include_deleted: bool = False,
        node_type: NodeType | None = None,
    ) -> int:
        """Возвращает количество дочерних узлов указанной папки.

        Args:
            parent_id: Идентификатор родительского узла.
            include_deleted: Учитывать ли удалённые узлы.
            node_type: Фильтр по типу узла.

        Returns:
            Количество дочерних узлов.
        """

        conditions: list[Any] = [FileSystemNode.parent_id == parent_id]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        if node_type is not None:
            conditions.append(FileSystemNode.node_type == node_type)

        return await self.count(*conditions)

    async def count_root_nodes(
        self,
        *,
        owner_id: uuid.UUID,
        include_deleted: bool = False,
        node_type: NodeType | None = None,
    ) -> int:
        """Возвращает количество корневых узлов пользователя.

        Корневыми считаются узлы без родительского узла. Условия фильтрации
        совпадают с ``get_root_nodes``, чтобы ``count`` и страница были
        согласованы.

        Args:
            owner_id: Идентификатор владельца узлов.
            include_deleted: Учитывать ли удалённые узлы.
            node_type: Фильтр по типу узла.

        Returns:
            Количество корневых узлов пользователя.
        """

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.parent_id.is_(None),
        ]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        if node_type is not None:
            conditions.append(FileSystemNode.node_type == node_type)

        return await self.count(*conditions)

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    def _validate_node_name(
        self,
        name: str,
    ) -> str:
        """Проверяет и нормализует имя узла файловой системы.

        Имя не должно быть пустым, содержать символ ``/``, быть равно ``.``
        или ``..``, а также превышать 255 символов.

        Args:
            name: Имя узла.

        Returns:
            Нормализованное имя узла.

        Raises:
            InvalidQueryError: Если имя узла некорректно.
        """

        normalized_name = name.strip()

        if not normalized_name:
            raise InvalidQueryError(
                "Имя узла файловой системы не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_node_name",
                details={"field": "name"},
            )

        if "/" in normalized_name:
            raise InvalidQueryError(
                "Имя узла файловой системы не может содержать символ '/'.",
                repository=self.repository_name,
                operation="_validate_node_name",
                details={"field": "name", "value": normalized_name},
            )

        if normalized_name in {".", ".."}:
            raise InvalidQueryError(
                "Недопустимое имя узла файловой системы.",
                repository=self.repository_name,
                operation="_validate_node_name",
                details={"field": "name", "value": normalized_name},
            )

        if len(normalized_name) > 255:
            raise InvalidQueryError(
                "Имя узла файловой системы не должно превышать 255 символов.",
                repository=self.repository_name,
                operation="_validate_node_name",
                details={
                    "field": "name",
                    "length": len(normalized_name),
                    "max_length": 255,
                },
            )

        return normalized_name

    def _normalize_path(
        self,
        path: str,
    ) -> str:
        """Нормализует материализованный путь узла.

        Добавляет начальный `/`, удаляет повторяющиеся слэши и завершающий слэш,
        если путь не является корневым.

        Args:
            path: Путь узла.

        Returns:
            Нормализованный путь.

        Raises:
            InvalidQueryError: Если путь пустой.
        """

        normalized_path = path.strip()

        if not normalized_path:
            raise InvalidQueryError(
                "Путь узла файловой системы не может быть пустым.",
                repository=self.repository_name,
                operation="_normalize_path",
                details={"field": "path"},
            )

        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"

        while "//" in normalized_path:
            normalized_path = normalized_path.replace("//", "/")

        if len(normalized_path) > 1:
            normalized_path = normalized_path.rstrip("/")

        return normalized_path

    def _build_node_path(
        self,
        *,
        parent: FileSystemNode | None,
        name: str,
    ) -> str:
        """Строит материализованный путь узла на основе родителя и имени.

        Args:
            parent: Родительский узел или ``None`` для корневого уровня.
            name: Имя создаваемого или обновляемого узла.

        Returns:
            Материализованный путь узла.

        Raises:
            InvalidQueryError: Если имя или путь родителя некорректны.
        """

        normalized_name = self._validate_node_name(name)

        if parent is None:
            return f"/{normalized_name}"

        parent_path = self._normalize_path(parent.path)

        if parent_path == "/":
            return f"/{normalized_name}"

        return f"{parent_path}/{normalized_name}"

    def _build_node_depth(
        self,
        *,
        parent: FileSystemNode | None,
    ) -> int:
        """Вычисляет глубину узла на основе родительского узла.

        Args:
            parent: Родительский узел или `None` для корневого уровня.

        Returns:
            Глубина узла. Для корневого узла возвращается `0`.
        """

        if parent is None:
            return 0

        return parent.depth + 1

    def _validate_depth(
        self,
        depth: int,
    ) -> None:
        """Проверяет глубину узла.

        Args:
            depth: Глубина узла.

        Raises:
            InvalidQueryError: Если глубина отрицательная.
        """

        if depth < 0:
            raise InvalidQueryError(
                "Глубина узла файловой системы не может быть отрицательной.",
                repository=self.repository_name,
                operation="_validate_depth",
                details={"depth": depth},
            )

    def _validate_parent_for_new_node(
        self,
        *,
        parent: FileSystemNode,
        owner_id: uuid.UUID,
    ) -> None:
        """Проверяет, что родительский узел подходит для создания или перемещения узла.

        Родитель должен принадлежать тому же владельцу, быть папкой
        и не быть удалённым.

        Args:
            parent: Родительский узел.
            owner_id: Ожидаемый идентификатор владельца.

        Raises:
            InvalidQueryError: Если родитель принадлежит другому пользователю,
                не является папкой или удалён.
        """

        if parent.owner_id != owner_id:
            raise InvalidQueryError(
                "Родительский узел принадлежит другому пользователю.",
                repository=self.repository_name,
                operation="_validate_parent_for_new_node",
                details={
                    "parent_id": str(parent.id),
                    "parent_owner_id": str(parent.owner_id),
                    "expected_owner_id": str(owner_id),
                },
            )

        if parent.node_type != NodeType.FOLDER:
            raise InvalidQueryError(
                "Родительским узлом может быть только папка.",
                repository=self.repository_name,
                operation="_validate_parent_for_new_node",
                details={
                    "parent_id": str(parent.id),
                    "parent_node_type": parent.node_type.value,
                },
            )

        if parent.is_deleted:
            raise InvalidQueryError(
                "Нельзя создать или переместить узел в удалённую папку.",
                repository=self.repository_name,
                operation="_validate_parent_for_new_node",
                details={"parent_id": str(parent.id)},
            )

    async def _ensure_not_moving_into_descendant(
        self,
        *,
        node_id: uuid.UUID,
        new_parent_id: uuid.UUID,
    ) -> None:
        """Проверяет, что узел не перемещается внутрь собственного потомка.

        Args:
            node_id: Идентификатор перемещаемого узла.
            new_parent_id: Идентификатор новой родительской папки.

        Raises:
            InvalidQueryError: Если новая родительская папка является потомком узла.
        """

        descendants = await self.get_descendants(
            node_id=node_id,
            include_self=False,
            include_deleted=True,
            order_by_depth=False,
        )

        descendant_ids = {node.id for node in descendants}

        if new_parent_id in descendant_ids:
            raise InvalidQueryError(
                "Нельзя переместить папку внутрь её собственного поддерева.",
                repository=self.repository_name,
                operation="_ensure_not_moving_into_descendant",
                details={
                    "node_id": str(node_id),
                    "new_parent_id": str(new_parent_id),
                },
            )

    async def _ensure_user_exists(
        self,
        user_id: uuid.UUID,
    ) -> None:
        """Проверяет существование пользователя.

        Args:
            user_id: Идентификатор пользователя.

        Raises:
            EntityNotFoundError: Если пользователь не найден.
            RepositoryError: Если произошла ошибка при обращении к базе данных.
        """

        try:
            user = await self.session.get(User, user_id)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="_ensure_user_exists",
                reason=str(exc),
                details={"user_id": str(user_id)},
                cause=exc,
            ) from exc

        if user is None:
            raise EntityNotFoundError(
                "User",
                entity_id=user_id,
                repository=self.repository_name,
            )

    def _apply_soft_delete(
        self,
        *,
        node: FileSystemNode,
        deleted_by: uuid.UUID | None,
        deleted_at: datetime | None,
    ) -> None:
        """Применяет soft delete к ORM-объекту узла.

        Args:
            node: Узел файловой системы.
            deleted_by: Идентификатор пользователя, выполнившего удаление.
            deleted_at: Дата удаления. Если не передана, используется текущее UTC-время.
        """

        node.mark_deleted(
            deleted_by=deleted_by,
            deleted_at=deleted_at or self._utc_now(),
        )
        node.updated_by = deleted_by

    def _apply_restore(
        self,
        *,
        node: FileSystemNode,
        updated_by: uuid.UUID | None,
    ) -> None:
        """Снимает soft delete с ORM-объекта узла.

        Args:
            node: Узел файловой системы.
            updated_by: Идентификатор пользователя, выполнившего восстановление.
        """

        node.is_deleted = False
        node.deleted_at = None
        node.deleted_by = None
        node.updated_by = updated_by

    def _get_order_by(
        self,
        sort_by: NodeSortField,
        sort_direction: NodeSortDirection,
    ) -> Any:
        """Возвращает SQLAlchemy-выражение сортировки.

        Args:
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки: ``asc`` или ``desc``.

        Returns:
            SQLAlchemy-выражение для ``order_by``.

        Raises:
            InvalidQueryError: Если поле или направление сортировки недопустимы.
        """

        allowed_fields: dict[str, Any] = {
            "name": FileSystemNode.name,
            "created_at": FileSystemNode.created_at,
            "updated_at": FileSystemNode.updated_at,
            "deleted_at": FileSystemNode.deleted_at,
            "depth": FileSystemNode.depth,
            "node_type": FileSystemNode.node_type,
        }

        if sort_by not in allowed_fields:
            raise InvalidQueryError(
                "Недопустимое поле сортировки узлов файловой системы.",
                repository=self.repository_name,
                operation="_get_order_by",
                details={
                    "sort_by": sort_by,
                    "allowed_fields": list(allowed_fields.keys()),
                },
            )

        if sort_direction not in {"asc", "desc"}:
            raise InvalidQueryError(
                "Недопустимое направление сортировки.",
                repository=self.repository_name,
                operation="_get_order_by",
                details={
                    "sort_direction": sort_direction,
                    "allowed_directions": ["asc", "desc"],
                },
            )

        column = allowed_fields[sort_by]

        if sort_direction == "desc":
            return column.desc()

        return column.asc()

    def _utc_now(self) -> datetime:
        """Возвращает текущее время в UTC.

        Returns:
            Текущая дата и время с timezone UTC.
        """

        return datetime.now(UTC)

    # ------------------------------------------------------------------
    # Переопределённые методы с более точной обработкой ошибок
    # ------------------------------------------------------------------

    async def create(
        self,
        entity: FileSystemNode,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileSystemNode:
        """Добавляет узел файловой системы в текущую сессию.

        Переопределяет базовый метод для более точной обработки ошибок
        при создании узла, в частности конфликтов уникальности.

        Args:
            entity: ORM-объект узла файловой системы.
            flush: Выполнить ли `flush` после добавления.
            refresh: Выполнить ли `refresh` после добавления.

        Returns:
            Созданный узел файловой системы.

        Raises:
            DuplicateEntityError: Если возник конфликт уникальности.
            RepositoryError: Если произошла ошибка SQLAlchemy.
        """

        try:
            return await super().create(
                entity,
                flush=flush,
                refresh=refresh,
            )

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_node",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="create_node",
                reason=str(exc),
                cause=exc,
            ) from exc
