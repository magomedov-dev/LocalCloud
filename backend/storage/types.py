from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from storage.exceptions import StorageObjectError


class StorageChecksumAlgorithm(StrEnum):
    """Поддерживаемые алгоритмы контрольной суммы объекта."""

    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    SHA512 = "sha512"


class StoragePresignedUrlMethod(StrEnum):
    """HTTP-метод доступа для предварительно подписанный URL."""

    GET = "GET"
    PUT = "PUT"
    POST = "POST"
    DELETE = "DELETE"


class StorageObjectVisibility(StrEnum):
    """Видимость объекта в хранилище."""

    PRIVATE = "private"


class StorageObjectStatus(StrEnum):
    """Состояние физического объекта в хранилище."""

    PENDING = "pending"
    AVAILABLE = "available"
    MISSING = "missing"
    CORRUPTED = "corrupted"
    DELETING = "deleting"
    DELETED = "deleted"


class StorageMultipartUploadStatus(StrEnum):
    """Состояние multipart upload-сессии на уровне хранилища."""

    INITIATED = "initiated"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"
    EXPIRED = "expired"


class StorageIntegrityProblemType(StrEnum):
    """Тип проблемы, обнаруженной при проверке целостности объекта."""

    OBJECT_NOT_FOUND = "object_not_found"
    SIZE_MISMATCH = "size_mismatch"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    METADATA_MISMATCH = "metadata_mismatch"
    OBJECT_STATUS_MISMATCH = "object_status_mismatch"
    UNEXPECTED_ERROR = "unexpected_error"


class StorageHealthState(StrEnum):
    """Состояние объектного хранилища по результатам health-check."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class StorageBaseModel(BaseModel):
    """Базовая модель DTO объектного хранилища."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=False,
        arbitrary_types_allowed=True,
    )


class StorageObjectMetadata(StorageBaseModel):
    """Метаданные объекта в MinIO/S3.

    Основным источником истины остаётся PostgreSQL. Метаданные в S3
    используются как вспомогательный механизм проверки и диагностики.
    """

    values: dict[str, str] = Field(default_factory=dict)

    @field_validator("values", mode="before")
    @classmethod
    def normalize_values(cls, value: Any) -> dict[str, str]:
        """Нормализует входные метаданные к словарю строк.

        Args:
            value: Исходное значение метаданных.

        Returns:
            Нормализованный словарь метаданных.

        Raises:
            TypeError: Если значение метаданных не является словарём.
            ValueError: Если ключ метаданных пустой.
        """

        if value is None:
            return {}

        if isinstance(value, StorageObjectMetadata):
            return dict(value.values)

        if not isinstance(value, Mapping):
            raise TypeError("Метаданные объекта должна быть словарём.")

        normalized: dict[str, str] = {}

        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()

            if not key:
                raise ValueError("Ключ метаданные не может быть пустым.")

            if raw_value is None:
                continue

            normalized[key] = str(raw_value)

        return normalized

    @property
    def has_metadata(self) -> bool:
        """Проверяет наличие метаданных.

        Returns:
            True, если словарь метаданных не пустой.
        """

        return bool(self.values)

    def get(self, key: str, default: str | None = None) -> str | None:
        """Возвращает значение метаданных по ключу.

        Args:
            key: Ключ метаданных.
            default: Значение по умолчанию, если ключ отсутствует.

        Returns:
            Значение метаданных или значение по умолчанию.
        """

        return self.values.get(key, default)

    def to_headers(self, *, prefix: str = "x-amz-meta-") -> dict[str, str]:
        """Возвращает метаданные в виде HTTP-заголовков S3.

        Args:
            prefix: Префикс HTTP-заголовков метаданных.

        Returns:
            Словарь HTTP-заголовков с метаданными.
        """

        return {f"{prefix}{key}": value for key, value in self.values.items()}

    def to_plain_dict(self) -> dict[str, str]:
        """Возвращает метаданные в виде обычного словаря.

        Returns:
            Копия словаря метаданных.
        """

        return dict(self.values)


