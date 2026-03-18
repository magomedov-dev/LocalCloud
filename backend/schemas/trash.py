from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, ValidationInfo, field_validator, model_validator

from database.models.enums import TrashItemStatus
from schemas.common import BaseSchema, PaginationParams
from schemas.nodes import NodeListItem


class TrashItemRead(BaseSchema):
    """Полное представление элемента корзины.

    Используется для возврата подробной информации об удалённом узле файловой
    системы: владельце, пользователе, выполнившем удаление, исходном
    расположении, статусе, сроке хранения, возможности восстановления и данных
    связанного узла.

    Attributes:
        id: Уникальный идентификатор элемента корзины.
        node_id: Идентификатор удалённого узла файловой системы.
        owner_id: Идентификатор владельца удалённого узла.
        deleted_by: Идентификатор пользователя, который переместил узел в
            корзину.
        original_parent_id: Идентификатор исходной родительской папки до
            удаления.
        original_path: Исходный логический путь узла до удаления.
        status: Текущий статус элемента корзины.
        deleted_at: Дата и время перемещения узла в корзину.
        expires_at: Дата и время, после которых элемент может быть
            окончательно удалён.
        restore_available: Признак возможности восстановления элемента.
        purged_at: Дата и время окончательного удаления элемента.
        node: Краткие данные удалённого узла, если они были загружены.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор элемента корзины.",
    )
    node_id: UUID = Field(
        ...,
        description="Идентификатор удалённого узла файловой системы.",
    )
    owner_id: UUID = Field(
        ...,
        description="Идентификатор владельца удалённого узла.",
    )
    deleted_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, который переместил узел в корзину.",
    )
    original_parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор исходной родительской папки до удаления.",
    )
    original_path: str = Field(
        ...,
        description="Исходный логический путь узла до удаления.",
    )
    status: TrashItemStatus = Field(
        ...,
        description="Текущий статус элемента корзины.",
    )
    deleted_at: datetime = Field(
        ...,
        description="Дата и время перемещения узла в корзину.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Дата и время, после которых элемент может быть окончательно удалён.",
    )
    restore_available: bool = Field(
        ...,
        description="Признак возможности восстановления элемента.",
    )
    purged_at: datetime | None = Field(
        default=None,
        description="Дата и время окончательного удаления элемента.",
    )
    node: NodeListItem | None = Field(
        default=None,
        description="Краткие данные удалённого узла, если они были загружены.",
    )


class TrashItemListItem(BaseSchema):
    """Краткое представление элемента корзины для списков.

    Используется в списках элементов корзины, когда нужны основные сведения об
    удалённом узле, его исходном расположении, статусе, сроке хранения и
    возможности восстановления.

    Attributes:
        id: Уникальный идентификатор элемента корзины.
        node_id: Идентификатор удалённого узла файловой системы.
        owner_id: Идентификатор владельца удалённого узла.
        deleted_by: Идентификатор пользователя, который переместил узел в
            корзину.
        original_parent_id: Идентификатор исходной родительской папки до
            удаления.
        original_path: Исходный логический путь узла до удаления.
        status: Текущий статус элемента корзины.
        deleted_at: Дата и время перемещения узла в корзину.
        expires_at: Дата и время, после которых элемент может быть
            окончательно удалён.
        restore_available: Признак возможности восстановления элемента.
        purged_at: Дата и время окончательного удаления элемента.
        node: Краткие данные удалённого узла, если они были загружены.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор элемента корзины.",
    )
    node_id: UUID = Field(
        ...,
        description="Идентификатор удалённого узла файловой системы.",
    )
    owner_id: UUID = Field(
        ...,
        description="Идентификатор владельца удалённого узла.",
    )
    deleted_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, который переместил узел в корзину.",
    )
    original_parent_id: UUID | None = Field(
        default=None,
        description="Идентификатор исходной родительской папки до удаления.",
    )
    original_path: str = Field(
        ...,
        description="Исходный логический путь узла до удаления.",
    )
    status: TrashItemStatus = Field(
        ...,
        description="Текущий статус элемента корзины.",
    )
    deleted_at: datetime = Field(
        ...,
        description="Дата и время перемещения узла в корзину.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Дата и время, после которых элемент может быть окончательно удалён.",
    )
    restore_available: bool = Field(
        ...,
        description="Признак возможности восстановления элемента.",
    )
    purged_at: datetime | None = Field(
        default=None,
        description="Дата и время окончательного удаления элемента.",
    )
    node: NodeListItem | None = Field(
        default=None,
        description="Краткие данные удалённого узла, если они были загружены.",
    )


