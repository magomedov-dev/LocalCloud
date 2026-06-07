from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, BinaryIO

from storage.exceptions import (
    StorageConnectionError,
    StorageError,
    StorageIntegrityError,
    StorageObjectNotFoundError,
)
from storage.metadata import normalize_metadata
from storage.objects import StorageObjectManager
from storage.types import (
    StorageChecksumAlgorithm,
    StorageIntegrityProblemType,
    StorageIntegrityReport,
    StorageIntegrityStatus,
    StorageObjectInfo,
    StorageObjectMetadata,
    StorageObjectStatus,
)

HASH_FACTORY_BY_ALGORITHM: dict[
    StorageChecksumAlgorithm,
    Callable[[], Any],
] = {
    StorageChecksumAlgorithm.MD5: hashlib.md5,
    StorageChecksumAlgorithm.SHA1: hashlib.sha1,
    StorageChecksumAlgorithm.SHA256: hashlib.sha256,
    StorageChecksumAlgorithm.SHA512: hashlib.sha512,
}


def normalize_checksum_algorithm(
    algorithm: StorageChecksumAlgorithm | str,
) -> StorageChecksumAlgorithm:
    """Нормализует алгоритм контрольной суммы.

    Args:
        algorithm: Алгоритм контрольной суммы в виде enum или строки.

    Returns:
        Нормализованный алгоритм контрольной суммы.

    Raises:
        StorageIntegrityError: Если алгоритм имеет неподдерживаемый тип или
            значение.
    """

    if isinstance(algorithm, StorageChecksumAlgorithm):
        return algorithm

    if isinstance(algorithm, str):
        normalized_algorithm = algorithm.strip().lower()

        try:
            return StorageChecksumAlgorithm(normalized_algorithm)
        except ValueError as exc:
            raise StorageIntegrityError(
                "Неподдерживаемый алгоритм контрольной суммы.",
                algorithm=algorithm,
                details={
                    "allowed_algorithms": [
                        item.value for item in StorageChecksumAlgorithm
                    ],
                },
                cause=exc,
            ) from exc

    raise StorageIntegrityError(
        "Алгоритм контрольной суммы должен быть строкой или StorageChecksumAlgorithm.",
        details={
            "value_type": type(algorithm).__name__,
        },
    )


def calculate_bytes_checksum(
    data: bytes | bytearray,
    *,
    algorithm: StorageChecksumAlgorithm | str,
) -> str:
    """Рассчитывает checksum для ``bytes`` или ``bytearray``.

    Args:
        data: Данные для расчёта контрольной суммы.
        algorithm: Алгоритм контрольной суммы.

    Returns:
        Контрольная сумма в hex-формате.

    Raises:
        StorageIntegrityError: Если данные или алгоритм некорректны.
    """

    if not isinstance(data, bytes | bytearray):
        raise StorageIntegrityError(
            "Для расчёта checksum ожидались bytes или bytearray.",
            details={
                "value_type": type(data).__name__,
            },
        )

    normalized_algorithm = normalize_checksum_algorithm(algorithm)
    hash_object = create_hash(normalized_algorithm)
    hash_object.update(bytes(data))

    return str(hash_object.hexdigest())


def calculate_stream_checksum(
    stream: BinaryIO,
    *,
    algorithm: StorageChecksumAlgorithm | str,
    chunk_size: int,
    reset_position: bool = True,
) -> str:
    """Рассчитывает checksum для file-like потока.

    Если ``reset_position`` равен ``True`` и поток поддерживает ``seek`` и
    ``tell``, позиция потока будет восстановлена после расчёта.

    Args:
        stream: File-like объект для чтения данных.
        algorithm: Алгоритм контрольной суммы.
        chunk_size: Размер блока чтения в байтах.
        reset_position: Восстанавливать ли исходную позицию потока.

    Returns:
        Контрольная сумма в hex-формате.

    Raises:
        StorageIntegrityError: Если поток, алгоритм или размер блока чтения
            некорректны.
    """

    if not hasattr(stream, "read"):
        raise StorageIntegrityError(
            "Для расчёта checksum ожидался file-like объект.",
            details={
                "value_type": type(stream).__name__,
            },
        )

    validate_checksum_chunk_size(chunk_size)

    normalized_algorithm = normalize_checksum_algorithm(algorithm)
    hash_object = create_hash(normalized_algorithm)

    initial_position: int | None = None

    if reset_position and hasattr(stream, "tell") and hasattr(stream, "seek"):
        try:
            initial_position = int(stream.tell())
        except (OSError, ValueError, TypeError):
            initial_position = None

    try:
        while True:
            chunk = stream.read(chunk_size)

            if not chunk:
                break

            if isinstance(chunk, bytearray):
                chunk = bytes(chunk)

            if not isinstance(chunk, bytes):
                raise StorageIntegrityError(
                    "Поток для расчёта checksum должен возвращать bytes.",
                    details={
                        "chunk_type": type(chunk).__name__,
                    },
                )

            hash_object.update(chunk)
    finally:
        if initial_position is not None and hasattr(stream, "seek"):
            try:
                stream.seek(initial_position)
            except (OSError, ValueError):
                pass

    return str(hash_object.hexdigest())


