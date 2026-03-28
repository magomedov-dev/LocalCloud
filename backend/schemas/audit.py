from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, ConfigDict, Field, ValidationInfo, field_validator

from database.models.enums import AuditAction, AuditResourceType, AuditResult
from schemas.common import BaseSchema, PaginationParams


class AuditLogRead(BaseSchema):
    """Схема полного представления события аудита.

    Используется для возврата полного события аудита через API. Содержит
    основные сведения о действии, контекст HTTP-запроса, данные затронутой
    сущности, информацию об ошибке, дополнительные метаданные и дату создания
    события.

    Attributes:
        id: Уникальный идентификатор события аудита.
        user_id: Идентификатор пользователя, выполнившего действие, или
            ``None`` для системных действий.
        action: Тип действия, выполненного в системе.
        result: Результат выполнения действия.
        entity_type: Тип сущности, затронутой действием.
        entity_id: Идентификатор затронутой сущности.
        resource_type: Нормализованный тип ресурса для фильтрации событий
            аудита.
        request_id: Идентификатор HTTP-запроса, в рамках которого создано
            событие.
        correlation_id: Идентификатор корреляции для связывания нескольких
            событий.
        ip_address: IP-адрес, с которого было выполнено действие.
        user_agent: User-Agent клиента, выполнившего действие.
        message: Краткое человекочитаемое описание события.
        error_code: Машиночитаемый код ошибки, если действие завершилось
            неуспешно.
        metadata: Дополнительные структурированные данные события аудита.
        created_at: Дата и время создания события аудита.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор события аудита.",
    )
    user_id: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, выполнившего действие. None означает системное действие.",
    )
    action: AuditAction = Field(
        ...,
        description="Тип действия, выполненного в системе.",
    )
    result: AuditResult = Field(
        ...,
        description="Результат выполнения действия.",
    )
    entity_type: str | None = Field(
        default=None,
        max_length=128,
        description="Тип сущности, затронутой действием.",
    )
    entity_id: UUID | None = Field(
        default=None,
        description="Идентификатор затронутой сущности.",
    )
    resource_type: AuditResourceType | None = Field(
        default=None,
        description="Нормализованный тип ресурса для фильтрации событий аудита.",
    )
    request_id: str | None = Field(
        default=None,
        max_length=128,
        description="Идентификатор HTTP-запроса, в рамках которого создано событие.",
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Идентификатор корреляции для связывания нескольких событий.",
    )
    ip_address: str | None = Field(
        default=None,
        description="IP-адрес, с которого было выполнено действие.",
    )
    user_agent: str | None = Field(
        default=None,
        description="User-Agent клиента, выполнившего действие.",
    )
    message: str | None = Field(
        default=None,
        description="Краткое человекочитаемое описание события.",
    )
    error_code: str | None = Field(
        default=None,
        max_length=128,
        description="Машиночитаемый код ошибки, если действие завершилось неуспешно.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata", "metadata_"),
        serialization_alias="metadata",
        description="Дополнительные структурированные данные события аудита.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания события аудита.",
    )


class AuditLogListItem(BaseSchema):
    """Краткое представление события аудита для списков.

    Используется в ответах API со списком событий аудита, когда клиенту не
    требуется полный контекст события, включая User-Agent и metadata.

    Attributes:
        id: Уникальный идентификатор события аудита.
        user_id: Идентификатор пользователя, выполнившего действие, или
            ``None`` для системных действий.
        action: Тип действия, выполненного в системе.
        result: Результат выполнения действия.
        entity_type: Тип сущности, затронутой действием.
        entity_id: Идентификатор затронутой сущности.
        resource_type: Нормализованный тип ресурса.
        request_id: Идентификатор HTTP-запроса.
        correlation_id: Идентификатор корреляции.
        ip_address: IP-адрес, с которого было выполнено действие.
        message: Краткое описание события.
        error_code: Машиночитаемый код ошибки.
        created_at: Дата и время создания события аудита.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор события аудита.",
    )
    user_id: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, выполнившего действие. None означает системное действие.",
    )
    action: AuditAction = Field(
        ...,
        description="Тип действия, выполненного в системе.",
    )
    result: AuditResult = Field(
        ...,
        description="Результат выполнения действия.",
    )
    entity_type: str | None = Field(
        default=None,
        max_length=128,
        description="Тип сущности, затронутой действием.",
    )
    entity_id: UUID | None = Field(
        default=None,
        description="Идентификатор затронутой сущности.",
    )
    resource_type: AuditResourceType | None = Field(
        default=None,
        description="Нормализованный тип ресурса.",
    )
    request_id: str | None = Field(
        default=None,
        max_length=128,
        description="Идентификатор HTTP-запроса.",
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Идентификатор корреляции.",
    )
    ip_address: str | None = Field(
        default=None,
        description="IP-адрес, с которого было выполнено действие.",
    )
    message: str | None = Field(
        default=None,
        description="Краткое описание события.",
    )
    error_code: str | None = Field(
        default=None,
        max_length=128,
        description="Машиночитаемый код ошибки.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания события аудита.",
    )


