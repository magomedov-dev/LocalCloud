from __future__ import annotations

from typing import Any


class StorageError(Exception):
    """Базовое исключение для всех ошибок объектного хранилища.

    Args:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Операция с объектным хранилищем не удалась.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует базовую ошибку объектного хранилища.

        Args:
            message: Человекочитаемое описание ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        self.message = message
        self.details = details.copy() if details else {}
        self.cause = cause

        super().__init__(self.message)

        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        """Возвращает строковое представление ошибки.

        Returns:
            Сообщение об ошибке с деталями, если они указаны.
        """

        if not self.details:
            return self.message
        return f"{self.message} Details: {self.details}"

    def to_dict(self) -> dict[str, Any]:
        """Преобразует исключение в словарь.

        Returns:
            Словарь с типом ошибки, сообщением, деталями и причиной.
        """

        payload: dict[str, Any] = {
            "error": self.__class__.__name__,
            "message": self.message,
        }

        if self.details:
            payload["details"] = self.details

        if self.cause is not None:
            payload["cause"] = self.cause.__class__.__name__

        return payload


class StorageCapacityError(StorageError):
    """Ошибка определения или валидации ёмкости хранилища.

    Возникает, когда невозможно безопасно определить пул хранилища (например,
    MinIO admin API недоступен и явная ёмкость не задана в конфиге) или когда
    заданная в конфиге ёмкость превышает физический объём диска.
    """

    def __init__(
        self,
        message: str = "Не удалось определить ёмкость объектного хранилища.",
        *,
        configured_bytes: int | None = None,
        physical_bytes: int | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку ёмкости хранилища.

        Args:
            message: Человекочитаемое описание ошибки.
            configured_bytes: Заданная в конфиге ёмкость пула в байтах.
            physical_bytes: Физическая ёмкость диска по данным MinIO в байтах.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged: dict[str, Any] = dict(details or {})
        if configured_bytes is not None:
            merged["configured_bytes"] = configured_bytes
        if physical_bytes is not None:
            merged["physical_bytes"] = physical_bytes
        super().__init__(message, details=merged, cause=cause)


class StorageConnectionError(StorageError):
    """Ошибка подключения к объектному хранилищу.

    Args:
        message: Человекочитаемое описание ошибки.
        endpoint: Endpoint объектного хранилища.
        secure: Признак использования защищённого соединения.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Не удалось подключиться к объектному хранилищу.",
        *,
        endpoint: str | None = None,
        secure: bool | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку подключения к объектному хранилищу.

        Args:
            message: Человекочитаемое описание ошибки.
            endpoint: Endpoint объектного хранилища.
            secure: Признак использования защищённого соединения.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if endpoint is not None:
            merged_details["endpoint"] = endpoint
        if secure is not None:
            merged_details["secure"] = secure

        super().__init__(message, details=merged_details, cause=cause)


class StorageAuthenticationError(StorageError):
    """Ошибка аутентификации или авторизации в MinIO/S3.

    Args:
        message: Человекочитаемое описание ошибки.
        access_key: Ключ доступа, связанный с ошибкой.
        operation: Название операции, при которой возникла ошибка.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Ошибка аутентификации в объектном хранилище.",
        *,
        access_key: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку аутентификации или авторизации.

        Args:
            message: Человекочитаемое описание ошибки.
            access_key: Ключ доступа, связанный с ошибкой.
            operation: Название операции, при которой возникла ошибка.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if access_key is not None:
            merged_details["access_key"] = access_key
        if operation is not None:
            merged_details["operation"] = operation

        super().__init__(message, details=merged_details, cause=cause)


class StoragePermissionDeniedError(StorageAuthenticationError):
    """Ошибка отказа в доступе к операции объектного хранилища.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Имя бакета, связанного с ошибкой.
        object_key: Ключ объекта, связанного с ошибкой.
        operation: Название операции, при которой возникла ошибка.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Недостаточно прав для выполнения операции в объектном хранилище.",
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку отказа в доступе.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Имя бакета, связанного с ошибкой.
            object_key: Ключ объекта, связанного с ошибкой.
            operation: Название операции, при которой возникла ошибка.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if bucket is not None:
            merged_details["bucket"] = bucket
        if object_key is not None:
            merged_details["object_key"] = object_key

        super().__init__(
            message,
            operation=operation,
            details=merged_details,
            cause=cause,
        )


