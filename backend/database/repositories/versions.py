from __future__ import annotations

import uuid
from typing import Any, TypedDict

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.filesystem import File, FileVersion
from database.repositories.base import BaseRepository


class FileVersionStorageInfo(TypedDict):
    """Информация о версии файла в объектном хранилище.

    Структура используется как компактное представление storage-метаданных
    версии файла без передачи полного ORM-объекта ``FileVersion``.

    Такой формат удобен для сервисного слоя, API-ответов и фоновых задач,
    которым нужно знать расположение объекта в хранилище, размер, MIME-тип,
    checksum и номер версии.

    Attributes:
        storage_bucket: Bucket объектного хранилища, в котором расположен объект
            версии файла.
        storage_key: Ключ объекта версии файла в объектном хранилище.
        size_bytes: Размер версии файла в байтах.
        checksum: Контрольная сумма версии файла или ``None``, если она
            не задана.
        mime_type: MIME-тип версии файла или ``None``, если он не задан.
        version_number: Порядковый номер версии файла.
        is_current: Признак того, что версия является текущей активной версией
            файла.
    """

    storage_bucket: str
    storage_key: str
    size_bytes: int
    checksum: str | None
    mime_type: str | None
    version_number: int
    is_current: bool


class FileVersionRepository(BaseRepository[FileVersion]):
    """Репозиторий для работы с версиями файлов.

    Инкапсулирует операции получения, создания, назначения текущей версии,
    обновления storage-информации, физического удаления, поиска и подсчёта
    версий файлов.

    Репозиторий работает с моделью ``FileVersion`` через асинхронную
    SQLAlchemy-сессию. В отдельных сценариях также обновляет связанное поле
    ``files.current_version_id`` у модели ``File``.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя, Unit of Work или другого внешнего механизма
    управления транзакциями.

    Args:
        session: Асинхронная SQLAlchemy-сессия, используемая для выполнения
            запросов и управления состоянием ORM-объектов.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий версий файлов.

        Args:
            session: Асинхронная SQLAlchemy-сессия, через которую будут
                выполняться операции с моделью ``FileVersion``.
        """

        super().__init__(session=session, model=FileVersion)

    # ------------------------------------------------------------------
    # Получение версий
    # ------------------------------------------------------------------

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> FileVersion | None:
        """Возвращает версию файла по идентификатору.

        Помимо самой версии файла, метод заранее загружает связанные объекты:
        файл и пользователя, создавшего версию. Это помогает избежать
        дополнительных lazy-load запросов при последующей работе с результатом.

        Args:
            entity_id: Уникальный идентификатор версии файла.

        Returns:
            Экземпляр ``FileVersion``, если версия найдена, иначе ``None``.
        """

        statement = (
            select(FileVersion)
            .where(FileVersion.id == entity_id)
            .options(
                selectinload(FileVersion.file),
                selectinload(FileVersion.creator),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_id",
        )

    async def get_required_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> FileVersion:
        """Возвращает версию файла по идентификатору или выбрасывает ошибку.

        Метод используется в сценариях, где отсутствие версии файла считается
        ошибкой бизнес-логики.

        Args:
            entity_id: Уникальный идентификатор версии файла.

        Returns:
            Найденный экземпляр ``FileVersion``.

        Raises:
            EntityNotFoundError: Если версия файла с указанным идентификатором
                не найдена.
        """

        version = await self.get_by_id(entity_id)

        if version is None:
            raise EntityNotFoundError(
                "FileVersion",
                entity_id=entity_id,
                repository=self.repository_name,
            )

        return version

    async def get_versions_by_file_id(
        self,
        file_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        newest_first: bool = True,
    ) -> list[FileVersion]:
        """Возвращает версии указанного файла с пагинацией.

        Метод выбирает версии файла по ``file_id`` и сортирует их по номеру
        версии. При необходимости порядок можно изменить: от новых версий
        к старым или от старых к новым.

        Args:
            file_id: Уникальный идентификатор файла.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей, которое нужно вернуть.
            newest_first: Если ``True``, версии сортируются по убыванию номера
                версии. Если ``False``, используется сортировка по возрастанию.

        Returns:
            Список экземпляров ``FileVersion`` для указанного файла.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        order_by = (
            FileVersion.version_number.desc()
            if newest_first
            else FileVersion.version_number.asc()
        )

        statement = (
            select(FileVersion)
            .where(FileVersion.file_id == file_id)
            .options(
                selectinload(FileVersion.file),
                selectinload(FileVersion.creator),
            )
            .order_by(order_by)
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_versions_by_file_id",
        )

    async def get_latest_version(
        self,
        file_id: uuid.UUID,
    ) -> FileVersion | None:
        """Возвращает последнюю версию файла.

        Последней считается версия с максимальным значением
        ``version_number`` среди всех версий указанного файла.

        Args:
            file_id: Уникальный идентификатор файла.

        Returns:
            Последний экземпляр ``FileVersion``, если у файла есть версии,
            иначе ``None``.
        """

        statement = (
            select(FileVersion)
            .where(FileVersion.file_id == file_id)
            .options(
                selectinload(FileVersion.file),
                selectinload(FileVersion.creator),
            )
            .order_by(FileVersion.version_number.desc())
            .limit(1)
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_latest_version",
        )

    async def get_required_latest_version(
        self,
        file_id: uuid.UUID,
    ) -> FileVersion:
        """Возвращает последнюю версию файла или выбрасывает ошибку.

        Args:
            file_id: Уникальный идентификатор файла.

        Returns:
            Последний экземпляр ``FileVersion`` для указанного файла.

        Raises:
            EntityNotFoundError: Если у файла нет ни одной версии.
        """

        version = await self.get_latest_version(file_id)

        if version is None:
            raise EntityNotFoundError(
                "FileVersion",
                lookup={"file_id": str(file_id), "latest": True},
                repository=self.repository_name,
                message="Последняя версия файла не найдена.",
            )

        return version

    async def get_current_version(
        self,
        file_id: uuid.UUID,
    ) -> FileVersion | None:
        """Возвращает текущую активную версию файла.

        Текущей считается версия, у которой поле ``is_current`` равно ``True``.

        Args:
            file_id: Уникальный идентификатор файла.

        Returns:
            Текущий экземпляр ``FileVersion``, если он найден, иначе ``None``.
        """

        statement = (
            select(FileVersion)
            .where(
                FileVersion.file_id == file_id,
                FileVersion.is_current.is_(True),
            )
            .options(
                selectinload(FileVersion.file),
                selectinload(FileVersion.creator),
            )
            .limit(1)
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_current_version",
        )

    async def get_required_current_version(
        self,
        file_id: uuid.UUID,
    ) -> FileVersion:
        """Возвращает текущую активную версию файла или выбрасывает ошибку.

        Args:
            file_id: Уникальный идентификатор файла.

        Returns:
            Текущий экземпляр ``FileVersion`` для указанного файла.

        Raises:
            EntityNotFoundError: Если текущая версия файла не найдена.
        """

        version = await self.get_current_version(file_id)

        if version is None:
            raise EntityNotFoundError(
                "FileVersion",
                lookup={"file_id": str(file_id), "is_current": True},
                repository=self.repository_name,
                message="Текущая версия файла не найдена.",
            )

        return version

    async def get_by_file_id_and_version_number(
        self,
        *,
        file_id: uuid.UUID,
        version_number: int,
    ) -> FileVersion | None:
        """Возвращает конкретную версию файла по номеру версии.

        Перед выполнением запроса номер версии валидируется. Версия ищется
        внутри конкретного файла, поэтому комбинация ``file_id`` и
        ``version_number`` должна однозначно определять запись.

        Args:
            file_id: Уникальный идентификатор файла.
            version_number: Номер версии файла.

        Returns:
            Экземпляр ``FileVersion``, если версия найдена, иначе ``None``.

        Raises:
            InvalidQueryError: Если номер версии некорректен.
        """

        validated_version_number = self._validate_version_number(version_number)

        statement = (
            select(FileVersion)
            .where(
                FileVersion.file_id == file_id,
                FileVersion.version_number == validated_version_number,
            )
            .options(
                selectinload(FileVersion.file),
                selectinload(FileVersion.creator),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_file_id_and_version_number",
        )

    async def get_required_by_file_id_and_version_number(
        self,
        *,
        file_id: uuid.UUID,
        version_number: int,
    ) -> FileVersion:
        """Возвращает конкретную версию файла по номеру или выбрасывает ошибку.

        Args:
            file_id: Уникальный идентификатор файла.
            version_number: Номер версии файла.

        Returns:
            Найденный экземпляр ``FileVersion``.

        Raises:
            InvalidQueryError: Если номер версии некорректен.
            EntityNotFoundError: Если версия файла с указанным номером
                не найдена.
        """

        version = await self.get_by_file_id_and_version_number(
            file_id=file_id,
            version_number=version_number,
        )

        if version is None:
            raise EntityNotFoundError(
                "FileVersion",
                lookup={
                    "file_id": str(file_id),
                    "version_number": version_number,
                },
                repository=self.repository_name,
            )

        return version

    # ------------------------------------------------------------------
    # Создание версий
    # ------------------------------------------------------------------

    async def create_version(
        self,
        *,
        file_id: uuid.UUID,
        storage_bucket: str,
        storage_key: str,
        size_bytes: int,
        version_number: int | None = None,
        checksum: str | None = None,
        mime_type: str | None = None,
        created_by: uuid.UUID | None = None,
        change_comment: str | None = None,
        is_current: bool = False,
        update_file_current_version: bool = True,
        flush: bool = True,
        refresh: bool = False,
        check_file_exists: bool = True,
    ) -> FileVersion:
        """Создаёт новую версию файла.

        Если ``version_number`` не передан, номер вычисляется автоматически как
        следующий после максимального номера версии для указанного файла.

        Если ``is_current`` равен ``True``, метод снимает признак текущей версии
        у остальных версий этого файла. При включённом
        ``update_file_current_version`` также обновляется поле
        ``files.current_version_id``.

        Метод добавляет версию в текущую сессию и при необходимости выполняет
        ``flush`` и ``refresh``. ``commit`` не выполняется.

        Args:
            file_id: Уникальный идентификатор файла, для которого создаётся
                версия.
            storage_bucket: Bucket объектного хранилища.
            storage_key: Ключ объекта версии файла в объектном хранилище.
            size_bytes: Размер версии файла в байтах.
            version_number: Номер версии файла. Если ``None``, номер
                вычисляется автоматически.
            checksum: Контрольная сумма версии файла.
            mime_type: MIME-тип версии файла.
            created_by: Уникальный идентификатор пользователя, создавшего
                версию.
            change_comment: Комментарий к изменению.
            is_current: Сделать ли создаваемую версию текущей.
            update_file_current_version: Обновлять ли поле
                ``files.current_version_id`` у связанного файла.
            flush: Выполнить ли ``flush`` после создания версии.
            refresh: Выполнить ли ``refresh`` после создания версии.
            check_file_exists: Проверять ли существование файла перед созданием
                версии.

        Returns:
            Созданный экземпляр ``FileVersion``.

        Raises:
            EntityNotFoundError: Если файл не найден.
            InvalidQueryError: Если номер версии, bucket, storage key или размер
                некорректны.
            DuplicateEntityError: Если версия с таким номером, storage key или
                признаком текущей версии уже существует.
        """

        if check_file_exists:
            await self._ensure_file_exists(file_id)

        calculated_version_number = (
            self._validate_version_number(version_number)
            if version_number is not None
            else await self.get_next_version_number(file_id)
        )

        version = FileVersion(
            file_id=file_id,
            version_number=calculated_version_number,
            storage_bucket=self._validate_storage_bucket(storage_bucket),
            storage_key=self._validate_storage_key(storage_key),
            size_bytes=self._validate_size_bytes(size_bytes),
            checksum=self._normalize_checksum(checksum),
            mime_type=self._normalize_mime_type(mime_type),
            created_by=created_by,
            change_comment=self._normalize_change_comment(change_comment),
            is_current=is_current,
        )

        if is_current:
            await self.unset_current_versions(
                file_id=file_id,
                flush=False,
            )

        created_version = await self.create(
            version,
            flush=True,
            refresh=refresh,
        )

        if is_current and update_file_current_version:
            await self._update_file_current_version_id(
                file_id=file_id,
                current_version_id=created_version.id,
                flush=False,
            )

        if flush:
            await self.flush()

        return created_version

    async def get_next_version_number(
        self,
        file_id: uuid.UUID,
    ) -> int:
        """Возвращает следующий номер версии для указанного файла.

        Метод находит максимальный номер версии файла и возвращает следующее
        значение. Если у файла ещё нет версий, возвращается ``1``.

        Args:
            file_id: Уникальный идентификатор файла.

        Returns:
            Следующий номер версии файла.
        """

        statement = select(
            func.coalesce(func.max(FileVersion.version_number), 0) + 1,
        ).where(FileVersion.file_id == file_id)

        result = await self.scalar_value(
            statement,
            operation="get_next_version_number",
        )

        return int(result or 1)

    async def version_number_exists(
        self,
        *,
        file_id: uuid.UUID,
        version_number: int,
    ) -> bool:
        """Проверяет существование версии с указанным номером.

        Args:
            file_id: Уникальный идентификатор файла.
            version_number: Номер версии файла.

        Returns:
            ``True``, если у файла уже существует версия с указанным номером,
            иначе ``False``.

        Raises:
            InvalidQueryError: Если номер версии некорректен.
        """

        validated_version_number = self._validate_version_number(version_number)

        return await self.exists(
            FileVersion.file_id == file_id,
            FileVersion.version_number == validated_version_number,
        )

    async def storage_key_exists(
        self,
        storage_key: str,
        *,
        exclude_version_id: uuid.UUID | None = None,
    ) -> bool:
        """Проверяет, используется ли storage key одной из версий файла.

        Метод полезен при создании версии или обновлении storage-информации,
        когда нужно избежать повторного использования одного и того же ключа
        объекта.

        Args:
            storage_key: Ключ объекта версии файла в объектном хранилище.
            exclude_version_id: Идентификатор версии, которую нужно исключить
                из проверки.

        Returns:
            ``True``, если storage key уже используется, иначе ``False``.

        Raises:
            InvalidQueryError: Если storage key некорректен.
        """

        conditions: list[Any] = [
            FileVersion.storage_key == self._validate_storage_key(storage_key),
        ]

        if exclude_version_id is not None:
            conditions.append(FileVersion.id != exclude_version_id)

        return await self.exists(*conditions)

    # ------------------------------------------------------------------
    # Текущая версия
    # ------------------------------------------------------------------

    async def set_current_version(
        self,
        *,
        version_id: uuid.UUID,
        update_file_current_version: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileVersion:
        """Делает указанную версию текущей.

        Метод получает версию по идентификатору, снимает признак ``is_current``
        у других версий того же файла и устанавливает ``is_current=True`` для
        выбранной версии.

        При включённом ``update_file_current_version`` также обновляется поле
        ``files.current_version_id`` у связанного файла.

        Args:
            version_id: Уникальный идентификатор версии файла.
            update_file_current_version: Обновлять ли поле
                ``files.current_version_id`` у связанного файла.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``FileVersion``, назначенный текущей версией.

        Raises:
            EntityNotFoundError: Если версия файла не найдена.
        """

        version = await self.get_required_by_id(version_id)

        await self.unset_current_versions(
            file_id=version.file_id,
            exclude_version_id=version.id,
            flush=False,
        )

        version.is_current = True

        if update_file_current_version:
            await self._update_file_current_version_id(
                file_id=version.file_id,
                current_version_id=version.id,
                flush=False,
            )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(version)

        return version

    async def set_current_version_by_number(
        self,
        *,
        file_id: uuid.UUID,
        version_number: int,
        update_file_current_version: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileVersion:
        """Делает текущей версию файла по номеру версии.

        Сначала находит версию по комбинации ``file_id`` и ``version_number``,
        затем делегирует назначение текущей версии методу
        ``set_current_version``.

        Args:
            file_id: Уникальный идентификатор файла.
            version_number: Номер версии файла.
            update_file_current_version: Обновлять ли поле
                ``files.current_version_id`` у связанного файла.
            flush: Выполнить ли ``flush`` после изменения.
            refresh: Выполнить ли ``refresh`` после изменения.

        Returns:
            Обновлённый экземпляр ``FileVersion``, назначенный текущей версией.

        Raises:
            InvalidQueryError: Если номер версии некорректен.
            EntityNotFoundError: Если версия файла не найдена.
        """

        version = await self.get_required_by_file_id_and_version_number(
            file_id=file_id,
            version_number=version_number,
        )

        return await self.set_current_version(
            version_id=version.id,
            update_file_current_version=update_file_current_version,
            flush=flush,
            refresh=refresh,
        )

    async def unset_current_versions(
        self,
        *,
        file_id: uuid.UUID,
        exclude_version_id: uuid.UUID | None = None,
        flush: bool = True,
    ) -> int:
        """Снимает признак текущей версии у версий указанного файла.

        Метод выполняет массовое обновление и устанавливает
        ``is_current=False`` для текущих версий файла. При переданном
        ``exclude_version_id`` указанная версия не изменяется.

        Args:
            file_id: Уникальный идентификатор файла.
            exclude_version_id: Идентификатор версии, которую нужно оставить
                без изменений.
            flush: Выполнить ли ``flush`` после массового обновления.

        Returns:
            Количество обновлённых версий.

        Raises:
            RepositoryError: Если произошла ошибка при выполнении массового
                обновления.
        """

        try:
            statement = (
                update(FileVersion)
                .where(
                    FileVersion.file_id == file_id,
                    FileVersion.is_current.is_(True),
                )
                .values(is_current=False)
            )

            if exclude_version_id is not None:
                statement = statement.where(
                    FileVersion.id != exclude_version_id,
                )

            result = await self.session.execute(statement)

            if flush:
                await self.flush()

            return int(getattr(result, "rowcount", 0) or 0)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="unset_current_versions",
                reason=str(exc),
                details={
                    "file_id": str(file_id),
                    "exclude_version_id": str(exclude_version_id)
                    if exclude_version_id is not None
                    else None,
                },
                cause=exc,
            ) from exc

    async def clear_file_current_version(
        self,
        *,
        file_id: uuid.UUID,
        flush: bool = True,
    ) -> None:
        """Очищает текущую версию файла.

        Метод снимает признак ``is_current`` у всех версий указанного файла и
        устанавливает ``files.current_version_id`` в ``None``.

        Args:
            file_id: Уникальный идентификатор файла.
            flush: Выполнить ли ``flush`` после обновления.

        Raises:
            RepositoryError: Если произошла ошибка при обновлении версий или
                связанного файла.
        """

        await self.unset_current_versions(
            file_id=file_id,
            flush=False,
        )

        await self._update_file_current_version_id(
            file_id=file_id,
            current_version_id=None,
            flush=False,
        )

        if flush:
            await self.flush()

    # ------------------------------------------------------------------
    # Storage-информация
    # ------------------------------------------------------------------

    async def get_version_storage_info(
        self,
        version_id: uuid.UUID,
    ) -> FileVersionStorageInfo:
        """Возвращает storage-информацию версии файла.

        Метод получает версию файла по идентификатору и возвращает только
        данные, необходимые для работы с объектным хранилищем.

        Args:
            version_id: Уникальный идентификатор версии файла.

        Returns:
            Структура ``FileVersionStorageInfo`` с bucket, storage key,
            размером, checksum, MIME-типом, номером версии и признаком текущей
            версии.

        Raises:
            EntityNotFoundError: Если версия файла не найдена.
        """

        version = await self.get_required_by_id(version_id)

        return {
            "storage_bucket": version.storage_bucket,
            "storage_key": version.storage_key,
            "size_bytes": version.size_bytes,
            "checksum": version.checksum,
            "mime_type": version.mime_type,
            "version_number": version.version_number,
            "is_current": version.is_current,
        }

    async def get_current_version_storage_info(
        self,
        file_id: uuid.UUID,
    ) -> FileVersionStorageInfo:
        """Возвращает storage-информацию текущей версии файла.

        Args:
            file_id: Уникальный идентификатор файла.

        Returns:
            Структура ``FileVersionStorageInfo`` для текущей версии файла.

        Raises:
            EntityNotFoundError: Если текущая версия файла не найдена.
        """

        version = await self.get_required_current_version(file_id)

        return {
            "storage_bucket": version.storage_bucket,
            "storage_key": version.storage_key,
            "size_bytes": version.size_bytes,
            "checksum": version.checksum,
            "mime_type": version.mime_type,
            "version_number": version.version_number,
            "is_current": version.is_current,
        }

    async def list_storage_info_by_file_id(
        self,
        file_id: uuid.UUID,
    ) -> list[FileVersionStorageInfo]:
        """Возвращает storage-информацию всех версий файла.

        Версии возвращаются в порядке возрастания номера версии. Метод
        ограничивает выборку первыми ``1000`` версиями.

        Args:
            file_id: Уникальный идентификатор файла.

        Returns:
            Список структур ``FileVersionStorageInfo`` для всех найденных
            версий файла.
        """

        versions = await self.get_versions_by_file_id(
            file_id,
            offset=0,
            limit=1000,
            newest_first=False,
        )

        return [
            {
                "storage_bucket": version.storage_bucket,
                "storage_key": version.storage_key,
                "size_bytes": version.size_bytes,
                "checksum": version.checksum,
                "mime_type": version.mime_type,
                "version_number": version.version_number,
                "is_current": version.is_current,
            }
            for version in versions
        ]

    # ------------------------------------------------------------------
    # Обновление версии
    # ------------------------------------------------------------------

    async def update_version_storage_info(
        self,
        *,
        version_id: uuid.UUID,
        storage_bucket: str,
        storage_key: str,
        size_bytes: int | None = None,
        checksum: str | None = None,
        mime_type: str | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileVersion:
        """Обновляет storage-информацию версии файла.

        Метод обновляет bucket, storage key, checksum, MIME-тип и, если передан
        ``size_bytes``, размер версии файла.

        Args:
            version_id: Уникальный идентификатор версии файла.
            storage_bucket: Новый bucket объектного хранилища.
            storage_key: Новый ключ объекта версии файла в объектном хранилище.
            size_bytes: Новый размер версии файла в байтах. Если ``None``,
                размер не изменяется.
            checksum: Новая контрольная сумма. ``None`` или пустая строка
                очищают значение.
            mime_type: Новый MIME-тип. ``None`` или пустая строка очищают
                значение.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый экземпляр ``FileVersion``.

        Raises:
            EntityNotFoundError: Если версия файла не найдена.
            InvalidQueryError: Если bucket, storage key, размер, checksum или
                MIME-тип некорректны.
        """

        version = await self.get_required_by_id(version_id)

        values: dict[str, Any] = {
            "storage_bucket": self._validate_storage_bucket(storage_bucket),
            "storage_key": self._validate_storage_key(storage_key),
            "checksum": self._normalize_checksum(checksum),
            "mime_type": self._normalize_mime_type(mime_type),
        }

        if size_bytes is not None:
            values["size_bytes"] = self._validate_size_bytes(size_bytes)

        return await self.update(
            version,
            values,
            flush=flush,
            refresh=refresh,
            allowed_fields={
                "storage_bucket",
                "storage_key",
                "size_bytes",
                "checksum",
                "mime_type",
            },
        )

    async def update_change_comment(
        self,
        *,
        version_id: uuid.UUID,
        change_comment: str | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileVersion:
        """Обновляет комментарий к версии файла.

        ``None`` или пустая после нормализации строка очищают комментарий.

        Args:
            version_id: Уникальный идентификатор версии файла.
            change_comment: Новый комментарий к версии файла.
            flush: Выполнить ли ``flush`` после обновления.
            refresh: Выполнить ли ``refresh`` после обновления.

        Returns:
            Обновлённый экземпляр ``FileVersion``.

        Raises:
            EntityNotFoundError: Если версия файла не найдена.
        """

        version = await self.get_required_by_id(version_id)

        return await self.update(
            version,
            {"change_comment": self._normalize_change_comment(change_comment)},
            flush=flush,
            refresh=refresh,
            allowed_fields={"change_comment"},
        )

    # ------------------------------------------------------------------
    # Удаление версий
    # ------------------------------------------------------------------

    async def delete_versions_by_file_id(
        self,
        file_id: uuid.UUID,
        *,
        flush: bool = True,
    ) -> int:
        """Физически удаляет все версии указанного файла.

        Метод удаляет только metadata-записи из таблицы ``file_versions``.
        Удаление объектов из MinIO или другого объектного хранилища должно
        выполняться сервисным слоем или фоновой задачей.

        После удаления версий поле ``files.current_version_id`` очищается.

        Args:
            file_id: Уникальный идентификатор файла.
            flush: Выполнить ли ``flush`` после удаления.

        Returns:
            Количество удалённых версий.
        """

        deleted_count = await self.bulk_delete(
            FileVersion.file_id == file_id,
            flush=False,
        )

        await self._update_file_current_version_id(
            file_id=file_id,
            current_version_id=None,
            flush=False,
        )

        if flush:
            await self.flush()

        return deleted_count

    async def delete_version(
        self,
        version_id: uuid.UUID,
        *,
        flush: bool = True,
        required: bool = True,
        clear_file_current_version: bool = True,
    ) -> bool:
        """Физически удаляет одну версию файла.

        Если удаляемая версия была текущей и ``clear_file_current_version``
        равен ``True``, поле ``files.current_version_id`` у связанного файла
        очищается.

        Метод удаляет только metadata-запись версии. Удаление физического
        объекта из хранилища должно выполняться вне репозитория.

        Args:
            version_id: Уникальный идентификатор версии файла.
            flush: Выполнить ли ``flush`` после удаления.
            required: Если ``True``, выбрасывать ошибку при отсутствии версии.
                Если ``False``, возвращать ``False``.
            clear_file_current_version: Очищать ли текущую версию у файла,
                если удаляемая версия была текущей.

        Returns:
            ``True``, если версия была удалена. ``False``, если версия не
            найдена и ``required=False``.

        Raises:
            EntityNotFoundError: Если версия не найдена и ``required=True``.
        """

        version = await self.get_by_id(version_id)

        if version is None:
            if required:
                raise EntityNotFoundError(
                    "FileVersion",
                    entity_id=version_id,
                    repository=self.repository_name,
                )

            return False

        file_id = version.file_id
        was_current = version.is_current

        await self.delete(version, flush=False)

        if was_current and clear_file_current_version:
            await self._update_file_current_version_id(
                file_id=file_id,
                current_version_id=None,
                flush=False,
            )

        if flush:
            await self.flush()

        return True

    async def delete_old_versions(
        self,
        *,
        file_id: uuid.UUID,
        keep_latest: int,
        keep_current: bool = True,
        flush: bool = True,
    ) -> int:
        """Удаляет старые версии файла, оставляя последние версии.

        Метод загружает версии файла в порядке от новых к старым и удаляет
        версии, которые выходят за пределы лимита ``keep_latest``. Если
        ``keep_current`` равен ``True``, текущая версия сохраняется даже при
        превышении лимита.

        Удаляются только metadata-записи ``file_versions``. Физические объекты
        из MinIO или другого объектного хранилища должен удалять сервисный слой
        или фоновая задача.

        Args:
            file_id: Уникальный идентификатор файла.
            keep_latest: Количество последних версий, которые нужно сохранить.
            keep_current: Сохранять ли текущую версию даже при превышении
                лимита.
            flush: Выполнить ли ``flush`` после удаления.

        Returns:
            Количество удалённых версий.

        Raises:
            InvalidQueryError: Если ``keep_latest`` меньше нуля.
        """

        if keep_latest < 0:
            raise InvalidQueryError(
                "Количество сохраняемых последних версий не может быть отрицательным.",
                repository=self.repository_name,
                operation="delete_old_versions",
                details={"keep_latest": keep_latest},
            )

        versions = await self.get_versions_by_file_id(
            file_id,
            offset=0,
            limit=1000,
            newest_first=True,
        )

        versions_to_delete = versions[keep_latest:]

        deleted_count = 0

        for version in versions_to_delete:
            if keep_current and version.is_current:
                continue

            await self.delete(version, flush=False)
            deleted_count += 1

        if flush:
            await self.flush()

        return deleted_count

    # ------------------------------------------------------------------
    # Подсчёты
    # ------------------------------------------------------------------

    async def count_versions(
        self,
        file_id: uuid.UUID,
    ) -> int:
        """Возвращает количество версий указанного файла.

        Args:
            file_id: Уникальный идентификатор файла.

        Returns:
            Количество версий файла.
        """

        return await self.count(FileVersion.file_id == file_id)

    async def count_all_versions(self) -> int:
        """Возвращает общее количество версий файлов.

        Returns:
            Общее количество записей ``file_versions``.
        """

        return await self.count()

    # ------------------------------------------------------------------
    # Дополнительные выборки
    # ------------------------------------------------------------------

    async def find_by_storage_key(
        self,
        storage_key: str,
    ) -> FileVersion | None:
        """Возвращает версию файла по storage key.

        Перед поиском storage key валидируется и нормализуется.

        Args:
            storage_key: Ключ объекта версии файла в объектном хранилище.

        Returns:
            Экземпляр ``FileVersion``, если версия найдена, иначе ``None``.

        Raises:
            InvalidQueryError: Если storage key некорректен.
        """

        normalized_storage_key = self._validate_storage_key(storage_key)

        statement = (
            select(FileVersion)
            .where(FileVersion.storage_key == normalized_storage_key)
            .options(
                selectinload(FileVersion.file),
                selectinload(FileVersion.creator),
            )
        )

        return await self.scalar_one_or_none(
            statement,
            operation="find_by_storage_key",
        )

    async def get_required_by_storage_key(
        self,
        storage_key: str,
    ) -> FileVersion:
        """Возвращает версию файла по storage key или выбрасывает ошибку.

        Args:
            storage_key: Ключ объекта версии файла в объектном хранилище.

        Returns:
            Найденный экземпляр ``FileVersion``.

        Raises:
            InvalidQueryError: Если storage key некорректен.
            EntityNotFoundError: Если версия файла с указанным storage key
                не найдена.
        """

        version = await self.find_by_storage_key(storage_key)

        if version is None:
            raise EntityNotFoundError(
                "FileVersion",
                lookup={"storage_key": storage_key},
                repository=self.repository_name,
            )

        return version

    async def list_by_checksum(
        self,
        *,
        checksum: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[FileVersion]:
        """Возвращает версии файлов по контрольной сумме.

        Метод используется для поиска версий с одинаковым содержимым или для
        проверки наличия уже загруженного объекта по checksum.

        Args:
            checksum: Контрольная сумма для поиска.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей, которое нужно вернуть.

        Returns:
            Список экземпляров ``FileVersion`` с указанной контрольной суммой.

        Raises:
            InvalidQueryError: Если checksum пустой после нормализации или если
                параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        normalized_checksum = self._normalize_checksum(checksum)

        if normalized_checksum is None:
            raise InvalidQueryError(
                "Checksum для поиска версии файла не может быть пустым.",
                repository=self.repository_name,
                operation="list_by_checksum",
                details={"field": "checksum"},
            )

        statement = (
            select(FileVersion)
            .where(FileVersion.checksum == normalized_checksum)
            .options(
                selectinload(FileVersion.file),
                selectinload(FileVersion.creator),
            )
            .order_by(FileVersion.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="list_by_checksum",
        )

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    async def _ensure_file_exists(
        self,
        file_id: uuid.UUID,
    ) -> File:
        """Проверяет существование файла.

        Метод выполняет прямой запрос к таблице файлов и возвращает найденный
        ORM-объект ``File``. Используется перед созданием версии, когда нужно
        убедиться, что связанный файл существует.

        Args:
            file_id: Уникальный идентификатор файла.

        Returns:
            Найденный экземпляр ``File``.

        Raises:
            EntityNotFoundError: Если файл с указанным идентификатором
                не найден.
            RepositoryError: Если произошла ошибка SQLAlchemy при обращении
                к базе данных.
        """

        try:
            result = await self.session.execute(
                select(File).where(File.id == file_id),
            )
            file = result.scalar_one_or_none()

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="_ensure_file_exists",
                reason=str(exc),
                details={"file_id": str(file_id)},
                cause=exc,
            ) from exc

        if file is None:
            raise EntityNotFoundError(
                "File",
                entity_id=file_id,
                repository=self.repository_name,
            )

        return file

    async def _update_file_current_version_id(
        self,
        *,
        file_id: uuid.UUID,
        current_version_id: uuid.UUID | None,
        flush: bool = True,
    ) -> None:
        """Обновляет поле ``files.current_version_id``.

        Метод выполняет массовое обновление записи файла и устанавливает
        идентификатор текущей версии или очищает его, если передан ``None``.

        Args:
            file_id: Уникальный идентификатор файла.
            current_version_id: Идентификатор текущей версии файла или ``None``.
            flush: Выполнить ли ``flush`` после обновления.

        Raises:
            RepositoryError: Если произошла ошибка SQLAlchemy при обновлении
                файла.
        """

        try:
            statement = (
                update(File)
                .where(File.id == file_id)
                .values(current_version_id=current_version_id)
            )

            await self.session.execute(statement)

            if flush:
                await self.flush()

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="_update_file_current_version_id",
                reason=str(exc),
                details={
                    "file_id": str(file_id),
                    "current_version_id": str(current_version_id)
                    if current_version_id is not None
                    else None,
                },
                cause=exc,
            ) from exc

    def _validate_version_number(
        self,
        version_number: int,
    ) -> int:
        """Проверяет номер версии файла.

        Номер версии должен быть положительным целым числом.

        Args:
            version_number: Номер версии файла.

        Returns:
            Проверенный номер версии файла.

        Raises:
            InvalidQueryError: Если номер версии не является ``int`` или меньше
                либо равен нулю.
        """

        if not isinstance(version_number, int):
            raise InvalidQueryError(
                "Номер версии файла должен быть целым числом.",
                repository=self.repository_name,
                operation="_validate_version_number",
                details={
                    "field": "version_number",
                    "value_type": type(version_number).__name__,
                },
            )

        if version_number <= 0:
            raise InvalidQueryError(
                "Номер версии файла должен быть положительным.",
                repository=self.repository_name,
                operation="_validate_version_number",
                details={
                    "field": "version_number",
                    "value": version_number,
                },
            )

        return version_number

    def _validate_storage_bucket(
        self,
        storage_bucket: str,
    ) -> str:
        """Проверяет и нормализует bucket объектного хранилища.

        Удаляет пробелы по краям строки и проверяет, что bucket не пустой и не
        превышает допустимую длину.

        Args:
            storage_bucket: Bucket объектного хранилища.

        Returns:
            Нормализованное имя bucket.

        Raises:
            InvalidQueryError: Если bucket пустой или превышает допустимую
                длину.
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
        """Проверяет и нормализует ключ объекта версии файла.

        Удаляет пробелы по краям строки и проверяет, что storage key не пустой.

        Args:
            storage_key: Ключ объекта версии файла в объектном хранилище.

        Returns:
            Нормализованный storage key.

        Raises:
            InvalidQueryError: Если storage key пустой после нормализации.
        """

        normalized = storage_key.strip()

        if not normalized:
            raise InvalidQueryError(
                "Ключ объекта версии файла не может быть пустым.",
                repository=self.repository_name,
                operation="_validate_storage_key",
                details={"field": "storage_key"},
            )

        return normalized

    def _validate_size_bytes(
        self,
        size_bytes: int,
    ) -> int:
        """Проверяет размер версии файла.

        Размер должен быть целым неотрицательным числом.

        Args:
            size_bytes: Размер версии файла в байтах.

        Returns:
            Проверенный размер версии файла.

        Raises:
            InvalidQueryError: Если размер не является ``int`` или меньше нуля.
        """

        if not isinstance(size_bytes, int):
            raise InvalidQueryError(
                "Размер версии файла должен быть целым числом.",
                repository=self.repository_name,
                operation="_validate_size_bytes",
                details={
                    "field": "size_bytes",
                    "value_type": type(size_bytes).__name__,
                },
            )

        if size_bytes < 0:
            raise InvalidQueryError(
                "Размер версии файла не может быть отрицательным.",
                repository=self.repository_name,
                operation="_validate_size_bytes",
                details={
                    "field": "size_bytes",
                    "value": size_bytes,
                },
            )

        return size_bytes

    def _normalize_checksum(
        self,
        checksum: str | None,
    ) -> str | None:
        """Нормализует контрольную сумму версии файла.

        Значение приводится к нижнему регистру. ``None`` или пустая после
        удаления пробелов строка возвращаются как ``None``.

        Args:
            checksum: Контрольная сумма версии файла.

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
                "Контрольная сумма версии файла не должна превышать 128 символов.",
                repository=self.repository_name,
                operation="_normalize_checksum",
                details={
                    "field": "checksum",
                    "length": len(normalized),
                    "max_length": 128,
                },
            )

        return normalized

    def _normalize_mime_type(
        self,
        mime_type: str | None,
    ) -> str | None:
        """Нормализует MIME-тип версии файла.

        Значение приводится к нижнему регистру. ``None`` или пустая после
        удаления пробелов строка возвращаются как ``None``.

        Args:
            mime_type: MIME-тип версии файла.

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
                "MIME-тип версии файла не должен превышать 255 символов.",
                repository=self.repository_name,
                operation="_normalize_mime_type",
                details={
                    "field": "mime_type",
                    "length": len(normalized),
                    "max_length": 255,
                },
            )

        return normalized

    def _normalize_change_comment(
        self,
        change_comment: str | None,
    ) -> str | None:
        """Нормализует комментарий к версии файла.

        Удаляет пробелы по краям строки. Если после нормализации строка пустая,
        возвращает ``None``.

        Args:
            change_comment: Комментарий к версии файла.

        Returns:
            Нормализованный комментарий или ``None``.
        """

        if change_comment is None:
            return None

        normalized = change_comment.strip()

        return normalized or None

    # ------------------------------------------------------------------
    # Переопределённые методы
    # ------------------------------------------------------------------

    async def create(
        self,
        entity: FileVersion,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> FileVersion:
        """Добавляет версию файла в текущую сессию.

        Переопределяет базовый метод для более понятной обработки конфликтов
        уникальности: повторного ``version_number`` внутри одного файла,
        повторного ``storage_key`` или нарушения ограничения на текущую версию.

        Args:
            entity: ORM-объект версии файла, который нужно добавить в сессию.
            flush: Выполнить ли ``flush`` после добавления.
            refresh: Выполнить ли ``refresh`` после добавления.

        Returns:
            Созданный экземпляр ``FileVersion``.

        Raises:
            DuplicateEntityError: Если версия с таким номером, storage key или
                признаком текущей версии уже существует.
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
                "FileVersion",
                field="file_id/version_number/storage_key",
                value=(
                    f"{entity.file_id}/{entity.version_number}/{entity.storage_key}"
                ),
                repository=self.repository_name,
                message=(
                    "Версия файла с таким номером, storage_key "
                    "или признаком текущей версии уже существует."
                ),
            ) from exc

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_version",
            ) from exc

    async def _execute_file_version_statement(
        self,
        statement: Select[tuple[FileVersion]],
        *,
        operation: str,
    ) -> list[FileVersion]:
        """Выполняет SELECT-запрос для модели ``FileVersion``.

        Метод инкапсулирует выполнение SQLAlchemy-запроса и преобразование
        результата в список ORM-объектов ``FileVersion``. Также обеспечивает
        единообразную обработку ошибок уникальности и общих SQLAlchemy-ошибок.

        Args:
            statement: SQLAlchemy ``SELECT``-запрос, возвращающий объекты
                ``FileVersion``.
            operation: Название операции, используемое в сообщениях и деталях
                ошибок репозитория.

        Returns:
            Список найденных экземпляров ``FileVersion``.

        Raises:
            DuplicateEntityError: Если произошёл конфликт уникальности.
            RepositoryError: Если произошла ошибка SQLAlchemy при выполнении
                запроса.
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
