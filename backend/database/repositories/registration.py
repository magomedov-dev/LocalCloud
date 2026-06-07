from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import RegistrationRequestStatus
from database.models.registration import RegistrationRequest
from database.models.users import User
from database.repositories.base import BaseRepository


class RegistrationRequestsRepository(BaseRepository[RegistrationRequest]):
    """Репозиторий для работы с заявками на регистрацию.

    Инкапсулирует операции создания, поиска, фильтрации, рассмотрения,
    отмены и подсчёта заявок на регистрацию.

    Работает с моделью ``RegistrationRequest`` через асинхронную
    SQLAlchemy-сессию.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий заявок на регистрацию.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=RegistrationRequest)

    # ------------------------------------------------------------------
    # Получение заявки по идентификатору
    # ------------------------------------------------------------------

    async def get_request_by_id(
        self,
        request_id: uuid.UUID,
    ) -> RegistrationRequest | None:
        """Возвращает заявку на регистрацию по идентификатору.

        Args:
            request_id: Идентификатор заявки.

        Returns:
            Заявка на регистрацию, если она найдена, иначе ``None``.
        """

        return await self.get_by_id(request_id)

    async def get_required_request_by_id(
        self,
        request_id: uuid.UUID,
    ) -> RegistrationRequest:
        """Возвращает заявку на регистрацию по идентификатору.

        Args:
            request_id: Идентификатор заявки.

        Returns:
            Найденная заявка на регистрацию.

        Raises:
            EntityNotFoundError: Если заявка не найдена.
        """

        return await self.get_required_by_id(request_id)

    # ------------------------------------------------------------------
    # Поиск по email / username
    # ------------------------------------------------------------------

    async def get_latest_by_email(
        self,
        email: str,
        *,
        case_sensitive: bool = False,
    ) -> RegistrationRequest | None:
        """Возвращает последнюю заявку на регистрацию по email.

        Email предварительно нормализуется. Если заявок несколько, возвращается
        самая новая по дате создания.

        Args:
            email: Email для поиска.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            Последняя заявка с указанным email или ``None``.
        """

        normalized_email = self._normalize_email(email)

        if not normalized_email:
            return None

        statement = select(RegistrationRequest)

        if case_sensitive:
            statement = statement.where(RegistrationRequest.email == normalized_email)
        else:
            statement = statement.where(
                func.lower(RegistrationRequest.email) == normalized_email.lower(),
            )

        statement = statement.order_by(RegistrationRequest.created_at.desc()).limit(1)

        return await self.scalar_one_or_none(
            statement,
            operation="get_latest_by_email",
        )

    async def get_latest_by_username(
        self,
        username: str,
        *,
        case_sensitive: bool = False,
    ) -> RegistrationRequest | None:
        """Возвращает последнюю заявку на регистрацию по username.

        Username предварительно нормализуется. Если заявок несколько,
        возвращается самая новая по дате создания.

        Args:
            username: Username для поиска.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            Последняя заявка с указанным username или ``None``.
        """

        normalized_username = self._normalize_username(username)

        if not normalized_username:
            return None

        statement = select(RegistrationRequest)

        if case_sensitive:
            statement = statement.where(
                RegistrationRequest.username == normalized_username,
            )
        else:
            statement = statement.where(
                func.lower(RegistrationRequest.username) == normalized_username.lower(),
            )

        statement = statement.order_by(RegistrationRequest.created_at.desc()).limit(1)

        return await self.scalar_one_or_none(
            statement,
            operation="get_latest_by_username",
        )

    async def get_pending_by_email(
        self,
        email: str,
        *,
        case_sensitive: bool = False,
    ) -> RegistrationRequest | None:
        """Возвращает ожидающую заявку на регистрацию по email.

        Args:
            email: Email для поиска.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            Ожидающая заявка с указанным email или ``None``.
        """

        normalized_email = self._normalize_email(email)

        if not normalized_email:
            return None

        if case_sensitive:
            email_condition = RegistrationRequest.email == normalized_email
        else:
            email_condition = (
                func.lower(RegistrationRequest.email) == normalized_email.lower()
            )

        statement = select(RegistrationRequest).where(
            email_condition,
            RegistrationRequest.status == RegistrationRequestStatus.PENDING,
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_pending_by_email",
        )

    async def get_pending_by_username(
        self,
        username: str,
        *,
        case_sensitive: bool = False,
    ) -> RegistrationRequest | None:
        """Возвращает ожидающую заявку на регистрацию по username.

        Args:
            username: Username для поиска.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            Ожидающая заявка с указанным username или ``None``.
        """

        normalized_username = self._normalize_username(username)

        if not normalized_username:
            return None

        if case_sensitive:
            username_condition = RegistrationRequest.username == normalized_username
        else:
            username_condition = (
                func.lower(RegistrationRequest.username) == normalized_username.lower()
            )

        statement = select(RegistrationRequest).where(
            username_condition,
            RegistrationRequest.status == RegistrationRequestStatus.PENDING,
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_pending_by_username",
        )

    async def get_pending_by_email_or_username(
        self,
        *,
        email: str,
        username: str,
    ) -> RegistrationRequest | None:
        """Возвращает ожидающую заявку по email или username.

        Метод используется для проверки конфликтов перед созданием новой заявки.

        Args:
            email: Email для поиска.
            username: Username для поиска.

        Returns:
            Ожидающая заявка с указанным email или username либо ``None``.
        """

        normalized_email = self._normalize_email(email)
        normalized_username = self._normalize_username(username)

        statement = select(RegistrationRequest).where(
            RegistrationRequest.status == RegistrationRequestStatus.PENDING,
            or_(
                func.lower(RegistrationRequest.email) == normalized_email.lower(),
                func.lower(RegistrationRequest.username) == normalized_username.lower(),
            ),
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_pending_by_email_or_username",
        )

    async def email_has_pending_request(
        self,
        email: str,
        *,
        case_sensitive: bool = False,
    ) -> bool:
        """Проверяет, существует ли ожидающая заявка с указанным email.

        Args:
            email: Email для проверки.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            ``True``, если ожидающая заявка с таким email существует,
            иначе ``False``.
        """

        normalized_email = self._normalize_email(email)

        if not normalized_email:
            return False

        if case_sensitive:
            email_condition = RegistrationRequest.email == normalized_email
        else:
            email_condition = (
                func.lower(RegistrationRequest.email) == normalized_email.lower()
            )

        return await self.exists(
            email_condition,
            RegistrationRequest.status == RegistrationRequestStatus.PENDING,
        )

    async def username_has_pending_request(
        self,
        username: str,
        *,
        case_sensitive: bool = False,
    ) -> bool:
        """Проверяет, существует ли ожидающая заявка с указанным username.

        Args:
            username: Username для проверки.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            ``True``, если ожидающая заявка с таким username существует,
            иначе ``False``.
        """

        normalized_username = self._normalize_username(username)

        if not normalized_username:
            return False

        if case_sensitive:
            username_condition = RegistrationRequest.username == normalized_username
        else:
            username_condition = (
                func.lower(RegistrationRequest.username) == normalized_username.lower()
            )

        return await self.exists(
            username_condition,
            RegistrationRequest.status == RegistrationRequestStatus.PENDING,
        )

    # ------------------------------------------------------------------
    # Создание заявки
    # ------------------------------------------------------------------

    async def create_request(
        self,
        *,
        email: str,
        username: str,
        password_hash: str,
        status: RegistrationRequestStatus = RegistrationRequestStatus.PENDING,
        comment: str | None = None,
        rejection_reason: str | None = None,
        reviewed_at: datetime | None = None,
        reviewed_by: uuid.UUID | None = None,
        created_user_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_pending_duplicates: bool = True,
        check_created_user_exists: bool = True,
    ) -> RegistrationRequest:
        """Создаёт новую заявку на регистрацию.

        Перед созданием нормализует и валидирует email, username и хэш пароля.
        При необходимости проверяет наличие ожидающих заявок с таким же email
        или username. Если передан ``created_user_id``, может дополнительно
        проверить, что связанный пользователь существует.

        Args:
            email: Email заявителя.
            username: Username заявителя.
            password_hash: Хэш пароля.
            status: Начальный статус заявки.
            comment: Комментарий к заявке.
            rejection_reason: Причина отклонения заявки.
            reviewed_at: Дата рассмотрения заявки.
            reviewed_by: ID пользователя, рассмотревшего заявку.
            created_user_id: ID пользователя, созданного по этой заявке.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_pending_duplicates: Проверять ли дубликаты среди ожидающих
                заявок.
            check_created_user_exists: Проверять ли существование созданного
                пользователя.

        Returns:
            Созданная заявка на регистрацию.

        Raises:
            InvalidQueryError: Если email, username или password_hash некорректны.
            DuplicateEntityError: Если уже существует ожидающая заявка с таким
                email или username.
            EntityNotFoundError: Если ``created_user_id`` передан, но пользователь
                не найден.
        """

        normalized_email = self._normalize_email(email)
        normalized_username = self._normalize_username(username)

        self._validate_email(normalized_email)
        self._validate_username(normalized_username)
        self._validate_password_hash(password_hash)

        if check_pending_duplicates:
            if await self.email_has_pending_request(normalized_email):
                raise DuplicateEntityError(
                    "RegistrationRequest",
                    field="email",
                    value=normalized_email,
                    repository=self.repository_name,
                    message=(
                        "Ожидающая заявка на регистрацию с таким email уже существует."
                    ),
                )

            if await self.username_has_pending_request(normalized_username):
                raise DuplicateEntityError(
                    "RegistrationRequest",
                    field="username",
                    value=normalized_username,
                    repository=self.repository_name,
                    message=(
                        "Ожидающая заявка на регистрацию с таким username "
                        "уже существует."
                    ),
                )

        if created_user_id is not None and check_created_user_exists:
            await self._ensure_user_exists(created_user_id)

        registration_request = RegistrationRequest(
            email=normalized_email,
            username=normalized_username,
            password_hash=password_hash,
            status=status,
            comment=comment.strip() if comment else None,
            rejection_reason=rejection_reason.strip() if rejection_reason else None,
            reviewed_at=reviewed_at,
            reviewed_by=reviewed_by,
            created_user_id=created_user_id,
        )

        try:
            return await self.create(
                registration_request,
                flush=flush,
                refresh=refresh,
            )

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_request",
            ) from exc

    # ------------------------------------------------------------------
    # Списки заявок
    # ------------------------------------------------------------------

    async def list_requests(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        statuses: Sequence[RegistrationRequestStatus] | None = None,
        reviewed_by: uuid.UUID | None = None,
        created_user_id: uuid.UUID | None = None,
        order_by_created_desc: bool = True,
    ) -> list[RegistrationRequest]:
        """Возвращает список заявок на регистрацию с пагинацией и фильтрацией.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            statuses: Список статусов для фильтрации.
            reviewed_by: ID пользователя, рассмотревшего заявку.
            created_user_id: ID пользователя, созданного по заявке.
            order_by_created_desc: Сортировать ли по дате создания по убыванию.

        Returns:
            Список заявок на регистрацию.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = select(RegistrationRequest)
        conditions: list[Any] = []

        if statuses:
            conditions.append(RegistrationRequest.status.in_(list(statuses)))

        if reviewed_by is not None:
            conditions.append(RegistrationRequest.reviewed_by == reviewed_by)

        if created_user_id is not None:
            conditions.append(RegistrationRequest.created_user_id == created_user_id)

        if conditions:
            statement = statement.where(*conditions)

        if order_by_created_desc:
            statement = statement.order_by(RegistrationRequest.created_at.desc())
        else:
            statement = statement.order_by(RegistrationRequest.created_at.asc())

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="list_requests",
        )

    async def list_pending(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by_created_desc: bool = False,
    ) -> list[RegistrationRequest]:
        """Возвращает список ожидающих заявок на регистрацию.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            order_by_created_desc: Сортировать ли по дате создания по убыванию.

        Returns:
            Список заявок со статусом ``PENDING``.
        """

        return await self.list_requests(
            offset=offset,
            limit=limit,
            statuses=[RegistrationRequestStatus.PENDING],
            order_by_created_desc=order_by_created_desc,
        )

    async def list_approved(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[RegistrationRequest]:
        """Возвращает список одобренных заявок.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список заявок со статусом ``APPROVED``.
        """

        return await self.list_by_status(
            RegistrationRequestStatus.APPROVED,
            offset=offset,
            limit=limit,
        )

    async def list_rejected(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[RegistrationRequest]:
        """Возвращает список отклонённых заявок.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список заявок со статусом ``REJECTED``.
        """

        return await self.list_by_status(
            RegistrationRequestStatus.REJECTED,
            offset=offset,
            limit=limit,
        )

    async def list_cancelled(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[RegistrationRequest]:
        """Возвращает список отменённых заявок.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список заявок со статусом ``CANCELLED``.
        """

        return await self.list_by_status(
            RegistrationRequestStatus.CANCELLED,
            offset=offset,
            limit=limit,
        )

    async def list_reviewed(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by_reviewed_desc: bool = True,
    ) -> list[RegistrationRequest]:
        """Возвращает список рассмотренных заявок.

        Рассмотренными считаются заявки со статусами ``APPROVED``,
        ``REJECTED`` и ``CANCELLED``.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            order_by_reviewed_desc: Сортировать ли по дате рассмотрения
                по убыванию.

        Returns:
            Список рассмотренных заявок.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = select(RegistrationRequest).where(
            RegistrationRequest.status.in_(
                [
                    RegistrationRequestStatus.APPROVED,
                    RegistrationRequestStatus.REJECTED,
                    RegistrationRequestStatus.CANCELLED,
                ],
            ),
        )

        if order_by_reviewed_desc:
            statement = statement.order_by(
                RegistrationRequest.reviewed_at.desc().nullslast(),
                RegistrationRequest.created_at.desc(),
            )
        else:
            statement = statement.order_by(
                RegistrationRequest.reviewed_at.asc().nullslast(),
                RegistrationRequest.created_at.asc(),
            )

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="list_reviewed",
        )

    async def list_by_status(
        self,
        status: RegistrationRequestStatus,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by_created_desc: bool = True,
    ) -> list[RegistrationRequest]:
        """Возвращает список заявок с указанным статусом.

        Args:
            status: Статус заявок.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            order_by_created_desc: Сортировать ли по дате создания по убыванию.

        Returns:
            Список заявок с указанным статусом.
        """

        return await self.list_requests(
            offset=offset,
            limit=limit,
            statuses=[status],
            order_by_created_desc=order_by_created_desc,
        )

    async def search_requests(
        self,
        query: str,
        *,
        offset: int = 0,
        limit: int = 100,
        statuses: Sequence[RegistrationRequestStatus] | None = None,
    ) -> list[RegistrationRequest]:
        """Выполняет поиск заявок по email или username.

        Поиск выполняется по частичному совпадению без учёта регистра.

        Args:
            query: Поисковая строка.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            statuses: Список статусов для фильтрации.

        Returns:
            Список найденных заявок.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        normalized_query = query.strip()

        statement = select(RegistrationRequest)
        conditions: list[Any] = []

        if normalized_query:
            pattern = f"%{normalized_query}%"
            conditions.append(
                or_(
                    RegistrationRequest.email.ilike(pattern),
                    RegistrationRequest.username.ilike(pattern),
                ),
            )

        if statuses:
            conditions.append(RegistrationRequest.status.in_(list(statuses)))

        if conditions:
            statement = statement.where(*conditions)

        statement = (
            statement.order_by(RegistrationRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="search_requests",
        )

    # ------------------------------------------------------------------
    # Изменение статуса заявки
    # ------------------------------------------------------------------

    async def approve_request(
        self,
        registration_request: RegistrationRequest,
        *,
        reviewed_by: uuid.UUID,
        created_user_id: uuid.UUID,
        comment: str | None = None,
        reviewed_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
        require_pending: bool = True,
    ) -> RegistrationRequest:
        """Одобряет заявку на регистрацию.

        При необходимости проверяет, что заявка находится в статусе,
        допускающем рассмотрение, и что пользователь, созданный по заявке,
        существует.

        Args:
            registration_request: Заявка на регистрацию.
            reviewed_by: ID пользователя, который одобряет заявку.
            created_user_id: ID пользователя, созданного по этой заявке.
            comment: Комментарий к рассмотрению заявки.
            reviewed_at: Дата рассмотрения. Если не передана, используется
                текущее UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            check_user_exists: Проверять ли существование созданного пользователя.
            require_pending: Требовать ли, чтобы заявка могла быть рассмотрена.

        Returns:
            Обновлённая заявка.

        Raises:
            InvalidQueryError: Если заявка уже была рассмотрена.
            EntityNotFoundError: Если пользователь ``created_user_id`` не найден.
        """

        if require_pending:
            self._ensure_request_can_be_reviewed(registration_request)

        if check_user_exists:
            await self._ensure_user_exists(created_user_id)

        registration_request.approve(
            reviewer_id=reviewed_by,
            created_user_id=created_user_id,
            comment=comment.strip() if comment else None,
            reviewed_at=reviewed_at or self._utc_now(),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(registration_request)

        return registration_request

    async def approve_request_by_id(
        self,
        request_id: uuid.UUID,
        *,
        reviewed_by: uuid.UUID,
        created_user_id: uuid.UUID,
        comment: str | None = None,
        reviewed_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
        require_pending: bool = True,
    ) -> RegistrationRequest:
        """Одобряет заявку на регистрацию по идентификатору.

        Args:
            request_id: Идентификатор заявки.
            reviewed_by: ID пользователя, который одобряет заявку.
            created_user_id: ID пользователя, созданного по этой заявке.
            comment: Комментарий к рассмотрению заявки.
            reviewed_at: Дата рассмотрения.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            check_user_exists: Проверять ли существование созданного пользователя.
            require_pending: Требовать ли, чтобы заявка могла быть рассмотрена.

        Returns:
            Обновлённая заявка.

        Raises:
            EntityNotFoundError: Если заявка или созданный пользователь не найдены.
            InvalidQueryError: Если заявка уже была рассмотрена.
        """

        registration_request = await self.get_required_by_id(request_id)

        return await self.approve_request(
            registration_request,
            reviewed_by=reviewed_by,
            created_user_id=created_user_id,
            comment=comment,
            reviewed_at=reviewed_at,
            flush=flush,
            refresh=refresh,
            check_user_exists=check_user_exists,
            require_pending=require_pending,
        )

    async def reject_request(
        self,
        registration_request: RegistrationRequest,
        *,
        reviewed_by: uuid.UUID,
        reason: str | None = None,
        comment: str | None = None,
        reviewed_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
        require_pending: bool = True,
    ) -> RegistrationRequest:
        """Отклоняет заявку на регистрацию.

        Args:
            registration_request: Заявка на регистрацию.
            reviewed_by: ID пользователя, который отклоняет заявку.
            reason: Причина отклонения.
            comment: Комментарий к рассмотрению заявки.
            reviewed_at: Дата рассмотрения. Если не передана, используется
                текущее UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            require_pending: Требовать ли, чтобы заявка могла быть рассмотрена.

        Returns:
            Обновлённая заявка.

        Raises:
            InvalidQueryError: Если заявка уже была рассмотрена.
        """

        if require_pending:
            self._ensure_request_can_be_reviewed(registration_request)

        registration_request.reject(
            reviewer_id=reviewed_by,
            reason=reason.strip() if reason else None,
            comment=comment.strip() if comment else None,
            reviewed_at=reviewed_at or self._utc_now(),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(registration_request)

        return registration_request

    async def reject_request_by_id(
        self,
        request_id: uuid.UUID,
        *,
        reviewed_by: uuid.UUID,
        reason: str | None = None,
        comment: str | None = None,
        reviewed_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
        require_pending: bool = True,
    ) -> RegistrationRequest:
        """Отклоняет заявку на регистрацию по идентификатору.

        Args:
            request_id: Идентификатор заявки.
            reviewed_by: ID пользователя, который отклоняет заявку.
            reason: Причина отклонения.
            comment: Комментарий к рассмотрению заявки.
            reviewed_at: Дата рассмотрения.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            require_pending: Требовать ли, чтобы заявка могла быть рассмотрена.

        Returns:
            Обновлённая заявка.

        Raises:
            EntityNotFoundError: Если заявка не найдена.
            InvalidQueryError: Если заявка уже была рассмотрена.
        """

        registration_request = await self.get_required_by_id(request_id)

        return await self.reject_request(
            registration_request,
            reviewed_by=reviewed_by,
            reason=reason,
            comment=comment,
            reviewed_at=reviewed_at,
            flush=flush,
            refresh=refresh,
            require_pending=require_pending,
        )

    async def cancel_request(
        self,
        registration_request: RegistrationRequest,
        *,
        comment: str | None = None,
        cancelled_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
        require_pending: bool = False,
    ) -> RegistrationRequest:
        """Отменяет заявку на регистрацию.

        Args:
            registration_request: Заявка на регистрацию.
            comment: Комментарий к отмене заявки.
            cancelled_at: Дата отмены. Если не передана, используется текущее
                UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            require_pending: Требовать ли, чтобы заявка могла быть рассмотрена.

        Returns:
            Обновлённая заявка.

        Raises:
            InvalidQueryError: Если включена проверка ``require_pending`` и заявка
                уже была рассмотрена.
        """

        if require_pending:
            self._ensure_request_can_be_reviewed(registration_request)

        registration_request.cancel(
            comment=comment.strip() if comment else None,
            cancelled_at=cancelled_at or self._utc_now(),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(registration_request)

        return registration_request

    async def cancel_request_by_id(
        self,
        request_id: uuid.UUID,
        *,
        comment: str | None = None,
        cancelled_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
        require_pending: bool = False,
    ) -> RegistrationRequest:
        """Отменяет заявку на регистрацию по идентификатору.

        Args:
            request_id: Идентификатор заявки.
            comment: Комментарий к отмене заявки.
            cancelled_at: Дата отмены.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            require_pending: Требовать ли, чтобы заявка могла быть рассмотрена.

        Returns:
            Обновлённая заявка.

        Raises:
            EntityNotFoundError: Если заявка не найдена.
            InvalidQueryError: Если включена проверка ``require_pending`` и заявка
                уже была рассмотрена.
        """

        registration_request = await self.get_required_by_id(request_id)

        return await self.cancel_request(
            registration_request,
            comment=comment,
            cancelled_at=cancelled_at,
            flush=flush,
            refresh=refresh,
            require_pending=require_pending,
        )

    async def reset_to_pending(
        self,
        registration_request: RegistrationRequest,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> RegistrationRequest:
        """Сбрасывает заявку обратно в статус ``PENDING``.

        Args:
            registration_request: Заявка на регистрацию.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая заявка.
        """

        registration_request.reset_to_pending()

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(registration_request)

        return registration_request

    async def reset_to_pending_by_id(
        self,
        request_id: uuid.UUID,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> RegistrationRequest:
        """Сбрасывает заявку обратно в статус ``PENDING`` по идентификатору.

        Args:
            request_id: Идентификатор заявки.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая заявка.

        Raises:
            EntityNotFoundError: Если заявка не найдена.
        """

        registration_request = await self.get_required_by_id(request_id)

        return await self.reset_to_pending(
            registration_request,
            flush=flush,
            refresh=refresh,
        )

    async def set_created_user(
        self,
        registration_request: RegistrationRequest,
        *,
        created_user_id: uuid.UUID,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
    ) -> RegistrationRequest:
        """Связывает заявку с созданным пользователем.

        При необходимости проверяет, что пользователь существует.

        Args:
            registration_request: Заявка на регистрацию.
            created_user_id: ID созданного пользователя.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            check_user_exists: Проверять ли существование пользователя.

        Returns:
            Обновлённая заявка.

        Raises:
            EntityNotFoundError: Если пользователь не найден.
        """

        if check_user_exists:
            await self._ensure_user_exists(created_user_id)

        registration_request.created_user_id = created_user_id

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(registration_request)

        return registration_request

    async def set_created_user_by_id(
        self,
        request_id: uuid.UUID,
        *,
        created_user_id: uuid.UUID,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
    ) -> RegistrationRequest:
        """Связывает заявку с созданным пользователем по идентификатору заявки.

        Args:
            request_id: Идентификатор заявки.
            created_user_id: ID созданного пользователя.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            check_user_exists: Проверять ли существование пользователя.

        Returns:
            Обновлённая заявка.

        Raises:
            EntityNotFoundError: Если заявка или пользователь не найдены.
        """

        registration_request = await self.get_required_by_id(request_id)

        return await self.set_created_user(
            registration_request,
            created_user_id=created_user_id,
            flush=flush,
            refresh=refresh,
            check_user_exists=check_user_exists,
        )

    # ------------------------------------------------------------------
    # Подсчёт
    # ------------------------------------------------------------------

    async def count_by_status(
        self,
        status: RegistrationRequestStatus,
    ) -> int:
        """Возвращает количество заявок с указанным статусом.

        Args:
            status: Статус заявок.

        Returns:
            Количество заявок с указанным статусом.
        """

        return await self.count(RegistrationRequest.status == status)

    async def count_pending(self) -> int:
        """Возвращает количество ожидающих заявок.

        Returns:
            Количество заявок со статусом ``PENDING``.
        """

        return await self.count_by_status(RegistrationRequestStatus.PENDING)

    async def count_reviewed(self) -> int:
        """Возвращает количество рассмотренных заявок.

        Рассмотренными считаются заявки со статусами ``APPROVED``,
        ``REJECTED`` и ``CANCELLED``.

        Returns:
            Количество рассмотренных заявок.
        """

        return await self.count(
            RegistrationRequest.status.in_(
                [
                    RegistrationRequestStatus.APPROVED,
                    RegistrationRequestStatus.REJECTED,
                    RegistrationRequestStatus.CANCELLED,
                ],
            ),
        )

    async def get_status_counts(self) -> dict[RegistrationRequestStatus, int]:
        """Возвращает количество заявок по каждому статусу.

        Returns:
            Словарь, где ключ — статус заявки, значение — количество заявок.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            statement = select(
                RegistrationRequest.status,
                func.count(RegistrationRequest.id),
            ).group_by(RegistrationRequest.status)

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

    def _base_select(self) -> Select[tuple[RegistrationRequest]]:
        """Создаёт базовый ``SELECT``-запрос для модели ``RegistrationRequest``.

        Returns:
            SQLAlchemy ``SELECT``-запрос для выборки заявок на регистрацию.
        """

        return select(RegistrationRequest)

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

    def _ensure_request_can_be_reviewed(
        self,
        registration_request: RegistrationRequest,
    ) -> None:
        """Проверяет, что заявка может быть рассмотрена.

        Args:
            registration_request: Заявка на регистрацию.

        Raises:
            InvalidQueryError: Если заявка уже была рассмотрена.
        """

        if not registration_request.can_be_reviewed:
            raise InvalidQueryError(
                "Заявка на регистрацию уже была рассмотрена.",
                repository=self.repository_name,
                operation="_ensure_request_can_be_reviewed",
                details={
                    "request_id": str(registration_request.id),
                    "status": registration_request.status.value,
                },
            )

    def _normalize_email(
        self,
        email: str,
    ) -> str:
        """Нормализует email.

        Удаляет пробелы по краям строки и приводит email к нижнему регистру.

        Args:
            email: Email для нормализации.

        Returns:
            Нормализованный email.
        """

        return email.strip().lower()

    def _normalize_username(
        self,
        username: str,
    ) -> str:
        """Нормализует username.

        Удаляет пробелы по краям строки. Регистр символов не изменяется.

        Args:
            username: Username для нормализации.

        Returns:
            Нормализованный username.
        """

        return username.strip()

    def _validate_email(
        self,
        email: str,
    ) -> None:
        """Выполняет базовую валидацию email заявки.

        Проверяет, что email не пустой, не превышает допустимую длину
        и содержит символ ``@``.

        Args:
            email: Email для проверки.

        Raises:
            InvalidQueryError: Если email пустой, слишком длинный или имеет
                неверный формат.
        """

        if not email:
            raise InvalidQueryError(
                "Email заявки на регистрацию не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_email",
            )

        if len(email) > 320:
            raise InvalidQueryError(
                "Email заявки на регистрацию превышает допустимую длину.",
                repository=self.repository_name,
                operation="_validate_email",
                details={
                    "max_length": 320,
                    "actual_length": len(email),
                },
            )

        if "@" not in email:
            raise InvalidQueryError(
                "Email заявки на регистрацию имеет недопустимый формат.",
                repository=self.repository_name,
                operation="_validate_email",
                details={"email": email},
            )

    def _validate_username(
        self,
        username: str,
    ) -> None:
        """Выполняет базовую валидацию username заявки.

        Проверяет, что username не пустой и не превышает допустимую длину.

        Args:
            username: Username для проверки.

        Raises:
            InvalidQueryError: Если username пустой или слишком длинный.
        """

        if not username:
            raise InvalidQueryError(
                "Username заявки на регистрацию не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_username",
            )

        if len(username) > 64:
            raise InvalidQueryError(
                "Username заявки на регистрацию превышает допустимую длину.",
                repository=self.repository_name,
                operation="_validate_username",
                details={
                    "max_length": 64,
                    "actual_length": len(username),
                },
            )

    def _validate_password_hash(
        self,
        password_hash: str,
    ) -> None:
        """Проверяет хэш пароля заявки.

        Args:
            password_hash: Хэш пароля для проверки.

        Raises:
            InvalidQueryError: Если хэш пароля пустой или превышает допустимую
                длину.
        """

        if not password_hash or not password_hash.strip():
            raise InvalidQueryError(
                "Хэш пароля заявки на регистрацию не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_password_hash",
            )

        if len(password_hash) > 255:
            raise InvalidQueryError(
                "Хэш пароля заявки на регистрацию превышает допустимую длину.",
                repository=self.repository_name,
                operation="_validate_password_hash",
                details={
                    "max_length": 255,
                    "actual_length": len(password_hash),
                },
            )

    def _utc_now(self) -> datetime:
        """Возвращает текущее время в UTC.

        Returns:
            Текущая дата и время с timezone UTC.
        """

        return datetime.now(UTC)
