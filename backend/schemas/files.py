from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator
from schemas.nodes import NodeListItem, NodeRead, validate_node_name

from database.models.enums import (
    FilePreviewStatus,
    FileProcessingStatus,
    FileVersionStatus,
    StorageObjectStatus,
)
from schemas.common import BaseSchema, PaginationParams


class FileMetadataRead(BaseSchema):
    """Метаданные содержимого файла без внутренних storage-ключей.

    Используется для безопасной передачи клиенту технических характеристик
    файла без раскрытия внутренних идентификаторов объектного хранилища.

    Attributes:
        size_bytes: Размер файла в байтах.
        mime_type: MIME-тип файла.
        extension: Расширение файла без ведущей точки.
        checksum: Контрольная сумма файла.
        checksum_algorithm: Алгоритм контрольной суммы.
        storage_status: Статус физического объекта файла в хранилище.
        processing_status: Статус обработки файла.
        preview_status: Статус генерации предпросмотра файла.
        current_version_id: Идентификатор текущей версии файла.
    """

    size_bytes: int = Field(
        ...,
        ge=0,
        description="Размер файла в байтах.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип файла.",
        examples=["application/pdf", "image/png", "text/plain"],
    )
    extension: str | None = Field(
        default=None,
        max_length=32,
        description="Расширение файла без ведущей точки.",
        examples=["pdf", "png", "txt"],
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Контрольная сумма файла.",
    )
    checksum_algorithm: str | None = Field(
        default=None,
        max_length=32,
        description="Алгоритм контрольной суммы.",
        examples=["sha256", "md5"],
    )
    storage_status: StorageObjectStatus = Field(
        ...,
        description="Статус физического объекта файла в хранилище.",
    )
    processing_status: FileProcessingStatus = Field(
        ...,
        description="Статус обработки файла.",
    )
    preview_status: FilePreviewStatus = Field(
        ...,
        description="Статус генерации предпросмотра файла.",
    )
    current_version_id: UUID | None = Field(
        default=None,
        description="Идентификатор текущей версии файла.",
    )


