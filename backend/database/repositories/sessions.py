from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Select, String, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import UploadPartStatus, UploadSessionStatus
from database.models.filesystem import FileSystemNode
from database.models.uploads import UploadPart, UploadSession
from database.models.users import User
from database.repositories.base import BaseRepository


class UploadSessionsRepository(BaseRepository[UploadSession]):
    """Репозиторий для работы с сессиями multipart-загрузки.

    Инкапсулирует операции создания, поиска, фильтрации, обновления статуса,
    учёта прогресса, проверки состояния и подсчёта сессий загрузки.

    Работает с моделью ``UploadSession`` через асинхронную SQLAlchemy-сессию.

    Репозиторий не выполняет ``commit`` или ``rollback``. Управление
    транзакциями должно находиться на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий сессий multipart-загрузки.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=UploadSession)

    # ------------------------------------------------------------------
    # Базовые выборки
    # ------------------------------------------------------------------

    async def get_session_by_id(
        self,
        upload_session_id: uuid.UUID,
    ) -> UploadSession | None:
        """Возвращает сессию загрузки по идентификатору.

        Args:
            upload_session_id: Идентификатор сессии загрузки.

        Returns:
            Сессия загрузки, если она найдена, иначе ``None``.
        """

        return await self.get_by_id(upload_session_id)

    async def get_required_session_by_id(
        self,
        upload_session_id: uuid.UUID,
    ) -> UploadSession:
        """Возвращает сессию загрузки по идентификатору.

        Args:
            upload_session_id: Идентификатор сессии загрузки.

        Returns:
            Найденная сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        return await self.get_required_by_id(upload_session_id)

    async def get_by_upload_id(
        self,
        upload_id: str,
    ) -> UploadSession | None:
        """Возвращает сессию загрузки по внешнему идентификатору multipart upload.

        Args:
            upload_id: Внешний идентификатор multipart-загрузки в объектном
                хранилище.

        Returns:
            Сессия загрузки, если она найдена, иначе ``None``.
        """

        normalized_upload_id = self._normalize_upload_id(upload_id)

        if not normalized_upload_id:
            return None

        statement = select(UploadSession).where(
            UploadSession.upload_id == normalized_upload_id,
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_upload_id",
        )

    async def get_required_by_upload_id(
        self,
        upload_id: str,
    ) -> UploadSession:
        """Возвращает сессию загрузки по внешнему идентификатору multipart upload.

        Args:
            upload_id: Внешний идентификатор multipart-загрузки в объектном
                хранилище.

        Returns:
            Найденная сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия с указанным ``upload_id`` не найдена.
        """

        upload_session = await self.get_by_upload_id(upload_id)

        if upload_session is None:
            raise EntityNotFoundError(
                self.model_name,
                lookup={"upload_id": upload_id},
                repository=self.repository_name,
            )

        return upload_session

    async def get_by_storage_key(
        self,
        *,
        storage_bucket: str,
        storage_key: str,
    ) -> UploadSession | None:
        """Возвращает сессию загрузки по bucket/key объекта в хранилище.

        Args:
            storage_bucket: Название bucket в объектном хранилище.
            storage_key: Ключ объекта в объектном хранилище.

        Returns:
            Сессия загрузки, если она найдена, иначе ``None``.
        """

        normalized_bucket = storage_bucket.strip()
        normalized_key = storage_key.strip()

        if not normalized_bucket or not normalized_key:
            return None

        statement = select(UploadSession).where(
            UploadSession.storage_bucket == normalized_bucket,
            UploadSession.storage_key == normalized_key,
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_storage_key",
        )

    async def is_upload_id_exists(
        self,
        upload_id: str,
    ) -> bool:
        """Проверяет существование сессии загрузки с указанным ``upload_id``.

        Args:
            upload_id: Внешний идентификатор multipart-загрузки.

        Returns:
            ``True``, если сессия с таким ``upload_id`` существует,
            иначе ``False``.
        """

        normalized_upload_id = self._normalize_upload_id(upload_id)

        if not normalized_upload_id:
            return False

        return await self.exists(UploadSession.upload_id == normalized_upload_id)

    # ------------------------------------------------------------------
    # Списки сессий
    # ------------------------------------------------------------------

    async def list_user_sessions(
        self,
        user_id: uuid.UUID,
        *,
        status: UploadSessionStatus | None = None,
        statuses: Sequence[UploadSessionStatus] | None = None,
        offset: int = 0,
        limit: int = 100,
        order_by_created_desc: bool = True,
    ) -> list[UploadSession]:
        """Возвращает сессии загрузки пользователя с пагинацией и фильтрацией.

        Нельзя одновременно передавать ``status`` и ``statuses``.

        Args:
            user_id: Идентификатор пользователя.
            status: Один статус для фильтрации.
            statuses: Набор статусов для фильтрации.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            order_by_created_desc: Сортировать ли по дате создания по убыванию.

        Returns:
            Список сессий загрузки пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны, одновременно
                переданы ``status`` и ``statuses`` или список ``statuses`` пустой.
        """

        self._validate_pagination(offset=offset, limit=limit)

        if status is not None and statuses is not None:
            raise InvalidQueryError(
                "Нельзя одновременно указывать status и statuses.",
                repository=self.repository_name,
                operation="list_user_sessions",
            )

        statement = select(UploadSession).where(UploadSession.user_id == user_id)

        if status is not None:
            statement = statement.where(UploadSession.status == status)

        if statuses is not None:
            if not statuses:
                raise InvalidQueryError(
                    "Список статусов сессий загрузки не может быть пустым.",
                    repository=self.repository_name,
                    operation="list_user_sessions",
                )
            statement = statement.where(UploadSession.status.in_(list(statuses)))

        if order_by_created_desc:
            statement = statement.order_by(UploadSession.created_at.desc())
        else:
            statement = statement.order_by(UploadSession.created_at.asc())

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="list_user_sessions",
        )

    async def list_user_active_sessions(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[UploadSession]:
        """Возвращает активные сессии загрузки пользователя.

        Активными считаются сессии со статусами ``CREATED`` и ``UPLOADING``.

        Args:
            user_id: Идентификатор пользователя.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список активных сессий загрузки пользователя.
        """

        return await self.list_user_sessions_by_statuses(
            user_id=user_id,
            statuses=[
                UploadSessionStatus.CREATED,
                UploadSessionStatus.UPLOADING,
            ],
            offset=offset,
            limit=limit,
            operation="list_user_active_sessions",
        )

    async def list_user_sessions_by_statuses(
        self,
        user_id: uuid.UUID,
        statuses: Sequence[UploadSessionStatus],
        *,
        offset: int = 0,
        limit: int = 100,
        operation: str = "list_user_sessions_by_statuses",
    ) -> list[UploadSession]:
        """Возвращает сессии загрузки пользователя по набору статусов.

        Args:
            user_id: Идентификатор пользователя.
            statuses: Набор статусов сессии загрузки.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            operation: Название операции для сообщений об ошибках.

        Returns:
            Список сессий загрузки пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны или список
                статусов пустой.
        """

        self._validate_pagination(offset=offset, limit=limit)

        if not statuses:
            raise InvalidQueryError(
                "Список статусов сессий загрузки не может быть пустым.",
                repository=self.repository_name,
                operation=operation,
            )

        statement = (
            select(UploadSession)
            .where(
                UploadSession.user_id == user_id,
                UploadSession.status.in_(list(statuses)),
            )
            .order_by(UploadSession.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(statement, operation=operation)

    async def list_parent_sessions(
        self,
        parent_node_id: uuid.UUID,
        *,
        status: UploadSessionStatus | None = None,
        statuses: Sequence[UploadSessionStatus] | None = None,
        offset: int = 0,
        limit: int = 100,
        order_by_created_desc: bool = True,
    ) -> list[UploadSession]:
        """Возвращает сессии загрузки, связанные с родительским узлом.

        Обычно используется для получения загрузок внутри конкретной папки
        назначения. Нельзя одновременно передавать ``status`` и ``statuses``.

        Args:
            parent_node_id: Идентификатор родительского узла файловой системы.
            status: Один статус для фильтрации.
            statuses: Набор статусов для фильтрации.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            order_by_created_desc: Сортировать ли по дате создания по убыванию.

        Returns:
            Список сессий загрузки, связанных с указанным родительским узлом.

        Raises:
            InvalidQueryError: Если параметры фильтрации или пагинации
                некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        if status is not None and statuses is not None:
            raise InvalidQueryError(
                "Нельзя одновременно указывать status и statuses.",
                repository=self.repository_name,
                operation="list_parent_sessions",
            )

        statement = select(UploadSession).where(
            UploadSession.parent_node_id == parent_node_id,
        )

        if status is not None:
            statement = statement.where(UploadSession.status == status)

        if statuses is not None:
            if not statuses:
                raise InvalidQueryError(
                    "Список статусов сессий загрузки не может быть пустым.",
                    repository=self.repository_name,
                    operation="list_parent_sessions",
                )
            statement = statement.where(UploadSession.status.in_(list(statuses)))

        if order_by_created_desc:
            statement = statement.order_by(UploadSession.created_at.desc())
        else:
            statement = statement.order_by(UploadSession.created_at.asc())

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="list_parent_sessions",
        )

    async def list_by_status(
        self,
        status: UploadSessionStatus,
        *,
        offset: int = 0,
        limit: int = 100,
        order_by_created_desc: bool = True,
    ) -> list[UploadSession]:
        """Возвращает сессии загрузки с указанным статусом.

        Args:
            status: Статус сессии загрузки.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            order_by_created_desc: Сортировать ли по дате создания по убыванию.

        Returns:
            Список сессий загрузки с указанным статусом.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = select(UploadSession).where(UploadSession.status == status)

        if order_by_created_desc:
            statement = statement.order_by(UploadSession.created_at.desc())
        else:
            statement = statement.order_by(UploadSession.created_at.asc())

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="list_by_status",
        )

    # ------------------------------------------------------------------
    # Создание
    # ------------------------------------------------------------------

    async def create_session(
        self,
        *,
        user_id: uuid.UUID,
        parent_node_id: uuid.UUID,
        file_name: str,
        file_size_bytes: int,
        part_size_bytes: int,
        storage_bucket: str,
        storage_key: str,
        upload_id: str,
        parts_count: int,
        expires_at: datetime,
        mime_type: str | None = None,
        checksum: str | None = None,
        checksum_algorithm: str | None = None,
        status: UploadSessionStatus = UploadSessionStatus.CREATED,
        uploaded_parts_count: int = 0,
        uploaded_bytes: int = 0,
        client_ip: str | None = None,
        user_agent: str | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
        check_parent_exists: bool = True,
        check_duplicate_upload_id: bool = True,
    ) -> UploadSession:
        """Создаёт новую сессию multipart-загрузки.

        Перед созданием нормализует строковые значения, валидирует параметры
        сессии, при необходимости проверяет существование пользователя,
        родительского узла файловой системы и уникальность ``upload_id``.

        Args:
            user_id: Идентификатор пользователя.
            parent_node_id: Идентификатор папки назначения.
            file_name: Имя загружаемого файла.
            file_size_bytes: Размер файла в байтах.
            part_size_bytes: Размер одной части загрузки в байтах.
            storage_bucket: Bucket объектного хранилища.
            storage_key: Ключ объекта в хранилище.
            upload_id: Внешний идентификатор multipart-загрузки.
            parts_count: Общее количество частей загрузки.
            expires_at: Дата и время истечения сессии.
            mime_type: MIME-тип файла.
            checksum: Контрольная сумма файла.
            checksum_algorithm: Алгоритм контрольной суммы.
            status: Начальный статус сессии.
            uploaded_parts_count: Начальное количество загруженных частей.
            uploaded_bytes: Начальное количество загруженных байтов.
            client_ip: IP-адрес клиента.
            user_agent: User-Agent клиента.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_user_exists: Проверять ли существование пользователя.
            check_parent_exists: Проверять ли существование родительского узла.
            check_duplicate_upload_id: Проверять ли уникальность ``upload_id``.

        Returns:
            Созданная сессия загрузки.

        Raises:
            InvalidQueryError: Если параметры сессии некорректны.
            EntityNotFoundError: Если пользователь или родительский узел не найден.
            DuplicateEntityError: Если сессия с таким ``upload_id`` уже существует.
        """

        normalized_file_name = file_name.strip()
        normalized_bucket = storage_bucket.strip()
        normalized_key = storage_key.strip()
        normalized_upload_id = self._normalize_upload_id(upload_id)

        self._validate_session_values(
            file_name=normalized_file_name,
            file_size_bytes=file_size_bytes,
            part_size_bytes=part_size_bytes,
            parts_count=parts_count,
            uploaded_parts_count=uploaded_parts_count,
            uploaded_bytes=uploaded_bytes,
            storage_bucket=normalized_bucket,
            storage_key=normalized_key,
            upload_id=normalized_upload_id,
        )

        if check_user_exists:
            await self._ensure_user_exists(user_id)

        if check_parent_exists:
            await self._ensure_parent_node_exists(parent_node_id)

        if check_duplicate_upload_id and await self.is_upload_id_exists(
            normalized_upload_id,
        ):
            raise DuplicateEntityError(
                "UploadSession",
                field="upload_id",
                value=normalized_upload_id,
                repository=self.repository_name,
            )

        upload_session = UploadSession(
            user_id=user_id,
            parent_node_id=parent_node_id,
            file_name=normalized_file_name,
            file_size_bytes=file_size_bytes,
            part_size_bytes=part_size_bytes,
            mime_type=mime_type.strip() if mime_type else None,
            checksum=checksum.strip() if checksum else None,
            checksum_algorithm=checksum_algorithm.strip()
            if checksum_algorithm
            else None,
            storage_bucket=normalized_bucket,
            storage_key=normalized_key,
            upload_id=normalized_upload_id,
            status=status,
            parts_count=parts_count,
            uploaded_parts_count=uploaded_parts_count,
            uploaded_bytes=uploaded_bytes,
            expires_at=expires_at,
            client_ip=client_ip.strip() if client_ip else None,
            user_agent=user_agent.strip() if user_agent else None,
        )

        try:
            return await self.create(
                upload_session,
                flush=flush,
                refresh=refresh,
            )

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_session",
            ) from exc

    # ------------------------------------------------------------------
    # Изменение статуса
    # ------------------------------------------------------------------

    async def update_status(
        self,
        upload_session_id: uuid.UUID,
        status: UploadSessionStatus,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Обновляет статус сессии загрузки по идентификатору.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            status: Новый статус сессии.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        upload_session = await self.get_required_by_id(upload_session_id)

        return await self.update_status_for_session(
            upload_session,
            status,
            flush=flush,
            refresh=refresh,
        )

    async def update_status_for_session(
        self,
        upload_session: UploadSession,
        status: UploadSessionStatus,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Обновляет статус переданного объекта сессии загрузки.

        Args:
            upload_session: Сессия загрузки для обновления.
            status: Новый статус сессии.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.
        """

        upload_session.status = status

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def mark_uploading(
        self,
        upload_session_id: uuid.UUID,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Помечает сессию загрузки как выполняющуюся.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        upload_session = await self.get_required_by_id(upload_session_id)
        upload_session.mark_uploading()

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def mark_completed(
        self,
        upload_session_id: uuid.UUID,
        *,
        completed_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
        require_all_parts: bool = True,
    ) -> UploadSession:
        """Помечает сессию загрузки как завершённую.

        Если ``require_all_parts=True``, перед завершением проверяет, что
        загружены все части файла.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            completed_at: Дата завершения. Если не передана, используется
                текущее UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.
            require_all_parts: Требовать ли загрузку всех частей перед
                завершением.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия загрузки не найдена.
            InvalidQueryError: Если загружены не все части.
        """

        upload_session = await self.get_required_by_id(upload_session_id)

        if require_all_parts and not upload_session.all_parts_uploaded:
            raise InvalidQueryError(
                "Сессию загрузки нельзя завершить: загружены не все части.",
                repository=self.repository_name,
                operation="mark_completed",
                details={
                    "upload_session_id": str(upload_session_id),
                    "uploaded_parts_count": upload_session.uploaded_parts_count,
                    "parts_count": upload_session.parts_count,
                },
            )

        upload_session.complete(completed_at=completed_at or self._now())

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def mark_failed(
        self,
        upload_session_id: uuid.UUID,
        *,
        reason: str | None = None,
        failed_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Помечает сессию загрузки как завершившуюся ошибкой.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            reason: Причина ошибки.
            failed_at: Дата ошибки. Если не передана, используется текущее
                UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        upload_session = await self.get_required_by_id(upload_session_id)
        upload_session.fail(
            reason=reason.strip() if reason else None,
            failed_at=failed_at or self._now(),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def mark_aborted(
        self,
        upload_session_id: uuid.UUID,
        *,
        aborted_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Помечает сессию загрузки как отменённую.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            aborted_at: Дата отмены. Если не передана, используется текущее
                UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        upload_session = await self.get_required_by_id(upload_session_id)
        upload_session.abort(aborted_at=aborted_at or self._now())

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def mark_expired(
        self,
        upload_session_id: uuid.UUID,
        *,
        expired_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Помечает сессию загрузки как истёкшую.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            expired_at: Дата истечения. Если не передана, используется текущее
                UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        upload_session = await self.get_required_by_id(upload_session_id)
        upload_session.expire(expired_at=expired_at or self._now())

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def mark_expired_sessions(
        self,
        *,
        moment: datetime | None = None,
        statuses: Sequence[UploadSessionStatus] | None = None,
        limit: int = 1000,
        flush: bool = True,
    ) -> int:
        """Помечает просроченные активные сессии загрузки как ``EXPIRED``.

        По умолчанию обрабатывает сессии, найденные через
        ``find_expired_sessions``.

        Args:
            moment: Момент времени, относительно которого проверяется истечение.
            statuses: Статусы сессий, которые нужно проверять.
            limit: Максимальное количество сессий для обработки.
            flush: Выполнить ``flush`` после обновления.

        Returns:
            Количество сессий, помеченных как истёкшие.
        """

        expired_sessions = await self.find_expired_sessions(
            moment=moment,
            statuses=statuses,
            offset=0,
            limit=limit,
        )

        expired_at = moment or self._now()

        for upload_session in expired_sessions:
            upload_session.expire(expired_at=expired_at)

        if flush:
            await self.flush()

        return len(expired_sessions)

    # ------------------------------------------------------------------
    # Работа со счётчиками загруженных частей и байтов
    # ------------------------------------------------------------------

    async def register_uploaded_part(
        self,
        upload_session_id: uuid.UUID,
        *,
        part_size_bytes: int,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Регистрирует загруженную часть в счётчиках сессии.

        Метод получает сессию с блокировкой строки ``FOR UPDATE``, чтобы
        снизить риск некорректного счётчика при параллельной отметке частей.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            part_size_bytes: Размер загруженной части в байтах.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            InvalidQueryError: Если размер части отрицательный.
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        if part_size_bytes < 0:
            raise InvalidQueryError(
                "Размер загруженной части не может быть отрицательным.",
                repository=self.repository_name,
                operation="register_uploaded_part",
                details={
                    "upload_session_id": str(upload_session_id),
                    "part_size_bytes": part_size_bytes,
                },
            )

        upload_session = await self._get_required_for_update(
            upload_session_id,
            operation="register_uploaded_part",
        )

        upload_session.register_uploaded_part(part_size_bytes)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def unregister_uploaded_part(
        self,
        upload_session_id: uuid.UUID,
        *,
        part_size_bytes: int,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Откатывает регистрацию загруженной части в счётчиках сессии.

        Метод используется, когда ранее зарегистрированная часть должна быть
        исключена из прогресса загрузки.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            part_size_bytes: Размер части в байтах.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            InvalidQueryError: Если размер части отрицательный.
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        if part_size_bytes < 0:
            raise InvalidQueryError(
                "Размер части не может быть отрицательным.",
                repository=self.repository_name,
                operation="unregister_uploaded_part",
                details={
                    "upload_session_id": str(upload_session_id),
                    "part_size_bytes": part_size_bytes,
                },
            )

        upload_session = await self._get_required_for_update(
            upload_session_id,
            operation="unregister_uploaded_part",
        )

        upload_session.unregister_uploaded_part(part_size_bytes)

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def increment_uploaded_parts_count(
        self,
        upload_session_id: uuid.UUID,
        *,
        increment_by: int = 1,
        uploaded_bytes_increment: int = 0,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Увеличивает количество загруженных частей и загруженных байтов.

        Метод получает сессию с блокировкой строки ``FOR UPDATE``.
        Если сессия находится в статусе ``CREATED``, она переводится
        в ``UPLOADING``.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            increment_by: Количество частей, на которое нужно увеличить счётчик.
            uploaded_bytes_increment: Количество байтов, на которое нужно
                увеличить прогресс.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            InvalidQueryError: Если значения прироста некорректны или итоговое
                количество частей превышает общее количество частей.
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        if increment_by <= 0:
            raise InvalidQueryError(
                "Значение increment_by должно быть положительным.",
                repository=self.repository_name,
                operation="increment_uploaded_parts_count",
                details={
                    "upload_session_id": str(upload_session_id),
                    "increment_by": increment_by,
                },
            )

        if uploaded_bytes_increment < 0:
            raise InvalidQueryError(
                "Прирост uploaded_bytes не может быть отрицательным.",
                repository=self.repository_name,
                operation="increment_uploaded_parts_count",
                details={
                    "upload_session_id": str(upload_session_id),
                    "uploaded_bytes_increment": uploaded_bytes_increment,
                },
            )

        upload_session = await self._get_required_for_update(
            upload_session_id,
            operation="increment_uploaded_parts_count",
        )

        new_count = upload_session.uploaded_parts_count + increment_by

        if new_count > upload_session.parts_count:
            raise InvalidQueryError(
                "Количество загруженных частей не может превышать общее количество частей.",
                repository=self.repository_name,
                operation="increment_uploaded_parts_count",
                details={
                    "upload_session_id": str(upload_session_id),
                    "uploaded_parts_count": upload_session.uploaded_parts_count,
                    "increment_by": increment_by,
                    "parts_count": upload_session.parts_count,
                },
            )

        upload_session.uploaded_parts_count = new_count
        upload_session.uploaded_bytes = min(
            upload_session.uploaded_bytes + uploaded_bytes_increment,
            upload_session.file_size_bytes,
        )

        if upload_session.status == UploadSessionStatus.CREATED:
            upload_session.status = UploadSessionStatus.UPLOADING

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def set_uploaded_parts_count(
        self,
        upload_session_id: uuid.UUID,
        uploaded_parts_count: int,
        *,
        uploaded_bytes: int | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Устанавливает точное количество загруженных частей и байтов.

        Метод полезен после пересчёта состояния по таблице ``upload_parts``.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            uploaded_parts_count: Новое количество загруженных частей.
            uploaded_bytes: Новое количество загруженных байтов.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            InvalidQueryError: Если значения прогресса некорректны.
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        upload_session = await self._get_required_for_update(
            upload_session_id,
            operation="set_uploaded_parts_count",
        )

        self._validate_progress_values(
            upload_session=upload_session,
            uploaded_parts_count=uploaded_parts_count,
            uploaded_bytes=uploaded_bytes,
            operation="set_uploaded_parts_count",
        )

        upload_session.uploaded_parts_count = uploaded_parts_count

        if uploaded_bytes is not None:
            upload_session.uploaded_bytes = uploaded_bytes

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_session)

        return upload_session

    async def recalculate_progress_from_parts(
        self,
        upload_session_id: uuid.UUID,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadSession:
        """Пересчитывает прогресс сессии по таблице ``upload_parts``.

        Учитываются только части со статусом ``UPLOADED``. Метод обновляет
        количество загруженных частей и сумму загруженных байтов.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия загрузки не найдена.
            RepositoryError: Если произошла ошибка при выполнении SQL-запроса.
        """

        upload_session = await self._get_required_for_update(
            upload_session_id,
            operation="recalculate_progress_from_parts",
        )

        try:
            statement = select(
                func.count(UploadPart.id),
                func.coalesce(func.sum(UploadPart.size_bytes), 0),
            ).where(
                UploadPart.upload_session_id == upload_session_id,
                UploadPart.status == UploadPartStatus.UPLOADED,
            )

            result = await self.session.execute(statement)
            uploaded_parts_count, uploaded_bytes = result.one()

            upload_session.uploaded_parts_count = int(uploaded_parts_count)
            upload_session.uploaded_bytes = int(uploaded_bytes or 0)

            if (
                upload_session.status == UploadSessionStatus.CREATED
                and uploaded_parts_count
            ):
                upload_session.status = UploadSessionStatus.UPLOADING

            if flush:
                await self.flush()

            if refresh:
                await self.refresh(upload_session)

            return upload_session

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="recalculate_progress_from_parts",
                reason=str(exc),
                details={"upload_session_id": str(upload_session_id)},
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Поиск служебных сессий
    # ------------------------------------------------------------------

    async def find_expired_sessions(
        self,
        *,
        moment: datetime | None = None,
        statuses: Sequence[UploadSessionStatus] | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[UploadSession]:
        """Возвращает сессии загрузки, срок действия которых истёк.

        По умолчанию ищет незавершённые активные сессии в статусах ``CREATED``
        и ``UPLOADING``.

        Args:
            moment: Момент времени для проверки истечения срока действия.
            statuses: Статусы сессий, которые нужно проверять.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список просроченных сессий загрузки.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны или передан
                пустой список статусов.
        """

        self._validate_pagination(offset=offset, limit=limit)

        if statuses is not None and not statuses:
            raise InvalidQueryError(
                "Список статусов не может быть пустым.",
                repository=self.repository_name,
                operation="find_expired_sessions",
            )

        checked_statuses = list(
            statuses
            or [
                UploadSessionStatus.CREATED,
                UploadSessionStatus.UPLOADING,
            ],
        )

        statement = (
            select(UploadSession)
            .where(
                UploadSession.status.in_(checked_statuses),
                UploadSession.expires_at <= (moment or self._now()),
            )
            .order_by(UploadSession.expires_at.asc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="find_expired_sessions",
        )

    async def find_unfinished_sessions(
        self,
        *,
        user_id: uuid.UUID | None = None,
        parent_node_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[UploadSession]:
        """Возвращает незавершённые сессии загрузки.

        Незавершёнными считаются сессии, статус которых не входит в список
        терминальных статусов.

        Args:
            user_id: Фильтр по идентификатору пользователя.
            parent_node_id: Фильтр по родительскому узлу файловой системы.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список незавершённых сессий загрузки.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = select(UploadSession).where(
            UploadSession.status.notin_(self._terminal_statuses()),
        )

        if user_id is not None:
            statement = statement.where(UploadSession.user_id == user_id)

        if parent_node_id is not None:
            statement = statement.where(
                UploadSession.parent_node_id == parent_node_id,
            )

        statement = (
            statement.order_by(UploadSession.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="find_unfinished_sessions",
        )

    async def find_ready_to_complete_sessions(
        self,
        *,
        moment: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[UploadSession]:
        """Возвращает сессии, которые потенциально готовы к завершению.

        В выборку попадают нетерминальные и неистёкшие сессии, у которых
        количество загруженных частей равно общему количеству частей.

        Args:
            moment: Момент времени для проверки срока действия.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список сессий, потенциально готовых к завершению.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        checked_moment = moment or self._now()

        statement = (
            select(UploadSession)
            .where(
                UploadSession.status.notin_(self._terminal_statuses()),
                UploadSession.expires_at > checked_moment,
                UploadSession.uploaded_parts_count == UploadSession.parts_count,
            )
            .order_by(UploadSession.created_at.asc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="find_ready_to_complete_sessions",
        )

    # ------------------------------------------------------------------
    # Проверки состояния
    # ------------------------------------------------------------------

    async def can_complete_session(
        self,
        upload_session_id: uuid.UUID,
        *,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет, может ли сессия загрузки быть завершена.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            moment: Момент времени для проверки состояния.

        Returns:
            ``True``, если сессия существует и может быть завершена,
            иначе ``False``.
        """

        upload_session = await self.get_by_id(upload_session_id)

        if upload_session is None:
            return False

        return upload_session.can_be_completed_at(moment or self._now())

    async def can_receive_parts(
        self,
        upload_session_id: uuid.UUID,
        *,
        moment: datetime | None = None,
    ) -> bool:
        """Проверяет, может ли сессия загрузки принимать части.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            moment: Момент времени для проверки состояния.

        Returns:
            ``True``, если сессия существует и может принимать части,
            иначе ``False``.
        """

        upload_session = await self.get_by_id(upload_session_id)

        if upload_session is None:
            return False

        return upload_session.can_receive_parts_at(moment or self._now())

    # ------------------------------------------------------------------
    # Подсчёт
    # ------------------------------------------------------------------

    async def count_user_sessions(
        self,
        user_id: uuid.UUID,
    ) -> int:
        """Возвращает количество сессий загрузки пользователя.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Количество сессий загрузки пользователя.
        """

        return await self.count(UploadSession.user_id == user_id)

    async def count_user_active_sessions(
        self,
        user_id: uuid.UUID,
        *,
        moment: datetime | None = None,
    ) -> int:
        """Возвращает количество активных неистёкших сессий загрузки пользователя.

        Активными считаются сессии в статусах ``CREATED`` и ``UPLOADING``,
        срок действия которых ещё не истёк.

        Args:
            user_id: Идентификатор пользователя.
            moment: Момент времени для проверки истечения срока действия.

        Returns:
            Количество активных неистёкших сессий загрузки пользователя.
        """

        checked_moment = moment or self._now()

        return await self.count(
            UploadSession.user_id == user_id,
            UploadSession.status.in_(
                [
                    UploadSessionStatus.CREATED,
                    UploadSessionStatus.UPLOADING,
                ],
            ),
            UploadSession.expires_at > checked_moment,
        )

    async def count_by_status(
        self,
        status: UploadSessionStatus,
    ) -> int:
        """Возвращает количество сессий загрузки с указанным статусом.

        Args:
            status: Статус сессии загрузки.

        Returns:
            Количество сессий загрузки с указанным статусом.
        """

        return await self.count(UploadSession.status == status)

    async def search_user_sessions(
        self,
        *,
        user_id: uuid.UUID,
        parent_node_id: uuid.UUID | None = None,
        status: UploadSessionStatus | None = None,
        include_terminal: bool = True,
        filename_query: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        expires_before: datetime | None = None,
        sort_by: str = "created_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> list[UploadSession]:
        """Ищет upload-сессии пользователя по фильтрам.

        Возвращает страницу upload-сессий указанного пользователя. Поддерживает
        фильтрацию по родительскому узлу, статусу, имени файла, диапазону даты
        создания и сроку истечения сессии. Если ``status`` не указан и
        ``include_terminal=False``, терминальные upload-сессии исключаются
        из результата.

        Args:
            user_id: Идентификатор пользователя, чьи upload-сессии нужно найти.
            parent_node_id: Идентификатор родительского узла для фильтрации.
                Если ``None``, фильтр по родителю не применяется.
            status: Статус upload-сессии для фильтрации. Если ``None``, фильтр
                по конкретному статусу не применяется.
            include_terminal: Включать ли терминальные upload-сессии, если
                ``status`` не указан.
            filename_query: Подстрока для поиска по имени файла без учёта
                регистра. Если ``None`` или пустая строка, фильтр по имени
                файла не применяется.
            created_from: Нижняя граница даты создания upload-сессии
                включительно.
            created_to: Верхняя граница даты создания upload-сессии включительно.
            expires_before: Верхняя граница срока истечения upload-сессии
                включительно.
            sort_by: Поле сортировки. Поддерживаются ``created_at``,
                ``expires_at``, ``file_name`` и ``status``. Если поле
                неизвестно, используется ``created_at``.
            sort_desc: Сортировать ли по убыванию.
            offset: Смещение для постраничной выдачи.
            limit: Максимальное количество upload-сессий в результате.

        Returns:
            Список upload-сессий пользователя, соответствующих фильтрам.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
            RepositoryError: Если не удалось выполнить запрос к базе данных.
        """

        self._validate_pagination(offset=offset, limit=limit)
        statement = select(UploadSession).where(UploadSession.user_id == user_id)

        if parent_node_id is not None:
            statement = statement.where(UploadSession.parent_node_id == parent_node_id)
        if status is not None:
            statement = statement.where(UploadSession.status == status)
        elif not include_terminal:
            statement = statement.where(
                UploadSession.status.notin_(self._terminal_statuses())
            )
        if filename_query:
            statement = statement.where(
                func.lower(UploadSession.file_name).contains(
                    filename_query.strip().lower()
                )
            )
        if created_from is not None:
            statement = statement.where(UploadSession.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(UploadSession.created_at <= created_to)
        if expires_before is not None:
            statement = statement.where(UploadSession.expires_at <= expires_before)

        sortable: dict[str, Any] = {
            "created_at": UploadSession.created_at,
            "expires_at": UploadSession.expires_at,
            "file_name": func.lower(UploadSession.file_name),
            "status": cast(String, UploadSession.status),
        }
        column = sortable.get(sort_by.strip().lower(), UploadSession.created_at)
        statement = statement.order_by(column.desc() if sort_desc else column.asc())
        statement = statement.offset(offset).limit(limit)
        return await self.scalars_all(statement, operation="search_user_sessions")

    async def count_user_sessions_filtered(
        self,
        *,
        user_id: uuid.UUID,
        parent_node_id: uuid.UUID | None = None,
        status: UploadSessionStatus | None = None,
        include_terminal: bool = True,
        filename_query: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        expires_before: datetime | None = None,
    ) -> int:
        """Считает upload-сессии пользователя по фильтрам.

        Возвращает количество upload-сессий указанного пользователя с теми же
        фильтрами, которые используются при поиске сессий. Если ``status``
        не указан и ``include_terminal=False``, терминальные upload-сессии
        не учитываются.

        Args:
            user_id: Идентификатор пользователя, чьи upload-сессии нужно
                посчитать.
            parent_node_id: Идентификатор родительского узла для фильтрации.
                Если ``None``, фильтр по родителю не применяется.
            status: Статус upload-сессии для фильтрации. Если ``None``, фильтр
                по конкретному статусу не применяется.
            include_terminal: Учитывать ли терминальные upload-сессии, если
                ``status`` не указан.
            filename_query: Подстрока для поиска по имени файла без учёта
                регистра. Если ``None`` или пустая строка, фильтр по имени
                файла не применяется.
            created_from: Нижняя граница даты создания upload-сессии
                включительно.
            created_to: Верхняя граница даты создания upload-сессии включительно.
            expires_before: Верхняя граница срока истечения upload-сессии
                включительно.

        Returns:
            Количество upload-сессий пользователя, соответствующих фильтрам.

        Raises:
            RepositoryError: Если не удалось выполнить запрос к базе данных.
        """

        statement = (
            select(func.count())
            .select_from(UploadSession)
            .where(UploadSession.user_id == user_id)
        )
        if parent_node_id is not None:
            statement = statement.where(UploadSession.parent_node_id == parent_node_id)
        if status is not None:
            statement = statement.where(UploadSession.status == status)
        elif not include_terminal:
            statement = statement.where(
                UploadSession.status.notin_(self._terminal_statuses())
            )
        if filename_query:
            statement = statement.where(
                func.lower(UploadSession.file_name).contains(
                    filename_query.strip().lower()
                )
            )
        if created_from is not None:
            statement = statement.where(UploadSession.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(UploadSession.created_at <= created_to)
        if expires_before is not None:
            statement = statement.where(UploadSession.expires_at <= expires_before)

        result = await self.session.execute(statement)
        return int(result.scalar_one() or 0)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    async def _get_required_for_update(
        self,
        upload_session_id: uuid.UUID,
        *,
        operation: str,
    ) -> UploadSession:
        """Возвращает сессию загрузки с блокировкой строки ``FOR UPDATE``.

        Используется для операций, изменяющих счётчики прогресса, чтобы снизить
        риск конфликтов при параллельных обновлениях.

        Args:
            upload_session_id: Идентификатор сессии загрузки.
            operation: Название операции для сообщений об ошибках.

        Returns:
            Найденная сессия загрузки.

        Raises:
            EntityNotFoundError: Если сессия загрузки не найдена.
        """

        statement = (
            select(UploadSession)
            .where(UploadSession.id == upload_session_id)
            .with_for_update()
        )

        upload_session = await self.scalar_one_or_none(
            statement,
            operation=operation,
        )

        if upload_session is None:
            raise EntityNotFoundError(
                self.model_name,
                entity_id=upload_session_id,
                repository=self.repository_name,
            )

        return upload_session

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

    async def _ensure_parent_node_exists(
        self,
        parent_node_id: uuid.UUID,
    ) -> None:
        """Проверяет существование родительского узла файловой системы.

        Args:
            parent_node_id: Идентификатор родительского узла файловой системы.

        Raises:
            EntityNotFoundError: Если родительский узел не найден.
            RepositoryError: Если произошла ошибка при обращении к базе данных.
        """

        try:
            parent_node = await self.session.get(FileSystemNode, parent_node_id)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="_ensure_parent_node_exists",
                reason=str(exc),
                details={"parent_node_id": str(parent_node_id)},
                cause=exc,
            ) from exc

        if parent_node is None:
            raise EntityNotFoundError(
                "FileSystemNode",
                entity_id=parent_node_id,
                repository=self.repository_name,
            )

    def _validate_session_values(
        self,
        *,
        file_name: str,
        file_size_bytes: int,
        part_size_bytes: int,
        parts_count: int,
        uploaded_parts_count: int,
        uploaded_bytes: int,
        storage_bucket: str,
        storage_key: str,
        upload_id: str,
    ) -> None:
        """Валидирует значения новой сессии multipart-загрузки.

        Проверяет имя файла, размеры, количество частей, начальный прогресс,
        bucket, storage key и ``upload_id``.

        Args:
            file_name: Имя загружаемого файла.
            file_size_bytes: Размер файла в байтах.
            part_size_bytes: Размер части в байтах.
            parts_count: Общее количество частей.
            uploaded_parts_count: Количество уже загруженных частей.
            uploaded_bytes: Количество уже загруженных байтов.
            storage_bucket: Bucket объектного хранилища.
            storage_key: Ключ объекта в хранилище.
            upload_id: Внешний идентификатор multipart-загрузки.

        Raises:
            InvalidQueryError: Если одно из значений некорректно.
        """

        if not file_name:
            raise InvalidQueryError(
                "Имя загружаемого файла не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_session_values",
            )

        if len(file_name) > 255:
            raise InvalidQueryError(
                "Имя загружаемого файла превышает допустимую длину.",
                repository=self.repository_name,
                operation="_validate_session_values",
                details={"max_length": 255, "actual_length": len(file_name)},
            )

        if file_size_bytes < 0:
            raise InvalidQueryError(
                "Размер файла не может быть отрицательным.",
                repository=self.repository_name,
                operation="_validate_session_values",
                details={"file_size_bytes": file_size_bytes},
            )

        if part_size_bytes <= 0:
            raise InvalidQueryError(
                "Размер части загрузки должен быть положительным.",
                repository=self.repository_name,
                operation="_validate_session_values",
                details={"part_size_bytes": part_size_bytes},
            )

        if parts_count <= 0:
            raise InvalidQueryError(
                "Количество частей загрузки должно быть положительным.",
                repository=self.repository_name,
                operation="_validate_session_values",
                details={"parts_count": parts_count},
            )

        if uploaded_parts_count < 0:
            raise InvalidQueryError(
                "Количество загруженных частей не может быть отрицательным.",
                repository=self.repository_name,
                operation="_validate_session_values",
                details={"uploaded_parts_count": uploaded_parts_count},
            )

        if uploaded_parts_count > parts_count:
            raise InvalidQueryError(
                "Количество загруженных частей не может превышать общее количество частей.",
                repository=self.repository_name,
                operation="_validate_session_values",
                details={
                    "uploaded_parts_count": uploaded_parts_count,
                    "parts_count": parts_count,
                },
            )

        if uploaded_bytes < 0:
            raise InvalidQueryError(
                "Количество загруженных байтов не может быть отрицательным.",
                repository=self.repository_name,
                operation="_validate_session_values",
                details={"uploaded_bytes": uploaded_bytes},
            )

        if uploaded_bytes > file_size_bytes:
            raise InvalidQueryError(
                "Количество загруженных байтов не может превышать размер файла.",
                repository=self.repository_name,
                operation="_validate_session_values",
                details={
                    "uploaded_bytes": uploaded_bytes,
                    "file_size_bytes": file_size_bytes,
                },
            )

        if not storage_bucket:
            raise InvalidQueryError(
                "Bucket хранилища не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_session_values",
            )

        if not storage_key:
            raise InvalidQueryError(
                "Ключ объекта хранилища не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_session_values",
            )

        if not upload_id:
            raise InvalidQueryError(
                "upload_id не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_session_values",
            )

    def _validate_progress_values(
        self,
        *,
        upload_session: UploadSession,
        uploaded_parts_count: int,
        uploaded_bytes: int | None,
        operation: str,
    ) -> None:
        """Валидирует значения прогресса загрузки.

        Проверяет, что количество загруженных частей и байтов не отрицательное
        и не превышает допустимые значения для сессии.

        Args:
            upload_session: Сессия загрузки, относительно которой выполняется
                проверка.
            uploaded_parts_count: Количество загруженных частей.
            uploaded_bytes: Количество загруженных байтов.
            operation: Название операции для сообщений об ошибках.

        Raises:
            InvalidQueryError: Если значения прогресса некорректны.
        """

        if uploaded_parts_count < 0:
            raise InvalidQueryError(
                "Количество загруженных частей не может быть отрицательным.",
                repository=self.repository_name,
                operation=operation,
                details={"uploaded_parts_count": uploaded_parts_count},
            )

        if uploaded_parts_count > upload_session.parts_count:
            raise InvalidQueryError(
                "Количество загруженных частей не может превышать общее количество частей.",
                repository=self.repository_name,
                operation=operation,
                details={
                    "uploaded_parts_count": uploaded_parts_count,
                    "parts_count": upload_session.parts_count,
                },
            )

        if uploaded_bytes is not None:
            if uploaded_bytes < 0:
                raise InvalidQueryError(
                    "Количество загруженных байтов не может быть отрицательным.",
                    repository=self.repository_name,
                    operation=operation,
                    details={"uploaded_bytes": uploaded_bytes},
                )

            if uploaded_bytes > upload_session.file_size_bytes:
                raise InvalidQueryError(
                    "Количество загруженных байтов не может превышать размер файла.",
                    repository=self.repository_name,
                    operation=operation,
                    details={
                        "uploaded_bytes": uploaded_bytes,
                        "file_size_bytes": upload_session.file_size_bytes,
                    },
                )

    def _normalize_upload_id(
        self,
        upload_id: str,
    ) -> str:
        """Нормализует внешний идентификатор multipart-загрузки.

        Args:
            upload_id: Внешний идентификатор multipart-загрузки.

        Returns:
            Нормализованный ``upload_id``.
        """

        return upload_id.strip()

    def _base_select(self) -> Select[tuple[UploadSession]]:
        """Создаёт базовый ``SELECT``-запрос для модели ``UploadSession``.

        Returns:
            SQLAlchemy ``SELECT``-запрос для выборки сессий загрузки.
        """

        return select(UploadSession)

    @staticmethod
    def _now() -> datetime:
        """Возвращает текущее время в UTC.

        Returns:
            Текущая дата и время с timezone UTC.
        """

        return datetime.now(UTC)

    @staticmethod
    def _terminal_statuses() -> list[UploadSessionStatus]:
        """Возвращает терминальные статусы сессии загрузки.

        Терминальные статусы означают, что сессия больше не считается активной
        или незавершённой.

        Returns:
            Список терминальных статусов сессии загрузки.
        """

        return [
            UploadSessionStatus.COMPLETED,
            UploadSessionStatus.FAILED,
            UploadSessionStatus.ABORTED,
            UploadSessionStatus.EXPIRED,
        ]