class StorageTimeoutError(StorageError):
    """Ошибка превышения времени выполнения операции с хранилищем.

    Args:
        message: Человекочитаемое описание ошибки.
        operation: Название операции, при которой возникла ошибка.
        timeout_seconds: Значение timeout в секундах.
        bucket: Имя бакета, связанного с ошибкой.
        object_key: Ключ объекта, связанного с ошибкой.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Время выполнения операции с объектным хранилищем истекло.",
        *,
        operation: str | None = None,
        timeout_seconds: float | None = None,
        bucket: str | None = None,
        object_key: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку превышения времени выполнения операции.

        Args:
            message: Человекочитаемое описание ошибки.
            operation: Название операции, при которой возникла ошибка.
            timeout_seconds: Значение timeout в секундах.
            bucket: Имя бакета, связанного с ошибкой.
            object_key: Ключ объекта, связанного с ошибкой.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if operation is not None:
            merged_details["operation"] = operation
        if timeout_seconds is not None:
            merged_details["timeout_seconds"] = timeout_seconds
        if bucket is not None:
            merged_details["bucket"] = bucket
        if object_key is not None:
            merged_details["object_key"] = object_key

        super().__init__(message, details=merged_details, cause=cause)


class StorageHealthCheckError(StorageError):
    """Ошибка проверки работоспособности объектного хранилища.

    Args:
        message: Человекочитаемое описание ошибки.
        component: Компонент, на котором завершилась проверка.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Проверка работоспособности объектного хранилища не пройдена.",
        *,
        component: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку health-check объектного хранилища.

        Args:
            message: Человекочитаемое описание ошибки.
            component: Компонент, на котором завершилась проверка.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if component is not None:
            merged_details["component"] = component

        super().__init__(message, details=merged_details, cause=cause)


class StorageBucketError(StorageError):
    """Ошибка операции с бакетом объектного хранилища.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Имя бакета, связанного с ошибкой.
        operation: Название операции, при которой возникла ошибка.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Операция с bucket объектного хранилища не удалась.",
        *,
        bucket: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку операции с бакетом.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Имя бакета, связанного с ошибкой.
            operation: Название операции, при которой возникла ошибка.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if bucket is not None:
            merged_details["bucket"] = bucket
        if operation is not None:
            merged_details["operation"] = operation

        super().__init__(message, details=merged_details, cause=cause)


class StorageBucketNotFoundError(StorageBucketError):
    """Ошибка отсутствия бакета в объектном хранилище.

    Args:
        bucket: Имя отсутствующего бакета.
        message: Человекочитаемое описание ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        bucket: str,
        *,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку отсутствия бакета.

        Args:
            bucket: Имя отсутствующего бакета.
            message: Человекочитаемое описание ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        default_message = f"Бакет '{bucket}' не найден в объектном хранилище."

        super().__init__(
            message or default_message,
            bucket=bucket,
            operation="get_bucket",
            details=details,
            cause=cause,
        )


class StorageBucketAlreadyExistsError(StorageBucketError):
    """Ошибка создания бакета, который уже существует.

    Args:
        bucket: Имя бакета, который уже существует.
        message: Человекочитаемое описание ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        bucket: str,
        *,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку уже существующего бакета.

        Args:
            bucket: Имя бакета, который уже существует.
            message: Человекочитаемое описание ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        default_message = f"Бакет '{bucket}' уже существует в объектном хранилище."

        super().__init__(
            message or default_message,
            bucket=bucket,
            operation="create_bucket",
            details=details,
            cause=cause,
        )


class StorageObjectError(StorageError):
    """Ошибка операции с объектом в MinIO/S3.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Имя бакета, связанного с объектом.
        object_key: Ключ объекта, связанного с ошибкой.
        operation: Название операции, при которой возникла ошибка.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Операция с объектом хранилища не удалась.",
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку операции с объектом.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Имя бакета, связанного с объектом.
            object_key: Ключ объекта, связанного с ошибкой.
            operation: Название операции, при которой возникла ошибка.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if bucket is not None:
            merged_details["bucket"] = bucket
        if object_key is not None:
            merged_details["object_key"] = object_key
        if operation is not None:
            merged_details["operation"] = operation

        super().__init__(message, details=merged_details, cause=cause)