class FileRead(BaseSchema):
    """Полное публичное представление файла.

    В этой схеме намеренно нет ``storage_bucket``, ``storage_key`` и
    ``preview_storage_key``, чтобы не раскрывать внутреннюю структуру
    объектного хранилища.

    Attributes:
        id: Уникальный идентификатор metadata-записи файла.
        node_id: Идентификатор узла файловой системы, связанного с файлом.
        size_bytes: Размер файла в байтах.
        mime_type: MIME-тип файла.
        extension: Расширение файла без ведущей точки.
        checksum: Контрольная сумма файла.
        checksum_algorithm: Алгоритм контрольной суммы.
        storage_status: Статус физического объекта файла в хранилище.
        processing_status: Статус обработки файла.
        preview_status: Статус генерации предпросмотра файла.
        current_version_id: Идентификатор текущей версии файла.
        created_at: Дата и время создания metadata-записи файла.
        updated_at: Дата и время последнего обновления metadata-записи файла.
        node: Общие данные узла файловой системы, если они были загружены.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор metadata-записи файла.",
    )
    node_id: UUID = Field(
        ...,
        description="Идентификатор узла файловой системы, связанного с файлом.",
    )
    size_bytes: int = Field(
        ...,
        ge=0,
        description="Размер файла в байтах.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип файла.",
    )
    extension: str | None = Field(
        default=None,
        max_length=32,
        description="Расширение файла без ведущей точки.",
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Контрольная сумма файла.",
    )
    checksum_algorithm: str | None = Field(
        default=None,
        max_length=32,
        description="Алгоритм контрольной суммы.",
    )
    storage_status: StorageObjectStatus = Field(
        ...,
        description="Статус физического объекта файла в хранилище.",
    )
    processing_status: FileProcessingStatus = Field(
        ...,
        description="Статус обработки файла.",
    )
    preview_status: FilePreviewStatus = Field(
        ...,
        description="Статус генерации предпросмотра файла.",
    )
    current_version_id: UUID | None = Field(
        default=None,
        description="Идентификатор текущей версии файла.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания metadata-записи файла.",
    )
    updated_at: datetime = Field(
        ...,
        description="Дата и время последнего обновления metadata-записи файла.",
    )
    node: NodeRead | None = Field(
        default=None,
        description="Общие данные узла файловой системы, если они были загружены.",
    )


class FileListItem(BaseSchema):
    """Краткое представление файла для списков.

    Используется в ответах API со списком файлов, когда клиенту нужны основные
    сведения о файле и краткие данные связанного узла файловой системы.

    Attributes:
        id: Уникальный идентификатор metadata-записи файла.
        node_id: Идентификатор узла файловой системы, связанного с файлом.
        size_bytes: Размер файла в байтах.
        mime_type: MIME-тип файла.
        extension: Расширение файла без ведущей точки.
        checksum: Контрольная сумма файла.
        checksum_algorithm: Алгоритм контрольной суммы.
        storage_status: Статус физического объекта файла в хранилище.
        processing_status: Статус обработки файла.
        preview_status: Статус генерации предпросмотра файла.
        current_version_id: Идентификатор текущей версии файла.
        created_at: Дата и время создания metadata-записи файла.
        updated_at: Дата и время последнего обновления metadata-записи файла.
        node: Краткие данные узла файловой системы, если они были загружены.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор metadata-записи файла.",
    )
    node_id: UUID = Field(
        ...,
        description="Идентификатор узла файловой системы, связанного с файлом.",
    )
    size_bytes: int = Field(
        ...,
        ge=0,
        description="Размер файла в байтах.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип файла.",
    )
    extension: str | None = Field(
        default=None,
        max_length=32,
        description="Расширение файла без ведущей точки.",
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Контрольная сумма файла.",
    )
    checksum_algorithm: str | None = Field(
        default=None,
        max_length=32,
        description="Алгоритм контрольной суммы.",
    )
    storage_status: StorageObjectStatus = Field(
        ...,
        description="Статус физического объекта файла в хранилище.",
    )
    processing_status: FileProcessingStatus = Field(
        ...,
        description="Статус обработки файла.",
    )
    preview_status: FilePreviewStatus = Field(
        ...,
        description="Статус генерации предпросмотра файла.",
    )
    current_version_id: UUID | None = Field(
        default=None,
        description="Идентификатор текущей версии файла.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания metadata-записи файла.",
    )
    updated_at: datetime = Field(
        ...,
        description="Дата и время последнего обновления metadata-записи файла.",
    )
    node: NodeListItem | None = Field(
        default=None,
        description="Краткие данные узла файловой системы, если они были загружены.",
    )


class FileUpdateRequest(BaseSchema):
    """Запрос на обновление пользовательских metadata файла.

    Позволяет изменить MIME-тип, расширение, контрольную сумму и алгоритм
    контрольной суммы. Текстовые значения нормализуются: пробелы по краям
    удаляются, пустые строки приводятся к ``None``.

    Attributes:
        mime_type: Новый MIME-тип файла.
        extension: Новое расширение файла без ведущей точки.
        checksum: Новая контрольная сумма файла.
        checksum_algorithm: Новый алгоритм контрольной суммы.
    """

    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="Новый MIME-тип файла.",
    )
    extension: str | None = Field(
        default=None,
        max_length=32,
        description="Новое расширение файла без ведущей точки.",
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Новая контрольная сумма файла.",
    )
    checksum_algorithm: str | None = Field(
        default=None,
        max_length=32,
        description="Новый алгоритм контрольной суммы.",
    )

    @field_validator("mime_type", "extension", "checksum", "checksum_algorithm")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Нормализует необязательное текстовое значение.

        Args:
            value: Исходное значение текстового поля.

        Returns:
            Строка без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("extension")
    @classmethod
    def normalize_extension(cls, value: str | None) -> str | None:
        """Нормализует расширение файла.

        Удаляет пробелы по краям, приводит расширение к нижнему регистру и
        убирает ведущую точку.

        Args:
            value: Исходное значение расширения файла.

        Returns:
            Нормализованное расширение без ведущей точки или ``None``.
        """

        if value is None:
            return None

        normalized_value = value.strip().lower().lstrip(".")
        return normalized_value or None

    @field_validator("checksum_algorithm")
    @classmethod
    def normalize_checksum_algorithm(cls, value: str | None) -> str | None:
        """Нормализует название алгоритма контрольной суммы.

        Args:
            value: Исходное название алгоритма.

        Returns:
            Название алгоритма без пробелов по краям в нижнем регистре или
            ``None``.
        """

        if value is None:
            return None

        normalized_value = value.strip().lower()
        return normalized_value or None


