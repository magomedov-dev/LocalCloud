from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from core.constants import StorageConstants
from storage.exceptions import InvalidStorageMetadataError
from storage.keys import sanitize_filename_for_metadata
from storage.types import StorageChecksumAlgorithm, StorageObjectMetadata


def normalize_metadata_key(key: str) -> str:
    """Нормализует ключ метаданных.

    Ключ приводится к нижнему регистру, пробелы заменяются на ``_``, символ
    ``-`` сохраняется. Остальные небезопасные символы не допускаются.

    Args:
        key: Исходный ключ метаданных.

    Returns:
        Нормализованный ключ метаданных.

    Raises:
        InvalidStorageMetadataError: Если ключ не является строкой, пустой,
            слишком длинный или содержит недопустимые символы.
    """

    if not isinstance(key, str):
        raise InvalidStorageMetadataError(
            "Ключ metadata должен быть строкой.",
            reason="metadata_key_is_not_string",
            details={
                "value_type": type(key).__name__,
            },
        )

    normalized_key = key.strip().lower().replace(" ", "_")

    if not normalized_key:
        raise InvalidStorageMetadataError(
            "Ключ metadata не может быть пустым.",
            metadata_key=key,
            reason="empty_metadata_key",
        )

    if len(normalized_key) > StorageConstants.STORAGE_METADATA_KEY_MAX_LENGTH:
        raise InvalidStorageMetadataError(
            "Ключ metadata превышает максимально допустимую длину.",
            metadata_key=normalized_key,
            reason="metadata_key_too_long",
            details={
                "length": len(normalized_key),
                "max_length": StorageConstants.STORAGE_METADATA_KEY_MAX_LENGTH,
            },
        )

    if not StorageConstants.ALLOWED_METADATA_KEY_PATTERN.fullmatch(normalized_key):
        raise InvalidStorageMetadataError(
            "Ключ metadata содержит недопустимые символы.",
            metadata_key=normalized_key,
            reason="invalid_metadata_key",
            details={
                "allowed_pattern": StorageConstants.ALLOWED_METADATA_KEY_PATTERN.pattern,
            },
        )

    return normalized_key


def normalize_metadata_value(value: Any) -> str | None:
    """Нормализует значение метаданных.

    Пустые значения возвращаются как ``None``, чтобы затем быть удалёнными из
    итогового набора метаданных.

    Args:
        value: Исходное значение метаданных.

    Returns:
        Нормализованное строковое значение или ``None``, если значение пустое.

    Raises:
        InvalidStorageMetadataError: Если значение имеет неподдерживаемый тип,
            содержит запрещённые символы или превышает максимально допустимую
            длину.
    """

    if value is None:
        return None

    if isinstance(value, uuid.UUID):
        normalized_value = str(value)
    elif isinstance(value, StorageChecksumAlgorithm):
        normalized_value = value.value
    elif isinstance(value, datetime):
        normalized_value = value.isoformat()
    elif isinstance(value, str):
        normalized_value = value.strip()
    elif isinstance(value, bool):
        normalized_value = "true" if value else "false"
    elif isinstance(value, int | float):
        normalized_value = str(value)
    else:
        raise InvalidStorageMetadataError(
            "Значение metadata имеет неподдерживаемый тип.",
            metadata_value=value,
            reason="unsupported_metadata_value_type",
            details={
                "value_type": type(value).__name__,
            },
        )

    if not normalized_value:
        return None

    if StorageConstants.FORBIDDEN_METADATA_VALUE_CHARS_PATTERN.search(normalized_value):
        raise InvalidStorageMetadataError(
            "Значение metadata не должно содержать переносы строк.",
            metadata_value=normalized_value,
            reason="metadata_value_contains_newline",
        )

    if len(normalized_value) > StorageConstants.STORAGE_METADATA_VALUE_MAX_LENGTH:
        raise InvalidStorageMetadataError(
            "Значение metadata превышает максимально допустимую длину.",
            metadata_value=normalized_value,
            reason="metadata_value_too_long",
            details={
                "length": len(normalized_value),
                "max_length": StorageConstants.STORAGE_METADATA_VALUE_MAX_LENGTH,
            },
        )

    return normalized_value


