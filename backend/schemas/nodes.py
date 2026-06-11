from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from database.models.enums import NodeType, NodeVisibility
from schemas.common import BaseSchema, PaginationParams

FORBIDDEN_NODE_NAME_CHARS = {"/", "\\", "\x00"}


def validate_node_name(value: str) -> str:
    """Проверяет и нормализует имя узла файловой системы.

    Удаляет пробелы по краям имени и проверяет, что имя не пустое, не содержит
    запрещённые символы и не совпадает со служебными именами ``.`` или ``..``.

    Args:
        value: Исходное имя узла файловой системы.

    Returns:
        Нормализованное имя узла файловой системы.

    Raises:
        ValueError: Если имя пустое после нормализации.
        ValueError: Если имя содержит ``/``, ``\\`` или NUL-символ.
        ValueError: Если имя равно ``.`` или ``..``.
    """

    normalized_value = value.strip()

    if not normalized_value:
        raise ValueError("Имя узла не должно быть пустым.")

    if any(char in normalized_value for char in FORBIDDEN_NODE_NAME_CHARS):
        raise ValueError("Имя узла не должно содержать '/', '\\' или NUL-символ.")

    if normalized_value in {".", ".."}:
        raise ValueError("Имя узла не может быть '.' или '..'.")

    return normalized_value


class NodeBase(BaseSchema):
    """Базовые поля узла файловой системы.

    Используется как общий родитель для схем создания и других DTO, которым
    нужны имя, родительская папка и видимость узла.

    Attributes:
        name: Имя файла или папки, отображаемое пользователю.
        parent_id: Идентификатор родительской папки. ``None`` означает
            корневой уровень.
        visibility: Видимость узла файловой системы.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Имя файла или папки, отображаемое пользователю.",
        examples=["Документы", "report.pdf"],
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор родительской папки. None означает корневой уровень.",
    )
    visibility: NodeVisibility = Field(
        default=NodeVisibility.PRIVATE,
        description="Видимость узла файловой системы.",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Проверяет имя узла файловой системы.

        Args:
            value: Исходное имя узла.

        Returns:
            Нормализованное и валидное имя узла.

        Raises:
            ValueError: Если имя узла не проходит правила валидации.
        """

        return validate_node_name(value)


class NodeCreate(NodeBase):
    """Запрос на создание узла файловой системы.

    Используется для создания файла или папки с заданным именем, родительской
    папкой, видимостью и типом узла.

    Attributes:
        name: Имя файла или папки, отображаемое пользователю.
        parent_id: Идентификатор родительской папки. ``None`` означает
            корневой уровень.
        visibility: Видимость узла файловой системы.
        node_type: Тип создаваемого узла файловой системы.
    """

    node_type: NodeType = Field(
        ...,
        description="Тип создаваемого узла файловой системы.",
    )