class AuditLogCreate(BaseSchema):
    """Схема создания события аудита.

    Используется сервисным слоем для создания событий аудита. Текстовые поля
    нормализуются: пробелы по краям удаляются, пустые строки приводятся к
    ``None``.

    Attributes:
        user_id: Идентификатор пользователя, выполнившего действие, или
            ``None`` для системных действий.
        action: Тип действия, выполненного в системе.
        result: Результат выполнения действия.
        entity_type: Тип сущности, затронутой действием.
        entity_id: Идентификатор затронутой сущности.
        resource_type: Нормализованный тип ресурса для фильтрации событий
            аудита.
        request_id: Идентификатор HTTP-запроса.
        correlation_id: Идентификатор корреляции.
        ip_address: IP-адрес, с которого было выполнено действие.
        user_agent: User-Agent клиента, выполнившего действие.
        message: Краткое человекочитаемое описание события.
        error_code: Машиночитаемый код ошибки.
        metadata: Дополнительные структурированные данные события аудита.
    """

    user_id: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, выполнившего действие. None означает системное действие.",
    )
    action: AuditAction = Field(
        ...,
        description="Тип действия, выполненного в системе.",
    )
    result: AuditResult = Field(
        default=AuditResult.SUCCESS,
        description="Результат выполнения действия.",
    )
    entity_type: str | None = Field(
        default=None,
        max_length=128,
        description="Тип сущности, затронутой действием.",
    )
    entity_id: UUID | None = Field(
        default=None,
        description="Идентификатор затронутой сущности.",
    )
    resource_type: AuditResourceType | None = Field(
        default=None,
        description="Нормализованный тип ресурса для фильтрации событий аудита.",
    )
    request_id: str | None = Field(
        default=None,
        max_length=128,
        description="Идентификатор HTTP-запроса.",
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Идентификатор корреляции.",
    )
    ip_address: str | None = Field(
        default=None,
        description="IP-адрес, с которого было выполнено действие.",
    )
    user_agent: str | None = Field(
        default=None,
        description="User-Agent клиента, выполнившего действие.",
    )
    message: str | None = Field(
        default=None,
        description="Краткое человекочитаемое описание события.",
    )
    error_code: str | None = Field(
        default=None,
        max_length=128,
        description="Машиночитаемый код ошибки.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata", "metadata_"),
        serialization_alias="metadata",
        description="Дополнительные структурированные данные события аудита.",
    )

    @field_validator(
        "entity_type",
        "request_id",
        "correlation_id",
        "ip_address",
        "user_agent",
        "message",
        "error_code",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Нормализует необязательное текстовое поле.

        Удаляет пробелы по краям строки. Если после нормализации строка
        становится пустой, возвращает ``None``.

        Args:
            value: Исходное значение текстового поля.

        Returns:
            Нормализованная строка или ``None``, если значение отсутствует
            либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class AuditQueryParams(PaginationParams):
    """Параметры фильтрации журнала аудита.

    Используются для получения списка событий аудита с пагинацией, фильтрами,
    поисковой строкой и настройками сортировки.

    Attributes:
        user_id: Фильтр по пользователю, выполнившему действие.
        action: Фильтр по типу действия.
        result: Фильтр по результату выполнения действия.
        resource_type: Фильтр по нормализованному типу ресурса.
        entity_type: Фильтр по типу затронутой сущности.
        entity_id: Фильтр по идентификатору затронутой сущности.
        request_id: Фильтр по идентификатору HTTP-запроса.
        correlation_id: Фильтр по идентификатору корреляции.
        ip_address: Фильтр по IP-адресу клиента.
        created_from: Начало диапазона даты создания события включительно.
        created_to: Конец диапазона даты создания события включительно.
        query: Поисковая строка по сообщению, коду ошибки, request_id или
            correlation_id.
        sort_by: Поле сортировки.
        sort_desc: Признак сортировки по убыванию.
    """

    user_id: UUID | None = Field(
        default=None,
        description="Фильтр по пользователю, выполнившему действие.",
    )
    action: AuditAction | None = Field(
        default=None,
        description="Фильтр по типу действия.",
    )
    result: AuditResult | None = Field(
        default=None,
        description="Фильтр по результату выполнения действия.",
    )
    resource_type: AuditResourceType | None = Field(
        default=None,
        description="Фильтр по нормализованному типу ресурса.",
    )
    entity_type: str | None = Field(
        default=None,
        max_length=128,
        description="Фильтр по типу затронутой сущности.",
    )
    entity_id: UUID | None = Field(
        default=None,
        description="Фильтр по идентификатору затронутой сущности.",
    )
    request_id: str | None = Field(
        default=None,
        max_length=128,
        description="Фильтр по идентификатору HTTP-запроса.",
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Фильтр по идентификатору корреляции.",
    )
    ip_address: str | None = Field(
        default=None,
        description="Фильтр по IP-адресу клиента.",
    )
    created_from: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания события: начало диапазона включительно.",
    )
    created_to: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания события: конец диапазона включительно.",
    )
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Поисковая строка по сообщению, коду ошибки, request_id или correlation_id.",
    )
    sort_by: str = Field(
        default="created_at",
        min_length=1,
        max_length=64,
        description="Поле сортировки.",
        examples=["created_at", "action", "result", "resource_type"],
    )
    sort_desc: bool = Field(
        default=True,
        description="Сортировать по убыванию.",
    )

    @field_validator(
        "entity_type",
        "request_id",
        "correlation_id",
        "ip_address",
        "query",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Нормализует необязательное текстовое поле фильтра.

        Args:
            value: Исходное значение фильтра.

        Returns:
            Нормализованная строка без пробелов по краям или ``None``, если
            значение отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("created_to")
    @classmethod
    def validate_created_range(
        cls,
        value: datetime | None,
        info: ValidationInfo,
    ) -> datetime | None:
        """Проверяет корректность диапазона дат создания события.

        Args:
            value: Значение верхней границы диапазона ``created_to``.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Значение ``created_to``, если диапазон корректен.

        Raises:
            ValueError: Если ``created_to`` меньше ``created_from``.
        """

        created_from = info.data.get("created_from")

        if created_from is not None and value is not None and value < created_from:
            raise ValueError("created_to не может быть раньше created_from.")

        return value


class AuditExportRequest(BaseSchema):
    """Запрос на экспорт журнала аудита.

    Используется для выгрузки событий аудита в поддерживаемом формате с
    применением фильтров, ограничения количества записей и настройки включения
    metadata.

    Attributes:
        user_id: Фильтр экспорта по пользователю.
        action: Фильтр экспорта по типу действия.
        result: Фильтр экспорта по результату действия.
        resource_type: Фильтр экспорта по типу ресурса.
        entity_type: Фильтр экспорта по типу сущности.
        entity_id: Фильтр экспорта по идентификатору сущности.
        request_id: Фильтр экспорта по идентификатору HTTP-запроса.
        correlation_id: Фильтр экспорта по идентификатору корреляции.
        created_from: Начало периода экспорта включительно.
        created_to: Конец периода экспорта включительно.
        format: Формат экспорта журнала аудита.
        include_metadata: Признак включения metadata событий в экспорт.
        limit: Максимальное количество событий для экспорта.
    """

    user_id: UUID | None = Field(
        default=None,
        description="Фильтр экспорта по пользователю.",
    )
    action: AuditAction | None = Field(
        default=None,
        description="Фильтр экспорта по типу действия.",
    )
    result: AuditResult | None = Field(
        default=None,
        description="Фильтр экспорта по результату действия.",
    )
    resource_type: AuditResourceType | None = Field(
        default=None,
        description="Фильтр экспорта по типу ресурса.",
    )
    entity_type: str | None = Field(
        default=None,
        max_length=128,
        description="Фильтр экспорта по типу сущности.",
    )
    entity_id: UUID | None = Field(
        default=None,
        description="Фильтр экспорта по идентификатору сущности.",
    )
    request_id: str | None = Field(
        default=None,
        max_length=128,
        description="Фильтр экспорта по идентификатору HTTP-запроса.",
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Фильтр экспорта по идентификатору корреляции.",
    )
    created_from: datetime | None = Field(
        default=None,
        description="Начало периода экспорта включительно.",
    )
    created_to: datetime | None = Field(
        default=None,
        description="Конец периода экспорта включительно.",
    )
    format: str = Field(
        default="json",
        min_length=1,
        max_length=16,
        description="Формат экспорта журнала аудита.",
        examples=["json", "csv"],
    )
    include_metadata: bool = Field(
        default=True,
        description="Включать ли metadata событий в экспорт.",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=100_000,
        description="Максимальное количество событий для экспорта.",
    )

    @field_validator(
        "entity_type",
        "request_id",
        "correlation_id",
        "format",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Нормализует текстовые поля запроса на экспорт.

        Args:
            value: Исходное значение текстового поля.

        Returns:
            Нормализованная строка без пробелов по краям или ``None``, если
            значение отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        """Проверяет и нормализует формат экспорта.

        Args:
            value: Исходное значение формата экспорта.

        Returns:
            Нормализованное значение формата в нижнем регистре.

        Raises:
            ValueError: Если формат не входит в список поддерживаемых значений:
                ``json`` или ``csv``.
        """

        normalized_value = value.strip().lower()

        if normalized_value not in {"json", "csv"}:
            raise ValueError("format должен быть json или csv.")

        return normalized_value

    @field_validator("created_to")
    @classmethod
    def validate_created_range(
        cls,
        value: datetime | None,
        info: ValidationInfo,
    ) -> datetime | None:
        """Проверяет корректность периода экспорта.

        Args:
            value: Значение верхней границы периода ``created_to``.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Значение ``created_to``, если период экспорта корректен.

        Raises:
            ValueError: Если ``created_to`` меньше ``created_from``.
        """

        created_from = info.data.get("created_from")

        if created_from is not None and value is not None and value < created_from:
            raise ValueError("created_to не может быть раньше created_from.")

        return value


class AuditSummaryRead(BaseSchema):
    """Сводка по событиям аудита.

    Используется для возврата агрегированной статистики по событиям аудита:
    общего количества, распределения по результатам, действиям и типам
    ресурсов, а также периода, за который построена сводка.

    Attributes:
        total_count: Общее количество событий аудита в выборке.
        success_count: Количество успешных событий.
        failure_count: Количество событий с ошибкой.
        denied_count: Количество событий с отказом в доступе.
        warning_count: Количество предупреждений.
        by_action: Количество событий по типам действий.
        by_resource_type: Количество событий по типам ресурсов.
        by_result: Количество событий по результатам выполнения.
        period_from: Начало периода, по которому построена сводка.
        period_to: Конец периода, по которому построена сводка.
    """

    total_count: int = Field(
        ...,
        ge=0,
        description="Общее количество событий аудита в выборке.",
    )
    success_count: int = Field(
        default=0,
        ge=0,
        description="Количество успешных событий.",
    )
    failure_count: int = Field(
        default=0,
        ge=0,
        description="Количество событий с ошибкой.",
    )
    denied_count: int = Field(
        default=0,
        ge=0,
        description="Количество событий с отказом в доступе.",
    )
    warning_count: int = Field(
        default=0,
        ge=0,
        description="Количество предупреждений.",
    )
    by_action: dict[AuditAction, int] = Field(
        default_factory=dict,
        description="Количество событий по типам действий.",
    )
    by_resource_type: dict[AuditResourceType, int] = Field(
        default_factory=dict,
        description="Количество событий по типам ресурсов.",
    )
    by_result: dict[AuditResult, int] = Field(
        default_factory=dict,
        description="Количество событий по результатам выполнения.",
    )
    period_from: datetime | None = Field(
        default=None,
        description="Начало периода, по которому построена сводка.",
    )
    period_to: datetime | None = Field(
        default=None,
        description="Конец периода, по которому построена сводка.",
    )