class StorageBucketInfo(StorageBaseModel):
    """Информация о бакете объектного хранилища."""

    name: str
    created_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Проверяет имя бакета.

        Args:
            value: Имя бакета.

        Returns:
            Валидное имя бакета.

        Raises:
            ValueError: Если имя бакета пустое.
        """

        if not value:
            raise ValueError("Имя бакета не может быть пустым.")
        return value


class StorageObjectInfo(StorageBaseModel):
    """Информация об объекте в MinIO/S3."""

    bucket: str
    object_key: str
    size_bytes: int
    content_type: str | None = None
    etag: str | None = None
    checksum: str | None = None
    checksum_algorithm: StorageChecksumAlgorithm | None = None
    metadata: StorageObjectMetadata = Field(default_factory=StorageObjectMetadata)
    status: StorageObjectStatus = StorageObjectStatus.AVAILABLE
    visibility: StorageObjectVisibility = StorageObjectVisibility.PRIVATE
    last_modified_at: datetime | None = None

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        """Проверяет имя бакета объекта.

        Args:
            value: Имя бакета.

        Returns:
            Валидное имя бакета.

        Raises:
            ValueError: Если имя бакета пустое.
        """

        if not value:
            raise ValueError("Бакет объекта не может быть пустым.")
        return value

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        """Проверяет ключ объекта.

        Args:
            value: Ключ объекта.

        Returns:
            Валидный ключ объекта.

        Raises:
            ValueError: Если ключ объекта пустой.
        """

        if not value:
            raise ValueError("Ключ объекта не может быть пустым.")
        return value

    @field_validator("size_bytes")
    @classmethod
    def validate_size_bytes(cls, value: int) -> int:
        """Проверяет размер объекта.

        Args:
            value: Размер объекта в байтах.

        Returns:
            Валидный размер объекта.

        Raises:
            ValueError: Если размер объекта отрицательный.
        """

        if value < 0:
            raise ValueError("Размер объекта не может быть отрицательным.")
        return value

    @model_validator(mode="after")
    def validate_checksum_pair(self) -> StorageObjectInfo:
        """Проверяет согласованность checksum и checksum_algorithm.

        Returns:
            Текущий объект после успешной проверки.

        Raises:
            ValueError: Если checksum и checksum_algorithm указаны
                несогласованно.
        """

        if self.checksum is None and self.checksum_algorithm is not None:
            raise ValueError(
                "Алгоритм контрольной суммы не может быть указан без значения checksum."
            )

        if self.checksum is not None and self.checksum_algorithm is None:
            raise ValueError("Для checksum необходимо указать checksum_algorithm.")

        return self

    @property
    def has_checksum(self) -> bool:
        """Проверяет наличие контрольной суммы.

        Returns:
            True, если указаны checksum и checksum_algorithm.
        """

        return self.checksum is not None and self.checksum_algorithm is not None

    @property
    def has_metadata(self) -> bool:
        """Проверяет наличие метаданных объекта.

        Returns:
            True, если у объекта есть метаданные.
        """

        return self.metadata.has_metadata

    @property
    def is_available(self) -> bool:
        """Проверяет, доступен ли объект.

        Returns:
            True, если объект имеет статус AVAILABLE.
        """

        return self.status == StorageObjectStatus.AVAILABLE

    @property
    def is_missing(self) -> bool:
        """Проверяет, отсутствует ли объект.

        Returns:
            True, если объект имеет статус MISSING.
        """

        return self.status == StorageObjectStatus.MISSING

    @property
    def is_corrupted(self) -> bool:
        """Проверяет, повреждён ли объект.

        Returns:
            True, если объект имеет статус CORRUPTED.
        """

        return self.status == StorageObjectStatus.CORRUPTED


class StoragePutObjectRequest(StorageBaseModel):
    """Данные для загрузки объекта в MinIO/S3 через backend."""

    bucket: str
    object_key: str
    data: bytes
    content_type: str | None = None
    metadata: StorageObjectMetadata = Field(default_factory=StorageObjectMetadata)

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        """Проверяет имя бакета загрузки.

        Args:
            value: Имя бакета.

        Returns:
            Валидное имя бакета.

        Raises:
            ValueError: Если имя бакета пустое.
        """

        if not value:
            raise ValueError("Бакет загрузки объекта не может быть пустым.")
        return value

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        """Проверяет ключ загружаемого объекта.

        Args:
            value: Ключ объекта.

        Returns:
            Валидный ключ объекта.

        Raises:
            ValueError: Если ключ объекта пустой.
        """

        if not value:
            raise ValueError("Ключ загружаемого объекта не может быть пустым.")
        return value

    @property
    def size_bytes(self) -> int:
        """Возвращает размер загружаемых данных.

        Returns:
            Размер данных в байтах.
        """

        return len(self.data)

    @property
    def has_metadata(self) -> bool:
        """Проверяет наличие метаданных загрузки.

        Returns:
            True, если для объекта переданы метаданные.
        """

        return self.metadata.has_metadata


class StorageUploadPart(StorageBaseModel):
    """Информация о части multipart-загрузки."""

    part_number: int
    etag: str
    size_bytes: int | None = None
    checksum: str | None = None
    uploaded_at: datetime | None = None

    @field_validator("part_number")
    @classmethod
    def validate_part_number(cls, value: int) -> int:
        """Проверяет номер части multipart-загрузки.

        Args:
            value: Номер части.

        Returns:
            Валидный номер части.

        Raises:
            ValueError: Если номер части не положительный.
        """

        if value <= 0:
            raise ValueError(
                "Номер части multipart-загрузки должен быть положительным."
            )
        return value

    @field_validator("etag")
    @classmethod
    def validate_etag(cls, value: str) -> str:
        """Проверяет ETag части multipart-загрузки.

        Args:
            value: ETag части.

        Returns:
            Валидный ETag.

        Raises:
            ValueError: Если ETag пустой.
        """

        if not value:
            raise ValueError("ETag части multipart-загрузки не может быть пустым.")
        return value

    @field_validator("size_bytes")
    @classmethod
    def validate_size_bytes(cls, value: int | None) -> int | None:
        """Проверяет размер части multipart-загрузки.

        Args:
            value: Размер части в байтах.

        Returns:
            Валидный размер части или None.

        Raises:
            ValueError: Если размер части не положительный.
        """

        if value is not None and value <= 0:
            raise ValueError(
                "Размер части multipart-загрузки должен быть положительным."
            )
        return value

    @property
    def has_checksum(self) -> bool:
        """Проверяет наличие контрольной суммы части.

        Returns:
            True, если для части указана контрольная сумма.
        """

        return self.checksum is not None


class StorageMultipartUpload(StorageBaseModel):
    """Информация об инициированной multipart-загрузке."""

    bucket: str
    object_key: str
    upload_id: str
    status: StorageMultipartUploadStatus = StorageMultipartUploadStatus.INITIATED
    metadata: StorageObjectMetadata = Field(default_factory=StorageObjectMetadata)
    created_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        """Проверяет имя бакета multipart-загрузки.

        Args:
            value: Имя бакета.

        Returns:
            Валидное имя бакета.

        Raises:
            ValueError: Если имя бакета пустое.
        """

        if not value:
            raise ValueError("Бакет multipart-загрузки не может быть пустым.")
        return value

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        """Проверяет ключ объекта multipart-загрузки.

        Args:
            value: Ключ объекта.

        Returns:
            Валидный ключ объекта.

        Raises:
            ValueError: Если ключ объекта пустой.
        """

        if not value:
            raise ValueError("Ключ объекта multipart-загрузки не может быть пустым.")
        return value

    @field_validator("upload_id")
    @classmethod
    def validate_upload_id(cls, value: str) -> str:
        """Проверяет идентификатор multipart-загрузки.

        Args:
            value: Идентификатор multipart-загрузки.

        Returns:
            Валидный идентификатор multipart-загрузки.

        Raises:
            ValueError: Если идентификатор multipart-загрузки пустой.
        """

        if not value:
            raise ValueError("Идентификатор multipart-загрузки не может быть пустым.")
        return value

    @property
    def has_metadata(self) -> bool:
        """Проверяет наличие метаданных multipart-загрузки.

        Returns:
            True, если для загрузки указаны метаданные.
        """

        return self.metadata.has_metadata

    @property
    def is_finished(self) -> bool:
        """Проверяет, завершена ли multipart-загрузка.

        Returns:
            True, если загрузка завершена, отменена, провалена или истекла.
        """

        return self.status in {
            StorageMultipartUploadStatus.COMPLETED,
            StorageMultipartUploadStatus.ABORTED,
            StorageMultipartUploadStatus.FAILED,
            StorageMultipartUploadStatus.EXPIRED,
        }


class StorageCompleteMultipartUploadRequest(StorageBaseModel):
    """Данные для завершения multipart-загрузки."""

    bucket: str
    object_key: str
    upload_id: str
    parts: list[StorageUploadPart]

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        """Проверяет имя бакета завершаемой multipart-загрузки.

        Args:
            value: Имя бакета.

        Returns:
            Валидное имя бакета.

        Raises:
            ValueError: Если имя бакета пустое.
        """

        if not value:
            raise ValueError(
                "Бакет завершения multipart-загрузки не может быть пустым."
            )
        return value

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        """Проверяет ключ объекта завершаемой multipart-загрузки.

        Args:
            value: Ключ объекта.

        Returns:
            Валидный ключ объекта.

        Raises:
            ValueError: Если ключ объекта пустой.
        """

        if not value:
            raise ValueError(
                "Ключ объекта завершения multipart-загрузки не может быть пустым."
            )
        return value

    @field_validator("upload_id")
    @classmethod
    def validate_upload_id(cls, value: str) -> str:
        """Проверяет идентификатор завершаемой multipart-загрузки.

        Args:
            value: Идентификатор multipart-загрузки.

        Returns:
            Валидный идентификатор multipart-загрузки.

        Raises:
            ValueError: Если идентификатор multipart-загрузки пустой.
        """

        if not value:
            raise ValueError(
                "Идентификатор завершаемой multipart-загрузки не может быть пустым."
            )
        return value

    @field_validator("parts")
    @classmethod
    def validate_parts(cls, value: list[StorageUploadPart]) -> list[StorageUploadPart]:
        """Проверяет список частей multipart-загрузки.

        Args:
            value: Список частей multipart-загрузки.

        Returns:
            Список частей, отсортированный по номеру части.

        Raises:
            ValueError: Если список частей пустой или содержит повторяющиеся
                номера частей.
        """

        if not value:
            raise ValueError(
                "Для завершения multipart-загрузки нужен хотя бы один part."
            )

        part_numbers = [part.part_number for part in value]

        if len(part_numbers) != len(set(part_numbers)):
            raise ValueError("Номера частей multipart-загрузки не должны повторяться.")

        return sorted(value, key=lambda part: part.part_number)

    @property
    def parts_count(self) -> int:
        """Возвращает количество частей multipart-загрузки.

        Returns:
            Количество частей.
        """

        return len(self.parts)


class StoragePresignedUrl(StorageBaseModel):
    """Предварительно подписанный URL для доступа к объекту."""

    url: str
    method: StoragePresignedUrlMethod
    bucket: str
    object_key: str
    expires_in_seconds: int
    expires_at: datetime | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Проверяет предварительно подписанный URL.

        Args:
            value: URL для проверки.

        Returns:
            Валидный URL.

        Raises:
            ValueError: Если URL пустой.
        """

        if not value:
            raise ValueError("Предварительно подписанный URL не может быть пустым.")
        return value

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        """Проверяет имя бакета для предварительно подписанного URL.

        Args:
            value: Имя бакета.

        Returns:
            Валидное имя бакета.

        Raises:
            ValueError: Если имя бакета пустое.
        """

        if not value:
            raise ValueError(
                "Бакет предварительно подписанного URL не может быть пустым."
            )
        return value

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        """Проверяет ключ объекта для предварительно подписанного URL.

        Args:
            value: Ключ объекта.

        Returns:
            Валидный ключ объекта.

        Raises:
            ValueError: Если ключ объекта пустой.
        """

        if not value:
            raise ValueError(
                "Ключ объекта предварительно подписанного URL не может быть пустым."
            )
        return value

    @field_validator("expires_in_seconds")
    @classmethod
    def validate_expires_in_seconds(cls, value: int) -> int:
        """Проверяет время жизни предварительно подписанного URL.

        Args:
            value: Время жизни URL в секундах.

        Returns:
            Валидное время жизни URL.

        Raises:
            ValueError: Если время жизни URL не положительное.
        """

        if value <= 0:
            raise ValueError(
                "Время жизни предварительно подписанного URL должно быть положительным."
            )
        return value

    @field_validator("headers", mode="before")
    @classmethod
    def normalize_headers(cls, value: Any) -> dict[str, str]:
        """Нормализует HTTP-заголовки предварительно подписанного URL.

        Args:
            value: Исходные HTTP-заголовки.

        Returns:
            Нормализованный словарь HTTP-заголовков.

        Raises:
            TypeError: Если заголовки не являются словарём.
        """

        if value is None:
            return {}

        if not isinstance(value, Mapping):
            raise TypeError(
                "Заголовки предварительно подписанного URL должны быть словарём."
            )

        return {
            str(header_name).strip(): str(header_value)
            for header_name, header_value in value.items()
            if str(header_name).strip()
        }

    @property
    def expires_in(self) -> int:
        """Возвращает время жизни URL.

        Returns:
            Время жизни URL в секундах.
        """

        return self.expires_in_seconds

    @property
    def is_download_url(self) -> bool:
        """Проверяет, предназначен ли URL для скачивания объекта.

        Returns:
            True, если URL использует GET-метод.
        """

        return self.method == StoragePresignedUrlMethod.GET

    @property
    def is_upload_url(self) -> bool:
        """Проверяет, предназначен ли URL для загрузки объекта.

        Returns:
            True, если URL использует PUT- или POST-метод.
        """

        return self.method in {
            StoragePresignedUrlMethod.PUT,
            StoragePresignedUrlMethod.POST,
        }


