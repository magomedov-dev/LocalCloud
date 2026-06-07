from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database.exceptions import (
    ConstraintViolationError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import PublicLinkStatus, UploadSessionStatus
from database.models.filesystem import File, FileSystemNode
from database.models.links import PublicLink
from database.models.quotas import UserQuota
from database.models.uploads import UploadSession
from database.models.users import User
from database.repositories.base import BaseRepository

_UNSET: Final = object()


class UserQuotaRepository(BaseRepository[UserQuota]):
    """Репозиторий для работы с пользовательскими квотами.

    Инкапсулирует операции создания, получения, обновления лимитов,
    изменения счётчиков, проверки ограничений, пересчёта фактического
    использования ресурсов и поиска квот, близких к лимиту.

    Работает с моделью ``UserQuota`` через асинхронную SQLAlchemy-сессию.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий пользовательских квот.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=UserQuota)

    # ------------------------------------------------------------------
    # Получение квот
    # ------------------------------------------------------------------

    async def get_by_user_id(
        self,
        user_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> UserQuota | None:
        """Возвращает квоту пользователя по идентификатору пользователя.

        При необходимости может заблокировать строку квоты через
        ``SELECT FOR UPDATE``, что полезно при изменении счётчиков и
        предотвращении гонок.

        Args:
            user_id: Идентификатор пользователя.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Квота пользователя, если она найдена, иначе ``None``.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            statement = select(UserQuota).where(UserQuota.user_id == user_id)

            if for_update:
                statement = statement.with_for_update()

            result = await self.session.execute(statement)

            return result.scalar_one_or_none()

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_by_user_id",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "for_update": for_update,
                },
                cause=exc,
            ) from exc

    async def get_required_by_user_id(
        self,
        user_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> UserQuota:
        """Возвращает квоту пользователя по идентификатору пользователя.

        Args:
            user_id: Идентификатор пользователя.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Найденная квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
        """

        quota = await self.get_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        if quota is None:
            raise EntityNotFoundError(
                "UserQuota",
                lookup={"user_id": str(user_id)},
                repository=self.repository_name,
            )

        return quota

    async def quota_exists_for_user(
        self,
        user_id: uuid.UUID,
    ) -> bool:
        """Проверяет существование квоты для пользователя.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            ``True``, если квота для пользователя существует, иначе ``False``.
        """

        return await self.exists(UserQuota.user_id == user_id)

    # ------------------------------------------------------------------
    # Создание квоты
    # ------------------------------------------------------------------

    async def create_quota(
        self,
        *,
        user_id: uuid.UUID,
        storage_limit_bytes: int,
        max_file_size_bytes: int,
        storage_used_bytes: int = 0,
        files_limit: int | None = None,
        files_used: int = 0,
        public_links_limit: int | None = 100,
        public_links_used: int = 0,
        active_upload_sessions_limit: int | None = 10,
        active_upload_sessions_used: int = 0,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
        check_duplicate: bool = True,
    ) -> UserQuota:
        """Создаёт квоту пользователя.

        Перед созданием валидирует лимиты и текущие значения счётчиков.
        При необходимости проверяет существование пользователя и отсутствие
        уже созданной квоты для этого пользователя.

        Args:
            user_id: Идентификатор пользователя.
            storage_limit_bytes: Максимальный объём хранилища в байтах.
            max_file_size_bytes: Максимальный размер одного файла в байтах.
            storage_used_bytes: Уже использованный объём хранилища в байтах.
            files_limit: Максимальное количество файлов или ``None`` без
                ограничения.
            files_used: Текущее количество файлов.
            public_links_limit: Максимальное количество публичных ссылок или
                ``None`` без ограничения.
            public_links_used: Текущее количество публичных ссылок.
            active_upload_sessions_limit: Максимальное количество активных
                upload-сессий или ``None`` без ограничения.
            active_upload_sessions_used: Текущее количество активных
                upload-сессий.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_user_exists: Проверять ли существование пользователя.
            check_duplicate: Проверять ли наличие уже существующей квоты.

        Returns:
            Созданная квота пользователя.

        Raises:
            InvalidQueryError: Если значения лимитов или счётчиков некорректны.
            ConstraintViolationError: Если текущие значения превышают заданные
                лимиты.
            DuplicateEntityError: Если квота для пользователя уже существует.
            EntityNotFoundError: Если пользователь не найден.
        """

        self._validate_quota_values(
            storage_limit_bytes=storage_limit_bytes,
            storage_used_bytes=storage_used_bytes,
            max_file_size_bytes=max_file_size_bytes,
            files_limit=files_limit,
            files_used=files_used,
            public_links_limit=public_links_limit,
            public_links_used=public_links_used,
            active_upload_sessions_limit=active_upload_sessions_limit,
            active_upload_sessions_used=active_upload_sessions_used,
        )

        if check_user_exists:
            await self._ensure_user_exists(user_id)

        if check_duplicate and await self.quota_exists_for_user(user_id):
            raise DuplicateEntityError(
                "UserQuota",
                field="user_id",
                value=user_id,
                repository=self.repository_name,
            )

        quota = UserQuota(
            user_id=user_id,
            storage_limit_bytes=storage_limit_bytes,
            storage_used_bytes=storage_used_bytes,
            max_file_size_bytes=max_file_size_bytes,
            files_limit=files_limit,
            files_used=files_used,
            public_links_limit=public_links_limit,
            public_links_used=public_links_used,
            active_upload_sessions_limit=active_upload_sessions_limit,
            active_upload_sessions_used=active_upload_sessions_used,
        )

        try:
            return await self.create(
                quota,
                flush=flush,
                refresh=refresh,
            )

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_quota",
            ) from exc

    async def create_default_quota(
        self,
        *,
        user_id: uuid.UUID,
        storage_limit_bytes: int = 10 * 1024 * 1024 * 1024,
        max_file_size_bytes: int = 1024 * 1024 * 1024,
        files_limit: int | None = None,
        public_links_limit: int | None = 100,
        active_upload_sessions_limit: int | None = 10,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
        check_duplicate: bool = True,
    ) -> UserQuota:
        """Создаёт квоту пользователя со стандартными значениями.

        По умолчанию задаёт лимит хранилища 10 ГБ, максимальный размер файла 1 ГБ,
        лимит публичных ссылок 100 и лимит активных upload-сессий 10.

        Args:
            user_id: Идентификатор пользователя.
            storage_limit_bytes: Максимальный объём хранилища в байтах.
            max_file_size_bytes: Максимальный размер одного файла в байтах.
            files_limit: Максимальное количество файлов или ``None`` без ограничения.
            public_links_limit: Максимальное количество публичных ссылок или ``None``.
            active_upload_sessions_limit: Максимальное количество активных upload-сессий или ``None``.
            flush: Выполнить ли ``flush`` после создания.
            refresh: Выполнить ли ``refresh`` после создания.
            check_user_exists: Проверять ли существование пользователя.
            check_duplicate: Проверять ли наличие уже существующей квоты.

        Returns:
            Созданная квота пользователя.

        Raises:
            InvalidQueryError: Если значения лимитов некорректны.
            DuplicateEntityError: Если квота для пользователя уже существует.
            EntityNotFoundError: Если пользователь не найден.
        """

        return await self.create_quota(
            user_id=user_id,
            storage_limit_bytes=storage_limit_bytes,
            max_file_size_bytes=max_file_size_bytes,
            storage_used_bytes=0,
            files_limit=files_limit,
            files_used=0,
            public_links_limit=public_links_limit,
            public_links_used=0,
            active_upload_sessions_limit=active_upload_sessions_limit,
            active_upload_sessions_used=0,
            flush=flush,
            refresh=refresh,
            check_user_exists=check_user_exists,
            check_duplicate=check_duplicate,
        )

    # ------------------------------------------------------------------
    # Обновление лимитов
    # ------------------------------------------------------------------

    async def update_limits(
        self,
        user_id: uuid.UUID,
        *,
        storage_limit_bytes: int | None = None,
        max_file_size_bytes: int | None = None,
        files_limit: int | None | object = _UNSET,
        public_links_limit: int | None | object = _UNSET,
        active_upload_sessions_limit: int | None | object = _UNSET,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Обновляет лимиты квоты пользователя.

        Если параметр лимита не передан, текущее значение сохраняется.
        Если параметр ``*_limit`` передан как ``None``, соответствующий лимит
        снимается.

        Args:
            user_id: Идентификатор пользователя.
            storage_limit_bytes: Новый лимит хранилища в байтах.
            max_file_size_bytes: Новый максимальный размер файла в байтах.
            files_limit: Новый лимит количества файлов, ``None`` для снятия
                лимита или ``_UNSET`` без изменений.
            public_links_limit: Новый лимит публичных ссылок, ``None`` для
                снятия лимита или ``_UNSET`` без изменений.
            active_upload_sessions_limit: Новый лимит активных upload-сессий,
                ``None`` для снятия лимита или ``_UNSET`` без изменений.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если новые значения лимитов некорректны.
            ConstraintViolationError: Если текущие значения превышают новые
                лимиты.
        """

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        new_storage_limit_bytes = (
            quota.storage_limit_bytes
            if storage_limit_bytes is None
            else storage_limit_bytes
        )

        new_max_file_size_bytes = (
            quota.max_file_size_bytes
            if max_file_size_bytes is None
            else max_file_size_bytes
        )

        new_files_limit: int | None
        if files_limit is _UNSET:
            new_files_limit = quota.files_limit
        elif files_limit is None:
            new_files_limit = None
        else:
            assert isinstance(files_limit, int)
            new_files_limit = files_limit

        new_public_links_limit: int | None
        if public_links_limit is _UNSET:
            new_public_links_limit = quota.public_links_limit
        elif public_links_limit is None:
            new_public_links_limit = None
        else:
            assert isinstance(public_links_limit, int)
            new_public_links_limit = public_links_limit

        new_active_upload_sessions_limit: int | None
        if active_upload_sessions_limit is _UNSET:
            new_active_upload_sessions_limit = quota.active_upload_sessions_limit
        elif active_upload_sessions_limit is None:
            new_active_upload_sessions_limit = None
        else:
            assert isinstance(active_upload_sessions_limit, int)
            new_active_upload_sessions_limit = active_upload_sessions_limit

        self._validate_quota_values(
            storage_limit_bytes=new_storage_limit_bytes,
            storage_used_bytes=quota.storage_used_bytes,
            max_file_size_bytes=new_max_file_size_bytes,
            files_limit=new_files_limit,
            files_used=quota.files_used,
            public_links_limit=new_public_links_limit,
            public_links_used=quota.public_links_used,
            active_upload_sessions_limit=new_active_upload_sessions_limit,
            active_upload_sessions_used=quota.active_upload_sessions_used,
        )

        quota.update_limits(
            storage_limit_bytes=new_storage_limit_bytes,
            max_file_size_bytes=new_max_file_size_bytes,
            files_limit=new_files_limit,
            public_links_limit=new_public_links_limit,
            active_upload_sessions_limit=new_active_upload_sessions_limit,
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    # ------------------------------------------------------------------
    # Объём хранилища
    # ------------------------------------------------------------------

    async def update_storage_used(
        self,
        user_id: uuid.UUID,
        *,
        storage_used_bytes: int,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Устанавливает точное значение использованного объёма хранилища.

        Args:
            user_id: Идентификатор пользователя.
            storage_used_bytes: Новое значение использованного объёма в байтах.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если значение некорректно.
            ConstraintViolationError: Если использованный объём превышает лимит.
        """

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        self._validate_storage_used(
            storage_used_bytes=storage_used_bytes,
            storage_limit_bytes=quota.storage_limit_bytes,
        )

        quota.set_storage_usage(storage_used_bytes)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def increase_used_space(
        self,
        user_id: uuid.UUID,
        *,
        size_bytes: int,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Увеличивает использованный объём хранилища пользователя.

        Args:
            user_id: Идентификатор пользователя.
            size_bytes: Количество байтов, которое нужно добавить.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``size_bytes`` некорректен.
            ConstraintViolationError: Если итоговое использование превышает лимит.
        """

        self._validate_non_negative_int(
            value=size_bytes,
            field_name="size_bytes",
        )

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        self._validate_storage_used(
            storage_used_bytes=quota.storage_used_bytes + size_bytes,
            storage_limit_bytes=quota.storage_limit_bytes,
        )

        quota.increase_storage_usage(size_bytes)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def decrease_used_space(
        self,
        user_id: uuid.UUID,
        *,
        size_bytes: int,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Уменьшает использованный объём хранилища пользователя.

        Args:
            user_id: Идентификатор пользователя.
            size_bytes: Количество байтов, которое нужно вычесть.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``size_bytes`` некорректен.
        """

        self._validate_non_negative_int(
            value=size_bytes,
            field_name="size_bytes",
        )

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.decrease_storage_usage(size_bytes)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def reset_usage(
        self,
        user_id: uuid.UUID,
        *,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Сбрасывает использованный объём хранилища пользователя в ноль.

        Args:
            user_id: Идентификатор пользователя.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
        """

        return await self.update_storage_used(
            user_id=user_id,
            storage_used_bytes=0,
            flush=flush,
            refresh=refresh,
            for_update=for_update,
        )

    # ------------------------------------------------------------------
    # Счётчик файлов
    # ------------------------------------------------------------------

    async def increase_files_used(
        self,
        user_id: uuid.UUID,
        *,
        count: int = 1,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Увеличивает счётчик файлов пользователя.

        Args:
            user_id: Идентификатор пользователя.
            count: Количество файлов, которое нужно добавить.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``count`` некорректен.
        """

        self._validate_non_negative_int(value=count, field_name="count")

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.increase_files_used(count)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def decrease_files_used(
        self,
        user_id: uuid.UUID,
        *,
        count: int = 1,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Уменьшает счётчик файлов пользователя.

        Args:
            user_id: Идентификатор пользователя.
            count: Количество файлов, которое нужно вычесть.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``count`` некорректен.
        """

        self._validate_non_negative_int(value=count, field_name="count")

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.decrease_files_used(count)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def set_files_used(
        self,
        user_id: uuid.UUID,
        *,
        count: int,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Устанавливает точное значение счётчика файлов пользователя.

        Args:
            user_id: Идентификатор пользователя.
            count: Новое значение счётчика файлов.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``count`` некорректен.
        """

        self._validate_non_negative_int(value=count, field_name="count")

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.set_files_used(count)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    # ------------------------------------------------------------------
    # Счётчик публичных ссылок
    # ------------------------------------------------------------------

    async def increase_public_links_used(
        self,
        user_id: uuid.UUID,
        *,
        count: int = 1,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Увеличивает счётчик публичных ссылок пользователя.

        Args:
            user_id: Идентификатор пользователя.
            count: Количество публичных ссылок, которое нужно добавить.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``count`` некорректен.
        """

        self._validate_non_negative_int(value=count, field_name="count")

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.increase_public_links_used(count)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def decrease_public_links_used(
        self,
        user_id: uuid.UUID,
        *,
        count: int = 1,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Уменьшает счётчик публичных ссылок пользователя.

        Args:
            user_id: Идентификатор пользователя.
            count: Количество публичных ссылок, которое нужно вычесть.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``count`` некорректен.
        """

        self._validate_non_negative_int(value=count, field_name="count")

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.decrease_public_links_used(count)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def set_public_links_used(
        self,
        user_id: uuid.UUID,
        *,
        count: int,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Устанавливает точное значение счётчика публичных ссылок пользователя.

        Args:
            user_id: Идентификатор пользователя.
            count: Новое значение счётчика публичных ссылок.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``count`` некорректен.
        """

        self._validate_non_negative_int(value=count, field_name="count")

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.set_public_links_used(count)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    # ------------------------------------------------------------------
    # Счётчик активных upload-сессий
    # ------------------------------------------------------------------

    async def increase_active_upload_sessions_used(
        self,
        user_id: uuid.UUID,
        *,
        count: int = 1,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Увеличивает счётчик активных upload-сессий пользователя.

        Args:
            user_id: Идентификатор пользователя.
            count: Количество активных upload-сессий, которое нужно добавить.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``count`` некорректен.
        """

        self._validate_non_negative_int(value=count, field_name="count")

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.increase_active_upload_sessions_used(count)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def decrease_active_upload_sessions_used(
        self,
        user_id: uuid.UUID,
        *,
        count: int = 1,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Уменьшает счётчик активных upload-сессий пользователя.

        Args:
            user_id: Идентификатор пользователя.
            count: Количество активных upload-сессий, которое нужно вычесть.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``count`` некорректен.
        """

        self._validate_non_negative_int(value=count, field_name="count")

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.decrease_active_upload_sessions_used(count)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def set_active_upload_sessions_used(
        self,
        user_id: uuid.UUID,
        *,
        count: int,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Устанавливает точное значение счётчика активных upload-сессий пользователя.

        Args:
            user_id: Идентификатор пользователя.
            count: Новое значение счётчика активных upload-сессий.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``count`` некорректен.
        """

        self._validate_non_negative_int(value=count, field_name="count")

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        quota.set_active_upload_sessions_used(count)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    # ------------------------------------------------------------------
    # Проверки квот
    # ------------------------------------------------------------------

    async def check_available_space(
        self,
        user_id: uuid.UUID,
        *,
        required_bytes: int,
        for_update: bool = False,
    ) -> bool:
        """Проверяет, достаточно ли у пользователя свободного места.

        Args:
            user_id: Идентификатор пользователя.
            required_bytes: Требуемый объём свободного места в байтах.
            for_update: Заблокировать ли строку квоты для чтения.

        Returns:
            ``True``, если свободного места достаточно, иначе ``False``.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``required_bytes`` некорректен.
        """

        self._validate_non_negative_int(
            value=required_bytes,
            field_name="required_bytes",
        )

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        return required_bytes <= quota.available_storage_bytes

    async def check_file_size_allowed(
        self,
        user_id: uuid.UUID,
        *,
        file_size_bytes: int,
        for_update: bool = False,
    ) -> bool:
        """Проверяет, не превышает ли файл максимальный допустимый размер.

        Args:
            user_id: Идентификатор пользователя.
            file_size_bytes: Размер файла в байтах.
            for_update: Заблокировать ли строку квоты для чтения.

        Returns:
            ``True``, если размер файла допустим, иначе ``False``.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``file_size_bytes`` некорректен.
        """

        self._validate_non_negative_int(
            value=file_size_bytes,
            field_name="file_size_bytes",
        )

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        return file_size_bytes <= quota.max_file_size_bytes

    async def check_files_limit_allowed(
        self,
        user_id: uuid.UUID,
        *,
        additional_files_count: int = 1,
        use_stored_counter: bool = True,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> bool:
        """Проверяет, позволяет ли квота добавить указанное количество файлов.

        Если лимит файлов не задан, метод возвращает ``True``.
        Текущее количество файлов может браться из сохранённого счётчика
        или пересчитываться по базе данных.

        Args:
            user_id: Идентификатор пользователя.
            additional_files_count: Количество файлов, которое планируется добавить.
            use_stored_counter: Использовать ли сохранённый счётчик ``files_used``.
            include_deleted: Учитывать ли удалённые файлы при пересчёте.
            for_update: Заблокировать ли строку квоты для чтения.

        Returns:
            ``True``, если лимит позволяет добавить файлы, иначе ``False``.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``additional_files_count`` некорректен.
        """

        self._validate_non_negative_int(
            value=additional_files_count,
            field_name="additional_files_count",
        )

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        if quota.files_limit is None:
            return True

        current_files_count = (
            quota.files_used
            if use_stored_counter
            else await self.count_user_files(
                user_id=user_id,
                include_deleted=include_deleted,
            )
        )

        return current_files_count + additional_files_count <= quota.files_limit

    async def check_public_links_limit_allowed(
        self,
        user_id: uuid.UUID,
        *,
        additional_links_count: int = 1,
        use_stored_counter: bool = True,
        only_active: bool = True,
        for_update: bool = False,
    ) -> bool:
        """Проверяет, позволяет ли квота добавить публичные ссылки.

        Если лимит публичных ссылок не задан, метод возвращает ``True``.
        Текущее количество ссылок может браться из сохранённого счётчика
        или пересчитываться по базе данных.

        Args:
            user_id: Идентификатор пользователя.
            additional_links_count: Количество публичных ссылок, которое планируется добавить.
            use_stored_counter: Использовать ли сохранённый счётчик ``public_links_used``.
            only_active: Учитывать ли только активные публичные ссылки при пересчёте.
            for_update: Заблокировать ли строку квоты для чтения.

        Returns:
            ``True``, если лимит позволяет добавить ссылки, иначе ``False``.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``additional_links_count`` некорректен.
        """

        self._validate_non_negative_int(
            value=additional_links_count,
            field_name="additional_links_count",
        )

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        if quota.public_links_limit is None:
            return True

        current_links_count = (
            quota.public_links_used
            if use_stored_counter
            else await self.count_user_public_links(
                user_id=user_id,
                only_active=only_active,
            )
        )

        return current_links_count + additional_links_count <= quota.public_links_limit

    async def check_active_upload_sessions_limit_allowed(
        self,
        user_id: uuid.UUID,
        *,
        additional_sessions_count: int = 1,
        use_stored_counter: bool = True,
        exclude_time_expired: bool = False,
        for_update: bool = False,
    ) -> bool:
        """Проверяет, позволяет ли квота создать активную upload-сессию.

        Если лимит активных upload-сессий не задан, метод возвращает ``True``.
        Текущее количество сессий может браться из сохранённого счётчика
        или пересчитываться по базе данных.

        Args:
            user_id: Идентификатор пользователя.
            additional_sessions_count: Количество upload-сессий, которое планируется добавить.
            use_stored_counter: Использовать ли сохранённый счётчик активных upload-сессий.
            for_update: Заблокировать ли строку квоты для чтения.

        Returns:
            ``True``, если лимит позволяет создать upload-сессии, иначе ``False``.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если ``additional_sessions_count`` некорректен.
        """

        self._validate_non_negative_int(
            value=additional_sessions_count,
            field_name="additional_sessions_count",
        )

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        if quota.active_upload_sessions_limit is None:
            return True

        current_sessions_count = (
            quota.active_upload_sessions_used
            if use_stored_counter
            else await self.count_user_active_upload_sessions(
                user_id=user_id,
                exclude_time_expired=exclude_time_expired,
            )
        )

        return (
            current_sessions_count + additional_sessions_count
            <= quota.active_upload_sessions_limit
        )

    async def can_store_file(
        self,
        user_id: uuid.UUID,
        *,
        file_size_bytes: int,
        additional_files_count: int = 1,
        include_deleted_files_in_limit: bool = False,
        use_stored_files_counter: bool = True,
        for_update: bool = False,
    ) -> bool:
        """Комплексно проверяет, можно ли сохранить файл пользователя.

        Проверяет размер файла, доступное место в хранилище и лимит количества файлов,
        если такой лимит задан.

        Args:
            user_id: Идентификатор пользователя.
            file_size_bytes: Размер файла в байтах.
            additional_files_count: Количество файлов, которое планируется добавить.
            include_deleted_files_in_limit: Учитывать ли удалённые файлы при проверке лимита.
            use_stored_files_counter: Использовать ли сохранённый счётчик файлов.
            for_update: Заблокировать ли строку квоты для чтения.

        Returns:
            ``True``, если файл можно сохранить, иначе ``False``.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            InvalidQueryError: Если размер файла или количество файлов некорректны.
        """

        self._validate_non_negative_int(
            value=file_size_bytes,
            field_name="file_size_bytes",
        )
        self._validate_non_negative_int(
            value=additional_files_count,
            field_name="additional_files_count",
        )

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        if file_size_bytes > quota.max_file_size_bytes:
            return False

        if file_size_bytes > quota.available_storage_bytes:
            return False

        if quota.files_limit is None:
            return True

        current_files_count = (
            quota.files_used
            if use_stored_files_counter
            else await self.count_user_files(
                user_id=user_id,
                include_deleted=include_deleted_files_in_limit,
            )
        )

        return current_files_count + additional_files_count <= quota.files_limit

    # ------------------------------------------------------------------
    # Пересчёт и статистика
    # ------------------------------------------------------------------

    async def recalculate_usage(
        self,
        user_id: uuid.UUID,
        *,
        include_deleted: bool = True,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Пересчитывает фактически использованный объём хранилища пользователя.

        Фактическое использование вычисляется по таблицам файлов и узлов файловой
        системы, затем записывается в квоту пользователя.

        Args:
            user_id: Идентификатор пользователя.
            include_deleted: Учитывать ли удалённые файлы при расчёте.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            ConstraintViolationError: Если рассчитанное использование превышает лимит.
            RepositoryError: Если произошла ошибка при расчёте использования.
        """

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        actual_usage = await self.calculate_user_storage_usage(
            user_id=user_id,
            include_deleted=include_deleted,
        )

        self._validate_storage_used(
            storage_used_bytes=actual_usage,
            storage_limit_bytes=quota.storage_limit_bytes,
        )

        quota.storage_used_bytes = actual_usage

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def recalculate_counters(
        self,
        user_id: uuid.UUID,
        *,
        include_deleted_files: bool = False,
        only_active_public_links: bool = True,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Пересчитывает счётчики файлов, публичных ссылок и активных upload-сессий.

        Args:
            user_id: Идентификатор пользователя.
            include_deleted_files: Учитывать ли удалённые файлы при подсчёте файлов.
            only_active_public_links: Учитывать ли только активные публичные ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            ConstraintViolationError: Если пересчитанные значения превышают лимиты.
            RepositoryError: Если произошла ошибка при пересчёте.
        """

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        files_used = await self.count_user_files(
            user_id=user_id,
            include_deleted=include_deleted_files,
        )
        public_links_used = await self.count_user_public_links(
            user_id=user_id,
            only_active=only_active_public_links,
        )
        active_upload_sessions_used = await self.count_user_active_upload_sessions(
            user_id=user_id,
        )

        self._validate_quota_values(
            storage_limit_bytes=quota.storage_limit_bytes,
            storage_used_bytes=quota.storage_used_bytes,
            max_file_size_bytes=quota.max_file_size_bytes,
            files_limit=quota.files_limit,
            files_used=files_used,
            public_links_limit=quota.public_links_limit,
            public_links_used=public_links_used,
            active_upload_sessions_limit=quota.active_upload_sessions_limit,
            active_upload_sessions_used=active_upload_sessions_used,
        )

        quota.files_used = files_used
        quota.public_links_used = public_links_used
        quota.active_upload_sessions_used = active_upload_sessions_used

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def recalculate_all(
        self,
        user_id: uuid.UUID,
        *,
        include_deleted_files_in_storage: bool = True,
        include_deleted_files_in_count: bool = False,
        only_active_public_links: bool = True,
        flush: bool = True,
        refresh: bool = False,
        for_update: bool = True,
    ) -> UserQuota:
        """Пересчитывает использование хранилища и все счётчики квоты.

        Обновляет:
        - использованный объём хранилища;
        - количество файлов;
        - количество публичных ссылок;
        - количество активных upload-сессий.

        Args:
            user_id: Идентификатор пользователя.
            include_deleted_files_in_storage: Учитывать ли удалённые файлы при расчёте хранилища.
            include_deleted_files_in_count: Учитывать ли удалённые файлы при подсчёте файлов.
            only_active_public_links: Учитывать ли только активные публичные ссылки.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.
            for_update: Заблокировать ли строку квоты для обновления.

        Returns:
            Обновлённая квота пользователя.

        Raises:
            EntityNotFoundError: Если квота пользователя не найдена.
            ConstraintViolationError: Если пересчитанные значения превышают лимиты.
            RepositoryError: Если произошла ошибка при пересчёте.
        """

        quota = await self.get_required_by_user_id(
            user_id=user_id,
            for_update=for_update,
        )

        storage_used_bytes = await self.calculate_user_storage_usage(
            user_id=user_id,
            include_deleted=include_deleted_files_in_storage,
        )
        files_used = await self.count_user_files(
            user_id=user_id,
            include_deleted=include_deleted_files_in_count,
        )
        public_links_used = await self.count_user_public_links(
            user_id=user_id,
            only_active=only_active_public_links,
        )
        active_upload_sessions_used = await self.count_user_active_upload_sessions(
            user_id=user_id,
        )

        self._validate_quota_values(
            storage_limit_bytes=quota.storage_limit_bytes,
            storage_used_bytes=storage_used_bytes,
            max_file_size_bytes=quota.max_file_size_bytes,
            files_limit=quota.files_limit,
            files_used=files_used,
            public_links_limit=quota.public_links_limit,
            public_links_used=public_links_used,
            active_upload_sessions_limit=quota.active_upload_sessions_limit,
            active_upload_sessions_used=active_upload_sessions_used,
        )

        quota.storage_used_bytes = storage_used_bytes
        quota.files_used = files_used
        quota.public_links_used = public_links_used
        quota.active_upload_sessions_used = active_upload_sessions_used

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(quota)

        return quota

    async def calculate_user_storage_usage(
        self,
        user_id: uuid.UUID,
        *,
        include_deleted: bool = True,
    ) -> int:
        """Вычисляет фактический объём файлов пользователя.

        Расчёт выполняется по таблицам ``files`` и ``file_system_nodes``.

        Args:
            user_id: Идентификатор пользователя.
            include_deleted: Учитывать ли удалённые файлы.

        Returns:
            Фактический объём файлов пользователя в байтах.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            statement = (
                select(func.coalesce(func.sum(File.size_bytes), 0))
                .select_from(File)
                .join(FileSystemNode, FileSystemNode.id == File.node_id)
                .where(FileSystemNode.owner_id == user_id)
            )

            if not include_deleted:
                statement = statement.where(FileSystemNode.is_deleted.is_(False))

            result = await self.session.execute(statement)

            return int(result.scalar_one() or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="calculate_user_storage_usage",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "include_deleted": include_deleted,
                },
                cause=exc,
            ) from exc

    async def count_user_files(
        self,
        user_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> int:
        """Возвращает количество файлов пользователя.

        Args:
            user_id: Идентификатор пользователя.
            include_deleted: Учитывать ли удалённые файлы.

        Returns:
            Количество файлов пользователя.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            statement = (
                select(func.count(File.id))
                .select_from(File)
                .join(FileSystemNode, FileSystemNode.id == File.node_id)
                .where(FileSystemNode.owner_id == user_id)
            )

            if not include_deleted:
                statement = statement.where(FileSystemNode.is_deleted.is_(False))

            result = await self.session.execute(statement)

            return int(result.scalar_one() or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count_user_files",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "include_deleted": include_deleted,
                },
                cause=exc,
            ) from exc

    async def count_user_public_links(
        self,
        user_id: uuid.UUID,
        *,
        only_active: bool = True,
    ) -> int:
        """Возвращает количество публичных ссылок пользователя.

        Args:
            user_id: Идентификатор пользователя.
            only_active: Учитывать ли только активные публичные ссылки.

        Returns:
            Количество публичных ссылок пользователя.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            statement = select(func.count(PublicLink.id)).where(
                PublicLink.created_by == user_id,
            )

            if only_active:
                statement = statement.where(
                    PublicLink.is_active.is_(True),
                    PublicLink.status == PublicLinkStatus.ACTIVE,
                )

            result = await self.session.execute(statement)

            return int(result.scalar_one() or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count_user_public_links",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "only_active": only_active,
                },
                cause=exc,
            ) from exc

    async def count_user_active_upload_sessions(
        self,
        user_id: uuid.UUID,
        *,
        exclude_time_expired: bool = False,
    ) -> int:
        """Возвращает количество активных upload-сессий пользователя.

        Активными считаются upload-сессии в статусах ``CREATED`` и
        ``UPLOADING``.

        Args:
            user_id: Идентификатор пользователя.
            exclude_time_expired: Если ``True``, не учитывать сессии, у которых
                истёк срок ``expires_at``, но которые ещё не были помечены как
                ``EXPIRED`` фоновым воркером. Логически такие сессии уже мертвы
                и не должны блокировать создание новых загрузок.

        Returns:
            Количество активных upload-сессий пользователя.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            conditions = [
                UploadSession.user_id == user_id,
                UploadSession.status.in_(
                    [
                        UploadSessionStatus.CREATED,
                        UploadSessionStatus.UPLOADING,
                    ],
                ),
            ]
            if exclude_time_expired:
                conditions.append(UploadSession.expires_at > datetime.now(UTC))

            statement = select(func.count(UploadSession.id)).where(*conditions)

            result = await self.session.execute(statement)

            return int(result.scalar_one() or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count_user_active_upload_sessions",
                reason=str(exc),
                details={"user_id": str(user_id)},
                cause=exc,
            ) from exc

    async def list_near_limit(
        self,
        *,
        threshold_percent: float = 90.0,
        offset: int = 0,
        limit: int = 100,
    ) -> list[UserQuota]:
        """Возвращает квоты пользователей, близких к заполнению хранилища.

        Квота попадает в выборку, если процент использования хранилища
        больше или равен указанному порогу.

        Args:
            threshold_percent: Минимальный процент использования хранилища.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список квот, близких к лимиту хранилища.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны
                или порог находится вне диапазона от 0 до 100.
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        self._validate_pagination(offset=offset, limit=limit)

        if threshold_percent < 0 or threshold_percent > 100:
            raise InvalidQueryError(
                "Порог использования должен находиться в диапазоне от 0 до 100.",
                repository=self.repository_name,
                operation="list_near_limit",
                details={"threshold_percent": threshold_percent},
            )

        try:
            usage_expression = (UserQuota.storage_used_bytes * 100.0) / func.nullif(
                UserQuota.storage_limit_bytes, 0
            )

            statement = (
                select(UserQuota)
                .where(usage_expression >= threshold_percent)
                .order_by(usage_expression.desc())
                .offset(offset)
                .limit(limit)
            )

            result = await self.session.execute(statement)

            return list(result.scalars().all())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="list_near_limit",
                reason=str(exc),
                details={
                    "threshold_percent": threshold_percent,
                    "offset": offset,
                    "limit": limit,
                },
                cause=exc,
            ) from exc

    async def list_over_limit(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[UserQuota]:
        """Возвращает квоты, у которых использованный объём превышает лимит.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список квот с превышенным лимитом хранилища.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(UserQuota)
            .where(UserQuota.storage_used_bytes > UserQuota.storage_limit_bytes)
            .order_by(UserQuota.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="list_over_limit",
        )

    # ------------------------------------------------------------------
    # Вспомогательные методы выполнения запросов
    # ------------------------------------------------------------------

    async def _scalar_int(
        self,
        statement: Select[Any],
        *,
        operation: str,
    ) -> int:
        """Выполняет SELECT-запрос и возвращает целочисленное значение.

        Args:
            statement: SQLAlchemy SELECT-запрос.
            operation: Название операции для сообщений об ошибках.

        Returns:
            Результат запроса, приведённый к ``int``.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            result = await self.session.execute(statement)
            value = result.scalar_one()

            return int(value or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation=operation,
                reason=str(exc),
                cause=exc,
            ) from exc

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

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def _validate_quota_values(
        self,
        *,
        storage_limit_bytes: int,
        storage_used_bytes: int,
        max_file_size_bytes: int,
        files_limit: int | None,
        files_used: int,
        public_links_limit: int | None,
        public_links_used: int,
        active_upload_sessions_limit: int | None,
        active_upload_sessions_used: int,
    ) -> None:
        """Проверяет согласованность значений квоты.

        Валидирует лимиты и текущие счётчики, а также проверяет, что
        использованные значения не превышают соответствующие лимиты.

        Args:
            storage_limit_bytes: Лимит хранилища в байтах.
            storage_used_bytes: Использованный объём хранилища в байтах.
            max_file_size_bytes: Максимальный размер одного файла в байтах.
            files_limit: Лимит количества файлов или ``None``.
            files_used: Текущее количество файлов.
            public_links_limit: Лимит публичных ссылок или ``None``.
            public_links_used: Текущее количество публичных ссылок.
            active_upload_sessions_limit: Лимит активных upload-сессий или
                ``None``.
            active_upload_sessions_used: Текущее количество активных
                upload-сессий.

        Raises:
            InvalidQueryError: Если одно из числовых значений некорректно.
            ConstraintViolationError: Если использованное значение превышает
                лимит.
        """

        self._validate_non_negative_int(
            value=storage_limit_bytes,
            field_name="storage_limit_bytes",
        )
        self._validate_non_negative_int(
            value=storage_used_bytes,
            field_name="storage_used_bytes",
        )
        self._validate_non_negative_int(
            value=max_file_size_bytes,
            field_name="max_file_size_bytes",
        )
        self._validate_non_negative_int(
            value=files_used,
            field_name="files_used",
        )
        self._validate_non_negative_int(
            value=public_links_used,
            field_name="public_links_used",
        )
        self._validate_non_negative_int(
            value=active_upload_sessions_used,
            field_name="active_upload_sessions_used",
        )

        if files_limit is not None:
            self._validate_non_negative_int(
                value=files_limit,
                field_name="files_limit",
            )

        if public_links_limit is not None:
            self._validate_non_negative_int(
                value=public_links_limit,
                field_name="public_links_limit",
            )

        if active_upload_sessions_limit is not None:
            self._validate_non_negative_int(
                value=active_upload_sessions_limit,
                field_name="active_upload_sessions_limit",
            )

        self._validate_storage_used(
            storage_used_bytes=storage_used_bytes,
            storage_limit_bytes=storage_limit_bytes,
        )

        if files_limit is not None and files_used > files_limit:
            raise ConstraintViolationError(
                "Количество файлов не может превышать установленный лимит.",
                constraint_name="ck_user_quotas_files_used_lte_limit",
                table_name="user_quotas",
                details={
                    "repository": self.repository_name,
                    "files_used": files_used,
                    "files_limit": files_limit,
                },
            )

        if public_links_limit is not None and public_links_used > public_links_limit:
            raise ConstraintViolationError(
                "Количество публичных ссылок не может превышать установленный лимит.",
                constraint_name="ck_user_quotas_public_links_used_lte_limit",
                table_name="user_quotas",
                details={
                    "repository": self.repository_name,
                    "public_links_used": public_links_used,
                    "public_links_limit": public_links_limit,
                },
            )

        if (
            active_upload_sessions_limit is not None
            and active_upload_sessions_used > active_upload_sessions_limit
        ):
            raise ConstraintViolationError(
                "Количество активных upload-сессий не может превышать установленный лимит.",
                constraint_name="ck_user_quotas_active_upload_sessions_used_lte_limit",
                table_name="user_quotas",
                details={
                    "repository": self.repository_name,
                    "active_upload_sessions_used": active_upload_sessions_used,
                    "active_upload_sessions_limit": active_upload_sessions_limit,
                },
            )

    def _validate_storage_used(
        self,
        *,
        storage_used_bytes: int,
        storage_limit_bytes: int,
    ) -> None:
        """Проверяет корректность использованного объёма хранилища.

        Значение должно быть неотрицательным и не должно превышать лимит хранилища.

        Args:
            storage_used_bytes: Использованный объём хранилища в байтах.
            storage_limit_bytes: Лимит хранилища в байтах.

        Raises:
            InvalidQueryError: Если одно из значений некорректно.
            ConstraintViolationError: Если использованный объём превышает лимит.
        """

        self._validate_non_negative_int(
            value=storage_used_bytes,
            field_name="storage_used_bytes",
        )
        self._validate_non_negative_int(
            value=storage_limit_bytes,
            field_name="storage_limit_bytes",
        )

        if storage_used_bytes > storage_limit_bytes:
            raise ConstraintViolationError(
                "Использованный объём хранилища не может превышать установленный лимит.",
                constraint_name="ck_user_quotas_storage_used_lte_limit",
                table_name="user_quotas",
                details={
                    "repository": self.repository_name,
                    "storage_used_bytes": storage_used_bytes,
                    "storage_limit_bytes": storage_limit_bytes,
                },
            )

    def _validate_non_negative_int(
        self,
        *,
        value: int,
        field_name: str,
    ) -> None:
        """Проверяет, что значение является неотрицательным целым числом.

        Args:
            value: Проверяемое значение.
            field_name: Название поля для сообщения об ошибке.

        Raises:
            InvalidQueryError: Если значение не является ``int`` или меньше нуля.
        """

        if not isinstance(value, int):
            raise InvalidQueryError(
                "Значение должно быть целым числом.",
                repository=self.repository_name,
                operation="_validate_non_negative_int",
                details={
                    "field": field_name,
                    "value": value,
                    "value_type": type(value).__name__,
                },
            )

        if value < 0:
            raise InvalidQueryError(
                "Значение не может быть отрицательным.",
                repository=self.repository_name,
                operation="_validate_non_negative_int",
                details={
                    "field": field_name,
                    "value": value,
                },
            )
