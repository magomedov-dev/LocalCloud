from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field

T = TypeVar("T")


class BaseSchema(BaseModel):
    """Базовая схема API.

    Используется как общий родитель для DTO, которые могут создаваться из
    ORM-объектов SQLAlchemy через Pydantic v2. Задаёт единые настройки
    валидации, заполнения полей и сериализации для всех наследников.

    Attributes:
        model_config: Конфигурация Pydantic-модели.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class MessageResponse(BaseSchema):
    """Универсальный ответ с текстовым сообщением.

    Используется для простых API-ответов, когда достаточно вернуть только
    человекочитаемое сообщение о результате операции.

    Attributes:
        message: Человекочитаемое сообщение о результате операции.
    """

    message: str = Field(
        ...,
        min_length=1,
        description="Человекочитаемое сообщение о результате операции.",
        examples=["Операция выполнена успешно."],
    )


class StatusResponse(MessageResponse):
    """Универсальный ответ со статусом выполнения операции.

    Расширяет текстовый ответ признаком успешности и необязательным
    машиночитаемым статусом.

    Attributes:
        message: Человекочитаемое сообщение о результате операции.
        success: Признак успешного выполнения операции.
        status: Машиночитаемый статус операции.
    """

    success: bool = Field(
        ...,
        description="Признак успешного выполнения операции.",
    )
    status: str | None = Field(
        default=None,
        description="Машиночитаемый статус операции.",
        examples=["ok", "created", "updated", "deleted"],
    )


class ErrorDetail(BaseSchema):
    """Описание одной ошибки или причины отказа.

    Используется как элемент детализации ошибок API, включая ошибки валидации,
    доменные ошибки и частичные ошибки массовых операций.

    Attributes:
        code: Машиночитаемый код ошибки.
        message: Человекочитаемое описание ошибки.
        field: Поле, с которым связана ошибка, если применимо.
        details: Дополнительные структурированные сведения об ошибке.
    """

    code: str | None = Field(
        default=None,
        description="Машиночитаемый код ошибки.",
        examples=["entity_not_found", "validation_error"],
    )
    message: str = Field(
        ...,
        min_length=1,
        description="Человекочитаемое описание ошибки.",
    )
    field: str | None = Field(
        default=None,
        description="Поле, с которым связана ошибка, если применимо.",
        examples=["email", "password", "node_id"],
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Дополнительные структурированные сведения об ошибке.",
    )


class ErrorResponse(BaseSchema):
    """Универсальный ответ API при ошибке.

    Используется для стандартизированного ответа при исключениях и ошибках
    бизнес-логики.

    Attributes:
        success: Признак успешности операции. Для ошибки всегда ``False``.
        error: Краткое машинное имя ошибки или тип исключения.
        message: Человекочитаемое сообщение об ошибке.
        details: Дополнительные сведения об ошибке.
        request_id: Идентификатор HTTP-запроса для трассировки ошибки.
    """

    success: bool = Field(
        default=False,
        description="Признак успешности операции. Для ошибки всегда false.",
    )
    error: str = Field(
        ...,
        min_length=1,
        description="Краткое машинное имя ошибки или тип исключения.",
        examples=["EntityNotFoundError", "ValidationError"],
    )
    message: str = Field(
        ...,
        min_length=1,
        description="Человекочитаемое сообщение об ошибке.",
    )
    details: dict[str, Any] | list[ErrorDetail] | None = Field(
        default=None,
        description="Дополнительные сведения об ошибке.",
    )
    request_id: str | None = Field(
        default=None,
        description="Идентификатор HTTP-запроса для трассировки ошибки.",
    )


class ValidationErrorItem(BaseSchema):
    """Описание ошибки валидации отдельного поля.

    Используется для передачи клиенту информации о конкретном поле или пути,
    в котором была обнаружена ошибка валидации.

    Attributes:
        field: Имя поля или путь к полю, в котором обнаружена ошибка.
        message: Описание ошибки валидации.
        code: Машиночитаемый код ошибки валидации.
        value: Переданное значение, вызвавшее ошибку, если его безопасно
            возвращать клиенту.
    """

    field: str = Field(
        ...,
        min_length=1,
        description="Имя поля или путь к полю, в котором обнаружена ошибка.",
        examples=["body.email", "query.limit"],
    )
    message: str = Field(
        ...,
        min_length=1,
        description="Описание ошибки валидации.",
    )
    code: str | None = Field(
        default=None,
        description="Машиночитаемый код ошибки валидации.",
        examples=["string_too_short", "greater_than_equal"],
    )
    value: Any | None = Field(
        default=None,
        description="Переданное значение, вызвавшее ошибку, если его безопасно возвращать клиенту.",
    )


class ValidationErrorResponse(BaseSchema):
    """Универсальный ответ API при ошибке валидации данных.

    Возвращается, когда входные данные не прошли проверку схемы или
    пользовательских валидаторов.

    Attributes:
        success: Признак успешности операции. Для ошибки валидации всегда
            ``False``.
        error: Тип ошибки.
        message: Общее описание ошибки валидации.
        errors: Список ошибок валидации по отдельным полям.
        request_id: Идентификатор HTTP-запроса для трассировки ошибки.
    """

    success: bool = Field(
        default=False,
        description="Признак успешности операции. Для ошибки валидации всегда false.",
    )
    error: str = Field(
        default="ValidationError",
        description="Тип ошибки.",
    )
    message: str = Field(
        default="Переданы некорректные данные.",
        description="Общее описание ошибки валидации.",
    )
    errors: list[ValidationErrorItem] = Field(
        default_factory=list,
        description="Список ошибок валидации по отдельным полям.",
    )
    request_id: str | None = Field(
        default=None,
        description="Идентификатор HTTP-запроса для трассировки ошибки.",
    )


class PaginationParams(BaseSchema):
    """Параметры постраничной выборки.

    Используется в query-параметрах API для ограничения размера страницы и
    задания смещения от начала выборки.

    Attributes:
        limit: Максимальное количество элементов в ответе.
        offset: Смещение от начала выборки.
    """

    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Максимальное количество элементов в ответе.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Смещение от начала выборки.",
    )


class PageMeta(BaseSchema):
    """Метаданные постраничного ответа.

    Содержит информацию о текущей странице, общем количестве элементов и
    вычисляемые признаки наличия соседних страниц.

    Attributes:
        limit: Максимальное количество элементов в текущей выборке.
        offset: Смещение текущей выборки от начала списка.
        total: Общее количество элементов, соответствующих запросу.
        count: Фактическое количество элементов в текущем ответе.
        has_next: Есть ли следующая страница.
        has_previous: Есть ли предыдущая страница.
        page: Номер текущей страницы, начиная с 1.
        pages: Общее количество страниц.
    """

    limit: int = Field(
        ...,
        ge=1,
        description="Максимальное количество элементов в текущей выборке.",
    )
    offset: int = Field(
        ...,
        ge=0,
        description="Смещение текущей выборки от начала списка.",
    )
    total: int = Field(
        ...,
        ge=0,
        description="Общее количество элементов, соответствующих запросу.",
    )
    count: int = Field(
        ...,
        ge=0,
        description="Фактическое количество элементов в текущем ответе.",
    )

    @computed_field(description="Есть ли следующая страница.")
    @property
    def has_next(self) -> bool:
        """Проверяет наличие следующей страницы.

        Returns:
            ``True``, если после текущей страницы есть элементы, иначе
            ``False``.
        """

        return self.offset + self.count < self.total

    @computed_field(description="Есть ли предыдущая страница.")
    @property
    def has_previous(self) -> bool:
        """Проверяет наличие предыдущей страницы.

        Returns:
            ``True``, если текущая выборка начинается не с первого элемента,
            иначе ``False``.
        """

        return self.offset > 0

    @computed_field(description="Номер текущей страницы, начиная с 1.")
    @property
    def page(self) -> int:
        """Вычисляет номер текущей страницы.

        Returns:
            Номер текущей страницы, начиная с 1. Если ``limit`` некорректен,
            возвращает ``1``.
        """

        if self.limit <= 0:
            return 1
        return self.offset // self.limit + 1

    @computed_field(description="Общее количество страниц.")
    @property
    def pages(self) -> int:
        """Вычисляет общее количество страниц.

        Returns:
            Общее количество страниц. Если элементов нет, возвращает ``0``.
        """

        if self.total == 0:
            return 0
        return (self.total + self.limit - 1) // self.limit


class PageResponse(BaseSchema, Generic[T]):
    """Универсальный постраничный ответ.

    Используется для API-методов, возвращающих список элементов с метаданными
    пагинации.

    Attributes:
        items: Элементы текущей страницы.
        meta: Метаданные пагинации.
    """

    items: list[T] = Field(
        default_factory=list,
        description="Элементы текущей страницы.",
    )
    meta: PageMeta = Field(
        ...,
        description="Метаданные пагинации.",
    )
