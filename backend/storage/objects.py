from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, BinaryIO

from minio.commonconfig import ComposeSource, CopySource
from minio.deleteobjects import DeleteObject

from core.constants import StorageConstants
from storage.buckets import StorageBucketNameValidator
from storage.client import StorageClient
from storage.exceptions import (
    StorageConnectionError,
    StorageCopyError,
    StorageDeleteError,
    StorageDownloadError,
    StorageError,
    StorageObjectError,
    StorageObjectNotFoundError,
    StorageUploadError,
)
from storage.keys import normalize_object_key
from storage.metadata import normalize_metadata
from storage.types import (
    StorageChecksumAlgorithm,
    StorageCopyResult,
    StorageDeleteResult,
    StorageDownloadResult,
    StorageObjectDeleteResult,
    StorageObjectInfo,
    StorageObjectMetadata,
)


def _write_stream_to_file(stream: Any, file_path: str, chunk_size: int) -> int:
    """Потоково пишет MinIO-response в файл блоками. Возвращает число байт.

    Блокирующая функция: вызывается через ``StorageClient.execute`` в пуле
    потоков. Память не зависит от размера объекта — в RAM держится лишь один
    блок ``chunk_size``.
    """

    written = 0
    with open(file_path, "wb") as file_obj:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            file_obj.write(chunk)
            written += len(chunk)
    return written


