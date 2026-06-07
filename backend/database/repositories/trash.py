from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
from database.models.enums import TrashItemStatus
from database.models.filesystem import FileSystemNode, TrashItem
from database.repositories.base import BaseRepository
from database.repositories.nodes import FileSystemNodeRepository

TrashItemSortField = Literal[
    "deleted_at",
    "expires_at",
    "purged_at",
    "original_path",
    "restore_available",
]

TrashSortDirection = Literal["asc", "desc"]


class TrashItemRepository(BaseRepository[TrashItem]):
    """Репозиторий для работы с элементами корзины.

    Инкапсулирует операции получения, создания, выборки, восстановления,
    окончательной очистки, отключения восстановления, проверки состояния,
    физического удаления и подсчёта элементов корзины.

    Работает с моделью ``TrashItem`` и связанным узлом ``FileSystemNode``.
    Операции soft delete, restore и purge узлов делегируются в
    ``FileSystemNodeRepository``.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий элементов корзины.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=TrashItem)
        self.nodes = FileSystemNodeRepository(session=session)

    # ------------------------------------------------------------------
    # Получение элементов корзины
    # ------------------------------------------------------------------

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> TrashItem | None:
        """Возвращает элемент корзины по идентификатору.

        Дополнительно загружает связанные сущности: узел, владельца,
        пользователя, выполнившего удаление, и исходного родителя.

        Args:
            entity_id: Идентификатор элемента корзины.

        Returns:
            Элемент корзины, если он найден, иначе ``None``.
        """

        statement = (
            select(TrashItem)
            .where(TrashItem.id == entity_id)
            .options(
                selectinload(TrashItem.node).selectinload(FileSystemNode.file),
                selectinload(TrashItem.node).selectinload(FileSystemNode.folder),
                selectinload(TrashItem.owner),
                selectinload(TrashItem.deleter),
                selectinload(TrashItem.original_parent),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_id",
        )

    async def get_required_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> TrashItem:
        """Возвращает элемент корзины по идентификатору.

        Args:
            entity_id: Идентификатор элемента корзины.

        Returns:
            Найденный элемент корзины.

        Raises:
            EntityNotFoundError: Если элемент корзины не найден.
        """

        trash_item = await self.get_by_id(entity_id)

        if trash_item is None:
            raise EntityNotFoundError(
                "TrashItem",
                entity_id=entity_id,
                repository=self.repository_name,
            )

        return trash_item

    async def get_by_node_id(
        self,
        node_id: uuid.UUID,
        *,
        include_purged: bool = True,
    ) -> TrashItem | None:
        """Возвращает элемент корзины по идентификатору узла файловой системы.

        Args:
            node_id: Идентификатор узла файловой системы.
            include_purged: Включать ли элементы, уже помеченные как
                окончательно удалённые.

        Returns:
            Элемент корзины, если он найден, иначе ``None``.
        """

        conditions: list[Any] = [TrashItem.node_id == node_id]

        if not include_purged:
            conditions.append(TrashItem.purged_at.is_(None))

        statement = (
            select(TrashItem)
            .where(*conditions)
            .options(
                selectinload(TrashItem.node).selectinload(FileSystemNode.file),
                selectinload(TrashItem.node).selectinload(FileSystemNode.folder),
                selectinload(TrashItem.owner),
                selectinload(TrashItem.deleter),
                selectinload(TrashItem.original_parent),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_node_id",
        )

    async def get_required_by_node_id(
        self,
        node_id: uuid.UUID,
        *,
        include_purged: bool = True,
    ) -> TrashItem:
        """Возвращает элемент корзины по идентификатору узла файловой системы.

        Args:
            node_id: Идентификатор узла файловой системы.
            include_purged: Включать ли элементы, уже помеченные как
                окончательно удалённые.

        Returns:
            Найденный элемент корзины.

        Raises:
            EntityNotFoundError: Если элемент корзины не найден.
        """

        trash_item = await self.get_by_node_id(
            node_id,
            include_purged=include_purged,
        )

        if trash_item is None:
            raise EntityNotFoundError(
                "TrashItem",
                lookup={"node_id": str(node_id)},
                repository=self.repository_name,
            )

        return trash_item

    async def get_active_by_node_id(
        self,
        node_id: uuid.UUID,
    ) -> TrashItem | None:
        """Возвращает активный элемент корзины по идентификатору узла.

        Активным считается элемент, у которого ``purged_at`` ещё не установлен.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            Активный элемент корзины, если он найден, иначе ``None``.
        """

        return await self.get_by_node_id(
            node_id,
            include_purged=False,
        )

    async def get_required_active_by_node_id(
        self,
        node_id: uuid.UUID,
    ) -> TrashItem:
        """Возвращает активный элемент корзины по идентификатору узла.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            Найденный активный элемент корзины.

        Raises:
            EntityNotFoundError: Если активный элемент корзины не найден.
        """

        trash_item = await self.get_active_by_node_id(node_id)

        if trash_item is None:
            raise EntityNotFoundError(
                "TrashItem",
                lookup={"node_id": str(node_id), "purged": False},
                repository=self.repository_name,
            )

        return trash_item

    # ------------------------------------------------------------------
    # Создание элемента корзины
    # ------------------------------------------------------------------

    async def create_trash_item(
        self,
        *,
        node_id: uuid.UUID,
        deleted_by: uuid.UUID | None = None,
        owner_id: uuid.UUID | None = None,
        original_parent_id: uuid.UUID | None = None,
        original_path: str | None = None,
        deleted_at: datetime | None = None,
        expires_at: datetime | None = None,
        restore_available: bool = True,
        soft_delete_node: bool = True,
        recursive_soft_delete: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> TrashItem:
        """Создаёт запись корзины для удалённого узла файловой системы.

        Если ``soft_delete_node=True``, связанный ``FileSystemNode`` также
        помечается удалённым через ``FileSystemNodeRepository``. При рекурсивном
        удалении удалённым помечается всё поддерево узла.

        Args:
            node_id: Идентификатор удаляемого узла файловой системы.
            deleted_by: Идентификатор пользователя, выполнившего удаление.
            owner_id: Идентификатор владельца элемента корзины. Если не передан,
                используется владелец узла.
            original_parent_id: Исходный родительский узел до удаления.
            original_path: Исходный путь узла до удаления.
            deleted_at: Дата удаления. Если не передана, используется текущее
                UTC-время.
            expires_at: Дата истечения срока хранения в корзине.
            restore_available: Доступно ли восстановление элемента.
            soft_delete_node: Помечать ли связанный узел удалённым.
            recursive_soft_delete: Помечать ли удалённым всё поддерево узла.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.

        Returns:
            Созданный элемент корзины.

        Raises:
            EntityNotFoundError: Если узел файловой системы не найден.
            DuplicateEntityError: Если для узла уже существует элемент корзины.
            InvalidQueryError: Если владелец не совпадает с владельцем узла,
                исходный путь некорректен или срок хранения задан неправильно.
        """

        node = await self.nodes.get_required_by_id(node_id)

        existing_trash_item = await self.get_by_node_id(node_id)
        resolved_owner_id = owner_id or node.owner_id

        if resolved_owner_id != node.owner_id:
            raise InvalidQueryError(
                "Владелец элемента корзины не совпадает с владельцем узла.",
                repository=self.repository_name,
                operation="create_trash_item",
                details={
                    "node_id": str(node.id),
                    "node_owner_id": str(node.owner_id),
                    "owner_id": str(resolved_owner_id),
                },
            )

        moment = deleted_at or self._utc_now()

        self._validate_expiration(
            deleted_at=moment,
            expires_at=expires_at,
        )

        if existing_trash_item is not None:
            if (
                existing_trash_item.is_in_trash
                and existing_trash_item.purged_at is None
            ):
                raise DuplicateEntityError(
                    "TrashItem",
                    field="node_id",
                    value=node_id,
                    repository=self.repository_name,
                    message="Для указанного узла уже существует элемент корзины.",
                )

            existing_trash_item.owner_id = resolved_owner_id
            existing_trash_item.deleted_by = deleted_by
            existing_trash_item.original_parent_id = (
                original_parent_id if original_parent_id is not None else node.parent_id
            )
            existing_trash_item.original_path = (
                self._validate_original_path(original_path)
                if original_path is not None
                else self._validate_original_path(node.path)
            )
            existing_trash_item.deleted_at = moment
            existing_trash_item.expires_at = expires_at
            existing_trash_item.restore_available = restore_available
            existing_trash_item.purged_at = None
            existing_trash_item.status = TrashItemStatus.IN_TRASH

            if soft_delete_node and not node.is_deleted:
                await self.nodes.soft_delete_node(
                    node_id=node.id,
                    deleted_by=deleted_by,
                    deleted_at=moment,
                    recursive=recursive_soft_delete,
                    flush=False,
                )

            if flush:
                await self.flush()

            if refresh:
                await self.refresh(existing_trash_item)

            return existing_trash_item

        trash_item = TrashItem(
            node_id=node.id,
            owner_id=resolved_owner_id,
            deleted_by=deleted_by,
            original_parent_id=(
                original_parent_id if original_parent_id is not None else node.parent_id
            ),
            original_path=(
                self._validate_original_path(original_path)
                if original_path is not None
                else self._validate_original_path(node.path)
            ),
            deleted_at=moment,
            expires_at=expires_at,
            restore_available=restore_available,
        )

        if soft_delete_node and not node.is_deleted:
            await self.nodes.soft_delete_node(
                node_id=node.id,
                deleted_by=deleted_by,
                deleted_at=moment,
                recursive=recursive_soft_delete,
                flush=False,
            )

        created_trash_item = await self.create(
            trash_item,
            flush=False,
            refresh=False,
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(created_trash_item)

        return created_trash_item

    # ------------------------------------------------------------------
    # Списки корзины
    # ------------------------------------------------------------------

    async def get_user_trash(
        self,
        *,
        owner_id: uuid.UUID,
        include_purged: bool = False,
        include_non_restorable: bool = True,
        offset: int = 0,
        limit: int = 100,
        sort_by: TrashItemSortField = "deleted_at",
        sort_direction: TrashSortDirection = "desc",
    ) -> list[TrashItem]:
        """Возвращает элементы корзины пользователя.

        Args:
            owner_id: Идентификатор владельца элементов корзины.
            include_purged: Включать ли окончательно удалённые элементы.
            include_non_restorable: Включать ли элементы, недоступные для
                восстановления.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список элементов корзины пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки
                некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions: list[Any] = [TrashItem.owner_id == owner_id]

        if not include_purged:
            conditions.append(TrashItem.purged_at.is_(None))

        if not include_non_restorable:
            conditions.extend(
                [
                    TrashItem.restore_available.is_(True),
                    TrashItem.purged_at.is_(None),
                ],
            )

        statement = (
            select(TrashItem)
            .where(and_(*conditions))
            .options(
                selectinload(TrashItem.node).selectinload(FileSystemNode.file),
                selectinload(TrashItem.node).selectinload(FileSystemNode.folder),
                selectinload(TrashItem.owner),
                selectinload(TrashItem.deleter),
                selectinload(TrashItem.original_parent),
            )
            .order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_user_trash",
        )

    async def get_user_active_trash(
        self,
        *,
        owner_id: uuid.UUID,
        exclude_expired: bool = False,
        now: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
        sort_by: TrashItemSortField = "deleted_at",
        sort_direction: TrashSortDirection = "desc",
    ) -> list[TrashItem]:
        """Возвращает активные элементы корзины пользователя.

        Активным считается элемент, который не был окончательно удалён
        и доступен для восстановления. При ``exclude_expired=True`` дополнительно
        исключаются элементы с истёкшим сроком хранения.

        Args:
            owner_id: Идентификатор владельца элементов корзины.
            exclude_expired: Исключать ли элементы с истёкшим сроком хранения.
            now: Момент времени для проверки срока хранения.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список активных элементов корзины пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки
                некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions: list[Any] = [
            TrashItem.owner_id == owner_id,
            TrashItem.purged_at.is_(None),
            TrashItem.restore_available.is_(True),
        ]

        if exclude_expired:
            current_time = now or self._utc_now()

            conditions.append(
                or_(
                    TrashItem.expires_at.is_(None),
                    TrashItem.expires_at > current_time,
                ),
            )

        statement = (
            select(TrashItem)
            .where(and_(*conditions))
            .options(
                selectinload(TrashItem.node).selectinload(FileSystemNode.file),
                selectinload(TrashItem.node).selectinload(FileSystemNode.folder),
                selectinload(TrashItem.owner),
                selectinload(TrashItem.deleter),
                selectinload(TrashItem.original_parent),
            )
            .order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_user_active_trash",
        )

    async def get_expired_items(
        self,
        *,
        now: datetime | None = None,
        owner_id: uuid.UUID | None = None,
        include_non_restorable: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> list[TrashItem]:
        """Возвращает элементы корзины, срок хранения которых истёк.

        В выборку попадают элементы с установленным ``expires_at``, у которых
        срок хранения меньше или равен указанному моменту, и которые ещё
        не были очищены.

        Args:
            now: Момент времени для проверки истечения срока хранения.
            owner_id: Фильтр по владельцу элементов корзины.
            include_non_restorable: Включать ли элементы, недоступные для
                восстановления.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список истёкших элементов корзины.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        current_time = now or self._utc_now()

        conditions: list[Any] = [
            TrashItem.expires_at.is_not(None),
            TrashItem.expires_at <= current_time,
            TrashItem.purged_at.is_(None),
        ]

        if owner_id is not None:
            conditions.append(TrashItem.owner_id == owner_id)

        if not include_non_restorable:
            conditions.append(TrashItem.restore_available.is_(True))

        statement = (
            select(TrashItem)
            .where(and_(*conditions))
            .options(
                selectinload(TrashItem.node).selectinload(FileSystemNode.file),
                selectinload(TrashItem.node).selectinload(FileSystemNode.folder),
                selectinload(TrashItem.owner),
                selectinload(TrashItem.deleter),
                selectinload(TrashItem.original_parent),
            )
            .order_by(TrashItem.expires_at.asc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_expired_items",
        )

    async def get_items_ready_for_purge(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[TrashItem]:
        """Возвращает элементы корзины, готовые к окончательной очистке.

        Метод является удобной обёрткой над ``get_expired_items()`` и
        предназначен для задач очистки корзины.

        Args:
            now: Момент времени для проверки истечения срока хранения.
            limit: Максимальное количество элементов для выборки.

        Returns:
            Список элементов корзины, готовых к purge.
        """

        return await self.get_expired_items(
            now=now,
            owner_id=None,
            include_non_restorable=True,
            offset=0,
            limit=limit,
        )

    async def get_non_restorable_items(
        self,
        *,
        owner_id: uuid.UUID | None = None,
        include_purged: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[TrashItem]:
        """Возвращает элементы корзины, недоступные для восстановления.

        Args:
            owner_id: Фильтр по владельцу элементов корзины.
            include_purged: Включать ли окончательно удалённые элементы.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список элементов корзины, у которых ``restore_available=False``.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions: list[Any] = [TrashItem.restore_available.is_(False)]

        if owner_id is not None:
            conditions.append(TrashItem.owner_id == owner_id)

        if not include_purged:
            conditions.append(TrashItem.purged_at.is_(None))

        statement = (
            select(TrashItem)
            .where(and_(*conditions))
            .options(
                selectinload(TrashItem.node).selectinload(FileSystemNode.file),
                selectinload(TrashItem.node).selectinload(FileSystemNode.folder),
                selectinload(TrashItem.owner),
                selectinload(TrashItem.deleter),
                selectinload(TrashItem.original_parent),
            )
            .order_by(TrashItem.deleted_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_non_restorable_items",
        )

    # ------------------------------------------------------------------
    # Восстановление, purge, отключение восстановления
    # ------------------------------------------------------------------

    async def mark_restored(
        self,
        *,
        trash_item_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        restored_by: uuid.UUID | None = None,
        restore_node: bool = True,
        recursive: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> TrashItem:
        """Помечает элемент корзины как восстановленный.

        Метод снимает возможность повторного восстановления у ``TrashItem``.
        Если ``restore_node=True``, связанный ``FileSystemNode`` также
        восстанавливается через ``FileSystemNodeRepository``.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.
            restored_by: Идентификатор пользователя, выполнившего восстановление.
            restore_node: Восстанавливать ли связанный узел.
            recursive: Восстанавливать ли всё поддерево узла.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый элемент корзины.

        Raises:
            InvalidQueryError: Если переданы некорректные идентификаторы,
                элемент уже окончательно удалён или недоступен для восстановления.
            EntityNotFoundError: Если элемент корзины не найден.
        """

        trash_item = await self._get_required_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        if trash_item.purged_at is not None:
            raise InvalidQueryError(
                "Нельзя восстановить окончательно удалённый элемент корзины.",
                repository=self.repository_name,
                operation="mark_restored",
                details={
                    "trash_item_id": str(trash_item.id),
                    "node_id": str(trash_item.node_id),
                    "purged_at": str(trash_item.purged_at),
                },
            )

        if not trash_item.restore_available:
            raise InvalidQueryError(
                "Элемент корзины недоступен для восстановления.",
                repository=self.repository_name,
                operation="mark_restored",
                details={
                    "trash_item_id": str(trash_item.id),
                    "node_id": str(trash_item.node_id),
                },
            )

        if restore_node:
            await self.nodes.restore_node(
                node_id=trash_item.node_id,
                updated_by=restored_by,
                recursive=recursive,
                flush=False,
                check_conflict=True,
            )

        trash_item.restore()

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(trash_item)

        return trash_item

    async def mark_purged(
        self,
        *,
        trash_item_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        purged_at: datetime | None = None,
        purge_node: bool = False,
        flush: bool = True,
        refresh: bool = False,
    ) -> TrashItem:
        """Помечает элемент корзины как окончательно удалённый.

        Устанавливает ``purged_at`` и отключает возможность восстановления.
        Если ``purge_node=True``, связанный ``FileSystemNode`` физически
        удаляется через ``FileSystemNodeRepository.mark_purged()``.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.
            purged_at: Дата окончательной очистки. Если не передана,
                используется текущее UTC-время.
            purge_node: Физически удалить ли связанный узел.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый элемент корзины.

        Raises:
            InvalidQueryError: Если переданы некорректные идентификаторы.
            EntityNotFoundError: Если элемент корзины не найден.
        """

        trash_item = await self._get_required_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        trash_item.purge(purged_at=purged_at)

        if purge_node:
            await self.nodes.mark_purged(
                node_id=trash_item.node_id,
                flush=False,
            )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(trash_item)

        return trash_item

    async def disable_restore(
        self,
        *,
        trash_item_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> TrashItem:
        """Отключает возможность восстановления элемента корзины.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый элемент корзины.

        Raises:
            InvalidQueryError: Если переданы некорректные идентификаторы.
            EntityNotFoundError: Если элемент корзины не найден.
        """

        trash_item = await self._get_required_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        trash_item.restore_available = False

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(trash_item)

        return trash_item

    async def enable_restore(
        self,
        *,
        trash_item_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> TrashItem:
        """Включает возможность восстановления элемента корзины.

        Нельзя включить восстановление для элемента, который уже был
        окончательно удалён и имеет установленный ``purged_at``.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый элемент корзины.

        Raises:
            InvalidQueryError: Если переданы некорректные идентификаторы
                или элемент уже окончательно удалён.
            EntityNotFoundError: Если элемент корзины не найден.
        """

        trash_item = await self._get_required_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        if trash_item.purged_at is not None:
            raise InvalidQueryError(
                "Нельзя включить восстановление для окончательно удалённого элемента.",
                repository=self.repository_name,
                operation="enable_restore",
                details={
                    "trash_item_id": str(trash_item.id),
                    "node_id": str(trash_item.node_id),
                    "purged_at": str(trash_item.purged_at),
                },
            )

        trash_item.restore_available = True

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(trash_item)

        return trash_item

    async def update_expiration(
        self,
        *,
        trash_item_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        expires_at: datetime | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> TrashItem:
        """Обновляет срок хранения элемента корзины.

        Если ``expires_at=None``, срок хранения становится бессрочным.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.
            expires_at: Новая дата истечения срока хранения или ``None``.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый элемент корзины.

        Raises:
            InvalidQueryError: Если переданы некорректные идентификаторы
                или срок хранения меньше либо равен времени удаления.
            EntityNotFoundError: Если элемент корзины не найден.
        """

        trash_item = await self._get_required_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        self._validate_expiration(
            deleted_at=trash_item.deleted_at,
            expires_at=expires_at,
        )

        trash_item.expires_at = expires_at

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(trash_item)

        return trash_item

    async def expire_item_now(
        self,
        *,
        trash_item_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> TrashItem:
        """Устанавливает срок хранения элемента корзины в текущий момент.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый элемент корзины.

        Raises:
            InvalidQueryError: Если переданы некорректные идентификаторы.
            EntityNotFoundError: Если элемент корзины не найден.
        """

        trash_item = await self._get_required_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        trash_item.expires_at = self._utc_now()

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(trash_item)

        return trash_item

    # ------------------------------------------------------------------
    # Физическое удаление записей trash_items
    # ------------------------------------------------------------------

    async def delete_trash_item(
        self,
        *,
        trash_item_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        required: bool = True,
    ) -> bool:
        """Физически удаляет запись ``trash_items``.

        Метод удаляет только запись корзины, но не удаляет связанный
        ``FileSystemNode``.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.
            flush: Выполнить ``flush`` после удаления.
            required: Выбрасывать ли ошибку, если элемент корзины не найден.

        Returns:
            ``True``, если запись была удалена, иначе ``False``.

        Raises:
            InvalidQueryError: Если переданы некорректные идентификаторы.
            EntityNotFoundError: Если элемент корзины не найден и
                ``required=True``.
        """

        trash_item = await self._get_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        if trash_item is None:
            if required:
                raise EntityNotFoundError(
                    "TrashItem",
                    lookup={
                        "trash_item_id": str(trash_item_id)
                        if trash_item_id is not None
                        else None,
                        "node_id": str(node_id) if node_id is not None else None,
                    },
                    repository=self.repository_name,
                )

            return False

        await self.delete(trash_item, flush=flush)

        return True

    async def delete_purged_items(
        self,
        *,
        owner_id: uuid.UUID | None = None,
        older_than: datetime | None = None,
        flush: bool = True,
    ) -> int:
        """Физически удаляет записи корзины, помеченные как окончательно удалённые.

        Args:
            owner_id: Фильтр по владельцу элементов корзины.
            older_than: Удалять только элементы, очищенные не позже указанного
                момента.
            flush: Выполнить ``flush`` после удаления.

        Returns:
            Количество удалённых записей.
        """

        conditions: list[Any] = [
            TrashItem.purged_at.is_not(None),
        ]

        if owner_id is not None:
            conditions.append(TrashItem.owner_id == owner_id)

        if older_than is not None:
            conditions.append(TrashItem.purged_at <= older_than)

        return await self.bulk_delete(
            *conditions,
            flush=flush,
        )

    async def delete_by_node_id(
        self,
        node_id: uuid.UUID,
        *,
        flush: bool = True,
        required: bool = True,
    ) -> bool:
        """Физически удаляет запись корзины по идентификатору узла.

        Args:
            node_id: Идентификатор связанного узла файловой системы.
            flush: Выполнить ``flush`` после удаления.
            required: Выбрасывать ли ошибку, если элемент корзины не найден.

        Returns:
            ``True``, если запись была удалена, иначе ``False``.

        Raises:
            EntityNotFoundError: Если элемент корзины не найден и
                ``required=True``.
        """

        return await self.delete_trash_item(
            node_id=node_id,
            flush=flush,
            required=required,
        )

    # ------------------------------------------------------------------
    # Подсчёты и проверки
    # ------------------------------------------------------------------

    async def count_user_trash_items(
        self,
        *,
        owner_id: uuid.UUID,
        include_purged: bool = False,
        only_restorable: bool = False,
    ) -> int:
        """Возвращает количество элементов корзины пользователя.

        Args:
            owner_id: Идентификатор владельца элементов корзины.
            include_purged: Учитывать ли окончательно удалённые элементы.
            only_restorable: Учитывать только элементы, доступные для
                восстановления.

        Returns:
            Количество элементов корзины пользователя.
        """

        conditions: list[Any] = [
            TrashItem.owner_id == owner_id,
        ]

        if not include_purged:
            conditions.append(TrashItem.purged_at.is_(None))

        if only_restorable:
            conditions.append(TrashItem.restore_available.is_(True))

        return await self.count(*conditions)

    async def count_active_user_trash_items(
        self,
        *,
        owner_id: uuid.UUID,
        exclude_expired: bool = False,
        now: datetime | None = None,
    ) -> int:
        """Возвращает количество активных элементов корзины пользователя.

        Активный элемент не очищен окончательно и доступен для восстановления.
        При ``exclude_expired=True`` элементы с истёкшим сроком хранения
        не учитываются.

        Args:
            owner_id: Идентификатор владельца элементов корзины.
            exclude_expired: Исключать ли элементы с истёкшим сроком хранения.
            now: Момент времени для проверки истечения срока хранения.

        Returns:
            Количество активных элементов корзины пользователя.
        """

        conditions: list[Any] = [
            TrashItem.owner_id == owner_id,
            TrashItem.purged_at.is_(None),
            TrashItem.restore_available.is_(True),
        ]

        if exclude_expired:
            current_time = now or self._utc_now()
            conditions.append(
                or_(
                    TrashItem.expires_at.is_(None),
                    TrashItem.expires_at > current_time,
                ),
            )

        return await self.count(*conditions)

    async def search_user_trash(
        self,
        *,
        owner_id: uuid.UUID,
        include_purged: bool = False,
        status: Any | None = None,
        restore_available: bool | None = None,
        deleted_from: datetime | None = None,
        deleted_to: datetime | None = None,
        expires_before: datetime | None = None,
        query: str | None = None,
        sort_by: TrashItemSortField = "deleted_at",
        sort_direction: TrashSortDirection = "desc",
        offset: int = 0,
        limit: int = 100,
    ) -> list[TrashItem]:
        """Ищет элементы корзины владельца по расширенным фильтрам.

        Возвращает страницу элементов корзины указанного владельца. Поддерживает
        фильтрацию по статусу, доступности восстановления, диапазону даты
        удаления, сроку хранения и поисковой строке. Поиск выполняется
        по исходному пути элемента корзины и имени связанного узла файловой
        системы.

        Args:
            owner_id: Идентификатор владельца элементов корзины.
            include_purged: Включать ли окончательно удалённые элементы. Если
                ``False``, элементы с заполненным ``purged_at`` исключаются.
            status: Статус элемента корзины для фильтрации. Если ``None``,
                фильтр по статусу не применяется.
            restore_available: Признак доступности восстановления. Если
                ``None``, фильтр по доступности восстановления не применяется.
            deleted_from: Нижняя граница даты удаления включительно.
            deleted_to: Верхняя граница даты удаления включительно.
            expires_before: Верхняя граница срока хранения включительно. При
                указании фильтра учитываются только элементы с непустым
                ``expires_at``.
            query: Поисковая строка. Если ``None`` или пустая строка,
                текстовый поиск не применяется.
            sort_by: Поле сортировки элементов корзины.
            sort_direction: Направление сортировки: ``asc`` или ``desc``.
            offset: Смещение для постраничной выдачи.
            limit: Максимальное количество элементов корзины в результате.

        Returns:
            Список элементов корзины владельца, соответствующих фильтрам.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки
                некорректны.
            RepositoryError: Если не удалось выполнить запрос к базе данных.
        """

        self._validate_pagination(offset=offset, limit=limit)
        conditions: list[Any] = [TrashItem.owner_id == owner_id]
        if not include_purged:
            conditions.append(TrashItem.purged_at.is_(None))
        if status is not None:
            conditions.append(TrashItem.status == status)
        if restore_available is not None:
            conditions.append(TrashItem.restore_available.is_(restore_available))
        if deleted_from is not None:
            conditions.append(TrashItem.deleted_at >= deleted_from)
        if deleted_to is not None:
            conditions.append(TrashItem.deleted_at <= deleted_to)
        if expires_before is not None:
            conditions.append(TrashItem.expires_at.is_not(None))
            conditions.append(TrashItem.expires_at <= expires_before)
        if query:
            like_query = f"%{query.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(TrashItem.original_path).like(like_query),
                    func.lower(self.nodes.model.name).like(like_query),
                )
            )

        statement = (
            select(TrashItem)
            .join(self.nodes.model, TrashItem.node_id == self.nodes.model.id)
            .where(and_(*conditions))
            .options(
                selectinload(TrashItem.node).selectinload(FileSystemNode.file),
                selectinload(TrashItem.node).selectinload(FileSystemNode.folder),
                selectinload(TrashItem.owner),
                selectinload(TrashItem.deleter),
                selectinload(TrashItem.original_parent),
            )
            .order_by(self._get_order_by(sort_by, sort_direction), TrashItem.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return await self.scalars_all(statement, operation="search_user_trash")

    async def count_user_trash_filtered(
        self,
        *,
        owner_id: uuid.UUID,
        include_purged: bool = False,
        status: Any | None = None,
        restore_available: bool | None = None,
        deleted_from: datetime | None = None,
        deleted_to: datetime | None = None,
        expires_before: datetime | None = None,
        query: str | None = None,
    ) -> int:
        """Считает элементы корзины владельца по расширенным фильтрам.

        Возвращает количество элементов корзины указанного владельца с теми же
        фильтрами, которые используются при поиске элементов корзины. При наличии
        ``query`` выполняет ``JOIN`` со связанным узлом файловой системы и ищет
        совпадение по исходному пути элемента корзины или имени узла.

        Args:
            owner_id: Идентификатор владельца элементов корзины.
            include_purged: Учитывать ли окончательно удалённые элементы. Если
                ``False``, элементы с заполненным ``purged_at`` исключаются.
            status: Статус элемента корзины для фильтрации. Если ``None``,
                фильтр по статусу не применяется.
            restore_available: Признак доступности восстановления. Если
                ``None``, фильтр по доступности восстановления не применяется.
            deleted_from: Нижняя граница даты удаления включительно.
            deleted_to: Верхняя граница даты удаления включительно.
            expires_before: Верхняя граница срока хранения включительно. При
                указании фильтра учитываются только элементы с непустым
                ``expires_at``.
            query: Поисковая строка. Если ``None`` или пустая строка,
                текстовый поиск не применяется.

        Returns:
            Количество элементов корзины владельца, соответствующих фильтрам.

        Raises:
            RepositoryError: Если не удалось выполнить запрос к базе данных.
        """

        conditions: list[Any] = [TrashItem.owner_id == owner_id]
        if not include_purged:
            conditions.append(TrashItem.purged_at.is_(None))
        if status is not None:
            conditions.append(TrashItem.status == status)
        if restore_available is not None:
            conditions.append(TrashItem.restore_available.is_(restore_available))
        if deleted_from is not None:
            conditions.append(TrashItem.deleted_at >= deleted_from)
        if deleted_to is not None:
            conditions.append(TrashItem.deleted_at <= deleted_to)
        if expires_before is not None:
            conditions.append(TrashItem.expires_at.is_not(None))
            conditions.append(TrashItem.expires_at <= expires_before)
        statement = select(func.count()).select_from(TrashItem).where(and_(*conditions))
        if query:
            like_query = f"%{query.strip().lower()}%"
            statement = statement.join(
                self.nodes.model, TrashItem.node_id == self.nodes.model.id
            ).where(
                or_(
                    func.lower(TrashItem.original_path).like(like_query),
                    func.lower(self.nodes.model.name).like(like_query),
                )
            )

        result = await self.session.execute(statement)
        return int(result.scalar_one() or 0)

    async def count_expired_items(
        self,
        *,
        now: datetime | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> int:
        """Возвращает количество элементов корзины с истёкшим сроком хранения.

        Args:
            now: Момент времени для проверки истечения срока хранения.
            owner_id: Фильтр по владельцу элементов корзины.

        Returns:
            Количество истёкших и ещё не очищенных элементов корзины.
        """

        current_time = now or self._utc_now()

        conditions: list[Any] = [
            TrashItem.expires_at.is_not(None),
            TrashItem.expires_at <= current_time,
            TrashItem.purged_at.is_(None),
        ]

        if owner_id is not None:
            conditions.append(TrashItem.owner_id == owner_id)

        return await self.count(*conditions)

    async def trash_item_exists_for_node(
        self,
        node_id: uuid.UUID,
        *,
        include_purged: bool = True,
    ) -> bool:
        """Проверяет, существует ли элемент корзины для указанного узла.

        Args:
            node_id: Идентификатор узла файловой системы.
            include_purged: Учитывать ли окончательно удалённые элементы.

        Returns:
            ``True``, если элемент корзины для узла существует, иначе ``False``.
        """

        conditions: list[Any] = [
            TrashItem.node_id == node_id,
        ]

        if not include_purged:
            conditions.append(TrashItem.purged_at.is_(None))

        return await self.exists(*conditions)

    async def can_restore(
        self,
        *,
        trash_item_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        check_expiration: bool = False,
        now: datetime | None = None,
    ) -> bool:
        """Проверяет, можно ли восстановить элемент корзины.

        Метод возвращает ``False``, если элемент не найден, недоступен для
        восстановления, уже очищен окончательно или, при
        ``check_expiration=True``, срок хранения истёк.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.
            check_expiration: Проверять ли срок хранения.
            now: Момент времени для проверки срока хранения.

        Returns:
            ``True``, если элемент можно восстановить, иначе ``False``.

        Raises:
            InvalidQueryError: Если переданы некорректные идентификаторы.
        """

        trash_item = await self._get_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        if trash_item is None:
            return False

        if not trash_item.restore_available:
            return False

        if trash_item.purged_at is not None:
            return False

        if check_expiration and trash_item.expires_at is not None:
            current_time = now or self._utc_now()

            if trash_item.expires_at <= current_time:
                return False

        return True

    async def is_expired(
        self,
        *,
        trash_item_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Проверяет, истёк ли срок хранения элемента корзины.

        Если элемент не найден или ``expires_at`` не установлен, возвращает
        ``False``.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.
            now: Момент времени для проверки истечения срока хранения.

        Returns:
            ``True``, если срок хранения элемента истёк, иначе ``False``.

        Raises:
            InvalidQueryError: Если переданы некорректные идентификаторы.
        """

        trash_item = await self._get_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        if trash_item is None:
            return False

        if trash_item.expires_at is None:
            return False

        return trash_item.expires_at <= (now or self._utc_now())

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    async def _get_by_trash_item_id_or_node_id(
        self,
        *,
        trash_item_id: uuid.UUID | None,
        node_id: uuid.UUID | None,
    ) -> TrashItem | None:
        """Возвращает элемент корзины по ``trash_item_id`` или ``node_id``.

        Нужно передать ровно один идентификатор.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.

        Returns:
            Элемент корзины, если он найден, иначе ``None``.

        Raises:
            InvalidQueryError: Если не передан ни один идентификатор
                или переданы оба идентификатора.
        """

        self._validate_single_lookup(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        if trash_item_id is not None:
            return await self.get_by_id(trash_item_id)

        assert node_id is not None

        return await self.get_by_node_id(node_id)

    async def _get_required_by_trash_item_id_or_node_id(
        self,
        *,
        trash_item_id: uuid.UUID | None,
        node_id: uuid.UUID | None,
    ) -> TrashItem:
        """Возвращает обязательный элемент по ``trash_item_id`` или ``node_id``.

        Нужно передать ровно один идентификатор.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.

        Returns:
            Найденный элемент корзины.

        Raises:
            InvalidQueryError: Если не передан ни один идентификатор
                или переданы оба идентификатора.
            EntityNotFoundError: Если элемент корзины не найден.
        """

        trash_item = await self._get_by_trash_item_id_or_node_id(
            trash_item_id=trash_item_id,
            node_id=node_id,
        )

        if trash_item is None:
            raise EntityNotFoundError(
                "TrashItem",
                lookup={
                    "trash_item_id": str(trash_item_id)
                    if trash_item_id is not None
                    else None,
                    "node_id": str(node_id) if node_id is not None else None,
                },
                repository=self.repository_name,
            )

        return trash_item

    def _validate_single_lookup(
        self,
        *,
        trash_item_id: uuid.UUID | None,
        node_id: uuid.UUID | None,
    ) -> None:
        """Проверяет, что передан ровно один идентификатор для поиска.

        Args:
            trash_item_id: Идентификатор элемента корзины.
            node_id: Идентификатор связанного узла файловой системы.

        Raises:
            InvalidQueryError: Если не передан ни один идентификатор
                или переданы оба идентификатора.
        """

        if trash_item_id is None and node_id is None:
            raise InvalidQueryError(
                "Необходимо передать trash_item_id или node_id.",
                repository=self.repository_name,
                operation="_validate_single_lookup",
            )

        if trash_item_id is not None and node_id is not None:
            raise InvalidQueryError(
                "Нужно передать только один идентификатор: trash_item_id или node_id.",
                repository=self.repository_name,
                operation="_validate_single_lookup",
                details={
                    "trash_item_id": str(trash_item_id),
                    "node_id": str(node_id),
                },
            )

    def _validate_original_path(
        self,
        original_path: str,
    ) -> str:
        """Проверяет и нормализует исходный путь удалённого узла.

        Добавляет начальный ``/``, удаляет повторяющиеся слэши и завершающий
        слэш, если путь не является корневым.

        Args:
            original_path: Исходный путь удалённого узла.

        Returns:
            Нормализованный исходный путь.

        Raises:
            InvalidQueryError: Если исходный путь пустой.
        """

        normalized_path = original_path.strip()

        if not normalized_path:
            raise InvalidQueryError(
                "Исходный путь элемента корзины не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_original_path",
                details={"field": "original_path"},
            )

        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"

        while "//" in normalized_path:
            normalized_path = normalized_path.replace("//", "/")

        if len(normalized_path) > 1:
            normalized_path = normalized_path.rstrip("/")

        return normalized_path

    def _validate_expiration(
        self,
        *,
        deleted_at: datetime,
        expires_at: datetime | None,
    ) -> None:
        """Проверяет срок хранения элемента корзины.

        Если ``expires_at`` передан, он должен быть позже времени удаления.

        Args:
            deleted_at: Дата удаления элемента.
            expires_at: Дата истечения срока хранения.

        Raises:
            InvalidQueryError: Если срок хранения меньше либо равен времени
                удаления.
        """

        if expires_at is None:
            return

        if expires_at <= deleted_at:
            raise InvalidQueryError(
                "Срок истечения элемента корзины должен быть позже времени удаления.",
                repository=self.repository_name,
                operation="_validate_expiration",
                details={
                    "deleted_at": str(deleted_at),
                    "expires_at": str(expires_at),
                },
            )

    def _get_order_by(
        self,
        sort_by: TrashItemSortField,
        sort_direction: TrashSortDirection,
    ) -> Any:
        """Возвращает SQLAlchemy-выражение сортировки элементов корзины.

        Args:
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки: ``asc`` или ``desc``.

        Returns:
            SQLAlchemy-выражение для ``order_by``.

        Raises:
            InvalidQueryError: Если поле или направление сортировки недопустимы.
        """

        allowed_fields: dict[str, Any] = {
            "deleted_at": TrashItem.deleted_at,
            "expires_at": TrashItem.expires_at,
            "purged_at": TrashItem.purged_at,
            "original_path": TrashItem.original_path,
            "restore_available": TrashItem.restore_available,
        }

        if sort_by not in allowed_fields:
            raise InvalidQueryError(
                "Недопустимое поле сортировки элементов корзины.",
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
    # Переопределённые методы
    # ------------------------------------------------------------------

    async def create(
        self,
        entity: TrashItem,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> TrashItem:
        """Добавляет элемент корзины в текущую сессию.

        Переопределяет базовый метод для более понятной ошибки при конфликте
        уникальности по ``node_id``.

        Args:
            entity: ORM-объект элемента корзины.
            flush: Выполнить ``flush`` после добавления.
            refresh: Выполнить ``refresh`` после добавления.

        Returns:
            Созданный элемент корзины.

        Raises:
            DuplicateEntityError: Если для указанного узла уже существует
                элемент корзины.
            RepositoryError: Если произошла ошибка SQLAlchemy.
        """

        try:
            return await super().create(
                entity,
                flush=flush,
                refresh=refresh,
            )

        except DuplicateEntityError as exc:
            raise DuplicateEntityError(
                "TrashItem",
                field="node_id",
                value=entity.node_id,
                repository=self.repository_name,
                message="Для указанного узла уже существует элемент корзины.",
            ) from exc

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_trash_item",
            ) from exc

    async def _execute_trash_item_statement(
        self,
        statement: Select[tuple[TrashItem]],
        *,
        operation: str,
    ) -> list[TrashItem]:
        """Выполняет ``SELECT``-запрос для модели ``TrashItem``.

        Args:
            statement: SQLAlchemy ``SELECT``-запрос.
            operation: Название операции для сообщений об ошибках.

        Returns:
            Список найденных элементов корзины.

        Raises:
            DuplicateEntityError: Если произошёл конфликт уникальности.
            RepositoryError: Если произошла ошибка SQLAlchemy.
        """

        try:
            result = await self.session.execute(statement)

            return list(result.scalars().all())

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation=operation,
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation=operation,
                reason=str(exc),
                cause=exc,
            ) from exc