def normalize_metadata(
    metadata: Mapping[str, Any] | StorageObjectMetadata | None,
) -> StorageObjectMetadata:
    """Нормализует набор метаданных и удаляет пустые значения.

    Args:
        metadata: Исходные метаданные в виде ``Mapping``,
            ``StorageObjectMetadata`` или ``None``.

    Returns:
        Нормализованный объект ``StorageObjectMetadata``.

    Raises:
        InvalidStorageMetadataError: Если метаданные имеют неподдерживаемый тип,
            содержат некорректные ключи или значения либо превышают общий
            допустимый размер.
    """

    if metadata is None:
        return StorageObjectMetadata()

    if isinstance(metadata, StorageObjectMetadata):
        raw_metadata: Mapping[str, Any] = metadata.values
    elif isinstance(metadata, Mapping):
        raw_metadata = metadata
    else:
        raise InvalidStorageMetadataError(
            "Метаданные должны быть словарём или StorageObjectMetadata.",
            reason="metadata_is_not_mapping",
            details={
                "value_type": type(metadata).__name__,
            },
        )

    normalized_values: dict[str, str] = {}

    for raw_key, raw_value in raw_metadata.items():
        normalized_key = normalize_metadata_key(raw_key)
        normalized_value = normalize_metadata_value(raw_value)

        if normalized_value is None:
            continue

        normalized_values[normalized_key] = normalized_value

    normalized_metadata = StorageObjectMetadata(values=normalized_values)
    validate_metadata(normalized_metadata)

    return normalized_metadata


def validate_metadata(
    metadata: Mapping[str, Any] | StorageObjectMetadata | None,
) -> StorageObjectMetadata:
    """Проверяет метаданные и возвращает нормализованный объект.

    Args:
        metadata: Метаданные в виде ``Mapping``, ``StorageObjectMetadata`` или
            ``None``.

    Returns:
        Проверенный и нормализованный объект ``StorageObjectMetadata``.

    Raises:
        InvalidStorageMetadataError: Если метаданные имеют неподдерживаемый тип,
            содержат некорректные ключи или значения либо превышают общий
            допустимый размер.
    """

    if metadata is None:
        return StorageObjectMetadata()

    if isinstance(metadata, StorageObjectMetadata):
        metadata_object = metadata
    else:
        metadata_object = normalize_metadata(metadata)

    total_size = 0
    normalized_values: dict[str, str] = {}

    for key, value in metadata_object.values.items():
        normalized_key = normalize_metadata_key(key)
        normalized_value = normalize_metadata_value(value)

        if normalized_value is None:
            continue

        total_size += len(normalized_key.encode("utf-8"))
        total_size += len(normalized_value.encode("utf-8"))
        normalized_values[normalized_key] = normalized_value

    if total_size > StorageConstants.STORAGE_METADATA_TOTAL_MAX_SIZE:
        raise InvalidStorageMetadataError(
            "Общий размер metadata превышает максимально допустимый размер.",
            reason="metadata_total_size_too_large",
            details={
                "total_size": total_size,
                "max_size": StorageConstants.STORAGE_METADATA_TOTAL_MAX_SIZE,
            },
        )

    return StorageObjectMetadata(values=normalized_values)


def metadata_to_headers(
    metadata: Mapping[str, Any] | StorageObjectMetadata | None,
    *,
    prefix: str = "x-amz-meta-",
) -> dict[str, str]:
    """Преобразует метаданные в HTTP-заголовки S3.

    MinIO/S3 принимает пользовательские метаданные как заголовки с префиксом
    ``x-amz-meta-``.

    Args:
        metadata: Исходные метаданные.
        prefix: Префикс HTTP-заголовков метаданных.

    Returns:
        Словарь HTTP-заголовков S3.

    Raises:
        InvalidStorageMetadataError: Если метаданные некорректны.
    """

    normalized_metadata = normalize_metadata(metadata)

    return {
        f"{prefix}{key}": value for key, value in normalized_metadata.values.items()
    }


