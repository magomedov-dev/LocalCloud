from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator
from schemas.nodes import NodeListItem, NodeRead, validate_node_name

from database.models.enums import BackgroundTaskStatus
from schemas.common import BaseSchema

COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_folder_color(value: str | None) -> str | None:
    """Нормализует и проверяет цветовую метку папки.

    Удаляет пробелы по краям значения, приводит пустые строки к ``None`` и
    проверяет HEX-значения, если цветовая метка начинается с ``#``.

    Args:
        value: Исходное значение цветовой метки папки.

    Returns:
        Нормализованная цветовая метка или ``None``, если значение отсутствует
        либо содержит только пробельные символы.

    Raises:
        ValueError: Если цветовая метка длиннее 32 символов.
        ValueError: Если значение начинается с ``#``, но не является корректным
            HEX-цветом в формате ``#fff`` или ``#ffffff``.
    """

    if value is None:
        return None

    normalized_value = value.strip()

    if not normalized_value:
        return None

    if len(normalized_value) > 32:
        raise ValueError("Цветовая метка папки не должна превышать 32 символа.")

    if normalized_value.startswith("#") and not COLOR_PATTERN.fullmatch(
        normalized_value
    ):
        raise ValueError(
            "Цвет папки должен быть корректным HEX-значением, например #fff или #ffffff."
        )

    return normalized_value


class FolderCreateRequest(BaseSchema):
    """Запрос на создание папки.

    Используется для создания новой папки в корне файловой системы или внутри
    указанной родительской папки. Имя папки проверяется через общую валидацию
    имени узла, описание нормализуется, а цветовая метка проверяется отдельным
    валидатором.

    Attributes:
        name: Имя создаваемой папки.
        parent_id: Идентификатор родительской папки. ``None`` означает создание
            в корне.
        description: Необязательное описание папки.
        color: Цветовая метка папки для интерфейса.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Имя создаваемой папки.",
        examples=["Документы", "Фотографии"],
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор родительской папки. None означает создание в корне.",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Необязательное описание папки.",
    )
    color: str | None = Field(
        default=None,
        max_length=32,
        description="Цветовая метка папки для интерфейса.",
        examples=["#3b82f6", "blue"],
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Проверяет имя создаваемой папки.

        Args:
            value: Исходное имя папки.

        Returns:
            Нормализованное и валидное имя папки.

        Raises:
            ValueError: Если имя папки не проходит правила валидации узла.
        """

        return validate_node_name(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        """Нормализует описание папки.

        Args:
            value: Исходное описание папки.

        Returns:
            Описание без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        """Проверяет и нормализует цветовую метку папки.

        Args:
            value: Исходное значение цветовой метки.

        Returns:
            Нормализованная цветовая метка или ``None``.

        Raises:
            ValueError: Если цветовая метка не проходит проверку.
        """

        return normalize_folder_color(value)


class FolderUpdateRequest(BaseSchema):
    """Запрос на обновление metadata папки.

    Используется для изменения пользовательских metadata папки: описания и
    цветовой метки. Значение ``None`` очищает соответствующее поле.

    Attributes:
        description: Новое описание папки. ``None`` очищает описание.
        color: Новая цветовая метка папки. ``None`` очищает цвет.
    """

    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Новое описание папки. None очищает описание.",
    )
    color: str | None = Field(
        default=None,
        max_length=32,
        description="Новая цветовая метка папки. None очищает цвет.",
        examples=["#22c55e", "green"],
    )

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        """Нормализует новое описание папки.

        Args:
            value: Исходное описание папки.

        Returns:
            Описание без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        """Проверяет и нормализует новую цветовую метку папки.

        Args:
            value: Исходное значение цветовой метки.

        Returns:
            Нормализованная цветовая метка или ``None``.

        Raises:
            ValueError: Если цветовая метка не проходит проверку.
        """

        return normalize_folder_color(value)


class FolderRead(BaseSchema):
    """Полное представление папки.

    Используется для возврата подробных metadata папки вместе с общими данными
    связанного узла файловой системы, если они были загружены.

    Attributes:
        id: Уникальный идентификатор metadata-записи папки.
        node_id: Идентификатор узла файловой системы, связанного с папкой.
        description: Описание папки.
        color: Цветовая метка папки.
        created_at: Дата и время создания metadata-записи папки.
        updated_at: Дата и время последнего обновления metadata-записи папки.
        node: Общие данные узла файловой системы, если они были загружены.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор metadata-записи папки.",
    )
    node_id: UUID = Field(
        ...,
        description="Идентификатор узла файловой системы, связанного с папкой.",
    )
    description: str | None = Field(
        default=None,
        description="Описание папки.",
    )
    color: str | None = Field(
        default=None,
        description="Цветовая метка папки.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания metadata-записи папки.",
    )
    updated_at: datetime = Field(
        ...,
        description="Дата и время последнего обновления metadata-записи папки.",
    )
    node: NodeRead | None = Field(
        default=None,
        description="Общие данные узла файловой системы, если они были загружены.",
    )


class FolderListItem(BaseSchema):
    """Краткое представление папки для списков.

    Используется в списках файловой системы, когда клиенту достаточно кратких
    metadata папки и краткой информации о связанном узле.

    Attributes:
        id: Уникальный идентификатор metadata-записи папки.
        node_id: Идентификатор узла файловой системы, связанного с папкой.
        description: Описание папки.
        color: Цветовая метка папки.
        created_at: Дата и время создания metadata-записи папки.
        updated_at: Дата и время последнего обновления metadata-записи папки.
        node: Краткие данные узла файловой системы, если они были загружены.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор metadata-записи папки.",
    )
    node_id: UUID = Field(
        ...,
        description="Идентификатор узла файловой системы, связанного с папкой.",
    )
    description: str | None = Field(
        default=None,
        description="Описание папки.",
    )
    color: str | None = Field(
        default=None,
        description="Цветовая метка папки.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания metadata-записи папки.",
    )
    updated_at: datetime = Field(
        ...,
        description="Дата и время последнего обновления metadata-записи папки.",
    )
    node: NodeListItem | None = Field(
        default=None,
        description="Краткие данные узла файловой системы, если они были загружены.",
    )