class StoragePresignedUploadPartUrl(StorageBaseModel):
    """Предварительно подписанный URL для загрузки части multipart upload."""

    part_number: int
    url: StoragePresignedUrl

    @field_validator("part_number")
    @classmethod
    def validate_part_number(cls, value: int) -> int:
        """Проверяет номер части для предварительно подписанного URL.

        Args:
            value: Номер части multipart-загрузки.

        Returns:
            Валидный номер части.

        Raises:
            ValueError: Если номер части не положительный.
        """

        if value <= 0:
            raise ValueError(
                "Номер части предварительно подписанного URL должен быть положительным."
            )
        return value


class StorageDownloadResult(StorageBaseModel):
    """Результат получения объекта из хранилища."""

    bucket: str
    object_key: str
    data: bytes
    size_bytes: int
    content_type: str | None = None
    etag: str | None = None
    metadata: StorageObjectMetadata = Field(default_factory=StorageObjectMetadata)

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        """Проверяет имя бакета результата скачивания.

        Args:
            value: Имя бакета.

        Returns:
            Валидное имя бакета.

        Raises:
            ValueError: Если имя бакета пустое.
        """

        if not value:
            raise ValueError("Бакет результата скачивания не может быть пустым.")
        return value

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        """Проверяет ключ скачанного объекта.

        Args:
            value: Ключ объекта.

        Returns:
            Валидный ключ объекта.

        Raises:
            ValueError: Если ключ объекта пустой.
        """

        if not value:
            raise ValueError("Ключ объекта результата скачивания не может быть пустым.")
        return value

    @field_validator("size_bytes")
    @classmethod
    def validate_size_bytes(cls, value: int) -> int:
        """Проверяет размер скачанного объекта.

        Args:
            value: Размер объекта в байтах.

        Returns:
            Валидный размер объекта.

        Raises:
            ValueError: Если размер объекта отрицательный.
        """

        if value < 0:
            raise ValueError("Размер скачанного объекта не может быть отрицательным.")
        return value

    @property
    def is_success(self) -> bool:
        """Проверяет успешность скачивания.

        Returns:
            True, если размер данных совпадает с ожидаемым размером.
        """

        return len(self.data) == self.size_bytes

    @property
    def has_metadata(self) -> bool:
        """Проверяет наличие метаданных в результате скачивания.

        Returns:
            True, если результат содержит метаданные.
        """

        return self.metadata.has_metadata


