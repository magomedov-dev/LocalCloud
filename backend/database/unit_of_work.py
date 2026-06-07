from __future__ import annotations

from types import TracebackType
from typing import Any, Self

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.client import get_async_session_factory
from database.exceptions import UnitOfWorkError
from database.repositories.audit import AuditLogRepository
from database.repositories.files import FileRepository
from database.repositories.folders import FolderRepository
from database.repositories.links import PublicLinksRepository
from database.repositories.nodes import FileSystemNodeRepository
from database.repositories.parts import UploadPartsRepository
from database.repositories.permissions import NodePermissionsRepository
from database.repositories.quotas import UserQuotaRepository
from database.repositories.registration import RegistrationRequestsRepository
from database.repositories.roles import RolesRepository
from database.repositories.sessions import UploadSessionsRepository
from database.repositories.tasks import BackgroundTasksRepository
from database.repositories.tokens import RefreshTokensRepository
from database.repositories.trash import TrashItemRepository
from database.repositories.users import UsersRepository
from database.repositories.versions import FileVersionRepository
from database.transactions import (
    ensure_transaction_closed,
    safe_commit,
    safe_flush,
    safe_refresh,
    safe_rollback,
)


class UnitOfWork:
    """Транзакционный контейнер для работы с репозиториями.

    UnitOfWork управляет жизненным циклом SQLAlchemy AsyncSession и задаёт
    единую транзакционную границу для сервисного слоя.

    Поддерживаются два режима работы:
        1. Собственная сессия: если ``session`` не передана, UnitOfWork создаёт
           новую AsyncSession через ``session_factory`` или глобальную фабрику
           ``get_async_session_factory()``.
        2. Внешняя сессия: если ``session`` передана явно, UnitOfWork использует
           её и по умолчанию не закрывает при выходе из контекста.

    По умолчанию UnitOfWork не выполняет commit автоматически при успешном
    выходе из контекста. Сервисный слой должен явно фиксировать изменения через
    ``await uow.commit()``.
    """

    def __init__(
        self,
        *,
        session: AsyncSession | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        commit_on_exit: bool = False,
        rollback_on_exit_without_commit: bool = True,
        close_session_on_exit: bool | None = None,
    ) -> None:
        """Инициализирует UnitOfWork.

        Args:
            session: Готовая внешняя AsyncSession. Если передана, UnitOfWork не
                создаёт новую сессию.
            session_factory: Фабрика SQLAlchemy AsyncSession. Используется
                только если ``session`` не передана.
            commit_on_exit: Если True, UnitOfWork выполнит commit при успешном
                выходе из ``async with``, если commit не был выполнен вручную.
            rollback_on_exit_without_commit: Если True, UnitOfWork выполнит
                rollback при успешном выходе из контекста, если commit не был
                выполнен.
            close_session_on_exit: Нужно ли закрывать сессию при выходе из
                контекста. Если None, значение определяется автоматически:
                True для собственной сессии и False для внешней.
        """

        self._external_session = session
        self._session_factory = session_factory

        self._session: AsyncSession | None = session
        self._owns_session = session is None

        self._close_session_on_exit = (
            self._owns_session
            if close_session_on_exit is None
            else close_session_on_exit
        )

        self._commit_on_exit = commit_on_exit
        self._rollback_on_exit_without_commit = rollback_on_exit_without_commit

        self._entered = False
        self._committed = False
        self._rolled_back = False
        self._closed = False

        self._users: UsersRepository | None = None
        self._roles: RolesRepository | None = None
        self._registration_requests: RegistrationRequestsRepository | None = None
        self._refresh_tokens: RefreshTokensRepository | None = None

        self._nodes: FileSystemNodeRepository | None = None
        self._files: FileRepository | None = None
        self._folders: FolderRepository | None = None
        self._versions: FileVersionRepository | None = None
        self._trash: TrashItemRepository | None = None

        self._permissions: NodePermissionsRepository | None = None
        self._links: PublicLinksRepository | None = None

        self._upload_sessions: UploadSessionsRepository | None = None
        self._upload_parts: UploadPartsRepository | None = None

        self._quotas: UserQuotaRepository | None = None
        self._audit: AuditLogRepository | None = None
        self._tasks: BackgroundTasksRepository | None = None

    async def __aenter__(self) -> Self:
        """Входит в асинхронный контекст UnitOfWork.

        Если сессия не была передана при создании UnitOfWork, метод создаёт
        новую AsyncSession через фабрику сессий.

        Returns:
            Текущий экземпляр UnitOfWork.

        Raises:
            UnitOfWorkError: Если UnitOfWork уже находится в активном контексте
                или если не удалось создать сессию базы данных.
        """

        if self._entered and not self._closed:
            raise UnitOfWorkError(
                "UnitOfWork уже находится в активном контексте.",
                details={
                    "operation": "unit_of_work.enter",
                },
            )

        if self._session is None:
            try:
                factory = self._session_factory or get_async_session_factory()
                self._session = factory()
                self._owns_session = True

                if self._external_session is None:
                    self._close_session_on_exit = True

            except Exception as exc:
                raise UnitOfWorkError(
                    "Не удалось создать сессию UnitOfWork.",
                    details={
                        "operation": "unit_of_work.enter",
                        "original_error": str(exc),
                        "original_error_type": exc.__class__.__name__,
                    },
                    cause=exc,
                ) from exc

        self._entered = True
        self._closed = False
        self._committed = False
        self._rolled_back = False

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Завершает асинхронный контекст UnitOfWork.

        При выходе из контекста UnitOfWork выполняет rollback при ошибке,
        commit при ``commit_on_exit=True`` или rollback без commit, если включена
        защита ``rollback_on_exit_without_commit``.

        Args:
            exc_type: Тип исключения, возникшего внутри блока ``async with``,
                или None.
            exc_value: Экземпляр исключения, возникшего внутри блока, или None.
            traceback: Traceback исключения, возникшего внутри блока, или None.

        Returns:
            False. UnitOfWork не подавляет исключения пользовательского кода.

        Raises:
            UnitOfWorkError: Если при автоматическом commit или закрытии
                собственной сессии произошла ошибка.
        """

        try:
            if exc_type is not None:
                await self.rollback(suppress_errors=True)
                return False

            if self._commit_on_exit and not self._committed:
                await self.commit()

            elif (
                self._rollback_on_exit_without_commit
                and not self._committed
                and not self._rolled_back
            ):
                await self.rollback(suppress_errors=True)

            return False

        finally:
            await self.close()

    @property
    def session(self) -> AsyncSession:
        """Возвращает активную SQLAlchemy AsyncSession.

        Returns:
            Активная AsyncSession.

        Raises:
            UnitOfWorkError: Если сессия не инициализирована или UnitOfWork уже
                закрыт.
        """

        if self._session is None:
            raise UnitOfWorkError(
                "Сессия UnitOfWork не инициализирована.",
                details={
                    "operation": "unit_of_work.session",
                    "hint": "Используйте UnitOfWork внутри async with.",
                },
            )

        if self._closed:
            raise UnitOfWorkError(
                "Сессия UnitOfWork уже закрыта.",
                details={
                    "operation": "unit_of_work.session",
                },
            )

        return self._session

    @property
    def users(self) -> UsersRepository:
        """Возвращает репозиторий пользователей.

        Returns:
            Экземпляр UsersRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._users is None:
            self._users = UsersRepository(self.session)
        return self._users

    @property
    def roles(self) -> RolesRepository:
        """Возвращает репозиторий ролей.

        Returns:
            Экземпляр RolesRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._roles is None:
            self._roles = RolesRepository(self.session)
        return self._roles

    @property
    def registration_requests(self) -> RegistrationRequestsRepository:
        """Возвращает репозиторий заявок на регистрацию.

        Returns:
            Экземпляр RegistrationRequestsRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._registration_requests is None:
            self._registration_requests = RegistrationRequestsRepository(
                self.session,
            )
        return self._registration_requests

    @property
    def refresh_tokens(self) -> RefreshTokensRepository:
        """Возвращает репозиторий refresh-токенов.

        Returns:
            Экземпляр RefreshTokensRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._refresh_tokens is None:
            self._refresh_tokens = RefreshTokensRepository(self.session)
        return self._refresh_tokens

    @property
    def nodes(self) -> FileSystemNodeRepository:
        """Возвращает репозиторий узлов файловой системы.

        Returns:
            Экземпляр FileSystemNodeRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._nodes is None:
            self._nodes = FileSystemNodeRepository(self.session)
        return self._nodes

    @property
    def files(self) -> FileRepository:
        """Возвращает репозиторий файлов.

        Returns:
            Экземпляр FileRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._files is None:
            self._files = FileRepository(self.session)
        return self._files

    @property
    def folders(self) -> FolderRepository:
        """Возвращает репозиторий папок.

        Returns:
            Экземпляр FolderRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._folders is None:
            self._folders = FolderRepository(self.session)
        return self._folders

    @property
    def versions(self) -> FileVersionRepository:
        """Возвращает репозиторий версий файлов.

        Returns:
            Экземпляр FileVersionRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._versions is None:
            self._versions = FileVersionRepository(self.session)
        return self._versions

    @property
    def trash(self) -> TrashItemRepository:
        """Возвращает репозиторий элементов корзины.

        Returns:
            Экземпляр TrashItemRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._trash is None:
            self._trash = TrashItemRepository(self.session)
        return self._trash

    @property
    def permissions(self) -> NodePermissionsRepository:
        """Возвращает репозиторий прав доступа к узлам.

        Returns:
            Экземпляр NodePermissionsRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._permissions is None:
            self._permissions = NodePermissionsRepository(self.session)
        return self._permissions

    @property
    def links(self) -> PublicLinksRepository:
        """Возвращает репозиторий публичных ссылок.

        Returns:
            Экземпляр PublicLinksRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._links is None:
            self._links = PublicLinksRepository(self.session)
        return self._links

    @property
    def upload_sessions(self) -> UploadSessionsRepository:
        """Возвращает репозиторий сессий загрузки.

        Returns:
            Экземпляр UploadSessionsRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._upload_sessions is None:
            self._upload_sessions = UploadSessionsRepository(self.session)
        return self._upload_sessions

    @property
    def upload_parts(self) -> UploadPartsRepository:
        """Возвращает репозиторий частей загрузки.

        Returns:
            Экземпляр UploadPartsRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._upload_parts is None:
            self._upload_parts = UploadPartsRepository(self.session)
        return self._upload_parts

    @property
    def quotas(self) -> UserQuotaRepository:
        """Возвращает репозиторий пользовательских квот.

        Returns:
            Экземпляр UserQuotaRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._quotas is None:
            self._quotas = UserQuotaRepository(self.session)
        return self._quotas

    @property
    def audit(self) -> AuditLogRepository:
        """Возвращает репозиторий журнала аудита.

        Returns:
            Экземпляр AuditLogRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._audit is None:
            self._audit = AuditLogRepository(self.session)
        return self._audit

    @property
    def tasks(self) -> BackgroundTasksRepository:
        """Возвращает репозиторий фоновых задач.

        Returns:
            Экземпляр BackgroundTasksRepository.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
        """

        if self._tasks is None:
            self._tasks = BackgroundTasksRepository(self.session)
        return self._tasks

    async def commit(self) -> None:
        """Фиксирует текущую транзакцию.

        После успешного commit флаг ``is_committed`` становится True, а
        ``is_rolled_back`` — False.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
            TransactionError: Если фиксация транзакции завершилась ошибкой.
        """

        self._ensure_usable(operation="unit_of_work.commit")

        await safe_commit(
            self.session,
            operation="unit_of_work.commit",
        )

        self._committed = True
        self._rolled_back = False

    async def rollback(
        self,
        *,
        suppress_errors: bool = False,
    ) -> None:
        """Откатывает текущую транзакцию.

        Args:
            suppress_errors: Если True, ошибки rollback подавляются. Используется
                при выходе из контекста после исходной ошибки пользовательского
                кода, чтобы не замаскировать её.

        Raises:
            TransactionError: Если rollback завершился ошибкой и
                ``suppress_errors=False``.
        """

        if self._session is None or self._closed:
            return

        await safe_rollback(
            self.session,
            operation="unit_of_work.rollback",
            suppress_errors=suppress_errors,
        )

        self._rolled_back = True
        self._committed = False

    async def flush(self) -> None:
        """Выполняет flush текущей сессии.

        Flush отправляет накопленные изменения в базу данных, но не фиксирует
        транзакцию окончательно.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
            TransactionError: Если flush завершился ошибкой.
        """

        self._ensure_usable(operation="unit_of_work.flush")

        await safe_flush(
            self.session,
            operation="unit_of_work.flush",
        )

    async def refresh(
        self,
        entity: Any,
        *,
        attribute_names: list[str] | None = None,
    ) -> Any:
        """Обновляет ORM-сущность из базы данных.

        Args:
            entity: ORM-объект SQLAlchemy, который нужно обновить из базы
                данных.
            attribute_names: Список имён атрибутов для обновления. Если None,
                обновляется вся сущность.

        Returns:
            Переданная ORM-сущность после обновления.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
            TransactionError: Если refresh завершился ошибкой.
        """

        self._ensure_usable(operation="unit_of_work.refresh")

        return await safe_refresh(
            self.session,
            entity,
            operation="unit_of_work.refresh",
            attribute_names=attribute_names,
        )

    async def flush_and_refresh(
        self,
        entity: Any,
        *,
        attribute_names: list[str] | None = None,
    ) -> Any:
        """Выполняет flush, затем refresh переданной ORM-сущности.

        Метод удобен после создания записи, когда нужно получить значения,
        сгенерированные базой данных: id, created_at, updated_at и другие.

        Args:
            entity: ORM-объект SQLAlchemy, который нужно отправить в базу
                данных и затем обновить.
            attribute_names: Список имён атрибутов для обновления. Если None,
                обновляется вся сущность.

        Returns:
            Переданная ORM-сущность после flush и refresh.

        Raises:
            UnitOfWorkError: Если UnitOfWork используется вне активного
                контекста.
            TransactionError: Если flush или refresh завершились ошибкой.
        """

        await self.flush()

        return await self.refresh(
            entity,
            attribute_names=attribute_names,
        )

    async def close(self) -> None:
        """Закрывает UnitOfWork.

        Если UnitOfWork должен закрывать сессию, перед закрытием проверяется
        наличие активной транзакции. Если транзакция активна, она безопасно
        завершается через rollback.

        Метод безопасен для повторного вызова.

        Raises:
            UnitOfWorkError: Если при закрытии собственной сессии произошла
                ошибка.
        """

        if self._closed:
            return

        session = self._session

        try:
            if session is not None and self._close_session_on_exit:
                if session.in_transaction():
                    await ensure_transaction_closed(
                        session,
                        operation="unit_of_work.close.rollback",
                    )

                try:
                    await session.close()
                except SQLAlchemyError as exc:
                    raise UnitOfWorkError(
                        "Не удалось закрыть сессию UnitOfWork.",
                        details={
                            "operation": "unit_of_work.close",
                            "original_error": str(exc),
                            "original_error_type": exc.__class__.__name__,
                        },
                        cause=exc,
                    ) from exc

        finally:
            self._closed = True
            self._entered = False
            self._reset_repositories()

            if self._owns_session:
                self._session = None

    def _ensure_usable(
        self,
        *,
        operation: str,
    ) -> None:
        """Проверяет, что UnitOfWork находится в пригодном состоянии.

        Args:
            operation: Название операции, для которой выполняется проверка.
                Используется в деталях исключения.

        Raises:
            UnitOfWorkError: Если UnitOfWork не содержит активной сессии, уже
                закрыт или используется вне активного контекста.
        """

        if self._session is None:
            raise UnitOfWorkError(
                "UnitOfWork не содержит активной сессии.",
                details={
                    "operation": operation,
                    "hint": "Используйте UnitOfWork внутри async with.",
                },
            )

        if self._closed:
            raise UnitOfWorkError(
                "UnitOfWork уже закрыт.",
                details={
                    "operation": operation,
                },
            )

        if not self._entered:
            raise UnitOfWorkError(
                "UnitOfWork используется вне активного контекста.",
                details={
                    "operation": operation,
                    "hint": "Оберните использование в async with UnitOfWork().",
                },
            )

    def _reset_repositories(self) -> None:
        """Сбрасывает лениво созданные экземпляры репозиториев.

        Метод вызывается при закрытии UnitOfWork, чтобы старые репозитории не
        продолжали ссылаться на закрытую или уже неактуальную сессию.
        """

        self._users = None
        self._roles = None
        self._registration_requests = None
        self._refresh_tokens = None

        self._nodes = None
        self._files = None
        self._folders = None
        self._versions = None
        self._trash = None

        self._permissions = None
        self._links = None

        self._upload_sessions = None
        self._upload_parts = None

        self._quotas = None
        self._audit = None
        self._tasks = None