class TrashQueryParams(PaginationParams):
    """Параметры фильтрации элементов корзины.

    Используется для постраничного получения элементов корзины с фильтрами по
    владельцу, пользователю, выполнившему удаление, статусу, возможности
    восстановления, датам удаления, сроку хранения и поисковой строке.

    Attributes:
        owner_id: Фильтр по владельцу удалённых элементов.
        deleted_by: Фильтр по пользователю, который переместил элементы в
            корзину.
        status: Фильтр по статусу элемента корзины.
        restore_available: Фильтр по возможности восстановления.
        deleted_from: Фильтр по дате удаления: начало диапазона включительно.
        deleted_to: Фильтр по дате удаления: конец диапазона включительно.
        expires_before: Вернуть элементы, срок хранения которых истекает не
            позднее указанного времени.
        query: Поисковая строка по исходному пути или имени удалённого узла.
        sort_by: Поле сортировки.
        sort_desc: Признак сортировки по убыванию.
    """

    owner_id: UUID | None = Field(
        default=None,
        description="Фильтр по владельцу удалённых элементов.",
    )
    deleted_by: UUID | None = Field(
        default=None,
        description="Фильтр по пользователю, который переместил элементы в корзину.",
    )
    status: TrashItemStatus | None = Field(
        default=TrashItemStatus.IN_TRASH,
        description="Фильтр по статусу элемента корзины.",
    )
    restore_available: bool | None = Field(
        default=None,
        description="Фильтр по возможности восстановления.",
    )
    deleted_from: datetime | None = Field(
        default=None,
        description="Фильтр по дате удаления: начало диапазона включительно.",
    )
    deleted_to: datetime | None = Field(
        default=None,
        description="Фильтр по дате удаления: конец диапазона включительно.",
    )
    expires_before: datetime | None = Field(
        default=None,
        description="Вернуть элементы, срок хранения которых истекает не позднее указанного времени.",
    )
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Поисковая строка по исходному пути или имени удалённого узла.",
    )
    sort_by: str = Field(
        default="deleted_at",
        min_length=1,
        max_length=64,
        description="Поле сортировки.",
        examples=["deleted_at", "expires_at", "original_path", "status"],
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
            value: Исходная поисковая строка.

        Returns:
            Поисковая строка без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("deleted_to")
    @classmethod
    def validate_deleted_range(
        cls,
        value: datetime | None,
        info: ValidationInfo,
    ) -> datetime | None:
        """Проверяет корректность диапазона даты удаления.

        Args:
            value: Значение верхней границы диапазона ``deleted_to``.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Значение ``deleted_to``, если диапазон корректен.

        Raises:
            ValueError: Если ``deleted_to`` меньше ``deleted_from``.
        """

        deleted_from = info.data.get("deleted_from")

        if deleted_from is not None and value is not None and value < deleted_from:
            raise ValueError("deleted_to не может быть раньше deleted_from.")

        return value


class TrashRestoreRequest(BaseSchema):
    """Запрос на восстановление элемента из корзины.

    Элемент для восстановления можно идентифицировать через ``trash_item_id``
    или ``node_id``. Целевая папка может быть задана явно либо определяться
    сервисным слоем.

    Attributes:
        trash_item_id: Идентификатор элемента корзины, который нужно
            восстановить.
        node_id: Идентификатор узла файловой системы, который нужно
            восстановить.
        target_parent_id: Идентификатор целевой родительской папки для
            восстановления. ``None`` означает восстановление в исходное
            расположение или в корень, если это определено сервисным слоем.
    """

    trash_item_id: UUID | None = Field(
        default=None,
        description="Идентификатор элемента корзины, который нужно восстановить.",
    )
    node_id: UUID | None = Field(
        default=None,
        description="Идентификатор узла файловой системы, который нужно восстановить.",
    )
    target_parent_id: UUID | None = Field(
        default=None,
        description=(
            "Идентификатор целевой родительской папки для восстановления. "
            "None означает восстановление в исходное расположение или в корень, "
            "если это определено сервисным слоем."
        ),
    )

    @model_validator(mode="after")
    def validate_identifier(self) -> TrashRestoreRequest:
        """Проверяет наличие идентификатора восстанавливаемого элемента.

        Returns:
            Текущий объект запроса, если он корректен.

        Raises:
            ValueError: Если не передан ни ``trash_item_id``, ни ``node_id``.
        """

        if self.trash_item_id is None and self.node_id is None:
            raise ValueError("Нужно передать trash_item_id или node_id.")

        return self


class TrashRestoreResponse(BaseSchema):
    """Ответ после восстановления элемента из корзины.

    Используется для возврата результата восстановления, обновлённого элемента
    корзины, восстановленного узла и человекочитаемого сообщения.

    Attributes:
        success: Признак успешного восстановления.
        trash_item: Элемент корзины после восстановления, если он возвращается
            сервисом.
        node: Восстановленный узел файловой системы, если он возвращается
            сервисом.
        message: Сообщение о результате восстановления.
    """

    success: bool = Field(
        ...,
        description="Признак успешного восстановления.",
    )
    trash_item: TrashItemRead | None = Field(
        default=None,
        description="Элемент корзины после восстановления, если он возвращается сервисом.",
    )
    node: NodeListItem | None = Field(
        default=None,
        description="Восстановленный узел файловой системы, если он возвращается сервисом.",
    )
    message: str = Field(
        default="Элемент успешно восстановлен из корзины.",
        description="Сообщение о результате восстановления.",
    )


class TrashPurgeRequest(BaseSchema):
    """Запрос на окончательное удаление элементов из корзины.

    Элементы можно указать через список идентификаторов элементов корзины или
    через список идентификаторов узлов. Списки не должны содержать дубликаты.

    Attributes:
        trash_item_ids: Список идентификаторов элементов корзины для
            окончательного удаления.
        node_ids: Список идентификаторов узлов для окончательного удаления.
        reason: Причина окончательного удаления.
    """

    trash_item_ids: list[UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=1000,
        description="Список идентификаторов элементов корзины для окончательного удаления.",
    )
    node_ids: list[UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=1000,
        description="Список идентификаторов узлов для окончательного удаления.",
    )
    reason: str | None = Field(
        default=None,
        max_length=512,
        description="Причина окончательного удаления.",
    )

    @field_validator("trash_item_ids", "node_ids")
    @classmethod
    def validate_unique_ids(cls, value: list[UUID] | None) -> list[UUID] | None:
        """Проверяет уникальность идентификаторов.

        Args:
            value: Список идентификаторов элементов корзины или узлов.

        Returns:
            Исходный список идентификаторов или ``None``, если список не
            передан.

        Raises:
            ValueError: Если список содержит дубликаты.
        """

        if value is None:
            return None

        if len(value) != len(set(value)):
            raise ValueError("Список идентификаторов не должен содержать дубликаты.")

        return value

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        """Нормализует причину окончательного удаления.

        Args:
            value: Исходная причина окончательного удаления.

        Returns:
            Причина без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @model_validator(mode="after")
    def validate_identifiers(self) -> TrashPurgeRequest:
        """Проверяет наличие элементов для окончательного удаления.

        Returns:
            Текущий объект запроса, если он содержит идентификаторы для
            удаления.

        Raises:
            ValueError: Если не переданы ни ``trash_item_ids``, ни
                ``node_ids``.
        """

        if not self.trash_item_ids and not self.node_ids:
            raise ValueError("Нужно передать trash_item_ids или node_ids.")

        return self


class TrashPurgeResponse(BaseSchema):
    """Ответ после окончательного удаления элементов из корзины.

    Используется для возврата результата массового окончательного удаления:
    количества запрошенных, удалённых и неуспешно обработанных элементов, а
    также списков успешных и ошибочных идентификаторов.

    Attributes:
        success: Признак успешного выполнения операции.
        requested_count: Количество элементов, запрошенных для окончательного
            удаления.
        purged_count: Количество окончательно удалённых элементов.
        failed_count: Количество элементов, которые не удалось окончательно
            удалить.
        purged_trash_item_ids: Идентификаторы окончательно удалённых элементов
            корзины.
        failed_trash_item_ids: Идентификаторы элементов корзины, которые не
            удалось удалить.
        message: Сообщение о результате операции.
    """

    success: bool = Field(
        ...,
        description="Признак успешного выполнения операции.",
    )
    requested_count: int = Field(
        ...,
        ge=0,
        description="Количество элементов, запрошенных для окончательного удаления.",
    )
    purged_count: int = Field(
        ...,
        ge=0,
        description="Количество окончательно удалённых элементов.",
    )
    failed_count: int = Field(
        default=0,
        ge=0,
        description="Количество элементов, которые не удалось окончательно удалить.",
    )
    purged_trash_item_ids: list[UUID] = Field(
        default_factory=list,
        description="Идентификаторы окончательно удалённых элементов корзины.",
    )
    failed_trash_item_ids: list[UUID] = Field(
        default_factory=list,
        description="Идентификаторы элементов корзины, которые не удалось удалить.",
    )
    message: str = Field(
        default="Окончательное удаление элементов корзины выполнено.",
        description="Сообщение о результате операции.",
    )


class TrashEmptyRequest(BaseSchema):
    """Запрос на очистку корзины пользователя.

    Используется для очистки корзины конкретного пользователя или корзины
    текущего пользователя, если владелец определяется из сессии.

    Attributes:
        owner_id: Идентификатор владельца корзины. Для обычного пользователя
            может определяться из текущей сессии, для администратора может
            передаваться явно.
        only_expired: Удалять только элементы с истёкшим сроком хранения.
        reason: Причина очистки корзины.
    """

    owner_id: UUID | None = Field(
        default=None,
        description=(
            "Идентификатор владельца корзины. Для обычного пользователя может определяться "
            "из текущей сессии, для администратора может передаваться явно."
        ),
    )
    only_expired: bool = Field(
        default=False,
        description="Удалять только элементы с истёкшим сроком хранения.",
    )
    reason: str | None = Field(
        default=None,
        max_length=512,
        description="Причина очистки корзины.",
    )

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        """Нормализует причину очистки корзины.

        Args:
            value: Исходная причина очистки.

        Returns:
            Причина без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class TrashCleanupRequest(BaseSchema):
    """Запрос на системную очистку устаревших элементов корзины.

    Используется для фоновой или административной очистки элементов корзины по
    владельцу, дате удаления, истечению срока хранения и лимиту обработки.
    Поддерживает пробный запуск без фактического удаления.

    Attributes:
        owner_id: Ограничить очистку корзиной конкретного пользователя.
        older_than: Удалять элементы, перемещённые в корзину раньше указанного
            времени.
        expired_before: Удалять элементы, срок хранения которых истёк раньше
            указанного времени.
        limit: Максимальное количество элементов для обработки за один запуск
            очистки.
        dry_run: Выполнить пробный запуск без фактического удаления.
    """

    owner_id: UUID | None = Field(
        default=None,
        description="Ограничить очистку корзиной конкретного пользователя.",
    )
    older_than: datetime | None = Field(
        default=None,
        description="Удалять элементы, перемещённые в корзину раньше указанного времени.",
    )
    expired_before: datetime | None = Field(
        default=None,
        description="Удалять элементы, срок хранения которых истёк раньше указанного времени.",
    )
    limit: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Максимальное количество элементов для обработки за один запуск очистки.",
    )
    dry_run: bool = Field(
        default=False,
        description="Выполнить пробный запуск без фактического удаления.",
    )
