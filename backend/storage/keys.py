from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from core.constants import StorageConstants
from storage.exceptions import InvalidStorageKeyError


def normalize_object_key(object_key: str) -> str:
    """Нормализует ``object_key`` для MinIO/S3.

    Удаляет внешние пробелы, но не исправляет опасные пути автоматически.
    Значения с ``..``, обратными слэшами, абсолютными путями и повторяющимися
    слэшами считаются ошибкой.

    Args:
        object_key: Исходный ключ объекта.

    Returns:
        Нормализованный ключ объекта.

    Raises:
        InvalidStorageKeyError: Если ключ равен ``None`` или не проходит
            валидацию.
    """

    if object_key is None:
        raise InvalidStorageKeyError(
            "Ключ объекта не может быть None.",
            reason="object_key_is_none",
        )

    normalized_key = object_key.strip()
    validate_object_key(normalized_key)

    return normalized_key


def validate_object_key(object_key: str) -> str:
    """Проверяет корректность ``object_key``.

    Args:
        object_key: Ключ объекта для проверки.

    Returns:
        Исходный ключ объекта, если он корректен.

    Raises:
        InvalidStorageKeyError: Если ключ не является строкой, пустой,
            слишком длинный, содержит небезопасные символы, является
            абсолютным путём или содержит недопустимые сегменты.
    """

    if not isinstance(object_key, str):
        raise InvalidStorageKeyError(
            "Ключ объекта должен быть строкой.",
            details={
                "value_type": type(object_key).__name__,
            },
        )

    if not object_key:
        raise InvalidStorageKeyError(
            "Ключ объекта не может быть пустым.",
            object_key=object_key,
            reason="empty_object_key",
        )

    if len(object_key) > StorageConstants.S3_OBJECT_KEY_MAX_LENGTH:
        raise InvalidStorageKeyError(
            "Ключ объекта превышает максимально допустимую длину.",
            object_key=object_key,
            reason="object_key_too_long",
            details={
                "length": len(object_key),
                "max_length": StorageConstants.S3_OBJECT_KEY_MAX_LENGTH,
            },
        )

    if "\\" in object_key:
        raise InvalidStorageKeyError(
            "Ключ объекта не должен содержать обратные слэши.",
            object_key=object_key,
            reason="contains_backslash",
        )

    if "//" in object_key:
        raise InvalidStorageKeyError(
            "Ключ объекта не должен содержать повторяющиеся слэши.",
            object_key=object_key,
            reason="contains_repeated_slashes",
        )

    if object_key.startswith("/"):
        raise InvalidStorageKeyError(
            "Ключ объекта не должен быть абсолютным POSIX-путём.",
            object_key=object_key,
            reason="absolute_posix_path",
        )

    if StorageConstants.SYSTEM_PATH_PREFIX_PATTERN.match(object_key):
        raise InvalidStorageKeyError(
            "Ключ объекта не должен быть системным путём.",
            object_key=object_key,
            reason="absolute_system_path",
        )

    parts = object_key.split("/")
    forbidden_parts = [
        part for part in parts if part in StorageConstants.FORBIDDEN_OBJECT_KEY_PARTS
    ]

    if forbidden_parts:
        raise InvalidStorageKeyError(
            "Ключ объекта содержит недопустимые сегменты пути.",
            object_key=object_key,
            reason="forbidden_path_part",
            details={
                "forbidden_parts": forbidden_parts,
            },
        )

    return object_key


def build_file_object_key(
    *,
    user_id: uuid.UUID,
    file_id: uuid.UUID,
    version_id: uuid.UUID,
) -> str:
    """Формирует ключ основного объекта файла.

    Физически в MinIO хранится конкретная версия содержимого файла, поэтому
    ключ файла совпадает с ключом версии.

    Args:
        user_id: Идентификатор пользователя-владельца файла.
        file_id: Идентификатор файла.
        version_id: Идентификатор версии файла.

    Returns:
        Ключ основного объекта файла.

    Raises:
        InvalidStorageKeyError: Если один из идентификаторов не является
            ``UUID`` или итоговый ключ не проходит валидацию.
    """

    return build_file_version_object_key(
        user_id=user_id,
        file_id=file_id,
        version_id=version_id,
    )