class StorageDeleteResult(StorageBaseModel):
    """Результат удаления объекта из хранилища."""

    bucket: str
    object_key: str
    deleted: bool
    version_id: str | None = None

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        """Проверяет имя бакета результата удаления.

        Args:
            value: Имя бакета.

        Returns:
            Валидное имя бакета.

        Raises:
            ValueError: Если имя бакета пустое.
        """

        if not value:
            raise ValueError("Бакет результата удаления не может быть пустым.")
        return value

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        """Проверяет ключ удаляемого объекта.

        Args:
            value: Ключ объекта.

        Returns:
            Валидный ключ объекта.

        Raises:
            ValueError: Если ключ объекта пустой.
        """

        if not value:
            raise ValueError("Ключ удаляемого объекта не может быть пустым.")
        return value

    @property
    def is_success(self) -> bool:
        """Проверяет успешность удаления.

        Returns:
            True, если объект был успешно удалён.
        """

        return self.deleted


class StorageCopyResult(StorageBaseModel):
    """Результат копирования объекта внутри хранилища."""

    source_bucket: str
    source_object_key: str
    destination_bucket: str
    destination_object_key: str
    etag: str | None = None
    copied_at: datetime | None = None

    @field_validator(
        "source_bucket",
        "source_object_key",
        "destination_bucket",
        "destination_object_key",
    )
    @classmethod
    def validate_required_string(cls, value: str) -> str:
        """Проверяет обязательное строковое поле результата копирования.

        Args:
            value: Значение обязательного строкового поля.

        Returns:
            Валидное строковое значение.

        Raises:
            ValueError: Если значение пустое.
        """

        if not value:
            raise ValueError("Поля результата копирования не могут быть пустыми.")
        return value


