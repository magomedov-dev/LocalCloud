from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final, Literal, cast

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import PublicLinkPermissionType, PublicLinkStatus
from database.models.filesystem import FileSystemNode
from database.models.links import PublicLink
from database.repositories.base import BaseRepository

_UNSET: Final[object] = object()

PublicLinkSortField = Literal[
    "created_at",
    "expires_at",
    "last_accessed_at",
    "last_downloaded_at",
    "last_uploaded_at",
    "download_count",
    "view_count",
    "upload_count",
    "status",
]

SortDirection = Literal["asc", "desc"]


class PublicLinksRepository(BaseRepository[PublicLink]):
    """Репозиторий для работы с публичными ссылками.

    Инкапсулирует операции получения, создания, поиска, фильтрации,
    обновления, активации, деактивации, отзыва, регистрации просмотров,
    скачиваний и загрузок, проверки доступности, подсчёта и физического
    удаления публичных ссылок.

    Работает с моделью ``PublicLink`` через асинхронную SQLAlchemy-сессию.

    Публичная ссылка считается доступной, если она активна, не отозвана,
    не истекла по времени и не достигла лимита скачиваний.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий публичных ссылок.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=PublicLink)

    # ------------------------------------------------------------------
    # Получение по id
    # ------------------------------------------------------------------

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> PublicLink | None:
        """Возвращает публичную ссылку по идентификатору.

        Дополнительно загружает связанный узел файловой системы, создателя ссылки
        и пользователя, который отозвал ссылку.

        Args:
            entity_id: Идентификатор публичной ссылки.

        Returns:
            Публичная ссылка, если она найдена, иначе ``None``.
        """

        statement = (
            select(PublicLink)
            .where(PublicLink.id == entity_id)
            .options(
                selectinload(PublicLink.node),
                selectinload(PublicLink.creator),
                selectinload(PublicLink.revoker),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_id",
        )

    async def get_required_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> PublicLink:
        """Возвращает публичную ссылку по идентификатору.

        Args:
            entity_id: Идентификатор публичной ссылки.

        Returns:
            Найденная публичная ссылка.

        Raises:
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self.get_by_id(entity_id)

        if public_link is None:
            raise EntityNotFoundError(
                "PublicLink",
                entity_id=entity_id,
                repository=self.repository_name,
            )

        return public_link

    # ------------------------------------------------------------------
    # Получение по token
    # ------------------------------------------------------------------

    async def get_by_token(
        self,
        token: str,
    ) -> PublicLink | None:
        """Возвращает публичную ссылку по token.

        Token предварительно нормализуется.

        Args:
            token: Token публичной ссылки.

        Returns:
            Публичная ссылка, если она найдена, иначе ``None``.

        Raises:
            InvalidQueryError: Если token пустой или превышает допустимую длину.
        """

        normalized_token = self._normalize_token(token)

        statement = (
            select(PublicLink)
            .where(PublicLink.token == normalized_token)
            .options(
                selectinload(PublicLink.node),
                selectinload(PublicLink.creator),
                selectinload(PublicLink.revoker),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_token",
        )

    async def get_required_by_token(
        self,
        token: str,
    ) -> PublicLink:
        """Возвращает публичную ссылку по token.

        Args:
            token: Token публичной ссылки.

        Returns:
            Найденная публичная ссылка.

        Raises:
            InvalidQueryError: Если token некорректен.
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self.get_by_token(token)

        if public_link is None:
            raise EntityNotFoundError(
                "PublicLink",
                lookup={"token": token},
                repository=self.repository_name,
            )

        return public_link

    async def get_available_link_by_token(
        self,
        token: str,
        *,
        moment: datetime | None = None,
    ) -> PublicLink | None:
        """Возвращает доступную публичную ссылку по token.

        Ссылка считается доступной, если:
        - имеет статус ``ACTIVE``;
        - имеет ``is_active=True``;
        - не была отозвана;
        - не истекла по времени;
        - не достигла лимита скачиваний.

        Args:
            token: Token публичной ссылки.
            moment: Момент времени для проверки доступности.
                Если не передан, используется текущее UTC-время.

        Returns:
            Доступная публичная ссылка, если она найдена, иначе ``None``.

        Raises:
            InvalidQueryError: Если token некорректен.
        """

        normalized_token = self._normalize_token(token)
        effective_moment = self._normalize_moment(moment)

        statement = (
            select(PublicLink)
            .where(
                PublicLink.token == normalized_token,
                *self._available_conditions(effective_moment),
            )
            .options(
                selectinload(PublicLink.node),
                selectinload(PublicLink.creator),
                selectinload(PublicLink.revoker),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_available_link_by_token",
        )

    async def get_required_available_link_by_token(
        self,
        token: str,
        *,
        moment: datetime | None = None,
    ) -> PublicLink:
        """Возвращает доступную публичную ссылку по token.

        Args:
            token: Token публичной ссылки.
            moment: Момент времени для проверки доступности.

        Returns:
            Найденная доступная публичная ссылка.

        Raises:
            InvalidQueryError: Если token некорректен.
            EntityNotFoundError: Если доступная публичная ссылка не найдена.
        """

        public_link = await self.get_available_link_by_token(
            token,
            moment=moment,
        )

        if public_link is None:
            raise EntityNotFoundError(
                "PublicLink",
                lookup={"token": token, "available": True},
                repository=self.repository_name,
                message="Доступная публичная ссылка не найдена.",
            )

        return public_link

    async def token_exists(
        self,
        token: str,
        *,
        exclude_link_id: uuid.UUID | None = None,
    ) -> bool:
        """Проверяет существование публичной ссылки с указанным token.

        Args:
            token: Token для проверки.
            exclude_link_id: Идентификатор ссылки, которую нужно исключить из проверки.

        Returns:
            ``True``, если ссылка с таким token существует, иначе ``False``.

        Raises:
            InvalidQueryError: Если token некорректен.
        """

        normalized_token = self._normalize_token(token)

        conditions: list[Any] = [PublicLink.token == normalized_token]

        if exclude_link_id is not None:
            conditions.append(PublicLink.id != exclude_link_id)

        return await self.exists(*conditions)

    async def is_token_exists(
        self,
        token: str,
        *,
        exclude_link_id: uuid.UUID | None = None,
    ) -> bool:
        """Проверяет существование публичной ссылки с указанным token.

        Метод является алиасом для ``token_exists()``.

        Args:
            token: Token для проверки.
            exclude_link_id: Идентификатор ссылки, которую нужно исключить из проверки.

        Returns:
            ``True``, если ссылка с таким token существует, иначе ``False``.
        """

        return await self.token_exists(
            token,
            exclude_link_id=exclude_link_id,
        )

    # ------------------------------------------------------------------
    # Создание публичной ссылки
    # ------------------------------------------------------------------

    async def create_link(
        self,
        *,
        node_id: uuid.UUID,
        token: str,
        created_by: uuid.UUID | None = None,
        password_hash: str | None = None,
        permission_type: PublicLinkPermissionType = PublicLinkPermissionType.DOWNLOAD,
        status: PublicLinkStatus = PublicLinkStatus.ACTIVE,
        expires_at: datetime | None = None,
        max_downloads: int | None = None,
        description: str | None = None,
        is_active: bool = True,
        flush: bool = True,
        refresh: bool = False,
        check_node_exists: bool = False,
        check_duplicate_token: bool = True,
    ) -> PublicLink:
        """Создаёт новую публичную ссылку.

        Перед созданием нормализует token, password hash и описание, валидирует
        лимит скачиваний, при необходимости проверяет существование узла файловой
        системы и уникальность token.

        Args:
            node_id: Идентификатор узла файловой системы.
            token: Уникальный token публичной ссылки.
            created_by: Идентификатор пользователя, создавшего ссылку.
            password_hash: Хэш пароля для защищённой ссылки.
            permission_type: Тип разрешения публичной ссылки.
            status: Начальный статус ссылки.
            expires_at: Дата истечения срока действия ссылки.
            max_downloads: Максимальное количество скачиваний или ``None``
                без ограничения.
            description: Описание публичной ссылки.
            is_active: Признак активности ссылки.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_node_exists: Проверять ли существование узла.
            check_duplicate_token: Проверять ли уникальность token.

        Returns:
            Созданная публичная ссылка.

        Raises:
            InvalidQueryError: Если token, password hash, описание или лимит
                скачиваний некорректны.
            EntityNotFoundError: Если узел файловой системы не найден.
            DuplicateEntityError: Если публичная ссылка с таким token уже
                существует.
        """

        normalized_token = self._normalize_token(token)
        normalized_password_hash = self._normalize_optional_string(
            password_hash,
            field_name="password_hash",
            max_length=255,
        )
        normalized_description = self._normalize_description(description)

        self._validate_max_downloads(max_downloads=max_downloads)

        if check_node_exists:
            await self._ensure_node_exists(node_id)

        if check_duplicate_token and await self.token_exists(normalized_token):
            raise DuplicateEntityError(
                "PublicLink",
                field="token",
                value=normalized_token,
                repository=self.repository_name,
            )

        public_link = PublicLink(
            node_id=node_id,
            created_by=created_by,
            token=normalized_token,
            password_hash=normalized_password_hash,
            permission_type=permission_type,
            status=status,
            expires_at=expires_at,
            max_downloads=max_downloads,
            download_count=0,
            view_count=0,
            upload_count=0,
            is_active=is_active,
            revoked_at=None,
            revoked_by=None,
            revoke_reason=None,
            last_accessed_at=None,
            last_downloaded_at=None,
            last_uploaded_at=None,
            description=normalized_description,
        )

        return await self.create(
            public_link,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Списки ссылок
    # ------------------------------------------------------------------

    async def list_user_links(
        self,
        *,
        created_by: uuid.UUID,
        active_only: bool = False,
        available_only: bool = False,
        permission_type: PublicLinkPermissionType | None = None,
        status: PublicLinkStatus | None = None,
        moment: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
        sort_by: PublicLinkSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[PublicLink]:
        """Возвращает публичные ссылки, созданные пользователем.

        Args:
            created_by: Идентификатор пользователя, создавшего ссылки.
            active_only: Возвращать только активные ссылки.
            available_only: Возвращать только доступные ссылки.
            permission_type: Фильтр по типу разрешения.
            status: Фильтр по статусу ссылки.
            moment: Момент времени для проверки доступности.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список публичных ссылок пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(PublicLink)
            .where(PublicLink.created_by == created_by)
            .options(
                selectinload(PublicLink.node),
                selectinload(PublicLink.creator),
                selectinload(PublicLink.revoker),
            )
        )

        statement = self._apply_common_filters(
            statement,
            active_only=active_only,
            available_only=available_only,
            permission_type=permission_type,
            status=status,
            moment=moment,
        )

        statement = (
            statement.order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="list_user_links",
        )

    async def list_node_links(
        self,
        *,
        node_id: uuid.UUID,
        active_only: bool = False,
        available_only: bool = False,
        permission_type: PublicLinkPermissionType | None = None,
        status: PublicLinkStatus | None = None,
        moment: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
        sort_by: PublicLinkSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[PublicLink]:
        """Возвращает публичные ссылки, созданные для конкретного узла.

        Args:
            node_id: Идентификатор узла файловой системы.
            active_only: Возвращать только активные ссылки.
            available_only: Возвращать только доступные ссылки.
            permission_type: Фильтр по типу разрешения.
            status: Фильтр по статусу ссылки.
            moment: Момент времени для проверки доступности.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список публичных ссылок узла.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(PublicLink)
            .where(PublicLink.node_id == node_id)
            .options(
                selectinload(PublicLink.node),
                selectinload(PublicLink.creator),
                selectinload(PublicLink.revoker),
            )
        )

        statement = self._apply_common_filters(
            statement,
            active_only=active_only,
            available_only=available_only,
            permission_type=permission_type,
            status=status,
            moment=moment,
        )

        statement = (
            statement.order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="list_node_links",
        )

    async def list_active_node_links(
        self,
        *,
        node_id: uuid.UUID,
        permission_type: PublicLinkPermissionType | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PublicLink]:
        """Возвращает активные публичные ссылки конкретного узла.

        Args:
            node_id: Идентификатор узла файловой системы.
            permission_type: Фильтр по типу разрешения.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список активных публичных ссылок узла.
        """

        return await self.list_node_links(
            node_id=node_id,
            active_only=True,
            available_only=False,
            permission_type=permission_type,
            offset=offset,
            limit=limit,
        )

    async def list_available_node_links(
        self,
        *,
        node_id: uuid.UUID,
        permission_type: PublicLinkPermissionType | None = None,
        moment: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PublicLink]:
        """Возвращает доступные публичные ссылки конкретного узла.

        Доступность проверяется с учётом активности, отзыва, срока действия
        и лимита скачиваний.

        Args:
            node_id: Идентификатор узла файловой системы.
            permission_type: Фильтр по типу разрешения.
            moment: Момент времени для проверки доступности.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список доступных публичных ссылок узла.
        """

        return await self.list_node_links(
            node_id=node_id,
            available_only=True,
            permission_type=permission_type,
            moment=moment,
            offset=offset,
            limit=limit,
        )

    async def search_links(
        self,
        *,
        query: str | None = None,
        created_by: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        permission_type: PublicLinkPermissionType | None = None,
        status: PublicLinkStatus | None = None,
        active_only: bool = False,
        available_only: bool = False,
        moment: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
        sort_by: PublicLinkSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[PublicLink]:
        """Ищет публичные ссылки по набору фильтров.

        Поисковая строка применяется к token и описанию ссылки.

        Args:
            query: Поисковая строка.
            created_by: Фильтр по создателю ссылки.
            node_id: Фильтр по узлу файловой системы.
            permission_type: Фильтр по типу разрешения.
            status: Фильтр по статусу ссылки.
            active_only: Возвращать только активные ссылки.
            available_only: Возвращать только доступные ссылки.
            moment: Момент времени для проверки доступности.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список найденных публичных ссылок.

        Raises:
            InvalidQueryError: Если параметры пагинации или сортировки некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions: list[Any] = []

        if created_by is not None:
            conditions.append(PublicLink.created_by == created_by)

        if node_id is not None:
            conditions.append(PublicLink.node_id == node_id)

        if query is not None and query.strip():
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(
                    PublicLink.token.ilike(pattern),
                    PublicLink.description.ilike(pattern),
                )
            )

        statement = select(PublicLink).options(
            selectinload(PublicLink.node),
            selectinload(PublicLink.creator),
            selectinload(PublicLink.revoker),
        )

        if conditions:
            statement = statement.where(and_(*conditions))

        statement = self._apply_common_filters(
            statement,
            active_only=active_only,
            available_only=available_only,
            permission_type=permission_type,
            status=status,
            moment=moment,
        )

        statement = (
            statement.order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="search_links",
        )

    # ------------------------------------------------------------------
    # Обновление публичной ссылки
    # ------------------------------------------------------------------

    async def update_link(
        self,
        public_link: PublicLink,
        *,
        token: str | None = None,
        password_hash: str | None | object = _UNSET,
        permission_type: PublicLinkPermissionType | None = None,
        status: PublicLinkStatus | None = None,
        expires_at: datetime | None | object = _UNSET,
        max_downloads: int | None | object = _UNSET,
        description: str | None | object = _UNSET,
        is_active: bool | None = None,
        revoked_at: datetime | None | object = _UNSET,
        revoked_by: uuid.UUID | None | object = _UNSET,
        revoke_reason: str | None | object = _UNSET,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Обновляет публичную ссылку.

        Для nullable-полей используется sentinel ``_UNSET``: ``_UNSET``
        означает «не изменять поле», а ``None`` означает «очистить поле».

        Args:
            public_link: ORM-объект публичной ссылки.
            token: Новый token ссылки.
            password_hash: Новый хэш пароля, ``None`` для очистки или
                ``_UNSET`` без изменений.
            permission_type: Новый тип разрешения.
            status: Новый статус ссылки.
            expires_at: Новый срок действия, ``None`` для бессрочной ссылки
                или ``_UNSET`` без изменений.
            max_downloads: Новый лимит скачиваний, ``None`` без ограничения
                или ``_UNSET`` без изменений.
            description: Новое описание, ``None`` для очистки или ``_UNSET``
                без изменений.
            is_active: Новый признак активности.
            revoked_at: Дата отзыва, ``None`` для очистки или ``_UNSET``
                без изменений.
            revoked_by: Пользователь, отозвавший ссылку, ``None`` для очистки
                или ``_UNSET`` без изменений.
            revoke_reason: Причина отзыва, ``None`` для очистки или ``_UNSET``
                без изменений.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            InvalidQueryError: Если новые значения некорректны или
                ``max_downloads`` меньше текущего ``download_count``.
        """

        values: dict[str, Any] = {}

        if token is not None:
            values["token"] = self._normalize_token(token)

        if password_hash is not _UNSET:
            values["password_hash"] = self._normalize_optional_string(
                cast(str | None, password_hash),
                field_name="password_hash",
                max_length=255,
            )

        if permission_type is not None:
            values["permission_type"] = permission_type

        if status is not None:
            values["status"] = status

        if expires_at is not _UNSET:
            values["expires_at"] = expires_at

        if max_downloads is not _UNSET:
            self._validate_max_downloads(max_downloads=max_downloads)

            normalized_max_downloads = cast(int | None, max_downloads)

            if (
                normalized_max_downloads is not None
                and normalized_max_downloads < public_link.download_count
            ):
                raise InvalidQueryError(
                    "max_downloads не может быть меньше текущего download_count.",
                    repository=self.repository_name,
                    operation="update_link",
                    details={
                        "max_downloads": normalized_max_downloads,
                        "download_count": public_link.download_count,
                    },
                )

            values["max_downloads"] = normalized_max_downloads

        if description is not _UNSET:
            values["description"] = self._normalize_description(
                cast(str | None, description),
            )

        if is_active is not None:
            values["is_active"] = is_active

        if revoked_at is not _UNSET:
            values["revoked_at"] = revoked_at

        if revoked_by is not _UNSET:
            values["revoked_by"] = revoked_by

        if revoke_reason is not _UNSET:
            values["revoke_reason"] = self._normalize_revoke_reason(
                cast(str | None, revoke_reason),
            )

        if not values:
            return public_link

        return await self.update(
            public_link,
            values,
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "token",
                "password_hash",
                "permission_type",
                "status",
                "expires_at",
                "max_downloads",
                "description",
                "is_active",
                "revoked_at",
                "revoked_by",
                "revoke_reason",
            },
        )

    async def update_link_by_id(
        self,
        link_id: uuid.UUID,
        **kwargs: Any,
    ) -> PublicLink:
        """Обновляет публичную ссылку по идентификатору.

        Args:
            link_id: Идентификатор публичной ссылки.
            **kwargs: Параметры, передаваемые в ``update_link``.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            EntityNotFoundError: Если публичная ссылка не найдена.
            InvalidQueryError: Если параметры обновления некорректны.
        """

        public_link = await self.get_required_by_id(link_id)

        return await self.update_link(public_link, **kwargs)

    async def update_password_hash(
        self,
        *,
        link_id: uuid.UUID | None = None,
        token: str | None = None,
        password_hash: str | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Обновляет хэш пароля публичной ссылки.

        Нужно передать ровно один идентификатор: ``link_id`` или ``token``.

        Args:
            link_id: Идентификатор публичной ссылки.
            token: Token публичной ссылки.
            password_hash: Новый хэш пароля или ``None`` для удаления защиты паролем.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            InvalidQueryError: Если идентификаторы переданы некорректно
                или password hash превышает допустимую длину.
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self._get_required_by_link_id_or_token(
            link_id=link_id,
            token=token,
        )

        public_link.update_password_hash(
            self._normalize_optional_string(
                password_hash,
                field_name="password_hash",
                max_length=255,
            )
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(public_link)

        return public_link

    async def update_expiration(
        self,
        *,
        link_id: uuid.UUID | None = None,
        token: str | None = None,
        expires_at: datetime | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Обновляет срок действия публичной ссылки.

        Нужно передать ровно один идентификатор: ``link_id`` или ``token``.

        Args:
            link_id: Идентификатор публичной ссылки.
            token: Token публичной ссылки.
            expires_at: Новый срок действия или ``None`` для бессрочной ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            InvalidQueryError: Если идентификаторы переданы некорректно.
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self._get_required_by_link_id_or_token(
            link_id=link_id,
            token=token,
        )

        public_link.update_expiration(expires_at)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(public_link)

        return public_link

    async def update_download_limit(
        self,
        *,
        link_id: uuid.UUID | None = None,
        token: str | None = None,
        max_downloads: int | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Обновляет лимит скачиваний публичной ссылки.

        Нужно передать ровно один идентификатор: ``link_id`` или ``token``.

        Args:
            link_id: Идентификатор публичной ссылки.
            token: Token публичной ссылки.
            max_downloads: Новый лимит скачиваний или ``None`` без ограничения.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            InvalidQueryError: Если идентификаторы переданы некорректно,
                лимит отрицательный или меньше текущего количества скачиваний.
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self._get_required_by_link_id_or_token(
            link_id=link_id,
            token=token,
        )

        self._validate_max_downloads(max_downloads=max_downloads)

        try:
            public_link.update_download_limit(max_downloads)

        except ValueError as exc:
            raise InvalidQueryError(
                str(exc),
                repository=self.repository_name,
                operation="update_download_limit",
                details={
                    "link_id": str(public_link.id),
                    "download_count": public_link.download_count,
                    "max_downloads": max_downloads,
                },
                cause=exc,
            ) from exc

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(public_link)

        return public_link

    # ------------------------------------------------------------------
    # Активация, деактивация, отзыв, истечение
    # ------------------------------------------------------------------

    async def activate_link(
        self,
        public_link: PublicLink,
        *,
        clear_revoked_fields: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Активирует публичную ссылку.

        Если ссылка была отозвана, поля отзыва должны быть очищены через
        ``clear_revoked_fields=True``, иначе активация запрещена.

        Args:
            public_link: ORM-объект публичной ссылки.
            clear_revoked_fields: Очищать ли поля отзыва.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Активированная публичная ссылка.

        Raises:
            InvalidQueryError: Если выполняется попытка активировать отозванную ссылку
                без очистки полей отзыва.
        """

        if public_link.status == PublicLinkStatus.REVOKED and not clear_revoked_fields:
            raise InvalidQueryError(
                "Нельзя активировать отозванную публичную ссылку без очистки полей отзыва.",
                repository=self.repository_name,
                operation="activate_link",
                details={"link_id": str(public_link.id)},
            )

        values: dict[str, Any] = {
            "status": PublicLinkStatus.ACTIVE,
            "is_active": True,
        }

        if clear_revoked_fields:
            values["revoked_at"] = None
            values["revoked_by"] = None
            values["revoke_reason"] = None

        return await self.update(
            public_link,
            values,
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "status",
                "is_active",
                "revoked_at",
                "revoked_by",
                "revoke_reason",
            },
        )

    async def activate_link_by_id(
        self,
        link_id: uuid.UUID,
        *,
        clear_revoked_fields: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Активирует публичную ссылку по идентификатору.

        Args:
            link_id: Идентификатор публичной ссылки.
            clear_revoked_fields: Очищать ли поля отзыва.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Активированная публичная ссылка.

        Raises:
            EntityNotFoundError: Если публичная ссылка не найдена.
            InvalidQueryError: Если ссылка не может быть активирована.
        """

        public_link = await self.get_required_by_id(link_id)

        return await self.activate_link(
            public_link,
            clear_revoked_fields=clear_revoked_fields,
            flush=flush,
            refresh=refresh,
        )

    async def activate_link_by_token(
        self,
        token: str,
        *,
        clear_revoked_fields: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Активирует публичную ссылку по token.

        Args:
            token: Token публичной ссылки.
            clear_revoked_fields: Очищать ли поля отзыва.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Активированная публичная ссылка.

        Raises:
            InvalidQueryError: Если token некорректен или ссылка не может быть активирована.
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self.get_required_by_token(token)

        return await self.activate_link(
            public_link,
            clear_revoked_fields=clear_revoked_fields,
            flush=flush,
            refresh=refresh,
        )

    async def deactivate_link(
        self,
        public_link: PublicLink,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Деактивирует публичную ссылку без установки ``revoked_at``.

        Args:
            public_link: ORM-объект публичной ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Деактивированная публичная ссылка.
        """

        public_link.disable()

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(public_link)

        return public_link

    async def deactivate_link_by_id(
        self,
        link_id: uuid.UUID,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Деактивирует публичную ссылку по идентификатору.

        Args:
            link_id: Идентификатор публичной ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Деактивированная публичная ссылка.

        Raises:
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self.get_required_by_id(link_id)

        return await self.deactivate_link(
            public_link,
            flush=flush,
            refresh=refresh,
        )

    async def deactivate_link_by_token(
        self,
        token: str,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Деактивирует публичную ссылку по token.

        Args:
            token: Token публичной ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Деактивированная публичная ссылка.

        Raises:
            InvalidQueryError: Если token некорректен.
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self.get_required_by_token(token)

        return await self.deactivate_link(
            public_link,
            flush=flush,
            refresh=refresh,
        )

    async def revoke_link(
        self,
        public_link: PublicLink,
        *,
        revoked_by: uuid.UUID | None = None,
        reason: str | None = None,
        revoked_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Отзывает публичную ссылку.

        Отзыв устанавливает статус отозванной ссылки и сохраняет дату, автора
        и причину отзыва через доменный метод модели ``PublicLink``.

        Args:
            public_link: ORM-объект публичной ссылки.
            revoked_by: Идентификатор пользователя, отозвавшего ссылку.
            reason: Причина отзыва.
            revoked_at: Дата отзыва. Если не передана, используется текущее UTC-время.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Отозванная публичная ссылка.
        """

        public_link.revoke(
            revoked_by=revoked_by,
            reason=self._normalize_revoke_reason(reason),
            revoked_at=revoked_at or self._now(),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(public_link)

        return public_link

    async def revoke_link_by_id(
        self,
        link_id: uuid.UUID,
        *,
        revoked_by: uuid.UUID | None = None,
        reason: str | None = None,
        revoked_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Отзывает публичную ссылку по идентификатору.

        Args:
            link_id: Идентификатор публичной ссылки.
            revoked_by: Идентификатор пользователя, отозвавшего ссылку.
            reason: Причина отзыва.
            revoked_at: Дата отзыва.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Отозванная публичная ссылка.

        Raises:
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self.get_required_by_id(link_id)

        return await self.revoke_link(
            public_link,
            revoked_by=revoked_by,
            reason=reason,
            revoked_at=revoked_at,
            flush=flush,
            refresh=refresh,
        )

    async def revoke_link_by_token(
        self,
        token: str,
        *,
        revoked_by: uuid.UUID | None = None,
        reason: str | None = None,
        revoked_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Отзывает публичную ссылку по token.

        Args:
            token: Token публичной ссылки.
            revoked_by: Идентификатор пользователя, отозвавшего ссылку.
            reason: Причина отзыва.
            revoked_at: Дата отзыва.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Отозванная публичная ссылка.

        Raises:
            InvalidQueryError: Если token некорректен.
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self.get_required_by_token(token)

        return await self.revoke_link(
            public_link,
            revoked_by=revoked_by,
            reason=reason,
            revoked_at=revoked_at,
            flush=flush,
            refresh=refresh,
        )

    async def mark_link_expired(
        self,
        public_link: PublicLink,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Помечает публичную ссылку как истёкшую.

        Args:
            public_link: ORM-объект публичной ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка со статусом истечения.
        """

        public_link.mark_expired()

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(public_link)

        return public_link

    async def mark_link_expired_by_id(
        self,
        link_id: uuid.UUID,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Помечает публичную ссылку как истёкшую по идентификатору.

        Args:
            link_id: Идентификатор публичной ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self.get_required_by_id(link_id)

        return await self.mark_link_expired(
            public_link,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Регистрация использования ссылки
    # ------------------------------------------------------------------

    async def register_view(
        self,
        public_link: PublicLink,
        *,
        accessed_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Регистрирует просмотр публичной ссылки.

        Обновляет дату последнего доступа и счётчик просмотров через доменный
        метод модели ``PublicLink``.

        Args:
            public_link: ORM-объект публичной ссылки.
            accessed_at: Дата доступа. Если не передана, используется текущее UTC-время.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.
        """

        public_link.mark_accessed(accessed_at=accessed_at or self._now())

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(public_link)

        return public_link

    async def register_view_by_token(
        self,
        token: str,
        *,
        accessed_at: datetime | None = None,
        require_available: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Регистрирует просмотр публичной ссылки по token.

        При ``require_available=True`` просмотр регистрируется только для доступной ссылки.

        Args:
            token: Token публичной ссылки.
            accessed_at: Дата доступа. Если не передана, используется текущее UTC-время.
            require_available: Требовать ли доступность ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            InvalidQueryError: Если token некорректен.
            EntityNotFoundError: Если ссылка не найдена или недоступна.
        """

        public_link = (
            await self.get_required_available_link_by_token(token)
            if require_available
            else await self.get_required_by_token(token)
        )

        return await self.register_view(
            public_link,
            accessed_at=accessed_at,
            flush=flush,
            refresh=refresh,
        )

    async def register_download(
        self,
        public_link: PublicLink,
        *,
        downloaded_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Регистрирует скачивание по публичной ссылке.

        Обновляет счётчик скачиваний, дату последнего скачивания и дату последнего
        доступа. Если лимит скачиваний достигнут, ссылка деактивируется.

        Args:
            public_link: ORM-объект публичной ссылки.
            downloaded_at: Дата скачивания. Если не передана, используется текущее UTC-время.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            InvalidQueryError: Если доменная модель запрещает скачивание
                из-за состояния ссылки или лимита скачиваний.
        """

        try:
            public_link.register_download(downloaded_at=downloaded_at or self._now())

        except ValueError as exc:
            raise InvalidQueryError(
                str(exc),
                repository=self.repository_name,
                operation="register_download",
                details={
                    "link_id": str(public_link.id),
                    "download_count": public_link.download_count,
                    "max_downloads": public_link.max_downloads,
                },
                cause=exc,
            ) from exc

        if public_link.is_download_limit_reached:
            public_link.is_active = False

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(public_link)

        return public_link

    async def increment_download_count(
        self,
        public_link: PublicLink,
        *,
        amount: int = 1,
        deactivate_when_limit_reached: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Увеличивает счётчик скачиваний публичной ссылки.

        Для пользовательского скачивания предпочтительнее использовать
        ``register_download()``, так как он также обновляет ``last_downloaded_at``
        и ``last_accessed_at``.

        Args:
            public_link: ORM-объект публичной ссылки.
            amount: Величина увеличения счётчика.
            deactivate_when_limit_reached: Деактивировать ли ссылку при достижении лимита.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            InvalidQueryError: Если ``amount`` не является положительным целым числом.
        """

        self._validate_download_increment(amount)

        next_download_count = public_link.download_count + amount

        values: dict[str, Any] = {
            "download_count": next_download_count,
            "last_downloaded_at": self._now(),
            "last_accessed_at": self._now(),
        }

        if (
            deactivate_when_limit_reached
            and public_link.max_downloads is not None
            and next_download_count >= public_link.max_downloads
        ):
            values["is_active"] = False

        return await self.update(
            public_link,
            values,
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "download_count",
                "last_downloaded_at",
                "last_accessed_at",
                "is_active",
            },
        )

    async def increment_download_count_by_id(
        self,
        link_id: uuid.UUID,
        *,
        amount: int = 1,
        deactivate_when_limit_reached: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Увеличивает счётчик скачиваний публичной ссылки по идентификатору.

        Args:
            link_id: Идентификатор публичной ссылки.
            amount: Величина увеличения счётчика.
            deactivate_when_limit_reached: Деактивировать ли ссылку при достижении лимита.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            EntityNotFoundError: Если публичная ссылка не найдена.
            InvalidQueryError: Если ``amount`` некорректен.
        """

        public_link = await self.get_required_by_id(link_id)

        return await self.increment_download_count(
            public_link,
            amount=amount,
            deactivate_when_limit_reached=deactivate_when_limit_reached,
            flush=flush,
            refresh=refresh,
        )

    async def increment_download_count_by_token(
        self,
        token: str,
        *,
        amount: int = 1,
        deactivate_when_limit_reached: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Увеличивает счётчик скачиваний публичной ссылки по token.

        Args:
            token: Token публичной ссылки.
            amount: Величина увеличения счётчика.
            deactivate_when_limit_reached: Деактивировать ли ссылку при достижении лимита.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            InvalidQueryError: Если token или ``amount`` некорректны.
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        public_link = await self.get_required_by_token(token)

        return await self.increment_download_count(
            public_link,
            amount=amount,
            deactivate_when_limit_reached=deactivate_when_limit_reached,
            flush=flush,
            refresh=refresh,
        )

    async def register_upload(
        self,
        public_link: PublicLink,
        *,
        uploaded_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Регистрирует загрузку через публичную ссылку.

        Обновляет счётчик загрузок, дату последней загрузки и дату последнего доступа
        через доменный метод модели ``PublicLink``.

        Args:
            public_link: ORM-объект публичной ссылки.
            uploaded_at: Дата загрузки. Если не передана, используется текущее UTC-время.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.
        """

        public_link.register_upload(uploaded_at=uploaded_at or self._now())

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(public_link)

        return public_link

    async def register_upload_by_token(
        self,
        token: str,
        *,
        uploaded_at: datetime | None = None,
        require_available: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Регистрирует загрузку через публичную ссылку по token.

        При ``require_available=True`` загрузка регистрируется только для доступной ссылки.

        Args:
            token: Token публичной ссылки.
            uploaded_at: Дата загрузки. Если не передана, используется текущее UTC-время.
            require_available: Требовать ли доступность ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённая публичная ссылка.

        Raises:
            InvalidQueryError: Если token некорректен.
            EntityNotFoundError: Если ссылка не найдена или недоступна.
        """

        public_link = (
            await self.get_required_available_link_by_token(token)
            if require_available
            else await self.get_required_by_token(token)
        )

        return await self.register_upload(
            public_link,
            uploaded_at=uploaded_at,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Истёкшие ссылки и ссылки с достигнутым лимитом
    # ------------------------------------------------------------------

    async def find_expired_links(
        self,
        *,
        moment: datetime | None = None,
        active_only: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PublicLink]:
        """Возвращает публичные ссылки с истёкшим сроком действия.

        Args:
            moment: Момент времени для проверки истечения срока действия.
            active_only: Возвращать только активные и неотозванные ссылки.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список публичных ссылок с истёкшим сроком действия.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        effective_moment = self._normalize_moment(moment)

        statement = (
            select(PublicLink)
            .where(
                PublicLink.expires_at.is_not(None),
                PublicLink.expires_at <= effective_moment,
            )
            .options(
                selectinload(PublicLink.node),
                selectinload(PublicLink.creator),
            )
        )

        if active_only:
            statement = statement.where(*self._active_conditions())

        statement = (
            statement.order_by(PublicLink.expires_at.asc()).offset(offset).limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="find_expired_links",
        )

    async def mark_expired_links_inactive(
        self,
        *,
        moment: datetime | None = None,
        set_status_expired: bool = True,
        flush: bool = True,
    ) -> int:
        """Массово деактивирует публичные ссылки с истёкшим сроком действия.

        При ``set_status_expired=True`` дополнительно устанавливает статус ``EXPIRED``.

        Args:
            moment: Момент времени для проверки истечения срока действия.
            set_status_expired: Устанавливать ли статус ``EXPIRED``.
            flush: Выполнить ли ``flush`` после массового обновления.

        Returns:
            Количество обновлённых ссылок.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        effective_moment = self._normalize_moment(moment)

        values: dict[str, Any] = {"is_active": False}

        if set_status_expired:
            values["status"] = PublicLinkStatus.EXPIRED

        return await self._bulk_update(
            conditions=[
                PublicLink.is_active.is_(True),
                PublicLink.revoked_at.is_(None),
                PublicLink.expires_at.is_not(None),
                PublicLink.expires_at <= effective_moment,
            ],
            values=values,
            operation="mark_expired_links_inactive",
            flush=flush,
        )

    async def find_download_limit_reached_links(
        self,
        *,
        active_only: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PublicLink]:
        """Возвращает ссылки, у которых достигнут лимит скачиваний.

        Args:
            active_only: Возвращать только активные и неотозванные ссылки.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список публичных ссылок с достигнутым лимитом скачиваний.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(PublicLink)
            .where(
                PublicLink.max_downloads.is_not(None),
                PublicLink.download_count >= PublicLink.max_downloads,
            )
            .options(
                selectinload(PublicLink.node),
                selectinload(PublicLink.creator),
            )
        )

        if active_only:
            statement = statement.where(*self._active_conditions())

        statement = (
            statement.order_by(PublicLink.created_at.asc()).offset(offset).limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="find_download_limit_reached_links",
        )

    async def mark_download_limit_reached_links_inactive(
        self,
        *,
        flush: bool = True,
    ) -> int:
        """Массово деактивирует публичные ссылки, достигшие лимита скачиваний.

        Args:
            flush: Выполнить ли ``flush`` после массового обновления.

        Returns:
            Количество обновлённых ссылок.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        return await self._bulk_update(
            conditions=[
                PublicLink.is_active.is_(True),
                PublicLink.revoked_at.is_(None),
                PublicLink.max_downloads.is_not(None),
                PublicLink.download_count >= PublicLink.max_downloads,
            ],
            values={"is_active": False},
            operation="mark_download_limit_reached_links_inactive",
            flush=flush,
        )

    # ------------------------------------------------------------------
    # Проверки
    # ------------------------------------------------------------------

    async def link_is_available(
        self,
        public_link: PublicLink,
        *,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет доступность ORM-объекта публичной ссылки.

        Args:
            public_link: ORM-объект публичной ссылки.
            moment: Момент времени для проверки доступности.

        Returns:
            ``True``, если ссылка доступна на указанный момент, иначе ``False``.
        """

        effective_moment = self._normalize_moment(moment)

        return public_link.is_available_at(effective_moment)

    async def token_is_available(
        self,
        token: str,
        *,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет, существует ли доступная ссылка с указанным token.

        Args:
            token: Token публичной ссылки.
            moment: Момент времени для проверки доступности.

        Returns:
            ``True``, если доступная ссылка существует, иначе ``False``.

        Raises:
            InvalidQueryError: Если token некорректен.
        """

        public_link = await self.get_available_link_by_token(
            token,
            moment=moment,
        )

        return public_link is not None

    async def can_view_by_token(
        self,
        token: str,
        *,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет, разрешён ли просмотр по token.

        Args:
            token: Token публичной ссылки.
            moment: Момент времени для проверки доступности.

        Returns:
            ``True``, если просмотр разрешён, иначе ``False``.
        """

        public_link = await self.get_by_token(token)

        if public_link is None:
            return False

        return public_link.can_view_at(self._normalize_moment(moment))

    async def can_download_by_token(
        self,
        token: str,
        *,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет, разрешено ли скачивание по token.

        Args:
            token: Token публичной ссылки.
            moment: Момент времени для проверки доступности.

        Returns:
            ``True``, если скачивание разрешено, иначе ``False``.
        """

        public_link = await self.get_by_token(token)

        if public_link is None:
            return False

        return public_link.can_download_at(self._normalize_moment(moment))

    async def can_upload_by_token(
        self,
        token: str,
        *,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет, разрешена ли загрузка по token.

        Args:
            token: Token публичной ссылки.
            moment: Момент времени для проверки доступности.

        Returns:
            ``True``, если загрузка разрешена, иначе ``False``.
        """

        public_link = await self.get_by_token(token)

        if public_link is None:
            return False

        return public_link.can_upload_at(self._normalize_moment(moment))

    # ------------------------------------------------------------------
    # Подсчёты
    # ------------------------------------------------------------------

    async def count_user_links(
        self,
        *,
        created_by: uuid.UUID,
        active_only: bool = False,
        available_only: bool = False,
        status: PublicLinkStatus | None = None,
        moment: datetime | None = None,
    ) -> int:
        """Возвращает количество публичных ссылок, созданных пользователем.

        Args:
            created_by: Идентификатор пользователя, создавшего ссылки.
            active_only: Учитывать только активные ссылки.
            available_only: Учитывать только доступные ссылки.
            status: Фильтр по статусу ссылки.
            moment: Момент времени для проверки доступности.

        Returns:
            Количество публичных ссылок пользователя.
        """

        conditions: list[Any] = [PublicLink.created_by == created_by]

        if status is not None:
            conditions.append(PublicLink.status == status)

        if available_only:
            conditions.extend(
                self._available_conditions(self._normalize_moment(moment))
            )
        elif active_only:
            conditions.extend(self._active_conditions())

        return await self.count(*conditions)

    async def count_node_links(
        self,
        *,
        node_id: uuid.UUID,
        active_only: bool = False,
        available_only: bool = False,
        status: PublicLinkStatus | None = None,
        moment: datetime | None = None,
    ) -> int:
        """Возвращает количество публичных ссылок для узла.

        Args:
            node_id: Идентификатор узла файловой системы.
            active_only: Учитывать только активные ссылки.
            available_only: Учитывать только доступные ссылки.
            status: Фильтр по статусу ссылки.
            moment: Момент времени для проверки доступности.

        Returns:
            Количество публичных ссылок для узла.
        """

        conditions: list[Any] = [PublicLink.node_id == node_id]

        if status is not None:
            conditions.append(PublicLink.status == status)

        if available_only:
            conditions.extend(
                self._available_conditions(self._normalize_moment(moment))
            )
        elif active_only:
            conditions.extend(self._active_conditions())

        return await self.count(*conditions)

    async def count_active_links(self) -> int:
        """Возвращает количество активных публичных ссылок.

        Returns:
            Количество ссылок со статусом ``ACTIVE``, ``is_active=True``
            и без признака отзыва.
        """

        return await self.count(*self._active_conditions())

    # ------------------------------------------------------------------
    # Физическое удаление
    # ------------------------------------------------------------------

    async def delete_link_by_token(
        self,
        token: str,
        *,
        flush: bool = True,
        required: bool = True,
    ) -> bool:
        """Физически удаляет публичную ссылку по token.

        Для пользовательского удаления обычно следует использовать ``revoke_link()``.

        Args:
            token: Token публичной ссылки.
            flush: Выполнить ли ``flush`` после удаления.
            required: Выбрасывать ли ошибку, если ссылка не найдена.

        Returns:
            ``True``, если ссылка была удалена, иначе ``False``.

        Raises:
            InvalidQueryError: Если token некорректен.
            EntityNotFoundError: Если ссылка не найдена и ``required=True``.
        """

        public_link = await self.get_by_token(token)

        if public_link is None:
            if required:
                raise EntityNotFoundError(
                    "PublicLink",
                    lookup={"token": token},
                    repository=self.repository_name,
                )

            return False

        await self.delete(public_link, flush=flush)

        return True

    async def delete_links_by_node(
        self,
        node_id: uuid.UUID,
        *,
        flush: bool = True,
    ) -> int:
        """Физически удаляет все публичные ссылки узла.

        Args:
            node_id: Идентификатор узла файловой системы.
            flush: Выполнить ли ``flush`` после удаления.

        Returns:
            Количество удалённых публичных ссылок.
        """

        return await self.bulk_delete(
            PublicLink.node_id == node_id,
            flush=flush,
        )

    # ------------------------------------------------------------------
    # Внутренние SQL-условия и фильтры
    # ------------------------------------------------------------------

    def _active_conditions(self) -> list[Any]:
        """Возвращает SQLAlchemy-условия активности публичной ссылки.

        Условия активности не проверяют срок действия и лимит скачиваний.

        Returns:
            Список условий для активной, включённой и неотозванной ссылки.
        """

        return [
            PublicLink.status == PublicLinkStatus.ACTIVE,
            PublicLink.is_active.is_(True),
            PublicLink.revoked_at.is_(None),
        ]

    def _available_conditions(
        self,
        moment: datetime,
    ) -> list[Any]:
        """Возвращает SQLAlchemy-условия доступности публичной ссылки.

        Доступность включает активность, отсутствие отзыва, актуальный срок действия
        и недостигнутый лимит скачиваний.

        Args:
            moment: Момент времени для проверки срока действия.

        Returns:
            Список SQLAlchemy-условий доступности.
        """

        return [
            *self._active_conditions(),
            or_(
                PublicLink.expires_at.is_(None),
                PublicLink.expires_at > moment,
            ),
            or_(
                PublicLink.max_downloads.is_(None),
                PublicLink.download_count < PublicLink.max_downloads,
            ),
        ]

    def _apply_common_filters(
        self,
        statement: Select[tuple[PublicLink]],
        *,
        active_only: bool,
        available_only: bool,
        permission_type: PublicLinkPermissionType | None,
        status: PublicLinkStatus | None,
        moment: datetime | None,
    ) -> Select[tuple[PublicLink]]:
        """Применяет общие фильтры к SELECT-запросу публичных ссылок.

        Args:
            statement: Исходный SQLAlchemy SELECT-запрос.
            active_only: Добавить фильтр активных ссылок.
            available_only: Добавить фильтр доступных ссылок.
            permission_type: Фильтр по типу разрешения.
            status: Фильтр по статусу ссылки.
            moment: Момент времени для проверки доступности.

        Returns:
            SELECT-запрос с применёнными фильтрами.
        """

        if available_only:
            statement = statement.where(
                *self._available_conditions(self._normalize_moment(moment)),
            )
        elif active_only:
            statement = statement.where(*self._active_conditions())

        if permission_type is not None:
            statement = statement.where(PublicLink.permission_type == permission_type)

        if status is not None:
            statement = statement.where(PublicLink.status == status)

        return statement

    def _get_order_by(
        self,
        sort_by: PublicLinkSortField,
        sort_direction: SortDirection,
    ) -> Any:
        """Возвращает SQLAlchemy-выражение сортировки публичных ссылок.

        Args:
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки: `asc` или `desc`.

        Returns:
            SQLAlchemy-выражение для `order_by`.

        Raises:
            InvalidQueryError: Если поле или направление сортировки недопустимы.
        """

        allowed_fields: dict[str, Any] = {
            "created_at": PublicLink.created_at,
            "expires_at": PublicLink.expires_at,
            "last_accessed_at": PublicLink.last_accessed_at,
            "last_downloaded_at": PublicLink.last_downloaded_at,
            "last_uploaded_at": PublicLink.last_uploaded_at,
            "download_count": PublicLink.download_count,
            "view_count": PublicLink.view_count,
            "upload_count": PublicLink.upload_count,
            "status": PublicLink.status,
        }

        if sort_by not in allowed_fields:
            raise InvalidQueryError(
                "Недопустимое поле сортировки публичных ссылок.",
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

    # ------------------------------------------------------------------
    # Валидация и нормализация
    # ------------------------------------------------------------------

    def _normalize_token(
        self,
        token: str,
    ) -> str:
        """Нормализует token публичной ссылки.

        Удаляет пробелы по краям строки и проверяет, что token не пустой
        и не превышает допустимую длину.

        Args:
            token: Token публичной ссылки.

        Returns:
            Нормализованный token.

        Raises:
            InvalidQueryError: Если token пустой или длиннее 128 символов.
        """

        normalized_token = token.strip()

        if not normalized_token:
            raise InvalidQueryError(
                "Token публичной ссылки не может быть пустым.",
                repository=self.repository_name,
                operation="_normalize_token",
                details={"model": self.model_name},
            )

        if len(normalized_token) > 128:
            raise InvalidQueryError(
                "Token публичной ссылки не должен превышать 128 символов.",
                repository=self.repository_name,
                operation="_normalize_token",
                details={
                    "model": self.model_name,
                    "token_length": len(normalized_token),
                    "max_length": 128,
                },
            )

        return normalized_token

    def _normalize_optional_string(
        self,
        value: str | None,
        *,
        field_name: str,
        max_length: int,
    ) -> str | None:
        """Нормализует необязательную строку.

        Удаляет пробелы по краям строки. Пустая строка возвращается как ``None``.

        Args:
            value: Исходное строковое значение.
            field_name: Название поля для сообщения об ошибке.
            max_length: Максимальная допустимая длина строки.

        Returns:
            Нормализованная строка или ``None``.

        Raises:
            InvalidQueryError: Если строка превышает допустимую длину.
        """

        if value is None:
            return None

        normalized = value.strip()

        if not normalized:
            return None

        if len(normalized) > max_length:
            raise InvalidQueryError(
                f"Поле {field_name} не должно превышать {max_length} символов.",
                repository=self.repository_name,
                operation="_normalize_optional_string",
                details={
                    "field": field_name,
                    "length": len(normalized),
                    "max_length": max_length,
                },
            )

        return normalized

    def _normalize_description(
        self,
        description: str | None,
    ) -> str | None:
        """Нормализует описание публичной ссылки.

        Args:
            description: Описание публичной ссылки.

        Returns:
            Нормализованное описание или ``None``.
        """

        if description is None:
            return None

        normalized = description.strip()

        return normalized or None

    def _normalize_revoke_reason(
        self,
        reason: str | None,
    ) -> str | None:
        """Нормализует причину отзыва публичной ссылки.

        Args:
            reason: Причина отзыва.

        Returns:
            Нормализованная причина отзыва или ``None``.

        Raises:
            InvalidQueryError: Если причина отзыва превышает допустимую длину.
        """

        return self._normalize_optional_string(
            reason,
            field_name="revoke_reason",
            max_length=512,
        )

    def _validate_max_downloads(
        self,
        *,
        max_downloads: int | None | object,
    ) -> None:
        """Проверяет значение лимита скачиваний.

        Значение может быть положительным целым числом, нулём или ``None``.
        ``None`` означает отсутствие лимита.

        Args:
            max_downloads: Проверяемый лимит скачиваний.

        Raises:
            InvalidQueryError: Если значение не является ``int``, ``None`` или ``_UNSET``,
                либо если значение отрицательное.
        """

        if max_downloads is _UNSET or max_downloads is None:
            return

        if not isinstance(max_downloads, int):
            raise InvalidQueryError(
                "max_downloads должен быть целым числом или None.",
                repository=self.repository_name,
                operation="_validate_max_downloads",
                details={
                    "model": self.model_name,
                    "max_downloads": max_downloads,
                    "value_type": type(max_downloads).__name__,
                },
            )

        if max_downloads < 0:
            raise InvalidQueryError(
                "max_downloads не может быть отрицательным.",
                repository=self.repository_name,
                operation="_validate_max_downloads",
                details={
                    "model": self.model_name,
                    "max_downloads": max_downloads,
                },
            )

    def _validate_download_increment(
        self,
        amount: int,
    ) -> None:
        """Проверяет величину увеличения счётчика скачиваний.

        Args:
            amount: Величина увеличения счётчика.

        Raises:
            InvalidQueryError: Если значение не является положительным целым числом.
        """

        if not isinstance(amount, int):
            raise InvalidQueryError(
                "Величина увеличения download_count должна быть целым числом.",
                repository=self.repository_name,
                operation="_validate_download_increment",
                details={
                    "amount": amount,
                    "value_type": type(amount).__name__,
                },
            )

        if amount <= 0:
            raise InvalidQueryError(
                "Счётчик скачиваний можно увеличить только на положительное значение.",
                repository=self.repository_name,
                operation="_validate_download_increment",
                details={"amount": amount},
            )

    def _normalize_moment(
        self,
        moment: datetime | None,
    ) -> datetime:
        """Возвращает дату и время для проверки срока действия ссылки.

        Если момент не передан, используется текущее UTC-время.
        Если передан naive datetime, он считается UTC.

        Args:
            moment: Момент времени для нормализации.

        Returns:
            Дата и время с информацией о часовом поясе.
        """

        if moment is None:
            return self._now()

        if moment.tzinfo is None:
            return moment.replace(tzinfo=UTC)

        return moment

    @staticmethod
    def _now() -> datetime:
        """Возвращает текущее время в UTC.

        Returns:
            Текущая дата и время с timezone UTC.
        """

        return datetime.now(UTC)

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    async def _get_required_by_link_id_or_token(
        self,
        *,
        link_id: uuid.UUID | None,
        token: str | None,
    ) -> PublicLink:
        """Возвращает публичную ссылку по ``link_id`` или ``token``.

        Нужно передать ровно один идентификатор.

        Args:
            link_id: Идентификатор публичной ссылки.
            token: Token публичной ссылки.

        Returns:
            Найденная публичная ссылка.

        Raises:
            InvalidQueryError: Если не передан ни один идентификатор
                или переданы оба идентификатора.
            EntityNotFoundError: Если публичная ссылка не найдена.
        """

        if link_id is None and token is None:
            raise InvalidQueryError(
                "Необходимо передать link_id или token.",
                repository=self.repository_name,
                operation="_get_required_by_link_id_or_token",
            )

        if link_id is not None and token is not None:
            raise InvalidQueryError(
                "Нужно передать только один идентификатор: link_id или token.",
                repository=self.repository_name,
                operation="_get_required_by_link_id_or_token",
                details={
                    "link_id": str(link_id),
                    "token": token,
                },
            )

        if link_id is not None:
            return await self.get_required_by_id(link_id)

        assert token is not None

        return await self.get_required_by_token(token)

    async def _ensure_node_exists(
        self,
        node_id: uuid.UUID,
    ) -> FileSystemNode:
        """Проверяет существование узла файловой системы.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            Найденный узел файловой системы.

        Raises:
            EntityNotFoundError: Если узел файловой системы не найден.
            RepositoryError: Если произошла ошибка при обращении к базе данных.
        """

        try:
            node = await self.session.get(FileSystemNode, node_id)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="_ensure_node_exists",
                reason=str(exc),
                details={"node_id": str(node_id)},
                cause=exc,
            ) from exc

        if node is None:
            raise EntityNotFoundError(
                "FileSystemNode",
                entity_id=node_id,
                repository=self.repository_name,
            )

        return node

    async def _bulk_update(
        self,
        *,
        conditions: list[Any],
        values: dict[str, Any],
        operation: str,
        flush: bool,
    ) -> int:
        """Выполняет массовое обновление публичных ссылок.

        Args:
            conditions: SQLAlchemy-условия для выбора ссылок.
            values: Значения для обновления.
            operation: Название операции для сообщений об ошибках.
            flush: Выполнить ``flush`` после массового обновления.

        Returns:
            Количество обновлённых ссылок.

        Raises:
            RepositoryError: Если произошла ошибка при массовом обновлении.
        """

        try:
            statement = update(PublicLink).where(*conditions).values(**values)

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

    # ------------------------------------------------------------------
    # Переопределённые методы
    # ------------------------------------------------------------------

    async def create(
        self,
        entity: PublicLink,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> PublicLink:
        """Добавляет публичную ссылку в текущую сессию.

        Переопределяет базовый метод для более понятной ошибки при конфликте
        уникальности по token.

        Args:
            entity: ORM-объект публичной ссылки.
            flush: Выполнить ``flush`` после добавления.
            refresh: Выполнить ``refresh`` после добавления.

        Returns:
            Созданная публичная ссылка.

        Raises:
            DuplicateEntityError: Если публичная ссылка с таким token уже
                существует.
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
                "PublicLink",
                field="token",
                value=entity.token,
                repository=self.repository_name,
                message="Публичная ссылка с таким token уже существует.",
            ) from exc

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_link",
            ) from exc