class FileRenameRequest(BaseSchema):
    """Запрос на переименование файла.

    Используется для изменения имени файла через общую валидацию имени узла
    файловой системы.

    Attributes:
        name: Новое имя файла.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Новое имя файла.",
        examples=["document.pdf", "photo.png"],
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Проверяет корректность нового имени файла.

        Args:
            value: Исходное имя файла.

        Returns:
            Нормализованное и валидное имя файла.

        Raises:
            ValueError: Если имя файла не проходит правила валидации узла.
        """

        return validate_node_name(value)


class FileMoveRequest(BaseSchema):
    """Запрос на перемещение файла.

    Используется для переноса файла в другую папку или в корень файловой
    системы.

    Attributes:
        target_parent_id: Идентификатор целевой папки. ``None`` означает
            перемещение в корень.
    """

    target_parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор целевой папки. None означает перемещение в корень.",
    )


class FileDownloadRequest(BaseSchema):
    """Запрос на получение ссылки для скачивания файла.

    Позволяет получить ссылку на текущую или конкретную версию файла, а также
    задать поведение скачивания и предлагаемое имя файла.

    Attributes:
        file_id: Идентификатор файла, для которого нужно получить ссылку на
            скачивание.
        version_id: Идентификатор версии файла. ``None`` означает скачивание
            текущей версии.
        force_download: Добавлять ли заголовки для скачивания как attachment.
        filename: Имя файла, которое нужно предложить клиенту при скачивании.
    """

    file_id: UUID = Field(
        ...,
        description="Идентификатор файла, для которого нужно получить ссылку на скачивание.",
    )
    version_id: UUID | None = Field(
        default=None,
        description="Идентификатор версии файла. None означает скачивание текущей версии.",
    )
    force_download: bool = Field(
        default=True,
        description="Добавлять ли заголовки для скачивания как attachment.",
    )
    filename: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Имя файла, которое нужно предложить клиенту при скачивании.",
    )

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None) -> str | None:
        """Проверяет предлагаемое имя файла для скачивания.

        Args:
            value: Исходное имя файла или ``None``.

        Returns:
            Валидное имя файла или ``None``, если имя не задано.

        Raises:
            ValueError: Если имя файла не проходит правила валидации узла.
        """

        if value is None:
            return None

        return validate_node_name(value)


class FileDownloadResponse(BaseSchema):
    """Ответ со ссылкой на скачивание файла.

    Содержит предварительно подписанную ссылку, срок её действия, HTTP-метод,
    дополнительные заголовки и сведения о скачиваемом файле.

    Attributes:
        presigned_url: Предварительно подписанная ссылка на скачивание файла.
        expires_at: Дата и время истечения срока действия ссылки.
        method: HTTP-метод, которым нужно воспользоваться для скачивания.
        headers: HTTP-заголовки, которые нужно использовать при скачивании,
            если применимо.
        file_id: Идентификатор файла, для которого сформирована ссылка.
        version_id: Идентификатор версии файла, если ссылка сформирована для
            конкретной версии.
        filename: Предлагаемое имя файла для скачивания.
        size_bytes: Размер скачиваемого файла в байтах, если известен.
        mime_type: MIME-тип скачиваемого файла, если известен.
    """

    presigned_url: str = Field(
        ...,
        description="Предварительно подписанная ссылка на скачивание файла.",
    )
    expires_at: datetime = Field(
        ...,
        description="Дата и время истечения срока действия ссылки.",
    )
    method: str = Field(
        default="GET",
        description="HTTP-метод, которым нужно воспользоваться для скачивания.",
        examples=["GET"],
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="HTTP-заголовки, которые нужно использовать при скачивании, если применимо.",
    )
    file_id: UUID | None = Field(
        default=None,
        description="Идентификатор файла, для которого сформирована ссылка.",
    )
    version_id: UUID | None = Field(
        default=None,
        description="Идентификатор версии файла, если ссылка сформирована для конкретной версии.",
    )
    filename: str | None = Field(
        default=None,
        description="Предлагаемое имя файла для скачивания.",
    )
    size_bytes: int | None = Field(
        default=None,
        ge=0,
        description="Размер скачиваемого файла в байтах, если известен.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип скачиваемого файла, если известен.",
    )

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        """Нормализует HTTP-метод для скачивания.

        Args:
            value: Исходное значение HTTP-метода.

        Returns:
            HTTP-метод без пробелов по краям в верхнем регистре.

        Raises:
            ValueError: Если HTTP-метод пустой после нормализации.
        """

        normalized_value = value.strip().upper()

        if not normalized_value:
            raise ValueError("HTTP-метод не должен быть пустым.")

        return normalized_value


