from __future__ import annotations

import asyncio
import functools
import inspect
import socket
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from minio import Minio
from minio.error import S3Error
from urllib3 import PoolManager

from core.config import StorageSettings, get_settings
from storage.exceptions import (
    StorageAuthenticationError,
    StorageConnectionError,
    StorageError,
    StoragePermissionDeniedError,
    StorageTimeoutError,
)

ReturnT = TypeVar("ReturnT")

_storage_executor: ThreadPoolExecutor | None = None
_storage_executor_lock = threading.Lock()


def _get_storage_executor() -> ThreadPoolExecutor:
    """Возвращает общий пул потоков для блокирующих операций хранилища.

    Returns:
        Общий пул потоков для операций storage-слоя.
    """

    global _storage_executor
    if _storage_executor is None:
        with _storage_executor_lock:
            if _storage_executor is None:
                _storage_executor = ThreadPoolExecutor(
                    max_workers=get_settings().storage.storage_executor_max_workers,
                    thread_name_prefix="storage-io",
                )
    return _storage_executor


def shutdown_storage_executor(*, wait: bool = False) -> None:
    """Останавливает общий пул потоков хранилища.

    Функцию следует вызывать при shutdown процесса.

    Args:
        wait: Если ``True``, ожидает завершения выполняющихся задач перед
            остановкой пула.

    Returns:
        ``None``.
    """

    global _storage_executor
    executor = _storage_executor
    _storage_executor = None
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=True)