class NodeUpdate(BaseSchema):
    """Запрос на обновление общих данных узла файловой системы.

    Позволяет изменить имя, родительскую папку и видимость узла. Поля со
    значением ``None`` не задают новое значение сами по себе и могут
    интерпретироваться сервисным слоем согласно логике обновления.

    Attributes:
        name: Новое имя узла файловой системы.
        parent_id: Новый идентификатор родительской папки. ``None`` означает
            перенос в корень.
        visibility: Новая видимость узла файловой системы.
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Новое имя узла файловой системы.",
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Новый идентификатор родительской папки. None означает перенос в корень.",
    )
    visibility: NodeVisibility | None = Field(
        default=None,
        description="Новая видимость узла файловой системы.",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        """Проверяет новое имя узла файловой системы.

        Args:
            value: Новое имя узла или ``None``.

        Returns:
            Нормализованное имя узла или ``None``, если имя не задано.

        Raises:
            ValueError: Если имя узла не проходит правила валидации.
        """

        if value is None:
            return None

        return validate_node_name(value)


class NodeRenameRequest(BaseSchema):
    """Запрос на переименование узла файловой системы.

    Используется для изменения только имени файла или папки.

    Attributes:
        name: Новое имя файла или папки.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Новое имя файла или папки.",
        examples=["Новый отчёт.pdf"],
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Проверяет новое имя узла.

        Args:
            value: Исходное новое имя узла.

        Returns:
            Нормализованное и валидное имя узла.

        Raises:
            ValueError: Если имя узла не проходит правила валидации.
        """

        return validate_node_name(value)


class NodeMoveRequest(BaseSchema):
    """Запрос на перемещение узла файловой системы.

    Используется для перемещения файла или папки в другую родительскую папку
    либо в корень файловой системы.

    Attributes:
        target_parent_id: Идентификатор целевой родительской папки. ``None``
            означает перемещение в корень.
    """

    target_parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор целевой родительской папки. None означает перемещение в корень.",
    )


class NodeCopyRequest(BaseSchema):
    """Запрос на копирование (дублирование) узла файловой системы.

    Используется для создания независимой копии файла или папки в указанной
    целевой папке либо в корне файловой системы. При копировании папки её
    содержимое копируется рекурсивно.

    Attributes:
        target_parent_id: Идентификатор целевой родительской папки. ``None``
            означает копирование в корень.
        new_name: Необязательное новое имя корневого узла копии. Если ``None``,
            используется имя исходного узла.
    """

    target_parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор целевой родительской папки. None означает копирование в корень.",
    )
    new_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Новое имя корневого узла копии. None означает использование исходного имени.",
    )

    @field_validator("new_name")
    @classmethod
    def validate_new_name(cls, value: str | None) -> str | None:
        """Проверяет необязательное новое имя копии узла.

        Args:
            value: Новое имя узла или ``None``.

        Returns:
            Нормализованное имя узла или ``None``, если имя не задано.

        Raises:
            ValueError: Если имя узла не проходит правила валидации.
        """

        if value is None:
            return None

        return validate_node_name(value)


class NodeRead(BaseSchema):
    """Полное представление узла файловой системы.

    Используется для возврата всех публичных данных узла: владельца,
    расположения, имени, типа, видимости, материализованного пути, глубины,
    audit-полей и информации о логическом удалении.

    Attributes:
        id: Уникальный идентификатор узла файловой системы.
        owner_id: Идентификатор владельца узла.
        parent_id: Идентификатор родительской папки. ``None`` означает
            корневой уровень.
        name: Имя файла или папки, отображаемое пользователю.
        node_type: Тип узла файловой системы.
        visibility: Видимость узла файловой системы.
        path: Материализованный логический путь узла.
        depth: Глубина вложенности узла.
        created_by: Идентификатор пользователя, создавшего узел.
        updated_by: Идентификатор пользователя, последним изменившего узел.
        deleted_by: Идентификатор пользователя, удалившего узел.
        created_at: Дата и время создания узла.
        updated_at: Дата и время последнего обновления узла.
        is_deleted: Признак логического удаления узла.
        deleted_at: Дата и время логического удаления узла.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор узла файловой системы.",
    )
    owner_id: UUID = Field(
        ...,
        description="Идентификатор владельца узла.",
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор родительской папки. None означает корневой уровень.",
    )
    name: str = Field(
        ...,
        description="Имя файла или папки, отображаемое пользователю.",
    )
    node_type: NodeType = Field(
        ...,
        description="Тип узла файловой системы.",
    )
    visibility: NodeVisibility = Field(
        ...,
        description="Видимость узла файловой системы.",
    )
    path: str = Field(
        ...,
        description="Материализованный логический путь узла.",
    )
    depth: int = Field(
        ...,
        ge=0,
        description="Глубина вложенности узла.",
    )
    created_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, создавшего узел.",
    )
    updated_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, последним изменившего узел.",
    )
    deleted_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, удалившего узел.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания узла.",
    )
    updated_at: datetime = Field(
        ...,
        description="Дата и время последнего обновления узла.",
    )
    is_deleted: bool = Field(
        ...,
        description="Признак логического удаления узла.",
    )
    deleted_at: datetime | None = Field(
        default=None,
        description="Дата и время логического удаления узла.",
    )


