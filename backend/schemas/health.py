from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from database.models.enums import HealthStatus
from schemas.common import BaseSchema


def normalize_health_status(value: HealthStatus | str) -> HealthStatus:
    """Нормализует внутренние health-статусы к публичному HealthStatus.

    Поддерживает как уже готовые значения ``HealthStatus``, так и строковые
    внутренние статусы, которые используются в разных сервисных слоях.

    Args:
        value: Исходный статус работоспособности.

    Returns:
        Нормализованный публичный статус ``HealthStatus``.

    Raises:
        ValueError: Если переданный статус не поддерживается.
    """

    if isinstance(value, HealthStatus):
        return value

    normalized_value = str(value).strip().lower()

    if normalized_value in {"ok", "healthy", "success", "available"}:
        return HealthStatus.OK

    if normalized_value in {"degraded", "warning", "slow"}:
        return HealthStatus.DEGRADED

    if normalized_value in {"unavailable", "unhealthy", "failed", "failure", "error"}:
        return HealthStatus.UNAVAILABLE

    raise ValueError(
        "Недопустимый health status. Ожидается ok, degraded, unavailable "
        "или совместимый внутренний статус."
    )


class ComponentHealthRead(BaseSchema):
    """Универсальное состояние отдельного компонента системы.

    Используется для описания результата проверки любого инфраструктурного или
    прикладного компонента: приложения, базы данных, хранилища, очереди,
    внешнего сервиса и других зависимостей.

    Attributes:
        component: Название проверяемого компонента.
        status: Публичный статус работоспособности компонента.
        connection: Доступно ли подключение к компоненту, если это применимо.
        latency_ms: Задержка проверки компонента в миллисекундах.
        latency_threshold_ms: Порог допустимой задержки в миллисекундах.
        error: Машиночитаемый тип ошибки, если проверка завершилась
            неуспешно.
        message: Человекочитаемое сообщение о состоянии компонента.
        details: Дополнительные структурированные детали проверки.
        checked_at: Дата и время проверки компонента.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    component: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Название проверяемого компонента.",
        examples=["application", "database", "storage"],
    )
    status: HealthStatus = Field(
        ...,
        description="Публичный статус работоспособности компонента.",
    )
    connection: bool | None = Field(
        default=None,
        description="Доступно ли подключение к компоненту, если это применимо.",
    )
    latency_ms: float | None = Field(
        default=None,
        ge=0,
        description="Задержка проверки компонента в миллисекундах.",
    )
    latency_threshold_ms: float | None = Field(
        default=None,
        gt=0,
        description="Порог допустимой задержки в миллисекундах.",
    )
    error: str | None = Field(
        default=None,
        max_length=255,
        description="Машиночитаемый тип ошибки, если проверка завершилась неуспешно.",
    )
    message: str | None = Field(
        default=None,
        description="Человекочитаемое сообщение о состоянии компонента.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Дополнительные структурированные детали проверки.",
    )
    checked_at: datetime | None = Field(
        default=None,
        description="Дата и время проверки компонента.",
    )

    @field_validator("component", "error", "message")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Нормализует текстовые поля состояния компонента.

        Args:
            value: Исходное текстовое значение.

        Returns:
            Строка без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: HealthStatus | str) -> HealthStatus:
        """Нормализует статус компонента.

        Args:
            value: Исходный статус компонента.

        Returns:
            Нормализованный публичный статус ``HealthStatus``.

        Raises:
            ValueError: Если статус не поддерживается.
        """

        return normalize_health_status(value)


class DatabaseHealthRead(ComponentHealthRead):
    """Состояние подключения к PostgreSQL.

    Расширяет универсальное состояние компонента значениями по умолчанию,
    специфичными для проверки базы данных.

    Attributes:
        component: Название проверяемого компонента.
        connection: Доступно ли подключение к базе данных.
    """

    component: str = Field(
        default="database",
        description="Название проверяемого компонента.",
    )
    connection: bool | None = Field(
        default=None,
        description="Доступно ли подключение к базе данных.",
    )


class StorageHealthRead(BaseSchema):
    """Состояние подключения к объектному хранилищу.

    Используется для публичного представления результата проверки storage:
    подключения, доступа к bucket, операций чтения/записи, задержки и
    дополнительных диагностических данных.

    Attributes:
        component: Название проверяемого компонента.
        status: Публичный статус работоспособности объектного хранилища.
        checked_at: Дата и время проверки объектного хранилища.
        connection_ok: Доступно ли подключение к объектному хранилищу.
        bucket_access_ok: Доступен ли проверяемый bucket.
        read_write_ok: Успешна ли проверка чтения/записи.
        latency_ms: Задержка проверки объектного хранилища в миллисекундах.
        latency_threshold_ms: Порог допустимой задержки объектного хранилища в
            миллисекундах.
        details: Дополнительные структурированные детали проверки.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    component: str = Field(
        default="storage",
        min_length=1,
        max_length=128,
        description="Название проверяемого компонента.",
    )
    status: HealthStatus = Field(
        ...,
        description="Публичный статус работоспособности объектного хранилища.",
    )
    checked_at: datetime | None = Field(
        default=None,
        description="Дата и время проверки объектного хранилища.",
    )
    connection_ok: bool = Field(
        ...,
        description="Доступно ли подключение к объектному хранилищу.",
    )
    bucket_access_ok: bool | None = Field(
        default=None,
        description="Доступен ли проверяемый bucket.",
    )
    read_write_ok: bool | None = Field(
        default=None,
        description="Успешна ли проверка чтения/записи.",
    )
    latency_ms: float | None = Field(
        default=None,
        ge=0,
        description="Задержка проверки объектного хранилища в миллисекундах.",
    )
    latency_threshold_ms: float | None = Field(
        default=None,
        gt=0,
        description="Порог допустимой задержки объектного хранилища в миллисекундах.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Дополнительные структурированные детали проверки.",
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: HealthStatus | str) -> HealthStatus:
        """Нормализует статус объектного хранилища.

        Args:
            value: Исходный статус объектного хранилища.

        Returns:
            Нормализованный публичный статус ``HealthStatus``.

        Raises:
            ValueError: Если статус не поддерживается.
        """

        return normalize_health_status(value)

    @model_validator(mode="before")
    @classmethod
    def support_storage_health_status_shape(cls, data: Any) -> Any:
        """Поддерживает объект ``storage.types.StorageHealthStatus``.

        В storage DTO статус называется ``state``, а в публичной API-схеме —
        ``status``. Валидатор преобразует объект или словарь внутреннего
        формата к форме, ожидаемой публичной схемой.

        Args:
            data: Исходные данные для построения схемы. Может быть словарём,
                объектом ``StorageHealthStatus`` или другим совместимым
                объектом.

        Returns:
            Исходные данные без изменений либо словарь, приведённый к публичной
            форме ``StorageHealthRead``.
        """

        if not isinstance(data, dict):
            state = getattr(data, "state", None)
            if state is not None:
                return {
                    "component": "storage",
                    "status": state,
                    "checked_at": getattr(data, "checked_at", None),
                    "connection_ok": getattr(data, "connection_ok", False),
                    "bucket_access_ok": getattr(data, "bucket_access_ok", None),
                    "read_write_ok": getattr(data, "read_write_ok", None),
                    "latency_ms": getattr(data, "latency_ms", None),
                    "latency_threshold_ms": getattr(data, "latency_threshold_ms", None),
                    "details": getattr(data, "details", None),
                }

            return data

        if "status" not in data and "state" in data:
            normalized_data = dict(data)
            normalized_data["status"] = normalized_data.pop("state")
            normalized_data.setdefault("component", "storage")
            return normalized_data

        return data