class StorageObjectManager:
    """Менеджер базовых операций с объектами MinIO/S3.

    Все операции MinIO выполняются через ``StorageClient.execute``, чтобы
    синхронный MinIO SDK не блокировал event loop.

    Args:
        client: Клиент объектного хранилища.
        bucket_name_validator: Валидатор имён bucket-ов.
    """

    def __init__(
        self,
        *,
        client: StorageClient,
        bucket_name_validator: StorageBucketNameValidator,
    ) -> None:
        """Инициализирует менеджер базовых операций.

        Args:
            client: Клиент объектного хранилища.
            bucket_name_validator: Валидатор имён bucket-ов.
        """

        self.client = client
        self.bucket_name_validator = bucket_name_validator

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

    async def put_object(
        self,
        *,
        bucket: str,
        object_key: str,
        data: BinaryIO | bytes | bytearray,
        length: int,
        content_type: str | None = None,
        metadata: dict[str, Any] | StorageObjectMetadata | None = None,
    ) -> StorageObjectInfo:
        """Загружает объект в хранилище.

        ``data`` может быть file-like объектом, ``bytes`` или ``bytearray``.
        Metadata нормализуются перед передачей в MinIO.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            data: Данные объекта.
            length: Размер объекта в байтах.
            content_type: MIME-тип объекта.
            metadata: Пользовательские metadata объекта.

        Returns:
            Информация о загруженном объекте.

        Raises:
            StorageUploadError: Если данные или размер объекта некорректны либо
                загрузка не удалась.
            StorageObjectError: Если операция с объектом не удалась.
            StorageError: Если произошла ошибка хранилища.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        normalized_metadata = normalize_metadata(metadata)

        if not isinstance(length, int) or isinstance(length, bool):
            raise StorageUploadError(
                "Размер загружаемого объекта должен быть целым числом.",
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                details={
                    "length": length,
                    "value_type": type(length).__name__,
                },
            )

        if length < 0:
            raise StorageUploadError(
                "Размер загружаемого объекта не может быть отрицательным.",
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                details={
                    "length": length,
                },
            )

        data_stream = self._prepare_data_stream(data)

        try:
            result = await self.client.execute(
                self.client.get_raw_client().put_object,
                normalized_bucket,
                normalized_object_key,
                data_stream,
                length,
                content_type=content_type,
                metadata=normalized_metadata.to_headers(),
                operation_name="put_object",
            )
        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                operation="put_object",
                operation_kind="upload",
            ) from exc

        etag = getattr(result, "etag", None)

        return StorageObjectInfo(
            bucket=normalized_bucket,
            object_key=normalized_object_key,
            size_bytes=length,
            content_type=content_type,
            etag=etag,
            metadata=normalized_metadata,
        )

    async def get_object(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> StorageDownloadResult:
        """Получает объект целиком.

        Метод является алиасом для ``get_object_bytes``.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.

        Returns:
            Результат скачивания объекта с данными в ``bytes``.

        Raises:
            StorageDownloadError: Если скачивание объекта не удалось.
            StorageObjectNotFoundError: Если объект не найден.
            StorageObjectError: Если операция с объектом не удалась.
        """

        return await self.get_object_bytes(
            bucket=bucket,
            object_key=object_key,
        )

    async def get_object_bytes(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> StorageDownloadResult:
        """Получает содержимое объекта в ``bytes``.

        Метод подходит для небольших и средних объектов. Для больших объектов
        лучше использовать ``get_object_stream``.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.

        Returns:
            Результат скачивания объекта.

        Raises:
            StorageDownloadError: Если скачивание объекта не удалось.
            StorageObjectNotFoundError: Если объект не найден.
            StorageObjectError: Если операция с объектом не удалась.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)

        response = None

        try:
            response = await self.client.execute(
                self.client.get_raw_client().get_object,
                normalized_bucket,
                normalized_object_key,
                operation_name="get_object",
            )

            data = await self.client.execute(
                response.read,
                operation_name="read_object_response",
            )

            stat = await self.stat_object(
                bucket=normalized_bucket,
                object_key=normalized_object_key,
            )

            return StorageDownloadResult(
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                data=data,
                size_bytes=len(data),
                content_type=stat.content_type,
                etag=stat.etag,
                metadata=stat.metadata,
            )

        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                operation="get_object_bytes",
                operation_kind="download",
            ) from exc
        finally:
            await self._close_response(response)

    async def get_object_range_bytes(
        self,
        *,
        bucket: str,
        object_key: str,
        offset: int = 0,
        length: int = 0,
    ) -> bytes:
        """Возвращает диапазон байт объекта, не скачивая его целиком.

        Нужно, например, для текстового превью: достаточно прочитать только
        первые N байт, а не загружать в память весь файл.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            offset: Смещение от начала объекта в байтах.
            length: Сколько байт прочитать (``0`` — до конца объекта).

        Returns:
            Прочитанные байты диапазона.

        Raises:
            StorageDownloadError: Если скачивание не удалось.
            StorageObjectNotFoundError: Если объект не найден.
            StorageObjectError: Если операция с объектом не удалась.
        """

        response = await self.get_object_stream(
            bucket=bucket,
            object_key=object_key,
            offset=offset,
            length=length,
        )
        try:
            return await self.client.execute(
                response.read,
                operation_name="read_object_range",
            )
        finally:
            await self._close_response(response)

    async def get_object_stream(
        self,
        *,
        bucket: str,
        object_key: str,
        offset: int = 0,
        length: int = 0,
    ) -> Any:
        """Возвращает поток ответа MinIO.

        Важно: вызывающий код обязан самостоятельно закрыть response через
        ``close()`` и ``release_conn()``.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            offset: Смещение в байтах от начала объекта для range-запросов.
            length: Количество байт для чтения. Значение ``0`` означает чтение
                до конца объекта.

        Returns:
            Поток ответа MinIO.

        Raises:
            StorageDownloadError: Если получение потока не удалось.
            StorageObjectNotFoundError: Если объект не найден.
            StorageObjectError: Если операция с объектом не удалась.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)

        try:
            return await self.client.execute(
                self.client.get_raw_client().get_object,
                normalized_bucket,
                normalized_object_key,
                offset=offset,
                length=length,
                operation_name="get_object_stream",
            )
        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                operation="get_object_stream",
                operation_kind="download",
            ) from exc

    async def download_object_to_file(
        self,
        *,
        bucket: str,
        object_key: str,
        file_path: str,
        chunk_size: int | None = None,
    ) -> int:
        """Потоково сохраняет объект в файл, не загружая его целиком в память.

        В отличие от ``get_object_bytes`` пик памяти не зависит от размера
        объекта: данные читаются блоками и сразу пишутся на диск. Нужно для
        обработки больших медиа (PDF/видео) в worker'е без RAM-спайка.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            file_path: Путь к файлу назначения (будет перезаписан).
            chunk_size: Размер блока чтения в байтах. По умолчанию —
                ``StorageConstants.STORAGE_DEFAULT_CHECKSUM_CHUNK_SIZE``.

        Returns:
            Количество записанных байт.

        Raises:
            StorageDownloadError: Если скачивание объекта не удалось.
            StorageObjectNotFoundError: Если объект не найден.
            StorageObjectError: Если операция с объектом не удалась.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        resolved_chunk_size = (
            chunk_size
            if chunk_size is not None
            else StorageConstants.STORAGE_DEFAULT_CHECKSUM_CHUNK_SIZE
        )

        response = None
        try:
            response = await self.client.execute(
                self.client.get_raw_client().get_object,
                normalized_bucket,
                normalized_object_key,
                operation_name="get_object",
            )
            # Блокирующее чтение из MinIO и запись на диск — целиком в пуле
            # потоков storage-клиента, чтобы не блокировать event loop.
            return await self.client.execute(
                _write_stream_to_file,
                response,
                file_path,
                resolved_chunk_size,
                operation_name="download_object_to_file",
            )
        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                operation="download_object_to_file",
                operation_kind="download",
            ) from exc
        finally:
            await self._close_response(response)

    async def calculate_object_checksum(
        self,
        *,
        bucket: str,
        object_key: str,
        algorithm: StorageChecksumAlgorithm | str,
        chunk_size: int | None = None,
    ) -> str:
        """Потоково вычисляет контрольную сумму объекта.

        В отличие от ``get_object_bytes`` объект не загружается в память
        целиком: данные читаются блоками и сразу подаются в hash-функцию,
        поэтому пик памяти не зависит от размера объекта. Блокирующее чтение и
        хеширование выполняются в пуле потоков, чтобы не блокировать event loop.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            algorithm: Алгоритм контрольной суммы.
            chunk_size: Размер блока чтения в байтах. Если ``None``, используется
                ``StorageConstants.STORAGE_DEFAULT_CHECKSUM_CHUNK_SIZE``.

        Returns:
            Контрольная сумма объекта в hex-формате.

        Raises:
            StorageDownloadError: Если скачивание объекта не удалось.
            StorageObjectNotFoundError: Если объект не найден.
            StorageObjectError: Если операция с объектом не удалась.
        """

        # Локальный импорт разрывает циклическую зависимость с модулем
        # storage.integrity, который импортирует StorageObjectManager.
        from storage.integrity import calculate_stream_checksum

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        resolved_chunk_size = (
            chunk_size
            if chunk_size is not None
            else StorageConstants.STORAGE_DEFAULT_CHECKSUM_CHUNK_SIZE
        )

        response = None

        try:
            response = await self.client.execute(
                self.client.get_raw_client().get_object,
                normalized_bucket,
                normalized_object_key,
                operation_name="get_object",
            )

            # Чтение из MinIO блокирующее, поэтому потоковое хеширование
            # выполняется целиком внутри пула потоков storage-клиента.
            return await self.client.execute(
                calculate_stream_checksum,
                response,
                algorithm=algorithm,
                chunk_size=resolved_chunk_size,
                reset_position=False,
                operation_name="calculate_object_checksum",
            )

        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                operation="calculate_object_checksum",
                operation_kind="download",
            ) from exc
        finally:
            await self._close_response(response)

    async def stat_object(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> StorageObjectInfo:
        """Возвращает информацию об объекте.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.

        Returns:
            Информация об объекте.

        Raises:
            StorageObjectNotFoundError: Если объект не найден.
            StorageObjectError: Если получение информации не удалось.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)

        try:
            stat = await self.client.execute(
                self.client.get_raw_client().stat_object,
                normalized_bucket,
                normalized_object_key,
                operation_name="stat_object",
            )
        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                operation="stat_object",
            ) from exc

        return self._build_object_info(
            bucket=normalized_bucket,
            object_key=normalized_object_key,
            stat=stat,
        )

    async def object_exists(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> bool:
        """Проверяет существование объекта.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.

        Returns:
            ``True``, если объект существует, иначе ``False``.

        Raises:
            StorageObjectError: Если проверка завершилась ошибкой, отличной от
                отсутствия объекта.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)

        try:
            await self.stat_object(
                bucket=normalized_bucket,
                object_key=normalized_object_key,
            )
            return True
        except StorageObjectNotFoundError:
            return False

    async def delete_object(
        self,
        *,
        bucket: str,
        object_key: str,
        missing_ok: bool = False,
    ) -> bool:
        """Удаляет объект.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            missing_ok: Не считать ошибкой отсутствие объекта.

        Returns:
            ``True``, если объект удалён. ``False``, если объект отсутствует и
            ``missing_ok`` равен ``True``.

        Raises:
            StorageObjectNotFoundError: Если объект отсутствует и
                ``missing_ok`` равен ``False``.
            StorageDeleteError: Если удаление объекта не удалось.
            StorageObjectError: Если операция с объектом не удалась.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)

        if not await self.object_exists(
            bucket=normalized_bucket,
            object_key=normalized_object_key,
        ):
            if missing_ok:
                return False

            raise StorageObjectNotFoundError(
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                details={
                    "operation": "delete_object",
                },
            )

        try:
            await self.client.execute(
                self.client.get_raw_client().remove_object,
                normalized_bucket,
                normalized_object_key,
                operation_name="delete_object",
            )
        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                operation="delete_object",
                operation_kind="delete",
            ) from exc

        return True

    async def delete_object_result(
        self,
        *,
        bucket: str,
        object_key: str,
        missing_ok: bool = False,
    ) -> StorageDeleteResult:
        """Удаляет объект и возвращает DTO-результат удаления.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            missing_ok: Не считать ошибкой отсутствие объекта.

        Returns:
            DTO с результатом удаления.

        Raises:
            StorageObjectNotFoundError: Если объект отсутствует и
                ``missing_ok`` равен ``False``.
            StorageDeleteError: Если удаление объекта не удалось.
            StorageObjectError: Если операция с объектом не удалась.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)

        deleted = await self.delete_object(
            bucket=normalized_bucket,
            object_key=normalized_object_key,
            missing_ok=missing_ok,
        )

        return StorageDeleteResult(
            bucket=normalized_bucket,
            object_key=normalized_object_key,
            deleted=deleted,
        )

    async def delete_objects(
        self,
        *,
        bucket: str,
        object_keys: Iterable[str],
    ) -> StorageObjectDeleteResult:
        """Удаляет несколько объектов.

        Args:
            bucket: Имя bucket.
            object_keys: Ключи объектов для удаления.

        Returns:
            Результат группового удаления с количеством успешно обработанных
            ключей и списком ошибок MinIO.

        Raises:
            StorageDeleteError: Если групповое удаление не удалось.
            StorageObjectError: Если операция с объектами не удалась.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_keys = [
            normalize_object_key(object_key) for object_key in object_keys
        ]

        if not normalized_object_keys:
            return StorageObjectDeleteResult(deleted_count=0)

        delete_objects = [
            DeleteObject(object_key) for object_key in normalized_object_keys
        ]

        try:
            error_iterator = await self.client.execute(
                self.client.get_raw_client().remove_objects,
                normalized_bucket,
                delete_objects,
                operation_name="delete_objects",
            )

            errors = await self.client.execute(
                lambda: list(error_iterator),
                operation_name="collect_delete_objects_errors",
            )
        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=None,
                operation="delete_objects",
                operation_kind="delete",
            ) from exc

        parsed_errors: list[StorageObjectError] = []

        for error in errors:
            error_object_key = getattr(error, "object_name", None)
            error_code = getattr(error, "code", None)
            error_message = getattr(error, "message", None)

            parsed_errors.append(
                StorageObjectError(
                    "Не удалось удалить объект из хранилища.",
                    bucket=normalized_bucket,
                    object_key=error_object_key,
                    operation="delete_objects",
                    details={
                        "code": error_code,
                        "reason": error_message,
                    },
                )
            )

        return StorageObjectDeleteResult(
            deleted_count=len(normalized_object_keys) - len(parsed_errors),
            errors=parsed_errors,
        )

    async def copy_object(
        self,
        *,
        source_bucket: str,
        source_object_key: str,
        destination_bucket: str,
        destination_object_key: str,
        metadata: dict[str, Any] | StorageObjectMetadata | None = None,
    ) -> StorageCopyResult:
        """Копирует объект внутри хранилища.

        Если ``metadata`` переданы, metadata целевого объекта заменяются. Если
        ``metadata`` не переданы, MinIO/S3 сохраняет metadata исходника.

        Args:
            source_bucket: Имя bucket исходного объекта.
            source_object_key: Ключ исходного объекта.
            destination_bucket: Имя bucket целевого объекта.
            destination_object_key: Ключ целевого объекта.
            metadata: Новые metadata целевого объекта.

        Returns:
            Результат копирования объекта.

        Raises:
            StorageCopyError: Если копирование объекта не удалось.
            StorageObjectNotFoundError: Если исходный объект не найден.
            StorageObjectError: Если операция с объектом не удалась.
        """

        normalized_source_bucket = self._validate_bucket_name(source_bucket)
        normalized_source_object_key = normalize_object_key(source_object_key)
        normalized_destination_bucket = self._validate_bucket_name(
            destination_bucket,
        )
        normalized_destination_object_key = normalize_object_key(
            destination_object_key,
        )
        normalized_metadata = normalize_metadata(metadata)

        source = CopySource(
            normalized_source_bucket,
            normalized_source_object_key,
        )

        extra_kwargs: dict[str, Any] = {}

        if normalized_metadata.has_metadata:
            extra_kwargs["metadata"] = normalized_metadata.to_headers()
            extra_kwargs["metadata_directive"] = "REPLACE"

        try:
            await self.client.execute(
                self.client.get_raw_client().copy_object,
                normalized_destination_bucket,
                normalized_destination_object_key,
                source,
                operation_name="copy_object",
                **extra_kwargs,
            )
        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_destination_bucket,
                object_key=normalized_destination_object_key,
                operation="copy_object",
                operation_kind="copy",
                details={
                    "source_bucket": normalized_source_bucket,
                    "source_object_key": normalized_source_object_key,
                },
            ) from exc

        copied_object = await self.stat_object(
            bucket=normalized_destination_bucket,
            object_key=normalized_destination_object_key,
        )

        return StorageCopyResult(
            source_bucket=normalized_source_bucket,
            source_object_key=normalized_source_object_key,
            destination_bucket=normalized_destination_bucket,
            destination_object_key=normalized_destination_object_key,
            etag=copied_object.etag,
            copied_at=datetime.now(UTC),
        )

    async def compose_object(
        self,
        *,
        bucket: str,
        object_key: str,
        sources: Iterable[tuple[str, str]],
        metadata: dict[str, Any] | StorageObjectMetadata | None = None,
    ) -> StorageObjectInfo:
        """Собирает объект из нескольких исходных объектов.

        ``sources`` принимает пары ``(source_bucket, source_object_key)``.

        Для маленьких объектов, которые не подходят под ограничение S3 compose
        по минимальному размеру части, используется fallback через скачивание
        частей и повторную загрузку итогового объекта.

        Args:
            bucket: Имя bucket целевого объекта.
            object_key: Ключ целевого объекта.
            sources: Исходные объекты в формате ``(bucket, object_key)``.
            metadata: Metadata итогового объекта.

        Returns:
            Информация о собранном объекте.

        Raises:
            StorageObjectError: Если список исходных объектов пустой или
                compose-операция не удалась.
            StorageObjectNotFoundError: Если один из исходных объектов не
                найден.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        normalized_metadata = normalize_metadata(metadata)

        normalized_sources = [
            (
                self._validate_bucket_name(source_bucket),
                normalize_object_key(source_object_key),
            )
            for source_bucket, source_object_key in sources
        ]

        source_objects = [
            ComposeSource(source_bucket, source_object_key)
            for source_bucket, source_object_key in normalized_sources
        ]

        if not source_objects:
            raise StorageObjectError(
                "Для compose_object нужен хотя бы один исходный объект.",
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                operation="compose_object",
            )

        extra_kwargs: dict[str, Any] = {}

        if normalized_metadata.has_metadata:
            extra_kwargs["metadata"] = normalized_metadata.to_headers()

        try:
            await self.client.execute(
                self.client.get_raw_client().compose_object,
                normalized_bucket,
                normalized_object_key,
                source_objects,
                operation_name="compose_object",
                **extra_kwargs,
            )
        except StorageError as exc:
            reason = str(exc.details.get("reason", ""))

            if "must be greater than 5242880" in reason:
                return await self._compose_small_objects_fallback(
                    bucket=normalized_bucket,
                    object_key=normalized_object_key,
                    sources=normalized_sources,
                    metadata=normalized_metadata,
                )

            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                operation="compose_object",
            ) from exc

        return await self.stat_object(
            bucket=normalized_bucket,
            object_key=normalized_object_key,
        )

    async def list_objects(
        self,
        *,
        bucket: str,
        prefix: str | None = None,
        recursive: bool = True,
    ) -> list[StorageObjectInfo]:
        """Возвращает список объектов bucket-а.

        Для каждого объекта формируется ``StorageObjectInfo`` на основании
        результата ``list_objects``. Metadata при listing обычно недоступны,
        поэтому поле ``metadata`` будет пустым.

        Args:
            bucket: Имя bucket.
            prefix: Префикс ключей объектов.
            recursive: Выполнять рекурсивный обход.

        Returns:
            Список объектов bucket-а.

        Raises:
            StorageObjectError: Если получение списка объектов не удалось.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_prefix = normalize_object_key(prefix) if prefix is not None else None

        try:
            objects_iter = await self.client.execute(
                self.client.get_raw_client().list_objects,
                normalized_bucket,
                prefix=normalized_prefix,
                recursive=recursive,
                operation_name="list_objects",
            )

            objects = await self.client.execute(
                lambda: list(objects_iter),
                operation_name="collect_list_objects",
            )
        except StorageError as exc:
            raise self._object_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_prefix,
                operation="list_objects",
            ) from exc

        result: list[StorageObjectInfo] = []

        for item in objects:
            object_name = getattr(item, "object_name", None)

            if not object_name:
                continue

            size = getattr(item, "size", None)
            etag = getattr(item, "etag", None)
            last_modified = getattr(item, "last_modified", None)
            content_type = getattr(item, "content_type", None)

            result.append(
                StorageObjectInfo(
                    bucket=normalized_bucket,
                    object_key=normalize_object_key(str(object_name)),
                    size_bytes=int(size) if size is not None else 0,
                    content_type=content_type,
                    etag=etag,
                    last_modified_at=last_modified
                    if isinstance(last_modified, datetime)
                    else None,
                )
            )

        return result

    async def count_objects(
        self,
        *,
        bucket: str,
        prefix: str | None = None,
        recursive: bool = True,
    ) -> int:
        """Возвращает количество объектов в bucket-е или prefix-е.

        Args:
            bucket: Имя bucket.
            prefix: Префикс ключей объектов.
            recursive: Выполнять рекурсивный обход.

        Returns:
            Количество объектов.

        Raises:
            StorageObjectError: Если получение списка объектов не удалось.
        """

        objects = await self.list_objects(
            bucket=bucket,
            prefix=prefix,
            recursive=recursive,
        )
        return len(objects)

    @staticmethod
    def _prepare_data_stream(data: BinaryIO | bytes | bytearray) -> BinaryIO:
        """Подготавливает поток данных для загрузки.

        Args:
            data: Данные объекта в виде ``bytes``, ``bytearray`` или file-like
                объекта.

        Returns:
            Binary stream для передачи в MinIO SDK.

        Raises:
            StorageUploadError: Если тип данных не поддерживается.
        """

        if isinstance(data, bytes):
            return BytesIO(data)

        if isinstance(data, bytearray):
            return BytesIO(bytes(data))

        if not hasattr(data, "read"):
            raise StorageUploadError(
                "Данные объекта должны быть bytes, bytearray или file-like объектом.",
                details={
                    "value_type": type(data).__name__,
                },
            )

        return data

    @staticmethod
    def _build_object_info(
        *,
        bucket: str,
        object_key: str,
        stat: Any,
    ) -> StorageObjectInfo:
        """Создаёт DTO информации об объекте из результата ``stat_object``.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            stat: Результат ``stat_object`` из MinIO SDK.

        Returns:
            Информация об объекте.
        """

        size = getattr(stat, "size", None)
        etag = getattr(stat, "etag", None)
        content_type = getattr(stat, "content_type", None)
        last_modified = getattr(stat, "last_modified", None)

        normalized_metadata = StorageObjectManager._extract_user_metadata(
            stat,
        )

        checksum = normalized_metadata.get("checksum")
        checksum_algorithm_value = normalized_metadata.get(
            "checksum_algorithm",
        )
        checksum_algorithm: StorageChecksumAlgorithm | None = None

        if checksum_algorithm_value is not None:
            try:
                checksum_algorithm = StorageChecksumAlgorithm(
                    checksum_algorithm_value,
                )
            except ValueError:
                checksum_algorithm = None

        return StorageObjectInfo(
            bucket=bucket,
            object_key=object_key,
            size_bytes=int(size) if size is not None else 0,
            content_type=content_type,
            etag=etag,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
            metadata=normalized_metadata,
            last_modified_at=last_modified
            if isinstance(last_modified, datetime)
            else None,
        )

    async def _close_response(self, response: Any | None) -> None:
        """Закрывает response MinIO и освобождает соединение.

        Args:
            response: Response-объект MinIO или ``None``.

        Returns:
            ``None``.
        """

        if response is None:
            return

        close_method = getattr(response, "close", None)
        release_conn_method = getattr(response, "release_conn", None)

        try:
            if callable(close_method):
                await self.client.execute(
                    close_method,
                    operation_name="close_object_response",
                )

            if callable(release_conn_method):
                await self.client.execute(
                    release_conn_method,
                    operation_name="release_object_response_connection",
                )
        except StorageError:
            return

    @staticmethod
    def _object_error(
        exc: StorageError,
        *,
        bucket: str,
        object_key: str | None,
        operation: str,
        operation_kind: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> StorageError:
        """Преобразует ошибку хранилища в ошибку уровня объектов.

        Args:
            exc: Исходная ошибка хранилища.
            bucket: Имя bucket.
            object_key: Ключ объекта.
            operation: Название выполняемой операции.
            operation_kind: Тип операции для выбора специализированной ошибки.
            details: Дополнительные details для итоговой ошибки.

        Returns:
            Уточнённая ошибка хранилища.
        """

        if isinstance(exc, StorageObjectNotFoundError):
            return exc

        if isinstance(exc, StorageConnectionError):
            return exc

        merged_details = dict(exc.details)
        merged_details.setdefault("reason", exc.message)

        if details:
            merged_details.update(details)

        code = merged_details.get("code")
        status_code = merged_details.get("status_code")

        if (
            code
            in {
                "NoSuchKey",
                "NoSuchObject",
                "NotFound",
                "NoSuchBucket",
                "NoSuchBucketPolicy",
            }
            or status_code == 404
        ):
            if object_key is None:
                return StorageObjectError(
                    "Объект не найден при выполнении операции.",
                    bucket=bucket,
                    object_key=object_key,
                    operation=operation,
                    details=merged_details,
                    cause=exc,
                )

            return StorageObjectNotFoundError(
                bucket=bucket,
                object_key=object_key,
                details={
                    **merged_details,
                    "operation": operation,
                },
                cause=exc,
            )

        if operation_kind == "upload":
            return StorageUploadError(
                "Загрузка объекта в хранилище не удалась.",
                bucket=bucket,
                object_key=object_key,
                details={
                    **merged_details,
                    "operation": operation,
                },
                cause=exc,
            )

        if operation_kind == "download":
            return StorageDownloadError(
                "Скачивание объекта из хранилища не удалось.",
                bucket=bucket,
                object_key=object_key,
                details={
                    **merged_details,
                    "operation": operation,
                },
                cause=exc,
            )

        if operation_kind == "delete":
            return StorageDeleteError(
                "Удаление объекта из хранилища не удалось.",
                bucket=bucket,
                object_key=object_key,
                details={
                    **merged_details,
                    "operation": operation,
                },
                cause=exc,
            )

        if operation_kind == "copy":
            return StorageCopyError(
                "Копирование объекта в хранилище не удалось.",
                destination_bucket=bucket,
                destination_object_key=object_key,
                details={
                    **merged_details,
                    "operation": operation,
                },
                cause=exc,
            )

        return StorageObjectError(
            "Операция с объектом хранилища не удалась.",
            bucket=bucket,
            object_key=object_key,
            operation=operation,
            details=merged_details,
            cause=exc,
        )

    @staticmethod
    def _extract_user_metadata(stat: Any) -> StorageObjectMetadata:
        """Извлекает пользовательские metadata из результата ``stat_object``.

        В разных версиях MinIO SDK metadata могут быть доступны как:

        * ``stat.metadata``;
        * ``stat._metadata``;
        * ``stat.http_headers``;
        * ``stat._http_headers``;
        * ``stat.headers``;
        * ``stat._headers``.

        Пользовательские metadata в S3 обычно приходят как HTTP-заголовки
        ``x-amz-meta-*``.

        Args:
            stat: Результат ``stat_object`` из MinIO SDK.

        Returns:
            Нормализованные пользовательские metadata.
        """

        user_metadata: dict[str, str] = {}

        raw_candidates: list[Any] = [
            getattr(stat, "metadata", None),
            getattr(stat, "_metadata", None),
            getattr(stat, "http_headers", None),
            getattr(stat, "_http_headers", None),
            getattr(stat, "headers", None),
            getattr(stat, "_headers", None),
        ]

        for raw_metadata in raw_candidates:
            if raw_metadata is None:
                continue

            extracted = StorageObjectManager._extract_metadata_from_mapping(
                raw_metadata,
            )
            user_metadata.update(extracted)

        return normalize_metadata(user_metadata)

    @staticmethod
    def _extract_metadata_from_mapping(
        raw_metadata: Any,
    ) -> dict[str, str]:
        """Извлекает пользовательские metadata из mapping-структуры.

        Args:
            raw_metadata: Исходная структура metadata.

        Returns:
            Словарь пользовательских metadata.
        """

        if not isinstance(raw_metadata, Mapping):
            return {}

        result: dict[str, str] = {}

        for raw_key, raw_value in raw_metadata.items():
            key = str(raw_key).strip().lower()
            value = str(raw_value).strip()

            if not key or not value:
                continue

            if key.startswith("x-amz-meta-"):
                result[key.removeprefix("x-amz-meta-")] = value
                continue

            if key.startswith("x-minio-meta-"):
                result[key.removeprefix("x-minio-meta-")] = value
                continue

            if key.startswith("metadata."):
                result[key.removeprefix("metadata.")] = value
                continue

            if key in {
                "purpose",
                "source",
                "number",
                "flag",
                "checksum",
                "checksum_algorithm",
                "original_filename",
                "content_type",
                "user_id",
                "file_id",
                "version_id",
                "upload_session_id",
                "task_id",
                "public_link_id",
                "created_by",
            }:
                result[key] = value

        return result

    async def _compose_small_objects_fallback(
        self,
        *,
        bucket: str,
        object_key: str,
        sources: list[tuple[str, str]],
        metadata: StorageObjectMetadata,
    ) -> StorageObjectInfo:
        """Собирает маленькие объекты через скачивание и повторную загрузку.

        Используется как fallback, когда S3 compose отклоняет части меньше
        минимально допустимого размера.

        Args:
            bucket: Имя bucket итогового объекта.
            object_key: Ключ итогового объекта.
            sources: Список исходных объектов в формате
                ``(source_bucket, source_object_key)``.
            metadata: Metadata итогового объекта.

        Returns:
            Информация о созданном объекте.

        Raises:
            StorageDownloadError: Если скачивание одной из частей не удалось.
            StorageUploadError: Если загрузка итогового объекта не удалась.
            StorageObjectError: Если операция с объектом не удалась.
        """

        payload_parts: list[bytes] = []

        for source_bucket, source_object_key in sources:
            download_result = await self.get_object_bytes(
                bucket=source_bucket,
                object_key=source_object_key,
            )
            payload_parts.append(download_result.data)

        payload = b"".join(payload_parts)

        content_type = None
        if metadata.has_metadata:
            content_type = metadata.get("content_type")

        return await self.put_object(
            bucket=bucket,
            object_key=object_key,
            data=payload,
            length=len(payload),
            content_type=content_type,
            metadata=metadata,
        )