def metadata_from_headers(
    headers: Mapping[str, Any] | None,
    *,
    prefix: str = "x-amz-meta-",
) -> StorageObjectMetadata:
    """Извлекает пользовательские метаданные из HTTP/S3-заголовков.

    Args:
        headers: Исходные HTTP/S3-заголовки.
        prefix: Префикс заголовков пользовательских метаданных.

    Returns:
        Нормализованный объект ``StorageObjectMetadata``.

    Raises:
        InvalidStorageMetadataError: Если извлечённые метаданные некорректны.
    """

    if headers is None:
        return StorageObjectMetadata()

    prefix_lower = prefix.lower()
    values: dict[str, Any] = {}

    for raw_key, raw_value in headers.items():
        header_key = str(raw_key).strip()
        header_key_lower = header_key.lower()

        if not header_key_lower.startswith(prefix_lower):
            continue

        metadata_key = header_key_lower.removeprefix(prefix_lower)
        values[metadata_key] = raw_value

    return normalize_metadata(values)


def build_file_metadata(
    *,
    user_id: uuid.UUID | str,
    file_id: uuid.UUID | str,
    version_id: uuid.UUID | str | None = None,
    checksum: str | None = None,
    checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
    original_filename: str | None = None,
    content_type: str | None = None,
    created_by: uuid.UUID | str | None = None,
    extra: Mapping[str, Any] | StorageObjectMetadata | None = None,
) -> StorageObjectMetadata:
    """Формирует метаданные для объекта файла.

    Args:
        user_id: Идентификатор пользователя-владельца файла.
        file_id: Идентификатор файла.
        version_id: Идентификатор версии файла.
        checksum: Контрольная сумма объекта.
        checksum_algorithm: Алгоритм контрольной суммы.
        original_filename: Исходное пользовательское имя файла.
        content_type: MIME-тип содержимого объекта.
        created_by: Идентификатор пользователя, создавшего объект.
        extra: Дополнительные метаданные, переопределяющие базовые значения.

    Returns:
        Нормализованные метаданные объекта файла.

    Raises:
        InvalidStorageMetadataError: Если идентификаторы,
            ``checksum_algorithm``, дополнительные метаданные или итоговый набор
            метаданных некорректны.
    """

    metadata = _base_metadata(
        user_id=user_id,
        file_id=file_id,
        version_id=version_id,
        checksum=checksum,
        checksum_algorithm=checksum_algorithm,
        original_filename=original_filename,
        content_type=content_type,
        created_by=created_by,
    )

    return merge_metadata(metadata, extra)


def build_file_version_metadata(
    *,
    user_id: uuid.UUID | str,
    file_id: uuid.UUID | str,
    version_id: uuid.UUID | str,
    checksum: str | None = None,
    checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
    original_filename: str | None = None,
    content_type: str | None = None,
    created_by: uuid.UUID | str | None = None,
    extra: Mapping[str, Any] | StorageObjectMetadata | None = None,
) -> StorageObjectMetadata:
    """Формирует метаданные для объекта версии файла.

    Args:
        user_id: Идентификатор пользователя-владельца файла.
        file_id: Идентификатор файла.
        version_id: Идентификатор версии файла.
        checksum: Контрольная сумма объекта.
        checksum_algorithm: Алгоритм контрольной суммы.
        original_filename: Исходное пользовательское имя файла.
        content_type: MIME-тип содержимого объекта.
        created_by: Идентификатор пользователя, создавшего объект.
        extra: Дополнительные метаданные, переопределяющие базовые значения.

    Returns:
        Нормализованные метаданные объекта версии файла.

    Raises:
        InvalidStorageMetadataError: Если идентификаторы,
            ``checksum_algorithm``, дополнительные метаданные или итоговый набор
            метаданных некорректны.
    """

    metadata = _base_metadata(
        user_id=user_id,
        file_id=file_id,
        version_id=version_id,
        checksum=checksum,
        checksum_algorithm=checksum_algorithm,
        original_filename=original_filename,
        content_type=content_type,
        created_by=created_by,
    )

    return merge_metadata(metadata, extra)