class FilePreviewRead(BaseSchema):
    """Представление предпросмотра файла.

    Используется для возврата статуса предпросмотра и временной ссылки на него,
    если предпросмотр был успешно сгенерирован.

    Attributes:
        file_id: Идентификатор файла.
        preview_status: Статус генерации предпросмотра.
        preview_available: Доступен ли предпросмотр файла.
        presigned_url: Предварительно подписанная ссылка на предпросмотр, если
            он доступен.
        expires_at: Дата и время истечения ссылки на предпросмотр.
        mime_type: MIME-тип предпросмотра.
        message: Дополнительное сообщение о состоянии предпросмотра.
    """

    file_id: UUID = Field(
        ...,
        description="Идентификатор файла.",
    )
    preview_status: FilePreviewStatus = Field(
        ...,
        description="Статус генерации предпросмотра.",
    )
    preview_available: bool = Field(
        default=False,
        description="Доступен ли предпросмотр файла.",
    )
    presigned_url: str | None = Field(
        default=None,
        description="Предварительно подписанная ссылка на предпросмотр, если он доступен.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Дата и время истечения ссылки на предпросмотр.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип предпросмотра.",
    )
    message: str | None = Field(
        default=None,
        description="Дополнительное сообщение о состоянии предпросмотра.",
    )


class FileVersionRead(BaseSchema):
    """Полное публичное представление версии файла.

    ``storage_bucket`` и ``storage_key`` намеренно не возвращаются, чтобы не
    раскрывать внутреннюю структуру объектного хранилища.

    Attributes:
        id: Уникальный идентификатор версии файла.
        file_id: Идентификатор файла, к которому относится версия.
        version_number: Порядковый номер версии внутри файла.
        status: Статус версии файла.
        size_bytes: Размер версии файла в байтах.
        checksum: Контрольная сумма версии файла.
        checksum_algorithm: Алгоритм контрольной суммы версии файла.
        mime_type: MIME-тип версии файла.
        created_at: Дата и время создания версии файла.
        created_by: Идентификатор пользователя, создавшего версию файла.
        change_comment: Комментарий к изменению версии.
        is_current: Признак текущей активной версии файла.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор версии файла.",
    )
    file_id: UUID = Field(
        ...,
        description="Идентификатор файла, к которому относится версия.",
    )
    version_number: int = Field(
        ...,
        ge=1,
        description="Порядковый номер версии внутри файла.",
    )
    status: FileVersionStatus = Field(
        ...,
        description="Статус версии файла.",
    )
    size_bytes: int = Field(
        ...,
        ge=0,
        description="Размер версии файла в байтах.",
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Контрольная сумма версии файла.",
    )
    checksum_algorithm: str | None = Field(
        default=None,
        max_length=32,
        description="Алгоритм контрольной суммы версии файла.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип версии файла.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания версии файла.",
    )
    created_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, создавшего версию файла.",
    )
    change_comment: str | None = Field(
        default=None,
        description="Комментарий к изменению версии.",
    )
    is_current: bool = Field(
        ...,
        description="Признак текущей активной версии файла.",
    )


class FileVersionListItem(BaseSchema):
    """Краткое представление версии файла для списков.

    Используется для отображения истории версий файла без лишних подробностей
    и без внутренних storage-ключей.

    Attributes:
        id: Уникальный идентификатор версии файла.
        file_id: Идентификатор файла, к которому относится версия.
        version_number: Порядковый номер версии внутри файла.
        status: Статус версии файла.
        size_bytes: Размер версии файла в байтах.
        mime_type: MIME-тип версии файла.
        checksum: Контрольная сумма версии файла.
        checksum_algorithm: Алгоритм контрольной суммы версии файла.
        created_at: Дата и время создания версии файла.
        created_by: Идентификатор пользователя, создавшего версию файла.
        is_current: Признак текущей активной версии файла.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор версии файла.",
    )
    file_id: UUID = Field(
        ...,
        description="Идентификатор файла, к которому относится версия.",
    )
    version_number: int = Field(
        ...,
        ge=1,
        description="Порядковый номер версии внутри файла.",
    )
    status: FileVersionStatus = Field(
        ...,
        description="Статус версии файла.",
    )
    size_bytes: int = Field(
        ...,
        ge=0,
        description="Размер версии файла в байтах.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип версии файла.",
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Контрольная сумма версии файла.",
    )
    checksum_algorithm: str | None = Field(
        default=None,
        max_length=32,
        description="Алгоритм контрольной суммы версии файла.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания версии файла.",
    )
    created_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, создавшего версию файла.",
    )
    is_current: bool = Field(
        ...,
        description="Признак текущей активной версии файла.",
    )