class StorageObjectNotFoundError(StorageObjectError):
    """Ошибка отсутствия объекта в MinIO/S3.

    Args:
        bucket: Имя бакета, в котором ожидался объект.
        object_key: Ключ отсутствующего объекта.
        message: Человекочитаемое описание ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        *,
        bucket: str,
        object_key: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку отсутствия объекта.

        Args:
            bucket: Имя бакета, в котором ожидался объект.
            object_key: Ключ отсутствующего объекта.
            message: Человекочитаемое описание ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        default_message = "Объект не найден в объектном хранилище."

        super().__init__(
            message or default_message,
            bucket=bucket,
            object_key=object_key,
            operation="get_object",
            details=details,
            cause=cause,
        )


class StorageObjectAlreadyExistsError(StorageObjectError):
    """Ошибка создания объекта, который уже существует.

    Args:
        bucket: Имя бакета, в котором находится объект.
        object_key: Ключ уже существующего объекта.
        message: Человекочитаемое описание ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        *,
        bucket: str,
        object_key: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку уже существующего объекта.

        Args:
            bucket: Имя бакета, в котором находится объект.
            object_key: Ключ уже существующего объекта.
            message: Человекочитаемое описание ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        default_message = "Объект уже существует в объектном хранилище."

        super().__init__(
            message or default_message,
            bucket=bucket,
            object_key=object_key,
            operation="put_object",
            details=details,
            cause=cause,
        )


class StorageUploadError(StorageObjectError):
    """Ошибка загрузки объекта в MinIO/S3.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Имя бакета, в который загружался объект.
        object_key: Ключ загружаемого объекта.
        upload_id: Идентификатор upload-сессии.
        operation: Название операции, при которой возникла ошибка.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Загрузка объекта в хранилище не удалась.",
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        upload_id: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку загрузки объекта.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Имя бакета, в который загружался объект.
            object_key: Ключ загружаемого объекта.
            upload_id: Идентификатор upload-сессии.
            operation: Название операции, при которой возникла ошибка.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if upload_id is not None:
            merged_details["upload_id"] = upload_id

        super().__init__(
            message,
            bucket=bucket,
            object_key=object_key,
            operation=operation or "upload",
            details=merged_details,
            cause=cause,
        )


class StorageDownloadError(StorageObjectError):
    """Ошибка скачивания объекта из MinIO/S3.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Имя бакета, из которого скачивался объект.
        object_key: Ключ скачиваемого объекта.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Скачивание объекта из хранилища не удалось.",
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку скачивания объекта.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Имя бакета, из которого скачивался объект.
            object_key: Ключ скачиваемого объекта.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        super().__init__(
            message,
            bucket=bucket,
            object_key=object_key,
            operation="download",
            details=details,
            cause=cause,
        )


class StorageDeleteError(StorageObjectError):
    """Ошибка удаления объекта из MinIO/S3.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Имя бакета, из которого удалялся объект.
        object_key: Ключ удаляемого объекта.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Удаление объекта из хранилища не удалось.",
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку удаления объекта.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Имя бакета, из которого удалялся объект.
            object_key: Ключ удаляемого объекта.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        super().__init__(
            message,
            bucket=bucket,
            object_key=object_key,
            operation="delete",
            details=details,
            cause=cause,
        )


class StorageCopyError(StorageObjectError):
    """Ошибка копирования объекта внутри MinIO/S3.

    Args:
        message: Человекочитаемое описание ошибки.
        source_bucket: Имя исходного бакета.
        source_object_key: Ключ исходного объекта.
        destination_bucket: Имя целевого бакета.
        destination_object_key: Ключ целевого объекта.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Копирование объекта в хранилище не удалось.",
        *,
        source_bucket: str | None = None,
        source_object_key: str | None = None,
        destination_bucket: str | None = None,
        destination_object_key: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку копирования объекта.

        Args:
            message: Человекочитаемое описание ошибки.
            source_bucket: Имя исходного бакета.
            source_object_key: Ключ исходного объекта.
            destination_bucket: Имя целевого бакета.
            destination_object_key: Ключ целевого объекта.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if source_bucket is not None:
            merged_details["source_bucket"] = source_bucket
        if source_object_key is not None:
            merged_details["source_object_key"] = source_object_key
        if destination_bucket is not None:
            merged_details["destination_bucket"] = destination_bucket
        if destination_object_key is not None:
            merged_details["destination_object_key"] = destination_object_key

        super().__init__(
            message,
            bucket=destination_bucket,
            object_key=destination_object_key,
            operation="copy",
            details=merged_details,
            cause=cause,
        )