def build_upload_metadata(
    *,
    user_id: uuid.UUID | str,
    upload_session_id: uuid.UUID | str,
    file_id: uuid.UUID | str | None = None,
    checksum: str | None = None,
    checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
    original_filename: str | None = None,
    content_type: str | None = None,
    created_by: uuid.UUID | str | None = None,
    extra: Mapping[str, Any] | StorageObjectMetadata | None = None,
) -> StorageObjectMetadata:
    """Формирует метаданные для временного объекта или multipart-загрузки.

    Args:
        user_id: Идентификатор пользователя-владельца загрузки.
        upload_session_id: Идентификатор upload-сессии.
        file_id: Идентификатор файла, связанного с загрузкой.
        checksum: Контрольная сумма объекта.
        checksum_algorithm: Алгоритм контрольной суммы.
        original_filename: Исходное пользовательское имя файла.
        content_type: MIME-тип содержимого объекта.
        created_by: Идентификатор пользователя, создавшего объект.
        extra: Дополнительные метаданные, переопределяющие базовые значения.

    Returns:
        Нормализованные метаданные временного объекта или multipart-загрузки.

    Raises:
        InvalidStorageMetadataError: Если идентификаторы,
            ``checksum_algorithm``, дополнительные метаданные или итоговый набор
            метаданных некорректны.
    """

    metadata: dict[str, Any] = {
        "user_id": _normalize_uuid_like(user_id, field_name="user_id"),
        "upload_session_id": _normalize_uuid_like(
            upload_session_id,
            field_name="upload_session_id",
        ),
        "file_id": (
            _normalize_uuid_like(file_id, field_name="file_id")
            if file_id is not None
            else None
        ),
        "checksum": checksum,
        "checksum_algorithm": _normalize_checksum_algorithm(checksum_algorithm),
        "original_filename": sanitize_filename_for_metadata(original_filename),
        "content_type": content_type,
        "created_by": (
            _normalize_uuid_like(created_by, field_name="created_by")
            if created_by is not None
            else None
        ),
    }

    return merge_metadata(metadata, extra)


def build_archive_metadata(
    *,
    user_id: uuid.UUID | str,
    task_id: uuid.UUID | str,
    original_filename: str | None = "archive.zip",
    content_type: str | None = "application/zip",
    created_by: uuid.UUID | str | None = None,
    checksum: str | None = None,
    checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
    extra: Mapping[str, Any] | StorageObjectMetadata | None = None,
) -> StorageObjectMetadata:
    """Формирует метаданные для объекта архива папки.

    Args:
        user_id: Идентификатор пользователя-владельца архива.
        task_id: Идентификатор задачи формирования архива.
        original_filename: Исходное имя файла архива.
        content_type: MIME-тип архива.
        created_by: Идентификатор пользователя, создавшего объект.
        checksum: Контрольная сумма объекта.
        checksum_algorithm: Алгоритм контрольной суммы.
        extra: Дополнительные метаданные, переопределяющие базовые значения.

    Returns:
        Нормализованные метаданные объекта архива.

    Raises:
        InvalidStorageMetadataError: Если идентификаторы,
            ``checksum_algorithm``, дополнительные метаданные или итоговый набор
            метаданных некорректны.
    """

    metadata: dict[str, Any] = {
        "user_id": _normalize_uuid_like(user_id, field_name="user_id"),
        "task_id": _normalize_uuid_like(task_id, field_name="task_id"),
        "checksum": checksum,
        "checksum_algorithm": _normalize_checksum_algorithm(checksum_algorithm),
        "original_filename": sanitize_filename_for_metadata(original_filename),
        "content_type": content_type,
        "created_by": (
            _normalize_uuid_like(created_by, field_name="created_by")
            if created_by is not None
            else None
        ),
    }

    return merge_metadata(metadata, extra)


