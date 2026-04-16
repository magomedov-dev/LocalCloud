from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from core.constants import StorageConstants
from storage.buckets import StorageBucketManager
from storage.client import StorageClient
from storage.exceptions import StorageError, StorageHealthCheckError
from storage.keys import normalize_object_key
from storage.objects import StorageObjectManager
from storage.types import StorageHealthState, StorageHealthStatus


class StorageHealthChecker:
    """Проверка состояния объектного хранилища.

    Выполняет проверки подключения, доступа к bucket, задержки и базового
    read/write сценария через тестовый объект.

    Args:
        client: Клиент объектного хранилища.
        bucket_manager: Менеджер операций с bucket-ами.
        object_manager: Менеджер операций с объектами.
    """

    def __init__(
        self,
        *,
        client: StorageClient,
        bucket_manager: StorageBucketManager,
        object_manager: StorageObjectManager,
    ) -> None:
        """Инициализирует класс проверок состояния объектного хранилища.

        Args:
            client: Клиент объектного хранилища.
            bucket_manager: Менеджер операций с bucket-ами.
            object_manager: Менеджер операций с объектами.
        """

        self.client = client
        self.bucket_manager = bucket_manager
        self.object_manager = object_manager

    async def check_storage_connection(self) -> bool:
        """Проверяет подключение к объектному хранилищу.

        Returns:
            ``True``, если ping прошёл успешно.

        Raises:
            StorageHealthCheckError: Если проверка подключения не пройдена.
        """

        try:
            return await self.client.ping()
        except StorageError as exc:
            raise StorageHealthCheckError(
                "Проверка подключения к объектному хранилищу не пройдена.",
                component="storage",
                details={
                    **exc.details,
                    "operation": "check_storage_connection",
                    "reason": exc.message,
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc
        except Exception as exc:
            raise StorageHealthCheckError(
                "Проверка подключения к объектному хранилищу завершилась ошибкой.",
                component="storage",
                details={
                    "operation": "check_storage_connection",
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc

    async def check_bucket_access(
        self,
        *,
        bucket: str,
    ) -> bool:
        """Проверяет доступ к bucket объектного хранилища.

        Args:
            bucket: Имя bucket.

        Returns:
            ``True``, если bucket доступен.

        Raises:
            StorageHealthCheckError: Если проверка доступа к bucket не пройдена.
        """

        try:
            return await self.bucket_manager.check_bucket_access(bucket)
        except StorageError as exc:
            raise StorageHealthCheckError(
                "Проверка доступа к bucket объектного хранилища не пройдена.",
                component="storage",
                details={
                    **exc.details,
                    "operation": "check_bucket_access",
                    "bucket": bucket,
                    "reason": exc.message,
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc
        except Exception as exc:
            raise StorageHealthCheckError(
                "Проверка доступа к bucket объектного хранилища завершилась ошибкой.",
                component="storage",
                details={
                    "operation": "check_bucket_access",
                    "bucket": bucket,
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc

    async def check_storage_latency(self) -> float:
        """Проверяет задержку ответа объектного хранилища.

        Returns:
            Задержка ping в миллисекундах, округлённая до 3 знаков.

        Raises:
            StorageHealthCheckError: Если проверка задержки не пройдена.
        """

        started_at = time.perf_counter()

        try:
            await self.client.ping()
        except StorageError as exc:
            raise StorageHealthCheckError(
                "Проверка задержки объектного хранилища не пройдена.",
                component="storage",
                details={
                    **exc.details,
                    "operation": "check_storage_latency",
                    "reason": exc.message,
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc
        except Exception as exc:
            raise StorageHealthCheckError(
                "Проверка задержки объектного хранилища завершилась ошибкой.",
                component="storage",
                details={
                    "operation": "check_storage_latency",
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc

        finished_at = time.perf_counter()
        latency_ms = (finished_at - started_at) * 1000

        return round(latency_ms, 3)

    async def check_storage_read_write(
        self,
        *,
        bucket: str,
        object_key: str | None = None,
    ) -> bool:
        """Проверяет базовый read/write сценарий объектного хранилища.

        Метод создаёт тестовый объект, проверяет его размер, скачивает и
        сверяет содержимое, затем пытается безопасно удалить тестовый объект.

        Args:
            bucket: Имя bucket для проверки.
            object_key: Ключ тестового объекта. Если не передан, генерируется
                автоматически.

        Returns:
            ``True``, если read/write проверка прошла успешно.

        Raises:
            StorageHealthCheckError: Если read/write проверка не пройдена.
        """

        test_object_key: str | None = None
        object_created = False

        try:
            test_object_key = normalize_object_key(
                object_key or self.build_healthcheck_object_key(),
            )

            await self.object_manager.put_object(
                bucket=bucket,
                object_key=test_object_key,
                data=StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD,
                length=len(StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD),
                content_type=StorageConstants.STORAGE_HEALTHCHECK_OBJECT_CONTENT_TYPE,
                metadata={
                    "purpose": "health_check",
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            object_created = True

            object_info = await self.object_manager.stat_object(
                bucket=bucket,
                object_key=test_object_key,
            )

            if object_info.size_bytes != len(
                StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
            ):
                raise StorageHealthCheckError(
                    "Проверка read/write объектного хранилища обнаружила некорректный размер объекта.",
                    component="storage",
                    details={
                        "operation": "check_storage_read_write",
                        "bucket": bucket,
                        "object_key": test_object_key,
                        "expected_size_bytes": len(
                            StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
                        ),
                        "actual_size_bytes": object_info.size_bytes,
                    },
                )

            download_result = await self.object_manager.get_object_bytes(
                bucket=bucket,
                object_key=test_object_key,
            )

            if (
                download_result.data
                != StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
            ):
                raise StorageHealthCheckError(
                    "Проверка read/write объектного хранилища обнаружила несовпадение содержимого объекта.",
                    component="storage",
                    details={
                        "operation": "check_storage_read_write",
                        "bucket": bucket,
                        "object_key": test_object_key,
                    },
                )

            return True

        except StorageHealthCheckError:
            raise
        except StorageError as exc:
            raise StorageHealthCheckError(
                "Проверка read/write объектного хранилища не пройдена.",
                component="storage",
                details={
                    **exc.details,
                    "operation": "check_storage_read_write",
                    "bucket": bucket,
                    "object_key": test_object_key or object_key,
                    "reason": exc.message,
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc
        except Exception as exc:
            raise StorageHealthCheckError(
                "Проверка read/write объектного хранилища завершилась ошибкой.",
                component="storage",
                details={
                    "operation": "check_storage_read_write",
                    "bucket": bucket,
                    "object_key": test_object_key or object_key,
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                cause=exc,
            ) from exc
        finally:
            if object_created and test_object_key is not None:
                await self.safe_delete_healthcheck_object(
                    bucket=bucket,
                    object_key=test_object_key,
                )

    async def check_storage_health(
        self,
        *,
        bucket: str,
        latency_threshold_ms: float | None = None,
        check_read_write: bool = True,
    ) -> StorageHealthStatus:
        """Проверяет общее состояние объектного хранилища.

        Проверка включает подключение, задержку, доступ к bucket и,
        опционально, read/write сценарий.

        Args:
            bucket: Имя bucket для проверки.
            latency_threshold_ms: Порог задержки в миллисекундах. Если не
                передан, используется значение по умолчанию из констант.
            check_read_write: Выполнять ли read/write проверку.

        Returns:
            DTO с итоговым состоянием объектного хранилища.
        """

        resolved_latency_threshold_ms = (
            StorageConstants.STORAGE_DEFAULT_LATENCY_THRESHOLD_MS
            if latency_threshold_ms is None
            else self.validate_latency_threshold(latency_threshold_ms)
        )

        checked_at = datetime.now(UTC)
        connection_ok = False
        bucket_access_ok: bool | None = None
        read_write_ok: bool | None = None
        latency_ms: float | None = None
        details: dict[str, Any] = {}

        try:
            connection_ok = await self.check_storage_connection()
        except StorageHealthCheckError as exc:
            return StorageHealthStatus(
                state=StorageHealthState.UNHEALTHY,
                checked_at=checked_at,
                connection_ok=False,
                bucket_access_ok=None,
                read_write_ok=None,
                latency_ms=None,
                latency_threshold_ms=resolved_latency_threshold_ms,
                details={
                    "reason": exc.message,
                    "error_type": exc.__class__.__name__,
                    **exc.details,
                },
            )

        try:
            latency_ms = await self.check_storage_latency()
        except StorageHealthCheckError as exc:
            details["latency_error"] = {
                "reason": exc.message,
                "error_type": exc.__class__.__name__,
                **exc.details,
            }

        try:
            bucket_access_ok = await self.check_bucket_access(
                bucket=bucket,
            )
        except StorageHealthCheckError as exc:
            return StorageHealthStatus(
                state=StorageHealthState.UNHEALTHY,
                checked_at=checked_at,
                connection_ok=connection_ok,
                bucket_access_ok=False,
                read_write_ok=None,
                latency_ms=latency_ms,
                latency_threshold_ms=resolved_latency_threshold_ms,
                details={
                    "reason": exc.message,
                    "error_type": exc.__class__.__name__,
                    **exc.details,
                    **details,
                },
            )

        if check_read_write:
            try:
                read_write_ok = await self.check_storage_read_write(
                    bucket=bucket,
                )
            except StorageHealthCheckError as exc:
                return StorageHealthStatus(
                    state=StorageHealthState.UNHEALTHY,
                    checked_at=checked_at,
                    connection_ok=connection_ok,
                    bucket_access_ok=bucket_access_ok,
                    read_write_ok=False,
                    latency_ms=latency_ms,
                    latency_threshold_ms=resolved_latency_threshold_ms,
                    details={
                        "reason": exc.message,
                        "error_type": exc.__class__.__name__,
                        **exc.details,
                        **details,
                    },
                )
        else:
            read_write_ok = None
            details["read_write_check_skipped"] = True

        state = self.resolve_health_state(
            connection_ok=connection_ok,
            bucket_access_ok=bucket_access_ok,
            read_write_ok=read_write_ok,
            latency_ms=latency_ms,
            latency_threshold_ms=resolved_latency_threshold_ms,
            read_write_check_enabled=check_read_write,
        )

        if latency_ms is not None and latency_ms > resolved_latency_threshold_ms:
            details["latency_threshold_exceeded"] = True

        return StorageHealthStatus(
            state=state,
            checked_at=checked_at,
            connection_ok=connection_ok,
            bucket_access_ok=bucket_access_ok,
            read_write_ok=read_write_ok,
            latency_ms=latency_ms,
            latency_threshold_ms=resolved_latency_threshold_ms,
            details=details,
        )

    async def get_storage_health_report(
        self,
        *,
        bucket: str,
        latency_threshold_ms: float | None = None,
        check_read_write: bool = True,
        raise_on_error: bool = False,
    ) -> StorageHealthStatus:
        """Возвращает health report объектного хранилища в виде DTO.

        Args:
            bucket: Имя bucket для проверки.
            latency_threshold_ms: Порог задержки в миллисекундах.
            check_read_write: Выполнять ли read/write проверку.
            raise_on_error: Пробрасывать ли ошибки вместо возврата unhealthy
                отчёта.

        Returns:
            DTO с результатами health-check.
        """

        resolved_latency_threshold_ms = (
            StorageConstants.STORAGE_DEFAULT_LATENCY_THRESHOLD_MS
            if latency_threshold_ms is None
            else self.validate_latency_threshold(latency_threshold_ms)
        )

        try:
            return await self.check_storage_health(
                bucket=bucket,
                latency_threshold_ms=resolved_latency_threshold_ms,
                check_read_write=check_read_write,
            )

        except StorageHealthCheckError as exc:
            if raise_on_error:
                raise

            return StorageHealthStatus(
                state=StorageHealthState.UNHEALTHY,
                checked_at=datetime.now(UTC),
                connection_ok=False,
                bucket_access_ok=None,
                read_write_ok=None,
                latency_ms=None,
                latency_threshold_ms=resolved_latency_threshold_ms,
                details={
                    "bucket": bucket,
                    "error": exc.__class__.__name__,
                    "message": exc.message,
                    **exc.details,
                },
            )

        except StorageError as exc:
            if raise_on_error:
                raise

            return StorageHealthStatus(
                state=StorageHealthState.UNHEALTHY,
                checked_at=datetime.now(UTC),
                connection_ok=False,
                bucket_access_ok=None,
                read_write_ok=None,
                latency_ms=None,
                latency_threshold_ms=resolved_latency_threshold_ms,
                details={
                    "bucket": bucket,
                    "error": exc.__class__.__name__,
                    "message": exc.message,
                    **exc.details,
                },
            )

        except Exception as exc:
            if raise_on_error:
                raise

            return StorageHealthStatus(
                state=StorageHealthState.UNHEALTHY,
                checked_at=datetime.now(UTC),
                connection_ok=False,
                bucket_access_ok=None,
                read_write_ok=None,
                latency_ms=None,
                latency_threshold_ms=resolved_latency_threshold_ms,
                details={
                    "bucket": bucket,
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                    "operation": "get_storage_health_report",
                    "reason": str(exc),
                    "error_type": exc.__class__.__name__,
                },
            )

    def build_healthcheck_object_key(self) -> str:
        """Создаёт ключ тестового health-check объекта.

        Returns:
            Нормализованный ключ тестового объекта.
        """

        return normalize_object_key(
            f"{StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PREFIX}/{uuid.uuid4()}.txt"
        )

    async def safe_delete_healthcheck_object(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> None:
        """Безопасно удаляет тестовый health-check объект.

        Ошибки удаления намеренно подавляются, чтобы cleanup не маскировал
        исходный результат health-check.

        Args:
            bucket: Имя bucket.
            object_key: Ключ тестового объекта.

        Returns:
            ``None``.
        """

        try:
            await self.object_manager.delete_object(
                bucket=bucket,
                object_key=object_key,
                missing_ok=True,
            )
        except StorageError:
            return

    @staticmethod
    def validate_latency_threshold(latency_threshold_ms: float) -> float:
        """Проверяет порог задержки объектного хранилища.

        Args:
            latency_threshold_ms: Порог задержки в миллисекундах.

        Returns:
            Проверенный порог задержки.

        Raises:
            StorageHealthCheckError: Если порог задержки некорректен.
        """

        if not isinstance(latency_threshold_ms, int | float):
            raise StorageHealthCheckError(
                "Порог задержки объектного хранилища должен быть числом.",
                component="storage",
                details={
                    "operation": "validate_latency_threshold",
                    "latency_threshold_ms": latency_threshold_ms,
                    "value_type": type(latency_threshold_ms).__name__,
                },
            )

        if isinstance(latency_threshold_ms, bool):
            raise StorageHealthCheckError(
                "Порог задержки объектного хранилища должен быть числом, а не bool.",
                component="storage",
                details={
                    "operation": "validate_latency_threshold",
                    "latency_threshold_ms": latency_threshold_ms,
                    "value_type": type(latency_threshold_ms).__name__,
                },
            )

        if latency_threshold_ms <= 0:
            raise StorageHealthCheckError(
                "Порог задержки объектного хранилища должен быть положительным.",
                component="storage",
                details={
                    "operation": "validate_latency_threshold",
                    "latency_threshold_ms": latency_threshold_ms,
                },
            )

        return float(latency_threshold_ms)

    @staticmethod
    def resolve_health_state(
        *,
        connection_ok: bool,
        bucket_access_ok: bool | None,
        read_write_ok: bool | None,
        latency_ms: float | None,
        latency_threshold_ms: float,
        read_write_check_enabled: bool,
    ) -> StorageHealthState:
        """Определяет итоговое состояние объектного хранилища.

        Args:
            connection_ok: Успешна ли проверка подключения.
            bucket_access_ok: Успешна ли проверка доступа к bucket.
            read_write_ok: Успешна ли read/write проверка.
            latency_ms: Измеренная задержка в миллисекундах.
            latency_threshold_ms: Порог задержки в миллисекундах.
            read_write_check_enabled: Была ли включена read/write проверка.

        Returns:
            Итоговое состояние хранилища.
        """

        if not connection_ok:
            return StorageHealthState.UNHEALTHY

        if bucket_access_ok is not True:
            return StorageHealthState.UNHEALTHY

        if read_write_check_enabled and read_write_ok is not True:
            return StorageHealthState.UNHEALTHY

        if latency_ms is None:
            return StorageHealthState.DEGRADED

        if latency_ms > latency_threshold_ms:
            return StorageHealthState.DEGRADED

        if not read_write_check_enabled:
            return StorageHealthState.DEGRADED

        return StorageHealthState.HEALTHY

    @staticmethod
    def _validate_payload(payload: bytes) -> bytes:
        """Проверяет payload health-check объекта.

        Args:
            payload: Payload тестового объекта.

        Returns:
            Проверенный payload.

        Raises:
            StorageHealthCheckError: Если payload некорректен.
        """

        if not isinstance(payload, bytes):
            raise StorageHealthCheckError(
                "Payload health-check объекта должен быть bytes.",
                component="storage",
                details={
                    "operation": "init_storage_health_checker",
                    "value_type": type(payload).__name__,
                },
            )

        if not payload:
            raise StorageHealthCheckError(
                "Payload health-check объекта не должен быть пустым.",
                component="storage",
                details={
                    "operation": "init_storage_health_checker",
                },
            )

        return payload

    @staticmethod
    def _validate_content_type(content_type: str) -> str:
        """Проверяет Content-Type health-check объекта.

        Args:
            content_type: Content-Type тестового объекта.

        Returns:
            Нормализованный Content-Type.

        Raises:
            StorageHealthCheckError: Если Content-Type некорректен.
        """

        if not isinstance(content_type, str):
            raise StorageHealthCheckError(
                "Content-Type health-check объекта должен быть строкой.",
                component="storage",
                details={
                    "operation": "init_storage_health_checker",
                    "value_type": type(content_type).__name__,
                },
            )

        normalized_content_type = content_type.strip()

        if not normalized_content_type:
            raise StorageHealthCheckError(
                "Content-Type health-check объекта не должен быть пустым.",
                component="storage",
                details={
                    "operation": "init_storage_health_checker",
                },
            )

        return normalized_content_type