class StorageMultipartUploadError(StorageUploadError):
    """Ошибка multipart-загрузки объекта в MinIO/S3.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Имя бакета, в который загружался объект.
        object_key: Ключ загружаемого объекта.
        upload_id: Идентификатор multipart upload-сессии.
        part_number: Номер части multipart-загрузки.
        operation: Название операции, при которой возникла ошибка.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Multipart-загрузка объекта не удалась.",
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        upload_id: str | None = None,
        part_number: int | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку multipart-загрузки объекта.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Имя бакета, в который загружался объект.
            object_key: Ключ загружаемого объекта.
            upload_id: Идентификатор multipart upload-сессии.
            part_number: Номер части multipart-загрузки.
            operation: Название операции, при которой возникла ошибка.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if part_number is not None:
            merged_details["part_number"] = part_number

        super().__init__(
            message,
            bucket=bucket,
            object_key=object_key,
            upload_id=upload_id,
            operation=operation or "multipart_upload",
            details=merged_details,
            cause=cause,
        )


class StorageMultipartUploadNotFoundError(StorageMultipartUploadError):
    """Ошибка отсутствия multipart upload-сессии.

    Args:
        bucket: Имя бакета, связанного с multipart-загрузкой.
        object_key: Ключ объекта, связанного с multipart-загрузкой.
        upload_id: Идентификатор отсутствующей upload-сессии.
        message: Человекочитаемое описание ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        *,
        bucket: str,
        object_key: str,
        upload_id: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку отсутствия multipart upload-сессии.

        Args:
            bucket: Имя бакета, связанного с multipart-загрузкой.
            object_key: Ключ объекта, связанного с multipart-загрузкой.
            upload_id: Идентификатор отсутствующей upload-сессии.
            message: Человекочитаемое описание ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        default_message = "Multipart upload-сессия не найдена."

        super().__init__(
            message or default_message,
            bucket=bucket,
            object_key=object_key,
            upload_id=upload_id,
            operation="get_multipart_upload",
            details=details,
            cause=cause,
        )


class StoragePresignedUrlError(StorageError):
    """Ошибка генерации предварительно подписанного URL.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Имя бакета, для которого создавался URL.
        object_key: Ключ объекта, для которого создавался URL.
        method: HTTP-метод предварительно подписанного URL.
        expires_in_seconds: Время жизни URL в секундах.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Не удалось сформировать предварительно подписанную ссылку.",
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        method: str | None = None,
        expires_in_seconds: int | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку генерации предварительно подписанного URL.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Имя бакета, для которого создавался URL.
            object_key: Ключ объекта, для которого создавался URL.
            method: HTTP-метод предварительно подписанного URL.
            expires_in_seconds: Время жизни URL в секундах.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if bucket is not None:
            merged_details["bucket"] = bucket
        if object_key is not None:
            merged_details["object_key"] = object_key
        if method is not None:
            merged_details["method"] = method
        if expires_in_seconds is not None:
            merged_details["expires_in_seconds"] = expires_in_seconds

        super().__init__(message, details=merged_details, cause=cause)


class StorageIntegrityError(StorageError):
    """Ошибка проверки целостности объекта.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Имя бакета, в котором находится объект.
        object_key: Ключ проверяемого объекта.
        algorithm: Алгоритм проверки целостности.
        expected: Ожидаемое значение.
        actual: Фактическое значение.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Проверка целостности объекта хранилища не удалась.",
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        algorithm: str | None = None,
        expected: Any | None = None,
        actual: Any | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку проверки целостности объекта.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Имя бакета, в котором находится объект.
            object_key: Ключ проверяемого объекта.
            algorithm: Алгоритм проверки целостности.
            expected: Ожидаемое значение.
            actual: Фактическое значение.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if bucket is not None:
            merged_details["bucket"] = bucket
        if object_key is not None:
            merged_details["object_key"] = object_key
        if algorithm is not None:
            merged_details["algorithm"] = algorithm
        if expected is not None:
            merged_details["expected"] = expected
        if actual is not None:
            merged_details["actual"] = actual

        super().__init__(message, details=merged_details, cause=cause)


