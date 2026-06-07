from __future__ import annotations

import uuid
from typing import Any, TypedDict

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import (
    FilePreviewStatus,
    FileProcessingStatus,
    NodeType,
    NodeVisibility,
    StorageObjectStatus,
)
from database.models.filesystem import File, FileSystemNode
from database.repositories.base import BaseRepository
from database.repositories.nodes import FileSystemNodeRepository


class FileStorageInfo(TypedDict):
    """Информация о расположении и состоянии файла в объектном хранилище.

    Используется как структурированный результат для методов, которым нужно
    вернуть storage-метаданные файла без передачи полного ORM-объекта.

    Attributes:
        storage_bucket: Bucket объектного хранилища.
        storage_key: Ключ объекта в хранилище.
        size_bytes: Размер файла в байтах.
        checksum: Контрольная сумма файла.
        checksum_algorithm: Алгоритм контрольной суммы.
        mime_type: MIME-тип файла.
        extension: Расширение файла без ведущей точки.
        storage_status: Статус физического объекта в хранилище.
        processing_status: Статус обработки файла.
        preview_status: Статус предпросмотра файла.
        preview_storage_key: Ключ предпросмотра в объектном хранилище.
        current_version_id: Идентификатор текущей версии файла.
    """

    storage_bucket: str
    storage_key: str
    size_bytes: int
    checksum: str | None
    checksum_algorithm: str | None
    mime_type: str | None
    extension: str | None
    storage_status: StorageObjectStatus
    processing_status: FileProcessingStatus
    preview_status: FilePreviewStatus
    preview_storage_key: str | None
    current_version_id: uuid.UUID | None