def build_preview_metadata(
    *,
    user_id: uuid.UUID | str,
    file_id: uuid.UUID | str,
    version_id: uuid.UUID | str | None = None,
    task_id: uuid.UUID | str | None = None,
    original_filename: str | None = None,
    content_type: str | None = None,
    created_by: uuid.UUID | str | None = None,
    checksum: str | None = None,
    checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
    extra: Mapping[str, Any] | StorageObjectMetadata | None = None,
) -> StorageObjectMetadata:
    """Формирует метаданные для объекта предпросмотра файла.

    Args:
        user_id: Идентификатор пользователя-владельца файла.
        file_id: Идентификатор файла.
        version_id: Идентификатор версии файла.
        task_id: Идентификатор задачи формирования предпросмотра.
        original_filename: Исходное пользовательское имя файла.
        content_type: MIME-тип содержимого предпросмотра.
        created_by: Идентификатор пользователя, создавшего объект.
        checksum: Контрольная сумма объекта.
        checksum_algorithm: Алгоритм контрольной суммы.
        extra: Дополнительные метаданные, переопределяющие базовые значения.

    Returns:
        Нормализованные метаданные объекта предпросмотра.

    Raises:
        InvalidStorageMetadataError: Если идентификаторы,
            ``checksum_algorithm``, дополнительные метаданные или итоговый набор
            метаданных некорректны.
    """

    metadata = _base_metadata(
        user_id=user_id,
        file_id=file_id,
        version_id=version_id,
        checksum=checksum,
        checksum_algorithm=checksum_algorithm,
        original_filename=original_filename,
        content_type=content_type,
        created_by=created_by,
    )

    metadata["task_id"] = (
        _normalize_uuid_like(task_id, field_name="task_id")
        if task_id is not None
        else None
    )

    return merge_metadata(metadata, extra)


def build_public_metadata(
    *,
    public_link_id: uuid.UUID | str,
    file_id: uuid.UUID | str,
    version_id: uuid.UUID | str | None = None,
    original_filename: str | None = None,
    content_type: str | None = None,
    checksum: str | None = None,
    checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
    extra: Mapping[str, Any] | StorageObjectMetadata | None = None,
) -> StorageObjectMetadata:
    """Формирует метаданные для подготовленного публичного объекта.

    Args:
        public_link_id: Идентификатор публичной ссылки.
        file_id: Идентификатор файла.
        version_id: Идентификатор версии файла.
        original_filename: Исходное пользовательское имя файла.
        content_type: MIME-тип содержимого объекта.
        checksum: Контрольная сумма объекта.
        checksum_algorithm: Алгоритм контрольной суммы.
        extra: Дополнительные метаданные, переопределяющие базовые значения.

    Returns:
        Нормализованные метаданные подготовленного публичного объекта.

    Raises:
        InvalidStorageMetadataError: Если идентификаторы,
            ``checksum_algorithm``, дополнительные метаданные или итоговый набор
            метаданных некорректны.
    """

    metadata: dict[str, Any] = {
        "public_link_id": _normalize_uuid_like(
            public_link_id,
            field_name="public_link_id",
        ),
        "file_id": _normalize_uuid_like(file_id, field_name="file_id"),
        "version_id": (
            _normalize_uuid_like(version_id, field_name="version_id")
            if version_id is not None
            else None
        ),
        "checksum": checksum,
        "checksum_algorithm": _normalize_checksum_algorithm(checksum_algorithm),
        "original_filename": sanitize_filename_for_metadata(original_filename),
        "content_type": content_type,
    }

    return merge_metadata(metadata, extra)


def merge_metadata(
    *metadata_items: Mapping[str, Any] | StorageObjectMetadata | None,
) -> StorageObjectMetadata:
    """Объединяет несколько наборов метаданных.

    Более поздние наборы переопределяют значения из предыдущих. Пустые значения
    удаляются.

    Args:
        *metadata_items: Наборы метаданных для объединения.

    Returns:
        Нормализованный объединённый объект ``StorageObjectMetadata``.

    Raises:
        InvalidStorageMetadataError: Если один из наборов метаданных
            некорректен или итоговый набор превышает допустимые ограничения.
    """

    merged: dict[str, Any] = {}

    for metadata in metadata_items:
        normalized_metadata = normalize_metadata(metadata)

        for key, value in normalized_metadata.values.items():
            merged[key] = value

    return normalize_metadata(merged)