class ApplicationHealthRead(BaseSchema):
    """Состояние самого backend-приложения.

    Используется для описания работоспособности приложения без проверки
    внешних зависимостей или вместе с ними в составе общего health-check.

    Attributes:
        component: Название проверяемого компонента.
        status: Публичный статус работоспособности приложения.
        app_name: Название приложения.
        app_version: Версия приложения.
        debug: Запущено ли приложение в debug-режиме.
        uptime_seconds: Время работы приложения в секундах, если известно.
        checked_at: Дата и время проверки приложения.
        details: Дополнительные сведения о состоянии приложения.
    """

    component: str = Field(
        default="application",
        description="Название проверяемого компонента.",
    )
    status: HealthStatus = Field(
        default=HealthStatus.OK,
        description="Публичный статус работоспособности приложения.",
    )
    app_name: str = Field(
        ...,
        min_length=1,
        description="Название приложения.",
        examples=["LocalCloud"],
    )
    app_version: str = Field(
        ...,
        min_length=1,
        description="Версия приложения.",
        examples=["0.1.0"],
    )
    debug: bool | None = Field(
        default=None,
        description="Запущено ли приложение в debug-режиме.",
    )
    uptime_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Время работы приложения в секундах, если известно.",
    )
    checked_at: datetime = Field(
        ...,
        description="Дата и время проверки приложения.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Дополнительные сведения о состоянии приложения.",
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: HealthStatus | str) -> HealthStatus:
        """Нормализует статус приложения.

        Args:
            value: Исходный статус приложения.

        Returns:
            Нормализованный публичный статус ``HealthStatus``.

        Raises:
            ValueError: Если статус не поддерживается.
        """

        return normalize_health_status(value)


