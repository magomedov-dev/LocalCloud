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
from database.models.enums import UserStatus
from database.models.users import User
from database.repositories.base import BaseRepository


class UsersRepository(BaseRepository[User]):
    """Репозиторий для работы с пользователями.

    Инкапсулирует операции чтения, поиска, создания, обновления, изменения
    статусов и подсчёта пользователей.

    Репозиторий работает с моделью ``User`` через асинхронную SQLAlchemy-сессию
    и предоставляет прикладные методы, специфичные для пользовательской
    сущности: поиск по ``email`` и ``username``, проверку уникальности,
    логическое удаление, блокировку, подтверждение email и обновление
    аутентификационных данных.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя, Unit of Work или другого внешнего механизма
    управления транзакциями.

    Args:
        session: Асинхронная SQLAlchemy-сессия, используемая для выполнения
            запросов и управления состоянием ORM-объектов.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий пользователей.

        Args:
            session: Асинхронная SQLAlchemy-сессия, через которую будут
                выполняться операции с моделью ``User``.
        """

        super().__init__(session=session, model=User)

    # ------------------------------------------------------------------
    # Получение пользователя по идентификатору
    # ------------------------------------------------------------------

    async def get_user_by_id(
        self,
        user_id: uuid.UUID,
    ) -> User | None:
        """Возвращает пользователя по идентификатору.

        Выполняет поиск пользователя по первичному ключу. Если пользователь
        отсутствует в базе данных, возвращает ``None`` и не выбрасывает
        исключение.

        Args:
            user_id: Уникальный идентификатор пользователя.

        Returns:
            Экземпляр ``User``, если пользователь найден, иначе ``None``.
        """

        return await self.get_by_id(user_id)

    async def get_required_user_by_id(
        self,
        user_id: uuid.UUID,
    ) -> User:
        """Возвращает пользователя по идентификатору или выбрасывает исключение.

        Метод предназначен для сценариев, где отсутствие пользователя считается
        ошибкой бизнес-логики.

        Args:
            user_id: Уникальный идентификатор пользователя.

        Returns:
            Найденный экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
        """

        return await self.get_required_by_id(user_id)

    async def get_active_user_by_id(
        self,
        user_id: uuid.UUID,
    ) -> User | None:
        """Возвращает активного пользователя по идентификатору.

        Пользователь считается активным, если его статус равен
        ``UserStatus.ACTIVE``.

        Args:
            user_id: Уникальный идентификатор пользователя.

        Returns:
            Активный экземпляр ``User``, если он найден, иначе ``None``.
        """

        statement = select(User).where(
            User.id == user_id,
            User.status == UserStatus.ACTIVE,
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_active_user_by_id",
        )

    async def get_required_active_user_by_id(
        self,
        user_id: uuid.UUID,
    ) -> User:
        """Возвращает активного пользователя по идентификатору.

        Метод выбрасывает исключение, если пользователь отсутствует или имеет
        статус, отличный от ``UserStatus.ACTIVE``.

        Args:
            user_id: Уникальный идентификатор пользователя.

        Returns:
            Активный экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если активный пользователь с указанным
                идентификатором не найден.
        """

        user = await self.get_active_user_by_id(user_id)

        if user is None:
            raise EntityNotFoundError(
                "User",
                entity_id=user_id,
                repository=self.repository_name,
                message="Активный пользователь не найден.",
            )

        return user

    # ------------------------------------------------------------------
    # Поиск по email
    # ------------------------------------------------------------------

    async def get_by_email(
        self,
        email: str,
        *,
        case_sensitive: bool = False,
        include_deleted: bool = True,
    ) -> User | None:
        """Возвращает пользователя по email.

        Перед поиском email нормализуется: удаляются пробелы по краям строки,
        значение приводится к нижнему регистру. Если после нормализации email
        пустой, метод возвращает ``None``.

        Args:
            email: Email пользователя.
            case_sensitive: Учитывать ли регистр при сравнении. Если ``False``,
                сравнение выполняется без учёта регистра.
            include_deleted: Включать ли в поиск пользователей со статусом
                ``UserStatus.DELETED``.

        Returns:
            Экземпляр ``User``, если пользователь найден, иначе ``None``.
        """

        normalized_email = self._normalize_email(email)

        if not normalized_email:
            return None

        statement = select(User)

        if case_sensitive:
            statement = statement.where(User.email == normalized_email)
        else:
            statement = statement.where(
                func.lower(User.email) == normalized_email.lower(),
            )

        if not include_deleted:
            statement = statement.where(User.status != UserStatus.DELETED)

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_email",
        )

    async def get_required_by_email(
        self,
        email: str,
        *,
        case_sensitive: bool = False,
        include_deleted: bool = True,
    ) -> User:
        """Возвращает пользователя по email или выбрасывает исключение.

        Используется в сценариях, где пользователь с указанным email должен
        существовать.

        Args:
            email: Email пользователя.
            case_sensitive: Учитывать ли регистр при сравнении.
            include_deleted: Включать ли в поиск пользователей со статусом
                ``UserStatus.DELETED``.

        Returns:
            Найденный экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным email не найден.
        """

        user = await self.get_by_email(
            email,
            case_sensitive=case_sensitive,
            include_deleted=include_deleted,
        )

        if user is None:
            raise EntityNotFoundError(
                "User",
                lookup={"email": email},
                repository=self.repository_name,
            )

        return user

    async def get_active_by_email(
        self,
        email: str,
        *,
        case_sensitive: bool = False,
    ) -> User | None:
        """Возвращает активного пользователя по email.

        Поиск ограничивается пользователями со статусом ``UserStatus.ACTIVE``.
        Email предварительно нормализуется.

        Args:
            email: Email пользователя.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            Активный экземпляр ``User``, если пользователь найден, иначе
            ``None``.
        """

        normalized_email = self._normalize_email(email)

        if not normalized_email:
            return None

        statement = select(User).where(User.status == UserStatus.ACTIVE)

        if case_sensitive:
            statement = statement.where(User.email == normalized_email)
        else:
            statement = statement.where(
                func.lower(User.email) == normalized_email.lower(),
            )

        return await self.scalar_one_or_none(
            statement,
            operation="get_active_by_email",
        )

    async def email_exists(
        self,
        email: str,
        *,
        exclude_user_id: uuid.UUID | None = None,
        include_deleted: bool = True,
        case_sensitive: bool = False,
    ) -> bool:
        """Проверяет существование пользователя с указанным email.

        Метод полезен при создании пользователя или обновлении email, когда
        необходимо проверить уникальность значения.

        Args:
            email: Email для проверки.
            exclude_user_id: Идентификатор пользователя, которого нужно
                исключить из проверки. Обычно используется при обновлении
                собственного email пользователя.
            include_deleted: Учитывать ли пользователей со статусом
                ``UserStatus.DELETED``.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            ``True``, если пользователь с таким email существует, иначе
            ``False``.
        """

        normalized_email = self._normalize_email(email)

        if not normalized_email:
            return False

        if case_sensitive:
            conditions: list[Any] = [User.email == normalized_email]
        else:
            conditions = [func.lower(User.email) == normalized_email.lower()]

        if exclude_user_id is not None:
            conditions.append(User.id != exclude_user_id)

        if not include_deleted:
            conditions.append(User.status != UserStatus.DELETED)

        return await self.exists(*conditions)

    # ------------------------------------------------------------------
    # Поиск по username
    # ------------------------------------------------------------------

    async def get_by_username(
        self,
        username: str,
        *,
        case_sensitive: bool = False,
        include_deleted: bool = True,
    ) -> User | None:
        """Возвращает пользователя по username.

        Перед поиском username нормализуется: удаляются пробелы по краям
        строки. Регистр символов при нормализации не изменяется.

        Args:
            username: Username пользователя.
            case_sensitive: Учитывать ли регистр при сравнении.
            include_deleted: Включать ли в поиск пользователей со статусом
                ``UserStatus.DELETED``.

        Returns:
            Экземпляр ``User``, если пользователь найден, иначе ``None``.
        """

        normalized_username = self._normalize_username(username)

        if not normalized_username:
            return None

        statement = select(User)

        if case_sensitive:
            statement = statement.where(User.username == normalized_username)
        else:
            statement = statement.where(
                func.lower(User.username) == normalized_username.lower(),
            )

        if not include_deleted:
            statement = statement.where(User.status != UserStatus.DELETED)

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_username",
        )

    async def get_required_by_username(
        self,
        username: str,
        *,
        case_sensitive: bool = False,
        include_deleted: bool = True,
    ) -> User:
        """Возвращает пользователя по username или выбрасывает исключение.

        Args:
            username: Username пользователя.
            case_sensitive: Учитывать ли регистр при сравнении.
            include_deleted: Включать ли в поиск пользователей со статусом
                ``UserStatus.DELETED``.

        Returns:
            Найденный экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным username
                не найден.
        """

        user = await self.get_by_username(
            username,
            case_sensitive=case_sensitive,
            include_deleted=include_deleted,
        )

        if user is None:
            raise EntityNotFoundError(
                "User",
                lookup={"username": username},
                repository=self.repository_name,
            )

        return user

    async def get_active_by_username(
        self,
        username: str,
        *,
        case_sensitive: bool = False,
    ) -> User | None:
        """Возвращает активного пользователя по username.

        Поиск ограничивается пользователями со статусом ``UserStatus.ACTIVE``.

        Args:
            username: Username пользователя.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            Активный экземпляр ``User``, если пользователь найден, иначе
            ``None``.
        """

        normalized_username = self._normalize_username(username)

        if not normalized_username:
            return None

        statement = select(User).where(User.status == UserStatus.ACTIVE)

        if case_sensitive:
            statement = statement.where(User.username == normalized_username)
        else:
            statement = statement.where(
                func.lower(User.username) == normalized_username.lower(),
            )

        return await self.scalar_one_or_none(
            statement,
            operation="get_active_by_username",
        )

    async def username_exists(
        self,
        username: str,
        *,
        exclude_user_id: uuid.UUID | None = None,
        include_deleted: bool = True,
        case_sensitive: bool = False,
    ) -> bool:
        """Проверяет существование пользователя с указанным username.

        Метод используется для проверки уникальности username при создании
        пользователя или изменении идентификационных данных.

        Args:
            username: Username для проверки.
            exclude_user_id: Идентификатор пользователя, которого нужно
                исключить из проверки.
            include_deleted: Учитывать ли пользователей со статусом
                ``UserStatus.DELETED``.
            case_sensitive: Учитывать ли регистр при сравнении.

        Returns:
            ``True``, если пользователь с таким username существует, иначе
            ``False``.
        """

        normalized_username = self._normalize_username(username)

        if not normalized_username:
            return False

        if case_sensitive:
            conditions: list[Any] = [User.username == normalized_username]
        else:
            conditions = [
                func.lower(User.username) == normalized_username.lower(),
            ]

        if exclude_user_id is not None:
            conditions.append(User.id != exclude_user_id)

        if not include_deleted:
            conditions.append(User.status != UserStatus.DELETED)

        return await self.exists(*conditions)

    # ------------------------------------------------------------------
    # Создание пользователя
    # ------------------------------------------------------------------

    async def create_user(
        self,
        *,
        email: str,
        username: str,
        password_hash: str,
        status: UserStatus = UserStatus.PENDING,
        approved_at: datetime | None = None,
        blocked_at: datetime | None = None,
        rejected_at: datetime | None = None,
        deleted_at: datetime | None = None,
        block_reason: str | None = None,
        rejection_reason: str | None = None,
        last_login_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_duplicates: bool = True,
    ) -> User:
        """Создаёт нового пользователя.

        Перед созданием метод нормализует и валидирует ``email``, ``username``
        и ``password_hash``. При включённой проверке дубликатов дополнительно
        проверяет уникальность email и username.

        Метод добавляет пользователя в текущую сессию и при необходимости
        выполняет ``flush`` и ``refresh``. Фиксация транзакции через ``commit``
        здесь не выполняется.

        Args:
            email: Email пользователя.
            username: Username пользователя.
            password_hash: Хэш пароля пользователя.
            status: Начальный статус пользователя.
            approved_at: Дата и время подтверждения пользователя.
            blocked_at: Дата и время блокировки пользователя.
            rejected_at: Дата и время отклонения пользователя.
            deleted_at: Дата и время логического удаления пользователя.
            block_reason: Причина блокировки. Если передана непустая строка,
                пробелы по краям будут удалены.
            rejection_reason: Причина отклонения. Если передана непустая
                строка, пробелы по краям будут удалены.
            last_login_at: Дата и время последнего успешного входа.
            flush: Выполнить ли ``flush`` после добавления пользователя
                в сессию.
            refresh: Выполнить ли ``refresh`` после создания пользователя.
            check_duplicates: Проверять ли уникальность email и username перед
                созданием.

        Returns:
            Созданный экземпляр ``User``.

        Raises:
            InvalidQueryError: Если email, username или password_hash
                некорректны.
            DuplicateEntityError: Если email или username уже используются.
        """

        normalized_email = self._normalize_email(email)
        normalized_username = self._normalize_username(username)

        self._validate_email(normalized_email)
        self._validate_username(normalized_username)
        self._validate_password_hash(password_hash)

        if check_duplicates:
            if await self.email_exists(normalized_email):
                raise DuplicateEntityError(
                    "User",
                    field="email",
                    value=normalized_email,
                    repository=self.repository_name,
                )

            if await self.username_exists(normalized_username):
                raise DuplicateEntityError(
                    "User",
                    field="username",
                    value=normalized_username,
                    repository=self.repository_name,
                )

        user = User(
            email=normalized_email,
            username=normalized_username,
            password_hash=password_hash,
            status=status,
            approved_at=approved_at,
            blocked_at=blocked_at,
            rejected_at=rejected_at,
            deleted_at=deleted_at,
            block_reason=block_reason.strip() if block_reason else None,
            rejection_reason=rejection_reason.strip() if rejection_reason else None,
            last_login_at=last_login_at,
        )

        try:
            return await self.create(
                user,
                flush=flush,
                refresh=refresh,
            )

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_user",
            ) from exc

    # ------------------------------------------------------------------
    # Списки и фильтрация
    # ------------------------------------------------------------------

    async def list_users(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        statuses: Sequence[UserStatus] | None = None,
        include_deleted: bool = False,
        order_by_created_desc: bool = True,
    ) -> list[User]:
        """Возвращает список пользователей с пагинацией и фильтрацией.

        Позволяет фильтровать пользователей по статусам и признаку логического
        удаления. Результат сортируется по дате создания.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей, которое нужно вернуть.
            statuses: Последовательность статусов для фильтрации. Если не
                передана, фильтр по статусу не применяется.
            include_deleted: Включать ли пользователей со статусом
                ``UserStatus.DELETED``.
            order_by_created_desc: Сортировать ли пользователей по дате создания
                по убыванию. Если ``False``, используется сортировка по
                возрастанию.

        Returns:
            Список экземпляров ``User``.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = select(User)
        conditions: list[Any] = []

        if statuses:
            conditions.append(User.status.in_(list(statuses)))

        if not include_deleted:
            conditions.append(User.status != UserStatus.DELETED)

        if conditions:
            statement = statement.where(*conditions)

        if order_by_created_desc:
            statement = statement.order_by(User.created_at.desc())
        else:
            statement = statement.order_by(User.created_at.asc())

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="list_users",
        )

    async def list_active_users(
        self,
        *,
        limit: int = 100,
        after_id: uuid.UUID | None = None,
    ) -> list[User]:
        """Возвращает страницу активных пользователей keyset-пагинацией.

        Метод предназначен для пакетных проходов worker-процесса (пересчёт
        квот). Используется keyset-пагинация по первичному ключу: страница не
        зависит от ``OFFSET`` и не требует подсчёта общего количества записей,
        поэтому стоимость выборки не растёт с глубиной обхода. Для обхода всех
        пользователей повторно вызывайте метод, передавая ``after_id`` равным
        идентификатору последнего обработанного пользователя.

        Args:
            limit: Максимальный размер страницы.
            after_id: Идентификатор-курсор. Возвращаются пользователи с
                идентификатором строго больше указанного. Если ``None``,
                возвращается первая страница.

        Returns:
            Список активных пользователей, отсортированный по идентификатору.

        Raises:
            InvalidPaginationError: Если ``limit`` некорректен.
        """

        return await self.list_keyset(
            limit=limit,
            after=after_id,
            conditions=[User.status == UserStatus.ACTIVE],
        )

    async def list_by_status(
        self,
        status: UserStatus,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by_created_desc: bool = True,
    ) -> list[User]:
        """Возвращает пользователей с указанным статусом.

        Args:
            status: Статус пользователей, по которому выполняется фильтрация.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей, которое нужно вернуть.
            order_by_created_desc: Сортировать ли пользователей по дате создания
                по убыванию.

        Returns:
            Список пользователей с указанным статусом.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        return await self.list_users(
            offset=offset,
            limit=limit,
            statuses=[status],
            include_deleted=True,
            order_by_created_desc=order_by_created_desc,
        )

    async def list_pending_users(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[User]:
        """Возвращает пользователей, ожидающих подтверждения.

        Результат сортируется по дате создания по возрастанию, чтобы первыми
        возвращались пользователи, которые ожидают подтверждения дольше всего.

        Args:
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей, которое нужно вернуть.

        Returns:
            Список пользователей со статусом ``UserStatus.PENDING``.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        return await self.list_by_status(
            UserStatus.PENDING,
            offset=offset,
            limit=limit,
            order_by_created_desc=False,
        )

    async def search_users(
        self,
        query: str,
        *,
        offset: int = 0,
        limit: int = 100,
        statuses: Sequence[UserStatus] | None = None,
        include_deleted: bool = False,
    ) -> list[User]:
        """Выполняет поиск пользователей по email или username.

        Поиск выполняется по частичному совпадению без учёта регистра.
        Дополнительно можно ограничить результат статусами и исключить
        логически удалённых пользователей.

        Если поисковая строка после удаления пробелов по краям оказывается
        пустой, метод возвращает пользователей только по дополнительным
        фильтрам.

        Args:
            query: Поисковая строка.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей, которое нужно вернуть.
            statuses: Последовательность статусов для фильтрации.
            include_deleted: Включать ли пользователей со статусом
                ``UserStatus.DELETED``.

        Returns:
            Список найденных пользователей.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        normalized_query = query.strip()

        statement = select(User)
        conditions: list[Any] = []

        if normalized_query:
            pattern = f"%{normalized_query}%"
            conditions.append(
                or_(
                    User.email.ilike(pattern),
                    User.username.ilike(pattern),
                ),
            )

        if statuses:
            conditions.append(User.status.in_(list(statuses)))

        if not include_deleted:
            conditions.append(User.status != UserStatus.DELETED)

        if conditions:
            statement = statement.where(*conditions)

        statement = (
            statement.order_by(User.created_at.desc()).offset(offset).limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="search_users",
        )

    async def find_by_email_or_username(
        self,
        value: str,
        *,
        include_deleted: bool = False,
    ) -> User | None:
        """Ищет пользователя по email или username.

        Метод предназначен для сценариев авторизации, где пользователь может
        указать email или username в одном поле ввода. Сравнение выполняется
        без учёта регистра.

        Args:
            value: Email или username пользователя.
            include_deleted: Включать ли в поиск пользователей со статусом
                ``UserStatus.DELETED``.

        Returns:
            Найденный экземпляр ``User`` или ``None``.
        """

        normalized_value = value.strip()

        if not normalized_value:
            return None

        statement = select(User).where(
            or_(
                func.lower(User.email) == normalized_value.lower(),
                func.lower(User.username) == normalized_value.lower(),
            ),
        )

        if not include_deleted:
            statement = statement.where(User.status != UserStatus.DELETED)

        return await self.scalar_one_or_none(
            statement,
            operation="find_by_email_or_username",
        )

    # ------------------------------------------------------------------
    # Изменение статуса пользователя
    # ------------------------------------------------------------------

    async def update_status(
        self,
        user: User,
        status: UserStatus,
        *,
        approved_at: datetime | None = None,
        blocked_at: datetime | None = None,
        rejected_at: datetime | None = None,
        deleted_at: datetime | None = None,
        block_reason: str | None = None,
        rejection_reason: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Обновляет статус пользователя и связанные поля.

        Метод изменяет статус пользователя и обновляет только те дополнительные
        поля, значения для которых были явно переданы.

        Args:
            user: Пользователь, которого нужно обновить.
            status: Новый статус пользователя.
            approved_at: Дата и время подтверждения пользователя.
            blocked_at: Дата и время блокировки пользователя.
            rejected_at: Дата и время отклонения пользователя.
            deleted_at: Дата и время логического удаления пользователя.
            block_reason: Причина блокировки. Пустая после удаления пробелов
                строка будет сохранена как ``None``.
            rejection_reason: Причина отклонения. Пустая после удаления
                пробелов строка будет сохранена как ``None``.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый экземпляр ``User``.
        """

        values: dict[str, Any] = {"status": status}

        if approved_at is not None:
            values["approved_at"] = approved_at

        if blocked_at is not None:
            values["blocked_at"] = blocked_at

        if rejected_at is not None:
            values["rejected_at"] = rejected_at

        if deleted_at is not None:
            values["deleted_at"] = deleted_at

        if block_reason is not None:
            values["block_reason"] = block_reason.strip() or None

        if rejection_reason is not None:
            values["rejection_reason"] = rejection_reason.strip() or None

        return await self.update(
            user,
            values,
            flush=flush,
            refresh=refresh,
        )

    async def update_status_by_id(
        self,
        user_id: uuid.UUID,
        status: UserStatus,
        *,
        approved_at: datetime | None = None,
        blocked_at: datetime | None = None,
        rejected_at: datetime | None = None,
        deleted_at: datetime | None = None,
        block_reason: str | None = None,
        rejection_reason: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Обновляет статус пользователя по идентификатору.

        Сначала получает пользователя по идентификатору, затем делегирует
        обновление методу ``update_status``.

        Args:
            user_id: Уникальный идентификатор пользователя.
            status: Новый статус пользователя.
            approved_at: Дата и время подтверждения пользователя.
            blocked_at: Дата и время блокировки пользователя.
            rejected_at: Дата и время отклонения пользователя.
            deleted_at: Дата и время логического удаления пользователя.
            block_reason: Причина блокировки.
            rejection_reason: Причина отклонения.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
        """

        user = await self.get_required_by_id(user_id)

        return await self.update_status(
            user,
            status,
            approved_at=approved_at,
            blocked_at=blocked_at,
            rejected_at=rejected_at,
            deleted_at=deleted_at,
            block_reason=block_reason,
            rejection_reason=rejection_reason,
            flush=flush,
            refresh=refresh,
        )

    async def mark_active(
        self,
        user: User,
        *,
        approved_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Помечает пользователя как активного.

        Вызывает доменный метод пользователя ``approve``. Если дата
        подтверждения не передана, используется текущее время в UTC.

        Args:
            user: Пользователь, которого нужно активировать.
            approved_at: Дата и время подтверждения. Если ``None``,
                используется текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.
        """

        user.approve(approved_at=approved_at or self._utc_now())

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(user)

        return user

    async def mark_active_by_id(
        self,
        user_id: uuid.UUID,
        *,
        approved_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Помечает пользователя как активного по идентификатору.

        Args:
            user_id: Уникальный идентификатор пользователя.
            approved_at: Дата и время подтверждения. Если ``None``,
                используется текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
        """

        user = await self.get_required_by_id(user_id)

        return await self.mark_active(
            user,
            approved_at=approved_at,
            flush=flush,
            refresh=refresh,
        )

    async def mark_blocked(
        self,
        user: User,
        *,
        reason: str | None = None,
        blocked_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Помечает пользователя как заблокированного.

        Вызывает доменный метод пользователя ``block``. Если дата блокировки не
        передана, используется текущее время в UTC.

        Args:
            user: Пользователь, которого нужно заблокировать.
            reason: Причина блокировки.
            blocked_at: Дата и время блокировки. Если ``None``, используется
                текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.
        """

        user.block(
            reason=reason.strip() if reason else None,
            blocked_at=blocked_at or self._utc_now(),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(user)

        return user

    async def mark_blocked_by_id(
        self,
        user_id: uuid.UUID,
        *,
        reason: str | None = None,
        blocked_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Помечает пользователя как заблокированного по идентификатору.

        Args:
            user_id: Уникальный идентификатор пользователя.
            reason: Причина блокировки.
            blocked_at: Дата и время блокировки. Если ``None``, используется
                текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
        """

        user = await self.get_required_by_id(user_id)

        return await self.mark_blocked(
            user,
            reason=reason,
            blocked_at=blocked_at,
            flush=flush,
            refresh=refresh,
        )

    async def unblock(
        self,
        user: User,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Разблокирует пользователя.

        Вызывает доменный метод пользователя ``unblock`` и при необходимости
        синхронизирует изменения с базой данных.

        Args:
            user: Пользователь, которого нужно разблокировать.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.
        """

        user.unblock()

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(user)

        return user

    async def unblock_by_id(
        self,
        user_id: uuid.UUID,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Разблокирует пользователя по идентификатору.

        Args:
            user_id: Уникальный идентификатор пользователя.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
        """

        user = await self.get_required_by_id(user_id)

        return await self.unblock(
            user,
            flush=flush,
            refresh=refresh,
        )

    async def mark_rejected(
        self,
        user: User,
        *,
        reason: str | None = None,
        rejected_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Помечает пользователя как отклонённого.

        Вызывает доменный метод пользователя ``reject``. Если дата отклонения
        не передана, используется текущее время в UTC.

        Args:
            user: Пользователь, которого нужно отклонить.
            reason: Причина отклонения.
            rejected_at: Дата и время отклонения. Если ``None``, используется
                текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.
        """

        user.reject(
            reason=reason.strip() if reason else None,
            rejected_at=rejected_at or self._utc_now(),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(user)

        return user

    async def mark_rejected_by_id(
        self,
        user_id: uuid.UUID,
        *,
        reason: str | None = None,
        rejected_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Помечает пользователя как отклонённого по идентификатору.

        Args:
            user_id: Уникальный идентификатор пользователя.
            reason: Причина отклонения.
            rejected_at: Дата и время отклонения. Если ``None``, используется
                текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
        """

        user = await self.get_required_by_id(user_id)

        return await self.mark_rejected(
            user,
            reason=reason,
            rejected_at=rejected_at,
            flush=flush,
            refresh=refresh,
        )

    async def mark_deleted(
        self,
        user: User,
        *,
        deleted_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Логически удаляет пользователя.

        Физическое удаление записи не выполняется. Пользователь получает статус
        ``UserStatus.DELETED``. Если дата удаления не передана, используется
        текущее время в UTC.

        Args:
            user: Пользователь, которого нужно логически удалить.
            deleted_at: Дата и время удаления. Если ``None``, используется
                текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.
        """

        user.mark_deleted(deleted_at=deleted_at or self._utc_now())

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(user)

        return user

    async def mark_deleted_by_id(
        self,
        user_id: uuid.UUID,
        *,
        deleted_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Логически удаляет пользователя по идентификатору.

        Физическое удаление записи не выполняется. Пользователь получает статус
        ``UserStatus.DELETED``.

        Args:
            user_id: Уникальный идентификатор пользователя.
            deleted_at: Дата и время удаления. Если ``None``, используется
                текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
        """

        user = await self.get_required_by_id(user_id)

        return await self.mark_deleted(
            user,
            deleted_at=deleted_at,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Прочие обновления пользователя
    # ------------------------------------------------------------------

    async def update_last_login(
        self,
        user: User,
        *,
        last_login_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Обновляет дату последнего успешного входа пользователя.

        Вызывает доменный метод пользователя ``mark_login``. Если дата входа не
        передана, используется текущее время в UTC.

        Args:
            user: Пользователь, для которого нужно обновить дату входа.
            last_login_at: Дата и время успешного входа. Если ``None``,
                используется текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.
        """

        user.mark_login(logged_in_at=last_login_at or self._utc_now())

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(user)

        return user

    async def update_last_login_by_id(
        self,
        user_id: uuid.UUID,
        *,
        last_login_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Обновляет дату последнего успешного входа по идентификатору.

        Args:
            user_id: Уникальный идентификатор пользователя.
            last_login_at: Дата и время успешного входа. Если ``None``,
                используется текущее UTC-время.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
        """

        user = await self.get_required_by_id(user_id)

        return await self.update_last_login(
            user,
            last_login_at=last_login_at,
            flush=flush,
            refresh=refresh,
        )

    async def update_password_hash(
        self,
        user: User,
        *,
        password_hash: str,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Обновляет хэш пароля пользователя.

        Перед обновлением выполняется базовая валидация хэша пароля. После
        успешной проверки вызывается доменный метод ``change_password_hash``.

        Args:
            user: Пользователь, для которого нужно обновить хэш пароля.
            password_hash: Новый хэш пароля.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            InvalidQueryError: Если хэш пароля пустой или превышает допустимую
                длину.
        """

        self._validate_password_hash(password_hash)

        user.change_password_hash(password_hash)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(user)

        return user

    async def update_password_hash_by_id(
        self,
        user_id: uuid.UUID,
        *,
        password_hash: str,
        flush: bool = True,
        refresh: bool = False,
    ) -> User:
        """Обновляет хэш пароля пользователя по id.

        Args:
            user_id: Уникальный идентификатор пользователя.
            password_hash: Новый хэш пароля.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
            InvalidQueryError: Если хэш пароля пустой или превышает допустимую
                длину.
        """

        user = await self.get_required_by_id(user_id)

        return await self.update_password_hash(
            user,
            password_hash=password_hash,
            flush=flush,
            refresh=refresh,
        )

    async def update_identity(
        self,
        user: User,
        *,
        email: str | None = None,
        username: str | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_duplicates: bool = True,
    ) -> User:
        """Обновляет email и/или username пользователя.

        Если новые значения не переданы, метод возвращает пользователя без
        изменений. Перед сохранением новые значения нормализуются и
        валидируются. При включённой проверке дубликатов выполняется проверка
        уникальности email и username с исключением текущего пользователя.

        Args:
            user: Пользователь, которого нужно обновить.
            email: Новый email. Если ``None``, email не изменяется.
            username: Новый username. Если ``None``, username не изменяется.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.
            check_duplicates: Проверять ли уникальность новых email и username.

        Returns:
            Обновлённый экземпляр ``User``. Если новые значения не переданы,
            возвращается исходный пользователь.

        Raises:
            InvalidQueryError: Если email или username некорректны.
            DuplicateEntityError: Если email или username уже используются
                другим пользователем.
        """

        values: dict[str, str] = {}

        if email is not None:
            normalized_email = self._normalize_email(email)
            self._validate_email(normalized_email)

            if check_duplicates and await self.email_exists(
                normalized_email,
                exclude_user_id=user.id,
            ):
                raise DuplicateEntityError(
                    "User",
                    field="email",
                    value=normalized_email,
                    repository=self.repository_name,
                )

            values["email"] = normalized_email

        if username is not None:
            normalized_username = self._normalize_username(username)
            self._validate_username(normalized_username)

            if check_duplicates and await self.username_exists(
                normalized_username,
                exclude_user_id=user.id,
            ):
                raise DuplicateEntityError(
                    "User",
                    field="username",
                    value=normalized_username,
                    repository=self.repository_name,
                )

            values["username"] = normalized_username

        if not values:
            return user

        return await self.update(
            user,
            values,
            flush=flush,
            refresh=refresh,
            allowed_fields={"email", "username"},
        )

    async def update_identity_by_id(
        self,
        user_id: uuid.UUID,
        *,
        email: str | None = None,
        username: str | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_duplicates: bool = True,
    ) -> User:
        """Обновляет email и/или username пользователя по id.

        Сначала получает пользователя по идентификатору, затем делегирует
        обновление методу ``update_identity``.

        Args:
            user_id: Уникальный идентификатор пользователя.
            email: Новый email. Если ``None``, email не изменяется.
            username: Новый username. Если ``None``, username не изменяется.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.
            check_duplicates: Проверять ли уникальность новых email и username.

        Returns:
            Обновлённый экземпляр ``User``.

        Raises:
            EntityNotFoundError: Если пользователь с указанным идентификатором
                не найден.
            InvalidQueryError: Если email или username некорректны.
            DuplicateEntityError: Если email или username уже используются
                другим пользователем.
        """

        user = await self.get_required_by_id(user_id)

        return await self.update_identity(
            user,
            email=email,
            username=username,
            flush=flush,
            refresh=refresh,
            check_duplicates=check_duplicates,
        )

    # ------------------------------------------------------------------
    # Подсчёт
    # ------------------------------------------------------------------

    async def count_by_status(
        self,
        status: UserStatus,
    ) -> int:
        """Возвращает количество пользователей с указанным статусом.

        Args:
            status: Статус пользователей, по которому выполняется подсчёт.

        Returns:
            Количество пользователей с указанным статусом.
        """

        return await self.count(User.status == status)

    async def count_active_users(self) -> int:
        """Возвращает количество активных пользователей.

        Returns:
            Количество пользователей со статусом ``UserStatus.ACTIVE``.
        """

        return await self.count_by_status(UserStatus.ACTIVE)

    async def count_pending_users(self) -> int:
        """Возвращает количество пользователей, ожидающих подтверждения.

        Returns:
            Количество пользователей со статусом ``UserStatus.PENDING``.
        """

        return await self.count_by_status(UserStatus.PENDING)

    async def count_non_deleted_users(self) -> int:
        """Возвращает количество пользователей без статуса ``DELETED``.

        Returns:
            Количество пользователей, которые не были логически удалены.
        """

        return await self.count(User.status != UserStatus.DELETED)

    async def get_status_counts(self) -> dict[UserStatus, int]:
        """Возвращает количество пользователей по каждому статусу.

        Выполняет группировку пользователей по полю ``status`` и возвращает
        словарь с количеством записей для каждого найденного статуса.

        Returns:
            Словарь, где ключ — значение ``UserStatus``, а значение —
            количество пользователей с этим статусом.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        try:
            statement = select(User.status, func.count(User.id)).group_by(User.status)
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

    def _base_select(self) -> Select[tuple[User]]:
        """Создаёт базовый SELECT-запрос для модели ``User``.

        Метод переопределяет базовое поведение репозитория и используется как
        единая точка создания простого запроса выборки пользователей.

        Returns:
            SQLAlchemy ``SELECT``-запрос для выборки объектов ``User``.
        """

        return select(User)

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

        Удаляет пробелы по краям строки. Регистр символов не изменяется, чтобы
        сохранить исходное отображаемое значение username.

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
        """Выполняет базовую валидацию email.

        Проверяет, что email не пустой, не превышает допустимую длину и
        содержит символ ``@``.

        Args:
            email: Email для проверки.

        Raises:
            InvalidQueryError: Если email пустой, превышает допустимую длину
                или имеет недопустимый формат.
        """

        if not email:
            raise InvalidQueryError(
                "Email пользователя не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_email",
            )

        if len(email) > 320:
            raise InvalidQueryError(
                "Email пользователя превышает допустимую длину.",
                repository=self.repository_name,
                operation="_validate_email",
                details={
                    "max_length": 320,
                    "actual_length": len(email),
                },
            )

        if "@" not in email:
            raise InvalidQueryError(
                "Email пользователя имеет недопустимый формат.",
                repository=self.repository_name,
                operation="_validate_email",
                details={"email": email},
            )

    def _validate_username(
        self,
        username: str,
    ) -> None:
        """Выполняет базовую валидацию username.

        Проверяет, что username не пустой и не превышает допустимую длину.

        Args:
            username: Username для проверки.

        Raises:
            InvalidQueryError: Если username пустой или превышает допустимую
                длину.
        """

        if not username:
            raise InvalidQueryError(
                "Username пользователя не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_username",
            )

        if len(username) > 64:
            raise InvalidQueryError(
                "Username пользователя превышает допустимую длину.",
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
        """Проверяет хэш пароля пользователя.

        Проверяет, что хэш пароля не пустой после удаления пробелов по краям
        строки и не превышает допустимую длину.

        Args:
            password_hash: Хэш пароля для проверки.

        Raises:
            InvalidQueryError: Если хэш пароля пустой или превышает допустимую
                длину.
        """

        if not password_hash or not password_hash.strip():
            raise InvalidQueryError(
                "Хэш пароля пользователя не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_password_hash",
            )

        if len(password_hash) > 255:
            raise InvalidQueryError(
                "Хэш пароля пользователя превышает допустимую длину.",
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
            Текущие дата и время с timezone ``UTC``.
        """

        return datetime.now(UTC)