class FileRepository(BaseRepository[File]):
    """Репозиторий для работы с файлами.

    Инкапсулирует операции получения, создания, обновления storage-информации,
    изменения метаданных, управления статусами, поиска, проверки, выборки,
    подсчёта и удаления записей файлов.

    Работает с моделью ``File`` и связанным узлом ``FileSystemNode``.
    Создание и операции над узлами файловой системы делегируются в
    ``FileSystemNodeRepository``.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий файлов.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=File)
        self.nodes = FileSystemNodeRepository(session=session)

    # ------------------------------------------------------------------
    # Получение файлов
    # ------------------------------------------------------------------

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> File | None:
        """Возвращает файл по идентификатору записи ``files``.

        Дополнительно загружает связанный узел файловой системы, текущую версию
        и список версий файла.

        Args:
            entity_id: Идентификатор записи файла.

        Returns:
            Файл, если он найден, иначе ``None``.
        """

        statement = (
            select(File)
            .where(File.id == entity_id)
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
                selectinload(File.versions),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_id",
        )

    async def get_required_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> File:
        """Возвращает файл по идентификатору записи ``files``.

        Args:
            entity_id: Идентификатор записи файла.

        Returns:
            Найденный файл.

        Raises:
            EntityNotFoundError: Если файл не найден.
        """

        file = await self.get_by_id(entity_id)

        if file is None:
            raise EntityNotFoundError(
                "File",
                entity_id=entity_id,
                repository=self.repository_name,
            )

        return file

    async def get_by_node_id(
        self,
        node_id: uuid.UUID,
        *,
        include_deleted_node: bool = True,
    ) -> File | None:
        """Возвращает файл по идентификатору связанного узла файловой системы.

        Учитываются только узлы типа ``FILE``.

        Args:
            node_id: Идентификатор узла файловой системы.
            include_deleted_node: Включать ли файлы, чей узел помечен удалённым.

        Returns:
            Файл, если он найден, иначе ``None``.
        """

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(
                File.node_id == node_id,
                FileSystemNode.node_type == NodeType.FILE,
            )
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
                selectinload(File.versions),
            )
        )

        if not include_deleted_node:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_node_id",
        )

    async def get_required_by_node_id(
        self,
        node_id: uuid.UUID,
        *,
        include_deleted_node: bool = True,
    ) -> File:
        """Возвращает файл по идентификатору связанного узла файловой системы.

        Args:
            node_id: Идентификатор узла файловой системы.
            include_deleted_node: Включать ли файлы, чей узел помечен удалённым.

        Returns:
            Найденный файл.

        Raises:
            EntityNotFoundError: Если файл не найден.
        """

        file = await self.get_by_node_id(
            node_id,
            include_deleted_node=include_deleted_node,
        )

        if file is None:
            raise EntityNotFoundError(
                "File",
                lookup={"node_id": str(node_id)},
                repository=self.repository_name,
            )

        return file

    async def get_active_by_node_id(
        self,
        node_id: uuid.UUID,
    ) -> File | None:
        """Возвращает файл по ``node_id``, только если связанный узел не удалён.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            Активный файл, если он найден, иначе ``None``.
        """

        return await self.get_by_node_id(
            node_id,
            include_deleted_node=False,
        )

    async def get_required_active_by_node_id(
        self,
        node_id: uuid.UUID,
    ) -> File:
        """Возвращает активный файл по ``node_id``.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            Найденный активный файл.

        Raises:
            EntityNotFoundError: Если активный файл не найден.
        """

        file = await self.get_active_by_node_id(node_id)

        if file is None:
            raise EntityNotFoundError(
                "File",
                lookup={"node_id": str(node_id), "active": True},
                repository=self.repository_name,
                message="Активный файл не найден.",
            )

        return file

    async def get_by_storage_key(
        self,
        *,
        storage_bucket: str,
        storage_key: str,
    ) -> File | None:
        """Возвращает файл по bucket/key объектного хранилища.

        Args:
            storage_bucket: Bucket объектного хранилища.
            storage_key: Ключ объекта в хранилище.

        Returns:
            Файл, если он найден, иначе ``None``.

        Raises:
            InvalidQueryError: Если bucket или storage key некорректны.
        """

        statement = (
            select(File)
            .where(
                File.storage_bucket == self._validate_storage_bucket(storage_bucket),
                File.storage_key == self._validate_storage_key(storage_key),
            )
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_storage_key",
        )

    async def get_required_by_storage_key(
        self,
        *,
        storage_bucket: str,
        storage_key: str,
    ) -> File:
        """Возвращает файл по bucket/key объектного хранилища.

        Args:
            storage_bucket: Bucket объектного хранилища.
            storage_key: Ключ объекта в хранилище.

        Returns:
            Найденный файл.

        Raises:
            InvalidQueryError: Если bucket или storage key некорректны.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self.get_by_storage_key(
            storage_bucket=storage_bucket,
            storage_key=storage_key,
        )

        if file is None:
            raise EntityNotFoundError(
                "File",
                lookup={
                    "storage_bucket": storage_bucket,
                    "storage_key": storage_key,
                },
                repository=self.repository_name,
            )

        return file

    # ------------------------------------------------------------------
    # Создание файлов
    # ------------------------------------------------------------------

    async def create_file(
        self,
        *,
        node_id: uuid.UUID,
        storage_bucket: str,
        storage_key: str,
        size_bytes: int,
        mime_type: str | None = None,
        extension: str | None = None,
        checksum: str | None = None,
        checksum_algorithm: str | None = None,
        storage_status: StorageObjectStatus = StorageObjectStatus.AVAILABLE,
        processing_status: FileProcessingStatus = FileProcessingStatus.READY,
        preview_status: FilePreviewStatus = FilePreviewStatus.NOT_REQUIRED,
        preview_storage_key: str | None = None,
        current_version_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
        validate_node: bool = True,
        check_duplicate_node: bool = True,
    ) -> File:
        """Создаёт запись файла для существующего узла файловой системы.

        Метод не создаёт ``FileSystemNode``. Узел должен быть создан заранее
        через ``FileSystemNodeRepository`` и иметь тип ``FILE``.

        Args:
            node_id: Идентификатор узла файла.
            storage_bucket: Bucket объектного хранилища.
            storage_key: Ключ объекта в хранилище.
            size_bytes: Размер файла в байтах.
            mime_type: MIME-тип файла.
            extension: Расширение файла без ведущей точки.
            checksum: Контрольная сумма файла.
            checksum_algorithm: Алгоритм контрольной суммы.
            storage_status: Начальный статус объекта в хранилище.
            processing_status: Начальный статус обработки файла.
            preview_status: Начальный статус предпросмотра файла.
            preview_storage_key: Ключ предпросмотра в объектном хранилище.
            current_version_id: Идентификатор текущей версии файла.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            validate_node: Проверять ли существование и тип узла.
            check_duplicate_node: Проверять ли наличие уже существующей записи
                файла для узла.

        Returns:
            Созданный файл.

        Raises:
            EntityNotFoundError: Если узел не найден.
            InvalidQueryError: Если узел не является файлом или входные значения
                некорректны.
            DuplicateEntityError: Если для узла уже существует запись файла
                или storage key уже используется.
        """

        if validate_node:
            await self._validate_file_node(
                node_id,
                check_duplicate=check_duplicate_node,
            )

        file = File(
            node_id=node_id,
            storage_bucket=self._validate_storage_bucket(storage_bucket),
            storage_key=self._validate_storage_key(storage_key),
            size_bytes=self._validate_size_bytes(size_bytes),
            mime_type=self._normalize_mime_type(mime_type),
            extension=self._normalize_extension(extension),
            checksum=self._normalize_checksum(checksum),
            checksum_algorithm=self._normalize_checksum_algorithm(
                checksum_algorithm,
            ),
            storage_status=storage_status,
            processing_status=processing_status,
            preview_status=preview_status,
            preview_storage_key=self._normalize_storage_key_optional(
                preview_storage_key,
            ),
            current_version_id=current_version_id,
        )

        return await self.create(
            file,
            flush=flush,
            refresh=refresh,
        )

    async def create_file_with_node(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        storage_bucket: str,
        storage_key: str,
        size_bytes: int,
        parent_id: uuid.UUID | None = None,
        mime_type: str | None = None,
        extension: str | None = None,
        checksum: str | None = None,
        checksum_algorithm: str | None = None,
        storage_status: StorageObjectStatus = StorageObjectStatus.AVAILABLE,
        processing_status: FileProcessingStatus = FileProcessingStatus.READY,
        preview_status: FilePreviewStatus = FilePreviewStatus.NOT_REQUIRED,
        preview_storage_key: str | None = None,
        current_version_id: uuid.UUID | None = None,
        visibility: NodeVisibility = NodeVisibility.PRIVATE,
        created_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_conflict: bool = True,
        check_owner_exists: bool = False,
    ) -> File:
        """Создаёт узел файла и связанную запись ``files``.

        Операция сначала создаёт ``FileSystemNode`` типа ``FILE``, затем создаёт
        связанную запись ``File``.

        Args:
            owner_id: Идентификатор владельца файла.
            name: Имя файлового узла.
            storage_bucket: Bucket объектного хранилища.
            storage_key: Ключ объекта в хранилище.
            size_bytes: Размер файла в байтах.
            parent_id: Идентификатор родительской папки.
            mime_type: MIME-тип файла.
            extension: Расширение файла.
            checksum: Контрольная сумма файла.
            checksum_algorithm: Алгоритм контрольной суммы.
            storage_status: Начальный статус объекта в хранилище.
            processing_status: Начальный статус обработки файла.
            preview_status: Начальный статус предпросмотра файла.
            preview_storage_key: Ключ предпросмотра в объектном хранилище.
            current_version_id: Идентификатор текущей версии файла.
            visibility: Видимость создаваемого узла.
            created_by: Идентификатор пользователя, создавшего файл.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_conflict: Проверять ли конфликт имени в родительской папке.
            check_owner_exists: Проверять ли существование владельца.

        Returns:
            Созданный файл.

        Raises:
            EntityNotFoundError: Если владелец или родительская папка не найдены.
            InvalidQueryError: Если параметры узла или файла некорректны.
            DuplicateEntityError: Если в папке уже существует узел с таким именем
                или storage key уже используется.
        """

        node = await self.nodes.create_node(
            owner_id=owner_id,
            name=name,
            node_type=NodeType.FILE,
            parent_id=parent_id,
            visibility=visibility,
            created_by=created_by,
            updated_by=created_by,
            flush=True,
            refresh=False,
            check_owner_exists=check_owner_exists,
            check_conflict=check_conflict,
        )

        return await self.create_file(
            node_id=node.id,
            storage_bucket=storage_bucket,
            storage_key=storage_key,
            size_bytes=size_bytes,
            mime_type=mime_type,
            extension=extension,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
            storage_status=storage_status,
            processing_status=processing_status,
            preview_status=preview_status,
            preview_storage_key=preview_storage_key,
            current_version_id=current_version_id,
            flush=flush,
            refresh=refresh,
            validate_node=False,
            check_duplicate_node=False,
        )

    async def create_for_existing_node(
        self,
        *,
        node_id: uuid.UUID,
        storage_bucket: str,
        storage_key: str,
        size_bytes: int,
        mime_type: str | None = None,
        extension: str | None = None,
        checksum: str | None = None,
        checksum_algorithm: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Создаёт запись ``File`` для уже существующего узла файла.

        Является удобным алиасом над ``create_file`` с включённой проверкой узла
        и проверкой дубликата по ``node_id``.

        Args:
            node_id: Идентификатор существующего узла типа ``FILE``.
            storage_bucket: Bucket объектного хранилища.
            storage_key: Ключ объекта в хранилище.
            size_bytes: Размер файла в байтах.
            mime_type: MIME-тип файла.
            extension: Расширение файла.
            checksum: Контрольная сумма файла.
            checksum_algorithm: Алгоритм контрольной суммы.
            flush: Выполнить ли ``flush`` после создания.
            refresh: Выполнить ли ``refresh`` после создания.

        Returns:
            Созданный файл.

        Raises:
            EntityNotFoundError: Если узел не найден.
            InvalidQueryError: Если узел не является файлом или значения некорректны.
            DuplicateEntityError: Если для узла уже существует запись файла.
        """

        return await self.create_file(
            node_id=node_id,
            storage_bucket=storage_bucket,
            storage_key=storage_key,
            size_bytes=size_bytes,
            mime_type=mime_type,
            extension=extension,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
            flush=flush,
            refresh=refresh,
            validate_node=True,
            check_duplicate_node=True,
        )

    # ------------------------------------------------------------------
    # Storage-информация
    # ------------------------------------------------------------------

    async def get_storage_info(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
    ) -> FileStorageInfo:
        """Возвращает информацию о расположении и состоянии файла в объектном хранилище.

        Нужно передать ровно один идентификатор: ``file_id`` или ``node_id``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.

        Returns:
            Структура ``FileStorageInfo`` с bucket, key, размером, checksum,
            MIME-типом, статусами и информацией о предпросмотре.

        Raises:
            InvalidQueryError: Если не передан ни один идентификатор
                или переданы оба идентификатора.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        return {
            "storage_bucket": file.storage_bucket,
            "storage_key": file.storage_key,
            "size_bytes": file.size_bytes,
            "checksum": file.checksum,
            "checksum_algorithm": file.checksum_algorithm,
            "mime_type": file.mime_type,
            "extension": file.extension,
            "storage_status": file.storage_status,
            "processing_status": file.processing_status,
            "preview_status": file.preview_status,
            "preview_storage_key": file.preview_storage_key,
            "current_version_id": file.current_version_id,
        }

    async def update_storage_info(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        storage_bucket: str,
        storage_key: str,
        size_bytes: int | None = None,
        checksum: str | None = None,
        checksum_algorithm: str | None = None,
        storage_status: StorageObjectStatus | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Обновляет информацию о расположении файла в объектном хранилище.

        Нужно передать ровно один идентификатор: ``file_id`` или ``node_id``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            storage_bucket: Новый bucket объектного хранилища.
            storage_key: Новый ключ объекта в хранилище.
            size_bytes: Новый размер файла в байтах.
            checksum: Новая контрольная сумма файла.
            checksum_algorithm: Новый алгоритм контрольной суммы.
            storage_status: Новый статус объекта в хранилище.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы или входные значения некорректны.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        values: dict[str, Any] = {
            "storage_bucket": self._validate_storage_bucket(storage_bucket),
            "storage_key": self._validate_storage_key(storage_key),
            "checksum": self._normalize_checksum(checksum),
            "checksum_algorithm": self._normalize_checksum_algorithm(
                checksum_algorithm,
            ),
        }

        if size_bytes is not None:
            values["size_bytes"] = self._validate_size_bytes(size_bytes)

        if storage_status is not None:
            values["storage_status"] = storage_status

        return await self.update(
            file,
            values,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Обновление метаданных
    # ------------------------------------------------------------------

    async def update_metadata(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        size_bytes: int | None = None,
        mime_type: str | None = None,
        extension: str | None = None,
        checksum: str | None = None,
        checksum_algorithm: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Обновляет общие метаданные файла.

        Обновляет размер, MIME-тип, расширение, checksum и алгоритм checksum.
        Нужно передать ровно один идентификатор: ``file_id`` или ``node_id``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            size_bytes: Новый размер файла в байтах.
            mime_type: Новый MIME-тип файла.
            extension: Новое расширение файла.
            checksum: Новая контрольная сумма файла.
            checksum_algorithm: Новый алгоритм контрольной суммы.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы или метаданные некорректны.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        values: dict[str, Any] = {
            "mime_type": self._normalize_mime_type(mime_type),
            "extension": self._normalize_extension(extension),
            "checksum": self._normalize_checksum(checksum),
            "checksum_algorithm": self._normalize_checksum_algorithm(
                checksum_algorithm,
            ),
        }

        if size_bytes is not None:
            values["size_bytes"] = self._validate_size_bytes(size_bytes)

        return await self.update(
            file,
            values,
            flush=flush,
            refresh=refresh,
        )

    async def update_size(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        size_bytes: int,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Обновляет размер файла.

        Нужно передать ровно один идентификатор: ``file_id`` или ``node_id``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            size_bytes: Новый размер файла в байтах.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы или размер файла некорректны.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        return await self.update(
            file,
            {"size_bytes": self._validate_size_bytes(size_bytes)},
            flush=flush,
            refresh=refresh,
        )

    async def update_checksum(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        checksum: str | None,
        checksum_algorithm: str | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Обновляет контрольную сумму файла.

        Нужно передать ровно один идентификатор: ``file_id`` или ``node_id``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            checksum: Новая контрольная сумма файла.
            checksum_algorithm: Алгоритм контрольной суммы.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы, checksum или алгоритм некорректны.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        return await self.update(
            file,
            {
                "checksum": self._normalize_checksum(checksum),
                "checksum_algorithm": self._normalize_checksum_algorithm(
                    checksum_algorithm,
                ),
            },
            flush=flush,
            refresh=refresh,
        )

    async def update_current_version(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        current_version_id: uuid.UUID | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Обновляет текущую активную версию файла.

        Нужно передать ровно один идентификатор: ``file_id`` или ``node_id``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            current_version_id: Идентификатор текущей версии файла или ``None``.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы переданы некорректно.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        return await self.update(
            file,
            {"current_version_id": current_version_id},
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Статусы файла
    # ------------------------------------------------------------------

    async def update_storage_status(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        storage_status: StorageObjectStatus,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Обновляет статус физического объекта файла в хранилище.

        Нужно передать ровно один идентификатор: ``file_id`` или ``node_id``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            storage_status: Новый статус объекта в хранилище.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы переданы некорректно.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        return await self.update(
            file,
            {"storage_status": storage_status},
            flush=flush,
            refresh=refresh,
        )

    async def mark_storage_available(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает объект файла как доступный в хранилище.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.
        """

        return await self.update_storage_status(
            file_id=file_id,
            node_id=node_id,
            storage_status=StorageObjectStatus.AVAILABLE,
            flush=flush,
            refresh=refresh,
        )

    async def mark_storage_missing(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает объект файла как отсутствующий в хранилище.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.
        """

        return await self.update_storage_status(
            file_id=file_id,
            node_id=node_id,
            storage_status=StorageObjectStatus.MISSING,
            flush=flush,
            refresh=refresh,
        )

    async def mark_storage_corrupted(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает объект файла как повреждённый.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.
        """

        return await self.update_storage_status(
            file_id=file_id,
            node_id=node_id,
            storage_status=StorageObjectStatus.CORRUPTED,
            flush=flush,
            refresh=refresh,
        )

    async def update_processing_status(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        processing_status: FileProcessingStatus,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Обновляет статус обработки файла.

        Нужно передать ровно один идентификатор: ``file_id`` или ``node_id``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            processing_status: Новый статус обработки файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы переданы некорректно.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        return await self.update(
            file,
            {"processing_status": processing_status},
            flush=flush,
            refresh=refresh,
        )

    async def mark_processing(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает файл как обрабатываемый.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.
        """

        return await self.update_processing_status(
            file_id=file_id,
            node_id=node_id,
            processing_status=FileProcessingStatus.PROCESSING,
            flush=flush,
            refresh=refresh,
        )

    async def mark_ready(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает файл как готовый и доступный в хранилище.

        Метод использует доменный метод ``mark_ready()`` модели ``File``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы переданы некорректно.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        file.mark_ready()

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(file)

        return file

    async def mark_processing_failed(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает обработку файла как завершившуюся ошибкой.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.
        """

        return await self.update_processing_status(
            file_id=file_id,
            node_id=node_id,
            processing_status=FileProcessingStatus.FAILED,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Предпросмотр
    # ------------------------------------------------------------------

    async def update_preview(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        preview_status: FilePreviewStatus,
        preview_storage_key: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Обновляет статус и storage key предпросмотра файла.

        Нужно передать ровно один идентификатор: ``file_id`` или ``node_id``.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            preview_status: Новый статус предпросмотра.
            preview_storage_key: Ключ предпросмотра в объектном хранилище.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы переданы некорректно.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        return await self.update(
            file,
            {
                "preview_status": preview_status,
                "preview_storage_key": self._normalize_storage_key_optional(
                    preview_storage_key,
                ),
            },
            flush=flush,
            refresh=refresh,
        )

    async def set_preview_ready(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        preview_storage_key: str,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает предпросмотр файла как готовый.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            preview_storage_key: Ключ готового предпросмотра в объектном хранилище.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.

        Raises:
            InvalidQueryError: Если идентификаторы или ключ предпросмотра некорректны.
            EntityNotFoundError: Если файл не найден.
        """

        file = await self._get_required_by_file_id_or_node_id(
            file_id=file_id,
            node_id=node_id,
        )

        file.set_preview_ready(
            self._validate_storage_key(preview_storage_key),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(file)

        return file

    async def mark_preview_not_required(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает предпросмотр файла как не требующийся.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.
        """

        return await self.update_preview(
            file_id=file_id,
            node_id=node_id,
            preview_status=FilePreviewStatus.NOT_REQUIRED,
            preview_storage_key=None,
            flush=flush,
            refresh=refresh,
        )

    async def mark_preview_pending(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает предпросмотр файла как ожидающий генерации.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.
        """

        return await self.update_preview(
            file_id=file_id,
            node_id=node_id,
            preview_status=FilePreviewStatus.PENDING,
            preview_storage_key=None,
            flush=flush,
            refresh=refresh,
        )

    async def mark_preview_generating(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает предпросмотр файла как генерируемый.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.
        """

        return await self.update_preview(
            file_id=file_id,
            node_id=node_id,
            preview_status=FilePreviewStatus.GENERATING,
            preview_storage_key=None,
            flush=flush,
            refresh=refresh,
        )

    async def mark_preview_failed(
        self,
        *,
        file_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Помечает генерацию предпросмотра как неудачную.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый файл.
        """

        return await self.update_preview(
            file_id=file_id,
            node_id=node_id,
            preview_status=FilePreviewStatus.FAILED,
            preview_storage_key=None,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Поиск по checksum, MIME-типу и расширению
    # ------------------------------------------------------------------

    async def find_by_checksum(
        self,
        *,
        checksum: str,
        checksum_algorithm: str | None = None,
        owner_id: uuid.UUID | None = None,
        include_deleted_nodes: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Возвращает файлы по контрольной сумме.

        Можно дополнительно ограничить поиск алгоритмом checksum, владельцем файла
        и признаком удаления связанного узла.

        Args:
            checksum: Контрольная сумма для поиска.
            checksum_algorithm: Алгоритм контрольной суммы.
            owner_id: Идентификатор владельца файлов.
            include_deleted_nodes: Включать ли файлы, чей узел удалён.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список файлов с указанной контрольной суммой.

        Raises:
            InvalidQueryError: Если checksum пустой или параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        normalized_checksum = self._normalize_checksum(checksum)

        if normalized_checksum is None:
            raise InvalidQueryError(
                "Checksum для поиска не может быть пустым.",
                repository=self.repository_name,
                operation="find_by_checksum",
                details={"field": "checksum"},
            )

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(File.checksum == normalized_checksum)
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
            )
            .order_by(File.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        normalized_algorithm = self._normalize_checksum_algorithm(
            checksum_algorithm,
        )

        if normalized_algorithm is not None:
            statement = statement.where(
                File.checksum_algorithm == normalized_algorithm,
            )

        if owner_id is not None:
            statement = statement.where(FileSystemNode.owner_id == owner_id)

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalars_all(
            statement,
            operation="find_by_checksum",
        )

    async def find_duplicates_by_checksum(
        self,
        *,
        checksum: str,
        checksum_algorithm: str | None = None,
        owner_id: uuid.UUID | None = None,
        exclude_file_id: uuid.UUID | None = None,
        include_deleted_nodes: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Возвращает потенциальные дубликаты файла по контрольной сумме.

        Args:
            checksum: Контрольная сумма для поиска.
            checksum_algorithm: Алгоритм контрольной суммы.
            owner_id: Идентификатор владельца файлов.
            exclude_file_id: Идентификатор файла, который нужно исключить из результата.
            include_deleted_nodes: Включать ли файлы, чей узел удалён.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список потенциальных дубликатов файла.
        """

        files = await self.find_by_checksum(
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
            owner_id=owner_id,
            include_deleted_nodes=include_deleted_nodes,
            offset=offset,
            limit=limit,
        )

        if exclude_file_id is None:
            return files

        return [file for file in files if file.id != exclude_file_id]

    async def list_by_mime_type(
        self,
        *,
        mime_type: str,
        owner_id: uuid.UUID | None = None,
        include_deleted_nodes: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Возвращает файлы по MIME-типу.

        Args:
            mime_type: MIME-тип для поиска.
            owner_id: Идентификатор владельца файлов.
            include_deleted_nodes: Включать ли файлы, чей узел удалён.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список файлов с указанным MIME-типом.

        Raises:
            InvalidQueryError: Если MIME-тип пустой или параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        normalized_mime_type = self._normalize_mime_type(mime_type)

        if normalized_mime_type is None:
            raise InvalidQueryError(
                "MIME-тип для поиска не может быть пустым.",
                repository=self.repository_name,
                operation="list_by_mime_type",
                details={"field": "mime_type"},
            )

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(File.mime_type == normalized_mime_type)
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
            )
            .order_by(File.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        if owner_id is not None:
            statement = statement.where(FileSystemNode.owner_id == owner_id)

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalars_all(
            statement,
            operation="list_by_mime_type",
        )

    async def list_by_extension(
        self,
        *,
        extension: str,
        owner_id: uuid.UUID | None = None,
        include_deleted_nodes: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Возвращает файлы по расширению.

        Расширение нормализуется: приводится к нижнему регистру и хранится
        без ведущей точки.

        Args:
            extension: Расширение файла.
            owner_id: Идентификатор владельца файлов.
            include_deleted_nodes: Включать ли файлы, чей узел удалён.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список файлов с указанным расширением.

        Raises:
            InvalidQueryError: Если расширение пустое, некорректное
                или параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        normalized_extension = self._normalize_extension(extension)

        if normalized_extension is None:
            raise InvalidQueryError(
                "Расширение для поиска не может быть пустым.",
                repository=self.repository_name,
                operation="list_by_extension",
                details={"field": "extension"},
            )

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(File.extension == normalized_extension)
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
            )
            .order_by(File.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        if owner_id is not None:
            statement = statement.where(FileSystemNode.owner_id == owner_id)

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalars_all(
            statement,
            operation="list_by_extension",
        )

    # ------------------------------------------------------------------
    # Проверки
    # ------------------------------------------------------------------

    async def is_file_node(
        self,
        node_id: uuid.UUID,
        *,
        include_deleted: bool = True,
        require_file_record: bool = False,
    ) -> bool:
        """Проверяет, является ли узел файловым узлом.

        При необходимости также проверяет наличие связанной записи ``files``.

        Args:
            node_id: Идентификатор узла файловой системы.
            include_deleted: Учитывать ли удалённые узлы.
            require_file_record: Требовать ли наличие записи ``File``.

        Returns:
            ``True``, если узел является файлом и, при необходимости, имеет запись ``File``,
            иначе ``False``.
        """

        conditions: list[Any] = [
            FileSystemNode.id == node_id,
            FileSystemNode.node_type == NodeType.FILE,
        ]

        if not include_deleted:
            conditions.append(FileSystemNode.is_deleted.is_(False))

        statement = select(
            select(FileSystemNode).where(*conditions).exists(),
        )

        node_exists = bool(
            await self.scalar_value(
                statement,
                operation="is_file_node",
            )
        )

        if not node_exists:
            return False

        if not require_file_record:
            return True

        return await self.exists(File.node_id == node_id)

    async def file_exists_for_node(
        self,
        node_id: uuid.UUID,
    ) -> bool:
        """Проверяет, существует ли запись ``files`` для указанного узла.

        Args:
            node_id: Идентификатор узла файловой системы.

        Returns:
            ``True``, если запись файла существует, иначе ``False``.
        """

        return await self.exists(File.node_id == node_id)

    async def storage_key_exists(
        self,
        *,
        storage_key: str,
        storage_bucket: str | None = None,
        exclude_file_id: uuid.UUID | None = None,
    ) -> bool:
        """Проверяет, используется ли storage key.

        Args:
            storage_key: Ключ объекта в хранилище.
            storage_bucket: Bucket объектного хранилища для дополнительного ограничения.
            exclude_file_id: Идентификатор файла, который нужно исключить из проверки.

        Returns:
            ``True``, если storage key уже используется, иначе ``False``.

        Raises:
            InvalidQueryError: Если storage key или bucket некорректны.
        """

        conditions: list[Any] = [
            File.storage_key == self._validate_storage_key(storage_key),
        ]

        if storage_bucket is not None:
            conditions.append(
                File.storage_bucket == self._validate_storage_bucket(storage_bucket),
            )

        if exclude_file_id is not None:
            conditions.append(File.id != exclude_file_id)

        return await self.exists(*conditions)

    async def require_file_node(
        self,
        node_id: uuid.UUID,
        *,
        include_deleted: bool = True,
    ) -> FileSystemNode:
        """Возвращает узел, если он существует и является файлом.

        Args:
            node_id: Идентификатор узла файловой системы.
            include_deleted: Разрешать ли удалённый узел.

        Returns:
            Узел файловой системы типа ``FILE``.

        Raises:
            EntityNotFoundError: Если узел не найден.
            InvalidQueryError: Если узел не является файлом или удалён,
                когда ``include_deleted=False``.
        """

        node = await self.nodes.get_required_by_id(node_id)

        if node.node_type != NodeType.FILE:
            raise InvalidQueryError(
                "Узел файловой системы не является файлом.",
                repository=self.repository_name,
                operation="require_file_node",
                details={
                    "node_id": str(node.id),
                    "node_type": node.node_type.value,
                    "expected_node_type": NodeType.FILE.value,
                },
            )

        if not include_deleted and node.is_deleted:
            raise InvalidQueryError(
                "Файл удалён и не может использоваться в этой операции.",
                repository=self.repository_name,
                operation="require_file_node",
                details={"node_id": str(node.id)},
            )

        return node

    # ------------------------------------------------------------------
    # Списки и выборки
    # ------------------------------------------------------------------

    async def list_by_node_ids(
        self,
        node_ids: list[uuid.UUID],
        *,
        include_deleted_nodes: bool = True,
    ) -> list[File]:
        """Возвращает файлы по списку ``node_id``.

        Args:
            node_ids: Список идентификаторов узлов файлов.
            include_deleted_nodes: Включать ли файлы, чьи узлы удалены.

        Returns:
            Список найденных файлов. Если список ID пустой, возвращается пустой список.
        """

        if not node_ids:
            return []

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(File.node_id.in_(node_ids))
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
            )
        )

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalars_all(
            statement,
            operation="list_by_node_ids",
        )

    async def list_user_files(
        self,
        *,
        owner_id: uuid.UUID,
        include_deleted_nodes: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Возвращает файлы пользователя.

        Args:
            owner_id: Идентификатор владельца файлов.
            include_deleted_nodes: Включать ли файлы, чьи узлы удалены.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список файлов пользователя.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(
                FileSystemNode.owner_id == owner_id,
                FileSystemNode.node_type == NodeType.FILE,
            )
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
            )
            .order_by(FileSystemNode.path.asc())
            .offset(offset)
            .limit(limit)
        )

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalars_all(
            statement,
            operation="list_user_files",
        )

    async def search_user_files(
        self,
        *,
        owner_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
        include_deleted_nodes: bool = False,
        query: str | None = None,
        mime_type: str | None = None,
        extension: str | None = None,
        storage_status: StorageObjectStatus | None = None,
        processing_status: FileProcessingStatus | None = None,
        preview_status: FilePreviewStatus | None = None,
        min_size_bytes: int | None = None,
        max_size_bytes: int | None = None,
        created_from: Any | None = None,
        created_to: Any | None = None,
        updated_from: Any | None = None,
        updated_to: Any | None = None,
        sort_by: str = "created_at",
        sort_direction: str = "desc",
        offset: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Ищет файлы пользователя по фильтрам.

        Возвращает страницу файлов указанного владельца. Поддерживает фильтрацию
        по родительскому узлу, признаку удаления связанного узла, поисковой
        строке, MIME-типу, расширению, статусам хранилища, обработки и
        предпросмотра, размеру файла, диапазонам дат создания и обновления.

        Args:
            owner_id: Идентификатор владельца файлов.
            parent_id: Идентификатор родительского узла. Если ``None``, фильтр
                по родителю не применяется.
            include_deleted_nodes: Включать ли файлы, связанные с удалёнными
                узлами файловой системы.
            query: Поисковая строка. Если ``None`` или пустая строка, текстовый
                поиск не применяется.
            mime_type: MIME-тип файла для фильтрации.
            extension: Расширение файла для фильтрации.
            storage_status: Статус объекта в хранилище для фильтрации.
            processing_status: Статус обработки файла для фильтрации.
            preview_status: Статус предпросмотра файла для фильтрации.
            min_size_bytes: Минимальный размер файла в байтах включительно.
            max_size_bytes: Максимальный размер файла в байтах включительно.
            created_from: Нижняя граница даты создания файла включительно.
            created_to: Верхняя граница даты создания файла включительно.
            updated_from: Нижняя граница даты обновления файла включительно.
            updated_to: Верхняя граница даты обновления файла включительно.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки: ``asc`` или ``desc``.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество файлов в результате.

        Returns:
            Список файлов пользователя, соответствующих фильтрам.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
            RepositoryError: Если выполнение запроса завершилось ошибкой.
        """

        self._validate_pagination(offset=offset, limit=limit)
        statement = (
            self._build_search_statement(
                owner_id=owner_id,
                parent_id=parent_id,
                include_deleted_nodes=include_deleted_nodes,
                query=query,
                mime_type=mime_type,
                extension=extension,
                storage_status=storage_status,
                processing_status=processing_status,
                preview_status=preview_status,
                min_size_bytes=min_size_bytes,
                max_size_bytes=max_size_bytes,
                created_from=created_from,
                created_to=created_to,
                updated_from=updated_from,
                updated_to=updated_to,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
            .offset(offset)
            .limit(limit)
        )
        return await self.scalars_all(statement, operation="search_user_files")

    async def count_user_files_filtered(
        self,
        *,
        owner_id: uuid.UUID,
        parent_id: uuid.UUID | None = None,
        include_deleted_nodes: bool = False,
        query: str | None = None,
        mime_type: str | None = None,
        extension: str | None = None,
        storage_status: StorageObjectStatus | None = None,
        processing_status: FileProcessingStatus | None = None,
        preview_status: FilePreviewStatus | None = None,
        min_size_bytes: int | None = None,
        max_size_bytes: int | None = None,
        created_from: Any | None = None,
        created_to: Any | None = None,
        updated_from: Any | None = None,
        updated_to: Any | None = None,
    ) -> int:
        """Возвращает количество файлов пользователя по фильтрам.

        Использует те же фильтры, что и ``search_user_files``. Для подсчёта
        строит поисковый запрос и считает количество строк из его подзапроса.

        Args:
            owner_id: Идентификатор владельца файлов.
            parent_id: Идентификатор родительского узла. Если ``None``, фильтр
                по родителю не применяется.
            include_deleted_nodes: Учитывать ли файлы, связанные с удалёнными
                узлами файловой системы.
            query: Поисковая строка. Если ``None`` или пустая строка, текстовый
                поиск не применяется.
            mime_type: MIME-тип файла для фильтрации.
            extension: Расширение файла для фильтрации.
            storage_status: Статус объекта в хранилище для фильтрации.
            processing_status: Статус обработки файла для фильтрации.
            preview_status: Статус предпросмотра файла для фильтрации.
            min_size_bytes: Минимальный размер файла в байтах включительно.
            max_size_bytes: Максимальный размер файла в байтах включительно.
            created_from: Нижняя граница даты создания файла включительно.
            created_to: Верхняя граница даты создания файла включительно.
            updated_from: Нижняя граница даты обновления файла включительно.
            updated_to: Верхняя граница даты обновления файла включительно.

        Returns:
            Количество файлов пользователя, соответствующих фильтрам.

        Raises:
            RepositoryError: Если выполнение запроса завершилось ошибкой.
        """

        statement = self._build_search_statement(
            owner_id=owner_id,
            parent_id=parent_id,
            include_deleted_nodes=include_deleted_nodes,
            query=query,
            mime_type=mime_type,
            extension=extension,
            storage_status=storage_status,
            processing_status=processing_status,
            preview_status=preview_status,
            min_size_bytes=min_size_bytes,
            max_size_bytes=max_size_bytes,
            created_from=created_from,
            created_to=created_to,
            updated_from=updated_from,
            updated_to=updated_to,
            sort_by="created_at",
            sort_direction="desc",
        )
        count_statement = select(func.count()).select_from(statement.subquery())
        total = await self.scalar_value(
            count_statement,
            operation="count_user_files_filtered",
        )
        return int(total or 0)

    async def list_child_files(
        self,
        *,
        parent_id: uuid.UUID,
        include_deleted_nodes: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Возвращает файлы внутри указанной папки.

        Args:
            parent_id: Идентификатор родительской папки.
            include_deleted_nodes: Включать ли файлы, чьи узлы удалены.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список файлов внутри указанной папки.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(
                FileSystemNode.parent_id == parent_id,
                FileSystemNode.node_type == NodeType.FILE,
            )
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
            )
            .order_by(FileSystemNode.name.asc())
            .offset(offset)
            .limit(limit)
        )

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalars_all(
            statement,
            operation="list_child_files",
        )

    async def list_ready_files(
        self,
        *,
        owner_id: uuid.UUID | None = None,
        include_deleted_nodes: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Возвращает готовые файлы, доступные в хранилище.

        Готовым считается файл со статусом обработки ``READY``
        и статусом объекта в хранилище ``AVAILABLE``.

        Args:
            owner_id: Идентификатор владельца файлов.
            include_deleted_nodes: Включать ли файлы, чьи узлы удалены.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список готовых файлов.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(
                File.processing_status == FileProcessingStatus.READY,
                File.storage_status == StorageObjectStatus.AVAILABLE,
            )
            .options(
                selectinload(File.node),
                selectinload(File.current_version),
            )
            .order_by(File.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        if owner_id is not None:
            statement = statement.where(FileSystemNode.owner_id == owner_id)

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalars_all(
            statement,
            operation="list_ready_files",
        )

    async def list_by_storage_status(
        self,
        *,
        storage_status: StorageObjectStatus,
        owner_id: uuid.UUID | None = None,
        include_deleted_nodes: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> list[File]:
        """Возвращает файлы по статусу объекта в хранилище.

        Args:
            storage_status: Статус объекта файла в хранилище.
            owner_id: Идентификатор владельца файлов.
            include_deleted_nodes: Включать ли файлы, чьи узлы удалены.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список файлов с указанным storage-статусом.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(File.storage_status == storage_status)
            .options(selectinload(File.node))
            .order_by(File.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )

        if owner_id is not None:
            statement = statement.where(FileSystemNode.owner_id == owner_id)

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        return await self.scalars_all(
            statement,
            operation="list_by_storage_status",
        )

    # ------------------------------------------------------------------
    # Подсчёты
    # ------------------------------------------------------------------

    async def count_user_files(
        self,
        *,
        owner_id: uuid.UUID,
        include_deleted_nodes: bool = False,
    ) -> int:
        """Возвращает количество файлов пользователя.

        Args:
            owner_id: Идентификатор владельца файлов.
            include_deleted_nodes: Учитывать ли файлы, чьи узлы удалены.

        Returns:
            Количество файлов пользователя.
        """

        statement = (
            select(func.count())
            .select_from(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(
                FileSystemNode.owner_id == owner_id,
                FileSystemNode.node_type == NodeType.FILE,
            )
        )

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        result = await self.scalar_value(
            statement,
            operation="count_user_files",
        )

        return int(result or 0)

    async def sum_user_files_size(
        self,
        *,
        owner_id: uuid.UUID,
        include_deleted_nodes: bool = False,
    ) -> int:
        """Возвращает суммарный размер файлов пользователя.

        Args:
            owner_id: Идентификатор владельца файлов.
            include_deleted_nodes: Учитывать ли файлы, чьи узлы удалены.

        Returns:
            Суммарный размер файлов пользователя в байтах.
        """

        statement = (
            select(func.coalesce(func.sum(File.size_bytes), 0))
            .select_from(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(
                FileSystemNode.owner_id == owner_id,
                FileSystemNode.node_type == NodeType.FILE,
            )
        )

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        result = await self.scalar_value(
            statement,
            operation="sum_user_files_size",
        )

        return int(result or 0)

    async def count_child_files(
        self,
        *,
        parent_id: uuid.UUID,
        include_deleted_nodes: bool = False,
    ) -> int:
        """Возвращает количество файлов внутри указанной папки.

        Args:
            parent_id: Идентификатор родительской папки.
            include_deleted_nodes: Учитывать ли файлы, чьи узлы удалены.

        Returns:
            Количество файлов внутри указанной папки.
        """

        statement = (
            select(func.count())
            .select_from(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(
                FileSystemNode.parent_id == parent_id,
                FileSystemNode.node_type == NodeType.FILE,
            )
        )

        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))

        result = await self.scalar_value(
            statement,
            operation="count_child_files",
        )

        return int(result or 0)

    # ------------------------------------------------------------------
    # Удаление записи files
    # ------------------------------------------------------------------

    async def delete_by_node_id(
        self,
        node_id: uuid.UUID,
        *,
        flush: bool = True,
        required: bool = True,
    ) -> bool:
        """Физически удаляет запись ``files`` по ``node_id``.

        Метод удаляет только запись ``File``, но не удаляет связанный ``FileSystemNode``.
        Пользовательское удаление файла должно выполняться через
        ``FileSystemNodeRepository.soft_delete_node()``.

        Args:
            node_id: Идентификатор узла файла.
            flush: Выполнить ли ``flush`` после удаления.
            required: Выбрасывать ли ошибку, если запись файла не найдена.

        Returns:
            ``True``, если запись была удалена, иначе ``False``.

        Raises:
            EntityNotFoundError: Если файл не найден и ``required=True``.
        """

        file = await self.get_by_node_id(node_id)

        if file is None:
            if required:
                raise EntityNotFoundError(
                    "File",
                    lookup={"node_id": str(node_id)},
                    repository=self.repository_name,
                )

            return False

        await self.delete(file, flush=flush)

        return True

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    async def _get_required_by_file_id_or_node_id(
        self,
        *,
        file_id: uuid.UUID | None,
        node_id: uuid.UUID | None,
    ) -> File:
        """Возвращает файл по ``file_id`` или ``node_id``.

        Нужно передать ровно один идентификатор.

        Args:
            file_id: Идентификатор записи файла.
            node_id: Идентификатор узла файла.

        Returns:
            Найденный файл.

        Raises:
            InvalidQueryError: Если не передан ни один идентификатор
                или переданы оба идентификатора.
            EntityNotFoundError: Если файл не найден.
        """

        if file_id is None and node_id is None:
            raise InvalidQueryError(
                "Необходимо передать file_id или node_id.",
                repository=self.repository_name,
                operation="_get_required_by_file_id_or_node_id",
            )

        if file_id is not None and node_id is not None:
            raise InvalidQueryError(
                "Нужно передать только один идентификатор: file_id или node_id.",
                repository=self.repository_name,
                operation="_get_required_by_file_id_or_node_id",
                details={
                    "file_id": str(file_id),
                    "node_id": str(node_id),
                },
            )

        if file_id is not None:
            return await self.get_required_by_id(file_id)

        assert node_id is not None

        return await self.get_required_by_node_id(node_id)

    async def _validate_file_node(
        self,
        node_id: uuid.UUID,
        *,
        check_duplicate: bool = True,
    ) -> FileSystemNode:
        """Проверяет, что узел существует, является файлом и ещё не имеет записи ``files``.

        Args:
            node_id: Идентификатор узла файловой системы.
            check_duplicate: Проверять ли наличие уже существующей записи файла.

        Returns:
            Узел файловой системы типа ``FILE``.

        Raises:
            EntityNotFoundError: Если узел не найден.
            InvalidQueryError: Если узел не является файлом.
            DuplicateEntityError: Если для узла уже существует запись файла.
        """

        node = await self.require_file_node(
            node_id,
            include_deleted=True,
        )

        if check_duplicate and await self.file_exists_for_node(node_id):
            raise DuplicateEntityError(
                "File",
                field="node_id",
                value=node_id,
                repository=self.repository_name,
                message="Для указанного узла уже существует запись файла.",
            )

        return node

    def _build_search_statement(
        self,
        *,
        owner_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        include_deleted_nodes: bool,
        query: str | None,
        mime_type: str | None,
        extension: str | None,
        storage_status: StorageObjectStatus | None,
        processing_status: FileProcessingStatus | None,
        preview_status: FilePreviewStatus | None,
        min_size_bytes: int | None,
        max_size_bytes: int | None,
        created_from: Any | None,
        created_to: Any | None,
        updated_from: Any | None,
        updated_to: Any | None,
        sort_by: str,
        sort_direction: str,
    ) -> Select[tuple[File]]:
        """Строит SQL-запрос для поиска файлов пользователя.

        Формирует базовый ``SELECT`` по ``File`` с ``JOIN`` к
        ``FileSystemNode`` и применяет фильтры по владельцу, родительскому узлу,
        признаку удаления узла, поисковой строке, MIME-типу, расширению,
        статусам файла, размеру, датам создания и обновления. Также добавляет
        eager loading для связанного узла и текущей версии файла.

        Args:
            owner_id: Идентификатор владельца файлов.
            parent_id: Идентификатор родительского узла. Если ``None``, фильтр
                по родителю не применяется.
            include_deleted_nodes: Включать ли файлы, связанные с удалёнными
                узлами файловой системы.
            query: Поисковая строка. При наличии применяется к имени узла, пути,
                MIME-типу, расширению и checksum файла.
            mime_type: MIME-тип файла для точной фильтрации.
            extension: Расширение файла для точной фильтрации.
            storage_status: Статус объекта файла в хранилище.
            processing_status: Статус обработки файла.
            preview_status: Статус генерации или доступности предпросмотра.
            min_size_bytes: Минимальный размер файла в байтах включительно.
            max_size_bytes: Максимальный размер файла в байтах включительно.
            created_from: Нижняя граница даты создания файла включительно.
            created_to: Верхняя граница даты создания файла включительно.
            updated_from: Нижняя граница даты обновления файла включительно.
            updated_to: Верхняя граница даты обновления файла включительно.
            sort_by: Поле сортировки. Поддерживаются ``name``, ``path``,
                ``size_bytes``, ``mime_type``, ``extension``, ``created_at``
                и ``updated_at``. Если поле неизвестно, используется
                ``created_at``.
            sort_direction: Направление сортировки. Значение ``desc`` включает
                сортировку по убыванию, остальные значения дают сортировку
                по возрастанию.

        Returns:
            SQLAlchemy ``Select``-запрос, возвращающий ``File`` и готовый
            к добавлению ``offset``, ``limit`` или использованию в подзапросе.
        """

        statement = (
            select(File)
            .join(FileSystemNode, File.node_id == FileSystemNode.id)
            .where(
                FileSystemNode.owner_id == owner_id,
                FileSystemNode.node_type == NodeType.FILE,
            )
            .options(selectinload(File.node), selectinload(File.current_version))
        )
        if parent_id is not None:
            statement = statement.where(FileSystemNode.parent_id == parent_id)
        if not include_deleted_nodes:
            statement = statement.where(FileSystemNode.is_deleted.is_(False))
        if query:
            normalized_query = query.strip()
            if normalized_query:
                pattern = f"%{normalized_query}%"
                statement = statement.where(
                    or_(
                        FileSystemNode.name.ilike(pattern),
                        FileSystemNode.path.ilike(pattern),
                        File.mime_type.ilike(pattern),
                        File.extension.ilike(pattern),
                        File.checksum.ilike(pattern),
                    )
                )
        if mime_type is not None:
            statement = statement.where(File.mime_type == mime_type)
        if extension is not None:
            statement = statement.where(File.extension == extension)
        if storage_status is not None:
            statement = statement.where(File.storage_status == storage_status)
        if processing_status is not None:
            statement = statement.where(File.processing_status == processing_status)
        if preview_status is not None:
            statement = statement.where(File.preview_status == preview_status)
        if min_size_bytes is not None:
            statement = statement.where(File.size_bytes >= min_size_bytes)
        if max_size_bytes is not None:
            statement = statement.where(File.size_bytes <= max_size_bytes)
        if created_from is not None:
            statement = statement.where(File.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(File.created_at <= created_to)
        if updated_from is not None:
            statement = statement.where(File.updated_at >= updated_from)
        if updated_to is not None:
            statement = statement.where(File.updated_at <= updated_to)

        sort_columns: dict[str, Any] = {
            "name": func.lower(FileSystemNode.name),
            "path": func.lower(FileSystemNode.path),
            "size_bytes": File.size_bytes,
            "mime_type": File.mime_type,
            "extension": File.extension,
            "created_at": File.created_at,
            "updated_at": File.updated_at,
        }
        column = sort_columns.get(sort_by.strip().lower(), File.created_at)
        is_desc = sort_direction.strip().lower() == "desc"
        return statement.order_by(column.desc() if is_desc else column.asc())

    def _validate_storage_bucket(
        self,
        storage_bucket: str,
    ) -> str:
        """Проверяет и нормализует bucket объектного хранилища.

        Args:
            storage_bucket: Bucket объектного хранилища.

        Returns:
            Нормализованное имя bucket.

        Raises:
            InvalidQueryError: Если bucket пустой или превышает допустимую длину.
        """

        normalized = storage_bucket.strip()

        if not normalized:
            raise InvalidQueryError(
                "Bucket объектного хранилища не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_storage_bucket",
                details={"field": "storage_bucket"},
            )

        if len(normalized) > 128:
            raise InvalidQueryError(
                "Bucket объектного хранилища не должен превышать 128 символов.",
                repository=self.repository_name,
                operation="_validate_storage_bucket",
                details={
                    "field": "storage_bucket",
                    "length": len(normalized),
                    "max_length": 128,
                },
            )

        return normalized

    def _validate_storage_key(
        self,
        storage_key: str,
    ) -> str:
        """Проверяет и нормализует ключ объекта в хранилище.

        Args:
            storage_key: Ключ объекта в хранилище.

        Returns:
            Нормализованный storage key.

        Raises:
            InvalidQueryError: Если storage key пустой.
        """

        normalized = storage_key.strip()

        if not normalized:
            raise InvalidQueryError(
                "Ключ объекта в хранилище не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_storage_key",
                details={"field": "storage_key"},
            )

        return normalized

    def _normalize_storage_key_optional(
        self,
        storage_key: str | None,
    ) -> str | None:
        """Нормализует необязательный storage key.

        Args:
            storage_key: Ключ объекта в хранилище или ``None``.

        Returns:
            Нормализованный storage key или ``None``.
        """

        if storage_key is None:
            return None

        normalized = storage_key.strip()

        return normalized or None

    def _validate_size_bytes(
        self,
        size_bytes: int,
    ) -> int:
        """Проверяет размер файла.

        Размер должен быть целым неотрицательным числом.

        Args:
            size_bytes: Размер файла в байтах.

        Returns:
            Проверенный размер файла.

        Raises:
            InvalidQueryError: Если размер не является ``int`` или меньше нуля.
        """

        if not isinstance(size_bytes, int):
            raise InvalidQueryError(
                "Размер файла должен быть целым числом.",
                repository=self.repository_name,
                operation="_validate_size_bytes",
                details={
                    "field": "size_bytes",
                    "value_type": type(size_bytes).__name__,
                },
            )

        if size_bytes < 0:
            raise InvalidQueryError(
                "Размер файла не может быть отрицательным.",
                repository=self.repository_name,
                operation="_validate_size_bytes",
                details={
                    "field": "size_bytes",
                    "value": size_bytes,
                },
            )

        return size_bytes

    def _normalize_mime_type(
        self,
        mime_type: str | None,
    ) -> str | None:
        """Нормализует MIME-тип файла.

        Значение приводится к нижнему регистру. Пустая строка возвращается как ``None``.

        Args:
            mime_type: MIME-тип файла.

        Returns:
            Нормализованный MIME-тип или ``None``.

        Raises:
            InvalidQueryError: Если MIME-тип превышает допустимую длину.
        """

        if mime_type is None:
            return None

        normalized = mime_type.strip().lower()

        if not normalized:
            return None

        if len(normalized) > 255:
            raise InvalidQueryError(
                "MIME-тип не должен превышать 255 символов.",
                repository=self.repository_name,
                operation="_normalize_mime_type",
                details={
                    "field": "mime_type",
                    "length": len(normalized),
                    "max_length": 255,
                },
            )

        return normalized

    def _normalize_extension(
        self,
        extension: str | None,
    ) -> str | None:
        """Нормализует расширение файла.

        Расширение приводится к нижнему регистру и хранится без ведущей точки.

        Args:
            extension: Расширение файла.

        Returns:
            Нормализованное расширение или ``None``.

        Raises:
            InvalidQueryError: Если расширение содержит разделители пути
                или превышает допустимую длину.
        """

        if extension is None:
            return None

        normalized = extension.strip().lower()

        if normalized.startswith("."):
            normalized = normalized[1:]

        if not normalized:
            return None

        if "/" in normalized or "\\" in normalized:
            raise InvalidQueryError(
                "Расширение файла не должно содержать разделители пути.",
                repository=self.repository_name,
                operation="_normalize_extension",
                details={
                    "field": "extension",
                    "value": normalized,
                },
            )

        if len(normalized) > 32:
            raise InvalidQueryError(
                "Расширение файла не должно превышать 32 символа.",
                repository=self.repository_name,
                operation="_normalize_extension",
                details={
                    "field": "extension",
                    "length": len(normalized),
                    "max_length": 32,
                },
            )

        return normalized

    def _normalize_checksum(
        self,
        checksum: str | None,
    ) -> str | None:
        """Нормализует контрольную сумму файла.

        Значение приводится к нижнему регистру. Пустая строка возвращается как ``None``.

        Args:
            checksum: Контрольная сумма файла.

        Returns:
            Нормализованная контрольная сумма или ``None``.

        Raises:
            InvalidQueryError: Если checksum превышает допустимую длину.
        """

        if checksum is None:
            return None

        normalized = checksum.strip().lower()

        if not normalized:
            return None

        if len(normalized) > 128:
            raise InvalidQueryError(
                "Контрольная сумма не должна превышать 128 символов.",
                repository=self.repository_name,
                operation="_normalize_checksum",
                details={
                    "field": "checksum",
                    "length": len(normalized),
                    "max_length": 128,
                },
            )

        return normalized

    def _normalize_checksum_algorithm(
        self,
        checksum_algorithm: str | None,
    ) -> str | None:
        """Нормализует название алгоритма контрольной суммы.

        Значение приводится к нижнему регистру. Пустая строка возвращается как ``None``.

        Args:
            checksum_algorithm: Название алгоритма контрольной суммы.

        Returns:
            Нормализованное название алгоритма или ``None``.

        Raises:
            InvalidQueryError: Если название алгоритма превышает допустимую длину.
        """

        if checksum_algorithm is None:
            return None

        normalized = checksum_algorithm.strip().lower()

        if not normalized:
            return None

        if len(normalized) > 32:
            raise InvalidQueryError(
                "Название алгоритма checksum не должно превышать 32 символа.",
                repository=self.repository_name,
                operation="_normalize_checksum_algorithm",
                details={
                    "field": "checksum_algorithm",
                    "length": len(normalized),
                    "max_length": 32,
                },
            )

        return normalized

    # ------------------------------------------------------------------
    # Переопределённые методы
    # ------------------------------------------------------------------

    async def create(
        self,
        entity: File,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> File:
        """Добавляет запись файла в текущую сессию.

        Переопределяет базовый метод для более понятной ошибки при конфликтах:
        ``node_id`` уже связан с файлом или ``storage_key`` уже используется.

        Args:
            entity: ORM-объект файла.
            flush: Выполнить ли ``flush`` после добавления.
            refresh: Выполнить ли ``refresh`` после добавления.

        Returns:
            Созданный файл.

        Raises:
            DuplicateEntityError: Если файл с таким ``node_id`` или ``storage_key`` уже существует.
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
                "File",
                field="node_id/storage_key",
                value=f"{entity.node_id}/{entity.storage_key}",
                repository=self.repository_name,
                message="Файл с таким node_id или storage_key уже существует.",
            ) from exc

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_file",
            ) from exc

    async def _execute_file_statement(
        self,
        statement: Select[tuple[File]],
        *,
        operation: str,
    ) -> list[File]:
        """Выполняет SELECT-запрос для модели ``File``.

        Args:
            statement: SQLAlchemy SELECT-запрос.
            operation: Название операции для сообщений об ошибках.

        Returns:
            Список найденных файлов.

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