def build_file_version_object_key(
    *,
    user_id: uuid.UUID,
    file_id: uuid.UUID,
    version_id: uuid.UUID,
) -> str:
    """Формирует ключ объекта версии файла.

    Пример:
        ``users/{user_id}/files/{file_id}/versions/{version_id}``

    Args:
        user_id: Идентификатор пользователя-владельца файла.
        file_id: Идентификатор файла.
        version_id: Идентификатор версии файла.

    Returns:
        Ключ объекта версии файла.

    Raises:
        InvalidStorageKeyError: Если один из идентификаторов не является
            ``UUID`` или итоговый ключ не проходит валидацию.
    """

    return _build_object_key(
        "users",
        _uuid_to_str(user_id, field_name="user_id"),
        "files",
        _uuid_to_str(file_id, field_name="file_id"),
        "versions",
        _uuid_to_str(version_id, field_name="version_id"),
    )


def build_upload_temp_object_key(
    *,
    user_id: uuid.UUID,
    upload_session_id: uuid.UUID,
) -> str:
    """Формирует ключ временного объекта загрузки.

    Пример:
        ``users/{user_id}/uploads/{upload_session_id}/source``

    Args:
        user_id: Идентификатор пользователя-владельца загрузки.
        upload_session_id: Идентификатор upload-сессии.

    Returns:
        Ключ временного объекта загрузки.

    Raises:
        InvalidStorageKeyError: Если один из идентификаторов не является
            ``UUID`` или итоговый ключ не проходит валидацию.
    """

    return _build_object_key(
        "users",
        _uuid_to_str(user_id, field_name="user_id"),
        "uploads",
        _uuid_to_str(upload_session_id, field_name="upload_session_id"),
        "source",
    )


def build_upload_part_object_key(
    *,
    user_id: uuid.UUID,
    upload_session_id: uuid.UUID,
    part_number: int,
) -> str:
    """Формирует ключ временной части загрузки.

    Пример:
        ``users/{user_id}/uploads/{upload_session_id}/parts/{part_number}``

    Args:
        user_id: Идентификатор пользователя-владельца загрузки.
        upload_session_id: Идентификатор upload-сессии.
        part_number: Номер части multipart-загрузки.

    Returns:
        Ключ временной части загрузки.

    Raises:
        InvalidStorageKeyError: Если один из идентификаторов не является
            ``UUID``, номер части некорректен или итоговый ключ не проходит
            валидацию.
    """

    _validate_part_number(part_number)

    return _build_object_key(
        "users",
        _uuid_to_str(user_id, field_name="user_id"),
        "uploads",
        _uuid_to_str(upload_session_id, field_name="upload_session_id"),
        "parts",
        str(part_number),
    )


def build_archive_object_key(
    *,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    extension: str = "zip",
) -> str:
    """Формирует ключ объекта архива папки.

    Пример:
        ``users/{user_id}/archives/{task_id}/archive.zip``

    Args:
        user_id: Идентификатор пользователя-владельца архива.
        task_id: Идентификатор задачи формирования архива.
        extension: Расширение файла архива.

    Returns:
        Ключ объекта архива.

    Raises:
        InvalidStorageKeyError: Если идентификатор не является ``UUID``,
            расширение некорректно или итоговый ключ не проходит валидацию.
    """

    normalized_extension = normalize_extension(extension) or "zip"

    return _build_object_key(
        "users",
        _uuid_to_str(user_id, field_name="user_id"),
        "archives",
        _uuid_to_str(task_id, field_name="task_id"),
        f"archive.{normalized_extension}",
    )