class StorageClient:
    """Async-обёртка над синхронным клиентом MinIO.

    Класс инкапсулирует ``minio.Minio`` и предоставляет единый метод
    ``execute`` для безопасного запуска синхронных операций через общий пул
    потоков.
    """

    def __init__(
        self,
        settings: StorageSettings,
        *,
        http_client: PoolManager | None = None,
    ) -> None:
        """Инициализирует клиент объектного хранилища.

        Args:
            settings: Настройки подключения к объектному хранилищу.
            http_client: Пользовательский HTTP-клиент для MinIO SDK.

        Raises:
            StorageConnectionError: Если параметры подключения некорректны или
                не удалось создать MinIO-клиент.
        """

        self.settings = settings
        self.endpoint = self._validate_required_string(
            settings.minio_endpoint,
            field_name="minio_endpoint",
        )
        self.access_key = self._validate_required_string(
            settings.minio_access_key,
            field_name="minio_access_key",
        )
        self.secret_key = self._validate_required_string(
            settings.minio_secret_key,
            field_name="minio_secret_key",
        )
        self.secure = settings.minio_secure
        self.region = settings.minio_region if settings.minio_region else None
        self.http_client = http_client

        try:
            self._client = Minio(
                endpoint=self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
                region=self.region,
                http_client=self.http_client,
            )
        except Exception as exc:
            raise StorageConnectionError(
                "Не удалось создать клиент объектного хранилища.",
                endpoint=self.endpoint,
                secure=self.secure,
                details={
                    "region": self.region,
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc

    @property
    def is_secure(self) -> bool:
        """Проверяет, используется ли защищённое соединение.

        Returns:
            ``True``, если клиент использует HTTPS-соединение.
        """

        return self.secure

    @property
    def base_url(self) -> str:
        """Возвращает базовый URL объектного хранилища.

        Returns:
            Базовый URL с HTTP- или HTTPS-схемой.
        """

        return self.settings.minio_base_url

    @property
    def public_url(self) -> str:
        """Возвращает публичный базовый URL объектного хранилища.

        Returns:
            Публичный базовый URL MinIO/S3.
        """

        return self.settings.minio_public_url

    def get_raw_client(self) -> Minio:
        """Возвращает исходный синхронный клиент MinIO.

        Метод нужен для низкоуровневых менеджеров storage-слоя. Использовать
        его напрямую в бизнес-логике не рекомендуется.

        Returns:
            Синхронный клиент ``minio.Minio``.
        """

        return self._client

    async def execute(
        self,
        operation: Callable[..., ReturnT],
        *args: Any,
        operation_name: str | None = None,
        timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> ReturnT:
        """Выполняет синхронную операцию MinIO в отдельном потоке.

        Все ошибки MinIO/S3 преобразуются в наследников ``StorageError``.

        Args:
            operation: Синхронная операция MinIO или storage-слоя.
            *args: Позиционные аргументы операции.
            operation_name: Название операции для диагностики ошибок.
            timeout_seconds: Максимальное время выполнения операции в секундах.
            **kwargs: Именованные аргументы операции.

        Returns:
            Результат выполнения операции.

        Raises:
            StorageTimeoutError: Если операция превысила ``timeout_seconds``.
            StoragePermissionDeniedError: Если MinIO/S3 вернул отказ в доступе.
            StorageAuthenticationError: Если MinIO/S3 вернул ошибку
                аутентификации или авторизации.
            StorageConnectionError: Если произошла сетевая ошибка или
                временная ошибка MinIO/S3.
            StorageError: Если операция завершилась другой ошибкой.
        """

        resolved_operation_name = operation_name or getattr(
            operation,
            "__name__",
            "unknown_storage_operation",
        )

        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(
                _get_storage_executor(),
                functools.partial(operation, *args, **kwargs),
            )

            if timeout_seconds is not None:
                return await asyncio.wait_for(future, timeout=timeout_seconds)

            return await future

        except TimeoutError as exc:
            raise StorageTimeoutError(
                "Операция объектного хранилища превысила допустимое время ожидания.",
                operation=resolved_operation_name,
                timeout_seconds=timeout_seconds,
                details={
                    "endpoint": self.endpoint,
                    "secure": self.secure,
                    "region": self.region,
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc

        except S3Error as exc:
            raise self._convert_s3_error(
                exc,
                operation_name=resolved_operation_name,
            ) from exc

        except (OSError, socket.error) as exc:
            raise StorageConnectionError(
                "Сетевая операция объектного хранилища не удалась.",
                endpoint=self.endpoint,
                secure=self.secure,
                details={
                    "operation": resolved_operation_name,
                    "region": self.region,
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc

        except StorageError:
            raise

        except Exception as exc:
            raise StorageError(
                "Операция объектного хранилища завершилась ошибкой.",
                details={
                    "operation": resolved_operation_name,
                    "endpoint": self.endpoint,
                    "secure": self.secure,
                    "region": self.region,
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc

    async def ping(self, *, timeout_seconds: float | None = 5.0) -> bool:
        """Проверяет доступность объектного хранилища.

        Для проверки используется лёгкая операция ``list_buckets``.

        Args:
            timeout_seconds: Максимальное время ожидания ответа в секундах.

        Returns:
            ``True``, если объектное хранилище доступно.

        Raises:
            StorageTimeoutError: Если проверка превысила ``timeout_seconds``.
            StoragePermissionDeniedError: Если MinIO/S3 вернул отказ в доступе.
            StorageAuthenticationError: Если MinIO/S3 вернул ошибку
                аутентификации или авторизации.
            StorageConnectionError: Если объектное хранилище недоступно.
            StorageError: Если проверка завершилась другой ошибкой.
        """

        await self.execute(
            self._client.list_buckets,
            operation_name="ping_storage",
            timeout_seconds=timeout_seconds,
        )
        return True

    async def list_buckets(self) -> Any:
        """Возвращает список бакетов через исходный MinIO SDK.

        Returns:
            Результат вызова ``Minio.list_buckets``.

        Raises:
            StoragePermissionDeniedError: Если MinIO/S3 вернул отказ в доступе.
            StorageAuthenticationError: Если MinIO/S3 вернул ошибку
                аутентификации или авторизации.
            StorageConnectionError: Если объектное хранилище недоступно.
            StorageError: Если операция завершилась другой ошибкой.
        """

        return await self.execute(
            self._client.list_buckets,
            operation_name="list_buckets",
        )

    async def bucket_exists(self, bucket_name: str) -> bool:
        """Проверяет существование бакета.

        Args:
            bucket_name: Имя проверяемого бакета.

        Returns:
            ``True``, если бакет существует.

        Raises:
            StorageConnectionError: Если имя бакета не является строкой,
                пустое или объектное хранилище недоступно.
            StoragePermissionDeniedError: Если MinIO/S3 вернул отказ в доступе.
            StorageAuthenticationError: Если MinIO/S3 вернул ошибку
                аутентификации или авторизации.
            StorageError: Если операция завершилась другой ошибкой.
        """

        bucket = self._validate_required_string(
            bucket_name,
            field_name="bucket_name",
        )

        return await self.execute(
            self._client.bucket_exists,
            bucket,
            operation_name="bucket_exists",
        )

    async def close(self) -> None:
        """Мягко закрывает HTTP-клиент, если он был передан явно.

        Официальный MinIO SDK не требует обязательного закрытия клиента. Если
        переданный ``http_client`` поддерживает ``close`` или ``clear``,
        выполняется попытка освободить ресурсы.

        Returns:
            ``None``.

        Raises:
            StorageError: Если не удалось закрыть пользовательский HTTP-клиент.
        """

        if self.http_client is None:
            return

        close_method = getattr(self.http_client, "close", None)
        clear_method = getattr(self.http_client, "clear", None)

        try:
            if callable(close_method):
                result = close_method()

                if inspect.isawaitable(result):
                    await result

            elif callable(clear_method):
                result = clear_method()

                if inspect.isawaitable(result):
                    await result

        except Exception as exc:
            raise StorageError(
                "Не удалось закрыть HTTP-клиент объектного хранилища.",
                details={
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc

    @staticmethod
    def _validate_required_string(value: str, *, field_name: str) -> str:
        """Проверяет обязательный строковый параметр подключения.

        Args:
            value: Значение параметра.
            field_name: Название параметра для диагностики ошибки.

        Returns:
            Нормализованное строковое значение.

        Raises:
            StorageConnectionError: Если значение не является строкой или
                является пустой строкой.
        """

        if not isinstance(value, str):
            raise StorageConnectionError(
                "Параметр подключения к объектному хранилищу должен быть строкой.",
                details={
                    "field": field_name,
                    "value_type": type(value).__name__,
                },
            )

        normalized_value = value.strip()

        if not normalized_value:
            raise StorageConnectionError(
                "Параметр подключения к объектному хранилищу не может быть пустым.",
                details={
                    "field": field_name,
                },
            )

        return normalized_value

    def _convert_s3_error(
        self,
        exc: S3Error,
        *,
        operation_name: str,
    ) -> StorageError:
        """Преобразует ошибку MinIO/S3 в доменное исключение storage-слоя.

        Args:
            exc: Исходная ошибка MinIO/S3.
            operation_name: Название операции, при которой возникла ошибка.

        Returns:
            Доменное исключение storage-слоя.
        """

        error_code = getattr(exc, "code", None)
        status_code = getattr(exc, "status_code", None)
        request_id = getattr(exc, "request_id", None)
        resource = getattr(exc, "resource", None)
        response = getattr(exc, "response", None)

        details: dict[str, Any] = {
            "operation": operation_name,
            "endpoint": self.endpoint,
            "secure": self.secure,
            "region": self.region,
            "code": error_code,
            "status_code": status_code,
            "request_id": request_id,
            "resource": resource,
            "reason": str(exc),
        }

        if response is not None:
            details["response"] = str(response)

        if error_code in {
            "AccessDenied",
            "AllAccessDisabled",
        }:
            return StoragePermissionDeniedError(
                "Недостаточно прав для выполнения операции в объектном хранилище.",
                operation=operation_name,
                details=details,
                cause=exc,
            )

        if error_code in {
            "InvalidAccessKeyId",
            "SignatureDoesNotMatch",
            "InvalidToken",
            "ExpiredToken",
            "AuthorizationHeaderMalformed",
            "AuthorizationQueryParametersError",
        } or status_code in {401, 403}:
            return StorageAuthenticationError(
                "Ошибка аутентификации или авторизации в объектном хранилище.",
                operation=operation_name,
                details=details,
                cause=exc,
            )

        if status_code in {408, 429, 500, 502, 503, 504}:
            return StorageConnectionError(
                "Объектное хранилище временно недоступно или вернуло ошибку соединения.",
                endpoint=self.endpoint,
                secure=self.secure,
                details=details,
                cause=exc,
            )

        return StorageError(
            "S3-операция объектного хранилища завершилась ошибкой.",
            details=details,
            cause=exc,
        )