class StorageChecksumMismatchError(StorageIntegrityError):
    """Ошибка несовпадения контрольной суммы объекта.

    Args:
        bucket: Имя бакета, в котором находится объект.
        object_key: Ключ проверяемого объекта.
        algorithm: Алгоритм контрольной суммы.
        expected: Ожидаемое значение контрольной суммы.
        actual: Фактическое значение контрольной суммы.
        message: Человекочитаемое описание ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        *,
        bucket: str,
        object_key: str,
        algorithm: str,
        expected: str,
        actual: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку несовпадения контрольной суммы.

        Args:
            bucket: Имя бакета, в котором находится объект.
            object_key: Ключ проверяемого объекта.
            algorithm: Алгоритм контрольной суммы.
            expected: Ожидаемое значение контрольной суммы.
            actual: Фактическое значение контрольной суммы.
            message: Человекочитаемое описание ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        default_message = "Контрольная сумма объекта не совпадает с ожидаемой."

        super().__init__(
            message or default_message,
            bucket=bucket,
            object_key=object_key,
            algorithm=algorithm,
            expected=expected,
            actual=actual,
            details=details,
            cause=cause,
        )


class InvalidStorageKeyError(StorageError):
    """Ошибка некорректного ключа объекта в хранилище.

    Args:
        message: Человекочитаемое описание ошибки.
        object_key: Некорректный ключ объекта.
        reason: Машиночитаемая причина ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Некорректный ключ объекта в хранилище.",
        *,
        object_key: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку некорректного ключа объекта.

        Args:
            message: Человекочитаемое описание ошибки.
            object_key: Некорректный ключ объекта.
            reason: Машиночитаемая причина ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if object_key is not None:
            merged_details["object_key"] = object_key
        if reason is not None:
            merged_details["reason"] = reason

        super().__init__(message, details=merged_details, cause=cause)


class InvalidStorageBucketNameError(StorageError):
    """Ошибка некорректного имени бакета.

    Args:
        message: Человекочитаемое описание ошибки.
        bucket: Некорректное имя бакета.
        reason: Машиночитаемая причина ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Некорректное имя bucket объектного хранилища.",
        *,
        bucket: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку некорректного имени бакета.

        Args:
            message: Человекочитаемое описание ошибки.
            bucket: Некорректное имя бакета.
            reason: Машиночитаемая причина ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if bucket is not None:
            merged_details["bucket"] = bucket
        if reason is not None:
            merged_details["reason"] = reason

        super().__init__(message, details=merged_details, cause=cause)


class InvalidStorageMetadataError(StorageError):
    """Ошибка некорректных метаданных объекта.

    Args:
        message: Человекочитаемое описание ошибки.
        metadata_key: Некорректный ключ метаданных.
        metadata_value: Некорректное значение метаданных.
        reason: Машиночитаемая причина ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Некорректные metadata объекта хранилища.",
        *,
        metadata_key: str | None = None,
        metadata_value: Any | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку некорректных метаданных объекта.

        Args:
            message: Человекочитаемое описание ошибки.
            metadata_key: Некорректный ключ метаданных.
            metadata_value: Некорректное значение метаданных.
            reason: Машиночитаемая причина ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if metadata_key is not None:
            merged_details["metadata_key"] = metadata_key
        if metadata_value is not None:
            merged_details["metadata_value"] = metadata_value
        if reason is not None:
            merged_details["reason"] = reason

        super().__init__(message, details=merged_details, cause=cause)


class StorageConfigurationError(StorageError):
    """Ошибка конфигурации объектного хранилища.

    Args:
        message: Человекочитаемое описание ошибки.
        parameter: Название некорректного параметра конфигурации.
        value: Некорректное значение параметра конфигурации.
        reason: Машиночитаемая причина ошибки.
        details: Дополнительные структурированные детали ошибки.
        cause: Исходное исключение, вызвавшее текущую ошибку.
    """

    def __init__(
        self,
        message: str = "Конфигурация объектного хранилища некорректна.",
        *,
        parameter: str | None = None,
        value: Any | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку конфигурации объектного хранилища.

        Args:
            message: Человекочитаемое описание ошибки.
            parameter: Название некорректного параметра конфигурации.
            value: Некорректное значение параметра конфигурации.
            reason: Машиночитаемая причина ошибки.
            details: Дополнительные структурированные детали ошибки.
            cause: Исходное исключение, вызвавшее текущую ошибку.
        """

        merged_details = details.copy() if details else {}

        if parameter is not None:
            merged_details["parameter"] = parameter
        if value is not None:
            merged_details["value"] = value
        if reason is not None:
            merged_details["reason"] = reason

        super().__init__(message, details=merged_details, cause=cause)