class FileVersionRestoreRequest(BaseSchema):
    """Запрос на восстановление версии файла как текущей.

    Используется для выбора существующей версии файла и назначения её текущей
    активной версией.

    Attributes:
        version_id: Идентификатор версии файла, которую нужно восстановить.
        change_comment: Комментарий к восстановлению версии.
    """

    version_id: UUID = Field(
        ...,
        description="Идентификатор версии файла, которую нужно восстановить.",
    )
    change_comment: str | None = Field(
        default=None,
        max_length=512,
        description="Комментарий к восстановлению версии.",
    )

    @field_validator("change_comment")
    @classmethod
    def normalize_change_comment(cls, value: str | None) -> str | None:
        """Нормализует комментарий к восстановлению версии.

        Args:
            value: Исходный комментарий.

        Returns:
            Комментарий без пробелов по краям или ``None``, если комментарий
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class FileSearchQuery(PaginationParams):
    """Параметры поиска файлов.

    Используется для постраничного поиска файлов с фильтрацией по владельцу,
    родительской папке, MIME-типу, расширению, статусам, размеру, датам
    создания и обновления, а также с настройками сортировки.

    Attributes:
        query: Поисковая строка по имени файла, пути или metadata.
        parent_id: Ограничить поиск указанной папкой.
        owner_id: Ограничить поиск указанным владельцем.
        mime_type: Фильтр по MIME-типу.
        extension: Фильтр по расширению файла без ведущей точки.
        storage_status: Фильтр по статусу объекта в хранилище.
        processing_status: Фильтр по статусу обработки файла.
        preview_status: Фильтр по статусу предпросмотра.
        min_size_bytes: Минимальный размер файла в байтах.
        max_size_bytes: Максимальный размер файла в байтах.
        created_from: Фильтр по дате создания: начало диапазона включительно.
        created_to: Фильтр по дате создания: конец диапазона включительно.
        updated_from: Фильтр по дате обновления: начало диапазона включительно.
        updated_to: Фильтр по дате обновления: конец диапазона включительно.
        include_deleted: Включать ли логически удалённые файлы в результаты
            поиска.
        sort_by: Поле сортировки.
        sort_desc: Признак сортировки по убыванию.
    """

    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Поисковая строка по имени файла, пути или metadata.",
        examples=["report", "pdf", "photo"],
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Ограничить поиск указанной папкой.",
    )
    owner_id: UUID | None = Field(
        default=None,
        description="Ограничить поиск указанным владельцем.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="Фильтр по MIME-типу.",
        examples=["application/pdf", "image/png"],
    )
    extension: str | None = Field(
        default=None,
        max_length=32,
        description="Фильтр по расширению файла без ведущей точки.",
        examples=["pdf", "png", "txt"],
    )
    storage_status: StorageObjectStatus | None = Field(
        default=None,
        description="Фильтр по статусу объекта в хранилище.",
    )
    processing_status: FileProcessingStatus | None = Field(
        default=None,
        description="Фильтр по статусу обработки файла.",
    )
    preview_status: FilePreviewStatus | None = Field(
        default=None,
        description="Фильтр по статусу предпросмотра.",
    )
    min_size_bytes: int | None = Field(
        default=None,
        ge=0,
        description="Минимальный размер файла в байтах.",
    )
    max_size_bytes: int | None = Field(
        default=None,
        ge=0,
        description="Максимальный размер файла в байтах.",
    )
    created_from: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания: начало диапазона включительно.",
    )
    created_to: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания: конец диапазона включительно.",
    )
    updated_from: datetime | None = Field(
        default=None,
        description="Фильтр по дате обновления: начало диапазона включительно.",
    )
    updated_to: datetime | None = Field(
        default=None,
        description="Фильтр по дате обновления: конец диапазона включительно.",
    )
    include_deleted: bool = Field(
        default=False,
        description="Включать ли логически удалённые файлы в результаты поиска.",
    )
    sort_by: str = Field(
        default="created_at",
        min_length=1,
        max_length=64,
        description="Поле сортировки.",
        examples=["name", "created_at", "updated_at", "size_bytes", "mime_type"],
    )
    sort_desc: bool = Field(
        default=True,
        description="Сортировать по убыванию.",
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        """Нормализует поисковую строку.

        Args:
            value: Исходное значение поисковой строки.

        Returns:
            Поисковая строка без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("mime_type")
    @classmethod
    def normalize_mime_type(cls, value: str | None) -> str | None:
        """Нормализует MIME-тип.

        Args:
            value: Исходное значение MIME-типа.

        Returns:
            MIME-тип без пробелов по краям в нижнем регистре или ``None``.
        """

        if value is None:
            return None

        normalized_value = value.strip().lower()
        return normalized_value or None

    @field_validator("extension")
    @classmethod
    def normalize_extension(cls, value: str | None) -> str | None:
        """Нормализует расширение файла.

        Args:
            value: Исходное значение расширения файла.

        Returns:
            Расширение без пробелов по краям, в нижнем регистре и без ведущей
            точки или ``None``.
        """

        if value is None:
            return None

        normalized_value = value.strip().lower().lstrip(".")
        return normalized_value or None

    @field_validator("max_size_bytes")
    @classmethod
    def validate_size_range(
        cls,
        value: int | None,
        info: object,
    ) -> int | None:
        """Проверяет корректность диапазона размера файла.

        Args:
            value: Значение верхней границы размера ``max_size_bytes``.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Значение ``max_size_bytes``, если диапазон корректен.

        Raises:
            ValueError: Если ``max_size_bytes`` меньше ``min_size_bytes``.
        """

        data = getattr(info, "data", {})
        min_size_bytes = data.get("min_size_bytes")

        if min_size_bytes is not None and value is not None and value < min_size_bytes:
            raise ValueError("max_size_bytes не может быть меньше min_size_bytes.")

        return value

    @field_validator("created_to")
    @classmethod
    def validate_created_range(
        cls,
        value: datetime | None,
        info: object,
    ) -> datetime | None:
        """Проверяет корректность диапазона даты создания.

        Args:
            value: Значение верхней границы диапазона ``created_to``.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Значение ``created_to``, если диапазон корректен.

        Raises:
            ValueError: Если ``created_to`` меньше ``created_from``.
        """

        data = getattr(info, "data", {})
        created_from = data.get("created_from")

        if created_from is not None and value is not None and value < created_from:
            raise ValueError("created_to не может быть раньше created_from.")

        return value

    @field_validator("updated_to")
    @classmethod
    def validate_updated_range(
        cls,
        value: datetime | None,
        info: object,
    ) -> datetime | None:
        """Проверяет корректность диапазона даты обновления.

        Args:
            value: Значение верхней границы диапазона ``updated_to``.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Значение ``updated_to``, если диапазон корректен.

        Raises:
            ValueError: Если ``updated_to`` меньше ``updated_from``.
        """

        data = getattr(info, "data", {})
        updated_from = data.get("updated_from")

        if updated_from is not None and value is not None and value < updated_from:
            raise ValueError("updated_to не может быть раньше updated_from.")

        return value
