from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import NodeType, NodeVisibility
from database.models.filesystem import FileSystemNode, Folder
from database.repositories.base import BaseRepository
from database.repositories.nodes import (
    FileSystemNodeRepository,
    NodeSortDirection,
)

FolderSortField = Literal[
    "name",
    "created_at",
    "updated_at",
    "deleted_at",
    "depth",
    "color",
]


class FolderRepository(BaseRepository[Folder]):
    """Репозиторий для работы с папками.

    Инкапсулирует операции получения, создания, поиска, обновления метаданных,
    переименования, перемещения, soft delete, восстановления и подсчёта папок.

    Работает с моделью ``Folder`` и связанным узлом ``FileSystemNode``.
    Операции над деревом файловой системы делегируются в
    ``FileSystemNodeRepository``.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий папок.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=Folder)
        self.nodes = FileSystemNodeRepository(session=session)

    # ------------------------------------------------------------------
    # Получение папки
    # ------------------------------------------------------------------

    async def get_folder_by_id(
        self,
        folder_id: uuid.UUID,
    ) -> Folder | None:
        """Возвращает папку по идентификатору записи ``folders``.

        Дополнительно загружает связанный узел файловой системы.

        Args:
            folder_id: Идентификатор записи папки.

        Returns:
            Папка, если она найдена, иначе ``None``.
        """

        statement = (
            select(Folder)
            .where(Folder.id == folder_id)
            .options(selectinload(Folder.node).selectinload(FileSystemNode.file))
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_folder_by_id",
        )

    async def get_required_folder_by_id(
        self,
        folder_id: uuid.UUID,
    ) -> Folder:
        """Возвращает папку по идентификатору записи ``folders``.

        Args:
            folder_id: Идентификатор записи папки.

        Returns:
            Найденная папка.

        Raises:
            EntityNotFoundError: Если папка не найдена.
        """

        folder = await self.get_folder_by_id(folder_id)

        if folder is None:
            raise EntityNotFoundError(
                "Folder",
                entity_id=folder_id,
                repository=self.repository_name,
            )

        return folder

    async def get_by_node_id(
        self,
        node_id: uuid.UUID,
        *,
        include_deleted: bool = True,
    ) -> Folder | None:
        """Возвращает папку по идентификатору связанного узла файловой системы.

        Учитываются только узлы типа ``FOLDER``.

        Args:
            node_id: Идентификатор узла файловой системы.
            include_deleted: Включать ли папки, чей узел помечен удалённым.

        Returns:
            Папка, если она найдена, иначе ``None``.
        """

        statement = (
            select(Folder)
            .join(FileSystemNode, FileSystemNode.id == Folder.node_id)
            .where(
                Folder.node_id == node_id,
                FileSystemNode.node_type == NodeType.FOLDER,
            )
            .options(selectinload(Folder.node).selectinload(FileSystemNode.file))
        )

        if not include_deleted:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_node_id",
        )

    async def get_required_by_node_id(
        self,
        node_id: uuid.UUID,
        *,
        include_deleted: bool = True,
    ) -> Folder:
        """Возвращает папку по идентификатору связанного узла файловой системы.

        Args:
            node_id: Идентификатор узла файловой системы.
            include_deleted: Включать ли папки, чей узел помечен удалённым.

        Returns:
            Найденная папка.

        Raises:
            EntityNotFoundError: Если папка не найдена.
        """

        folder = await self.get_by_node_id(
            node_id,
            include_deleted=include_deleted,
        )

        if folder is None:
            raise EntityNotFoundError(
                "Folder",
                lookup={"node_id": str(node_id)},
                repository=self.repository_name,
            )

        return folder

    async def get_active_by_node_id(
        self,
        node_id: uuid.UUID,
    ) -> Folder | None:
        """Возвращает активную неудалённую папку по идентификатору узла.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            Активная папка, если она найдена, иначе ``None``.
        """

        return await self.get_by_node_id(
            node_id,
            include_deleted=False,
        )

    async def get_required_active_by_node_id(
        self,
        node_id: uuid.UUID,
    ) -> Folder:
        """Возвращает активную неудалённую папку по идентификатору узла.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            Найденная активная папка.

        Raises:
            EntityNotFoundError: Если активная папка не найдена.
        """

        folder = await self.get_active_by_node_id(node_id)

        if folder is None:
            raise EntityNotFoundError(
                "Folder",
                lookup={"node_id": str(node_id), "active": True},
                repository=self.repository_name,
                message="Активная папка не найдена.",
            )

        return folder

    async def get_by_owner_and_path(
        self,
        *,
        owner_id: uuid.UUID,
        path: str,
        include_deleted: bool = False,
    ) -> Folder | None:
        """Возвращает папку пользователя по материализованному пути.

        Сначала ищет узел файловой системы по владельцу и пути, затем проверяет,
        что найденный узел имеет тип ``FOLDER``.

        Args:
            owner_id: Идентификатор владельца папки.
            path: Материализованный путь папки.
            include_deleted: Включать ли удалённые папки.

        Returns:
            Папка, если она найдена, иначе ``None``.

        Raises:
            InvalidQueryError: Если путь пустой или некорректный.
        """

        node = await self.nodes.get_by_owner_and_path(
            owner_id=owner_id,
            path=path,
            include_deleted=include_deleted,
        )

        if node is None or node.node_type != NodeType.FOLDER:
            return None

        return await self.get_by_node_id(
            node.id,
            include_deleted=include_deleted,
        )

    async def folder_exists_for_node(
        self,
        node_id: uuid.UUID,
    ) -> bool:
        """Проверяет, существует ли запись ``folders`` для указанного узла.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            ``True``, если запись папки существует, иначе ``False``.
        """

        return await self.exists(Folder.node_id == node_id)

    # ------------------------------------------------------------------
    # Создание папки
    # ------------------------------------------------------------------

    async def create_folder(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        parent_id: uuid.UUID | None = None,
        description: str | None = None,
        color: str | None = None,
        visibility: NodeVisibility = NodeVisibility.PRIVATE,
        created_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_conflict: bool = True,
        check_owner_exists: bool = False,
    ) -> Folder:
        """Создаёт новую папку.

        Операция выполняется в два шага:

        1. Создаётся узел ``file_system_nodes`` типа ``FOLDER``.
        2. Создаётся связанная запись ``folders``.

        Args:
            owner_id: Идентификатор владельца папки.
            name: Имя папки.
            parent_id: Идентификатор родительской папки или ``None`` для корня.
            description: Описание папки.
            color: Цветовая метка папки.
            visibility: Видимость связанного узла.
            created_by: Идентификатор пользователя, создавшего папку.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_conflict: Проверять ли конфликт имени в родительской папке.
            check_owner_exists: Проверять ли существование владельца.

        Returns:
            Созданная папка.

        Raises:
            InvalidQueryError: Если имя, родительский узел или цветовая метка
                некорректны.
            EntityNotFoundError: Если владелец или родительский узел не найден.
            DuplicateEntityError: Если в родительской папке уже есть папка
                или узел с таким именем.
            RepositoryError: Если произошла ошибка при создании записи.
        """

        node = await self.nodes.create_node(
            owner_id=owner_id,
            name=name,
            node_type=NodeType.FOLDER,
            parent_id=parent_id,
            visibility=visibility,
            created_by=created_by,
            updated_by=created_by,
            flush=True,
            refresh=False,
            check_owner_exists=check_owner_exists,
            check_conflict=check_conflict,
        )

        folder = Folder(
            node_id=node.id,
            description=self._normalize_optional_text(description),
            color=self._normalize_color(color),
        )

        try:
            self.session.add(folder)

            if flush:
                await self.flush()

            if refresh:
                await self.refresh(folder)

            return folder

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_folder",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="create_folder",
                reason=str(exc),
                details={
                    "owner_id": str(owner_id),
                    "parent_id": str(parent_id) if parent_id else None,
                    "node_id": str(node.id),
                    "name": node.name,
                },
                cause=exc,
            ) from exc

    async def create_for_existing_node(
        self,
        *,
        node_id: uuid.UUID,
        description: str | None = None,
        color: str | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_duplicate: bool = True,
    ) -> Folder:
        """Создаёт запись ``Folder`` для уже существующего узла типа ``FOLDER``.

        Args:
            node_id: Идентификатор существующего узла файловой системы.
            description: Описание папки.
            color: Цветовая метка папки.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_duplicate: Проверять ли наличие уже существующей записи
                ``Folder``.

        Returns:
            Созданная запись папки.

        Raises:
            EntityNotFoundError: Если узел не найден.
            InvalidQueryError: Если узел не является папкой или цветовая метка
                некорректна.
            DuplicateEntityError: Если запись ``Folder`` для узла уже существует.
        """

        node = await self.nodes.get_required_by_id(node_id)

        if node.node_type != NodeType.FOLDER:
            raise InvalidQueryError(
                "Запись Folder может быть создана только для узла типа folder.",
                repository=self.repository_name,
                operation="create_for_existing_node",
                details={
                    "node_id": str(node_id),
                    "node_type": node.node_type.value,
                },
            )

        if check_duplicate and await self.folder_exists_for_node(node_id):
            raise DuplicateEntityError(
                "Folder",
                field="node_id",
                value=node_id,
                repository=self.repository_name,
            )

        folder = Folder(
            node_id=node_id,
            description=self._normalize_optional_text(description),
            color=self._normalize_color(color),
        )

        return await self.create(
            folder,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Списки папок
    # ------------------------------------------------------------------

    async def list_user_folders(
        self,
        *,
        owner_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
        include_deleted: bool = False,
        offset: int = 0,
        limit: int = 100,
        sort_by: FolderSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[Folder]:
        """Возвращает папки пользователя с пагинацией, фильтрацией и сортировкой.

        Если ``parent_id`` передан, возвращаются папки внутри указанной
        родительской папки. Если ``parent_id=None``, возвращаются корневые папки
        пользователя.

        Args:
            owner_id: Идентификатор владельца папок.
            parent_id: Идентификатор родительской папки или ``None`` для корня.
            include_deleted: Включать ли удалённые папки.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список папок пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки
                некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(Folder)
            .join(FileSystemNode, FileSystemNode.id == Folder.node_id)
            .where(
                FileSystemNode.owner_id == owner_id,
                FileSystemNode.node_type == NodeType.FOLDER,
            )
            .options(selectinload(Folder.node).selectinload(FileSystemNode.file))
        )

        if parent_id is None:
            statement = statement.where(FileSystemNode.parent_id.is_(None))
        else:
            statement = statement.where(FileSystemNode.parent_id == parent_id)

        if not include_deleted:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        statement = (
            statement.order_by(self._get_folder_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="list_user_folders",
        )

    async def list_child_folders(
        self,
        *,
        parent_id: uuid.UUID,
        include_deleted: bool = False,
        offset: int = 0,
        limit: int = 100,
        sort_by: FolderSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[Folder]:
        """Возвращает дочерние папки указанной папки.

        Args:
            parent_id: Идентификатор родительской папки.
            include_deleted: Включать ли удалённые папки.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список дочерних папок.
        """

        return await self.list_user_folders_by_parent(
            parent_id=parent_id,
            include_deleted=include_deleted,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_user_folders_by_parent(
        self,
        *,
        parent_id: uuid.UUID,
        include_deleted: bool = False,
        offset: int = 0,
        limit: int = 100,
        sort_by: FolderSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[Folder]:
        """Возвращает папки внутри указанного родительского узла.

        В отличие от ``list_user_folders``, метод не фильтрует результат по владельцу,
        а использует только ``parent_id``.

        Args:
            parent_id: Идентификатор родительского узла.
            include_deleted: Включать ли удалённые папки.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список папок внутри указанного родительского узла.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(Folder)
            .join(FileSystemNode, FileSystemNode.id == Folder.node_id)
            .where(
                FileSystemNode.parent_id == parent_id,
                FileSystemNode.node_type == NodeType.FOLDER,
            )
            .options(selectinload(Folder.node).selectinload(FileSystemNode.file))
        )

        if not include_deleted:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        statement = (
            statement.order_by(self._get_folder_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="list_user_folders_by_parent",
        )

    async def list_deleted_folders(
        self,
        *,
        owner_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
        sort_by: FolderSortField = "deleted_at",
        sort_direction: NodeSortDirection = "desc",
    ) -> list[Folder]:
        """Возвращает удалённые папки пользователя.

        Args:
            owner_id: Идентификатор владельца папок.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список удалённых папок пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(Folder)
            .join(FileSystemNode, FileSystemNode.id == Folder.node_id)
            .where(
                FileSystemNode.owner_id == owner_id,
                FileSystemNode.node_type == NodeType.FOLDER,
                FileSystemNode.is_deleted.is_(True),
            )
            .options(selectinload(Folder.node).selectinload(FileSystemNode.file))
            .order_by(self._get_folder_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="list_deleted_folders",
        )

    # ------------------------------------------------------------------
    # Обновление метаданных папки
    # ------------------------------------------------------------------

    async def update_metadata(
        self,
        *,
        folder_id: uuid.UUID,
        description: str | None = None,
        color: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> Folder:
        """Обновляет метаданные папки по идентификатору записи ``folders``.

        Обновляются описание и цветовая метка папки.

        Args:
            folder_id: Идентификатор записи папки.
            description: Новое описание папки.
            color: Новая цветовая метка папки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая папка.

        Raises:
            EntityNotFoundError: Если папка не найдена.
            InvalidQueryError: Если цветовая метка некорректна.
        """

        folder = await self.get_required_folder_by_id(folder_id)

        folder.update_metadata(
            description=self._normalize_optional_text(description),
            color=self._normalize_color(color),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(folder)

        return folder

    async def update_metadata_by_node_id(
        self,
        *,
        node_id: uuid.UUID,
        description: str | None = None,
        color: str | None = None,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> Folder:
        """Обновляет метаданные папки по идентификатору связанного узла.

        Обновляет описание и цветовую метку папки. Если связанный узел загружен,
        также обновляет поле ``updated_by``.

        Args:
            node_id: Идентификатор узла файловой системы.
            description: Новое описание папки.
            color: Новая цветовая метка папки.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая папка.

        Raises:
            EntityNotFoundError: Если папка не найдена.
            InvalidQueryError: Если цветовая метка некорректна.
        """

        folder = await self.get_required_by_node_id(node_id)

        folder.update_metadata(
            description=self._normalize_optional_text(description),
            color=self._normalize_color(color),
        )

        if folder.node is not None:
            folder.node.updated_by = updated_by

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(folder)

        return folder

    async def set_color(
        self,
        *,
        node_id: uuid.UUID,
        color: str | None,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> Folder:
        """Обновляет цветовую метку папки.

        Args:
            node_id: Идентификатор узла файловой системы.
            color: Новая цветовая метка. ``None`` или пустая строка снимают цвет.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая папка.

        Raises:
            EntityNotFoundError: Если папка не найдена.
            InvalidQueryError: Если цветовая метка некорректна.
        """

        folder = await self.get_required_by_node_id(node_id)
        folder.color = self._normalize_color(color)

        if folder.node is not None:
            folder.node.updated_by = updated_by

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(folder)

        return folder

    async def set_description(
        self,
        *,
        node_id: uuid.UUID,
        description: str | None,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> Folder:
        """Обновляет описание папки.

        Args:
            node_id: Идентификатор узла файловой системы.
            description: Новое описание. ``None`` или пустая строка очищают описание.
            updated_by: Идентификатор пользователя, выполнившего обновление.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая папка.

        Raises:
            EntityNotFoundError: Если папка не найдена.
        """

        folder = await self.get_required_by_node_id(node_id)
        folder.description = self._normalize_optional_text(description)

        if folder.node is not None:
            folder.node.updated_by = updated_by

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(folder)

        return folder

    # ------------------------------------------------------------------
    # Делегирование операций узла
    # ------------------------------------------------------------------

    async def rename_folder(
        self,
        *,
        node_id: uuid.UUID,
        new_name: str,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> Folder:
        """Переименовывает папку.

        Операция делегируется в ``FileSystemNodeRepository``, поскольку имя,
        путь и конфликт имён относятся к узлу файловой системы.

        Args:
            node_id: Идентификатор узла папки.
            new_name: Новое имя папки.
            updated_by: Идентификатор пользователя, выполнившего переименование.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая папка.

        Raises:
            EntityNotFoundError: Если папка или узел не найдены.
            InvalidQueryError: Если узел не является папкой или имя некорректно.
            DuplicateEntityError: Если в родительской папке уже есть узел
                с таким именем.
        """

        node = await self.nodes.rename_node(
            node_id=node_id,
            new_name=new_name,
            updated_by=updated_by,
            flush=flush,
            refresh=False,
        )

        if node.node_type != NodeType.FOLDER:
            raise InvalidQueryError(
                "Переименовываемый узел не является папкой.",
                repository=self.repository_name,
                operation="rename_folder",
                details={"node_id": str(node_id), "node_type": node.node_type.value},
            )

        folder = await self.get_required_by_node_id(node.id)

        if refresh:
            await self.refresh(folder)

        return folder

    async def move_folder(
        self,
        *,
        node_id: uuid.UUID,
        new_parent_id: uuid.UUID | None,
        updated_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> Folder:
        """Перемещает папку в другую папку или на корневой уровень.

        Операция делегируется в ``FileSystemNodeRepository``, поскольку
        перемещение требует обновления ``parent_id``, ``path``, ``depth``
        и путей потомков.

        Args:
            node_id: Идентификатор узла папки.
            new_parent_id: Идентификатор новой родительской папки или ``None``
                для корня.
            updated_by: Идентификатор пользователя, выполнившего перемещение.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Перемещённая папка.

        Raises:
            EntityNotFoundError: Если папка, узел или родительская папка
                не найдены.
            InvalidQueryError: Если узел не является папкой или перемещение
                некорректно.
            DuplicateEntityError: Если в целевой папке уже есть узел
                с таким именем.
        """

        node = await self.nodes.move_node(
            node_id=node_id,
            new_parent_id=new_parent_id,
            updated_by=updated_by,
            flush=flush,
            refresh=False,
        )

        if node.node_type != NodeType.FOLDER:
            raise InvalidQueryError(
                "Перемещаемый узел не является папкой.",
                repository=self.repository_name,
                operation="move_folder",
                details={"node_id": str(node_id), "node_type": node.node_type.value},
            )

        folder = await self.get_required_by_node_id(node.id)

        if refresh:
            await self.refresh(folder)

        return folder

    async def soft_delete_folder(
        self,
        *,
        node_id: uuid.UUID,
        deleted_by: uuid.UUID | None = None,
        recursive: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> Folder:
        """Помечает папку как удалённую.

        По умолчанию удаление выполняется рекурсивно, потому что удаление папки
        обычно должно затрагивать всё её поддерево.

        Args:
            node_id: Идентификатор узла папки.
            deleted_by: Идентификатор пользователя, выполнившего удаление.
            recursive: Удалять ли всё поддерево.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Удалённая папка.

        Raises:
            EntityNotFoundError: Если папка или узел не найдены.
            InvalidQueryError: Если узел не является папкой.
        """

        node = await self.nodes.soft_delete_node(
            node_id=node_id,
            deleted_by=deleted_by,
            recursive=recursive,
            flush=flush,
            refresh=False,
        )

        if node.node_type != NodeType.FOLDER:
            raise InvalidQueryError(
                "Удаляемый узел не является папкой.",
                repository=self.repository_name,
                operation="soft_delete_folder",
                details={"node_id": str(node_id), "node_type": node.node_type.value},
            )

        folder = await self.get_required_by_node_id(
            node.id,
            include_deleted=True,
        )

        if refresh:
            await self.refresh(folder)

        return folder

    async def restore_folder(
        self,
        *,
        node_id: uuid.UUID,
        updated_by: uuid.UUID | None = None,
        recursive: bool = True,
        flush: bool = True,
        refresh: bool = False,
        check_conflict: bool = True,
    ) -> Folder:
        """Восстанавливает удалённую папку.

        По умолчанию восстановление выполняется рекурсивно для всего поддерева.
        При необходимости проверяется конфликт имени в родительской папке.

        Args:
            node_id: Идентификатор узла папки.
            updated_by: Идентификатор пользователя, выполнившего восстановление.
            recursive: Восстанавливать ли всё поддерево.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            check_conflict: Проверять ли конфликт имени при восстановлении.

        Returns:
            Восстановленная папка.

        Raises:
            EntityNotFoundError: Если папка или узел не найдены.
            InvalidQueryError: Если узел не является папкой.
            DuplicateEntityError: Если восстановление создаёт конфликт имени.
        """

        node = await self.nodes.restore_node(
            node_id=node_id,
            updated_by=updated_by,
            recursive=recursive,
            flush=flush,
            refresh=False,
            check_conflict=check_conflict,
        )

        if node.node_type != NodeType.FOLDER:
            raise InvalidQueryError(
                "Восстанавливаемый узел не является папкой.",
                repository=self.repository_name,
                operation="restore_folder",
                details={"node_id": str(node_id), "node_type": node.node_type.value},
            )

        folder = await self.get_required_by_node_id(node.id)

        if refresh:
            await self.refresh(folder)

        return folder

    # ------------------------------------------------------------------
    # Поиск
    # ------------------------------------------------------------------

    async def search_folders(
        self,
        *,
        owner_id: uuid.UUID,
        query: str | None = None,
        parent_id: uuid.UUID | None = None,
        include_deleted: bool = False,
        color: str | None = None,
        offset: int = 0,
        limit: int = 100,
        sort_by: FolderSortField = "name",
        sort_direction: NodeSortDirection = "asc",
    ) -> list[Folder]:
        """Ищет папки пользователя по набору фильтров.

        Поиск выполняется по имени узла, материализованному пути и описанию
        папки. Дополнительно можно фильтровать по родительской папке, цвету
        и признаку удаления.

        Args:
            owner_id: Идентификатор владельца папок.
            query: Поисковая строка.
            parent_id: Ограничение поиска конкретной родительской папкой.
            include_deleted: Включать ли удалённые папки.
            color: Цветовая метка для фильтрации.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список найденных папок.

        Raises:
            InvalidQueryError: Если параметры пагинации, сортировки или цветовая
                метка некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.node_type == NodeType.FOLDER,
        ]

        if parent_id is not None:
            conditions.append(FileSystemNode.parent_id == parent_id)

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        if color is not None:
            conditions.append(Folder.color == self._normalize_color(color))

        if query is not None and query.strip():
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    FileSystemNode.name.ilike(pattern),
                    FileSystemNode.path.ilike(pattern),
                    Folder.description.ilike(pattern),
                )
            )

        statement = (
            select(Folder)
            .join(FileSystemNode, FileSystemNode.id == Folder.node_id)
            .where(and_(*conditions))
            .options(selectinload(Folder.node).selectinload(FileSystemNode.file))
            .order_by(self._get_folder_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="search_folders",
        )

    # ------------------------------------------------------------------
    # Подсчёты
    # ------------------------------------------------------------------

    async def count_user_folders_filtered(
        self,
        *,
        owner_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
        include_deleted: bool = False,
    ) -> int:
        """Возвращает количество папок пользователя с фильтром по родителю.

        Если ``parent_id=None``, считаются только корневые папки. Если
        ``parent_id`` указан, считаются папки внутри указанной родительской
        папки.

        Args:
            owner_id: Идентификатор владельца папок.
            parent_id: Идентификатор родительской папки или ``None`` для корня.
            include_deleted: Учитывать ли удалённые папки.

        Returns:
            Количество папок.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.node_type == NodeType.FOLDER,
        ]

        if parent_id is None:
            conditions.append(FileSystemNode.parent_id.is_(None))
        else:
            conditions.append(FileSystemNode.parent_id == parent_id)

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        try:
            statement = (
                select(func.count(Folder.id))
                .join(FileSystemNode, FileSystemNode.id == Folder.node_id)
                .where(*conditions)
            )

            result = await self.session.execute(statement)

            return int(result.scalar_one() or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count_user_folders_filtered",
                reason=str(exc),
                details={
                    "owner_id": str(owner_id),
                    "parent_id": str(parent_id) if parent_id else None,
                    "include_deleted": include_deleted,
                },
                cause=exc,
            ) from exc

    async def count_search_results(
        self,
        *,
        owner_id: uuid.UUID,
        query: str | None = None,
        parent_id: uuid.UUID | None = None,
        include_deleted: bool = False,
        color: str | None = None,
    ) -> int:
        """Возвращает количество папок, соответствующих критериям поиска.

        Использует те же фильтры, что и `search_folders`, без пагинации.

        Args:
            owner_id: Идентификатор владельца папок.
            query: Поисковая строка.
            parent_id: Ограничение поиска конкретной родительской папкой.
            include_deleted: Учитывать ли удалённые папки.
            color: Цветовая метка для фильтрации.

        Returns:
            Количество совпадающих папок.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.node_type == NodeType.FOLDER,
        ]

        if parent_id is not None:
            conditions.append(FileSystemNode.parent_id == parent_id)

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        if color is not None:
            conditions.append(Folder.color == self._normalize_color(color))

        if query is not None and query.strip():
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    FileSystemNode.name.ilike(pattern),
                    FileSystemNode.path.ilike(pattern),
                    Folder.description.ilike(pattern),
                )
            )

        try:
            statement = (
                select(func.count(Folder.id))
                .join(FileSystemNode, FileSystemNode.id == Folder.node_id)
                .where(and_(*conditions))
            )

            result = await self.session.execute(statement)

            return int(result.scalar_one() or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count_search_results",
                reason=str(exc),
                details={
                    "owner_id": str(owner_id),
                    "parent_id": str(parent_id) if parent_id else None,
                    "include_deleted": include_deleted,
                    "color": color,
                },
                cause=exc,
            ) from exc

    async def count_user_folders(
        self,
        *,
        owner_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> int:
        """Возвращает количество папок пользователя.

        Args:
            owner_id: Идентификатор владельца папок.
            include_deleted: Учитывать ли удалённые папки.

        Returns:
            Количество папок пользователя.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        conditions: list[Any] = [
            FileSystemNode.owner_id == owner_id,
            FileSystemNode.node_type == NodeType.FOLDER,
        ]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        try:
            statement = (
                select(func.count(Folder.id))
                .join(FileSystemNode, FileSystemNode.id == Folder.node_id)
                .where(*conditions)
            )

            result = await self.session.execute(statement)

            return int(result.scalar_one() or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count_user_folders",
                reason=str(exc),
                details={
                    "owner_id": str(owner_id),
                    "include_deleted": include_deleted,
                },
                cause=exc,
            ) from exc

    async def count_child_folders(
        self,
        *,
        parent_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> int:
        """Возвращает количество дочерних папок указанного узла.

        Args:
            parent_id: Идентификатор родительского узла.
            include_deleted: Учитывать ли удалённые папки.

        Returns:
            Количество дочерних папок.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        conditions: list[Any] = [
            FileSystemNode.parent_id == parent_id,
            FileSystemNode.node_type == NodeType.FOLDER,
        ]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        try:
            statement = (
                select(func.count(Folder.id))
                .join(FileSystemNode, FileSystemNode.id == Folder.node_id)
                .where(*conditions)
            )

            result = await self.session.execute(statement)

            return int(result.scalar_one() or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count_child_folders",
                reason=str(exc),
                details={
                    "parent_id": str(parent_id),
                    "include_deleted": include_deleted,
                },
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _base_select(self) -> Select[tuple[Folder]]:
        """Создаёт базовый ``SELECT``-запрос для модели ``Folder``.

        Returns:
            SQLAlchemy ``SELECT``-запрос для выборки папок.
        """

        return select(Folder)

    def _normalize_optional_text(
        self,
        value: str | None,
    ) -> str | None:
        """Нормализует необязательное текстовое поле.

        Удаляет пробелы по краям строки. Если после нормализации строка пустая,
        возвращает ``None``.

        Args:
            value: Исходное текстовое значение.

        Returns:
            Нормализованная строка или ``None``.
        """

        if value is None:
            return None

        normalized = value.strip()

        return normalized or None

    def _normalize_color(
        self,
        color: str | None,
    ) -> str | None:
        """Нормализует цветовую метку папки.

        ``None`` или пустая строка используются для снятия цветовой метки.
        Непустое значение не должно превышать 32 символа.

        Args:
            color: Цветовая метка папки.

        Returns:
            Нормализованная цветовая метка или ``None``.

        Raises:
            InvalidQueryError: Если цветовая метка превышает допустимую длину.
        """

        if color is None:
            return None

        normalized = color.strip()

        if not normalized:
            return None

        if len(normalized) > 32:
            raise InvalidQueryError(
                "Цветовая метка папки не должна превышать 32 символа.",
                repository=self.repository_name,
                operation="_normalize_color",
                details={
                    "color": normalized,
                    "max_length": 32,
                    "actual_length": len(normalized),
                },
            )

        return normalized

    def _get_folder_order_by(
        self,
        sort_by: FolderSortField,
        sort_direction: NodeSortDirection,
    ) -> Any:
        """Возвращает SQLAlchemy-выражение сортировки папок.

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
            "color": Folder.color,
        }

        if sort_by not in allowed_fields:
            raise InvalidQueryError(
                "Недопустимое поле сортировки папок.",
                repository=self.repository_name,
                operation="_get_folder_order_by",
                details={
                    "sort_by": sort_by,
                    "allowed_fields": list(allowed_fields.keys()),
                },
            )

        if sort_direction not in {"asc", "desc"}:
            raise InvalidQueryError(
                "Недопустимое направление сортировки.",
                repository=self.repository_name,
                operation="_get_folder_order_by",
                details={
                    "sort_direction": sort_direction,
                    "allowed_directions": ["asc", "desc"],
                },
            )

        column = allowed_fields[sort_by]

        if sort_direction == "desc":
            return column.desc()

        return column.asc()
