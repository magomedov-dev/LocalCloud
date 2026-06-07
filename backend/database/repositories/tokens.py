from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import SessionStatus
from database.models.tokens import RefreshToken
from database.models.users import User
from database.repositories.base import BaseRepository


class RefreshTokensRepository(BaseRepository[RefreshToken]):
    """Репозиторий для работы с refresh-токенами.

    Инкапсулирует операции создания, поиска, проверки активности, ротации,
    отзыва, деактивации, удаления и подсчёта refresh-токенов.

    Работает с моделью ``RefreshToken`` через асинхронную SQLAlchemy-сессию.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий refresh-токенов.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=RefreshToken)

    # ------------------------------------------------------------------
    # Получение refresh-токена
    # ------------------------------------------------------------------

    async def get_token_by_id(
        self,
        token_id: uuid.UUID,
    ) -> RefreshToken | None:
        """Возвращает refresh-токен по идентификатору.

        Args:
            token_id: Идентификатор refresh-токена.

        Returns:
            Refresh-токен, если он найден, иначе ``None``.
        """

        return await self.get_by_id(token_id)

    async def get_required_token_by_id(
        self,
        token_id: uuid.UUID,
    ) -> RefreshToken:
        """Возвращает refresh-токен по идентификатору.

        Args:
            token_id: Идентификатор refresh-токена.

        Returns:
            Найденный refresh-токен.

        Raises:
            EntityNotFoundError: Если refresh-токен не найден.
        """

        return await self.get_required_by_id(token_id)

    async def get_by_hash(
        self,
        token_hash: str,
    ) -> RefreshToken | None:
        """Возвращает refresh-токен по хэшу.

        Метод ожидает уже готовый безопасный хэш токена, а не исходное значение
        refresh-токена.

        Args:
            token_hash: Хэш refresh-токена.

        Returns:
            Refresh-токен, если он найден, иначе ``None``.
        """

        normalized_token_hash = self._normalize_token_hash(token_hash)

        if not normalized_token_hash:
            return None

        statement = select(RefreshToken).where(
            RefreshToken.token_hash == normalized_token_hash,
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_hash",
        )

    async def get_required_by_hash(
        self,
        token_hash: str,
    ) -> RefreshToken:
        """Возвращает refresh-токен по хэшу.

        Args:
            token_hash: Хэш refresh-токена.

        Returns:
            Найденный refresh-токен.

        Raises:
            EntityNotFoundError: Если refresh-токен с указанным хэшем не найден.
        """

        token = await self.get_by_hash(token_hash)

        if token is None:
            raise EntityNotFoundError(
                "RefreshToken",
                lookup={"token_hash": "<hidden>"},
                repository=self.repository_name,
            )

        return token

    async def token_hash_exists(
        self,
        token_hash: str,
    ) -> bool:
        """Проверяет существование refresh-токена с указанным хэшем.

        Args:
            token_hash: Хэш refresh-токена.

        Returns:
            ``True``, если токен с таким хэшем существует, иначе ``False``.
        """

        normalized_token_hash = self._normalize_token_hash(token_hash)

        if not normalized_token_hash:
            return False

        return await self.exists(
            RefreshToken.token_hash == normalized_token_hash,
        )

    # ------------------------------------------------------------------
    # Создание refresh-токена
    # ------------------------------------------------------------------

    async def create_token(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        status: SessionStatus = SessionStatus.ACTIVE,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
        is_active: bool = True,
        parent_token_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
        check_duplicate: bool = True,
        check_parent_exists: bool = True,
    ) -> RefreshToken:
        """Создаёт новый refresh-токен.

        Перед созданием нормализует и валидирует хэш токена. При необходимости
        проверяет существование пользователя, parent-токена и отсутствие
        дубликата по хэшу.

        Args:
            user_id: Идентификатор пользователя, которому принадлежит токен.
            token_hash: Хэш refresh-токена.
            expires_at: Дата и время истечения срока действия токена.
            status: Начальный статус токена.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            device_name: Название устройства.
            is_active: Признак активности токена.
            parent_token_id: Идентификатор родительского токена при ротации.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_user_exists: Проверять ли существование пользователя.
            check_duplicate: Проверять ли дубликат по хэшу токена.
            check_parent_exists: Проверять ли существование parent-токена.

        Returns:
            Созданный refresh-токен.

        Raises:
            InvalidQueryError: Если хэш токена пустой или слишком длинный.
            EntityNotFoundError: Если пользователь или parent-токен не найден.
            DuplicateEntityError: Если refresh-токен с таким хэшем уже существует.
        """

        normalized_token_hash = self._normalize_token_hash(token_hash)
        self._validate_token_hash(normalized_token_hash)

        if check_user_exists:
            await self._ensure_user_exists(user_id)

        if parent_token_id is not None and check_parent_exists:
            await self.get_required_by_id(parent_token_id)

        if check_duplicate and await self.token_hash_exists(normalized_token_hash):
            raise DuplicateEntityError(
                "RefreshToken",
                field="token_hash",
                value="<hidden>",
                repository=self.repository_name,
            )

        refresh_token = RefreshToken(
            user_id=user_id,
            token_hash=normalized_token_hash,
            status=status,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name.strip() if device_name else None,
            is_active=is_active,
            parent_token_id=parent_token_id,
        )

        try:
            return await self.create(
                refresh_token,
                flush=flush,
                refresh=refresh,
            )

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_token",
            ) from exc

    # ------------------------------------------------------------------
    # Списки токенов пользователя
    # ------------------------------------------------------------------

    async def list_user_tokens(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        include_inactive: bool = True,
        include_revoked: bool = True,
        include_expired: bool = True,
        moment: datetime | None = None,
        order_by_created_desc: bool = True,
    ) -> list[RefreshToken]:
        """Возвращает refresh-токены пользователя с пагинацией и фильтрами.

        Args:
            user_id: Идентификатор пользователя.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            include_inactive: Включать ли неактивные токены.
            include_revoked: Включать ли отозванные токены.
            include_expired: Включать ли истёкшие токены.
            moment: Момент времени для проверки истечения срока действия.
            order_by_created_desc: Сортировать ли по дате создания по убыванию.

        Returns:
            Список refresh-токенов пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        effective_moment = moment or self._utc_now()

        statement = select(RefreshToken).where(RefreshToken.user_id == user_id)

        if not include_inactive:
            statement = statement.where(RefreshToken.is_active.is_(True))

        if not include_revoked:
            statement = statement.where(
                RefreshToken.revoked_at.is_(None),
                RefreshToken.status != SessionStatus.REVOKED,
            )

        if not include_expired:
            statement = statement.where(
                RefreshToken.expires_at > effective_moment,
                RefreshToken.status != SessionStatus.EXPIRED,
            )

        if order_by_created_desc:
            statement = statement.order_by(RefreshToken.created_at.desc())
        else:
            statement = statement.order_by(RefreshToken.created_at.asc())

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="list_user_tokens",
        )

    async def list_active_user_tokens(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        moment: datetime | None = None,
        order_by_created_desc: bool = True,
    ) -> list[RefreshToken]:
        """Возвращает активные refresh-токены пользователя.

        Активным считается токен, который:

        * имеет ``is_active=True``;
        * имеет статус ``ACTIVE``;
        * не был отозван;
        * не был заменён другим токеном;
        * не истёк на указанный момент времени.

        Args:
            user_id: Идентификатор пользователя.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            moment: Момент времени для проверки актуальности токена.
            order_by_created_desc: Сортировать ли по дате создания по убыванию.

        Returns:
            Список активных refresh-токенов пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        effective_moment = moment or self._utc_now()

        statement = (
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_active.is_(True),
                RefreshToken.status == SessionStatus.ACTIVE,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.replaced_by_token_id.is_(None),
                RefreshToken.expires_at > effective_moment,
            )
            .offset(offset)
            .limit(limit)
        )

        if order_by_created_desc:
            statement = statement.order_by(RefreshToken.created_at.desc())
        else:
            statement = statement.order_by(RefreshToken.created_at.asc())

        return await self.scalars_all(
            statement,
            operation="list_active_user_tokens",
        )

    async def list_revoked_user_tokens(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by_revoked_desc: bool = True,
    ) -> list[RefreshToken]:
        """Возвращает отозванные refresh-токены пользователя.

        Args:
            user_id: Идентификатор пользователя.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            order_by_revoked_desc: Сортировать ли по дате отзыва по убыванию.

        Returns:
            Список отозванных refresh-токенов пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_not(None),
        )

        if order_by_revoked_desc:
            statement = statement.order_by(
                RefreshToken.revoked_at.desc().nullslast(),
            )
        else:
            statement = statement.order_by(
                RefreshToken.revoked_at.asc().nullslast(),
            )

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="list_revoked_user_tokens",
        )

    async def list_expired_user_tokens(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        moment: datetime | None = None,
    ) -> list[RefreshToken]:
        """Возвращает истёкшие refresh-токены пользователя.

        Args:
            user_id: Идентификатор пользователя.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            moment: Момент времени, относительно которого проверяется истечение.

        Returns:
            Список истёкших refresh-токенов пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        effective_moment = moment or self._utc_now()

        statement = (
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.expires_at <= effective_moment,
            )
            .order_by(RefreshToken.expires_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="list_expired_user_tokens",
        )

    # ------------------------------------------------------------------
    # Отзыв и деактивация токенов
    # ------------------------------------------------------------------

    async def revoke_token(
        self,
        refresh_token: RefreshToken,
        *,
        reason: str | None = None,
        revoked_at: datetime | None = None,
        replaced_by_token_id: uuid.UUID | None = None,
        deactivate: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> RefreshToken:
        """Отзывает refresh-токен.

        При необходимости связывает текущий токен с новым токеном через
        ``replaced_by_token_id``. По умолчанию токен также деактивируется.

        Args:
            refresh_token: Refresh-токен для отзыва.
            reason: Причина отзыва.
            revoked_at: Дата и время отзыва. Если не передана, используется
                текущее UTC-время.
            replaced_by_token_id: Идентификатор токена, которым был заменён
                текущий токен.
            deactivate: Деактивировать ли токен после отзыва.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый refresh-токен.
        """

        if replaced_by_token_id is not None:
            refresh_token.replaced_by_token_id = replaced_by_token_id

        refresh_token.revoke(
            reason=reason.strip() if reason else None,
            revoked_at=revoked_at or self._utc_now(),
        )

        if not deactivate:
            refresh_token.is_active = True

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(refresh_token)

        return refresh_token

    async def revoke_token_by_id(
        self,
        token_id: uuid.UUID,
        *,
        reason: str | None = None,
        revoked_at: datetime | None = None,
        replaced_by_token_id: uuid.UUID | None = None,
        deactivate: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> RefreshToken:
        """Отзывает refresh-токен по идентификатору.

        Args:
            token_id: Идентификатор refresh-токена.
            reason: Причина отзыва.
            revoked_at: Дата и время отзыва.
            replaced_by_token_id: Идентификатор токена, которым был заменён
                текущий токен.
            deactivate: Деактивировать ли токен после отзыва.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый refresh-токен.

        Raises:
            EntityNotFoundError: Если refresh-токен не найден.
        """

        token = await self.get_required_by_id(token_id)

        return await self.revoke_token(
            token,
            reason=reason,
            revoked_at=revoked_at,
            replaced_by_token_id=replaced_by_token_id,
            deactivate=deactivate,
            flush=flush,
            refresh=refresh,
        )

    async def revoke_token_by_hash(
        self,
        token_hash: str,
        *,
        reason: str | None = None,
        revoked_at: datetime | None = None,
        replaced_by_token_id: uuid.UUID | None = None,
        deactivate: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> RefreshToken:
        """Отзывает refresh-токен по хэшу.

        Args:
            token_hash: Хэш refresh-токена.
            reason: Причина отзыва.
            revoked_at: Дата и время отзыва.
            replaced_by_token_id: Идентификатор токена, которым был заменён
                текущий токен.
            deactivate: Деактивировать ли токен после отзыва.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый refresh-токен.

        Raises:
            EntityNotFoundError: Если refresh-токен с указанным хэшем не найден.
        """

        token = await self.get_required_by_hash(token_hash)

        return await self.revoke_token(
            token,
            reason=reason,
            revoked_at=revoked_at,
            replaced_by_token_id=replaced_by_token_id,
            deactivate=deactivate,
            flush=flush,
            refresh=refresh,
        )

    async def revoke_all_user_tokens(
        self,
        user_id: uuid.UUID,
        *,
        reason: str | None = None,
        revoked_at: datetime | None = None,
        exclude_token_id: uuid.UUID | None = None,
        flush: bool = True,
    ) -> int:
        """Отзывает все активные refresh-токены пользователя.

        Можно исключить один токен из отзыва, например текущую сессию
        пользователя.

        Args:
            user_id: Идентификатор пользователя.
            reason: Причина отзыва.
            revoked_at: Дата и время отзыва. Если не передана, используется
                текущее UTC-время.
            exclude_token_id: Идентификатор токена, который не нужно отзывать.
            flush: Выполнить ``flush`` после обновления.

        Returns:
            Количество отозванных токенов.
        """

        effective_revoked_at = revoked_at or self._utc_now()

        tokens = await self.list_active_user_tokens(
            user_id,
            offset=0,
            limit=1000,
            moment=effective_revoked_at,
        )

        revoked_count = 0

        for token in tokens:
            if exclude_token_id is not None and token.id == exclude_token_id:
                continue

            token.revoke(
                reason=reason.strip() if reason else None,
                revoked_at=effective_revoked_at,
            )
            revoked_count += 1

        if flush:
            await self.flush()

        return revoked_count

    async def deactivate_token(
        self,
        refresh_token: RefreshToken,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> RefreshToken:
        """Помечает refresh-токен как неактивный.

        Args:
            refresh_token: Refresh-токен для деактивации.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый refresh-токен.
        """

        refresh_token.deactivate()

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(refresh_token)

        return refresh_token

    async def deactivate_token_by_id(
        self,
        token_id: uuid.UUID,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> RefreshToken:
        """Деактивирует refresh-токен по идентификатору.

        Args:
            token_id: Идентификатор refresh-токена.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый refresh-токен.

        Raises:
            EntityNotFoundError: Если refresh-токен не найден.
        """

        token = await self.get_required_by_id(token_id)

        return await self.deactivate_token(
            token,
            flush=flush,
            refresh=refresh,
        )

    async def deactivate_token_by_hash(
        self,
        token_hash: str,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> RefreshToken:
        """Деактивирует refresh-токен по хэшу.

        Args:
            token_hash: Хэш refresh-токена.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённый refresh-токен.

        Raises:
            EntityNotFoundError: Если refresh-токен с указанным хэшем не найден.
        """

        token = await self.get_required_by_hash(token_hash)

        return await self.deactivate_token(
            token,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Ротация токена
    # ------------------------------------------------------------------

    async def rotate_token(
        self,
        *,
        old_token: RefreshToken,
        new_token_hash: str,
        new_expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
        revoked_at: datetime | None = None,
        revoke_reason: str | None = "Replaced by token rotation",
        flush: bool = True,
        refresh: bool = False,
        check_duplicate: bool = True,
    ) -> RefreshToken:
        """Выполняет ротацию refresh-токена.

        Ротация создаёт новый токен для того же пользователя, связывает его
        со старым токеном через ``parent_token_id``, затем помечает старый токен
        как заменённый и отозванный.

        Старый токен должен быть пригоден к использованию на момент ротации.

        Args:
            old_token: Старый refresh-токен.
            new_token_hash: Хэш нового refresh-токена.
            new_expires_at: Дата и время истечения нового токена.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            device_name: Название устройства. Если не передано, используется
                устройство старого токена.
            revoked_at: Дата и время отзыва старого токена.
            revoke_reason: Причина отзыва старого токена.
            flush: Выполнить ``flush`` после операции.
            refresh: Выполнить ``refresh`` для нового токена.
            check_duplicate: Проверять ли дубликат нового хэша токена.

        Returns:
            Новый refresh-токен.

        Raises:
            InvalidQueryError: Если старый токен не может быть использован или
                новый хэш некорректен.
            DuplicateEntityError: Если новый хэш токена уже существует.
            RepositoryError: Если произошла ошибка при выполнении операции
                в базе данных.
        """

        if not old_token.can_be_used_at(self._utc_now()):
            raise InvalidQueryError(
                "Нельзя ротировать неактивный, отозванный, заменённый или истёкший refresh-токен.",
                repository=self.repository_name,
                operation="rotate_token",
                details={
                    "old_token_id": str(old_token.id),
                    "user_id": str(old_token.user_id),
                    "status": old_token.status.value,
                    "is_active": old_token.is_active,
                    "revoked_at": old_token.revoked_at.isoformat()
                    if old_token.revoked_at
                    else None,
                    "expires_at": old_token.expires_at.isoformat(),
                    "replaced_by_token_id": str(old_token.replaced_by_token_id)
                    if old_token.replaced_by_token_id
                    else None,
                },
            )

        normalized_new_token_hash = self._normalize_token_hash(new_token_hash)
        self._validate_token_hash(normalized_new_token_hash)

        if check_duplicate and await self.token_hash_exists(normalized_new_token_hash):
            raise DuplicateEntityError(
                "RefreshToken",
                field="token_hash",
                value="<hidden>",
                repository=self.repository_name,
            )

        new_token = RefreshToken(
            user_id=old_token.user_id,
            token_hash=normalized_new_token_hash,
            status=SessionStatus.ACTIVE,
            expires_at=new_expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name.strip() if device_name else old_token.device_name,
            is_active=True,
            parent_token_id=old_token.id,
        )

        try:
            self.session.add(new_token)
            await self.flush()

            old_token.replace_with(
                new_token,
                replaced_at=revoked_at or self._utc_now(),
            )

            if revoke_reason:
                old_token.revoke_reason = revoke_reason

            if flush:
                await self.flush()

            if refresh:
                await self.refresh(new_token)

            return new_token

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="rotate_token",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="rotate_token",
                reason=str(exc),
                details={
                    "old_token_id": str(old_token.id),
                    "user_id": str(old_token.user_id),
                },
                cause=exc,
            ) from exc

    async def rotate_token_by_hash(
        self,
        *,
        old_token_hash: str,
        new_token_hash: str,
        new_expires_at: datetime,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
        revoked_at: datetime | None = None,
        revoke_reason: str | None = "Replaced by token rotation",
        flush: bool = True,
        refresh: bool = False,
        check_duplicate: bool = True,
    ) -> RefreshToken:
        """Выполняет ротацию refresh-токена по хэшу старого токена.

        Args:
            old_token_hash: Хэш старого refresh-токена.
            new_token_hash: Хэш нового refresh-токена.
            new_expires_at: Дата и время истечения нового токена.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            device_name: Название устройства.
            revoked_at: Дата и время отзыва старого токена.
            revoke_reason: Причина отзыва старого токена.
            flush: Выполнить ``flush`` после операции.
            refresh: Выполнить ``refresh`` для нового токена.
            check_duplicate: Проверять ли дубликат нового хэша токена.

        Returns:
            Новый refresh-токен.

        Raises:
            EntityNotFoundError: Если старый токен не найден.
            InvalidQueryError: Если старый токен не может быть использован или
                новый хэш некорректен.
            DuplicateEntityError: Если новый хэш токена уже существует.
        """

        old_token = await self.get_required_by_hash(old_token_hash)

        return await self.rotate_token(
            old_token=old_token,
            new_token_hash=new_token_hash,
            new_expires_at=new_expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            revoked_at=revoked_at,
            revoke_reason=revoke_reason,
            flush=flush,
            refresh=refresh,
            check_duplicate=check_duplicate,
        )

    # ------------------------------------------------------------------
    # Проверка активности токена
    # ------------------------------------------------------------------

    async def is_token_active(
        self,
        token_hash: str,
        *,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет, активен ли refresh-токен по хэшу.

        Args:
            token_hash: Хэш refresh-токена.
            moment: Момент времени для проверки активности. Если не передан,
                используется текущее UTC-время.

        Returns:
            ``True``, если токен существует и может быть использован,
            иначе ``False``.
        """

        token = await self.get_by_hash(token_hash)

        if token is None:
            return False

        return token.can_be_used_at(moment or self._utc_now())

    async def get_active_by_hash(
        self,
        token_hash: str,
        *,
        moment: datetime | None = None,
    ) -> RefreshToken | None:
        """Возвращает активный refresh-токен по хэшу.

        Активным считается токен, который:

        * имеет ``is_active=True``;
        * имеет статус ``ACTIVE``;
        * не был отозван;
        * не был заменён другим токеном;
        * не истёк на указанный момент времени.

        Args:
            token_hash: Хэш refresh-токена.
            moment: Момент времени для проверки активности.

        Returns:
            Активный refresh-токен или ``None``.
        """

        normalized_token_hash = self._normalize_token_hash(token_hash)

        if not normalized_token_hash:
            return None

        effective_moment = moment or self._utc_now()

        statement = select(RefreshToken).where(
            RefreshToken.token_hash == normalized_token_hash,
            RefreshToken.is_active.is_(True),
            RefreshToken.status == SessionStatus.ACTIVE,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.replaced_by_token_id.is_(None),
            RefreshToken.expires_at > effective_moment,
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_active_by_hash",
        )

    async def get_required_active_by_hash(
        self,
        token_hash: str,
        *,
        moment: datetime | None = None,
    ) -> RefreshToken:
        """Возвращает активный refresh-токен по хэшу.

        Args:
            token_hash: Хэш refresh-токена.
            moment: Момент времени для проверки активности.

        Returns:
            Активный refresh-токен.

        Raises:
            EntityNotFoundError: Если активный refresh-токен не найден.
        """

        token = await self.get_active_by_hash(
            token_hash,
            moment=moment,
        )

        if token is None:
            raise EntityNotFoundError(
                "RefreshToken",
                lookup={
                    "token_hash": "<hidden>",
                    "active": True,
                },
                repository=self.repository_name,
            )

        return token

    # ------------------------------------------------------------------
    # Пометка истёкших токенов
    # ------------------------------------------------------------------

    async def mark_expired_tokens(
        self,
        *,
        expired_before: datetime | None = None,
        flush: bool = True,
    ) -> int:
        """Помечает истёкшие активные refresh-токены как ``EXPIRED``.

        Обновляются только токены со статусом ``ACTIVE``, срок действия которых
        меньше или равен указанному моменту времени.

        Args:
            expired_before: Момент времени, до которого токены считаются
                истёкшими. Если не передан, используется текущее UTC-время.
            flush: Выполнить ``flush`` после обновления.

        Returns:
            Количество токенов, помеченных как истёкшие.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении операции
                в базе данных.
        """

        effective_expired_before = expired_before or self._utc_now()

        try:
            statement = select(RefreshToken).where(
                RefreshToken.expires_at <= effective_expired_before,
                RefreshToken.status == SessionStatus.ACTIVE,
            )

            result = await self.session.execute(statement)
            tokens = list(result.scalars().all())

            for token in tokens:
                token.mark_expired()

            if flush:
                await self.flush()

            return len(tokens)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="mark_expired_tokens",
                reason=str(exc),
                details={
                    "expired_before": effective_expired_before.isoformat(),
                },
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Очистка токенов
    # ------------------------------------------------------------------

    async def delete_expired_tokens(
        self,
        *,
        expired_before: datetime | None = None,
        flush: bool = True,
    ) -> int:
        """Физически удаляет истёкшие refresh-токены.

        Args:
            expired_before: Момент времени, до которого токены считаются
                истёкшими. Если не передан, используется текущее UTC-время.
            flush: Выполнить ``flush`` после удаления.

        Returns:
            Количество удалённых токенов.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении удаления.
        """

        effective_expired_before = expired_before or self._utc_now()

        try:
            result = await self.session.execute(
                delete(RefreshToken).where(
                    RefreshToken.expires_at <= effective_expired_before,
                ),
            )

            if flush:
                await self.flush()

            return int(getattr(result, "rowcount", 0) or 0)

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="delete_expired_tokens",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="delete_expired_tokens",
                reason=str(exc),
                details={
                    "expired_before": effective_expired_before.isoformat(),
                },
                cause=exc,
            ) from exc

    async def delete_revoked_tokens(
        self,
        *,
        revoked_before: datetime | None = None,
        flush: bool = True,
    ) -> int:
        """Физически удаляет отозванные refresh-токены.

        Если передан ``revoked_before``, удаляются только токены, отозванные
        не позже указанного момента.

        Args:
            revoked_before: Верхняя граница даты отзыва токена.
            flush: Выполнить ``flush`` после удаления.

        Returns:
            Количество удалённых токенов.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении удаления.
        """

        try:
            statement = delete(RefreshToken).where(
                RefreshToken.revoked_at.is_not(None),
            )

            if revoked_before is not None:
                statement = statement.where(
                    RefreshToken.revoked_at <= revoked_before,
                )

            result = await self.session.execute(statement)

            if flush:
                await self.flush()

            return int(getattr(result, "rowcount", 0) or 0)

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="delete_revoked_tokens",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="delete_revoked_tokens",
                reason=str(exc),
                details={
                    "revoked_before": revoked_before.isoformat()
                    if revoked_before is not None
                    else None,
                },
                cause=exc,
            ) from exc

    async def delete_inactive_tokens(
        self,
        *,
        flush: bool = True,
    ) -> int:
        """Физически удаляет неактивные refresh-токены.

        Args:
            flush: Выполнить ``flush`` после удаления.

        Returns:
            Количество удалённых токенов.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении удаления.
        """

        try:
            result = await self.session.execute(
                delete(RefreshToken).where(
                    RefreshToken.is_active.is_(False),
                ),
            )

            if flush:
                await self.flush()

            return int(getattr(result, "rowcount", 0) or 0)

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="delete_inactive_tokens",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="delete_inactive_tokens",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def delete_user_tokens(
        self,
        user_id: uuid.UUID,
        *,
        flush: bool = True,
    ) -> int:
        """Физически удаляет все refresh-токены пользователя.

        Args:
            user_id: Идентификатор пользователя.
            flush: Выполнить ``flush`` после удаления.

        Returns:
            Количество удалённых токенов.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении удаления.
        """

        try:
            result = await self.session.execute(
                delete(RefreshToken).where(RefreshToken.user_id == user_id),
            )

            if flush:
                await self.flush()

            return int(getattr(result, "rowcount", 0) or 0)

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="delete_user_tokens",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="delete_user_tokens",
                reason=str(exc),
                details={"user_id": str(user_id)},
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Подсчёт
    # ------------------------------------------------------------------

    async def count_user_tokens(
        self,
        user_id: uuid.UUID,
    ) -> int:
        """Возвращает количество refresh-токенов пользователя.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Количество refresh-токенов пользователя.
        """

        return await self.count(RefreshToken.user_id == user_id)

    async def count_active_user_tokens(
        self,
        user_id: uuid.UUID,
        *,
        moment: datetime | None = None,
    ) -> int:
        """Возвращает количество активных refresh-токенов пользователя.

        Args:
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки активности токена.

        Returns:
            Количество активных refresh-токенов пользователя.
        """

        effective_moment = moment or self._utc_now()

        return await self.count(
            RefreshToken.user_id == user_id,
            RefreshToken.is_active.is_(True),
            RefreshToken.status == SessionStatus.ACTIVE,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.replaced_by_token_id.is_(None),
            RefreshToken.expires_at > effective_moment,
        )

    async def count_revoked_user_tokens(
        self,
        user_id: uuid.UUID,
    ) -> int:
        """Возвращает количество отозванных refresh-токенов пользователя.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Количество отозванных refresh-токенов пользователя.
        """

        return await self.count(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_not(None),
        )

    async def get_status_counts(self) -> dict[SessionStatus, int]:
        """Возвращает количество refresh-токенов по каждому статусу.

        Returns:
            Словарь, где ключ — статус токена, значение — количество токенов.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            statement = select(
                RefreshToken.status,
                func.count(RefreshToken.id),
            ).group_by(RefreshToken.status)

            result = await self.session.execute(statement)

            return {status: int(count) for status, count in result.all()}

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_status_counts",
                reason=str(exc),
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

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

    def _normalize_token_hash(
        self,
        token_hash: str,
    ) -> str:
        """Нормализует хэш refresh-токена.

        Метод ожидает уже готовый безопасный хэш токена, а не исходное значение
        refresh-токена. Нормализация удаляет пробелы по краям строки.

        Args:
            token_hash: Хэш refresh-токена.

        Returns:
            Нормализованный хэш refresh-токена.
        """

        return token_hash.strip()

    def _validate_token_hash(
        self,
        token_hash: str,
    ) -> None:
        """Выполняет базовую валидацию хэша refresh-токена.

        Проверяет, что хэш не пустой и не превышает допустимую длину.

        Args:
            token_hash: Хэш refresh-токена.

        Raises:
            InvalidQueryError: Если хэш токена пустой или слишком длинный.
        """

        if not token_hash:
            raise InvalidQueryError(
                "Хэш refresh-токена не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_token_hash",
            )

        if len(token_hash) > 255:
            raise InvalidQueryError(
                "Хэш refresh-токена превышает допустимую длину.",
                repository=self.repository_name,
                operation="_validate_token_hash",
                details={
                    "max_length": 255,
                    "actual_length": len(token_hash),
                },
            )

    def _utc_now(self) -> datetime:
        """Возвращает текущее время в UTC.

        Returns:
            Текущая дата и время с timezone UTC.
        """

        return datetime.now(UTC)