class StorageIntegrityStatus(StorageBaseModel):
    """Результат отдельной проверки целостности."""

    is_success: bool
    problem_type: StorageIntegrityProblemType | None = None
    message: str | None = None
    expected: Any | None = None
    actual: Any | None = None

    @model_validator(mode="after")
    def validate_problem_type(self) -> StorageIntegrityStatus:
        """Проверяет наличие типа проблемы для неуспешной проверки.

        Returns:
            Текущий объект после успешной проверки.

        Raises:
            ValueError: Если проверка неуспешна, но problem_type не указан.
        """

        if not self.is_success and self.problem_type is None:
            raise ValueError(
                "Для неуспешной проверки целостности нужно указать problem_type."
            )
        return self

    @property
    def has_problem(self) -> bool:
        """Проверяет наличие проблемы целостности.

        Returns:
            True, если проверка выявила проблему.
        """

        return not self.is_success


class StorageIntegrityReport(StorageBaseModel):
    """Итоговый отчёт проверки целостности объекта."""

    bucket: str
    object_key: str
    checked_at: datetime
    object_exists: bool
    size_status: StorageIntegrityStatus | None = None
    checksum_status: StorageIntegrityStatus | None = None
    metadata_status: StorageIntegrityStatus | None = None
    object_status: StorageIntegrityStatus | None = None
    problems: list[StorageIntegrityStatus] = Field(default_factory=list)

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        """Проверяет имя бакета отчёта целостности.

        Args:
            value: Имя бакета.

        Returns:
            Валидное имя бакета.

        Raises:
            ValueError: Если имя бакета пустое.
        """

        if not value:
            raise ValueError("Бакет отчёта целостности не может быть пустым.")
        return value

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        """Проверяет ключ объекта отчёта целостности.

        Args:
            value: Ключ объекта.

        Returns:
            Валидный ключ объекта.

        Raises:
            ValueError: Если ключ объекта пустой.
        """

        if not value:
            raise ValueError("Ключ объекта отчёта целостности не может быть пустым.")
        return value

    @model_validator(mode="after")
    def normalize_problems(self) -> StorageIntegrityReport:
        """Формирует итоговый список проблем целостности.

        В список добавляются проблемы из отдельных проверок, если они ещё
        не были переданы явно.

        Returns:
            Текущий отчёт с нормализованным списком проблем.
        """

        derived_problems = [
            status
            for status in (
                self.size_status,
                self.checksum_status,
                self.metadata_status,
                self.object_status,
            )
            if status is not None and status.has_problem
        ]

        explicit_problems = list(self.problems)
        known_problem_keys = {
            (
                problem.problem_type,
                problem.message,
                repr(problem.expected),
                repr(problem.actual),
            )
            for problem in explicit_problems
        }

        for problem in derived_problems:
            problem_key = (
                problem.problem_type,
                problem.message,
                repr(problem.expected),
                repr(problem.actual),
            )

            if problem_key not in known_problem_keys:
                explicit_problems.append(problem)

        object.__setattr__(self, "problems", explicit_problems)
        return self

    @property
    def is_success(self) -> bool:
        """Проверяет успешность отчёта целостности.

        Returns:
            True, если объект существует и проблем не найдено.
        """

        return self.object_exists and not self.problems

    @property
    def has_problems(self) -> bool:
        """Проверяет наличие проблем в отчёте.

        Returns:
            True, если отчёт содержит хотя бы одну проблему.
        """

        return bool(self.problems)