class NodeListItem(BaseSchema):
    """Краткое представление узла файловой системы для списков.

    Используется в списках файлов и папок, когда клиенту не нужны все audit-поля
    полного представления.

    Attributes:
        id: Уникальный идентификатор узла файловой системы.
        owner_id: Идентификатор владельца узла.
        parent_id: Идентификатор родительской папки. ``None`` означает
            корневой уровень.
        name: Имя файла или папки.
        node_type: Тип узла файловой системы.
        visibility: Видимость узла файловой системы.
        path: Материализованный логический путь узла.
        depth: Глубина вложенности узла.
        created_at: Дата и время создания узла.
        updated_at: Дата и время последнего обновления узла.
        is_deleted: Признак логического удаления узла.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор узла файловой системы.",
    )
    owner_id: UUID = Field(
        ...,
        description="Идентификатор владельца узла.",
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор родительской папки. None означает корневой уровень.",
    )
    name: str = Field(
        ...,
        description="Имя файла или папки.",
    )
    node_type: NodeType = Field(
        ...,
        description="Тип узла файловой системы.",
    )
    visibility: NodeVisibility = Field(
        ...,
        description="Видимость узла файловой системы.",
    )
    path: str = Field(
        ...,
        description="Материализованный логический путь узла.",
    )
    depth: int = Field(
        ...,
        ge=0,
        description="Глубина вложенности узла.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания узла.",
    )
    updated_at: datetime = Field(
        ...,
        description="Дата и время последнего обновления узла.",
    )
    is_deleted: bool = Field(
        ...,
        description="Признак логического удаления узла.",
    )
    file_size_bytes: int | None = Field(
        default=None,
        description="Размер файла в байтах. None для папок.",
    )
    file_mime_type: str | None = Field(
        default=None,
        description="MIME-тип файла. None для папок.",
    )


class NodeTreeItem(BaseSchema):
    """Элемент дерева файловой системы.

    Используется для построения иерархического ответа с вложенными дочерними
    узлами.

    Attributes:
        id: Уникальный идентификатор узла файловой системы.
        parent_id: Идентификатор родительской папки. ``None`` означает
            корневой уровень.
        name: Имя узла файловой системы.
        node_type: Тип узла файловой системы.
        visibility: Видимость узла файловой системы.
        path: Материализованный логический путь узла.
        depth: Глубина вложенности узла.
        children: Дочерние узлы файловой системы.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор узла файловой системы.",
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор родительской папки. None означает корневой уровень.",
    )
    name: str = Field(
        ...,
        description="Имя узла файловой системы.",
    )
    node_type: NodeType = Field(
        ...,
        description="Тип узла файловой системы.",
    )
    visibility: NodeVisibility = Field(
        ...,
        description="Видимость узла файловой системы.",
    )
    path: str = Field(
        ...,
        description="Материализованный логический путь узла.",
    )
    depth: int = Field(
        ...,
        ge=0,
        description="Глубина вложенности узла.",
    )
    children: list[NodeTreeItem] = Field(
        default_factory=list,
        description="Дочерние узлы файловой системы.",
    )


