from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any, BinaryIO

from core.config import StorageSettings
from core.constants import StorageConstants
from core.logging import get_logger
from storage.buckets import (
    StorageBucketManager,
    StorageBucketNameValidator,
)
from storage.client import StorageClient
from storage.exceptions import StorageError
from storage.health import StorageHealthChecker
from storage.integrity import StorageIntegrityChecker
from storage.keys import (
    build_archive_object_key,
    build_file_object_key,
    build_file_version_object_key,
    build_preview_object_key,
    normalize_object_key,
)
from storage.metadata import (
    build_archive_metadata,
    build_file_metadata,
    build_file_version_metadata,
    build_preview_metadata,
    normalize_metadata,
)
from storage.multipart import StorageMultipartManager
from storage.objects import StorageObjectDeleteResult, StorageObjectManager
from storage.presigned import (
    StoragePresignedUrlManager,
)
from storage.types import (
    StorageChecksumAlgorithm,
    StorageCopyResult,
    StorageDownloadResult,
    StorageIntegrityReport,
    StorageMultipartUpload,
    StorageObjectInfo,
    StorageObjectMetadata,
    StorageObjectStatus,
    StoragePresignedUploadPartUrl,
    StoragePresignedUrl,
    StorageUploadPart,
)

logger = get_logger("storage.service")