class FolderContentRead(BaseSchema):
    """Содержимое папки.

    Используется для возврата текущей папки, хлебных крошек и списка файлов или
    подпапок, находящихся внутри неё.

    Attributes:
        folder: Папка, содержимое которой возвращается.
        breadcrumbs: Цепочка родительских узлов от корня до текущей папки.
        items: Файлы и папки внутри текущей папки.
        total: Общее количество элементов в папке.
    """

    folder: FolderRead = Field(
        ...,
        description="Папка, содержимое которой возвращается.",
    )
    breadcrumbs: list[NodeListItem] = Field(
        default_factory=list,
        description="Цепочка родительских узлов от корня до текущей папки.",
    )
    items: list[NodeListItem] = Field(
        default_factory=list,
        description="Файлы и папки внутри текущей папки.",
    )
    total: int = Field(
        default=0,
        ge=0,
        description="Общее количество элементов в папке.",
    )


class FolderArchiveRequest(BaseSchema):
    """Запрос на фоновое создание ZIP-архива папки.

    Используется для постановки фоновой задачи, которая создаёт ZIP-архив
    содержимого папки. Имя архива проверяется как имя узла файловой системы, а
    расширение ``.zip`` при необходимости удаляется из пользовательского ввода.

    Attributes:
        folder_id: Идентификатор папки, для которой нужно создать ZIP-архив.
        include_deleted: Включать ли логически удалённые элементы в архив.
        archive_name: Желаемое имя архива без обязательного расширения
            ``.zip``.
        password: Пароль для архива, если поддерживается сервисным слоем.
    """

    folder_id: UUID = Field(
        ...,
        description="Идентификатор папки, для которой нужно создать ZIP-архив.",
    )
    include_deleted: bool = Field(
        default=False,
        description="Включать ли логически удалённые элементы в архив.",
    )
    archive_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Желаемое имя архива без обязательного расширения .zip.",
        examples=["documents.zip", "photos-2026"],
    )
    password: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Пароль для архива, если поддерживается сервисным слоем.",
    )

    @field_validator("archive_name")
    @classmethod
    def validate_archive_name(cls, value: str | None) -> str | None:
        """Проверяет и нормализует имя создаваемого архива.

        Args:
            value: Исходное имя архива или ``None``.

        Returns:
            Нормализованное имя архива без расширения ``.zip`` или ``None``,
            если имя архива не задано.

        Raises:
            ValueError: Если имя архива не проходит правила валидации узла или
                становится пустым после удаления расширения ``.zip``.
        """

        if value is None:
            return None

        normalized_value = validate_node_name(value)

        if normalized_value.lower().endswith(".zip"):
            normalized_value = normalized_value[:-4].strip()

        if not normalized_value:
            raise ValueError("Имя архива не должно быть пустым.")

        return normalized_value


class FolderArchiveResponse(BaseSchema):
    """Ответ на запрос создания ZIP-архива папки.

    Возвращается после успешной постановки фоновой задачи на создание архива.

    Attributes:
        task_id: Идентификатор фоновой задачи создания архива.
        status: Текущий статус фоновой задачи.
        message: Сообщение о результате постановки задачи.
    """

    task_id: UUID = Field(
        ...,
        description="Идентификатор фоновой задачи создания архива.",
    )
    status: BackgroundTaskStatus = Field(
        ...,
        description="Текущий статус фоновой задачи.",
    )
    message: str = Field(
        default="Задача создания архива папки поставлена в очередь.",
        description="Сообщение о результате постановки задачи.",
    )


class BulkArchiveRequest(BaseSchema):
    """Запрос на создание ZIP-архива из произвольного набора узлов.

    Используется для постановки фоновой задачи, которая собирает один ZIP-архив
    из выбранных файлов и/или папок. Файлы добавляются в корень архива, папки —
    со своим содержимым с сохранением относительной структуры.

    Attributes:
        node_ids: Идентификаторы выбранных узлов (файлов и/или папок).
        archive_name: Желаемое имя архива без обязательного расширения .zip.
    """

    node_ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Идентификаторы выбранных узлов (файлов и/или папок).",
    )
    archive_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Желаемое имя архива без обязательного расширения .zip.",
        examples=["selection", "documents-2026"],
    )