class UnitOfWorkFactory:
    """Фабрика UnitOfWork.

    Используется для внедрения UnitOfWork в сервисный слой.

    Example:
        ```python
        uow_factory = UnitOfWorkFactory()

        async with uow_factory() as uow:
            user = await uow.users.get_required_by_id(user_id)
            await uow.commit()
        ```
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        commit_on_exit: bool = False,
        rollback_on_exit_without_commit: bool = True,
    ) -> None:
        """Инициализирует фабрику UnitOfWork.

        Args:
            session_factory: Фабрика SQLAlchemy AsyncSession, которая будет
                использоваться создаваемыми UnitOfWork.
            commit_on_exit: Значение по умолчанию для автоматического commit
                при выходе из контекста.
            rollback_on_exit_without_commit: Значение по умолчанию для rollback
                при выходе без явного commit.
        """

        self.session_factory = session_factory
        self.commit_on_exit = commit_on_exit
        self.rollback_on_exit_without_commit = rollback_on_exit_without_commit

    def __call__(
        self,
        *,
        session: AsyncSession | None = None,
        commit_on_exit: bool | None = None,
        rollback_on_exit_without_commit: bool | None = None,
        close_session_on_exit: bool | None = None,
    ) -> UnitOfWork:
        """Создаёт новый экземпляр UnitOfWork.

        Args:
            session: Внешняя AsyncSession. Если передана, UnitOfWork будет
                работать с ней и по умолчанию не будет закрывать её при выходе.
            commit_on_exit: Переопределяет режим автоматического commit для
                создаваемого UnitOfWork.
            rollback_on_exit_without_commit: Переопределяет режим rollback при
                выходе без явного commit.
            close_session_on_exit: Переопределяет правило закрытия сессии при
                выходе из контекста.

        Returns:
            Новый экземпляр UnitOfWork.
        """

        return UnitOfWork(
            session=session,
            session_factory=self.session_factory,
            commit_on_exit=(
                self.commit_on_exit if commit_on_exit is None else commit_on_exit
            ),
            rollback_on_exit_without_commit=(
                self.rollback_on_exit_without_commit
                if rollback_on_exit_without_commit is None
                else rollback_on_exit_without_commit
            ),
            close_session_on_exit=close_session_on_exit,
        )


def create_unit_of_work_factory(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    commit_on_exit: bool = False,
    rollback_on_exit_without_commit: bool = True,
) -> UnitOfWorkFactory:
    """Создаёт фабрику UnitOfWork.

    Функция удобна для слоя зависимостей приложения, например для
    ``app/dependencies.py``, где можно один раз подготовить фабрику и затем
    передавать её в сервисы.

    Args:
        session_factory: Фабрика SQLAlchemy AsyncSession. Если None, UnitOfWork
            будет получать глобальную фабрику через
            ``get_async_session_factory()``.
        commit_on_exit: Значение по умолчанию для автоматического commit при
            успешном выходе из контекста.
        rollback_on_exit_without_commit: Значение по умолчанию для rollback при
            выходе без явного commit.

    Returns:
        Экземпляр UnitOfWorkFactory.
    """

    return UnitOfWorkFactory(
        session_factory=session_factory,
        commit_on_exit=commit_on_exit,
        rollback_on_exit_without_commit=rollback_on_exit_without_commit,
    )