class HealthCheckResponse(BaseSchema):
    """Полный ответ health-check endpoint.

    Возвращает итоговый статус системы, сведения о приложении и основных
    зависимостях, а также список дополнительных компонентов, если они
    участвовали в проверке.

    Attributes:
        app_name: Название приложения.
        app_version: Версия приложения.
        status: Итоговый статус работоспособности системы.
        checked_at: Дата и время выполнения общей проверки.
        application: Состояние backend-приложения.
        database: Состояние подключения к базе данных.
        storage: Состояние объектного хранилища.
        components: Дополнительные компоненты, участвующие в health-check.
        details: Дополнительные сведения о результате проверки.
    """

    app_name: str = Field(
        ...,
        min_length=1,
        description="Название приложения.",
        examples=["LocalCloud"],
    )
    app_version: str = Field(
        ...,
        min_length=1,
        description="Версия приложения.",
        examples=["0.1.0"],
    )
    status: HealthStatus = Field(
        ...,
        description="Итоговый статус работоспособности системы.",
    )
    checked_at: datetime = Field(
        ...,
        description="Дата и время выполнения общей проверки.",
    )
    application: ApplicationHealthRead | None = Field(
        default=None,
        description="Состояние backend-приложения.",
    )
    database: DatabaseHealthRead | None = Field(
        default=None,
        description="Состояние подключения к базе данных.",
    )
    storage: StorageHealthRead | None = Field(
        default=None,
        description="Состояние объектного хранилища.",
    )
    components: list[ComponentHealthRead] = Field(
        default_factory=list,
        description="Дополнительные компоненты, участвующие в health-check.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Дополнительные сведения о результате проверки.",
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: HealthStatus | str) -> HealthStatus:
        """Нормализует итоговый health-статус системы.

        Args:
            value: Исходный итоговый статус.

        Returns:
            Нормализованный публичный статус ``HealthStatus``.

        Raises:
            ValueError: Если статус не поддерживается.
        """

        return normalize_health_status(value)


class ReadinessResponse(BaseSchema):
    """Ответ проверки готовности приложения принимать пользовательские запросы.

    Используется readiness endpoint-ом для отображения того, может ли
    приложение обслуживать пользовательский трафик с учётом состояния ключевых
    зависимостей.

    Attributes:
        app_name: Название приложения.
        app_version: Версия приложения.
        status: Статус готовности приложения.
        ready: Готово ли приложение принимать пользовательские запросы.
        checked_at: Дата и время проверки готовности.
        database: Состояние базы данных, если проверка выполнялась.
        storage: Состояние объектного хранилища, если проверка выполнялась.
        details: Дополнительные сведения о готовности приложения.
    """

    app_name: str = Field(
        ...,
        min_length=1,
        description="Название приложения.",
        examples=["LocalCloud"],
    )
    app_version: str = Field(
        ...,
        min_length=1,
        description="Версия приложения.",
        examples=["0.1.0"],
    )
    status: HealthStatus = Field(
        ...,
        description="Статус готовности приложения.",
    )
    ready: bool = Field(
        ...,
        description="Готово ли приложение принимать пользовательские запросы.",
    )
    checked_at: datetime = Field(
        ...,
        description="Дата и время проверки готовности.",
    )
    database: DatabaseHealthRead | None = Field(
        default=None,
        description="Состояние базы данных, если проверка выполнялась.",
    )
    storage: StorageHealthRead | None = Field(
        default=None,
        description="Состояние объектного хранилища, если проверка выполнялась.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Дополнительные сведения о готовности приложения.",
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: HealthStatus | str) -> HealthStatus:
        """Нормализует статус готовности приложения.

        Args:
            value: Исходный статус готовности.

        Returns:
            Нормализованный публичный статус ``HealthStatus``.

        Raises:
            ValueError: Если статус не поддерживается.
        """

        return normalize_health_status(value)


class LivenessResponse(BaseSchema):
    """Ответ проверки жизнеспособности backend-процесса.

    Используется liveness endpoint-ом для отображения того, запущен ли
    backend-процесс и способен ли он отвечать на базовые служебные запросы.

    Attributes:
        app_name: Название приложения.
        app_version: Версия приложения.
        status: Статус жизнеспособности приложения.
        alive: Работает ли backend-процесс.
        checked_at: Дата и время проверки жизнеспособности.
        uptime_seconds: Время работы приложения в секундах, если известно.
        details: Дополнительные сведения о жизнеспособности приложения.
    """

    app_name: str = Field(
        ...,
        min_length=1,
        description="Название приложения.",
        examples=["LocalCloud"],
    )
    app_version: str = Field(
        ...,
        min_length=1,
        description="Версия приложения.",
        examples=["0.1.0"],
    )
    status: HealthStatus = Field(
        ...,
        description="Статус жизнеспособности приложения.",
    )
    alive: bool = Field(
        ...,
        description="Работает ли backend-процесс.",
    )
    checked_at: datetime = Field(
        ...,
        description="Дата и время проверки жизнеспособности.",
    )
    uptime_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Время работы приложения в секундах, если известно.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Дополнительные сведения о жизнеспособности приложения.",
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: HealthStatus | str) -> HealthStatus:
        """Нормализует статус жизнеспособности приложения.

        Args:
            value: Исходный статус жизнеспособности.

        Returns:
            Нормализованный публичный статус ``HealthStatus``.

        Raises:
            ValueError: Если статус не поддерживается.
        """

        return normalize_health_status(value)