def filter_empty_metadata(
    metadata: Mapping[str, Any] | StorageObjectMetadata | None,
) -> StorageObjectMetadata:
    """Удаляет метаданные с пустыми значениями.

    Args:
        metadata: Исходные метаданные.

    Returns:
        Метаданные без пустых значений.

    Raises:
        InvalidStorageMetadataError: Если исходные метаданные содержат
            некорректные значения.
    """

    if metadata is None:
        return StorageObjectMetadata()

    raw_metadata = (
        metadata.values if isinstance(metadata, StorageObjectMetadata) else metadata
    )

    filtered = {
        key: value
        for key, value in raw_metadata.items()
        if normalize_metadata_value(value) is not None
    }

    return normalize_metadata(filtered)


def remove_metadata_keys(
    metadata: Mapping[str, Any] | StorageObjectMetadata | None,
    *keys: str,
) -> StorageObjectMetadata:
    """Удаляет указанные ключи из метаданных.

    Args:
        metadata: Исходные метаданные.
        *keys: Ключи метаданных, которые нужно удалить.

    Returns:
        Метаданные без указанных ключей.

    Raises:
        InvalidStorageMetadataError: Если исходные метаданные или один из
            ключей некорректны.
    """

    normalized_metadata = normalize_metadata(metadata)
    keys_to_remove = {normalize_metadata_key(key) for key in keys}

    return StorageObjectMetadata(
        values={
            key: value
            for key, value in normalized_metadata.values.items()
            if key not in keys_to_remove
        }
    )


def pick_metadata_keys(
    metadata: Mapping[str, Any] | StorageObjectMetadata | None,
    *keys: str,
) -> StorageObjectMetadata:
    """Оставляет в метаданных только указанные ключи.

    Args:
        metadata: Исходные метаданные.
        *keys: Ключи метаданных, которые нужно оставить.

    Returns:
        Метаданные только с указанными ключами.

    Raises:
        InvalidStorageMetadataError: Если исходные метаданные или один из
            ключей некорректны.
    """

    normalized_metadata = normalize_metadata(metadata)
    keys_to_pick = {normalize_metadata_key(key) for key in keys}

    return StorageObjectMetadata(
        values={
            key: value
            for key, value in normalized_metadata.values.items()
            if key in keys_to_pick
        }
    )


def has_metadata_key(
    metadata: Mapping[str, Any] | StorageObjectMetadata | None,
    key: str,
) -> bool:
    """Проверяет наличие ключа в метаданных.

    Args:
        metadata: Исходные метаданные.
        key: Проверяемый ключ метаданных.

    Returns:
        ``True``, если ключ присутствует в метаданных.

    Raises:
        InvalidStorageMetadataError: Если исходные метаданные или ключ
            некорректны.
    """

    normalized_metadata = normalize_metadata(metadata)
    normalized_key = normalize_metadata_key(key)

    return normalized_key in normalized_metadata.values


def get_metadata_value(
    metadata: Mapping[str, Any] | StorageObjectMetadata | None,
    key: str,
    default: str | None = None,
) -> str | None:
    """Возвращает значение метаданных по ключу.

    Args:
        metadata: Исходные метаданные.
        key: Ключ метаданных.
        default: Значение по умолчанию, если ключ отсутствует.

    Returns:
        Значение метаданных или ``default``.

    Raises:
        InvalidStorageMetadataError: Если исходные метаданные или ключ
            некорректны.
    """

    normalized_metadata = normalize_metadata(metadata)
    normalized_key = normalize_metadata_key(key)

    return normalized_metadata.values.get(normalized_key, default)