def build_preview_object_key(
    *,
    user_id: uuid.UUID,
    file_id: uuid.UUID,
    extension: str | None = None,
) -> str:
    """Формирует ключ объекта предпросмотра файла.

    Примеры:
        ``users/{user_id}/previews/{file_id}/preview``
        ``users/{user_id}/previews/{file_id}/preview.jpg``

    Args:
        user_id: Идентификатор пользователя-владельца файла.
        file_id: Идентификатор файла.
        extension: Расширение файла предпросмотра.

    Returns:
        Ключ объекта предпросмотра.

    Raises:
        InvalidStorageKeyError: Если один из идентификаторов не является
            ``UUID``, расширение некорректно или итоговый ключ не проходит
            валидацию.
    """

    normalized_extension = normalize_extension(extension)
    preview_name = "preview"

    if normalized_extension is not None:
        preview_name = f"{preview_name}.{normalized_extension}"

    return _build_object_key(
        "users",
        _uuid_to_str(user_id, field_name="user_id"),
        "previews",
        _uuid_to_str(file_id, field_name="file_id"),
        preview_name,
    )


def build_public_download_object_key(
    *,
    public_link_id: uuid.UUID,
    file_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> str:
    """Формирует технический ключ для публичной выдачи или временной копии.

    Этот ключ не обязателен для обычной pre-signed download-логики, но может
    использоваться для подготовленных публичных объектов.

    Примеры:
        ``public/{public_link_id}/files/{file_id}``
        ``public/{public_link_id}/files/{file_id}/versions/{version_id}``

    Args:
        public_link_id: Идентификатор публичной ссылки.
        file_id: Идентификатор файла.
        version_id: Идентификатор версии файла.

    Returns:
        Ключ объекта для публичной выдачи.

    Raises:
        InvalidStorageKeyError: Если один из идентификаторов не является
            ``UUID`` или итоговый ключ не проходит валидацию.
    """

    parts = [
        "public",
        _uuid_to_str(public_link_id, field_name="public_link_id"),
        "files",
        _uuid_to_str(file_id, field_name="file_id"),
    ]

    if version_id is not None:
        parts.extend(
            [
                "versions",
                _uuid_to_str(version_id, field_name="version_id"),
            ]
        )

    return _build_object_key(*parts)


def build_trash_object_key(
    *,
    user_id: uuid.UUID,
    node_id: uuid.UUID,
    object_id: uuid.UUID | None = None,
) -> str:
    """Формирует ключ технической копии объекта в зоне корзины.

    Обычно soft delete не требует физического перемещения объекта в MinIO, но
    функция полезна для сценариев физического quarantine/trash storage.

    Примеры:
        ``users/{user_id}/trash/{node_id}``
        ``users/{user_id}/trash/{node_id}/objects/{object_id}``

    Args:
        user_id: Идентификатор пользователя-владельца объекта.
        node_id: Идентификатор узла файловой структуры.
        object_id: Идентификатор физического объекта.

    Returns:
        Ключ объекта в зоне корзины.

    Raises:
        InvalidStorageKeyError: Если один из идентификаторов не является
            ``UUID`` или итоговый ключ не проходит валидацию.
    """

    parts = [
        "users",
        _uuid_to_str(user_id, field_name="user_id"),
        "trash",
        _uuid_to_str(node_id, field_name="node_id"),
    ]

    if object_id is not None:
        parts.extend(
            [
                "objects",
                _uuid_to_str(object_id, field_name="object_id"),
            ]
        )

    return _build_object_key(*parts)


def build_backup_object_key(
    *,
    backup_id: uuid.UUID,
    filename: str,
    prefix: str = "backups",
) -> str:
    """Формирует ключ объекта резервной копии.

    Пользовательское имя файла очищается и используется только как техническое
    имя объекта внутри директории ``backup_id``.

    Args:
        backup_id: Идентификатор резервной копии.
        filename: Пользовательское имя файла резервной копии.
        prefix: Верхнеуровневый префикс для backup-объектов.

    Returns:
        Ключ объекта резервной копии.

    Raises:
        InvalidStorageKeyError: Если ``backup_id`` не является ``UUID``,
            ``prefix`` некорректен или итоговый ключ не проходит валидацию.
    """

    normalized_prefix = _normalize_safe_path_part(prefix, field_name="prefix")
    safe_filename = sanitize_filename_for_metadata(filename)

    if not safe_filename:
        safe_filename = "backup"

    return _build_object_key(
        normalized_prefix,
        _uuid_to_str(backup_id, field_name="backup_id"),
        safe_filename,
    )


def build_temporary_object_key(
    *,
    namespace: str,
    object_id: uuid.UUID,
    filename: str | None = None,
) -> str:
    """Формирует универсальный временный ``object_key``.

    Примеры:
        ``tmp/{namespace}/{object_id}``
        ``tmp/{namespace}/{object_id}/{filename}``

    Args:
        namespace: Пространство имён временного объекта.
        object_id: Идентификатор временного объекта.
        filename: Пользовательское имя файла.

    Returns:
        Ключ временного объекта.

    Raises:
        InvalidStorageKeyError: Если ``namespace`` некорректен, ``object_id``
            не является ``UUID`` или итоговый ключ не проходит валидацию.
    """

    normalized_namespace = _normalize_safe_path_part(
        namespace,
        field_name="namespace",
    )

    parts = [
        "tmp",
        normalized_namespace,
        _uuid_to_str(object_id, field_name="object_id"),
    ]

    if filename is not None:
        safe_filename = sanitize_filename_for_metadata(filename)

        if safe_filename:
            parts.append(safe_filename)

    return _build_object_key(*parts)


def extract_extension(filename: str | None) -> str | None:
    """Извлекает расширение файла без ведущей точки.

    Args:
        filename: Пользовательское имя файла.

    Returns:
        Нормализованное расширение файла без ведущей точки или ``None``, если
        расширение отсутствует.

    Raises:
        InvalidStorageKeyError: Если расширение содержит недопустимые символы
            или превышает максимальную длину.
    """

    if filename is None:
        return None

    sanitized_filename = sanitize_filename_for_metadata(filename)

    if not sanitized_filename:
        return None

    suffix = PurePosixPath(sanitized_filename).suffix

    if not suffix:
        return None

    return normalize_extension(suffix)


def normalize_extension(extension: str | None) -> str | None:
    """Нормализует расширение файла.

    Args:
        extension: Расширение файла с ведущей точкой или без неё.

    Returns:
        Нормализованное расширение без ведущей точки или ``None``, если
        расширение пустое.

    Raises:
        InvalidStorageKeyError: Если расширение содержит разделители пути,
            недопустимые сегменты или превышает максимальную длину.
    """

    if extension is None:
        return None

    normalized_extension = extension.strip().lower()

    if normalized_extension.startswith("."):
        normalized_extension = normalized_extension[1:]

    if not normalized_extension:
        return None

    if "/" in normalized_extension or "\\" in normalized_extension:
        raise InvalidStorageKeyError(
            "Расширение файла не должно содержать разделители пути.",
            reason="extension_contains_path_separator",
            details={
                "extension": extension,
            },
        )

    if normalized_extension in {".", ".."} or ".." in normalized_extension:
        raise InvalidStorageKeyError(
            "Расширение файла содержит недопустимые сегменты.",
            reason="invalid_extension",
            details={
                "extension": extension,
            },
        )

    normalized_extension = StorageConstants.UNSAFE_EXTENSION_CHARS_PATTERN.sub(
        "",
        normalized_extension,
    )

    if not normalized_extension:
        return None

    if len(normalized_extension) > StorageConstants.STORAGE_EXTENSION_MAX_LENGTH:
        raise InvalidStorageKeyError(
            "Расширение файла превышает максимально допустимую длину.",
            reason="extension_too_long",
            details={
                "extension": extension,
                "length": len(normalized_extension),
                "max_length": StorageConstants.STORAGE_EXTENSION_MAX_LENGTH,
            },
        )

    return normalized_extension


def sanitize_filename_for_metadata(filename: str | None) -> str:
    """Подготавливает пользовательское имя файла для хранения в метаданных.

    Это значение не используется для построения основного ``object_key``.

    Args:
        filename: Исходное пользовательское имя файла.

    Returns:
        Безопасное имя файла для хранения в метаданных или пустую строку, если
        имя не может быть использовано.
    """

    if filename is None:
        return ""

    sanitized = filename.strip()
    sanitized = sanitized.replace("\\", "/")
    sanitized = sanitized.split("/")[-1]
    sanitized = StorageConstants.UNSAFE_FILENAME_CHARS_PATTERN.sub("_", sanitized)
    sanitized = sanitized.strip(" .")

    if sanitized in {"", ".", ".."}:
        return ""

    if len(sanitized) > StorageConstants.STORAGE_FILENAME_METADATA_MAX_LENGTH:
        sanitized = sanitized[
            : StorageConstants.STORAGE_FILENAME_METADATA_MAX_LENGTH
        ].rstrip(" .")

    return sanitized


def make_object_metadata_filename(filename: str | None) -> dict[str, str]:
    """Возвращает словарь метаданных с безопасным оригинальным именем файла.

    Если имя пустое или полностью небезопасное, возвращается пустой словарь.

    Args:
        filename: Исходное пользовательское имя файла.

    Returns:
        Словарь с ключом ``original-filename`` или пустой словарь.
    """

    sanitized_filename = sanitize_filename_for_metadata(filename)

    if not sanitized_filename:
        return {}

    return {
        "original-filename": sanitized_filename,
    }


def split_object_key(object_key: str) -> list[str]:
    """Валидирует ``object_key`` и возвращает его сегменты.

    Args:
        object_key: Ключ объекта.

    Returns:
        Список сегментов ключа объекта.

    Raises:
        InvalidStorageKeyError: Если ключ объекта не проходит валидацию.
    """

    normalized_key = normalize_object_key(object_key)
    return normalized_key.split("/")


def get_object_key_filename(object_key: str) -> str:
    """Возвращает последний сегмент ``object_key``.

    Args:
        object_key: Ключ объекта.

    Returns:
        Последний сегмент ключа объекта.

    Raises:
        InvalidStorageKeyError: Если ключ объекта не проходит валидацию.
    """

    parts = split_object_key(object_key)
    return parts[-1]


def get_object_key_parent(object_key: str) -> str | None:
    """Возвращает родительский префикс ``object_key``.

    Args:
        object_key: Ключ объекта.

    Returns:
        Родительский префикс или ``None``, если ключ находится на верхнем
        уровне.

    Raises:
        InvalidStorageKeyError: Если ключ объекта не проходит валидацию.
    """

    parts = split_object_key(object_key)

    if len(parts) <= 1:
        return None

    return "/".join(parts[:-1])


def object_key_starts_with_prefix(object_key: str, prefix: str) -> bool:
    """Проверяет, находится ли ``object_key`` внутри указанного ``prefix``.

    Сравнение выполняется по границам сегментов, а не простым ``startswith``.

    Args:
        object_key: Проверяемый ключ объекта.
        prefix: Префикс ключа объекта.

    Returns:
        ``True``, если ключ совпадает с префиксом или находится внутри него.

    Raises:
        InvalidStorageKeyError: Если ключ объекта или префикс не проходят
            валидацию.
    """

    normalized_key = normalize_object_key(object_key)
    normalized_prefix = normalize_object_key(prefix)

    return normalized_key == normalized_prefix or normalized_key.startswith(
        f"{normalized_prefix}/"
    )


def _build_object_key(*parts: str) -> str:
    """Собирает ``object_key`` из сегментов пути и валидирует результат.

    Args:
        *parts: Сегменты ключа объекта.

    Returns:
        Валидный ключ объекта.

    Raises:
        InvalidStorageKeyError: Если один из сегментов или итоговый ключ
            некорректен.
    """

    normalized_parts = [
        _normalize_safe_path_part(part, field_name="object_key_part") for part in parts
    ]

    object_key = "/".join(normalized_parts)
    return normalize_object_key(object_key)


def _normalize_safe_path_part(value: str, *, field_name: str) -> str:
    """Нормализует безопасный сегмент ``object_key``.

    Args:
        value: Исходный сегмент ключа объекта.
        field_name: Название поля для диагностических деталей ошибки.

    Returns:
        Нормализованный сегмент ключа объекта.

    Raises:
        InvalidStorageKeyError: Если сегмент не является строкой, пустой,
            является ``.`` или ``..`` либо содержит разделители пути.
    """

    if not isinstance(value, str):
        raise InvalidStorageKeyError(
            "Сегмент ключа объекта должен быть строкой.",
            reason="invalid_object_key_part_type",
            details={
                "field": field_name,
                "value": str(value),
                "value_type": type(value).__name__,
            },
        )

    normalized_value = value.strip()

    if normalized_value in StorageConstants.FORBIDDEN_OBJECT_KEY_PARTS:
        raise InvalidStorageKeyError(
            "Сегмент ключа объекта недопустим.",
            reason="invalid_object_key_part",
            details={
                "field": field_name,
                "value": value,
            },
        )

    if "/" in normalized_value or "\\" in normalized_value:
        raise InvalidStorageKeyError(
            "Сегмент ключа объекта не должен содержать разделители пути.",
            reason="object_key_part_contains_path_separator",
            details={
                "field": field_name,
                "value": value,
            },
        )

    return normalized_value


def _uuid_to_str(value: uuid.UUID, *, field_name: str) -> str:
    """Преобразует ``UUID`` в строку.

    Args:
        value: Значение ``UUID``.
        field_name: Название поля для диагностических деталей ошибки.

    Returns:
        Строковое представление ``UUID``.

    Raises:
        InvalidStorageKeyError: Если значение не является ``UUID``.
    """

    if not isinstance(value, uuid.UUID):
        raise InvalidStorageKeyError(
            "Для построения ключа объекта ожидался UUID.",
            reason="invalid_uuid",
            details={
                "field": field_name,
                "value": str(value),
                "value_type": type(value).__name__,
            },
        )

    return str(value)


def _validate_part_number(part_number: int) -> None:
    """Проверяет номер части multipart-загрузки.

    Args:
        part_number: Номер части multipart-загрузки.

    Returns:
        ``None``.

    Raises:
        InvalidStorageKeyError: Если номер части не является целым числом,
            является ``bool``, не положительный или превышает максимально
            допустимый номер части.
    """

    if not isinstance(part_number, int) or isinstance(part_number, bool):
        raise InvalidStorageKeyError(
            "Номер части загрузки должен быть целым числом.",
            reason="invalid_part_number_type",
            details={
                "part_number": part_number,
                "value_type": type(part_number).__name__,
            },
        )

    if part_number <= 0:
        raise InvalidStorageKeyError(
            "Номер части загрузки должен быть положительным.",
            reason="invalid_part_number",
            details={
                "part_number": part_number,
            },
        )

    if part_number > StorageConstants.S3_MULTIPART_MAX_PART_NUMBER:
        raise InvalidStorageKeyError(
            "Номер части загрузки превышает максимально допустимое значение.",
            reason="part_number_too_large",
            details={
                "part_number": part_number,
                "max_part_number": StorageConstants.S3_MULTIPART_MAX_PART_NUMBER,
            },
        )
