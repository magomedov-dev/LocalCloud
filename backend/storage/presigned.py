from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


from core.constants import StorageConstants
from storage.buckets import StorageBucketNameValidator
from storage.client import StorageClient
from storage.exceptions import (
    StorageConnectionError,
    StorageError,
    StoragePresignedUrlError,
)
from storage.keys import normalize_object_key
from storage.types import (
    StoragePresignedUploadPartUrl,
    StoragePresignedUrl,
    StoragePresignedUrlMethod,
)


class StoragePresignedUrlManager:
    """Менеджер генерации pre-signed URL MinIO/S3.

    Все операции выполняются через ``StorageClient.execute``, чтобы синхронный
    MinIO SDK не блокировал event loop.

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
        """Инициализирует менеджер генерации pre-signed URL.

        Args:
            client: Клиент объектного хранилища.
            bucket_name_validator: Валидатор имён bucket-ов.
        """

        self.client = client
        self.bucket_name_validator = bucket_name_validator

        self.public_url = client.settings.minio_public_url

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

    async def generate_presigned_get_url(
        self,
        *,
        bucket: str,
        object_key: str,
        expires_in_seconds: int,
        response_headers: dict[str, str] | None = None,
        request_date: datetime | None = None,
        version_id: str | None = None,
    ) -> StoragePresignedUrl:
        """Генерирует pre-signed URL для скачивания объекта.

        Метод не проверяет существование объекта и права пользователя.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expires_in_seconds: Срок жизни ссылки в секундах.
            response_headers: Response headers для переопределения ответа S3.
            request_date: Дата запроса для подписи URL.
            version_id: Идентификатор версии объекта.

        Returns:
            DTO с pre-signed URL.

        Raises:
            StoragePresignedUrlError: Если URL не удалось сформировать.
            StorageError: Если произошла ошибка хранилища.
        """

        return await self._generate_presigned_url(
            bucket=bucket,
            object_key=object_key,
            method=StoragePresignedUrlMethod.GET,
            expires_in_seconds=expires_in_seconds,
            response_headers=response_headers,
            request_date=request_date,
            version_id=version_id,
        )

    async def generate_presigned_put_url(
        self,
        *,
        bucket: str,
        object_key: str,
        expires_in_seconds: int,
        request_date: datetime | None = None,
    ) -> StoragePresignedUrl:
        """Генерирует pre-signed URL для PUT-загрузки объекта.

        Metadata и content-type в этот метод не добавляются намеренно: если они
        должны быть обязательными, их лучше контролировать через отдельную
        upload-логику или POST policy.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expires_in_seconds: Срок жизни ссылки в секундах.
            request_date: Дата запроса для подписи URL.

        Returns:
            DTO с pre-signed URL.

        Raises:
            StoragePresignedUrlError: Если URL не удалось сформировать.
            StorageError: Если произошла ошибка хранилища.
        """

        return await self._generate_presigned_url(
            bucket=bucket,
            object_key=object_key,
            method=StoragePresignedUrlMethod.PUT,
            expires_in_seconds=expires_in_seconds,
            request_date=request_date,
        )

    async def generate_presigned_delete_url(
        self,
        *,
        bucket: str,
        object_key: str,
        expires_in_seconds: int,
        request_date: datetime | None = None,
        version_id: str | None = None,
    ) -> StoragePresignedUrl:
        """Генерирует pre-signed URL для удаления объекта через DELETE.

        В обычной бизнес-логике удаление лучше выполнять backend-ом. Метод
        оставлен для инфраструктурных сценариев и тестов.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expires_in_seconds: Срок жизни ссылки в секундах.
            request_date: Дата запроса для подписи URL.
            version_id: Идентификатор версии объекта.

        Returns:
            DTO с pre-signed URL.

        Raises:
            StoragePresignedUrlError: Если URL не удалось сформировать.
            StorageError: Если произошла ошибка хранилища.
        """

        return await self._generate_presigned_url(
            bucket=bucket,
            object_key=object_key,
            method=StoragePresignedUrlMethod.DELETE,
            expires_in_seconds=expires_in_seconds,
            request_date=request_date,
            version_id=version_id,
        )

    async def generate_presigned_upload_part_url(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        part_number: int,
        expires_in_seconds: int,
        request_date: datetime | None = None,
    ) -> StoragePresignedUrl:
        """Генерирует pre-signed URL для части multipart upload.

        URL подписывается как PUT-запрос с query-параметрами ``partNumber`` и
        ``uploadId``.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart upload.
            part_number: Номер части multipart upload.
            expires_in_seconds: Срок жизни ссылки в секундах.
            request_date: Дата запроса для подписи URL.

        Returns:
            DTO с pre-signed URL для загрузки части.

        Raises:
            StoragePresignedUrlError: Если параметры некорректны или URL не
                удалось сформировать.
            StorageError: Если произошла ошибка хранилища.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        normalized_upload_id = self.validate_upload_id(upload_id)
        normalized_part_number = self.validate_part_number(part_number)
        normalized_expires = self.validate_expires_in_seconds(
            expires_in_seconds,
        )

        extra_query_params = {
            "partNumber": str(normalized_part_number),
            "uploadId": normalized_upload_id,
        }

        try:
            url = await self.client.execute(
                self.client.get_raw_client().get_presigned_url,
                StoragePresignedUrlMethod.PUT.value,
                normalized_bucket,
                normalized_object_key,
                expires=timedelta(seconds=normalized_expires),
                extra_query_params=extra_query_params,
                request_date=request_date,
                operation_name="generate_presigned_upload_part_url",
            )
        except StorageError as exc:
            raise self._presigned_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                method=StoragePresignedUrlMethod.PUT,
                expires_in_seconds=normalized_expires,
                operation="generate_presigned_upload_part_url",
                details={
                    "upload_id": normalized_upload_id,
                    "part_number": normalized_part_number,
                },
            ) from exc

        return self._build_presigned_url_result(
            url=self._to_public_url(url),
            method=StoragePresignedUrlMethod.PUT,
            bucket=normalized_bucket,
            object_key=normalized_object_key,
            expires_in_seconds=normalized_expires,
            headers={},
        )

    async def generate_presigned_upload_part_urls(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        part_numbers: list[int] | tuple[int, ...] | range,
        expires_in_seconds: int,
        request_date: datetime | None = None,
    ) -> list[StoragePresignedUploadPartUrl]:
        """Генерирует набор pre-signed URL для частей multipart upload.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            upload_id: Идентификатор multipart upload.
            part_numbers: Номера частей multipart upload.
            expires_in_seconds: Срок жизни ссылок в секундах.
            request_date: Дата запроса для подписи URL.

        Returns:
            Список DTO с номерами частей и pre-signed URL.

        Raises:
            StoragePresignedUrlError: Если параметры некорректны или URL не
                удалось сформировать.
            StorageError: Если произошла ошибка хранилища.
        """

        result: list[StoragePresignedUploadPartUrl] = []

        for part_number in part_numbers:
            normalized_part_number = self.validate_part_number(part_number)
            url = await self.generate_presigned_upload_part_url(
                bucket=bucket,
                object_key=object_key,
                upload_id=upload_id,
                part_number=normalized_part_number,
                expires_in_seconds=expires_in_seconds,
                request_date=request_date,
            )
            result.append(
                StoragePresignedUploadPartUrl(
                    part_number=normalized_part_number,
                    url=url,
                )
            )

        return result

    async def _generate_presigned_url(
        self,
        *,
        bucket: str,
        object_key: str,
        method: StoragePresignedUrlMethod,
        expires_in_seconds: int,
        response_headers: dict[str, str] | None = None,
        request_date: datetime | None = None,
        version_id: str | None = None,
    ) -> StoragePresignedUrl:
        """Генерирует pre-signed URL указанного HTTP-метода.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            method: HTTP-метод pre-signed URL.
            expires_in_seconds: Срок жизни ссылки в секундах.
            response_headers: Response headers для переопределения ответа S3.
            request_date: Дата запроса для подписи URL.
            version_id: Идентификатор версии объекта.

        Returns:
            DTO с pre-signed URL.

        Raises:
            StoragePresignedUrlError: Если URL не удалось сформировать.
            StorageError: Если произошла ошибка хранилища.
        """

        normalized_bucket = self._validate_bucket_name(bucket)
        normalized_object_key = normalize_object_key(object_key)
        normalized_expires = self.validate_expires_in_seconds(
            expires_in_seconds,
        )
        normalized_response_headers = self.normalize_response_headers(
            response_headers,
        )

        extra_query_params: dict[str, str] = {}

        if version_id is not None and version_id.strip():
            extra_query_params["versionId"] = version_id.strip()

        try:
            url = await self.client.execute(
                self.client.get_raw_client().get_presigned_url,
                method.value,
                normalized_bucket,
                normalized_object_key,
                expires=timedelta(seconds=normalized_expires),
                response_headers=normalized_response_headers or None,
                request_date=request_date,
                extra_query_params=extra_query_params or None,
                operation_name=f"generate_presigned_{method.value.lower()}_url",
            )
        except StorageError as exc:
            raise self._presigned_error(
                exc,
                bucket=normalized_bucket,
                object_key=normalized_object_key,
                method=method,
                expires_in_seconds=normalized_expires,
                operation=f"generate_presigned_{method.value.lower()}_url",
            ) from exc

        return self._build_presigned_url_result(
            url=self._to_public_url(url),
            method=method,
            bucket=normalized_bucket,
            object_key=normalized_object_key,
            expires_in_seconds=normalized_expires,
            headers=normalized_response_headers,
        )

    def validate_expires_in_seconds(self, expires_in_seconds: int) -> int:
        """Проверяет срок жизни pre-signed URL.

        Максимум ограничен 7 днями, что соответствует распространённому пределу
        для S3-compatible pre-signed URL.

        Args:
            expires_in_seconds: Срок жизни ссылки в секундах.

        Returns:
            Проверенное значение срока жизни.

        Raises:
            StoragePresignedUrlError: Если значение не является допустимым
                целым числом секунд.
        """

        if not isinstance(expires_in_seconds, int):
            raise StoragePresignedUrlError(
                "Срок жизни pre-signed URL должен быть целым числом секунд.",
                expires_in_seconds=None,
                details={
                    "operation": "validate_expires_in_seconds",
                    "value": expires_in_seconds,
                    "value_type": type(expires_in_seconds).__name__,
                },
            )

        if isinstance(expires_in_seconds, bool):
            raise StoragePresignedUrlError(
                "Срок жизни pre-signed URL должен быть целым числом секунд, а не bool.",
                expires_in_seconds=None,
                details={
                    "operation": "validate_expires_in_seconds",
                    "value": expires_in_seconds,
                    "value_type": type(expires_in_seconds).__name__,
                },
            )

        if expires_in_seconds < StorageConstants.S3_PRESIGNED_MIN_EXPIRES_IN_SECONDS:
            raise StoragePresignedUrlError(
                "Срок жизни pre-signed URL должен быть положительным.",
                expires_in_seconds=expires_in_seconds,
                details={
                    "operation": "validate_expires_in_seconds",
                    "min_expires_in_seconds": StorageConstants.S3_PRESIGNED_MIN_EXPIRES_IN_SECONDS,
                },
            )

        if expires_in_seconds > StorageConstants.S3_PRESIGNED_MAX_EXPIRES_IN_SECONDS:
            raise StoragePresignedUrlError(
                "Срок жизни pre-signed URL превышает максимально допустимый.",
                expires_in_seconds=expires_in_seconds,
                details={
                    "operation": "validate_expires_in_seconds",
                    "max_expires_in_seconds": StorageConstants.S3_PRESIGNED_MAX_EXPIRES_IN_SECONDS,
                },
            )

        return expires_in_seconds

    @staticmethod
    def validate_upload_id(upload_id: str) -> str:
        """Проверяет идентификатор multipart upload.

        Args:
            upload_id: Исходный идентификатор multipart upload.

        Returns:
            Нормализованный идентификатор multipart upload.

        Raises:
            StoragePresignedUrlError: Если upload ID некорректен.
        """

        if not isinstance(upload_id, str):
            raise StoragePresignedUrlError(
                "Идентификатор multipart-загрузки должен быть строкой.",
                details={
                    "operation": "validate_upload_id",
                    "value_type": type(upload_id).__name__,
                },
            )

        normalized_upload_id = upload_id.strip()

        if not normalized_upload_id:
            raise StoragePresignedUrlError(
                "Идентификатор multipart-загрузки не может быть пустым.",
                details={
                    "operation": "validate_upload_id",
                },
            )

        return normalized_upload_id

    def validate_part_number(self, part_number: int) -> int:
        """Проверяет номер части multipart upload.

        Args:
            part_number: Номер части multipart upload.

        Returns:
            Проверенный номер части.

        Raises:
            StoragePresignedUrlError: Если номер части некорректен.
        """

        if not isinstance(part_number, int):
            raise StoragePresignedUrlError(
                "Номер части multipart-загрузки должен быть целым числом.",
                details={
                    "operation": "validate_part_number",
                    "value": part_number,
                    "value_type": type(part_number).__name__,
                },
            )

        if isinstance(part_number, bool):
            raise StoragePresignedUrlError(
                "Номер части multipart-загрузки должен быть целым числом, а не bool.",
                details={
                    "operation": "validate_part_number",
                    "part_number": part_number,
                    "value_type": type(part_number).__name__,
                },
            )

        if part_number < StorageConstants.S3_MULTIPART_MIN_PART_NUMBER:
            raise StoragePresignedUrlError(
                "Номер части multipart-загрузки должен быть положительным.",
                details={
                    "operation": "validate_part_number",
                    "part_number": part_number,
                    "min_part_number": StorageConstants.S3_MULTIPART_MIN_PART_NUMBER,
                },
            )

        if part_number > StorageConstants.S3_MULTIPART_MAX_PART_NUMBER:
            raise StoragePresignedUrlError(
                "Номер части multipart-загрузки превышает максимально допустимое значение.",
                details={
                    "operation": "validate_part_number",
                    "part_number": part_number,
                    "max_part_number": StorageConstants.S3_MULTIPART_MAX_PART_NUMBER,
                },
            )

        return part_number

    def validate_size_range(
        self,
        *,
        min_size_bytes: int | None,
        max_size_bytes: int | None,
    ) -> None:
        """Проверяет ограничения размера для POST policy.

        Args:
            min_size_bytes: Минимальный допустимый размер объекта.
            max_size_bytes: Максимальный допустимый размер объекта.

        Returns:
            ``None``.

        Raises:
            StoragePresignedUrlError: Если диапазон размера некорректен.
        """

        if min_size_bytes is not None:
            if not isinstance(min_size_bytes, int) or isinstance(
                min_size_bytes,
                bool,
            ):
                raise StoragePresignedUrlError(
                    "Минимальный размер POST policy должен быть целым числом.",
                    details={
                        "operation": "validate_size_range",
                        "value": min_size_bytes,
                        "value_type": type(min_size_bytes).__name__,
                    },
                )

            if min_size_bytes < 0:
                raise StoragePresignedUrlError(
                    "Минимальный размер POST policy не может быть отрицательным.",
                    details={
                        "operation": "validate_size_range",
                        "min_size_bytes": min_size_bytes,
                    },
                )

        if max_size_bytes is not None:
            if not isinstance(max_size_bytes, int) or isinstance(
                max_size_bytes,
                bool,
            ):
                raise StoragePresignedUrlError(
                    "Максимальный размер POST policy должен быть целым числом.",
                    details={
                        "operation": "validate_size_range",
                        "value": max_size_bytes,
                        "value_type": type(max_size_bytes).__name__,
                    },
                )

            if max_size_bytes <= 0:
                raise StoragePresignedUrlError(
                    "Максимальный размер POST policy должен быть положительным.",
                    details={
                        "operation": "validate_size_range",
                        "max_size_bytes": max_size_bytes,
                    },
                )

            if max_size_bytes > StorageConstants.S3_POST_POLICY_MAX_OBJECT_SIZE_BYTES:
                raise StoragePresignedUrlError(
                    "Максимальный размер POST policy превышает допустимое значение.",
                    details={
                        "operation": "validate_size_range",
                        "max_size_bytes": max_size_bytes,
                        "max_allowed_size_bytes": StorageConstants.S3_POST_POLICY_MAX_OBJECT_SIZE_BYTES,
                    },
                )

        if (
            min_size_bytes is not None
            and max_size_bytes is not None
            and min_size_bytes > max_size_bytes
        ):
            raise StoragePresignedUrlError(
                "Минимальный размер POST policy не может быть больше максимального.",
                details={
                    "operation": "validate_size_range",
                    "min_size_bytes": min_size_bytes,
                    "max_size_bytes": max_size_bytes,
                },
            )

    @staticmethod
    def normalize_response_headers(
        response_headers: dict[str, str] | None,
    ) -> dict[str, str]:
        """Нормализует response headers для pre-signed GET URL.

        Args:
            response_headers: Исходные response headers.

        Returns:
            Нормализованный словарь response headers.

        Raises:
            StoragePresignedUrlError: Если headers переданы в некорректном
                формате.
        """

        if response_headers is None:
            return {}

        if not isinstance(response_headers, dict):
            raise StoragePresignedUrlError(
                "Response headers для pre-signed URL должны быть словарём.",
                details={
                    "operation": "normalize_response_headers",
                    "value_type": type(response_headers).__name__,
                },
            )

        normalized_headers: dict[str, str] = {}

        for raw_key, raw_value in response_headers.items():
            key = str(raw_key).strip()
            value = str(raw_value).strip()

            if not key:
                raise StoragePresignedUrlError(
                    "Имя response header не может быть пустым.",
                    details={
                        "operation": "normalize_response_headers",
                    },
                )

            if not value:
                continue

            normalized_headers[key] = value

        return normalized_headers

    @staticmethod
    def normalize_optional_header_value(
        value: str | None,
        *,
        field_name: str,
    ) -> str | None:
        """Нормализует необязательное значение HTTP-заголовка.

        Args:
            value: Исходное значение HTTP-заголовка.
            field_name: Название поля для диагностических details.

        Returns:
            Нормализованное значение или ``None``.

        Raises:
            StoragePresignedUrlError: Если значение заголовка некорректно.
        """

        if value is None:
            return None

        if not isinstance(value, str):
            raise StoragePresignedUrlError(
                "Значение HTTP-заголовка должно быть строкой.",
                details={
                    "operation": "normalize_optional_header_value",
                    "field": field_name,
                    "value_type": type(value).__name__,
                },
            )

        normalized_value = value.strip()

        if not normalized_value:
            return None

        if "\r" in normalized_value or "\n" in normalized_value:
            raise StoragePresignedUrlError(
                "Значение HTTP-заголовка не должно содержать переносы строк.",
                details={
                    "operation": "normalize_optional_header_value",
                    "field": field_name,
                },
            )

        return normalized_value

    def _to_public_url(self, url: str) -> str:
        """Заменяет внутренний host pre-signed URL на публичный.

        MinIO SDK подписывает URL для внутреннего endpoint-а
        (``MINIO_HOST:MINIO_PORT``), который недоступен из браузера. Подпись
        SigV4 включает host, поэтому nginx, проксируя bucket-пути в MinIO,
        обязан восстановить исходный внутренний ``Host``. Тогда подпись
        остаётся валидной, а в браузер уходит публичный origin.

        Если публичный и внутренний endpoint совпадают, например при локальном
        запуске без Docker/nginx, URL возвращается без изменений.

        Args:
            url: Pre-signed URL, сформированный MinIO SDK.

        Returns:
            Pre-signed URL с публичным origin.
        """

        internal_base = self.client.settings.minio_base_url

        if internal_base == self.public_url:
            return url

        if url.startswith(internal_base):
            return self.public_url + url[len(internal_base) :]

        return url

    def _build_post_policy_url(self, bucket: str) -> str:
        """Формирует публичный URL для POST policy.

        Args:
            bucket: Имя bucket.

        Returns:
            URL bucket-а для отправки POST form-data.
        """

        return f"{self.public_url}/{bucket}"

    @staticmethod
    def _build_presigned_url_result(
        *,
        url: str,
        method: StoragePresignedUrlMethod,
        bucket: str,
        object_key: str,
        expires_in_seconds: int,
        headers: dict[str, str] | None = None,
    ) -> StoragePresignedUrl:
        """Создаёт DTO результата генерации pre-signed URL.

        Args:
            url: Сформированный URL.
            method: HTTP-метод URL.
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expires_in_seconds: Срок жизни ссылки в секундах.
            headers: Headers, связанные с URL.

        Returns:
            DTO с pre-signed URL.

        Raises:
            StoragePresignedUrlError: Если MinIO/S3 вернул пустой URL.
        """

        if not isinstance(url, str) or not url.strip():
            raise StoragePresignedUrlError(
                "MinIO/S3 вернул пустой pre-signed URL.",
                bucket=bucket,
                object_key=object_key,
                method=method.value,
                expires_in_seconds=expires_in_seconds,
                details={
                    "operation": "build_presigned_url_result",
                    "value_type": type(url).__name__,
                },
            )

        return StoragePresignedUrl(
            url=url,
            method=method,
            bucket=bucket,
            object_key=object_key,
            expires_in_seconds=expires_in_seconds,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
            headers=headers or {},
        )

    @staticmethod
    def _presigned_error(
        exc: StorageError,
        *,
        bucket: str,
        object_key: str,
        method: StoragePresignedUrlMethod,
        expires_in_seconds: int,
        operation: str,
        details: dict[str, Any] | None = None,
    ) -> StorageError:
        """Преобразует ошибку хранилища в ошибку генерации pre-signed URL.

        Args:
            exc: Исходная ошибка хранилища.
            bucket: Имя bucket.
            object_key: Ключ объекта.
            method: HTTP-метод pre-signed URL.
            expires_in_seconds: Срок жизни ссылки в секундах.
            operation: Название выполняемой операции.
            details: Дополнительные details для итоговой ошибки.

        Returns:
            Уточнённая ошибка хранилища.
        """

        if isinstance(exc, StorageConnectionError):
            return exc

        if isinstance(exc, StoragePresignedUrlError):
            return exc

        merged_details = dict(exc.details)
        merged_details.setdefault("reason", exc.message)
        merged_details["operation"] = operation

        if details:
            merged_details.update(details)

        return StoragePresignedUrlError(
            "Не удалось сформировать предварительно подписанную ссылку.",
            bucket=bucket,
            object_key=object_key,
            method=method.value,
            expires_in_seconds=expires_in_seconds,
            details=merged_details,
            cause=exc,
        )