def _base_metadata(
    *,
    user_id: uuid.UUID | str,
    file_id: uuid.UUID | str,
    version_id: uuid.UUID | str | None = None,
    checksum: str | None = None,
    checksum_algorithm: StorageChecksumAlgorithm | str | None = None,
    original_filename: str | None = None,
    content_type: str | None = None,
    created_by: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Формирует базовый набор метаданных объекта файла.

    Args:
        user_id: Идентификатор пользователя-владельца файла.
        file_id: Идентификатор файла.
        version_id: Идентификатор версии файла.
        checksum: Контрольная сумма объекта.
        checksum_algorithm: Алгоритм контрольной суммы.
        original_filename: Исходное пользовательское имя файла.
        content_type: MIME-тип содержимого объекта.
        created_by: Идентификатор пользователя, создавшего объект.

    Returns:
        Словарь базовых метаданных.

    Raises:
        InvalidStorageMetadataError: Если идентификаторы или
            ``checksum_algorithm`` некорректны.
    """

    return {
        "user_id": _normalize_uuid_like(user_id, field_name="user_id"),
        "file_id": _normalize_uuid_like(file_id, field_name="file_id"),
        "version_id": (
            _normalize_uuid_like(version_id, field_name="version_id")
            if version_id is not None
            else None
        ),
        "checksum": checksum,
        "checksum_algorithm": _normalize_checksum_algorithm(checksum_algorithm),
        "original_filename": sanitize_filename_for_metadata(original_filename),
        "content_type": content_type,
        "created_by": (
            _normalize_uuid_like(created_by, field_name="created_by")
            if created_by is not None
            else None
        ),
    }


def _normalize_uuid_like(value: uuid.UUID | str, *, field_name: str) -> str:
    """Нормализует UUID-подобное значение метаданных.

    Args:
        value: ``UUID`` или строковое представление ``UUID``.
        field_name: Название поля метаданных для сообщения об ошибке.

    Returns:
        Строковое представление ``UUID``.

    Raises:
        InvalidStorageMetadataError: Если значение пустое, имеет
            неподдерживаемый тип или не является валидным ``UUID``.
    """

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, str):
        normalized_value = value.strip()

        if not normalized_value:
            raise InvalidStorageMetadataError(
                "UUID-значение метаданных не может быть пустым.",
                metadata_key=field_name,
                metadata_value=value,
                reason="empty_uuid_metadata_value",
            )

        try:
            return str(uuid.UUID(normalized_value))
        except ValueError as exc:
            raise InvalidStorageMetadataError(
                "Метаданные содержат некорректное UUID-значение.",
                metadata_key=field_name,
                metadata_value=value,
                reason="invalid_uuid_metadata_value",
            ) from exc

    raise InvalidStorageMetadataError(
        "UUID-значение metadata должно быть uuid.UUID или строкой.",
        metadata_key=field_name,
        metadata_value=value,
        reason="unsupported_uuid_metadata_value_type",
        details={
            "value_type": type(value).__name__,
        },
    )


def _normalize_checksum_algorithm(
    checksum_algorithm: StorageChecksumAlgorithm | str | None,
) -> str | None:
    """Нормализует алгоритм контрольной суммы.

    Args:
        checksum_algorithm: Алгоритм контрольной суммы в виде enum, строки или
            ``None``.

    Returns:
        Строковое значение алгоритма или ``None``.

    Raises:
        InvalidStorageMetadataError: Если алгоритм имеет неподдерживаемый тип
            или не входит в список поддерживаемых алгоритмов.
    """

    if checksum_algorithm is None:
        return None

    if isinstance(checksum_algorithm, StorageChecksumAlgorithm):
        return checksum_algorithm.value

    if isinstance(checksum_algorithm, str):
        normalized_algorithm = checksum_algorithm.strip().lower()

        if not normalized_algorithm:
            return None

        try:
            return StorageChecksumAlgorithm(normalized_algorithm).value
        except ValueError as exc:
            raise InvalidStorageMetadataError(
                "Неподдерживаемый алгоритм контрольной суммы.",
                metadata_key="checksum_algorithm",
                metadata_value=checksum_algorithm,
                reason="unsupported_checksum_algorithm",
                details={
                    "allowed_algorithms": [
                        algorithm.value for algorithm in StorageChecksumAlgorithm
                    ],
                },
            ) from exc

    raise InvalidStorageMetadataError(
        "Алгоритм контрольной суммы должен быть строкой или StorageChecksumAlgorithm.",
        metadata_key="checksum_algorithm",
        metadata_value=checksum_algorithm,
        reason="invalid_checksum_algorithm_type",
        details={
            "value_type": type(checksum_algorithm).__name__,
        },
    )