def validate_checksum_chunk_size(chunk_size: int) -> int:
    """Проверяет размер блока чтения для расчёта checksum.

    Args:
        chunk_size: Размер блока чтения в байтах.

    Returns:
        Проверенный размер блока чтения.

    Raises:
        StorageIntegrityError: Если размер блока чтения некорректен.
    """

    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool):
        raise StorageIntegrityError(
            "Размер блока чтения для checksum должен быть целым числом.",
            details={
                "chunk_size": chunk_size,
                "value_type": type(chunk_size).__name__,
            },
        )

    if chunk_size <= 0:
        raise StorageIntegrityError(
            "Размер блока чтения для checksum должен быть положительным.",
            details={
                "chunk_size": chunk_size,
            },
        )

    return chunk_size


class StorageIntegrityChecker:
    """Проверка целостности объектов MinIO/S3.

    Для получения фактических данных используется ``StorageObjectManager``.
    Обычные несовпадения размера, checksum или metadata возвращаются в отчёте
    как проблемы, а не выбрасываются как исключения.

    Args:
        object_manager: Менеджер операций с объектами.
    """

    def __init__(
        self,
        *,
        object_manager: StorageObjectManager,
    ) -> None:
        """Инициализирует класс проверок целостности объектов.

        Args:
            object_manager: Менеджер операций с объектами.
        """

        self.object_manager = object_manager

    async def verify_object_exists(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> StorageIntegrityStatus:
        """Проверяет существование объекта.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.

        Returns:
            Статус проверки существования объекта.

        Raises:
            StorageIntegrityError: Если проверка не удалась из-за
                инфраструктурной ошибки.
        """

        try:
            exists = await self.object_manager.object_exists(
                bucket=bucket,
                object_key=object_key,
            )
        except StorageConnectionError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_exists",
            ) from exc
        except StorageError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_exists",
            ) from exc

        if exists:
            return StorageIntegrityStatus(
                is_success=True,
                message="Объект найден в хранилище.",
            )

        return StorageIntegrityStatus(
            is_success=False,
            problem_type=StorageIntegrityProblemType.OBJECT_NOT_FOUND,
            message="Объект отсутствует в хранилище.",
            expected=True,
            actual=False,
        )

    async def verify_object_size(
        self,
        *,
        bucket: str,
        object_key: str,
        expected_size_bytes: int,
        object_info: StorageObjectInfo | None = None,
    ) -> StorageIntegrityStatus:
        """Проверяет размер объекта.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expected_size_bytes: Ожидаемый размер объекта в байтах.
            object_info: Уже полученная информация об объекте.

        Returns:
            Статус проверки размера объекта.

        Raises:
            StorageIntegrityError: Если ожидаемый размер некорректен или
                проверка не удалась из-за инфраструктурной ошибки.
        """

        self._validate_expected_size(expected_size_bytes)

        try:
            resolved_object_info = object_info or await self.object_manager.stat_object(
                bucket=bucket,
                object_key=object_key,
            )
        except StorageObjectNotFoundError:
            return StorageIntegrityStatus(
                is_success=False,
                problem_type=StorageIntegrityProblemType.OBJECT_NOT_FOUND,
                message="Невозможно проверить размер: объект отсутствует.",
                expected=expected_size_bytes,
                actual=None,
            )
        except StorageConnectionError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_size",
                expected=expected_size_bytes,
            ) from exc
        except StorageError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_size",
                expected=expected_size_bytes,
            ) from exc

        actual_size_bytes = resolved_object_info.size_bytes

        if actual_size_bytes == expected_size_bytes:
            return StorageIntegrityStatus(
                is_success=True,
                message="Размер объекта совпадает с ожидаемым.",
                expected=expected_size_bytes,
                actual=actual_size_bytes,
            )

        return StorageIntegrityStatus(
            is_success=False,
            problem_type=StorageIntegrityProblemType.SIZE_MISMATCH,
            message="Размер объекта не совпадает с ожидаемым.",
            expected=expected_size_bytes,
            actual=actual_size_bytes,
        )

    async def verify_object_checksum(
        self,
        *,
        bucket: str,
        object_key: str,
        expected_checksum: str,
        expected_checksum_algorithm: StorageChecksumAlgorithm | str,
    ) -> StorageIntegrityStatus:
        """Проверяет checksum объекта.

        Фактический checksum считается по содержимому объекта, а не берётся из
        metadata, потому что metadata не является источником истины.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expected_checksum: Ожидаемая контрольная сумма.
            expected_checksum_algorithm: Алгоритм ожидаемой контрольной суммы.

        Returns:
            Статус проверки checksum.

        Raises:
            StorageIntegrityError: Если ожидаемые параметры некорректны или
                проверка не удалась из-за инфраструктурной ошибки.
        """

        normalized_expected_checksum = self._normalize_expected_checksum(
            expected_checksum,
        )
        normalized_algorithm = normalize_checksum_algorithm(
            expected_checksum_algorithm,
        )

        try:
            download_result = await self.object_manager.get_object_bytes(
                bucket=bucket,
                object_key=object_key,
            )
        except StorageObjectNotFoundError:
            return StorageIntegrityStatus(
                is_success=False,
                problem_type=StorageIntegrityProblemType.OBJECT_NOT_FOUND,
                message="Невозможно проверить checksum: объект отсутствует.",
                expected=normalized_expected_checksum,
                actual=None,
            )
        except StorageConnectionError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_checksum",
                expected=normalized_expected_checksum,
            ) from exc
        except StorageError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_checksum",
                expected=normalized_expected_checksum,
            ) from exc

        actual_checksum = calculate_bytes_checksum(
            download_result.data,
            algorithm=normalized_algorithm,
        )

        if actual_checksum == normalized_expected_checksum:
            return StorageIntegrityStatus(
                is_success=True,
                message="Checksum объекта совпадает с ожидаемым.",
                expected=normalized_expected_checksum,
                actual=actual_checksum,
            )

        return StorageIntegrityStatus(
            is_success=False,
            problem_type=StorageIntegrityProblemType.CHECKSUM_MISMATCH,
            message="Checksum объекта не совпадает с ожидаемым.",
            expected=normalized_expected_checksum,
            actual=actual_checksum,
        )

    async def verify_object_metadata(
        self,
        *,
        bucket: str,
        object_key: str,
        expected_metadata: Mapping[str, Any] | StorageObjectMetadata,
        object_info: StorageObjectInfo | None = None,
        require_exact_match: bool = False,
    ) -> StorageIntegrityStatus:
        """Проверяет metadata объекта.

        По умолчанию проверяется, что все ожидаемые metadata присутствуют и
        совпадают. Если ``require_exact_match`` равен ``True``, также
        проверяется отсутствие лишних metadata в объекте.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expected_metadata: Ожидаемые metadata.
            object_info: Уже полученная информация об объекте.
            require_exact_match: Требовать точного совпадения metadata.

        Returns:
            Статус проверки metadata.

        Raises:
            StorageIntegrityError: Если проверка не удалась из-за
                инфраструктурной ошибки.
        """

        normalized_expected_metadata = normalize_metadata(expected_metadata)

        try:
            resolved_object_info = object_info or await self.object_manager.stat_object(
                bucket=bucket,
                object_key=object_key,
            )
        except StorageObjectNotFoundError:
            return StorageIntegrityStatus(
                is_success=False,
                problem_type=StorageIntegrityProblemType.OBJECT_NOT_FOUND,
                message="Невозможно проверить metadata: объект отсутствует.",
                expected=normalized_expected_metadata.to_plain_dict(),
                actual=None,
            )
        except StorageConnectionError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_metadata",
                expected=normalized_expected_metadata.to_plain_dict(),
            ) from exc
        except StorageError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_metadata",
                expected=normalized_expected_metadata.to_plain_dict(),
            ) from exc

        actual_metadata = normalize_metadata(resolved_object_info.metadata)

        expected_values = normalized_expected_metadata.to_plain_dict()
        actual_values = actual_metadata.to_plain_dict()

        if require_exact_match:
            matches = actual_values == expected_values
        else:
            matches = all(
                actual_values.get(key) == value
                for key, value in expected_values.items()
            )

        if matches:
            return StorageIntegrityStatus(
                is_success=True,
                message="Metadata объекта совпадают с ожидаемыми.",
                expected=expected_values,
                actual=actual_values,
            )

        return StorageIntegrityStatus(
            is_success=False,
            problem_type=StorageIntegrityProblemType.METADATA_MISMATCH,
            message="Metadata объекта не совпадают с ожидаемыми.",
            expected=expected_values,
            actual=actual_values,
        )

    async def verify_object_status(
        self,
        *,
        bucket: str,
        object_key: str,
        expected_status: StorageObjectStatus,
        object_info: StorageObjectInfo | None = None,
    ) -> StorageIntegrityStatus:
        """Проверяет инфраструктурный статус объекта.

        Так как S3 не хранит прикладной статус, фактический статус берётся из
        ``StorageObjectInfo``. Обычно ``AVAILABLE`` означает, что
        ``stat_object`` выполнился успешно.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expected_status: Ожидаемый статус объекта.
            object_info: Уже полученная информация об объекте.

        Returns:
            Статус проверки статуса объекта.

        Raises:
            StorageIntegrityError: Если ожидаемый статус некорректен или
                проверка не удалась из-за инфраструктурной ошибки.
        """

        if not isinstance(expected_status, StorageObjectStatus):
            raise StorageIntegrityError(
                "Ожидаемый статус объекта должен быть StorageObjectStatus.",
                expected=expected_status,
                details={
                    "value_type": type(expected_status).__name__,
                },
            )

        try:
            resolved_object_info = object_info or await self.object_manager.stat_object(
                bucket=bucket,
                object_key=object_key,
            )
        except StorageObjectNotFoundError:
            actual_status = StorageObjectStatus.MISSING

            if expected_status == actual_status:
                return StorageIntegrityStatus(
                    is_success=True,
                    message="Статус объекта совпадает с ожидаемым.",
                    expected=expected_status.value,
                    actual=actual_status.value,
                )

            return StorageIntegrityStatus(
                is_success=False,
                problem_type=StorageIntegrityProblemType.OBJECT_STATUS_MISMATCH,
                message="Статус объекта не совпадает с ожидаемым.",
                expected=expected_status.value,
                actual=actual_status.value,
            )
        except StorageConnectionError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_status",
                expected=expected_status.value,
            ) from exc
        except StorageError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="verify_object_status",
                expected=expected_status.value,
            ) from exc

        actual_status = resolved_object_info.status

        if actual_status == expected_status:
            return StorageIntegrityStatus(
                is_success=True,
                message="Статус объекта совпадает с ожидаемым.",
                expected=expected_status.value,
                actual=actual_status.value,
            )

        return StorageIntegrityStatus(
            is_success=False,
            problem_type=StorageIntegrityProblemType.OBJECT_STATUS_MISMATCH,
            message="Статус объекта не совпадает с ожидаемым.",
            expected=expected_status.value,
            actual=actual_status.value,
        )

    async def verify_object(
        self,
        *,
        bucket: str,
        object_key: str,
        expected_size_bytes: int | None = None,
        expected_checksum: str | None = None,
        expected_checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
        expected_metadata: Mapping[str, Any] | StorageObjectMetadata | None = None,
        expected_status: StorageObjectStatus | None = None,
        require_exact_metadata_match: bool = False,
    ) -> StorageIntegrityReport:
        """Выполняет комплексную проверку объекта.

        Метод является алиасом для ``build_integrity_report``.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expected_size_bytes: Ожидаемый размер объекта в байтах.
            expected_checksum: Ожидаемая контрольная сумма.
            expected_checksum_algorithm: Алгоритм ожидаемой контрольной суммы.
            expected_metadata: Ожидаемые metadata.
            expected_status: Ожидаемый статус объекта.
            require_exact_metadata_match: Требовать точного совпадения
                metadata.

        Returns:
            Отчёт проверки целостности объекта.

        Raises:
            StorageIntegrityError: Если входные параметры некорректны или
                проверка не удалась из-за инфраструктурной ошибки.
        """

        return await self.build_integrity_report(
            bucket=bucket,
            object_key=object_key,
            expected_size_bytes=expected_size_bytes,
            expected_checksum=expected_checksum,
            expected_checksum_algorithm=expected_checksum_algorithm,
            expected_metadata=expected_metadata,
            expected_status=expected_status,
            require_exact_metadata_match=require_exact_metadata_match,
        )

    async def build_integrity_report(
        self,
        *,
        bucket: str,
        object_key: str,
        expected_size_bytes: int | None = None,
        expected_checksum: str | None = None,
        expected_checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
        expected_metadata: Mapping[str, Any] | StorageObjectMetadata | None = None,
        expected_status: StorageObjectStatus | None = None,
        require_exact_metadata_match: bool = False,
    ) -> StorageIntegrityReport:
        """Строит отчёт проверки целостности объекта.

        Если объект отсутствует, это отражается в отчёте как проблема.
        Критичными ошибками считаются инфраструктурные сбои и некорректные
        входные параметры проверки.

        Args:
            bucket: Имя bucket.
            object_key: Ключ объекта.
            expected_size_bytes: Ожидаемый размер объекта в байтах.
            expected_checksum: Ожидаемая контрольная сумма.
            expected_checksum_algorithm: Алгоритм ожидаемой контрольной суммы.
            expected_metadata: Ожидаемые metadata.
            expected_status: Ожидаемый статус объекта.
            require_exact_metadata_match: Требовать точного совпадения
                metadata.

        Returns:
            Отчёт проверки целостности объекта.

        Raises:
            StorageIntegrityError: Если входные параметры некорректны или
                проверка не удалась из-за инфраструктурной ошибки.
        """

        checked_at = datetime.now(UTC)
        problems: list[StorageIntegrityStatus] = []

        self._validate_checksum_expectation(
            expected_checksum=expected_checksum,
            expected_checksum_algorithm=expected_checksum_algorithm,
        )

        if expected_size_bytes is not None:
            self._validate_expected_size(expected_size_bytes)

        object_info: StorageObjectInfo | None = None

        try:
            object_info = await self.object_manager.stat_object(
                bucket=bucket,
                object_key=object_key,
            )
            exists_status = StorageIntegrityStatus(
                is_success=True,
                message="Объект найден в хранилище.",
            )
            object_exists = True
        except StorageObjectNotFoundError:
            exists_status = StorageIntegrityStatus(
                is_success=False,
                problem_type=StorageIntegrityProblemType.OBJECT_NOT_FOUND,
                message="Объект отсутствует в хранилище.",
                expected=True,
                actual=False,
            )
            object_exists = False
            problems.append(exists_status)
        except StorageConnectionError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="build_integrity_report",
            ) from exc
        except StorageError as exc:
            raise self._critical_integrity_error(
                exc,
                bucket=bucket,
                object_key=object_key,
                operation="build_integrity_report",
            ) from exc

        size_status: StorageIntegrityStatus | None = None
        checksum_status: StorageIntegrityStatus | None = None
        metadata_status: StorageIntegrityStatus | None = None
        object_status: StorageIntegrityStatus | None = None

        if object_exists and expected_size_bytes is not None:
            size_status = await self.verify_object_size(
                bucket=bucket,
                object_key=object_key,
                expected_size_bytes=expected_size_bytes,
                object_info=object_info,
            )

            if not size_status.is_success:
                problems.append(size_status)

        if (
            object_exists
            and expected_checksum is not None
            and expected_checksum_algorithm is not None
        ):
            checksum_status = await self.verify_object_checksum(
                bucket=bucket,
                object_key=object_key,
                expected_checksum=expected_checksum,
                expected_checksum_algorithm=expected_checksum_algorithm,
            )

            if not checksum_status.is_success:
                problems.append(checksum_status)

        if object_exists and expected_metadata is not None:
            metadata_status = await self.verify_object_metadata(
                bucket=bucket,
                object_key=object_key,
                expected_metadata=expected_metadata,
                object_info=object_info,
                require_exact_match=require_exact_metadata_match,
            )

            if not metadata_status.is_success:
                problems.append(metadata_status)

        if expected_status is not None:
            object_status = await self.verify_object_status(
                bucket=bucket,
                object_key=object_key,
                expected_status=expected_status,
                object_info=object_info,
            )

            if not object_status.is_success:
                problems.append(object_status)

        return StorageIntegrityReport(
            bucket=bucket,
            object_key=object_key,
            checked_at=checked_at,
            object_exists=object_exists,
            size_status=size_status,
            checksum_status=checksum_status,
            metadata_status=metadata_status,
            object_status=object_status,
            problems=problems,
        )

    @staticmethod
    def _validate_expected_size(expected_size_bytes: int) -> None:
        """Проверяет ожидаемый размер объекта.

        Args:
            expected_size_bytes: Ожидаемый размер объекта в байтах.

        Returns:
            ``None``.

        Raises:
            StorageIntegrityError: Если ожидаемый размер некорректен.
        """

        if not isinstance(expected_size_bytes, int) or isinstance(
            expected_size_bytes,
            bool,
        ):
            raise StorageIntegrityError(
                "Ожидаемый размер объекта должен быть целым числом.",
                expected=expected_size_bytes,
                details={
                    "value_type": type(expected_size_bytes).__name__,
                },
            )

        if expected_size_bytes < 0:
            raise StorageIntegrityError(
                "Ожидаемый размер объекта не может быть отрицательным.",
                expected=expected_size_bytes,
            )

    @staticmethod
    def _normalize_expected_checksum(expected_checksum: str) -> str:
        """Нормализует ожидаемый checksum.

        Args:
            expected_checksum: Исходное ожидаемое значение checksum.

        Returns:
            Нормализованный checksum.

        Raises:
            StorageIntegrityError: Если checksum некорректен.
        """

        if not isinstance(expected_checksum, str):
            raise StorageIntegrityError(
                "Ожидаемый checksum должен быть строкой.",
                expected=expected_checksum,
                details={
                    "value_type": type(expected_checksum).__name__,
                },
            )

        normalized_checksum = expected_checksum.strip().lower()

        if not normalized_checksum:
            raise StorageIntegrityError(
                "Ожидаемый checksum не может быть пустым.",
                expected=expected_checksum,
            )

        return normalized_checksum

    @staticmethod
    def _validate_checksum_expectation(
        *,
        expected_checksum: str | None,
        expected_checksum_algorithm: StorageChecksumAlgorithm | str | None,
    ) -> None:
        """Проверяет согласованность ожиданий для checksum.

        Args:
            expected_checksum: Ожидаемая контрольная сумма.
            expected_checksum_algorithm: Алгоритм ожидаемой контрольной суммы.

        Returns:
            ``None``.

        Raises:
            StorageIntegrityError: Если передана только часть checksum-ожидания
                или одно из значений некорректно.
        """

        if expected_checksum is None and expected_checksum_algorithm is None:
            return

        if expected_checksum is None:
            raise StorageIntegrityError(
                "Для проверки checksum не передано ожидаемое значение.",
                details={
                    "field": "expected_checksum",
                },
            )

        if expected_checksum_algorithm is None:
            raise StorageIntegrityError(
                "Для проверки checksum не передан алгоритм.",
                expected=expected_checksum,
                details={
                    "field": "expected_checksum_algorithm",
                },
            )

        StorageIntegrityChecker._normalize_expected_checksum(expected_checksum)
        normalize_checksum_algorithm(expected_checksum_algorithm)

    @staticmethod
    def _critical_integrity_error(
        exc: StorageError,
        *,
        bucket: str,
        object_key: str,
        operation: str,
        expected: Any | None = None,
    ) -> StorageIntegrityError:
        """Создаёт критическую ошибку проверки целостности.

        Args:
            exc: Исходная ошибка хранилища.
            bucket: Имя bucket.
            object_key: Ключ объекта.
            operation: Название выполняемой операции.
            expected: Ожидаемое значение, связанное с проверкой.

        Returns:
            Ошибка проверки целостности.
        """

        details = dict(exc.details)
        details.setdefault("reason", exc.message)
        details["operation"] = operation
        details["error_type"] = exc.__class__.__name__

        return StorageIntegrityError(
            "Проверка целостности объекта хранилища не удалась.",
            bucket=bucket,
            object_key=object_key,
            expected=expected,
            details=details,
            cause=exc,
        )


def create_hash(algorithm: StorageChecksumAlgorithm) -> Any:
    """Создаёт hash-объект для указанного алгоритма.

    Args:
        algorithm: Алгоритм контрольной суммы.

    Returns:
        Hash-объект из ``hashlib``.

    Raises:
        StorageIntegrityError: Если алгоритм не поддерживается.
    """

    hash_factory = HASH_FACTORY_BY_ALGORITHM.get(algorithm)

    if hash_factory is None:
        raise StorageIntegrityError(
            "Неподдерживаемый алгоритм контрольной суммы.",
            algorithm=algorithm.value,
            details={
                "algorithm": algorithm.value,
            },
        )

    return hash_factory()
