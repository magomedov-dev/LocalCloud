from __future__ import annotations

from datetime import datetime
from typing import Any

from core.constants import StorageConstants
from storage.client import StorageClient
from storage.exceptions import (
    InvalidStorageBucketNameError,
    StorageBucketAlreadyExistsError,
    StorageBucketError,
    StorageBucketNotFoundError,
    StorageConnectionError,
    StorageError,
)
from storage.types import StorageBucketInfo


class StorageBucketNameValidator:
    """Валидатор имён bucket-ов объектного хранилища.

    Args:
        min_length: Минимальная допустимая длина имени bucket.
        max_length: Максимальная допустимая длина имени bucket.

    Raises:
        ValueError: Если ограничения длины некорректны.
    """

    def __init__(self, *, min_length: int, max_length: int) -> None:
        """Инициализирует валидатор имён bucket-ов.

        Args:
            min_length: Минимальная допустимая длина имени bucket.
            max_length: Максимальная допустимая длина имени bucket.

        Raises:
            ValueError: Если ограничения длины некорректны.
        """

        if not isinstance(min_length, int) or isinstance(min_length, bool):
            raise ValueError("min_length должен быть целым числом.")

        if not isinstance(max_length, int) or isinstance(max_length, bool):
            raise ValueError("max_length должен быть целым числом.")

        if min_length <= 0:
            raise ValueError("min_length должен быть больше нуля.")

        if max_length < min_length:
            raise ValueError("max_length должен быть больше или равен min_length.")

        self.min_length = min_length
        self.max_length = max_length

    def validate(self, bucket: str) -> str:
        """Проверяет и нормализует имя bucket.

        Правила приближены к S3-compatible требованиям:

        * длина от ``min_length`` до ``max_length`` символов;
        * только латинские строчные буквы, цифры, точки и дефисы;
        * имя начинается и заканчивается буквой или цифрой;
        * запрещены повторяющиеся точки;
        * запрещены сочетания ``.-`` и ``-.``;
        * запрещён формат, похожий на IPv4-адрес.

        Args:
            bucket: Исходное имя bucket.

        Returns:
            Нормализованное имя bucket.

        Raises:
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        if not isinstance(bucket, str):
            raise InvalidStorageBucketNameError(
                "Имя bucket должно быть строкой.",
                reason="bucket_name_is_not_string",
                details={
                    "value_type": type(bucket).__name__,
                },
            )

        normalized_bucket = bucket.strip().lower()

        if not normalized_bucket:
            raise InvalidStorageBucketNameError(
                "Имя bucket не может быть пустым.",
                bucket=bucket,
                reason="empty_bucket_name",
            )

        if len(normalized_bucket) < self.min_length:
            raise InvalidStorageBucketNameError(
                "Имя bucket слишком короткое.",
                bucket=normalized_bucket,
                reason="bucket_name_too_short",
                details={
                    "length": len(normalized_bucket),
                    "min_length": self.min_length,
                },
            )

        if len(normalized_bucket) > self.max_length:
            raise InvalidStorageBucketNameError(
                "Имя bucket слишком длинное.",
                bucket=normalized_bucket,
                reason="bucket_name_too_long",
                details={
                    "length": len(normalized_bucket),
                    "max_length": self.max_length,
                },
            )

        if not StorageConstants.BUCKET_NAME_PATTERN.fullmatch(normalized_bucket):
            raise InvalidStorageBucketNameError(
                "Имя bucket содержит недопустимые символы или структуру.",
                bucket=normalized_bucket,
                reason="invalid_bucket_name_pattern",
                details={
                    "allowed_pattern": StorageConstants.BUCKET_NAME_PATTERN.pattern,
                },
            )

        if ".." in normalized_bucket:
            raise InvalidStorageBucketNameError(
                "Имя bucket не должно содержать повторяющиеся точки.",
                bucket=normalized_bucket,
                reason="contains_repeated_dots",
            )

        if ".-" in normalized_bucket or "-." in normalized_bucket:
            raise InvalidStorageBucketNameError(
                "Имя bucket не должно содержать сочетания '.-' или '-.'.",
                bucket=normalized_bucket,
                reason="contains_invalid_dot_dash_sequence",
            )

        if StorageConstants.IP_ADDRESS_LIKE_PATTERN.fullmatch(normalized_bucket):
            raise InvalidStorageBucketNameError(
                "Имя bucket не должно быть похоже на IPv4-адрес.",
                bucket=normalized_bucket,
                reason="ip_address_like_bucket_name",
            )

        return normalized_bucket


class StorageBucketManager:
    """Менеджер операций с bucket-ами MinIO/S3.

    Все операции выполняются через ``StorageClient.execute``, чтобы
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
        """Инициализирует менеджер bucket-ов.

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

    async def bucket_exists(self, bucket: str) -> bool:
        """Проверяет существование bucket.

        Args:
            bucket: Имя bucket.

        Returns:
            ``True``, если bucket существует, иначе ``False``.

        Raises:
            StorageBucketError: Если операция проверки не удалась.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        normalized_bucket = self._validate_bucket_name(bucket)

        try:
            return await self.client.execute(
                self.client.get_raw_client().bucket_exists,
                normalized_bucket,
                operation_name="bucket_exists",
            )
        except StorageError as exc:
            raise self._bucket_error(
                exc,
                bucket=normalized_bucket,
                operation="bucket_exists",
            ) from exc

    async def require_bucket_exists(self, bucket: str) -> StorageBucketInfo:
        """Возвращает информацию о bucket, если он существует.

        Args:
            bucket: Имя bucket.

        Returns:
            Информация о bucket.

        Raises:
            StorageBucketNotFoundError: Если bucket отсутствует.
            StorageBucketError: Если операция проверки не удалась.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        normalized_bucket = self._validate_bucket_name(bucket)

        if not await self.bucket_exists(normalized_bucket):
            raise StorageBucketNotFoundError(
                normalized_bucket,
                details={
                    "operation": "require_bucket_exists",
                },
            )

        return await self.get_bucket_info(normalized_bucket)

    async def get_bucket_info(self, bucket: str) -> StorageBucketInfo:
        """Возвращает информацию о bucket.

        Args:
            bucket: Имя bucket.

        Returns:
            Информация о bucket.

        Raises:
            StorageBucketNotFoundError: Если bucket отсутствует.
            StorageBucketError: Если получение информации не удалось.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        normalized_bucket = self._validate_bucket_name(bucket)

        try:
            buckets = await self.client.execute(
                self.client.get_raw_client().list_buckets,
                operation_name="get_bucket_info",
            )
        except StorageError as exc:
            raise self._bucket_error(
                exc,
                bucket=normalized_bucket,
                operation="get_bucket_info",
            ) from exc

        for bucket_info in buckets:
            bucket_name = getattr(bucket_info, "name", None)

            if bucket_name == normalized_bucket:
                return StorageBucketInfo(
                    name=normalized_bucket,
                    created_at=self._extract_bucket_created_at(bucket_info),
                )

        raise StorageBucketNotFoundError(
            normalized_bucket,
            details={
                "operation": "get_bucket_info",
            },
        )

    async def list_buckets(self) -> list[StorageBucketInfo]:
        """Возвращает список bucket-ов.

        Returns:
            Список информации о bucket-ах.

        Raises:
            StorageBucketError: Если получение списка bucket-ов не удалось.
        """

        try:
            buckets = await self.client.execute(
                self.client.get_raw_client().list_buckets,
                operation_name="list_buckets",
            )
        except StorageError as exc:
            raise self._bucket_error(
                exc,
                bucket=None,
                operation="list_buckets",
            ) from exc

        result: list[StorageBucketInfo] = []

        for bucket_info in buckets:
            bucket_name = getattr(bucket_info, "name", None)

            if bucket_name is None:
                continue

            try:
                normalized_bucket = self._validate_bucket_name(str(bucket_name))
            except StorageError:
                normalized_bucket = str(bucket_name)

            result.append(
                StorageBucketInfo(
                    name=normalized_bucket,
                    created_at=self._extract_bucket_created_at(bucket_info),
                )
            )

        return result

    async def create_bucket(
        self,
        bucket: str,
        *,
        region: str | None = None,
        object_lock: bool = False,
        ignore_existing: bool = True,
    ) -> StorageBucketInfo:
        """Создаёт bucket.

        Если ``ignore_existing`` равен ``True`` и bucket уже существует, метод
        возвращает информацию о существующем bucket.

        Args:
            bucket: Имя bucket.
            region: Регион размещения bucket.
            object_lock: Включить Object Lock при создании bucket.
            ignore_existing: Не считать ошибкой уже существующий bucket.

        Returns:
            Информация о созданном или уже существующем bucket.

        Raises:
            StorageBucketAlreadyExistsError: Если bucket уже существует и
                ``ignore_existing`` равен ``False``.
            StorageBucketError: Если создание bucket не удалось.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        normalized_bucket = self._validate_bucket_name(bucket)

        if await self.bucket_exists(normalized_bucket):
            if ignore_existing:
                return await self.get_bucket_info(normalized_bucket)

            raise StorageBucketAlreadyExistsError(
                normalized_bucket,
                details={
                    "operation": "create_bucket",
                },
            )

        try:
            await self.client.execute(
                self.client.get_raw_client().make_bucket,
                normalized_bucket,
                location=region,
                object_lock=object_lock,
                operation_name="create_bucket",
            )
        except StorageError as exc:
            raise self._bucket_error(
                exc,
                bucket=normalized_bucket,
                operation="create_bucket",
            ) from exc

        return await self.get_bucket_info(normalized_bucket)

    async def ensure_bucket_exists(
        self,
        bucket: str,
        *,
        region: str | None = None,
        object_lock: bool = False,
    ) -> StorageBucketInfo:
        """Гарантирует наличие bucket.

        Если bucket уже существует, возвращает информацию о нём. Если bucket
        отсутствует, создаёт его.

        Args:
            bucket: Имя bucket.
            region: Регион размещения bucket при создании.
            object_lock: Включить Object Lock при создании bucket.

        Returns:
            Информация о существующем или созданном bucket.

        Raises:
            StorageBucketError: Если проверка или создание bucket не удались.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        normalized_bucket = self._validate_bucket_name(bucket)

        if await self.bucket_exists(normalized_bucket):
            return await self.get_bucket_info(normalized_bucket)

        return await self.create_bucket(
            normalized_bucket,
            region=region,
            object_lock=object_lock,
            ignore_existing=True,
        )

    async def ensure_buckets_exist(
        self,
        buckets: list[str] | tuple[str, ...] | set[str],
        *,
        region: str | None = None,
        object_lock: bool = False,
    ) -> list[StorageBucketInfo]:
        """Гарантирует наличие нескольких bucket-ов.

        Args:
            buckets: Коллекция имён bucket-ов.
            region: Регион размещения bucket-ов при создании.
            object_lock: Включить Object Lock при создании bucket-ов.

        Returns:
            Информация обо всех bucket-ах в порядке обхода входной коллекции.

        Raises:
            StorageBucketError: Если проверка или создание bucket не удались.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        result: list[StorageBucketInfo] = []

        for bucket in buckets:
            bucket_info = await self.ensure_bucket_exists(
                bucket,
                region=region,
                object_lock=object_lock,
            )
            result.append(bucket_info)

        return result

    async def remove_bucket(
        self,
        bucket: str,
        *,
        missing_ok: bool = False,
    ) -> bool:
        """Удаляет bucket.

        Args:
            bucket: Имя bucket.
            missing_ok: Не считать ошибкой отсутствие bucket.

        Returns:
            ``True``, если bucket был удалён. ``False``, если bucket
            отсутствует и ``missing_ok`` равен ``True``.

        Raises:
            StorageBucketNotFoundError: Если bucket отсутствует и
                ``missing_ok`` равен ``False``.
            StorageBucketError: Если удаление bucket не удалось.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        normalized_bucket = self._validate_bucket_name(bucket)

        exists = await self.bucket_exists(normalized_bucket)

        if not exists:
            if missing_ok:
                return False

            raise StorageBucketNotFoundError(
                normalized_bucket,
                details={
                    "operation": "remove_bucket",
                },
            )

        try:
            await self.client.execute(
                self.client.get_raw_client().remove_bucket,
                normalized_bucket,
                operation_name="remove_bucket",
            )
        except StorageError as exc:
            raise self._bucket_error(
                exc,
                bucket=normalized_bucket,
                operation="remove_bucket",
            ) from exc

        return True

    async def check_bucket_access(self, bucket: str) -> bool:
        """Проверяет доступность bucket для текущего клиента.

        Метод проверяет факт существования bucket и возможность получить
        информацию о нём через список bucket-ов.

        Args:
            bucket: Имя bucket.

        Returns:
            ``True``, если bucket доступен.

        Raises:
            StorageBucketNotFoundError: Если bucket отсутствует.
            StorageBucketError: Если проверка доступа не удалась.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        normalized_bucket = self._validate_bucket_name(bucket)

        if not await self.bucket_exists(normalized_bucket):
            raise StorageBucketNotFoundError(
                normalized_bucket,
                details={
                    "operation": "check_bucket_access",
                },
            )

        await self.get_bucket_info(normalized_bucket)

        return True

    async def check_buckets_access(
        self,
        buckets: list[str] | tuple[str, ...] | set[str],
    ) -> dict[str, bool]:
        """Проверяет доступность нескольких bucket-ов.

        Args:
            buckets: Коллекция имён bucket-ов.

        Returns:
            Словарь, где ключ — нормализованное имя bucket, значение —
            результат проверки доступа.

        Raises:
            StorageBucketNotFoundError: Если хотя бы один bucket отсутствует.
            StorageBucketError: Если проверка доступа не удалась.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        result: dict[str, bool] = {}

        for bucket in buckets:
            normalized_bucket = self._validate_bucket_name(bucket)
            result[normalized_bucket] = await self.check_bucket_access(
                normalized_bucket,
            )

        return result

    async def bucket_is_empty(self, bucket: str) -> bool:
        """Проверяет, пуст ли bucket.

        Для проверки запрашивается максимум один объект.

        Args:
            bucket: Имя bucket.

        Returns:
            ``True``, если bucket пустой, иначе ``False``.

        Raises:
            StorageBucketNotFoundError: Если bucket отсутствует.
            StorageBucketError: Если проверка bucket не удалась.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        normalized_bucket = self._validate_bucket_name(bucket)

        if not await self.bucket_exists(normalized_bucket):
            raise StorageBucketNotFoundError(
                normalized_bucket,
                details={
                    "operation": "bucket_is_empty",
                },
            )

        try:
            objects_iter = await self.client.execute(
                self.client.get_raw_client().list_objects,
                normalized_bucket,
                recursive=True,
                operation_name="bucket_is_empty",
            )

            for _ in objects_iter:
                return False

            return True

        except StorageError as exc:
            raise self._bucket_error(
                exc,
                bucket=normalized_bucket,
                operation="bucket_is_empty",
            ) from exc

    async def remove_bucket_if_empty(
        self,
        bucket: str,
        *,
        missing_ok: bool = False,
    ) -> bool:
        """Удаляет bucket только если он пустой.

        Args:
            bucket: Имя bucket.
            missing_ok: Не считать ошибкой отсутствие bucket при удалении.

        Returns:
            ``True``, если bucket был удалён. ``False``, если bucket
            отсутствует и ``missing_ok`` равен ``True``.

        Raises:
            StorageBucketError: Если bucket не пустой или операция удаления не
                удалась.
            StorageBucketNotFoundError: Если bucket отсутствует.
            InvalidStorageBucketNameError: Если имя bucket некорректно.
        """

        normalized_bucket = self._validate_bucket_name(bucket)

        if not await self.bucket_is_empty(normalized_bucket):
            raise StorageBucketError(
                "Bucket не может быть удалён, так как он не пустой.",
                bucket=normalized_bucket,
                operation="remove_bucket_if_empty",
                details={
                    "reason": "bucket_is_not_empty",
                },
            )

        return await self.remove_bucket(
            normalized_bucket,
            missing_ok=missing_ok,
        )

    @staticmethod
    def _extract_bucket_created_at(bucket_info: Any) -> datetime | None:
        """Извлекает дату создания bucket из объекта SDK.

        Args:
            bucket_info: Объект bucket, полученный из MinIO/S3 SDK.

        Returns:
            Дата создания bucket или ``None``, если дата недоступна.
        """

        created_at = getattr(bucket_info, "creation_date", None)

        if isinstance(created_at, datetime):
            return created_at

        return None

    @staticmethod
    def _bucket_error(
        exc: StorageError,
        *,
        bucket: str | None,
        operation: str,
    ) -> StorageError:
        """Преобразует ошибку хранилища в ошибку уровня bucket-ов.

        Args:
            exc: Исходная ошибка хранилища.
            bucket: Имя bucket, связанное с операцией.
            operation: Название выполняемой операции.

        Returns:
            Ошибка хранилища, уточнённая до bucket-specific ошибки.
        """

        if isinstance(
            exc,
            (
                StorageBucketNotFoundError,
                StorageBucketAlreadyExistsError,
                StorageConnectionError,
            ),
        ):
            return exc

        details = dict(exc.details)
        details.setdefault("reason", exc.message)

        code = details.get("code")
        status_code = details.get("status_code")

        if code in {"NoSuchBucket", "NoSuchBucketPolicy"} or status_code == 404:
            if bucket is None:
                return StorageBucketError(
                    "Bucket не найден при выполнении операции.",
                    bucket=bucket,
                    operation=operation,
                    details=details,
                    cause=exc,
                )

            return StorageBucketNotFoundError(
                bucket,
                details={
                    **details,
                    "operation": operation,
                },
                cause=exc,
            )

        if (
            code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}
            or status_code == 409
        ):
            if bucket is None:
                return StorageBucketError(
                    "Bucket уже существует.",
                    bucket=bucket,
                    operation=operation,
                    details=details,
                    cause=exc,
                )

            return StorageBucketAlreadyExistsError(
                bucket,
                details={
                    **details,
                    "operation": operation,
                },
                cause=exc,
            )

        if code in {"BucketNotEmpty"}:
            return StorageBucketError(
                "Bucket не пустой.",
                bucket=bucket,
                operation=operation,
                details={
                    **details,
                    "reason": "bucket_not_empty",
                },
                cause=exc,
            )

        return StorageBucketError(
            "Операция с bucket объектного хранилища не удалась.",
            bucket=bucket,
            operation=operation,
            details=details,
            cause=exc,
        )
