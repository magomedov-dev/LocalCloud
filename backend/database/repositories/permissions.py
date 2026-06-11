from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import Select, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from database.exceptions import EntityNotFoundError, InvalidQueryError
from database.models.filesystem import FileSystemNode
from database.models.permissions import NodePermission
from database.repositories.base import BaseRepository

_UNSET: Final = object()


class NodePermissionsRepository(BaseRepository[NodePermission]):
    """Репозиторий для работы с разрешениями на узлы файловой системы.

    Инкапсулирует операции получения, выдачи, обновления, продления,
    отзыва, восстановления, проверки доступа, массового отзыва,
    выборки и подсчёта разрешений.

    Работает с моделью ``NodePermission`` и таблицей ``node_permissions``.

    Разрешение считается активным, если оно не отозвано, не истекло
    и содержит хотя бы один включённый флаг доступа.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий разрешений на узлы файловой системы.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=NodePermission)

    # ------------------------------------------------------------------
    # Базовое получение разрешений
    # ------------------------------------------------------------------

    async def get_permission_by_id(
        self,
        permission_id: uuid.UUID,
    ) -> NodePermission | None:
        """Возвращает разрешение по идентификатору.

        Args:
            permission_id: Идентификатор разрешения.

        Returns:
            Разрешение, если оно найдено, иначе ``None``.
        """

        return await self.get_by_id(permission_id)

    async def get_required_permission_by_id(
        self,
        permission_id: uuid.UUID,
    ) -> NodePermission:
        """Возвращает разрешение по идентификатору.

        Args:
            permission_id: Идентификатор разрешения.

        Returns:
            Найденное разрешение.

        Raises:
            EntityNotFoundError: Если разрешение не найдено.
        """

        return await self.get_required_by_id(permission_id)

    async def get_by_node_and_user(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> NodePermission | None:
        """Возвращает разрешение пользователя на конкретный узел.

        Метод возвращает запись независимо от того, была ли она отозвана
        или истекла по времени.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.

        Returns:
            Разрешение пользователя на узел, если оно найдено, иначе ``None``.
        """

        statement = (
            select(NodePermission)
            .where(
                NodePermission.node_id == node_id,
                NodePermission.user_id == user_id,
            )
            .options(
                selectinload(NodePermission.node),
                selectinload(NodePermission.user),
                selectinload(NodePermission.grantor),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_node_and_user",
        )

    async def get_required_by_node_and_user(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> NodePermission:
        """Возвращает разрешение пользователя на конкретный узел.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.

        Returns:
            Найденное разрешение.

        Raises:
            EntityNotFoundError: Если разрешение не найдено.
        """

        permission = await self.get_by_node_and_user(
            node_id=node_id,
            user_id=user_id,
        )

        if permission is None:
            raise EntityNotFoundError(
                "NodePermission",
                lookup={
                    "node_id": str(node_id),
                    "user_id": str(user_id),
                },
                repository=self.repository_name,
            )

        return permission

    async def get_active_by_node_and_user(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> NodePermission | None:
        """Возвращает активное разрешение пользователя на конкретный узел.

        Активным считается разрешение, которое:

        * не отозвано;
        * не истекло по времени;
        * содержит хотя бы один включённый флаг доступа.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки срока действия разрешения.
                Если не передан, используется текущее UTC-время.

        Returns:
            Активное разрешение, если оно найдено, иначе ``None``.
        """

        effective_moment = self._normalize_moment(moment)

        statement = (
            select(NodePermission)
            .where(
                NodePermission.node_id == node_id,
                NodePermission.user_id == user_id,
                *self._active_conditions(effective_moment),
            )
            .options(
                selectinload(NodePermission.node),
                selectinload(NodePermission.user),
                selectinload(NodePermission.grantor),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_active_by_node_and_user",
        )

    async def get_required_active_by_node_and_user(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> NodePermission:
        """Возвращает активное разрешение пользователя на конкретный узел.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки срока действия разрешения.

        Returns:
            Найденное активное разрешение.

        Raises:
            EntityNotFoundError: Если активное разрешение не найдено.
        """

        permission = await self.get_active_by_node_and_user(
            node_id=node_id,
            user_id=user_id,
            moment=moment,
        )

        if permission is None:
            raise EntityNotFoundError(
                "NodePermission",
                lookup={
                    "node_id": str(node_id),
                    "user_id": str(user_id),
                    "active": True,
                },
                repository=self.repository_name,
            )

        return permission

    # ------------------------------------------------------------------
    # Выдача и обновление разрешений
    # ------------------------------------------------------------------

    async def grant_permission(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        granted_by: uuid.UUID | None = None,
        can_read: bool = True,
        can_download: bool = False,
        can_write: bool = False,
        can_delete: bool = False,
        can_share: bool = False,
        expires_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> NodePermission:
        """Выдаёт пользователю разрешение на узел файловой системы.

        Если запись для пары ``node_id + user_id`` уже существует, метод
        переиспользует её: обновляет флаги доступа, срок действия, автора выдачи
        и снимает отзыв через ``revoked_at=None``.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя, которому выдаётся доступ.
            granted_by: Идентификатор пользователя, выдавшего доступ.
            can_read: Разрешить чтение.
            can_download: Разрешить скачивание.
            can_write: Разрешить запись.
            can_delete: Разрешить удаление.
            can_share: Разрешить управление доступом.
            expires_at: Дата и время истечения разрешения. ``None`` означает
                бессрочный доступ.
            flush: Выполнить ``flush`` после создания или обновления.
            refresh: Выполнить ``refresh`` после создания или обновления.

        Returns:
            Созданное или обновлённое разрешение.

        Raises:
            InvalidQueryError: Если не включён ни один флаг доступа.
            DuplicateEntityError: Если возник конфликт уникальности при создании.
        """

        self._validate_any_permission(
            can_read=can_read,
            can_download=can_download,
            can_write=can_write,
            can_delete=can_delete,
            can_share=can_share,
        )

        existing_permission = await self.get_by_node_and_user(
            node_id=node_id,
            user_id=user_id,
        )

        if existing_permission is not None:
            return await self.update_permission(
                existing_permission,
                can_read=can_read,
                can_download=can_download,
                can_write=can_write,
                can_delete=can_delete,
                can_share=can_share,
                granted_by=granted_by,
                expires_at=expires_at,
                revoked_at=None,
                flush=flush,
                refresh=refresh,
            )

        permission = NodePermission(
            node_id=node_id,
            user_id=user_id,
            granted_by=granted_by,
            can_read=can_read,
            can_download=can_download,
            can_write=can_write,
            can_delete=can_delete,
            can_share=can_share,
            expires_at=expires_at,
            revoked_at=None,
        )

        return await self.create(
            permission,
            flush=flush,
            refresh=refresh,
        )

    async def update_permission(
        self,
        permission: NodePermission,
        *,
        can_read: bool | None = None,
        can_download: bool | None = None,
        can_write: bool | None = None,
        can_delete: bool | None = None,
        can_share: bool | None = None,
        granted_by: uuid.UUID | None | object = _UNSET,
        expires_at: datetime | None | object = _UNSET,
        revoked_at: datetime | None | object = _UNSET,
        flush: bool = True,
        refresh: bool = False,
    ) -> NodePermission:
        """Обновляет существующую запись разрешения.

        Для флагов доступа значение ``None`` означает, что флаг не изменяется.
        Для ``granted_by``, ``expires_at`` и ``revoked_at`` используется sentinel
        ``_UNSET``: ``_UNSET`` означает «не изменять поле», а ``None`` означает
        «явно очистить поле».

        Args:
            permission: ORM-объект разрешения.
            can_read: Новое значение права чтения.
            can_download: Новое значение права скачивания.
            can_write: Новое значение права записи.
            can_delete: Новое значение права удаления.
            can_share: Новое значение права управления доступом.
            granted_by: Новый автор выдачи доступа, ``None`` для очистки или
                ``_UNSET`` без изменений.
            expires_at: Новый срок действия, ``None`` для бессрочного доступа
                или ``_UNSET`` без изменений.
            revoked_at: Дата отзыва, ``None`` для восстановления или ``_UNSET``
                без изменений.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённое разрешение.

        Raises:
            InvalidQueryError: Если после обновления не остаётся ни одного флага доступа.
        """

        values: dict[str, Any] = {}

        if can_read is not None:
            values["can_read"] = can_read

        if can_download is not None:
            values["can_download"] = can_download

        if can_write is not None:
            values["can_write"] = can_write

        if can_delete is not None:
            values["can_delete"] = can_delete

        if can_share is not None:
            values["can_share"] = can_share

        if granted_by is not _UNSET:
            values["granted_by"] = granted_by

        if expires_at is not _UNSET:
            values["expires_at"] = expires_at

        if revoked_at is not _UNSET:
            values["revoked_at"] = revoked_at

        next_can_read = values.get("can_read", permission.can_read)
        next_can_download = values.get("can_download", permission.can_download)
        next_can_write = values.get("can_write", permission.can_write)
        next_can_delete = values.get("can_delete", permission.can_delete)
        next_can_share = values.get("can_share", permission.can_share)

        self._validate_any_permission(
            can_read=next_can_read,
            can_download=next_can_download,
            can_write=next_can_write,
            can_delete=next_can_delete,
            can_share=next_can_share,
        )

        return await self.update(
            permission,
            values,
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "can_read",
                "can_download",
                "can_write",
                "can_delete",
                "can_share",
                "granted_by",
                "expires_at",
                "revoked_at",
            },
        )

    async def update_permission_by_node_and_user(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        can_read: bool | None = None,
        can_download: bool | None = None,
        can_write: bool | None = None,
        can_delete: bool | None = None,
        can_share: bool | None = None,
        granted_by: uuid.UUID | None | object = _UNSET,
        expires_at: datetime | None | object = _UNSET,
        revoked_at: datetime | None | object = _UNSET,
        flush: bool = True,
        refresh: bool = False,
    ) -> NodePermission:
        """Обновляет разрешение по паре ``node_id + user_id``.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            can_read: Новое значение права чтения.
            can_download: Новое значение права скачивания.
            can_write: Новое значение права записи.
            can_delete: Новое значение права удаления.
            can_share: Новое значение права управления доступом.
            granted_by: Новый автор выдачи доступа, ``None`` для очистки или
                ``_UNSET`` без изменений.
            expires_at: Новый срок действия, ``None`` для бессрочного доступа
                или ``_UNSET`` без изменений.
            revoked_at: Дата отзыва, ``None`` для восстановления или ``_UNSET``
                без изменений.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённое разрешение.

        Raises:
            EntityNotFoundError: Если разрешение не найдено.
            InvalidQueryError: Если после обновления не остаётся ни одного флага доступа.
        """

        permission = await self.get_required_by_node_and_user(
            node_id=node_id,
            user_id=user_id,
        )

        return await self.update_permission(
            permission,
            can_read=can_read,
            can_download=can_download,
            can_write=can_write,
            can_delete=can_delete,
            can_share=can_share,
            granted_by=granted_by,
            expires_at=expires_at,
            revoked_at=revoked_at,
            flush=flush,
            refresh=refresh,
        )

    async def extend_permission(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        expires_at: datetime | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> NodePermission:
        """Изменяет срок действия разрешения.

        Передача ``expires_at=None`` делает разрешение бессрочным.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            expires_at: Новая дата истечения разрешения или ``None`` для
                бессрочного доступа.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённое разрешение.

        Raises:
            EntityNotFoundError: Если разрешение не найдено.
        """

        return await self.update_permission_by_node_and_user(
            node_id=node_id,
            user_id=user_id,
            expires_at=expires_at,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Отзыв разрешений
    # ------------------------------------------------------------------

    async def revoke_permission(
        self,
        permission: NodePermission,
        *,
        revoked_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> NodePermission:
        """Отзывает конкретное разрешение.

        Отзыв выполняется установкой поля ``revoked_at``.

        Args:
            permission: ORM-объект разрешения.
            revoked_at: Дата отзыва. Если не передана, используется текущее
                UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Отозванное разрешение.
        """

        effective_revoked_at = self._normalize_moment(revoked_at)

        return await self.update(
            permission,
            {"revoked_at": effective_revoked_at},
            flush=flush,
            refresh=refresh,
            allowed_fields={"revoked_at"},
        )

    async def revoke_permission_by_id(
        self,
        permission_id: uuid.UUID,
        *,
        revoked_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> NodePermission:
        """Отзывает разрешение по идентификатору.

        Args:
            permission_id: Идентификатор разрешения.
            revoked_at: Дата отзыва. Если не передана, используется текущее
                UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Отозванное разрешение.

        Raises:
            EntityNotFoundError: Если разрешение не найдено.
        """

        permission = await self.get_required_by_id(permission_id)

        return await self.revoke_permission(
            permission,
            revoked_at=revoked_at,
            flush=flush,
            refresh=refresh,
        )

    async def revoke_permission_by_node_and_user(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        revoked_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> NodePermission:
        """Отзывает разрешение пользователя на конкретный узел.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            revoked_at: Дата отзыва. Если не передана, используется текущее
                UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Отозванное разрешение.

        Raises:
            EntityNotFoundError: Если разрешение не найдено.
        """

        permission = await self.get_required_by_node_and_user(
            node_id=node_id,
            user_id=user_id,
        )

        return await self.revoke_permission(
            permission,
            revoked_at=revoked_at,
            flush=flush,
            refresh=refresh,
        )

    async def restore_permission(
        self,
        permission: NodePermission,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> NodePermission:
        """Восстанавливает ранее отозванное разрешение.

        Восстановление выполняется очисткой поля ``revoked_at``.

        Args:
            permission: ORM-объект разрешения.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Восстановленное разрешение.

        Raises:
            InvalidQueryError: Если разрешение не содержит ни одного флага доступа.
        """

        return await self.update_permission(
            permission,
            revoked_at=None,
            flush=flush,
            refresh=refresh,
        )

    async def restore_permission_by_node_and_user(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        flush: bool = True,
        refresh: bool = False,
    ) -> NodePermission:
        """Восстанавливает разрешение по паре ``node_id + user_id``.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Восстановленное разрешение.

        Raises:
            EntityNotFoundError: Если разрешение не найдено.
            InvalidQueryError: Если разрешение не содержит ни одного флага доступа.
        """

        permission = await self.get_required_by_node_and_user(
            node_id=node_id,
            user_id=user_id,
        )

        return await self.restore_permission(
            permission,
            flush=flush,
            refresh=refresh,
        )

    async def revoke_all_node_permissions(
        self,
        *,
        node_id: uuid.UUID,
        revoked_at: datetime | None = None,
        only_active: bool = True,
        flush: bool = True,
    ) -> int:
        """Отзывает все разрешения, выданные на конкретный узел.

        Args:
            node_id: Идентификатор узла файловой системы.
            revoked_at: Дата отзыва. Если не передана, используется текущее
                UTC-время.
            only_active: Отзывать только неотозванные разрешения.
            flush: Выполнить ``flush`` после массового обновления.

        Returns:
            Количество обновлённых разрешений.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        effective_revoked_at = self._normalize_moment(revoked_at)

        conditions: list[Any] = [NodePermission.node_id == node_id]

        if only_active:
            conditions.append(NodePermission.revoked_at.is_(None))

        return await self._bulk_revoke(
            conditions=conditions,
            revoked_at=effective_revoked_at,
            operation="revoke_all_node_permissions",
            flush=flush,
        )

    async def revoke_all_user_permissions(
        self,
        *,
        user_id: uuid.UUID,
        revoked_at: datetime | None = None,
        only_active: bool = True,
        flush: bool = True,
    ) -> int:
        """Отзывает все разрешения, выданные конкретному пользователю.

        Args:
            user_id: Идентификатор пользователя.
            revoked_at: Дата отзыва. Если не передана, используется текущее
                UTC-время.
            only_active: Отзывать только неотозванные разрешения.
            flush: Выполнить ``flush`` после массового обновления.

        Returns:
            Количество обновлённых разрешений.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        effective_revoked_at = self._normalize_moment(revoked_at)

        conditions: list[Any] = [NodePermission.user_id == user_id]

        if only_active:
            conditions.append(NodePermission.revoked_at.is_(None))

        return await self._bulk_revoke(
            conditions=conditions,
            revoked_at=effective_revoked_at,
            operation="revoke_all_user_permissions",
            flush=flush,
        )

    async def revoke_permissions_granted_by_user(
        self,
        *,
        granted_by: uuid.UUID,
        revoked_at: datetime | None = None,
        only_active: bool = True,
        flush: bool = True,
    ) -> int:
        """Отзывает все разрешения, выданные указанным пользователем.

        Args:
            granted_by: Идентификатор пользователя, выдавшего разрешения.
            revoked_at: Дата отзыва. Если не передана, используется текущее
                UTC-время.
            only_active: Отзывать только неотозванные разрешения.
            flush: Выполнить ``flush`` после массового обновления.

        Returns:
            Количество обновлённых разрешений.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        effective_revoked_at = self._normalize_moment(revoked_at)

        conditions: list[Any] = [NodePermission.granted_by == granted_by]

        if only_active:
            conditions.append(NodePermission.revoked_at.is_(None))

        return await self._bulk_revoke(
            conditions=conditions,
            revoked_at=effective_revoked_at,
            operation="revoke_permissions_granted_by_user",
            flush=flush,
        )

    # ------------------------------------------------------------------
    # Получение списков разрешений
    # ------------------------------------------------------------------

    async def get_node_permissions(
        self,
        *,
        node_id: uuid.UUID,
        active_only: bool = False,
        moment: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[NodePermission]:
        """Возвращает разрешения, выданные на конкретный узел.

        Args:
            node_id: Идентификатор узла файловой системы.
            active_only: Возвращать только активные разрешения.
            moment: Момент времени для проверки активности разрешений.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список разрешений на указанный узел.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(NodePermission)
            .where(NodePermission.node_id == node_id)
            .options(
                selectinload(NodePermission.user),
                selectinload(NodePermission.grantor),
            )
        )

        if active_only:
            effective_moment = self._normalize_moment(moment)
            statement = statement.where(*self._active_conditions(effective_moment))

        statement = (
            statement.order_by(NodePermission.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_node_permissions",
        )

    async def get_distinct_active_granted_node_ids(
        self,
        *,
        granted_by: uuid.UUID,
        moment: datetime | None = None,
    ) -> list[uuid.UUID]:
        """Возвращает уникальные id узлов с активными грантами пользователя.

        Одним лёгким запросом (``SELECT DISTINCT node_id``), без гидрации ORM-
        объектов и без постраничного обхода. Нужно для бейджа «доступ выдан».

        Args:
            granted_by: Идентификатор пользователя, выдавшего гранты.
            moment: Момент времени для проверки активности (по умолчанию — now).

        Returns:
            Список уникальных идентификаторов узлов.
        """

        effective_moment = self._normalize_moment(moment)
        statement = (
            select(NodePermission.node_id)
            .where(
                NodePermission.granted_by == granted_by,
                *self._active_conditions(effective_moment),
            )
            .distinct()
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_active_ancestor_permissions(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> list[NodePermission]:
        """Возвращает активные разрешения пользователя на предков узла.

        Одним запросом: рекурсивный CTE поднимается по цепочке ``parent_id``
        (пропуская удалённых предков) и сразу джойнится к ``node_permissions``.
        Заменяет обход предков по одному (N+1). Нужно для наследования прав:
        доступ к папке распространяется на её содержимое.

        Args:
            node_id: Идентификатор узла, для которого ищутся права предков.
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки активности (по умолчанию — now).

        Returns:
            Список активных разрешений пользователя на неудалённых предках узла.
        """

        effective_moment = self._normalize_moment(moment)

        ancestors_cte = (
            select(FileSystemNode.id, FileSystemNode.parent_id)
            .where(FileSystemNode.id == node_id)
            .cte(name="permission_ancestors", recursive=True)
        )
        parent_alias = aliased(FileSystemNode)
        ancestors_cte = ancestors_cte.union_all(
            select(parent_alias.id, parent_alias.parent_id).where(
                parent_alias.id == ancestors_cte.c.parent_id,
                parent_alias.is_deleted.is_(False),
            )
        )

        statement = select(NodePermission).where(
            NodePermission.node_id.in_(
                select(ancestors_cte.c.id).where(ancestors_cte.c.id != node_id)
            ),
            NodePermission.user_id == user_id,
            *self._active_conditions(effective_moment),
        )

        return await self.scalars_all(
            statement,
            operation="get_active_ancestor_permissions",
        )

    async def get_permissions_for_nodes(
        self,
        *,
        node_ids: list[uuid.UUID],
        active_only: bool = False,
        moment: datetime | None = None,
    ) -> list[NodePermission]:
        """Возвращает разрешения для набора узлов одним запросом.

        Пакетный аналог :meth:`get_node_permissions` для проверок доступа к
        спискам узлов (например, батч миниатюр): один ``IN``-запрос вместо
        запроса на каждый узел. Связи ``user``/``grantor`` не подгружаются —
        проверке прав нужны только скалярные поля разрешения.

        Args:
            node_ids: Идентификаторы узлов файловой системы.
            active_only: Возвращать только активные разрешения.
            moment: Момент времени для проверки активности разрешений.

        Returns:
            Список разрешений всех указанных узлов. Если список ID пустой,
            возвращается пустой список.
        """

        if not node_ids:
            return []

        statement = select(NodePermission).where(
            NodePermission.node_id.in_(node_ids)
        )

        if active_only:
            effective_moment = self._normalize_moment(moment)
            statement = statement.where(*self._active_conditions(effective_moment))

        return await self.scalars_all(
            statement,
            operation="get_permissions_for_nodes",
        )

    async def get_active_ancestor_permissions_for_nodes(
        self,
        *,
        node_ids: list[uuid.UUID],
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> list[tuple[uuid.UUID, NodePermission]]:
        """Возвращает активные разрешения пользователя на предков набора узлов.

        Пакетный аналог :meth:`get_active_ancestor_permissions`: один
        рекурсивный CTE поднимается по цепочкам ``parent_id`` сразу для всех
        узлов (пропуская удалённых предков) и джойнится к ``node_permissions``.
        Каждая строка результата привязана к исходному узлу-потомку, чтобы
        вызывающий код мог сгруппировать наследуемые права по узлам.

        Args:
            node_ids: Идентификаторы узлов, для которых ищутся права предков.
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки активности (по умолчанию — now).

        Returns:
            Список пар ``(node_id исходного узла, разрешение на его предке)``.
            Если список ID пустой, возвращается пустой список.

        Raises:
            RepositoryError: Если запрос завершился ошибкой.
        """

        if not node_ids:
            return []

        effective_moment = self._normalize_moment(moment)

        ancestors_cte = (
            select(
                FileSystemNode.id.label("descendant_id"),
                FileSystemNode.id.label("id"),
                FileSystemNode.parent_id.label("parent_id"),
            )
            .where(FileSystemNode.id.in_(node_ids))
            .cte(name="permission_ancestors_batch", recursive=True)
        )
        parent_alias = aliased(FileSystemNode)
        ancestors_cte = ancestors_cte.union_all(
            select(
                ancestors_cte.c.descendant_id,
                parent_alias.id,
                parent_alias.parent_id,
            ).where(
                parent_alias.id == ancestors_cte.c.parent_id,
                parent_alias.is_deleted.is_(False),
            )
        )

        statement = (
            select(ancestors_cte.c.descendant_id, NodePermission)
            .join(ancestors_cte, NodePermission.node_id == ancestors_cte.c.id)
            .where(
                ancestors_cte.c.id != ancestors_cte.c.descendant_id,
                NodePermission.user_id == user_id,
                *self._active_conditions(effective_moment),
            )
        )

        try:
            result = await self.session.execute(statement)
            return [(row[0], row[1]) for row in result.all()]
        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_active_ancestor_permissions_for_nodes",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def get_user_permissions(
        self,
        *,
        user_id: uuid.UUID,
        active_only: bool = False,
        moment: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[NodePermission]:
        """Возвращает разрешения, выданные конкретному пользователю.

        Args:
            user_id: Идентификатор пользователя.
            active_only: Возвращать только активные разрешения.
            moment: Момент времени для проверки активности разрешений.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список разрешений пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(NodePermission)
            .where(NodePermission.user_id == user_id)
            .options(
                # Грузим File узла, чтобы «Доступно мне» знало mime/размер без
                # ленивой подгрузки (как сделано для public links в links.py).
                selectinload(NodePermission.node).selectinload(FileSystemNode.file),
                selectinload(NodePermission.grantor),
            )
        )

        if active_only:
            effective_moment = self._normalize_moment(moment)
            statement = statement.where(*self._active_conditions(effective_moment))

        statement = (
            statement.order_by(NodePermission.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_user_permissions",
        )

    async def get_granted_by_user(
        self,
        *,
        granted_by: uuid.UUID,
        active_only: bool = False,
        moment: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[NodePermission]:
        """Возвращает разрешения, выданные конкретным пользователем.

        Args:
            granted_by: Идентификатор пользователя, выдавшего разрешения.
            active_only: Возвращать только активные разрешения.
            moment: Момент времени для проверки активности разрешений.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список разрешений, выданных пользователем.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(NodePermission)
            .where(NodePermission.granted_by == granted_by)
            .options(
                selectinload(NodePermission.node),
                selectinload(NodePermission.user),
            )
        )

        if active_only:
            effective_moment = self._normalize_moment(moment)
            statement = statement.where(*self._active_conditions(effective_moment))

        statement = (
            statement.order_by(NodePermission.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_granted_by_user",
        )

    async def get_accessible_node_ids(
        self,
        *,
        user_id: uuid.UUID,
        require_read: bool = False,
        require_download: bool = False,
        require_write: bool = False,
        require_delete: bool = False,
        require_share: bool = False,
        moment: datetime | None = None,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[uuid.UUID]:
        """Возвращает идентификаторы узлов, доступных пользователю по разрешениям.

        Метод учитывает только записи ``node_permissions``. Владение объектом через
        ``file_system_nodes.owner_id`` должно учитываться отдельно в сервисном слое.

        Args:
            user_id: Идентификатор пользователя.
            require_read: Требовать право чтения.
            require_download: Требовать право скачивания.
            require_write: Требовать право записи.
            require_delete: Требовать право удаления.
            require_share: Требовать право управления доступом.
            moment: Момент времени для проверки активности разрешений.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список идентификаторов доступных узлов.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
            RepositoryError: Если произошла ошибка при выполнении запроса.
        """

        self._validate_pagination(offset=offset, limit=limit)

        effective_moment = self._normalize_moment(moment)

        statement = select(NodePermission.node_id).where(
            NodePermission.user_id == user_id,
            *self._active_conditions(effective_moment),
        )

        permission_conditions = self._required_permission_conditions(
            require_read=require_read,
            require_download=require_download,
            require_write=require_write,
            require_delete=require_delete,
            require_share=require_share,
        )

        if permission_conditions:
            statement = statement.where(*permission_conditions)

        statement = (
            statement.order_by(NodePermission.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self._execute_uuid_scalars(
            statement,
            operation="get_accessible_node_ids",
        )

    # ------------------------------------------------------------------
    # Проверки доступа
    # ------------------------------------------------------------------

    async def user_has_permission(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        require_read: bool = False,
        require_download: bool = False,
        require_write: bool = False,
        require_delete: bool = False,
        require_share: bool = False,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет, имеет ли пользователь активное разрешение на узел.

        Если флаги ``require_*`` не переданы, проверяется наличие любого активного
        разрешения. Если один или несколько флагов переданы, разрешение должно
        содержать все требуемые права.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            require_read: Требовать право чтения.
            require_download: Требовать право скачивания.
            require_write: Требовать право записи.
            require_delete: Требовать право удаления.
            require_share: Требовать право управления доступом.
            moment: Момент времени для проверки активности разрешения.

        Returns:
            ``True``, если пользователь имеет подходящее активное разрешение,
            иначе ``False``.
        """

        effective_moment = self._normalize_moment(moment)

        statement = select(NodePermission.id).where(
            NodePermission.node_id == node_id,
            NodePermission.user_id == user_id,
            *self._active_conditions(effective_moment),
        )

        permission_conditions = self._required_permission_conditions(
            require_read=require_read,
            require_download=require_download,
            require_write=require_write,
            require_delete=require_delete,
            require_share=require_share,
        )

        if permission_conditions:
            statement = statement.where(*permission_conditions)

        statement = statement.limit(1)

        value = await self.scalar_value(
            statement,
            operation="user_has_permission",
        )

        return value is not None

    async def user_can_read(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет наличие активного права чтения.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки активности разрешения.

        Returns:
            ``True``, если пользователь может читать узел, иначе ``False``.
        """

        return await self.user_has_permission(
            node_id=node_id,
            user_id=user_id,
            require_read=True,
            moment=moment,
        )

    async def user_can_download(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет наличие активного права скачивания.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки активности разрешения.

        Returns:
            ``True``, если пользователь может скачивать узел, иначе ``False``.
        """

        return await self.user_has_permission(
            node_id=node_id,
            user_id=user_id,
            require_download=True,
            moment=moment,
        )

    async def user_can_write(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет наличие активного права записи.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки активности разрешения.

        Returns:
            ``True``, если пользователь может изменять узел, иначе ``False``.
        """

        return await self.user_has_permission(
            node_id=node_id,
            user_id=user_id,
            require_write=True,
            moment=moment,
        )

    async def user_can_delete(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет наличие активного права удаления.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки активности разрешения.

        Returns:
            ``True``, если пользователь может удалять узел, иначе ``False``.
        """

        return await self.user_has_permission(
            node_id=node_id,
            user_id=user_id,
            require_delete=True,
            moment=moment,
        )

    async def user_can_share(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет наличие активного права управления доступом.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки активности разрешения.

        Returns:
            ``True``, если пользователь может управлять доступом к узлу,
            иначе ``False``.
        """

        return await self.user_has_permission(
            node_id=node_id,
            user_id=user_id,
            require_share=True,
            moment=moment,
        )

    # ------------------------------------------------------------------
    # Подсчёты
    # ------------------------------------------------------------------

    async def count_node_permissions(
        self,
        *,
        node_id: uuid.UUID,
        active_only: bool = False,
        moment: datetime | None = None,
    ) -> int:
        """Возвращает количество разрешений, выданных на узел.

        Args:
            node_id: Идентификатор узла файловой системы.
            active_only: Учитывать только активные разрешения.
            moment: Момент времени для проверки активности разрешений.

        Returns:
            Количество разрешений на узел.
        """

        conditions: list[Any] = [NodePermission.node_id == node_id]

        if active_only:
            effective_moment = self._normalize_moment(moment)
            conditions.extend(self._active_conditions(effective_moment))

        return await self.count(*conditions)

    async def count_user_permissions(
        self,
        *,
        user_id: uuid.UUID,
        active_only: bool = False,
        moment: datetime | None = None,
    ) -> int:
        """Возвращает количество разрешений, выданных пользователю.

        Args:
            user_id: Идентификатор пользователя.
            active_only: Учитывать только активные разрешения.
            moment: Момент времени для проверки активности разрешений.

        Returns:
            Количество разрешений пользователя.
        """

        conditions: list[Any] = [NodePermission.user_id == user_id]

        if active_only:
            effective_moment = self._normalize_moment(moment)
            conditions.extend(self._active_conditions(effective_moment))

        return await self.count(*conditions)

    async def count_granted_by_user(
        self,
        *,
        granted_by: uuid.UUID,
        active_only: bool = False,
        moment: datetime | None = None,
    ) -> int:
        """Возвращает количество разрешений, выданных пользователем.

        Args:
            granted_by: Идентификатор пользователя, выдавшего разрешения.
            active_only: Учитывать только активные разрешения.
            moment: Момент времени для проверки активности разрешений.

        Returns:
            Количество разрешений, выданных пользователем.
        """

        conditions: list[Any] = [NodePermission.granted_by == granted_by]

        if active_only:
            effective_moment = self._normalize_moment(moment)
            conditions.extend(self._active_conditions(effective_moment))

        return await self.count(*conditions)

    # ------------------------------------------------------------------
    # Физическое удаление разрешений
    # ------------------------------------------------------------------

    async def delete_permission_by_node_and_user(
        self,
        *,
        node_id: uuid.UUID,
        user_id: uuid.UUID,
        flush: bool = True,
        required: bool = True,
    ) -> bool:
        """Физически удаляет разрешение по паре ``node_id + user_id``.

        Для пользовательского отзыва доступа обычно следует использовать
        ``revoke_permission_by_node_and_user()``.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            flush: Выполнить ``flush`` после удаления.
            required: Выбрасывать ли ошибку, если разрешение не найдено.

        Returns:
            ``True``, если разрешение было удалено, иначе ``False``.

        Raises:
            EntityNotFoundError: Если разрешение не найдено и ``required=True``.
        """

        permission = await self.get_by_node_and_user(
            node_id=node_id,
            user_id=user_id,
        )

        if permission is None:
            if required:
                raise EntityNotFoundError(
                    "NodePermission",
                    lookup={
                        "node_id": str(node_id),
                        "user_id": str(user_id),
                    },
                    repository=self.repository_name,
                )

            return False

        await self.delete(permission, flush=flush)

        return True

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    async def _bulk_revoke(
        self,
        *,
        conditions: list[Any],
        revoked_at: datetime,
        operation: str,
        flush: bool,
    ) -> int:
        """Массово устанавливает ``revoked_at`` для разрешений.

        Args:
            conditions: SQLAlchemy-условия для выбора разрешений.
            revoked_at: Дата отзыва.
            operation: Название операции для сообщений об ошибках.
            flush: Выполнить ``flush`` после массового обновления.

        Returns:
            Количество обновлённых записей.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        try:
            statement = (
                update(NodePermission).where(*conditions).values(revoked_at=revoked_at)
            )

            result = await self.session.execute(statement)

            if flush:
                await self.flush()

            return int(getattr(result, "rowcount", 0) or 0)

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

    async def _execute_uuid_scalars(
        self,
        statement: Select[tuple[uuid.UUID]],
        *,
        operation: str,
    ) -> list[uuid.UUID]:
        """Выполняет SELECT-запрос и возвращает список UUID-значений.

        Args:
            statement: SQLAlchemy SELECT-запрос, возвращающий UUID.
            operation: Название операции для сообщений об ошибках.

        Returns:
            Список UUID-значений.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении запроса.
        """

        try:
            result = await self.session.execute(statement)

            return list(result.scalars().all())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation=operation,
                reason=str(exc),
                cause=exc,
            ) from exc

    def _active_conditions(
        self,
        moment: datetime,
    ) -> list[Any]:
        """Возвращает SQLAlchemy-условия активности разрешения.

        Разрешение считается активным, если оно не отозвано, не истекло
        и содержит хотя бы один включённый флаг доступа.

        Args:
            moment: Момент времени для проверки срока действия.

        Returns:
            Список SQLAlchemy-условий активности.
        """

        return [
            NodePermission.revoked_at.is_(None),
            or_(
                NodePermission.expires_at.is_(None),
                NodePermission.expires_at > moment,
            ),
            or_(
                NodePermission.can_read.is_(True),
                NodePermission.can_download.is_(True),
                NodePermission.can_write.is_(True),
                NodePermission.can_delete.is_(True),
                NodePermission.can_share.is_(True),
            ),
        ]

    def _required_permission_conditions(
        self,
        *,
        require_read: bool,
        require_download: bool,
        require_write: bool,
        require_delete: bool,
        require_share: bool,
    ) -> list[Any]:
        """Возвращает SQLAlchemy-условия для обязательных флагов доступа.

        Args:
            require_read: Требовать право чтения.
            require_download: Требовать право скачивания.
            require_write: Требовать право записи.
            require_delete: Требовать право удаления.
            require_share: Требовать право управления доступом.

        Returns:
            Список SQLAlchemy-условий для требуемых прав.
        """

        conditions: list[Any] = []

        if require_read:
            conditions.append(NodePermission.can_read.is_(True))

        if require_download:
            conditions.append(NodePermission.can_download.is_(True))

        if require_write:
            conditions.append(NodePermission.can_write.is_(True))

        if require_delete:
            conditions.append(NodePermission.can_delete.is_(True))

        if require_share:
            conditions.append(NodePermission.can_share.is_(True))

        return conditions

    def _validate_any_permission(
        self,
        *,
        can_read: bool,
        can_download: bool,
        can_write: bool,
        can_delete: bool,
        can_share: bool,
    ) -> None:
        """Проверяет, что включён хотя бы один флаг доступа.

        Пустое разрешение не имеет практического смысла. Для удаления доступа
        следует использовать ``revoke_permission()``.

        Args:
            can_read: Флаг права чтения.
            can_download: Флаг права скачивания.
            can_write: Флаг права записи.
            can_delete: Флаг права удаления.
            can_share: Флаг права управления доступом.

        Raises:
            InvalidQueryError: Если все флаги доступа выключены.
        """

        if not any(
            [
                can_read,
                can_download,
                can_write,
                can_delete,
                can_share,
            ]
        ):
            raise InvalidQueryError(
                "Разрешение должно содержать хотя бы один активный флаг доступа.",
                repository=self.repository_name,
                operation="_validate_any_permission",
                details={
                    "model": self.model_name,
                    "can_read": can_read,
                    "can_download": can_download,
                    "can_write": can_write,
                    "can_delete": can_delete,
                    "can_share": can_share,
                },
            )

    def _normalize_moment(
        self,
        moment: datetime | None,
    ) -> datetime:
        """Возвращает дату и время для проверки срока действия разрешения.

        Если момент не передан, используется текущее UTC-время.
        Если передан naive datetime, к нему добавляется timezone UTC.

        Args:
            moment: Момент времени для нормализации.

        Returns:
            Дата и время с информацией о часовом поясе.
        """

        if moment is None:
            return datetime.now(UTC)

        if moment.tzinfo is None:
            return moment.replace(tzinfo=UTC)

        return moment
