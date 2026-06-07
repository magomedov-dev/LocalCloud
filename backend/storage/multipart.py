from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, BinaryIO

from core.constants import StorageConstants
from storage.buckets import StorageBucketNameValidator
from storage.client import StorageClient
from storage.exceptions import (
    StorageConnectionError,
    StorageError,
    StorageMultipartUploadError,
    StorageMultipartUploadNotFoundError,
)
from storage.keys import normalize_object_key
from storage.metadata import normalize_metadata
from storage.objects import StorageObjectManager
from storage.types import (
    StorageMultipartUpload,
    StorageObjectInfo,
    StorageObjectMetadata,
    StorageUploadPart,
)


class StorageMultipartManager:
    """Менеджер multipart-загрузок MinIO/S3.

    Все операции выполняются через ``StorageClient.execute``, чтобы синхронный
    MinIO SDK не блокировал event loop.

    Важно:
        Официальный MinIO Python SDK не предоставляет публичных высокоуровневых
        async-методов multipart upload. Поэтому этот менеджер использует
        низкоуровневые методы клиента MinIO, инкапсулируя их в одном месте.

    Args:
        client: Клиент объектного хранилища.
        bucket_name_validator: Валидатор имён bucket-ов.
        object_manager: Менеджер операций с объектами.
    """

    def __init__(
        self,
        *,
        client: StorageClient,
        bucket_name_validator: StorageBucketNameValidator,
        object_manager: StorageObjectManager,
    ) -> None:
        """Инициализирует менеджер multipart-загрузок.

        Args:
            client: Клиент объектного хранилища.
            bucket_name_validator: Валидатор имён bucket-ов.
            object_manager: Менеджер операций с объектами.
        """

        self.client = client
        self.bucket_name_validator = bucket_name_validator
        self.object_manager = object_manager

    def _validate_bucket_name(self, bucket: str) -> str:
        """Проверяет и нормализует имя bucket.

        Args:
            bucket: Исходное имя bucket.

        Returns:
            Нормализованное имя bucket.

        Raises:
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        return self.bucket_name_validator.validate(bucket)

    async def create_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        content_type: str | None = None,
        metadata: dict[str, Any] | StorageObjectMetadata | None = None,
    ) -> StorageMultipartUpload:
        """Инициирует multipart-загрузку объекта.

        Возвращает ``upload_id``, который должен быть сохранён сервисным слоем
        или репозиторием ``upload_sessions`` вне этого модуля.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            content_type: MIME-тип итогового объекта.
            metadata: Пользовательские metadata итогового объекта.

        Returns:
            DTO с параметрами созданной multipart-загрузки.

        Raises:
            StorageMultipartUploadError: Если multipart-загрузку не удалось
                создать или SDK вернул некорректный upload ID.
            StorageError: Если произошла ошибка хранилища.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        normalized_metadata = normalize_metadata(metadata)

        headers = self._build_headers(
            content_type=content_type,
            metadata=normalized_metadata,
        )

        try:
            upload_id = await self.client.execute(
                self.client.get_raw_client()._create_multipart_upload,
                normalized_bucket,
                normalized_object_key,
                headers,
                operation_name="create_multipart_upload",
            )
        except StorageError as exc:
            raise self._multipart_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                upload_id=None,
                operation="create_multipart_upload",
            ) from exc

        if not isinstance(upload_id, str) or not upload_id.strip():
            raise StorageMultipartUploadError(
                "MinIO/S3 не вернул корректный идентификатор multipart-загрузки.",
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                details={
                    "operation": "create_multipart_upload",
                    "upload_id": upload_id,
                },
            )

        return StorageMultipartUpload(
            bucket=normalized_bucket,
            object_key=normalized_object_key,
            upload_id=upload_id.strip(),
            metadata=normalized_metadata,
            created_at=datetime.now(UTC),
        )

    async def upload_part(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        part_number: int,
        data: BinaryIO | bytes | bytearray,
        size_bytes: int,
    ) -> StorageUploadPart:
        """Загружает одну часть multipart-загрузки.

        Метод не сохраняет информацию о части в PostgreSQL. Возвращённые
        ``part_number`` и ``etag`` должны быть сохранены вызывающим кодом.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart-загрузки.
            part_number: Номер загружаемой части.
            data: Данные части.
            size_bytes: Размер части в байтах.

        Returns:
            DTO с информацией о загруженной части.

        Raises:
            StorageMultipartUploadError: Если параметры некорректны, часть не
                удалось загрузить или SDK не вернул ETag.
            StorageMultipartUploadNotFoundError: Если multipart-загрузка не
                найдена.
            StorageError: Если произошла ошибка хранилища.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        normalized_upload_id = self.validate_upload_id(upload_id)
        normalized_part_number = self.validate_part_number(part_number)
        normalized_size_bytes = self.validate_part_size(size_bytes)

        part_payload = self._read_part_payload(
            data=data,
            size_bytes=normalized_size_bytes,
            bucket=normalized_bucket,
            object_key=normalized_object_key,
            upload_id=normalized_upload_id,
            part_number=normalized_part_number,
        )

        try:
            result = await self.client.execute(
                self.client.get_raw_client()._upload_part,
                normalized_bucket,
                normalized_object_key,
                part_payload,
                {},
                normalized_upload_id,
                normalized_part_number,
                operation_name="upload_part",
            )
        except StorageError as exc:
            raise self._multipart_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                upload_id=normalized_upload_id,
                part_number=normalized_part_number,
                operation="upload_part",
            ) from exc

        etag = getattr(result, "etag", None)

        if not isinstance(etag, str) or not etag.strip():
            etag = str(result).strip() if result is not None else ""

        etag = etag.strip().strip('"')

        if not etag:
            raise StorageMultipartUploadError(
                "MinIO/S3 не вернул ETag загруженной части.",
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                upload_id=normalized_upload_id,
                part_number=normalized_part_number,
                details={
                    "operation": "upload_part",
                },
            )

        return StorageUploadPart(
            part_number=normalized_part_number,
            etag=etag,
            size_bytes=normalized_size_bytes,
            uploaded_at=datetime.now(UTC),
        )

    async def list_uploaded_parts(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        max_parts: int = 1_000,
        part_number_marker: int = 0,
    ) -> list[StorageUploadPart]:
        """Возвращает список уже загруженных частей multipart-загрузки.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart-загрузки.
            max_parts: Максимальное количество частей в ответе.
            part_number_marker: Marker номера части для пагинации.

        Returns:
            Отсортированный по номеру части список загруженных частей.

        Raises:
            StorageMultipartUploadError: Если параметры некорректны или
                получение списка частей не удалось.
            StorageMultipartUploadNotFoundError: Если multipart-загрузка не
                найдена.
            StorageError: Если произошла ошибка хранилища.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        normalized_upload_id = self.validate_upload_id(upload_id)
        normalized_max_parts = self.validate_max_parts(max_parts)
        normalized_marker = self.validate_part_number_marker(
            part_number_marker,
        )

        try:
            result = await self.client.execute(
                self.client.get_raw_client()._list_parts,
                normalized_bucket,
                normalized_object_key,
                normalized_upload_id,
                normalized_max_parts,
                normalized_marker,
                operation_name="list_uploaded_parts",
            )
        except StorageError as exc:
            raise self._multipart_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                upload_id=normalized_upload_id,
                operation="list_uploaded_parts",
            ) from exc

        raw_parts = self._extract_parts(result)
        parts: list[StorageUploadPart] = []

        for raw_part in raw_parts:
            part_number = getattr(raw_part, "part_number", None)
            etag = getattr(raw_part, "etag", None)
            size = getattr(raw_part, "size", None)
            last_modified = getattr(raw_part, "last_modified", None)

            if part_number is None or etag is None:
                continue

            parts.append(
                StorageUploadPart(
                    part_number=self.validate_part_number(int(part_number)),
                    etag=str(etag).strip().strip('"'),
                    size_bytes=int(size) if size is not None else None,
                    uploaded_at=last_modified
                    if isinstance(last_modified, datetime)
                    else None,
                )
            )

        return sorted(parts, key=lambda part: part.part_number)

    async def complete_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        parts: Iterable[StorageUploadPart | tuple[int, str] | dict[str, Any]],
    ) -> StorageObjectInfo:
        """Завершает multipart-загрузку.

        ``parts`` должен содержать ``part_number`` и ``etag`` для каждой
        загруженной части. После завершения метод возвращает
        ``StorageObjectInfo`` через ``stat_object``.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart-загрузки.
            parts: Части для завершения загрузки.

        Returns:
            Информация об итоговом объекте.

        Raises:
            StorageMultipartUploadError: Если список частей пустой,
                некорректный или завершение загрузки не удалось.
            StorageMultipartUploadNotFoundError: Если multipart-загрузка не
                найдена.
            StorageError: Если произошла ошибка хранилища.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        normalized_upload_id = self.validate_upload_id(upload_id)
        completion_parts = self.build_completion_parts(parts)

        if not completion_parts:
            raise StorageMultipartUploadError(
                "Нельзя завершить multipart-загрузку без частей.",
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                upload_id=normalized_upload_id,
                details={
                    "operation": "complete_multipart_upload",
                },
            )

        try:
            await self.client.execute(
                self.client.get_raw_client()._complete_multipart_upload,
                normalized_bucket,
                normalized_object_key,
                normalized_upload_id,
                completion_parts,
                operation_name="complete_multipart_upload",
            )
        except StorageError as exc:
            raise self._multipart_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                upload_id=normalized_upload_id,
                operation="complete_multipart_upload",
            ) from exc

        return await self._stat_completed_object(
            bucket=normalized_bucket,
            object_key=normalized_object_key,
        )

    async def abort_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        missing_ok: bool = False,
    ) -> bool:
        """Отменяет multipart-загрузку.

        Метод не изменяет состояние ``upload_sessions`` в PostgreSQL.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart-загрузки.
            missing_ok: Не считать ошибкой отсутствие multipart-загрузки.

        Returns:
            ``True``, если загрузка была отменена. ``False``, если загрузка
            отсутствует и ``missing_ok`` равен ``True``.

        Raises:
            StorageMultipartUploadError: Если отмена загрузки не удалась.
            StorageMultipartUploadNotFoundError: Если multipart-загрузка не
                найдена и ``missing_ok`` равен ``False``.
            StorageError: Если произошла ошибка хранилища.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        normalized_upload_id = self.validate_upload_id(upload_id)

        try:
            await self.client.execute(
                self.client.get_raw_client()._abort_multipart_upload,
                normalized_bucket,
                normalized_object_key,
                normalized_upload_id,
                operation_name="abort_multipart_upload",
            )
        except StorageMultipartUploadNotFoundError:
            if missing_ok:
                return False
            raise
        except StorageError as exc:
            converted = self._multipart_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                upload_id=normalized_upload_id,
                operation="abort_multipart_upload",
            )

            if missing_ok and isinstance(
                converted,
                StorageMultipartUploadNotFoundError,
            ):
                return False

            raise converted from exc

        return True

    @staticmethod
    def validate_upload_id(upload_id: str) -> str:
        """Проверяет идентификатор multipart-загрузки.

        Args:
            upload_id: Исходный идентификатор multipart-загрузки.

        Returns:
            Нормализованный идентификатор multipart-загрузки.

        Raises:
            StorageMultipartUploadError: Если upload ID некорректен.
        """

        if not isinstance(upload_id, str):
            raise StorageMultipartUploadError(
                "Идентификатор multipart-загрузки должен быть строкой.",
                upload_id=None,
                details={
                    "operation": "validate_upload_id",
                    "value_type": type(upload_id).__name__,
                },
            )

        normalized_upload_id = upload_id.strip()

        if not normalized_upload_id:
            raise StorageMultipartUploadError(
                "Идентификатор multipart-загрузки не может быть пустым.",
                upload_id=upload_id,
                details={
                    "operation": "validate_upload_id",
                },
            )

        return normalized_upload_id

    def validate_part_number(self, part_number: int) -> int:
        """Проверяет номер части multipart-загрузки.

        Args:
            part_number: Номер части multipart-загрузки.

        Returns:
            Проверенный номер части.

        Raises:
            StorageMultipartUploadError: Если номер части некорректен.
        """

        if not isinstance(part_number, int) or isinstance(part_number, bool):
            raise StorageMultipartUploadError(
                "Номер части multipart-загрузки должен быть целым числом.",
                part_number=None,
                details={
                    "operation": "validate_part_number",
                    "value": part_number,
                    "value_type": type(part_number).__name__,
                },
            )

        if part_number < StorageConstants.S3_MULTIPART_MIN_PART_NUMBER:
            raise StorageMultipartUploadError(
                "Номер части multipart-загрузки должен быть положительным.",
                part_number=part_number,
                details={
                    "operation": "validate_part_number",
                    "min_part_number": StorageConstants.S3_MULTIPART_MIN_PART_NUMBER,
                },
            )

        if part_number > StorageConstants.S3_MULTIPART_MAX_PART_NUMBER:
            raise StorageMultipartUploadError(
                "Номер части multipart-загрузки превышает максимально допустимое значение.",
                part_number=part_number,
                details={
                    "operation": "validate_part_number",
                    "max_part_number": StorageConstants.S3_MULTIPART_MAX_PART_NUMBER,
                },
            )

        return part_number

    def validate_part_number_marker(self, part_number_marker: int) -> int:
        """Проверяет marker для list parts.

        Для S3 marker может быть ``0``, что означает начало списка.

        Args:
            part_number_marker: Marker номера части.

        Returns:
            Проверенный marker номера части.

        Raises:
            StorageMultipartUploadError: Если marker некорректен.
        """

        if not isinstance(part_number_marker, int) or isinstance(
            part_number_marker,
            bool,
        ):
            raise StorageMultipartUploadError(
                "Маркер номера части должен быть целым числом.",
                details={
                    "operation": "validate_part_number_marker",
                    "value": part_number_marker,
                    "value_type": type(part_number_marker).__name__,
                },
            )

        if part_number_marker < 0:
            raise StorageMultipartUploadError(
                "Маркер номера части не может быть отрицательным.",
                details={
                    "operation": "validate_part_number_marker",
                    "part_number_marker": part_number_marker,
                },
            )

        if part_number_marker > StorageConstants.S3_MULTIPART_MAX_PART_NUMBER:
            raise StorageMultipartUploadError(
                "Маркер номера части превышает максимально допустимое значение.",
                details={
                    "operation": "validate_part_number_marker",
                    "part_number_marker": part_number_marker,
                    "max_part_number": StorageConstants.S3_MULTIPART_MAX_PART_NUMBER,
                },
            )

        return part_number_marker

    def validate_max_parts(self, max_parts: int) -> int:
        """Проверяет ``max_parts`` для list parts.

        Args:
            max_parts: Максимальное количество частей в ответе.

        Returns:
            Проверенное значение ``max_parts``.

        Raises:
            StorageMultipartUploadError: Если ``max_parts`` некорректен.
        """

        if not isinstance(max_parts, int) or isinstance(max_parts, bool):
            raise StorageMultipartUploadError(
                "Максимальное количество частей должно быть целым числом.",
                details={
                    "operation": "validate_max_parts",
                    "value": max_parts,
                    "value_type": type(max_parts).__name__,
                },
            )

        if max_parts <= 0:
            raise StorageMultipartUploadError(
                "Максимальное количество частей должно быть положительным.",
                details={
                    "operation": "validate_max_parts",
                    "max_parts": max_parts,
                },
            )

        if max_parts > StorageConstants.S3_MULTIPART_MAX_PART_NUMBER:
            raise StorageMultipartUploadError(
                "Максимальное количество частей превышает допустимое значение.",
                details={
                    "operation": "validate_max_parts",
                    "max_parts": max_parts,
                    "max_allowed": StorageConstants.S3_MULTIPART_MAX_PART_NUMBER,
                },
            )

        return max_parts

    def validate_part_size(
        self,
        size_bytes: int,
        *,
        is_last_part: bool = False,
        enforce_s3_min_size: bool = False,
    ) -> int:
        """Проверяет размер части multipart-загрузки.

        По умолчанию проверяется только ``size_bytes > 0``. При необходимости
        можно включить ``enforce_s3_min_size=True`` для проверки минимального
        S3-размера не последней части — 5 MiB.

        Args:
            size_bytes: Размер части в байтах.
            is_last_part: Является ли часть последней.
            enforce_s3_min_size: Проверять ли минимальный размер S3 для
                непоследней части.

        Returns:
            Проверенный размер части.

        Raises:
            StorageMultipartUploadError: Если размер части некорректен.
        """

        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
            raise StorageMultipartUploadError(
                "Размер части multipart-загрузки должен быть целым числом.",
                details={
                    "operation": "validate_part_size",
                    "value": size_bytes,
                    "value_type": type(size_bytes).__name__,
                },
            )

        if size_bytes < StorageConstants.S3_MULTIPART_MIN_PART_SIZE_BYTES:
            raise StorageMultipartUploadError(
                "Размер части multipart-загрузки должен быть положительным.",
                details={
                    "operation": "validate_part_size",
                    "size_bytes": size_bytes,
                    "min_size_bytes": StorageConstants.S3_MULTIPART_MIN_PART_SIZE_BYTES,
                },
            )

        if (
            enforce_s3_min_size
            and not is_last_part
            and size_bytes < StorageConstants.S3_MULTIPART_MIN_NON_LAST_PART_SIZE_BYTES
        ):
            raise StorageMultipartUploadError(
                "Размер не последней части multipart-загрузки меньше минимального S3-размера.",
                details={
                    "operation": "validate_part_size",
                    "size_bytes": size_bytes,
                    "min_non_last_part_size_bytes": StorageConstants.S3_MULTIPART_MIN_NON_LAST_PART_SIZE_BYTES,
                },
            )

        return size_bytes

    def build_completion_parts(
        self,
        parts: Iterable[StorageUploadPart | tuple[int, str] | dict[str, Any]],
    ) -> list[_CompletionPart]:
        """Подготавливает список частей для завершения multipart-загрузки.

        Поддерживаемые элементы:

        * ``StorageUploadPart``;
        * ``tuple(part_number, etag)``;
        * ``dict`` с ключами ``part_number`` и ``etag``.

        Args:
            parts: Части multipart-загрузки.

        Returns:
            Список объектов, совместимых с ожиданиями MinIO SDK.

        Raises:
            StorageMultipartUploadError: Если часть имеет неподдерживаемый
                формат, некорректный номер, пустой ETag или дублирующийся номер
                части.
        """

        normalized_parts: list[tuple[int, str]] = []

        for part in parts:
            part_number, etag = self._extract_completion_part(part)
            normalized_part_number = self.validate_part_number(part_number)
            normalized_etag = self._validate_etag(
                etag,
                part_number=normalized_part_number,
            )

            normalized_parts.append((normalized_part_number, normalized_etag))

        normalized_parts.sort(key=lambda item: item[0])
        self._validate_unique_part_numbers(normalized_parts)

        return [
            _CompletionPart(
                part_number=part_number,
                etag=etag,
            )
            for part_number, etag in normalized_parts
        ]

    async def _stat_completed_object(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> StorageObjectInfo:
        """Возвращает информацию о завершённом multipart-объекте.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.

        Returns:
            Информация об объекте.
        """

        return await self.object_manager.stat_object(
            bucket=bucket,
            object_key=object_key,
        )

    @staticmethod
    def _build_headers(
        *,
        content_type: str | None,
        metadata: StorageObjectMetadata,
    ) -> dict[str, str]:
        """Формирует headers для инициации multipart-загрузки.

        Args:
            content_type: MIME-тип итогового объекта.
            metadata: Пользовательские metadata итогового объекта.

        Returns:
            Headers для MinIO SDK.
        """

        headers: dict[str, str] = {}

        if content_type is not None and content_type.strip():
            headers["Content-Type"] = content_type.strip()

        headers.update(metadata.to_headers())

        return headers

    @staticmethod
    def _read_part_payload(
        *,
        data: BinaryIO | bytes | bytearray,
        size_bytes: int,
        bucket: str,
        object_key: str,
        upload_id: str,
        part_number: int,
    ) -> bytes:
        """Читает payload части multipart-загрузки.

        Args:
            data: Данные части.
            size_bytes: Ожидаемый размер части в байтах.
            bucket: Имя bucket.
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart-загрузки.
            part_number: Номер части.

        Returns:
            Payload части в ``bytes``.

        Raises:
            StorageMultipartUploadError: Если данные имеют некорректный тип или
                размер прочитанной части не совпадает с ожидаемым.
        """

        if isinstance(data, bytes):
            payload = data
        elif isinstance(data, bytearray):
            payload = bytes(data)
        else:
            if not hasattr(data, "read"):
                raise StorageMultipartUploadError(
                    "Данные части multipart-загрузки должны быть bytes, bytearray или file-like объектом.",
                    bucket=bucket,
                    object_key=object_key,
                    upload_id=upload_id,
                    part_number=part_number,
                    details={
                        "operation": "upload_part",
                        "value_type": type(data).__name__,
                    },
                )

            payload = data.read(size_bytes)

        if not isinstance(payload, bytes):
            raise StorageMultipartUploadError(
                "Поток части multipart-загрузки должен возвращать bytes.",
                bucket=bucket,
                object_key=object_key,
                upload_id=upload_id,
                part_number=part_number,
                details={
                    "operation": "upload_part",
                    "chunk_type": type(payload).__name__,
                },
            )

        if len(payload) != size_bytes:
            raise StorageMultipartUploadError(
                "Размер прочитанной части multipart-загрузки не совпадает с ожидаемым.",
                bucket=bucket,
                object_key=object_key,
                upload_id=upload_id,
                part_number=part_number,
                details={
                    "operation": "upload_part",
                    "expected_size_bytes": size_bytes,
                    "actual_size_bytes": len(payload),
                },
            )

        return payload

    @staticmethod
    def _validate_etag(etag: str, *, part_number: int) -> str:
        """Проверяет ETag части multipart-загрузки.

        Args:
            etag: Исходный ETag.
            part_number: Номер части для диагностических details.

        Returns:
            Нормализованный ETag.

        Raises:
            StorageMultipartUploadError: Если ETag некорректен.
        """

        if not isinstance(etag, str):
            raise StorageMultipartUploadError(
                "ETag части multipart-загрузки должен быть строкой.",
                part_number=part_number,
                details={
                    "operation": "validate_etag",
                    "value_type": type(etag).__name__,
                },
            )

        normalized_etag = etag.strip().strip('"')

        if not normalized_etag:
            raise StorageMultipartUploadError(
                "ETag части multipart-загрузки не может быть пустым.",
                part_number=part_number,
                details={
                    "operation": "validate_etag",
                },
            )

        return normalized_etag

    @staticmethod
    def _extract_completion_part(
        part: StorageUploadPart | tuple[int, str] | dict[str, Any],
    ) -> tuple[int, str]:
        """Извлекает ``part_number`` и ``etag`` из элемента ``parts``.

        Args:
            part: Элемент списка частей.

        Returns:
            Кортеж ``(part_number, etag)``.

        Raises:
            StorageMultipartUploadError: Если формат части не поддерживается.
        """

        if isinstance(part, StorageUploadPart):
            return part.part_number, part.etag

        if isinstance(part, tuple):
            if len(part) != 2:
                raise StorageMultipartUploadError(
                    "Tuple части multipart-загрузки должен содержать part_number и etag.",
                    details={
                        "operation": "build_completion_parts",
                        "value": part,
                    },
                )

            part_number, etag = part
            return part_number, etag

        if isinstance(part, dict):
            if "part_number" not in part or "etag" not in part:
                raise StorageMultipartUploadError(
                    "Dict части multipart-загрузки должен содержать part_number и etag.",
                    details={
                        "operation": "build_completion_parts",
                        "keys": list(part.keys()),
                    },
                )

            return part["part_number"], part["etag"]

        raise StorageMultipartUploadError(
            "Неподдерживаемый формат части multipart-загрузки.",
            details={
                "operation": "build_completion_parts",
                "value_type": type(part).__name__,
            },
        )

    @staticmethod
    def _validate_unique_part_numbers(
        parts: list[tuple[int, str]],
    ) -> None:
        """Проверяет уникальность номеров частей.

        Args:
            parts: Список нормализованных частей.

        Returns:
            ``None``.

        Raises:
            StorageMultipartUploadError: Если найден дублирующийся номер части.
        """

        seen_part_numbers: set[int] = set()

        for part_number, _ in parts:
            if part_number in seen_part_numbers:
                raise StorageMultipartUploadError(
                    "Список частей multipart-загрузки содержит дублирующиеся номера.",
                    part_number=part_number,
                    details={
                        "operation": "build_completion_parts",
                    },
                )

            seen_part_numbers.add(part_number)

    @staticmethod
    def _extract_parts(result: Any) -> list[Any]:
        """Извлекает список частей из результата ``_list_parts``.

        Метод учитывает различия в результатах разных версий MinIO SDK.

        Args:
            result: Результат вызова ``_list_parts``.

        Returns:
            Список raw-объектов частей.
        """

        if result is None:
            return []

        if isinstance(result, list):
            return result

        parts = getattr(result, "parts", None)
        if parts is not None:
            return list(parts)

        if isinstance(result, tuple):
            for item in result:
                item_parts = getattr(item, "parts", None)

                if item_parts is not None:
                    return list(item_parts)

                if isinstance(item, list):
                    return item

        return []

    @staticmethod
    def _multipart_error(
        exc: StorageError,
        *,
        bucket: str,
        object_key: str,
        upload_id: str | None,
        operation: str,
        part_number: int | None = None,
    ) -> StorageError:
        """Преобразует ошибку хранилища в multipart-specific ошибку.

        Args:
            exc: Исходная ошибка хранилища.
            bucket: Имя bucket.
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart-загрузки.
            operation: Название выполняемой операции.
            part_number: Номер части, если ошибка связана с конкретной частью.

        Returns:
            Уточнённая ошибка хранилища.
        """

        if isinstance(exc, StorageConnectionError):
            return exc

        if isinstance(
            exc,
            (
                StorageMultipartUploadError,
                StorageMultipartUploadNotFoundError,
            ),
        ):
            return exc

        details = dict(exc.details)
        details.setdefault("reason", exc.message)
        details["operation"] = operation

        code = details.get("code")
        status_code = details.get("status_code")

        if (
            code
            in {
                "NoSuchUpload",
                "NoSuchMultipartUpload",
                "InvalidUploadId",
                "UploadNotFound",
            }
            or status_code == 404
        ):
            if upload_id is None:
                return StorageMultipartUploadError(
                    "Multipart upload-сессия не найдена.",
                    bucket=bucket,
                    object_key=object_key,
                    upload_id=upload_id,
                    part_number=part_number,
                    operation=operation,
                    details=details,
                    cause=exc,
                )

            return StorageMultipartUploadNotFoundError(
                bucket=bucket,
                object_key=object_key,
                upload_id=upload_id,
                details={
                    **details,
                    "operation": operation,
                    "part_number": part_number,
                },
                cause=exc,
            )

        return StorageMultipartUploadError(
            "Multipart-операция объектного хранилища не удалась.",
            bucket=bucket,
            object_key=object_key,
            upload_id=upload_id,
            part_number=part_number,
            operation=operation,
            details=details,
            cause=exc,
        )


class _CompletionPart:
    """Минимальная структура части для complete multipart upload.

    MinIO SDK ожидает объекты с атрибутами ``part_number`` и ``etag``.

    Args:
        part_number: Номер части.
        etag: ETag части.
    """

    def __init__(self, *, part_number: int, etag: str) -> None:
        """Инициализирует часть для complete multipart upload.

        Args:
            part_number: Номер части.
            etag: ETag части.
        """

        self.part_number = part_number
        self.etag = etag