class StorageHealthStatus(StorageBaseModel):
    """Результат проверки работоспособности объектного хранилища."""

    state: StorageHealthState
    checked_at: datetime
    connection_ok: bool
    bucket_access_ok: bool | None = None
    read_write_ok: bool | None = None
    latency_ms: float | None = None
    latency_threshold_ms: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("latency_ms")
    @classmethod
    def validate_latency_ms(cls, value: float | None) -> float | None:
        """Проверяет задержку объектного хранилища.

        Args:
            value: Задержка в миллисекундах.

        Returns:
            Валидная задержка или None.

        Raises:
            ValueError: Если задержка отрицательная.
        """

        if value is not None and value < 0:
            raise ValueError("Задержка хранилища не может быть отрицательной.")
        return value

    @field_validator("latency_threshold_ms")
    @classmethod
    def validate_latency_threshold_ms(cls, value: float | None) -> float | None:
        """Проверяет порог задержки объектного хранилища.

        Args:
            value: Порог задержки в миллисекундах.

        Returns:
            Валидный порог задержки или None.

        Raises:
            ValueError: Если порог задержки не положительный.
        """

        if value is not None and value <= 0:
            raise ValueError("Порог задержки хранилища должен быть положительным.")
        return value

    @property
    def is_healthy(self) -> bool:
        """Проверяет штатное состояние хранилища.

        Returns:
            True, если хранилище имеет состояние HEALTHY.
        """

        return self.state == StorageHealthState.HEALTHY

    @property
    def is_degraded(self) -> bool:
        """Проверяет деградированное состояние хранилища.

        Returns:
            True, если хранилище имеет состояние DEGRADED.
        """

        return self.state == StorageHealthState.DEGRADED

    @property
    def is_unhealthy(self) -> bool:
        """Проверяет неисправное состояние хранилища.

        Returns:
            True, если хранилище имеет состояние UNHEALTHY.
        """

        return self.state == StorageHealthState.UNHEALTHY

    @property
    def is_success(self) -> bool:
        """Проверяет успешность health-check.

        Returns:
            True, если хранилище работает штатно.
        """

        return self.is_healthy


class StorageObjectDeleteResult:
    """Результат массового удаления объектов.

    Класс не наследуется от Pydantic-модели, чтобы не смешивать DTO-слой
    с инфраструктурным результатом операции массового удаления.
    """

    def __init__(
        self,
        *,
        deleted_count: int,
        errors: list[StorageObjectError] | None = None,
    ) -> None:
        """Создаёт результат массового удаления объектов.

        Args:
            deleted_count: Количество удалённых объектов.
            errors: Список ошибок, возникших при удалении.
        """

        self.deleted_count = deleted_count
        self.errors = errors or []

    @property
    def is_success(self) -> bool:
        """Проверяет успешность массового удаления.

        Returns:
            True, если массовое удаление прошло без ошибок.
        """

        return not self.errors

    @property
    def has_errors(self) -> bool:
        """Проверяет наличие ошибок массового удаления.

        Returns:
            True, если при удалении возникли ошибки.
        """

        return bool(self.errors)
