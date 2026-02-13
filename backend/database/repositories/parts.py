from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypedDict

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import UploadPartStatus
from database.models.uploads import UploadPart, UploadSession
from database.repositories.base import BaseRepository


class UploadedPartCompletionInfo(TypedDict):
    """Данные загруженной части, необходимые для завершения multipart upload.

    Используется как компактный результат для передачи в S3/MinIO
    ``CompleteMultipartUpload``, где важны номер части, ETag и связанные
    контрольные метаданные.

    Attributes:
        part_number: Номер части multipart-загрузки.
        etag: ETag, полученный от объектного хранилища после загрузки части.
        size_bytes: Размер загруженной части в байтах.
        checksum: Контрольная сумма части.
    """

    part_number: int
    etag: str
    size_bytes: int
    checksum: str | None


class UploadPartsRepository(BaseRepository[UploadPart]):
    """Репозиторий для работы с частями multipart-загрузки.

    Инкапсулирует операции получения, создания, массового создания,
    изменения статусов, обновления ETag/checksum, проверки готовности,
    подсчёта, подготовки данных для завершения multipart upload
    и физического удаления частей.

    Работает с моделью ``UploadPart`` через асинхронную SQLAlchemy-сессию.

    Репозиторий не выполняет ``commit``. Фиксация транзакций должна происходить
    на уровне сервисного слоя или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий частей multipart-загрузки.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=UploadPart)

    # ------------------------------------------------------------------
    # Базовые выборки
    # ------------------------------------------------------------------

    async def get_part_by_id(
        self,
        upload_part_id: uuid.UUID,
    ) -> UploadPart | None:
        """Возвращает часть загрузки по идентификатору.

        Args:
            upload_part_id: Идентификатор части загрузки.

        Returns:
            Часть загрузки, если она найдена, иначе ``None``.
        """

        return await self.get_by_id(upload_part_id)

    async def get_required_part_by_id(
        self,
        upload_part_id: uuid.UUID,
    ) -> UploadPart:
        """Возвращает часть загрузки по идентификатору.

        Args:
            upload_part_id: Идентификатор части загрузки.

        Returns:
            Найденная часть загрузки.

        Raises:
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        return await self.get_required_by_id(upload_part_id)

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> UploadPart | None:
        """Возвращает часть загрузки по идентификатору.

        Дополнительно загружает связанную upload-сессию.

        Args:
            entity_id: Идентификатор части загрузки.

        Returns:
            Часть загрузки, если она найдена, иначе ``None``.
        """

        statement = (
            select(UploadPart)
            .where(UploadPart.id == entity_id)
            .options(selectinload(UploadPart.upload_session))
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_id",
        )

    async def get_required_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> UploadPart:
        """Возвращает часть загрузки по идентификатору.

        Args:
            entity_id: Идентификатор части загрузки.

        Returns:
            Найденная часть загрузки.

        Raises:
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        upload_part = await self.get_by_id(entity_id)

        if upload_part is None:
            raise EntityNotFoundError(
                "UploadPart",
                entity_id=entity_id,
                repository=self.repository_name,
            )

        return upload_part

    async def get_by_session_and_part_number(
        self,
        upload_session_id: uuid.UUID,
        part_number: int,
    ) -> UploadPart | None:
        """Возвращает часть загрузки по идентификатору сессии и номеру части.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части в рамках multipart-загрузки.

        Returns:
            Часть загрузки, если она найдена, иначе ``None``.

        Raises:
            InvalidQueryError: Если номер части некорректен.
        """

        self._validate_part_number(part_number)

        statement = (
            select(UploadPart)
            .where(
                UploadPart.upload_session_id == upload_session_id,
                UploadPart.part_number == part_number,
            )
            .options(selectinload(UploadPart.upload_session))
        )

        return await self.scalar_one_or_none(
            statement,
            operation="get_by_session_and_part_number",
        )

    async def get_required_by_session_and_part_number(
        self,
        upload_session_id: uuid.UUID,
        part_number: int,
    ) -> UploadPart:
        """Возвращает обязательную часть загрузки по сессии и номеру части.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части в рамках multipart-загрузки.

        Returns:
            Найденная часть загрузки.

        Raises:
            InvalidQueryError: Если номер части некорректен.
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        upload_part = await self.get_by_session_and_part_number(
            upload_session_id=upload_session_id,
            part_number=part_number,
        )

        if upload_part is None:
            raise EntityNotFoundError(
                "UploadPart",
                lookup={
                    "upload_session_id": str(upload_session_id),
                    "part_number": part_number,
                },
                repository=self.repository_name,
            )

        return upload_part

    async def get_session_parts(
        self,
        upload_session_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[UploadPart]:
        """Возвращает части указанной upload-сессии с пагинацией.

        Части сортируются по номеру части по возрастанию.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список частей upload-сессии.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(UploadPart)
            .where(UploadPart.upload_session_id == upload_session_id)
            .options(selectinload(UploadPart.upload_session))
            .order_by(UploadPart.part_number.asc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(
            statement,
            operation="get_session_parts",
        )

    async def get_uploaded_parts(
        self,
        upload_session_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[UploadPart]:
        """Возвращает успешно загруженные части указанной upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список частей со статусом ``UPLOADED``.
        """

        return await self.get_session_parts_by_status(
            upload_session_id=upload_session_id,
            status=UploadPartStatus.UPLOADED,
            offset=offset,
            limit=limit,
            operation="get_uploaded_parts",
        )

    async def get_pending_parts(
        self,
        upload_session_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[UploadPart]:
        """Возвращает части указанной upload-сессии, ожидающие загрузки.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список частей со статусом ``PENDING``.
        """

        return await self.get_session_parts_by_status(
            upload_session_id=upload_session_id,
            status=UploadPartStatus.PENDING,
            offset=offset,
            limit=limit,
            operation="get_pending_parts",
        )

    async def get_failed_parts(
        self,
        upload_session_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[UploadPart]:
        """Возвращает части указанной upload-сессии, загрузка которых завершилась ошибкой.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.

        Returns:
            Список частей со статусом ``FAILED``.
        """

        return await self.get_session_parts_by_status(
            upload_session_id=upload_session_id,
            status=UploadPartStatus.FAILED,
            offset=offset,
            limit=limit,
            operation="get_failed_parts",
        )

    async def get_session_parts_by_status(
        self,
        *,
        upload_session_id: uuid.UUID,
        status: UploadPartStatus,
        offset: int = 0,
        limit: int = 1000,
        operation: str = "get_session_parts_by_status",
    ) -> list[UploadPart]:
        """Возвращает части upload-сессии по указанному статусу.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            status: Статус частей для фильтрации.
            offset: Количество записей, которые нужно пропустить.
            limit: Максимальное количество записей.
            operation: Название операции для сообщений об ошибках.

        Returns:
            Список частей с указанным статусом.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = (
            select(UploadPart)
            .where(
                UploadPart.upload_session_id == upload_session_id,
                UploadPart.status == status,
            )
            .options(selectinload(UploadPart.upload_session))
            .order_by(UploadPart.part_number.asc())
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(statement, operation=operation)

    # ------------------------------------------------------------------
    # Создание
    # ------------------------------------------------------------------

    async def create_part(
        self,
        *,
        upload_session_id: uuid.UUID,
        part_number: int,
        size_bytes: int,
        etag: str | None = None,
        checksum: str | None = None,
        status: UploadPartStatus = UploadPartStatus.PENDING,
        uploaded_at: datetime | None = None,
        failed_at: datetime | None = None,
        failure_reason: str | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_session_exists: bool = False,
        check_duplicate: bool = True,
    ) -> UploadPart:
        """Создаёт одну часть multipart-загрузки.

        Перед созданием валидирует номер части, размер, статус и связанные поля.
        При необходимости проверяет существование upload-сессии и отсутствие
        дубликата по паре ``upload_session_id + part_number``.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.
            size_bytes: Размер части в байтах.
            etag: ETag части, если она уже загружена.
            checksum: Контрольная сумма части.
            status: Начальный статус части.
            uploaded_at: Дата успешной загрузки части.
            failed_at: Дата ошибки загрузки части.
            failure_reason: Причина ошибки загрузки.
            flush: Выполнить ``flush`` после создания.
            refresh: Выполнить ``refresh`` после создания.
            check_session_exists: Проверять ли существование upload-сессии.
            check_duplicate: Проверять ли дубликат номера части в сессии.

        Returns:
            Созданная часть загрузки.

        Raises:
            InvalidQueryError: Если значения части некорректны.
            EntityNotFoundError: Если upload-сессия не найдена.
            DuplicateEntityError: Если часть с таким номером уже существует в сессии.
        """

        self._validate_part_values(
            part_number=part_number,
            size_bytes=size_bytes,
            status=status,
            etag=etag,
            uploaded_at=uploaded_at,
            failed_at=failed_at,
            failure_reason=failure_reason,
        )

        if check_session_exists:
            await self._ensure_upload_session_exists(upload_session_id)

        if check_duplicate and await self.part_exists(
            upload_session_id=upload_session_id,
            part_number=part_number,
        ):
            raise DuplicateEntityError(
                "UploadPart",
                field="upload_session_id/part_number",
                value=f"{upload_session_id}/{part_number}",
                repository=self.repository_name,
                message="Часть с таким номером уже существует в указанной upload-сессии.",
            )

        upload_part = UploadPart(
            upload_session_id=upload_session_id,
            part_number=part_number,
            size_bytes=size_bytes,
            etag=self._normalize_etag(etag),
            checksum=self._normalize_checksum(checksum),
            status=status,
            uploaded_at=uploaded_at,
            failed_at=failed_at,
            failure_reason=self._normalize_failure_reason(failure_reason),
        )

        return await self.create(
            upload_part,
            flush=flush,
            refresh=refresh,
        )

    async def create_parts(
        self,
        upload_session_id: uuid.UUID,
        parts: Sequence[dict[str, Any]],
        *,
        flush: bool = True,
        check_session_exists: bool = False,
    ) -> list[UploadPart]:
        """Создаёт несколько частей multipart-загрузки.

        Каждый словарь в ``parts`` должен содержать ``part_number`` и
        ``size_bytes``. Дополнительно могут быть переданы ``etag``, ``checksum``,
        ``status``, ``uploaded_at``, ``failed_at`` и ``failure_reason``.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            parts: Последовательность словарей с данными частей.
            flush: Выполнить ``flush`` после создания.
            check_session_exists: Проверять ли существование upload-сессии.

        Returns:
            Список созданных частей загрузки.

        Raises:
            InvalidQueryError: Если список пустой, часть содержит некорректные данные
                или номера частей повторяются.
            EntityNotFoundError: Если upload-сессия не найдена.
            DuplicateEntityError: Если часть с таким номером уже существует в сессии.
        """

        if not parts:
            raise InvalidQueryError(
                "Список частей загрузки не может быть пустым.",
                repository=self.repository_name,
                operation="create_parts",
                details={
                    "model": self.model_name,
                    "upload_session_id": str(upload_session_id),
                },
            )

        if check_session_exists:
            await self._ensure_upload_session_exists(upload_session_id)

        upload_parts: list[UploadPart] = []
        seen_part_numbers: set[int] = set()

        for part_data in parts:
            try:
                part_number = int(part_data["part_number"])
                size_bytes = int(part_data["size_bytes"])
            except KeyError as exc:
                raise InvalidQueryError(
                    "Данные части загрузки должны содержать part_number и size_bytes.",
                    repository=self.repository_name,
                    operation="create_parts",
                    details={
                        "upload_session_id": str(upload_session_id),
                        "part_data": part_data,
                        "missing_key": str(exc),
                    },
                ) from exc

            status = self._coerce_status(
                part_data.get("status", UploadPartStatus.PENDING),
            )
            etag = part_data.get("etag")
            checksum = part_data.get("checksum")
            uploaded_at = part_data.get("uploaded_at")
            failed_at = part_data.get("failed_at")
            failure_reason = part_data.get("failure_reason")

            self._validate_part_values(
                part_number=part_number,
                size_bytes=size_bytes,
                status=status,
                etag=etag,
                uploaded_at=uploaded_at,
                failed_at=failed_at,
                failure_reason=failure_reason,
            )

            if part_number in seen_part_numbers:
                raise InvalidQueryError(
                    "Список частей содержит повторяющийся номер части.",
                    repository=self.repository_name,
                    operation="create_parts",
                    details={
                        "model": self.model_name,
                        "upload_session_id": str(upload_session_id),
                        "part_number": part_number,
                    },
                )

            seen_part_numbers.add(part_number)

            upload_parts.append(
                UploadPart(
                    upload_session_id=upload_session_id,
                    part_number=part_number,
                    size_bytes=size_bytes,
                    etag=self._normalize_etag(etag),
                    checksum=self._normalize_checksum(checksum),
                    status=status,
                    uploaded_at=uploaded_at,
                    failed_at=failed_at,
                    failure_reason=self._normalize_failure_reason(failure_reason),
                )
            )

        return await self.create_many(upload_parts, flush=flush)

    async def create_parts_by_sizes(
        self,
        upload_session_id: uuid.UUID,
        part_sizes: Sequence[int],
        *,
        first_part_number: int = 1,
        flush: bool = True,
        check_session_exists: bool = False,
    ) -> list[UploadPart]:
        """Создаёт части multipart-загрузки по списку размеров.

        Номера частей назначаются последовательно, начиная с ``first_part_number``.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_sizes: Последовательность размеров частей в байтах.
            first_part_number: Номер первой создаваемой части.
            flush: Выполнить ``flush`` после создания.
            check_session_exists: Проверять ли существование upload-сессии.

        Returns:
            Список созданных частей загрузки.

        Raises:
            InvalidQueryError: Если список размеров пустой, номер первой части
                или размер одной из частей некорректны.
            EntityNotFoundError: Если upload-сессия не найдена.
        """

        self._validate_part_number(first_part_number)

        if not part_sizes:
            raise InvalidQueryError(
                "Список размеров частей загрузки не может быть пустым.",
                repository=self.repository_name,
                operation="create_parts_by_sizes",
                details={"upload_session_id": str(upload_session_id)},
            )

        parts = [
            {
                "part_number": first_part_number + index,
                "size_bytes": size_bytes,
            }
            for index, size_bytes in enumerate(part_sizes)
        ]

        return await self.create_parts(
            upload_session_id,
            parts,
            flush=flush,
            check_session_exists=check_session_exists,
        )

    # ------------------------------------------------------------------
    # Изменение статуса частей
    # ------------------------------------------------------------------

    async def mark_part_uploaded(
        self,
        upload_session_id: uuid.UUID,
        part_number: int,
        *,
        etag: str,
        checksum: str | None = None,
        uploaded_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadPart:
        """Помечает часть как успешно загруженную.

        Метод получает часть с блокировкой строки ``FOR UPDATE``, устанавливает
        статус ``UPLOADED``, ETag, checksum и дату загрузки.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.
            etag: ETag, полученный после загрузки части.
            checksum: Контрольная сумма части.
            uploaded_at: Дата загрузки. Если не передана, используется текущее UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая часть загрузки.

        Raises:
            InvalidQueryError: Если номер части некорректен или ETag пустой.
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        normalized_etag = self._normalize_etag(etag)

        if not normalized_etag:
            raise InvalidQueryError(
                "ETag загруженной части не может быть пустым.",
                repository=self.repository_name,
                operation="mark_part_uploaded",
                details={
                    "upload_session_id": str(upload_session_id),
                    "part_number": part_number,
                },
            )

        upload_part = await self._get_required_for_update(
            upload_session_id=upload_session_id,
            part_number=part_number,
            operation="mark_part_uploaded",
        )

        upload_part.mark_uploaded(
            etag=normalized_etag,
            uploaded_at=uploaded_at or self._now(),
            checksum=self._normalize_checksum(checksum),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_part)

        return upload_part

    async def mark_part_failed(
        self,
        upload_session_id: uuid.UUID,
        part_number: int,
        *,
        reason: str | None = None,
        failed_at: datetime | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadPart:
        """Помечает часть как завершившуюся ошибкой.

        Метод получает часть с блокировкой строки ``FOR UPDATE``, устанавливает
        статус ``FAILED``, дату ошибки и причину ошибки.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.
            reason: Причина ошибки загрузки.
            failed_at: Дата ошибки. Если не передана, используется текущее UTC-время.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая часть загрузки.

        Raises:
            InvalidQueryError: Если номер части некорректен.
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        upload_part = await self._get_required_for_update(
            upload_session_id=upload_session_id,
            part_number=part_number,
            operation="mark_part_failed",
        )

        upload_part.mark_failed(
            reason=self._normalize_failure_reason(reason),
            failed_at=failed_at or self._now(),
        )

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_part)

        return upload_part

    async def reset_part(
        self,
        upload_session_id: uuid.UUID,
        part_number: int,
        *,
        clear_etag: bool = True,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadPart:
        """Сбрасывает часть загрузки в состояние ``PENDING``.

        Если ``clear_etag=True``, очищаются ETag, checksum, дата загрузки,
        дата ошибки и причина ошибки. Если ``clear_etag=False``, очищаются только
        поля ошибки и статус, а ETag/checksum/uploaded_at остаются без изменений.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.
            clear_etag: Очищать ли ETag, checksum и дату загрузки.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая часть загрузки.

        Raises:
            InvalidQueryError: Если номер части некорректен.
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        upload_part = await self._get_required_for_update(
            upload_session_id=upload_session_id,
            part_number=part_number,
            operation="reset_part",
        )

        if clear_etag:
            upload_part.reset()
        else:
            upload_part.status = UploadPartStatus.PENDING
            upload_part.failed_at = None
            upload_part.failure_reason = None

        if flush:
            await self.flush()

        if refresh:
            await self.refresh(upload_part)

        return upload_part

    async def update_part_status(
        self,
        upload_session_id: uuid.UUID,
        part_number: int,
        status: UploadPartStatus,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadPart:
        """Обновляет статус части загрузки.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.
            status: Новый статус части.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая часть загрузки.

        Raises:
            InvalidQueryError: Если номер части некорректен.
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        upload_part = await self._get_required_for_update(
            upload_session_id=upload_session_id,
            part_number=part_number,
            operation="update_part_status",
        )

        return await self.update(
            upload_part,
            {"status": status},
            flush=flush,
            refresh=refresh,
            allowed_fields={"status"},
        )

    async def update_part_etag(
        self,
        upload_session_id: uuid.UUID,
        part_number: int,
        *,
        etag: str | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadPart:
        """Обновляет ETag части загрузки.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.
            etag: Новый ETag части или ``None``.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая часть загрузки.

        Raises:
            InvalidQueryError: Если номер части некорректен.
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        upload_part = await self._get_required_for_update(
            upload_session_id=upload_session_id,
            part_number=part_number,
            operation="update_part_etag",
        )

        return await self.update(
            upload_part,
            {"etag": self._normalize_etag(etag)},
            flush=flush,
            refresh=refresh,
            allowed_fields={"etag"},
        )

    async def update_part_checksum(
        self,
        upload_session_id: uuid.UUID,
        part_number: int,
        *,
        checksum: str | None,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadPart:
        """Обновляет checksum части загрузки.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.
            checksum: Новая контрольная сумма части или ``None``.
            flush: Выполнить ``flush`` после обновления.
            refresh: Выполнить ``refresh`` после обновления.

        Returns:
            Обновлённая часть загрузки.

        Raises:
            InvalidQueryError: Если номер части или checksum некорректны.
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        upload_part = await self._get_required_for_update(
            upload_session_id=upload_session_id,
            part_number=part_number,
            operation="update_part_checksum",
        )

        return await self.update(
            upload_part,
            {"checksum": self._normalize_checksum(checksum)},
            flush=flush,
            refresh=refresh,
            allowed_fields={"checksum"},
        )

    # ------------------------------------------------------------------
    # Подсчёт и проверки готовности
    # ------------------------------------------------------------------

    async def count_uploaded_parts(
        self,
        upload_session_id: uuid.UUID,
    ) -> int:
        """Возвращает количество загруженных частей upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            Количество частей со статусом ``UPLOADED``.
        """

        return await self.count(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.status == UploadPartStatus.UPLOADED,
        )

    async def count_pending_parts(
        self,
        upload_session_id: uuid.UUID,
    ) -> int:
        """Возвращает количество ожидающих частей upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            Количество частей со статусом ``PENDING``.
        """

        return await self.count(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.status == UploadPartStatus.PENDING,
        )

    async def count_failed_parts(
        self,
        upload_session_id: uuid.UUID,
    ) -> int:
        """Возвращает количество ошибочных частей upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            Количество частей со статусом ``FAILED``.
        """

        return await self.count(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.status == UploadPartStatus.FAILED,
        )

    async def count_session_parts(
        self,
        upload_session_id: uuid.UUID,
    ) -> int:
        """Возвращает общее количество частей upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            Общее количество частей upload-сессии.
        """

        return await self.count(
            UploadPart.upload_session_id == upload_session_id,
        )

    async def count_parts_by_status(
        self,
        *,
        upload_session_id: uuid.UUID,
        status: UploadPartStatus,
    ) -> int:
        """Возвращает количество частей upload-сессии с указанным статусом.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            status: Статус частей для подсчёта.

        Returns:
            Количество частей с указанным статусом.
        """

        return await self.count(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.status == status,
        )

    async def sum_uploaded_bytes(
        self,
        upload_session_id: uuid.UUID,
    ) -> int:
        """Возвращает суммарный размер успешно загруженных частей.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            Суммарный размер частей со статусом ``UPLOADED`` в байтах.
        """

        statement = select(func.coalesce(func.sum(UploadPart.size_bytes), 0)).where(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.status == UploadPartStatus.UPLOADED,
        )

        value = await self.scalar_value(
            statement,
            operation="sum_uploaded_bytes",
        )

        return int(value or 0)

    async def check_all_parts_uploaded(
        self,
        upload_session_id: uuid.UUID,
        *,
        expected_parts_count: int | None = None,
        require_etags: bool = True,
    ) -> bool:
        """Проверяет, что все части upload-сессии успешно загружены.

        Если ``expected_parts_count`` передан, проверяется точное количество частей.
        Если ``expected_parts_count=None``, проверяется, что в сессии есть хотя бы
        одна часть и все существующие части имеют статус ``UPLOADED``.

        При ``require_etags=True`` дополнительно проверяется, что у всех загруженных
        частей есть ETag.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            expected_parts_count: Ожидаемое количество частей.
            require_etags: Требовать ли ETag у всех загруженных частей.

        Returns:
            ``True``, если все части готовы для завершения multipart upload,
            иначе ``False``.

        Raises:
            InvalidQueryError: Если ожидаемое количество частей некорректно.
        """

        if expected_parts_count is not None:
            self._validate_expected_parts_count(expected_parts_count)

        uploaded_count = await self.count_uploaded_parts(upload_session_id)
        total_count = await self.count_session_parts(upload_session_id)

        if expected_parts_count is not None:
            if total_count != expected_parts_count:
                return False

            if uploaded_count != expected_parts_count:
                return False
        else:
            if total_count <= 0 or uploaded_count != total_count:
                return False

        if require_etags and await self.has_missing_etags(upload_session_id):
            return False

        return True

    async def get_uploaded_parts_for_completion(
        self,
        upload_session_id: uuid.UUID,
    ) -> list[UploadPart]:
        """Возвращает загруженные части, пригодные для завершения multipart upload.

        В результат попадают только части со статусом ``UPLOADED`` и непустым ETag.
        Части сортируются по номеру по возрастанию, как требуется для
        ``CompleteMultipartUpload``.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            Список загруженных частей с ETag.
        """

        statement = (
            select(UploadPart)
            .where(
                UploadPart.upload_session_id == upload_session_id,
                UploadPart.status == UploadPartStatus.UPLOADED,
                UploadPart.etag.is_not(None),
            )
            .order_by(UploadPart.part_number.asc())
        )

        return await self.scalars_all(
            statement,
            operation="get_uploaded_parts_for_completion",
        )

    async def get_completion_info(
        self,
        upload_session_id: uuid.UUID,
    ) -> list[UploadedPartCompletionInfo]:
        """Возвращает минимальные данные загруженных частей для CompleteMultipartUpload.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            Список структур ``UploadedPartCompletionInfo``, отсортированный по номеру части.
        """

        parts = await self.get_uploaded_parts_for_completion(upload_session_id)

        result: list[UploadedPartCompletionInfo] = []

        for part in parts:
            if part.etag is None:
                continue

            result.append(
                {
                    "part_number": part.part_number,
                    "etag": part.etag,
                    "size_bytes": part.size_bytes,
                    "checksum": part.checksum,
                }
            )

        return result

    async def has_missing_etags(
        self,
        upload_session_id: uuid.UUID,
    ) -> bool:
        """Проверяет, есть ли загруженные части без ETag.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            ``True``, если есть части со статусом ``UPLOADED`` без ETag,
            иначе ``False``.
        """

        return await self.exists(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.status == UploadPartStatus.UPLOADED,
            UploadPart.etag.is_(None),
        )

    async def has_failed_parts(
        self,
        upload_session_id: uuid.UUID,
    ) -> bool:
        """Проверяет, есть ли ошибочные части upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            ``True``, если есть части со статусом ``FAILED``, иначе ``False``.
        """

        return await self.exists(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.status == UploadPartStatus.FAILED,
        )

    async def has_pending_parts(
        self,
        upload_session_id: uuid.UUID,
    ) -> bool:
        """Проверяет, есть ли ожидающие части upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            ``True``, если есть части со статусом ``PENDING``, иначе ``False``.
        """

        return await self.exists(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.status == UploadPartStatus.PENDING,
        )

    async def part_exists(
        self,
        *,
        upload_session_id: uuid.UUID,
        part_number: int,
    ) -> bool:
        """Проверяет существование части по upload-сессии и номеру.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.

        Returns:
            ``True``, если часть существует, иначе ``False``.

        Raises:
            InvalidQueryError: Если номер части некорректен.
        """

        self._validate_part_number(part_number)

        return await self.exists(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.part_number == part_number,
        )

    # ------------------------------------------------------------------
    # Удаление
    # ------------------------------------------------------------------

    async def delete_parts_by_session(
        self,
        upload_session_id: uuid.UUID,
        *,
        flush: bool = True,
    ) -> int:
        """Физически удаляет все части указанной upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            flush: Выполнить ``flush`` после удаления.

        Returns:
            Количество удалённых частей.
        """

        return await self.bulk_delete(
            UploadPart.upload_session_id == upload_session_id,
            flush=flush,
        )

    async def delete_part_by_session_and_number(
        self,
        upload_session_id: uuid.UUID,
        part_number: int,
        *,
        flush: bool = True,
        required: bool = True,
    ) -> bool:
        """Физически удаляет одну часть по upload-сессии и номеру части.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.
            flush: Выполнить ``flush`` после удаления.
            required: Выбрасывать ли ошибку, если часть не найдена.

        Returns:
            ``True``, если часть была удалена, иначе ``False``.

        Raises:
            InvalidQueryError: Если номер части некорректен.
            EntityNotFoundError: Если часть не найдена и ``required=True``.
        """

        upload_part = await self.get_by_session_and_part_number(
            upload_session_id=upload_session_id,
            part_number=part_number,
        )

        if upload_part is None:
            if required:
                raise EntityNotFoundError(
                    "UploadPart",
                    lookup={
                        "upload_session_id": str(upload_session_id),
                        "part_number": part_number,
                    },
                    repository=self.repository_name,
                )

            return False

        await self.delete(upload_part, flush=flush)

        return True

    async def delete_failed_parts(
        self,
        upload_session_id: uuid.UUID,
        *,
        flush: bool = True,
    ) -> int:
        """Физически удаляет ошибочные части указанной upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            flush: Выполнить ``flush`` после удаления.

        Returns:
            Количество удалённых частей со статусом ``FAILED``.
        """

        return await self.bulk_delete(
            UploadPart.upload_session_id == upload_session_id,
            UploadPart.status == UploadPartStatus.FAILED,
            flush=flush,
        )

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    async def _get_required_for_update(
        self,
        *,
        upload_session_id: uuid.UUID,
        part_number: int,
        operation: str,
    ) -> UploadPart:
        """Возвращает часть загрузки с блокировкой строки ``FOR UPDATE``.

        Используется для операций, изменяющих статус или метаданные части,
        чтобы снизить риск гонок при параллельных обновлениях.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            part_number: Номер части.
            operation: Название операции для сообщений об ошибках.

        Returns:
            Найденная часть загрузки.

        Raises:
            InvalidQueryError: Если номер части некорректен.
            EntityNotFoundError: Если часть загрузки не найдена.
        """

        self._validate_part_number(part_number)

        statement = (
            select(UploadPart)
            .where(
                UploadPart.upload_session_id == upload_session_id,
                UploadPart.part_number == part_number,
            )
            .with_for_update()
        )

        upload_part = await self.scalar_one_or_none(
            statement,
            operation=operation,
        )

        if upload_part is None:
            raise EntityNotFoundError(
                "UploadPart",
                lookup={
                    "upload_session_id": str(upload_session_id),
                    "part_number": part_number,
                },
                repository=self.repository_name,
            )

        return upload_part

    async def _ensure_upload_session_exists(
        self,
        upload_session_id: uuid.UUID,
    ) -> UploadSession:
        """Проверяет существование upload-сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.

        Returns:
            Найденная upload-сессия.

        Raises:
            EntityNotFoundError: Если upload-сессия не найдена.
            RepositoryError: Если произошла ошибка при обращении к базе данных.
        """

        try:
            upload_session = await self.session.get(UploadSession, upload_session_id)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="_ensure_upload_session_exists",
                reason=str(exc),
                details={"upload_session_id": str(upload_session_id)},
                cause=exc,
            ) from exc

        if upload_session is None:
            raise EntityNotFoundError(
                "UploadSession",
                entity_id=upload_session_id,
                repository=self.repository_name,
            )

        return upload_session

    def _validate_part_values(
        self,
        *,
        part_number: int,
        size_bytes: int,
        status: UploadPartStatus,
        etag: str | None,
        uploaded_at: datetime | None,
        failed_at: datetime | None,
        failure_reason: str | None,
    ) -> None:
        """Валидирует значения части multipart-загрузки.

        Проверяет номер части, размер, согласованность статуса с ETag,
        ``uploaded_at``, ``failed_at`` и ``failure_reason``.

        Args:
            part_number: Номер части.
            size_bytes: Размер части в байтах.
            status: Статус части.
            etag: ETag части.
            uploaded_at: Дата загрузки части.
            failed_at: Дата ошибки загрузки части.
            failure_reason: Причина ошибки загрузки части.

        Raises:
            InvalidQueryError: Если значения части некорректны или противоречат статусу.
        """

        self._validate_part_number(part_number)

        if not isinstance(size_bytes, int):
            raise InvalidQueryError(
                "Размер части загрузки должен быть целым числом.",
                repository=self.repository_name,
                operation="_validate_part_values",
                details={
                    "field": "size_bytes",
                    "value_type": type(size_bytes).__name__,
                },
            )

        if size_bytes <= 0:
            raise InvalidQueryError(
                "Размер части загрузки должен быть положительным.",
                repository=self.repository_name,
                operation="_validate_part_values",
                details={
                    "part_number": part_number,
                    "size_bytes": size_bytes,
                },
            )

        normalized_etag = self._normalize_etag(etag)

        if status == UploadPartStatus.UPLOADED and not normalized_etag:
            raise InvalidQueryError(
                "Загруженная часть должна иметь ETag.",
                repository=self.repository_name,
                operation="_validate_part_values",
                details={
                    "part_number": part_number,
                    "status": status.value,
                },
            )

        if status != UploadPartStatus.UPLOADED and uploaded_at is not None:
            raise InvalidQueryError(
                "Время uploaded_at допустимо только для загруженной части.",
                repository=self.repository_name,
                operation="_validate_part_values",
                details={
                    "part_number": part_number,
                    "status": status.value,
                    "uploaded_at": uploaded_at.isoformat(),
                },
            )

        if status == UploadPartStatus.UPLOADED and failed_at is not None:
            raise InvalidQueryError(
                "Загруженная часть не может иметь failed_at.",
                repository=self.repository_name,
                operation="_validate_part_values",
                details={
                    "part_number": part_number,
                    "status": status.value,
                    "failed_at": failed_at.isoformat(),
                },
            )

        if status != UploadPartStatus.FAILED and failed_at is not None:
            raise InvalidQueryError(
                "Время failed_at допустимо только для ошибочной части.",
                repository=self.repository_name,
                operation="_validate_part_values",
                details={
                    "part_number": part_number,
                    "status": status.value,
                    "failed_at": failed_at.isoformat(),
                },
            )

        if status != UploadPartStatus.FAILED and failure_reason:
            raise InvalidQueryError(
                "failure_reason допустим только для ошибочной части.",
                repository=self.repository_name,
                operation="_validate_part_values",
                details={
                    "part_number": part_number,
                    "status": status.value,
                },
            )

    def _validate_part_number(
        self,
        part_number: int,
    ) -> None:
        """Проверяет номер части multipart-загрузки.

        Номер части должен быть положительным целым числом.

        Args:
            part_number: Номер части.

        Raises:
            InvalidQueryError: Если номер части не является ``int`` или меньше либо равен нулю.
        """

        if not isinstance(part_number, int):
            raise InvalidQueryError(
                "Номер части загрузки должен быть целым числом.",
                repository=self.repository_name,
                operation="_validate_part_number",
                details={
                    "field": "part_number",
                    "value_type": type(part_number).__name__,
                },
            )

        if part_number <= 0:
            raise InvalidQueryError(
                "Номер части загрузки должен быть положительным.",
                repository=self.repository_name,
                operation="_validate_part_number",
                details={"part_number": part_number},
            )

    def _validate_expected_parts_count(
        self,
        expected_parts_count: int,
    ) -> None:
        """Проверяет ожидаемое количество частей.

        Значение должно быть положительным целым числом.

        Args:
            expected_parts_count: Ожидаемое количество частей.

        Raises:
            InvalidQueryError: Если значение не является ``int`` или меньше либо равно нулю.
        """

        if not isinstance(expected_parts_count, int):
            raise InvalidQueryError(
                "Ожидаемое количество частей должно быть целым числом.",
                repository=self.repository_name,
                operation="_validate_expected_parts_count",
                details={
                    "field": "expected_parts_count",
                    "value_type": type(expected_parts_count).__name__,
                },
            )

        if expected_parts_count <= 0:
            raise InvalidQueryError(
                "Ожидаемое количество частей должно быть положительным.",
                repository=self.repository_name,
                operation="_validate_expected_parts_count",
                details={"expected_parts_count": expected_parts_count},
            )

    def _coerce_status(
        self,
        status: UploadPartStatus | str,
    ) -> UploadPartStatus:
        """Приводит значение статуса к ``UploadPartStatus``.

        Args:
            status: Статус как ``UploadPartStatus`` или строковое значение enum.

        Returns:
            Значение ``UploadPartStatus``.

        Raises:
            InvalidQueryError: Если строковое значение не соответствует допустимому статусу.
        """

        if isinstance(status, UploadPartStatus):
            return status

        try:
            return UploadPartStatus(status)

        except ValueError as exc:
            raise InvalidQueryError(
                "Некорректный статус части загрузки.",
                repository=self.repository_name,
                operation="_coerce_status",
                details={
                    "status": status,
                    "allowed_statuses": [item.value for item in UploadPartStatus],
                },
            ) from exc

    def _normalize_etag(
        self,
        etag: str | None,
    ) -> str | None:
        """Нормализует ETag части.

        Удаляет пробелы по краям строки. Пустая строка возвращается как ``None``.

        Args:
            etag: ETag части.

        Returns:
            Нормализованный ETag или ``None``.
        """

        if etag is None:
            return None

        normalized = etag.strip()

        return normalized or None

    def _normalize_checksum(
        self,
        checksum: str | None,
    ) -> str | None:
        """Нормализует checksum части.

        Значение приводится к нижнему регистру. Пустая строка возвращается как ``None``.

        Args:
            checksum: Контрольная сумма части.

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
                "Checksum части не должен превышать 128 символов.",
                repository=self.repository_name,
                operation="_normalize_checksum",
                details={
                    "field": "checksum",
                    "length": len(normalized),
                    "max_length": 128,
                },
            )

        return normalized

    def _normalize_failure_reason(
        self,
        failure_reason: str | None,
    ) -> str | None:
        """Нормализует причину ошибки загрузки части.

        Удаляет пробелы по краям строки. Пустая строка возвращается как ``None``.

        Args:
            failure_reason: Причина ошибки загрузки.

        Returns:
            Нормализованная причина ошибки или ``None``.
        """

        if failure_reason is None:
            return None

        normalized = failure_reason.strip()

        return normalized or None

    @staticmethod
    def _now() -> datetime:
        """Возвращает текущее время в UTC.

        Returns:
            Текущая дата и время с timezone UTC.
        """

        return datetime.now(UTC)

    # ------------------------------------------------------------------
    # Переопределённые методы
    # ------------------------------------------------------------------

    async def create(
        self,
        entity: UploadPart,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> UploadPart:
        """Добавляет часть загрузки в текущую сессию.

        Переопределяет базовый метод для более понятной ошибки при конфликте
        уникальности по паре ``upload_session_id + part_number``.

        Args:
            entity: ORM-объект части загрузки.
            flush: Выполнить ``flush`` после добавления.
            refresh: Выполнить ``refresh`` после добавления.

        Returns:
            Созданная часть загрузки.

        Raises:
            DuplicateEntityError: Если часть с таким номером уже существует
                в указанной upload-сессии.
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
                "UploadPart",
                field="upload_session_id/part_number",
                value=f"{entity.upload_session_id}/{entity.part_number}",
                repository=self.repository_name,
                message="Часть с таким номером уже существует в указанной upload-сессии.",
            ) from exc

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_part",
            ) from exc

    async def _execute_upload_part_statement(
        self,
        statement: Select[tuple[UploadPart]],
        *,
        operation: str,
    ) -> list[UploadPart]:
        """Выполняет SELECT-запрос для модели ``UploadPart``.

        Args:
            statement: SQLAlchemy SELECT-запрос.
            operation: Название операции для сообщений об ошибках.

        Returns:
            Список найденных частей загрузки.

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