class StorageService:
    """Высокоуровневый фасад объектного хранилища LocalCloud.

    Сервис объединяет bucket/object/multipart/presigned/integrity менеджеры и
    предоставляет методы, удобные для бизнес-сервисов backend.

    Важно:
        Сервис не читает конфигурацию самостоятельно, не обращается к
        PostgreSQL, не открывает транзакции, не проверяет права пользователя и
        не принимает решений о бизнес-доступе к файлам.

    Args:
        settings: Настройки объектного хранилища.
        client: Готовый клиент объектного хранилища.
        bucket_name_validator: Валидатор имён bucket-ов.
        bucket_manager: Менеджер операций с bucket-ами.
        object_manager: Менеджер операций с объектами.
        multipart_manager: Менеджер multipart-загрузок.
        presigned_url_manager: Менеджер pre-signed URL.
        integrity_checker: Компонент проверки целостности.
        health_checker: Компонент health-check.
    """

    def __init__(
        self,
        *,
        settings: StorageSettings,
        client: StorageClient | None = None,
        bucket_name_validator: StorageBucketNameValidator | None = None,
        bucket_manager: StorageBucketManager | None = None,
        object_manager: StorageObjectManager | None = None,
        multipart_manager: StorageMultipartManager | None = None,
        presigned_url_manager: StoragePresignedUrlManager | None = None,
        integrity_checker: StorageIntegrityChecker | None = None,
        health_checker: StorageHealthChecker | None = None,
    ) -> None:
        """Инициализирует высокоуровневый фасад объектного хранилища.

        Args:
            settings: Настройки объектного хранилища.
            client: Готовый клиент объектного хранилища.
            bucket_name_validator: Валидатор имён bucket-ов.
            bucket_manager: Менеджер операций с bucket-ами.
            object_manager: Менеджер операций с объектами.
            multipart_manager: Менеджер multipart-загрузок.
            presigned_url_manager: Менеджер pre-signed URL.
            integrity_checker: Компонент проверки целостности.
            health_checker: Компонент health-check.
        """

        self.settings = settings

        self.bucket_name_validator = (
            bucket_name_validator
            or StorageBucketNameValidator(
                min_length=StorageConstants.S3_BUCKET_NAME_MIN_LENGTH,
                max_length=StorageConstants.S3_BUCKET_NAME_MAX_LENGTH,
            )
        )

        self.default_files_bucket = self.bucket_name_validator.validate(
            StorageConstants.MINIO_BUCKET_FILES,
        )
        self.default_temp_bucket = self.bucket_name_validator.validate(
            StorageConstants.MINIO_BUCKET_TEMP,
        )
        self.default_archives_bucket = self.bucket_name_validator.validate(
            StorageConstants.MINIO_BUCKET_ARCHIVES,
        )
        self.default_buckets = [
            self.default_files_bucket,
            self.default_temp_bucket,
            self.default_archives_bucket,
        ]

        self.presigned_upload_expire_seconds = (
            StorageConstants.PRESIGNED_UPLOAD_EXPIRE_SECONDS
        )
        self.presigned_download_expire_seconds = (
            StorageConstants.PRESIGNED_DOWNLOAD_EXPIRE_SECONDS
        )

        self.multipart_part_size_bytes = StorageConstants.MULTIPART_PART_SIZE_BYTES
        self.multipart_max_parts = StorageConstants.MULTIPART_MAX_PARTS

        self.default_checksum_chunk_size = (
            StorageConstants.STORAGE_DEFAULT_CHECKSUM_CHUNK_SIZE
        )

        self.client = client or StorageClient(settings=settings)

        self.buckets = bucket_manager or StorageBucketManager(
            client=self.client,
            bucket_name_validator=self.bucket_name_validator,
        )

        self.objects = object_manager or StorageObjectManager(
            client=self.client,
            bucket_name_validator=self.bucket_name_validator,
        )

        self.multipart = multipart_manager or StorageMultipartManager(
            client=self.client,
            bucket_name_validator=self.bucket_name_validator,
            object_manager=self.objects,
        )

        self.presigned = presigned_url_manager or StoragePresignedUrlManager(
            client=self.client,
            bucket_name_validator=self.bucket_name_validator,
        )

        self.integrity = integrity_checker or StorageIntegrityChecker(
            object_manager=self.objects,
        )

        self.health = health_checker or StorageHealthChecker(
            client=self.client,
            bucket_manager=self.buckets,
            object_manager=self.objects,
        )

    async def ensure_storage_ready(
        self,
        *,
        bucket: str | None = None,
        create_bucket: bool = False,
        region: str | None = None,
        object_lock: bool = False,
    ) -> bool:
        """Проверяет готовность хранилища и доступность bucket.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            create_bucket: Создать bucket при отсутствии.
            region: Регион bucket. Если не передан, используется регион из
                настроек.
            object_lock: Включить Object Lock при создании bucket.

        Returns:
            ``True``, если хранилище готово.

        Raises:
            StorageError: Если проверка или создание bucket не удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)
        resolved_region = region or self.settings.minio_region

        await self.client.ping()

        if create_bucket:
            await self.buckets.ensure_bucket_exists(
                resolved_bucket,
                region=resolved_region,
                object_lock=object_lock,
            )
        else:
            await self.buckets.check_bucket_access(resolved_bucket)

        return True

    async def ensure_buckets_ready(
        self,
        *,
        buckets: Iterable[str] | None = None,
        create_missing: bool = False,
        region: str | None = None,
        object_lock: bool = False,
    ) -> dict[str, bool]:
        """Проверяет готовность нескольких bucket-ов.

        Args:
            buckets: Bucket-ы для проверки. Если не переданы, проверяются
                default bucket-и storage-сервиса.
            create_missing: Создавать отсутствующие bucket-ы.
            region: Регион bucket-ов при создании.
            object_lock: Включить Object Lock при создании bucket-ов.

        Returns:
            Словарь с результатом проверки по каждому bucket.

        Raises:
            StorageError: Если ping, проверка или создание bucket не удались.
        """

        resolved_buckets = list(buckets or self.default_buckets)
        resolved_region = region or self.settings.minio_region

        await self.client.ping()

        result: dict[str, bool] = {}

        for bucket in resolved_buckets:
            normalized_bucket = self.bucket_name_validator.validate(bucket)

            if create_missing:
                await self.buckets.ensure_bucket_exists(
                    normalized_bucket,
                    region=resolved_region,
                    object_lock=object_lock,
                )
                # Авто-аборт незавершённых multipart-загрузок: best-effort,
                # чтобы недоступность lifecycle-API (нестандартный S3-совместимый
                # бэкенд) не блокировала запуск приложения.
                try:
                    await self.buckets.ensure_incomplete_multipart_lifecycle(
                        normalized_bucket,
                        days=self.settings.incomplete_multipart_expiry_days,
                    )
                except StorageError as exc:
                    logger.warning(
                        "Не удалось установить lifecycle-правило авто-аборта "
                        "незавершённых multipart-загрузок.",
                        extra={
                            "bucket": normalized_bucket,
                            "error_type": exc.__class__.__name__,
                            "reason": str(exc),
                        },
                    )
                result[normalized_bucket] = True
                continue

            result[normalized_bucket] = await self.buckets.check_bucket_access(
                normalized_bucket,
            )

        return result

    async def upload_file_object(
        self,
        *,
        data: BinaryIO | bytes | bytearray,
        length: int,
        bucket: str | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | StorageObjectMetadata | None = None,
        checksum: str | None = None,
        checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
        original_filename: str | None = None,
        created_by: uuid.UUID | str | None = None,
    ) -> StorageObjectInfo:
        """Загружает объект файла в хранилище.

        Если ``object_key`` не передан, сервис строит ключ по ``user_id``,
        ``file_id`` и ``version_id``.

        Args:
            data: Данные объекта.
            length: Размер объекта в байтах.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.
            content_type: MIME-тип объекта.
            metadata: Дополнительные metadata.
            checksum: Контрольная сумма объекта.
            checksum_algorithm: Алгоритм контрольной суммы.
            original_filename: Исходное имя файла.
            created_by: Идентификатор создателя.

        Returns:
            Информация о загруженном объекте.

        Raises:
            StorageError: Если построение ключа, metadata или загрузка объекта
                не удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        merged_metadata = self._build_merged_file_metadata(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
            original_filename=original_filename,
            content_type=content_type,
            created_by=created_by,
            metadata=metadata,
        )

        return await self.objects.put_object(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
            data=data,
            length=length,
            content_type=content_type,
            metadata=merged_metadata,
        )

    async def download_file_object(
        self,
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
    ) -> StorageDownloadResult:
        """Скачивает объект файла полностью в ``bytes``.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.

        Returns:
            Результат скачивания объекта.

        Raises:
            StorageError: Если построение ключа или скачивание объекта не
                удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        return await self.objects.get_object_bytes(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
        )

    async def get_file_object_stream(
        self,
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        offset: int = 0,
        length: int = 0,
    ) -> Any:
        """Возвращает поток файла из хранилища.

        Вызывающий код обязан закрыть response через ``close`` и
        ``release_conn``.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.
            offset: Смещение в байтах от начала объекта.
            length: Количество байт для чтения. Значение ``0`` означает чтение
                до конца объекта.

        Returns:
            Поток ответа MinIO/S3.

        Raises:
            StorageError: Если построение ключа или получение потока не
                удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        return await self.objects.get_object_stream(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
            offset=offset,
            length=length,
        )

    async def get_file_object_info(
        self,
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
    ) -> StorageObjectInfo:
        """Возвращает stat/metadata информацию об объекте файла.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.

        Returns:
            Информация об объекте.

        Raises:
            StorageError: Если построение ключа или получение информации об
                объекте не удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        return await self.objects.stat_object(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
        )

    async def file_object_exists(
        self,
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
    ) -> bool:
        """Проверяет существование объекта файла.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.

        Returns:
            ``True``, если объект существует, иначе ``False``.

        Raises:
            StorageError: Если построение ключа или проверка существования не
                удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        return await self.objects.object_exists(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
        )

    async def delete_file_object(
        self,
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        missing_ok: bool = False,
    ) -> bool:
        """Удаляет один объект файла.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.
            missing_ok: Не считать ошибкой отсутствие объекта.

        Returns:
            ``True``, если объект удалён. ``False``, если объект отсутствует и
            ``missing_ok`` равен ``True``.

        Raises:
            StorageError: Если построение ключа или удаление объекта не
                удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        return await self.objects.delete_object(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
            missing_ok=missing_ok,
        )

    async def delete_file_objects(
        self,
        *,
        object_keys: Iterable[str],
        bucket: str | None = None,
    ) -> StorageObjectDeleteResult:
        """Удаляет несколько объектов файлов.

        Args:
            object_keys: Ключи объектов для удаления.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.

        Returns:
            Результат группового удаления объектов.

        Raises:
            StorageError: Если удаление объектов не удалось.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        return await self.objects.delete_objects(
            bucket=resolved_bucket,
            object_keys=object_keys,
        )

    async def copy_file_object(
        self,
        *,
        source_object_key: str,
        destination_object_key: str,
        source_bucket: str | None = None,
        destination_bucket: str | None = None,
        metadata: Mapping[str, Any] | StorageObjectMetadata | None = None,
    ) -> StorageCopyResult:
        """Копирует объект файла внутри S3-compatible хранилища.

        Args:
            source_object_key: Ключ исходного объекта.
            destination_object_key: Ключ целевого объекта.
            source_bucket: Bucket исходного объекта.
            destination_bucket: Bucket целевого объекта.
            metadata: Metadata целевого объекта.

        Returns:
            Результат копирования объекта.

        Raises:
            StorageError: Если копирование объекта не удалось.
        """

        resolved_source_bucket = self._resolve_files_bucket(source_bucket)
        resolved_destination_bucket = self._resolve_files_bucket(destination_bucket)

        return await self.objects.copy_object(
            source_bucket=resolved_source_bucket,
            source_object_key=source_object_key,
            destination_bucket=resolved_destination_bucket,
            destination_object_key=destination_object_key,
            metadata=normalize_metadata(metadata),
        )

    async def create_download_url(
        self,
        *,
        bucket: str | None = None,
        expires_in_seconds: int | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        response_headers: dict[str, str] | None = None,
    ) -> StoragePresignedUrl:
        """Создаёт pre-signed GET URL для скачивания объекта.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            expires_in_seconds: Срок жизни ссылки в секундах.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.
            response_headers: Response headers для GET URL.

        Returns:
            DTO с pre-signed URL.

        Raises:
            StorageError: Если построение ключа или создание URL не удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)
        resolved_expires = expires_in_seconds or self.presigned_download_expire_seconds

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        return await self.presigned.generate_presigned_get_url(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
            expires_in_seconds=resolved_expires,
            response_headers=response_headers,
        )

    async def create_upload_url(
        self,
        *,
        bucket: str | None = None,
        expires_in_seconds: int | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
    ) -> StoragePresignedUrl:
        """Создаёт pre-signed PUT URL для загрузки объекта.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            expires_in_seconds: Срок жизни ссылки в секундах.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.

        Returns:
            DTO с pre-signed URL.

        Raises:
            StorageError: Если построение ключа или создание URL не удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)
        resolved_expires = expires_in_seconds or self.presigned_upload_expire_seconds

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        return await self.presigned.generate_presigned_put_url(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
            expires_in_seconds=resolved_expires,
        )

    async def create_delete_url(
        self,
        *,
        bucket: str | None = None,
        expires_in_seconds: int | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
    ) -> StoragePresignedUrl:
        """Создаёт pre-signed DELETE URL.

        В обычной бизнес-логике удаление лучше выполнять backend-ом.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            expires_in_seconds: Срок жизни ссылки в секундах.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.

        Returns:
            DTO с pre-signed URL.

        Raises:
            StorageError: Если построение ключа или создание URL не удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)
        resolved_expires = expires_in_seconds or self.presigned_upload_expire_seconds

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        return await self.presigned.generate_presigned_delete_url(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
            expires_in_seconds=resolved_expires,
        )

    async def create_upload_part_url(
        self,
        *,
        object_key: str,
        upload_id: str,
        part_number: int,
        bucket: str | None = None,
        expires_in_seconds: int | None = None,
    ) -> StoragePresignedUrl:
        """Создаёт pre-signed PUT URL для части multipart upload.

        Args:
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart upload.
            part_number: Номер части.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            expires_in_seconds: Срок жизни ссылки в секундах.

        Returns:
            DTO с pre-signed URL.

        Raises:
            StorageError: Если создание URL не удалось.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)
        resolved_expires = expires_in_seconds or self.presigned_upload_expire_seconds

        return await self.presigned.generate_presigned_upload_part_url(
            bucket=resolved_bucket,
            object_key=object_key,
            upload_id=upload_id,
            part_number=part_number,
            expires_in_seconds=resolved_expires,
        )

    async def create_upload_part_urls(
        self,
        *,
        object_key: str,
        upload_id: str,
        part_numbers: list[int] | tuple[int, ...] | range,
        bucket: str | None = None,
        expires_in_seconds: int | None = None,
    ) -> list[StoragePresignedUploadPartUrl]:
        """Создаёт pre-signed PUT URL для нескольких частей multipart upload.

        Args:
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart upload.
            part_numbers: Номера частей.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            expires_in_seconds: Срок жизни ссылок в секундах.

        Returns:
            Список DTO с URL для частей.

        Raises:
            StorageError: Если создание URL не удалось.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)
        resolved_expires = expires_in_seconds or self.presigned_upload_expire_seconds

        return await self.presigned.generate_presigned_upload_part_urls(
            bucket=resolved_bucket,
            object_key=object_key,
            upload_id=upload_id,
            part_numbers=part_numbers,
            expires_in_seconds=resolved_expires,
        )

    async def init_multipart_upload(
        self,
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | StorageObjectMetadata | None = None,
        checksum: str | None = None,
        checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
        original_filename: str | None = None,
        created_by: uuid.UUID | str | None = None,
    ) -> StorageMultipartUpload:
        """Инициирует multipart-загрузку объекта файла.

        Состояние ``upload_sessions`` должно сохраняться вызывающим сервисом,
        а не этим storage-фасадом.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.
            content_type: MIME-тип итогового объекта.
            metadata: Дополнительные metadata.
            checksum: Контрольная сумма объекта.
            checksum_algorithm: Алгоритм контрольной суммы.
            original_filename: Исходное имя файла.
            created_by: Идентификатор создателя.

        Returns:
            DTO созданной multipart-загрузки.

        Raises:
            StorageError: Если построение ключа, metadata или инициализация
                multipart-загрузки не удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        merged_metadata = self._build_merged_file_metadata(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
            original_filename=original_filename,
            content_type=content_type,
            created_by=created_by,
            metadata=metadata,
        )

        return await self.multipart.create_multipart_upload(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
            content_type=content_type,
            metadata=merged_metadata,
        )

    async def upload_multipart_part(
        self,
        *,
        object_key: str,
        upload_id: str,
        part_number: int,
        data: BinaryIO | bytes | bytearray,
        size_bytes: int,
        bucket: str | None = None,
    ) -> StorageUploadPart:
        """Загружает одну часть multipart upload через backend.

        Args:
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart upload.
            part_number: Номер части.
            data: Данные части.
            size_bytes: Размер части в байтах.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.

        Returns:
            DTO загруженной части.

        Raises:
            StorageError: Если загрузка части не удалась.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        return await self.multipart.upload_part(
            bucket=resolved_bucket,
            object_key=object_key,
            upload_id=upload_id,
            part_number=part_number,
            data=data,
            size_bytes=size_bytes,
        )

    async def list_multipart_parts(
        self,
        *,
        object_key: str,
        upload_id: str,
        bucket: str | None = None,
        max_parts: int | None = None,
        part_number_marker: int = 0,
    ) -> list[StorageUploadPart]:
        """Возвращает уже загруженные части multipart upload.

        Args:
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart upload.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            max_parts: Максимальное количество частей.
            part_number_marker: Marker номера части.

        Returns:
            Список загруженных частей.

        Raises:
            StorageError: Если получение списка частей не удалось.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)
        resolved_max_parts = max_parts or self.multipart_max_parts

        return await self.multipart.list_uploaded_parts(
            bucket=resolved_bucket,
            object_key=object_key,
            upload_id=upload_id,
            max_parts=resolved_max_parts,
            part_number_marker=part_number_marker,
        )

    async def complete_multipart_upload(
        self,
        *,
        object_key: str,
        upload_id: str,
        parts: Iterable[StorageUploadPart | tuple[int, str] | dict[str, Any]],
        bucket: str | None = None,
    ) -> StorageObjectInfo:
        """Завершает multipart-загрузку объекта.

        Args:
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart upload.
            parts: Загруженные части.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.

        Returns:
            Информация об итоговом объекте.

        Raises:
            StorageError: Если завершение multipart-загрузки не удалось.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        return await self.multipart.complete_multipart_upload(
            bucket=resolved_bucket,
            object_key=object_key,
            upload_id=upload_id,
            parts=parts,
        )

    async def abort_multipart_upload(
        self,
        *,
        object_key: str,
        upload_id: str,
        bucket: str | None = None,
        missing_ok: bool = False,
    ) -> bool:
        """Отменяет multipart-загрузку объекта.

        Args:
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart upload.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            missing_ok: Не считать ошибкой отсутствие multipart upload.

        Returns:
            ``True``, если upload отменён. ``False``, если upload отсутствует
            и ``missing_ok`` равен ``True``.

        Raises:
            StorageError: Если отмена multipart-загрузки не удалась.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        return await self.multipart.abort_multipart_upload(
            bucket=resolved_bucket,
            object_key=object_key,
            upload_id=upload_id,
            missing_ok=missing_ok,
        )

    async def verify_file_object(
        self,
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        user_id: uuid.UUID | None = None,
        file_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        expected_size_bytes: int | None = None,
        expected_checksum: str | None = None,
        expected_checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
        expected_metadata: Mapping[str, Any] | StorageObjectMetadata | None = None,
        expected_status: StorageObjectStatus | None = None,
        require_exact_metadata_match: bool = False,
    ) -> StorageIntegrityReport:
        """Проверяет целостность объекта файла.

        Ожидаемые значения должны передаваться из слоя, где источником истины
        является PostgreSQL.

        Args:
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            object_key: Явный ключ объекта.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.
            expected_size_bytes: Ожидаемый размер объекта.
            expected_checksum: Ожидаемая контрольная сумма.
            expected_checksum_algorithm: Алгоритм контрольной суммы.
            expected_metadata: Ожидаемые metadata.
            expected_status: Ожидаемый статус объекта.
            require_exact_metadata_match: Требовать точного совпадения
                metadata.

        Returns:
            Отчёт проверки целостности.

        Raises:
            StorageError: Если построение ключа или проверка целостности не
                удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        resolved_object_key = self._resolve_file_object_key(
            object_key=object_key,
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

        return await self.integrity.verify_object(
            bucket=resolved_bucket,
            object_key=resolved_object_key,
            expected_size_bytes=expected_size_bytes,
            expected_checksum=expected_checksum,
            expected_checksum_algorithm=expected_checksum_algorithm,
            expected_metadata=expected_metadata,
            expected_status=expected_status,
            require_exact_metadata_match=require_exact_metadata_match,
        )

    async def upload_archive_object(
        self,
        *,
        user_id: uuid.UUID,
        task_id: uuid.UUID,
        data: BinaryIO | bytes | bytearray,
        length: int,
        bucket: str | None = None,
        extension: str = "zip",
        content_type: str | None = "application/zip",
        metadata: Mapping[str, Any] | StorageObjectMetadata | None = None,
        checksum: str | None = None,
        checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
        original_filename: str | None = "archive.zip",
        created_by: uuid.UUID | str | None = None,
    ) -> StorageObjectInfo:
        """Загружает объект архива.

        Метод является вспомогательным для фоновых задач архивации.

        Args:
            user_id: Идентификатор пользователя.
            task_id: Идентификатор задачи архивации.
            data: Данные архива.
            length: Размер архива в байтах.
            bucket: Имя bucket. Если не передан, используется default archives
                bucket.
            extension: Расширение объекта архива.
            content_type: MIME-тип архива.
            metadata: Дополнительные metadata.
            checksum: Контрольная сумма архива.
            checksum_algorithm: Алгоритм контрольной суммы.
            original_filename: Исходное имя архива.
            created_by: Идентификатор создателя.

        Returns:
            Информация о загруженном архиве.

        Raises:
            StorageError: Если построение ключа, metadata или загрузка архива
                не удались.
        """

        resolved_bucket = self._resolve_archives_bucket(bucket)

        object_key = self.build_archive_key(
            user_id=user_id,
            task_id=task_id,
            extension=extension,
        )

        base_metadata = build_archive_metadata(
            user_id=user_id,
            task_id=task_id,
            original_filename=original_filename,
            content_type=content_type,
            created_by=created_by,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
        )

        merged_metadata = merge_metadata_objects(
            base_metadata,
            normalize_metadata(metadata),
        )

        return await self.objects.put_object(
            bucket=resolved_bucket,
            object_key=object_key,
            data=data,
            length=length,
            content_type=content_type,
            metadata=merged_metadata,
        )

    async def upload_preview_object(
        self,
        *,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
        data: BinaryIO | bytes | bytearray,
        length: int,
        bucket: str | None = None,
        version_id: uuid.UUID | str | None = None,
        task_id: uuid.UUID | str | None = None,
        extension: str | None = None,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | StorageObjectMetadata | None = None,
        checksum: str | None = None,
        checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
        original_filename: str | None = None,
        created_by: uuid.UUID | str | None = None,
    ) -> StorageObjectInfo:
        """Загружает объект предпросмотра файла.

        Args:
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            data: Данные предпросмотра.
            length: Размер объекта в байтах.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            version_id: Идентификатор версии файла.
            task_id: Идентификатор задачи генерации предпросмотра.
            extension: Расширение объекта предпросмотра.
            content_type: MIME-тип объекта.
            metadata: Дополнительные metadata.
            checksum: Контрольная сумма объекта.
            checksum_algorithm: Алгоритм контрольной суммы.
            original_filename: Исходное имя файла.
            created_by: Идентификатор создателя.

        Returns:
            Информация о загруженном объекте предпросмотра.

        Raises:
            StorageError: Если построение ключа, metadata или загрузка объекта
                не удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        object_key = self.build_preview_key(
            user_id=user_id,
            file_id=file_id,
            extension=extension,
        )

        base_metadata = build_preview_metadata(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
            task_id=task_id,
            original_filename=original_filename,
            content_type=content_type,
            created_by=created_by,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
        )

        merged_metadata = merge_metadata_objects(
            base_metadata,
            normalize_metadata(metadata),
        )

        return await self.objects.put_object(
            bucket=resolved_bucket,
            object_key=object_key,
            data=data,
            length=length,
            content_type=content_type,
            metadata=merged_metadata,
        )

    async def download_archive_object(
        self,
        *,
        user_id: uuid.UUID,
        task_id: uuid.UUID,
        bucket: str | None = None,
        extension: str = "zip",
    ) -> StorageDownloadResult:
        """Скачивает объект архива.

        Args:
            user_id: Идентификатор пользователя.
            task_id: Идентификатор задачи архивации.
            bucket: Имя bucket. Если не передан, используется default archives
                bucket.
            extension: Расширение объекта архива.

        Returns:
            Результат скачивания архива.

        Raises:
            StorageError: Если построение ключа или скачивание архива не
                удались.
        """

        resolved_bucket = self._resolve_archives_bucket(bucket)

        object_key = self.build_archive_key(
            user_id=user_id,
            task_id=task_id,
            extension=extension,
        )

        return await self.objects.get_object_bytes(
            bucket=resolved_bucket,
            object_key=object_key,
        )

    async def delete_archive_object(
        self,
        *,
        user_id: uuid.UUID,
        task_id: uuid.UUID,
        bucket: str | None = None,
        extension: str = "zip",
        missing_ok: bool = False,
    ) -> bool:
        """Удаляет объект архива.

        Args:
            user_id: Идентификатор пользователя.
            task_id: Идентификатор задачи архивации.
            bucket: Имя bucket. Если не передан, используется default archives
                bucket.
            extension: Расширение объекта архива.
            missing_ok: Не считать ошибкой отсутствие объекта.

        Returns:
            ``True``, если объект удалён. ``False``, если объект отсутствует и
            ``missing_ok`` равен ``True``.

        Raises:
            StorageError: Если построение ключа или удаление архива не удались.
        """

        resolved_bucket = self._resolve_archives_bucket(bucket)

        object_key = self.build_archive_key(
            user_id=user_id,
            task_id=task_id,
            extension=extension,
        )

        return await self.objects.delete_object(
            bucket=resolved_bucket,
            object_key=object_key,
            missing_ok=missing_ok,
        )

    async def delete_preview_object(
        self,
        *,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
        bucket: str | None = None,
        extension: str | None = None,
        missing_ok: bool = False,
    ) -> bool:
        """Удаляет объект предпросмотра файла.

        Args:
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            bucket: Имя bucket. Если не передан, используется default files
                bucket.
            extension: Расширение объекта предпросмотра.
            missing_ok: Не считать ошибкой отсутствие объекта.

        Returns:
            ``True``, если объект удалён. ``False``, если объект отсутствует и
            ``missing_ok`` равен ``True``.

        Raises:
            StorageError: Если построение ключа или удаление предпросмотра не
                удались.
        """

        resolved_bucket = self._resolve_files_bucket(bucket)

        object_key = self.build_preview_key(
            user_id=user_id,
            file_id=file_id,
            extension=extension,
        )

        return await self.objects.delete_object(
            bucket=resolved_bucket,
            object_key=object_key,
            missing_ok=missing_ok,
        )

    def build_file_key(
        self,
        *,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> str:
        """Строит object key основного объекта файла.

        Args:
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.

        Returns:
            Ключ объекта файла.

        Raises:
            StorageError: Если идентификаторы или итоговый ключ некорректны.
        """

        return build_file_object_key(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

    def build_file_version_key(
        self,
        *,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> str:
        """Строит object key версии файла.

        Args:
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.

        Returns:
            Ключ объекта версии файла.

        Raises:
            StorageError: Если идентификаторы или итоговый ключ некорректны.
        """

        return build_file_version_object_key(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

    def build_archive_key(
        self,
        *,
        user_id: uuid.UUID,
        task_id: uuid.UUID,
        extension: str = "zip",
    ) -> str:
        """Строит object key архива.

        Args:
            user_id: Идентификатор пользователя.
            task_id: Идентификатор задачи архивации.
            extension: Расширение архива.

        Returns:
            Ключ объекта архива.

        Raises:
            StorageError: Если идентификаторы, расширение или итоговый ключ
                некорректны.
        """

        return build_archive_object_key(
            user_id=user_id,
            task_id=task_id,
            extension=extension,
        )

    def build_preview_key(
        self,
        *,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
        extension: str | None = None,
    ) -> str:
        """Строит object key предпросмотра файла.

        Args:
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            extension: Расширение предпросмотра.

        Returns:
            Ключ объекта предпросмотра.

        Raises:
            StorageError: Если идентификаторы, расширение или итоговый ключ
                некорректны.
        """

        return build_preview_object_key(
            user_id=user_id,
            file_id=file_id,
            extension=extension,
        )

    def _resolve_files_bucket(self, bucket: str | None) -> str:
        """Возвращает нормализованный files bucket.

        Args:
            bucket: Имя bucket или ``None``.

        Returns:
            Нормализованное имя bucket.

        Raises:
            StorageError: Если имя bucket некорректно.
        """

        if bucket is None:
            return self.default_files_bucket

        return self.bucket_name_validator.validate(bucket)

    def _resolve_temp_bucket(self, bucket: str | None) -> str:
        """Возвращает нормализованный temp bucket.

        Args:
            bucket: Имя bucket или ``None``.

        Returns:
            Нормализованное имя bucket.

        Raises:
            StorageError: Если имя bucket некорректно.
        """

        if bucket is None:
            return self.default_temp_bucket

        return self.bucket_name_validator.validate(bucket)

    def _resolve_archives_bucket(self, bucket: str | None) -> str:
        """Возвращает нормализованный archives bucket.

        Args:
            bucket: Имя bucket или ``None``.

        Returns:
            Нормализованное имя bucket.

        Raises:
            StorageError: Если имя bucket некорректно.
        """

        if bucket is None:
            return self.default_archives_bucket

        return self.bucket_name_validator.validate(bucket)

    @staticmethod
    def _resolve_file_object_key(
        *,
        object_key: str | None,
        user_id: uuid.UUID | None,
        file_id: uuid.UUID | None,
        version_id: uuid.UUID | None,
    ) -> str:
        """Возвращает явный или построенный object key файла.

        Args:
            object_key: Явный object key.
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.

        Returns:
            Нормализованный object key.

        Raises:
            StorageError: Если ``object_key`` не передан и недостаточно данных
                для построения ключа.
        """

        if object_key is not None:
            return normalize_object_key(object_key)

        if user_id is None or file_id is None or version_id is None:
            raise StorageError(
                "Для построения ключа объекта файла нужны user_id, file_id и version_id.",
                details={
                    "operation": "resolve_file_object_key",
                    "user_id_provided": user_id is not None,
                    "file_id_provided": file_id is not None,
                    "version_id_provided": version_id is not None,
                },
            )

        return build_file_version_object_key(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
        )

    @staticmethod
    def _build_file_upload_metadata(
        *,
        user_id: uuid.UUID | None,
        file_id: uuid.UUID | None,
        version_id: uuid.UUID | None,
        checksum: str | None,
        checksum_algorithm: StorageChecksumAlgorithm | str | None,
        original_filename: str | None,
        content_type: str | None,
        created_by: uuid.UUID | str | None,
    ) -> StorageObjectMetadata:
        """Строит базовые metadata для загрузки файла.

        Args:
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.
            checksum: Контрольная сумма.
            checksum_algorithm: Алгоритм контрольной суммы.
            original_filename: Исходное имя файла.
            content_type: MIME-тип файла.
            created_by: Идентификатор создателя.

        Returns:
            Metadata файла или версии файла.

        Raises:
            StorageError: Если metadata некорректны.
        """

        if user_id is None or file_id is None:
            return StorageObjectMetadata()

        if version_id is None:
            return build_file_metadata(
                user_id=user_id,
                file_id=file_id,
                checksum=checksum,
                checksum_algorithm=checksum_algorithm,
                original_filename=original_filename,
                content_type=content_type,
                created_by=created_by,
            )

        return build_file_version_metadata(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
            original_filename=original_filename,
            content_type=content_type,
            created_by=created_by,
        )

    @staticmethod
    def _build_merged_file_metadata(
        *,
        user_id: uuid.UUID | None,
        file_id: uuid.UUID | None,
        version_id: uuid.UUID | None,
        checksum: str | None,
        checksum_algorithm: StorageChecksumAlgorithm | str | None,
        original_filename: str | None,
        content_type: str | None,
        created_by: uuid.UUID | str | None,
        metadata: Mapping[str, Any] | StorageObjectMetadata | None,
    ) -> StorageObjectMetadata:
        """Строит итоговые metadata файла.

        Args:
            user_id: Идентификатор пользователя.
            file_id: Идентификатор файла.
            version_id: Идентификатор версии файла.
            checksum: Контрольная сумма.
            checksum_algorithm: Алгоритм контрольной суммы.
            original_filename: Исходное имя файла.
            content_type: MIME-тип файла.
            created_by: Идентификатор создателя.
            metadata: Дополнительные metadata.

        Returns:
            Объединённые metadata файла.

        Raises:
            StorageError: Если metadata некорректны.
        """

        base_metadata = StorageService._build_file_upload_metadata(
            user_id=user_id,
            file_id=file_id,
            version_id=version_id,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
            original_filename=original_filename,
            content_type=content_type,
            created_by=created_by,
        )

        return merge_metadata_objects(
            base_metadata,
            normalize_metadata(metadata),
        )


def merge_metadata_objects(
    base_metadata: StorageObjectMetadata,
    extra_metadata: StorageObjectMetadata,
) -> StorageObjectMetadata:
    """Объединяет два ``StorageObjectMetadata``.

    Более поздние metadata переопределяют базовые значения. Используются plain
    values, а не S3-заголовки, чтобы избежать повторного добавления префикса
    ``x-amz-meta-``.

    Args:
        base_metadata: Базовые metadata.
        extra_metadata: Дополнительные metadata.

    Returns:
        Объединённые metadata.

    Raises:
        StorageError: Если metadata некорректны.
    """

    merged_values = {
        **base_metadata.to_plain_dict(),
        **extra_metadata.to_plain_dict(),
    }

    return normalize_metadata(merged_values)


def get_storage_service(
    *,
    settings: StorageSettings,
    client: StorageClient | None = None,
) -> StorageService:
    """Создаёт ``StorageService``.

    ``StorageSettings`` передаётся только в ``StorageService``, остальные
    storage-компоненты получают готовые зависимости и конкретные аргументы.

    Args:
        settings: Настройки объектного хранилища.
        client: Готовый клиент объектного хранилища.

    Returns:
        Экземпляр ``StorageService``.
    """

    return StorageService(
        settings=settings,
        client=client,
    )