class NodeBreadcrumbItem(BaseSchema):
    """Элемент хлебных крошек для отображения пути.

    Используется для построения цепочки навигации от корня до текущего узла.

    Attributes:
        id: Уникальный идентификатор узла в цепочке пути.
        name: Имя узла в цепочке пути.
        node_type: Тип узла в цепочке пути.
        path: Логический путь узла.
        depth: Глубина вложенности узла.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор узла в цепочке пути.",
    )
    name: str = Field(
        ...,
        description="Имя узла в цепочке пути.",
    )
    node_type: NodeType = Field(
        ...,
        description="Тип узла в цепочке пути.",
    )
    path: str = Field(
        ...,
        description="Логический путь узла.",
    )
    depth: int = Field(
        ...,
        ge=0,
        description="Глубина вложенности узла.",
    )


class NodeQueryParams(PaginationParams):
    """Параметры фильтрации списка узлов файловой системы.

    Используется для постраничного получения списка узлов с фильтрацией по
    родительской папке, владельцу, типу, видимости, признаку удаления, датам
    создания и обновления, а также с настройками сортировки.

    Attributes:
        parent_id: Фильтр по родительской папке. ``None`` может означать
            корневой уровень.
        owner_id: Фильтр по владельцу узла.
        node_type: Фильтр по типу узла.
        visibility: Фильтр по видимости узла.
        is_deleted: Фильтр по признаку логического удаления.
        created_from: Фильтр по дате создания: начало диапазона включительно.
        created_to: Фильтр по дате создания: конец диапазона включительно.
        updated_from: Фильтр по дате обновления: начало диапазона включительно.
        updated_to: Фильтр по дате обновления: конец диапазона включительно.
        sort_by: Поле сортировки.
        sort_desc: Признак сортировки по убыванию.
    """

    parent_id: UUID | None = Field(
        default=None,
        description="Фильтр по родительской папке. None может означать корневой уровень.",
    )
    owner_id: UUID | None = Field(
        default=None,
        description="Фильтр по владельцу узла.",
    )
    node_type: NodeType | None = Field(
        default=None,
        description="Фильтр по типу узла.",
    )
    visibility: NodeVisibility | None = Field(
        default=None,
        description="Фильтр по видимости узла.",
    )
    is_deleted: bool | None = Field(
        default=False,
        description="Фильтр по признаку логического удаления.",
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
    sort_by: str = Field(
        default="name",
        min_length=1,
        max_length=64,
        description="Поле сортировки.",
        examples=["name", "created_at", "updated_at", "node_type"],
    )
    sort_desc: bool = Field(
        default=False,
        description="Сортировать по убыванию.",
    )

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


class NodeSearchQuery(PaginationParams):
    """Параметры поиска узлов файловой системы.

    Используется для постраничного поиска файлов и папок по имени или пути с
    дополнительными фильтрами по родительской папке, владельцу, типу, видимости
    и признаку логического удаления.

    Attributes:
        query: Поисковая строка по имени или пути узла.
        parent_id: Ограничить поиск указанной папкой.
        owner_id: Ограничить поиск указанным владельцем.
        node_type: Фильтр по типу узла.
        visibility: Фильтр по видимости узла.
        include_deleted: Включать ли логически удалённые узлы в результаты
            поиска.
        sort_by: Поле сортировки результатов поиска.
        sort_desc: Признак сортировки по убыванию.
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Поисковая строка по имени или пути узла.",
        examples=["отчёт", "photo", "pdf"],
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Ограничить поиск указанной папкой.",
    )
    owner_id: UUID | None = Field(
        default=None,
        description="Ограничить поиск указанным владельцем.",
    )
    node_type: NodeType | None = Field(
        default=None,
        description="Фильтр по типу узла.",
    )
    visibility: NodeVisibility | None = Field(
        default=None,
        description="Фильтр по видимости узла.",
    )
    include_deleted: bool = Field(
        default=False,
        description="Включать ли логически удалённые узлы в результаты поиска.",
    )
    sort_by: str = Field(
        default="name",
        min_length=1,
        max_length=64,
        description="Поле сортировки результатов поиска.",
        examples=["name", "created_at", "updated_at"],
    )
    sort_desc: bool = Field(
        default=False,
        description="Сортировать по убыванию.",
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        """Нормализует поисковую строку.

        Args:
            value: Исходная поисковая строка.

        Returns:
            Поисковая строка без пробелов по краям.

        Raises:
            ValueError: Если поисковая строка пустая после нормализации.
        """

        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError("query не должен быть пустым.")

        return normalized_value


class NodeOperationResponse(BaseSchema):
    """Результат операции над узлом файловой системы.

    Используется для возврата результата создания, обновления, перемещения,
    удаления, восстановления или другой операции над узлом.

    Attributes:
        success: Признак успешного выполнения операции.
        node: Узел файловой системы после выполнения операции, если применимо.
        message: Человекочитаемое сообщение о результате операции.
    """

    success: bool = Field(
        ...,
        description="Признак успешного выполнения операции.",
    )
    node: NodeRead | None = Field(
        default=None,
        description="Узел файловой системы после выполнения операции, если применимо.",
    )
    message: str = Field(
        ...,
        min_length=1,
        description="Человекочитаемое сообщение о результате операции.",
    )


class ThumbnailBatchRequest(BaseSchema):
    """Запрос на пакетное получение thumbnail URL для нескольких узлов.

    Attributes:
        node_ids: Список идентификаторов узлов файловой системы.
    """

    node_ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Список идентификаторов узлов (не более 100).",
    )


class ThumbnailBatchItem(BaseSchema):
    """Состояние миниатюры одного узла в пакетном ответе.

    Различает три исхода, чтобы клиент опрашивал повторно только те узлы,
    у которых превью реально генерируется, и не запрашивал бесконечно те,
    у которых миниатюры не будет никогда.

    Attributes:
        status: ``ready`` — миниатюра есть (см. ``url``); ``pending`` —
            превью генерируется или подписание временно не удалось, имеет
            смысл опросить позже; ``none`` — миниатюры нет и не будет
            (нет доступа, тип не поддерживается, генерация не требуется
            или завершилась отказом).
        url: Presigned URL миниатюры. Заполнен только при ``status=ready``.
    """

    status: Literal["ready", "pending", "none"] = Field(
        ...,
        description="Состояние миниатюры: ready | pending | none.",
    )
    url: str | None = Field(
        default=None,
        description="Presigned URL миниатюры (только для status=ready).",
    )


class ThumbnailBatchResponse(BaseSchema):
    """Ответ с состоянием миниатюры каждого запрошенного узла.

    Attributes:
        thumbnails: Словарь node_id → состояние миниатюры.
    """

    thumbnails: dict[str, ThumbnailBatchItem] = Field(
        ...,
        description="Словарь node_id (строка) → состояние миниатюры.",
    )
