from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum, StrEnum
from http import HTTPStatus
from typing import Any, ClassVar
from uuid import UUID

from database.exceptions import (
    ConstraintViolationError,
    DatabaseConnectionError,
    DatabaseError,
    DatabaseTimeoutError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidPaginationError,
    InvalidQueryError,
    TransactionError,
    UnitOfWorkError,
)
from schemas.common import ErrorResponse
from security.cookies.exceptions import CookieError
from security.jwt.exceptions import (
    JwtExpiredError,
    JwtInvalidClaimsError,
    JwtInvalidTokenTypeError,
    JwtTokenError,
)
from security.permissions.exceptions import PermissionCheckError, PermissionDeniedError
from storage.exceptions import (
    StorageAuthenticationError,
    StorageBucketNotFoundError,
    StorageChecksumMismatchError,
    StorageConnectionError,
    StorageError,
    StorageHealthCheckError,
    StorageIntegrityError,
    StorageObjectNotFoundError,
    StoragePermissionDeniedError,
    StorageTimeoutError,
)


class ServiceErrorCategory(StrEnum):
    """Категории ошибок сервисного слоя.

    Категория описывает общий тип сбоя и используется обработчиками API,
    логированием и вызывающим кодом сервисов.
    """

    VALIDATION = "validation"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    PERMISSION = "permission"
    QUOTA = "quota"
    STORAGE = "storage"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    PUBLIC_LINK = "public_link"
    BACKGROUND_TASK = "background_task"
    REGISTRATION = "registration"
    INFRASTRUCTURE = "infrastructure"
    INTERNAL = "internal"


class ServiceErrorCode(StrEnum):
    """Стабильные машинно-читаемые коды ошибок сервисного слоя.

    Значения используются клиентами API, логами и обработчиками ошибок для
    программного определения причины сбоя.
    """

    SERVICE_ERROR = "service_error"
    VALIDATION_ERROR = "validation_error"
    CONFLICT_ERROR = "conflict_error"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    AUTHENTICATION_ERROR = "authentication_error"
    AUTHORIZATION_ERROR = "authorization_error"
    QUOTA_EXCEEDED = "quota_exceeded"
    STORAGE_SERVICE_ERROR = "storage_service_error"
    UPLOAD_ERROR = "upload_error"
    DOWNLOAD_ERROR = "download_error"
    PUBLIC_LINK_ERROR = "public_link_error"
    BACKGROUND_TASK_ERROR = "background_task_error"
    REGISTRATION_ERROR = "registration_error"
    DATABASE_ERROR = "database_error"
    STORAGE_ERROR = "storage_error"
    SECURITY_ERROR = "security_error"
    UNEXPECTED_ERROR = "unexpected_error"


# JSON-совместимый словарь с произвольными значениями.
JsonDict = dict[str, Any]


def _copy_details(details: Mapping[str, Any] | None) -> JsonDict:
    """Создаёт поверхностную копию словаря деталей ошибки.

    Args:
        details: Исходные детали ошибки или `None`.

    Returns:
        Новый словарь с деталями ошибки. Если `details` не передан, возвращается
        пустой словарь.
    """

    return dict(details) if details else {}


def _normalize_code(code: str | Enum | None, fallback: str | Enum) -> str:
    """Нормализует код ошибки до непустой строки.

    Args:
        code: Пользовательский код ошибки, enum-значение или `None`.
        fallback: Код ошибки по умолчанию, используемый при отсутствии или
            пустом значении `code`.

    Returns:
        Нормализованный строковый код ошибки.
    """

    value = fallback.value if isinstance(fallback, Enum) else fallback
    if code is None:
        return value

    raw_code = code.value if isinstance(code, Enum) else code
    normalized_code = str(raw_code).strip()
    return normalized_code or value


def _normalize_category(
    category: str | ServiceErrorCategory | None, fallback: ServiceErrorCategory
) -> ServiceErrorCategory:
    """Нормализует категорию ошибки.

    Args:
        category: Пользовательская категория ошибки, enum-значение или `None`.
        fallback: Категория по умолчанию, используемая при некорректном
            значении `category`.

    Returns:
        Экземпляр `ServiceErrorCategory`.
    """

    if category is None:
        return fallback
    if isinstance(category, ServiceErrorCategory):
        return category
    try:
        return ServiceErrorCategory(str(category).strip().lower())
    except ValueError:
        return fallback


def _jsonable(value: Any) -> Any:
    """Преобразует значение в JSON-сериализуемый формат.

    Поддерживает базовые типы, UUID, даты, enum-значения, словари,
    коллекции, Pydantic-модели и dataclass-объекты.

    Args:
        value: Значение для преобразования.

    Returns:
        JSON-сериализуемое представление значения.
    """

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set | frozenset):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    return str(value)


def _exception_payload(exc: BaseException) -> JsonDict:
    """Создаёт JSON-сериализуемое описание исключения.

    Если исключение предоставляет метод `to_dict()`, используется его результат.
    При ошибке сериализации возвращается базовое описание исключения.

    Args:
        exc: Исключение, которое нужно представить в виде словаря.

    Returns:
        Словарь с описанием исключения.
    """

    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        try:
            return _jsonable(to_dict())
        except Exception:
            pass

    return {
        "error": exc.__class__.__name__,
        "message": str(exc),
    }


def _merge_details(details: Mapping[str, Any] | None, **items: Any) -> JsonDict:
    """Объединяет исходные детали ошибки с дополнительными полями.

    Поля со значением `None` пропускаются. Остальные значения приводятся к
    JSON-сериализуемому виду.

    Args:
        details: Исходные детали ошибки.
        **items: Дополнительные поля, которые нужно добавить в детали.

    Returns:
        Новый словарь с объединёнными деталями ошибки.
    """

    merged_details = _copy_details(details)
    for key, value in items.items():
        if value is not None:
            merged_details[key] = _jsonable(value)
    return merged_details


class ServiceError(Exception):
    """Базовое исключение сервисного слоя LocalCloud.

    Сервисные исключения не зависят от FastAPI. API-слой может преобразовывать
    их в HTTP-ответы через `status_code`, `to_dict()` или
    `to_error_response()`.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        code: Стабильный машинно-читаемый код ошибки.
        category: Категория ошибки сервисного слоя.
        status_code: HTTP-статус, соответствующий ошибке.
        service: Имя сервиса, в котором произошла ошибка.
        operation: Название операции, во время которой произошла ошибка.
        details: Дополнительные JSON-сериализуемые детали ошибки.
        cause: Исходное исключение, ставшее причиной сервисной ошибки.
        retryable: Признак того, что операцию можно повторить.
    """

    default_message: ClassVar[str] = "Операция сервисного слоя не удалась."
    default_code: ClassVar[str] = ServiceErrorCode.SERVICE_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.INTERNAL
    default_status_code: ClassVar[int] = HTTPStatus.INTERNAL_SERVER_ERROR
    default_retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | Enum | None = None,
        category: str | ServiceErrorCategory | None = None,
        status_code: int | HTTPStatus | None = None,
        service: str | None = None,
        operation: str | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
        retryable: bool | None = None,
    ) -> None:
        """Инициализирует сервисную ошибку.

        Args:
            message: Человекочитаемое сообщение. Если не передано,
                используется `default_message`.
            code: Машинно-читаемый код ошибки. Если не передан,
                используется `default_code`.
            category: Категория ошибки. Если не передана или некорректна,
                используется `default_category`.
            status_code: HTTP-статус ошибки. Если не передан,
                используется `default_status_code`.
            service: Имя сервиса, в котором произошла ошибка.
            operation: Название операции, во время которой произошла ошибка.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
            retryable: Признак возможности повторить операцию.
        """

        self.message = message or self.default_message
        self.code = _normalize_code(code, self.default_code)
        self.category = _normalize_category(category, self.default_category)
        self.status_code = int(status_code or self.default_status_code)
        self.service = service
        self.operation = operation
        self.details = _merge_details(details, service=service, operation=operation)
        self.cause = cause
        self.retryable = self.default_retryable if retryable is None else retryable

        super().__init__(self.message)

        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        """Возвращает строковое представление ошибки.

        Returns:
            Сообщение об ошибке. Если есть детали, они добавляются к сообщению.
        """

        if not self.details:
            return self.message
        return f"{self.message} Details: {self.details}"

    @property
    def is_client_error(self) -> bool:
        """Проверяет, относится ли ошибка к клиентским HTTP-ошибкам.

        Returns:
            `True`, если HTTP-статус находится в диапазоне 400-499.
        """

        return 400 <= self.status_code < 500

    @property
    def is_server_error(self) -> bool:
        """Проверяет, относится ли ошибка к серверным HTTP-ошибкам.

        Returns:
            `True`, если HTTP-статус равен 500 или выше.
        """

        return self.status_code >= 500

    def to_dict(self, *, include_cause: bool = True) -> JsonDict:
        """Преобразует ошибку в JSON-сериализуемый словарь.

        Args:
            include_cause: Нужно ли включать имя исходного исключения.

        Returns:
            Словарь с кодом, категорией, сообщением, HTTP-статусом,
            признаком повторяемости и дополнительными деталями ошибки.
        """

        payload: JsonDict = {
            "error": self.__class__.__name__,
            "code": self.code,
            "category": self.category.value,
            "message": self.message,
            "status_code": self.status_code,
            "retryable": self.retryable,
        }

        if self.details:
            payload["details"] = _jsonable(self.details)

        if include_cause and self.cause is not None:
            payload["cause"] = self.cause.__class__.__name__

        return payload

    def to_error_response(self, *, request_id: str | None = None) -> ErrorResponse:
        """Преобразует ошибку в объект ответа API.

        Args:
            request_id: Идентификатор запроса, который нужно добавить в ответ.

        Returns:
            Объект `ErrorResponse` для возврата из API-слоя.
        """

        return ErrorResponse(
            error=self.code,
            message=self.message,
            details=_jsonable(self.details) if self.details else None,
            request_id=request_id,
        )


class ValidationServiceError(ServiceError):
    """Ошибка бизнес-валидации входных или промежуточных данных."""

    default_message: ClassVar[str] = "Данные не прошли бизнес-валидацию."
    default_code: ClassVar[str] = ServiceErrorCode.VALIDATION_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.VALIDATION
    default_status_code: ClassVar[int] = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(
        self,
        message: str | None = None,
        *,
        field: str | None = None,
        value: Any | None = None,
        reason: str | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку бизнес-валидации.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            field: Поле, не прошедшее валидацию.
            value: Некорректное значение.
            reason: Причина ошибки валидации.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            details=_merge_details(details, field=field, value=value, reason=reason),
            cause=cause,
        )


class ConflictServiceError(ServiceError):
    """Ошибка конфликта бизнес-состояния или нарушения уникальности."""

    default_message: ClassVar[str] = (
        "Операция конфликтует с текущим состоянием системы."
    )
    default_code: ClassVar[str] = ServiceErrorCode.CONFLICT_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.CONFLICT
    default_status_code: ClassVar[int] = HTTPStatus.CONFLICT

    def __init__(
        self,
        message: str | None = None,
        *,
        entity_name: str | None = None,
        entity_id: Any | None = None,
        field: str | None = None,
        value: Any | None = None,
        reason: str | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку конфликта состояния.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            entity_name: Название сущности, с которой связан конфликт.
            entity_id: Идентификатор сущности.
            field: Поле, вызвавшее конфликт.
            value: Значение, вызвавшее конфликт.
            reason: Причина конфликта.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            details=_merge_details(
                details,
                entity=entity_name,
                entity_id=entity_id,
                field=field,
                value=value,
                reason=reason,
            ),
            cause=cause,
        )


class NotFoundServiceError(ServiceError):
    """Ошибка отсутствия запрошенной бизнес-сущности."""

    default_message: ClassVar[str] = "Запрашиваемая сущность не найдена."
    default_code: ClassVar[str] = ServiceErrorCode.NOT_FOUND.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.NOT_FOUND
    default_status_code: ClassVar[int] = HTTPStatus.NOT_FOUND

    def __init__(
        self,
        message: str | None = None,
        *,
        entity_name: str | None = None,
        entity_id: Any | None = None,
        lookup: Mapping[str, Any] | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку отсутствия сущности.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            entity_name: Название искомой сущности.
            entity_id: Идентификатор искомой сущности.
            lookup: Параметры поиска сущности.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        resolved_message = message
        if resolved_message is None and entity_name is not None:
            resolved_message = f"Сущность '{entity_name}' не найдена."

        super().__init__(
            resolved_message,
            code=code,
            details=_merge_details(
                details, entity=entity_name, entity_id=entity_id, lookup=lookup
            ),
            cause=cause,
        )


class PermissionServiceError(ServiceError):
    """Ошибка проверки прав доступа к узлу или ресурсу."""

    default_message: ClassVar[str] = "Недостаточно прав для выполнения операции."
    default_code: ClassVar[str] = ServiceErrorCode.PERMISSION_DENIED.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.PERMISSION
    default_status_code: ClassVar[int] = HTTPStatus.FORBIDDEN

    def __init__(
        self,
        message: str | None = None,
        *,
        user_id: Any | None = None,
        resource_type: str | None = None,
        resource_id: Any | None = None,
        action: str | Enum | None = None,
        required_permission: str | Enum | None = None,
        reason: str | Enum | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку проверки прав доступа.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            user_id: Идентификатор пользователя.
            resource_type: Тип ресурса.
            resource_id: Идентификатор ресурса.
            action: Запрошенное действие.
            required_permission: Требуемое право доступа.
            reason: Причина отказа.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            details=_merge_details(
                details,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                required_permission=required_permission,
                reason=reason,
            ),
            cause=cause,
        )


class AuthenticationServiceError(ServiceError):
    """Ошибка аутентификации пользователя или проверки сессии."""

    default_message: ClassVar[str] = "Не удалось выполнить аутентификацию."
    default_code: ClassVar[str] = ServiceErrorCode.AUTHENTICATION_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = (
        ServiceErrorCategory.AUTHENTICATION
    )
    default_status_code: ClassVar[int] = HTTPStatus.UNAUTHORIZED

    def __init__(
        self,
        message: str | None = None,
        *,
        user_id: Any | None = None,
        username: str | None = None,
        email: str | None = None,
        session_id: Any | None = None,
        reason: str | Enum | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку аутентификации.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            user_id: Идентификатор пользователя.
            username: Имя пользователя.
            email: Email пользователя.
            session_id: Идентификатор сессии.
            reason: Причина ошибки аутентификации.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            details=_merge_details(
                details,
                user_id=user_id,
                username=username,
                email=email,
                session_id=session_id,
                reason=reason,
            ),
            cause=cause,
        )


class AuthorizationServiceError(ServiceError):
    """Ошибка авторизации аутентифицированного пользователя."""

    default_message: ClassVar[str] = (
        "Пользователь не авторизован для выполнения операции."
    )
    default_code: ClassVar[str] = ServiceErrorCode.AUTHORIZATION_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = (
        ServiceErrorCategory.AUTHORIZATION
    )
    default_status_code: ClassVar[int] = HTTPStatus.FORBIDDEN

    def __init__(
        self,
        message: str | None = None,
        *,
        user_id: Any | None = None,
        role: str | None = None,
        required_role: str | None = None,
        action: str | Enum | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку авторизации.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            user_id: Идентификатор пользователя.
            role: Текущая роль пользователя.
            required_role: Роль, необходимая для выполнения операции.
            action: Запрошенное действие.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            details=_merge_details(
                details,
                user_id=user_id,
                role=role,
                required_role=required_role,
                action=action,
            ),
            cause=cause,
        )


class QuotaExceededServiceError(ServiceError):
    """Ошибка превышения пользовательской квоты или лимита размера файла."""

    default_message: ClassVar[str] = "Превышена доступная квота пользователя."
    default_code: ClassVar[str] = ServiceErrorCode.QUOTA_EXCEEDED.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.QUOTA
    default_status_code: ClassVar[int] = 413

    def __init__(
        self,
        message: str | None = None,
        *,
        user_id: Any | None = None,
        resource_type: str | None = None,
        requested: int | None = None,
        used: int | None = None,
        limit: int | None = None,
        available: int | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку превышения квоты.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            user_id: Идентификатор пользователя.
            resource_type: Тип ресурса, для которого превышена квота.
            requested: Запрошенный объём ресурса.
            used: Уже использованный объём ресурса.
            limit: Максимально допустимый объём ресурса.
            available: Доступный остаток ресурса.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            details=_merge_details(
                details,
                user_id=user_id,
                resource_type=resource_type,
                requested=requested,
                used=used,
                limit=limit,
                available=available,
            ),
            cause=cause,
        )


class StorageServiceError(ServiceError):
    """Ошибка бизнес-операции, вызванная сбоем файлового хранилища."""

    default_message: ClassVar[str] = "Операция с файловым хранилищем не удалась."
    default_code: ClassVar[str] = ServiceErrorCode.STORAGE_SERVICE_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.STORAGE
    default_status_code: ClassVar[int] = HTTPStatus.BAD_GATEWAY
    default_retryable: ClassVar[bool] = True

    def __init__(
        self,
        message: str | None = None,
        *,
        bucket: str | None = None,
        object_key: str | None = None,
        operation: str | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
        retryable: bool | None = None,
    ) -> None:
        """Инициализирует ошибку файлового хранилища.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            bucket: Имя бакета.
            object_key: Ключ объекта в хранилище.
            operation: Операция, во время которой произошла ошибка.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
            retryable: Признак возможности повторить операцию.
        """

        super().__init__(
            message,
            code=code,
            operation=operation,
            details=_merge_details(details, bucket=bucket, object_key=object_key),
            cause=cause,
            retryable=retryable,
        )


class UploadServiceError(ServiceError):
    """Ошибка сценария загрузки файла."""

    default_message: ClassVar[str] = "Операция загрузки файла не удалась."
    default_code: ClassVar[str] = ServiceErrorCode.UPLOAD_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.UPLOAD
    default_status_code: ClassVar[int] = HTTPStatus.CONFLICT

    def __init__(
        self,
        message: str | None = None,
        *,
        upload_session_id: Any | None = None,
        file_id: Any | None = None,
        user_id: Any | None = None,
        part_number: int | None = None,
        operation: str | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку загрузки файла.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            upload_session_id: Идентификатор сессии загрузки.
            file_id: Идентификатор файла.
            user_id: Идентификатор пользователя.
            part_number: Номер части multipart-загрузки.
            operation: Операция, во время которой произошла ошибка.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            operation=operation,
            details=_merge_details(
                details,
                upload_session_id=upload_session_id,
                file_id=file_id,
                user_id=user_id,
                part_number=part_number,
            ),
            cause=cause,
        )


class DownloadServiceError(ServiceError):
    """Ошибка сценария скачивания файла или архива."""

    default_message: ClassVar[str] = "Операция скачивания файла не удалась."
    default_code: ClassVar[str] = ServiceErrorCode.DOWNLOAD_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.DOWNLOAD
    default_status_code: ClassVar[int] = HTTPStatus.BAD_GATEWAY

    def __init__(
        self,
        message: str | None = None,
        *,
        file_id: Any | None = None,
        node_id: Any | None = None,
        version_id: Any | None = None,
        public_link_id: Any | None = None,
        user_id: Any | None = None,
        operation: str | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку скачивания файла или архива.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            file_id: Идентификатор файла.
            node_id: Идентификатор узла.
            version_id: Идентификатор версии файла.
            public_link_id: Идентификатор публичной ссылки.
            user_id: Идентификатор пользователя.
            operation: Операция, во время которой произошла ошибка.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            operation=operation,
            details=_merge_details(
                details,
                file_id=file_id,
                node_id=node_id,
                version_id=version_id,
                public_link_id=public_link_id,
                user_id=user_id,
            ),
            cause=cause,
        )


class PublicLinkServiceError(ServiceError):
    """Ошибка бизнес-сценария работы с публичной ссылкой."""

    default_message: ClassVar[str] = "Операция с публичной ссылкой не удалась."
    default_code: ClassVar[str] = ServiceErrorCode.PUBLIC_LINK_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.PUBLIC_LINK
    default_status_code: ClassVar[int] = HTTPStatus.BAD_REQUEST

    def __init__(
        self,
        message: str | None = None,
        *,
        public_link_id: Any | None = None,
        token: str | None = None,
        node_id: Any | None = None,
        reason: str | Enum | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку публичной ссылки.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            public_link_id: Идентификатор публичной ссылки.
            token: Токен публичной ссылки.
            node_id: Идентификатор узла, связанного с публичной ссылкой.
            reason: Причина ошибки.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            details=_merge_details(
                details,
                public_link_id=public_link_id,
                token=token,
                node_id=node_id,
                reason=reason,
            ),
            cause=cause,
        )


class BackgroundTaskServiceError(ServiceError):
    """Ошибка управления фоновой задачей."""

    default_message: ClassVar[str] = "Операция с фоновой задачей не удалась."
    default_code: ClassVar[str] = ServiceErrorCode.BACKGROUND_TASK_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = (
        ServiceErrorCategory.BACKGROUND_TASK
    )
    default_status_code: ClassVar[int] = HTTPStatus.CONFLICT

    def __init__(
        self,
        message: str | None = None,
        *,
        task_id: Any | None = None,
        task_type: str | None = None,
        status: str | Enum | None = None,
        worker_id: str | None = None,
        operation: str | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку фоновой задачи.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            task_id: Идентификатор фоновой задачи.
            task_type: Тип фоновой задачи.
            status: Статус фоновой задачи.
            worker_id: Идентификатор обработчика задачи.
            operation: Операция, во время которой произошла ошибка.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            operation=operation,
            details=_merge_details(
                details,
                task_id=task_id,
                task_type=task_type,
                status=status,
                worker_id=worker_id,
            ),
            cause=cause,
        )


class RegistrationServiceError(ServiceError):
    """Ошибка сценария регистрации пользователя."""

    default_message: ClassVar[str] = "Операция регистрации не удалась."
    default_code: ClassVar[str] = ServiceErrorCode.REGISTRATION_ERROR.value
    default_category: ClassVar[ServiceErrorCategory] = ServiceErrorCategory.REGISTRATION
    default_status_code: ClassVar[int] = HTTPStatus.CONFLICT

    def __init__(
        self,
        message: str | None = None,
        *,
        request_id: Any | None = None,
        user_id: Any | None = None,
        email: str | None = None,
        username: str | None = None,
        status: str | Enum | None = None,
        reason: str | Enum | None = None,
        code: str | Enum | None = None,
        details: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку регистрации пользователя.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            request_id: Идентификатор запроса регистрации.
            user_id: Идентификатор пользователя.
            email: Email пользователя.
            username: Имя пользователя.
            status: Статус регистрационного сценария.
            reason: Причина ошибки регистрации.
            code: Машинно-читаемый код ошибки.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение.
        """

        super().__init__(
            message,
            code=code,
            details=_merge_details(
                details,
                request_id=request_id,
                user_id=user_id,
                email=email,
                username=username,
                status=status,
                reason=reason,
            ),
            cause=cause,
        )


def service_error_from_database(
    exc: DatabaseError,
    *,
    operation: str | None = None,
    message: str | None = None,
    service: str | None = None,
) -> ServiceError:
    """Преобразует ошибку базы данных в сервисную ошибку.

    Args:
        exc: Исключение слоя базы данных.
        operation: Операция, во время которой произошла ошибка.
        message: Пользовательское сообщение для итоговой сервисной ошибки.
        service: Имя сервиса, в котором произошла ошибка.

    Returns:
        Экземпляр `ServiceError` или одного из его подклассов.
    """

    details = _merge_details(
        {"database_error": _exception_payload(exc)},
        service=service,
        operation=operation,
    )

    if isinstance(exc, EntityNotFoundError):
        return NotFoundServiceError(
            message,
            entity_name=exc.details.get("entity"),
            entity_id=exc.details.get("entity_id"),
            lookup=exc.details.get("lookup"),
            details=details,
            cause=exc,
        )

    if isinstance(exc, DuplicateEntityError | ConstraintViolationError):
        return ConflictServiceError(
            message,
            entity_name=exc.details.get("entity"),
            field=exc.details.get("field") or exc.details.get("column_name"),
            value=exc.details.get("value"),
            reason="database_constraint",
            details=details,
            cause=exc,
        )

    if isinstance(exc, InvalidPaginationError | InvalidQueryError):
        return ValidationServiceError(
            message,
            reason="invalid_query",
            details=details,
            cause=exc,
        )

    retryable = isinstance(
        exc,
        DatabaseConnectionError
        | DatabaseTimeoutError
        | TransactionError
        | UnitOfWorkError,
    )
    code = ServiceErrorCode.DATABASE_ERROR
    status_code = (
        HTTPStatus.SERVICE_UNAVAILABLE
        if retryable
        else HTTPStatus.INTERNAL_SERVER_ERROR
    )

    return ServiceError(
        message or "Операция с базой данных не удалась.",
        code=code,
        category=ServiceErrorCategory.INFRASTRUCTURE,
        status_code=status_code,
        service=service,
        operation=operation,
        details=details,
        cause=exc,
        retryable=retryable,
    )


def service_error_from_storage(
    exc: StorageError,
    *,
    operation: str | None = None,
    message: str | None = None,
    service: str | None = None,
) -> ServiceError:
    """Преобразует ошибку файлового хранилища в сервисную ошибку.

    Args:
        exc: Исключение слоя файлового хранилища.
        operation: Операция, во время которой произошла ошибка.
        message: Пользовательское сообщение для итоговой сервисной ошибки.
        service: Имя сервиса, в котором произошла ошибка.

    Returns:
        Экземпляр `ServiceError` или одного из его подклассов.
    """

    details = _merge_details(
        {"storage_error": _exception_payload(exc)},
        service=service,
        operation=operation,
    )

    if isinstance(exc, StorageObjectNotFoundError | StorageBucketNotFoundError):
        return NotFoundServiceError(
            message or "Объект файлового хранилища не найден.",
            entity_name="StorageObject",
            lookup={
                "bucket": exc.details.get("bucket"),
                "object_key": exc.details.get("object_key"),
            },
            details=details,
            cause=exc,
        )

    if isinstance(exc, StoragePermissionDeniedError | StorageAuthenticationError):
        return StorageServiceError(
            message or "Хранилище отклонило операцию доступа.",
            operation=operation,
            code=ServiceErrorCode.STORAGE_ERROR,
            details=details,
            cause=exc,
            retryable=False,
        )

    retryable = isinstance(
        exc, StorageConnectionError | StorageTimeoutError | StorageHealthCheckError
    )
    if isinstance(exc, StorageIntegrityError | StorageChecksumMismatchError):
        retryable = False

    return StorageServiceError(
        message,
        bucket=exc.details.get("bucket"),
        object_key=exc.details.get("object_key"),
        operation=operation,
        code=ServiceErrorCode.STORAGE_ERROR,
        details=_merge_details(details, service=service),
        cause=exc,
        retryable=retryable,
    )


def service_error_from_security(
    exc: BaseException,
    *,
    operation: str | None = None,
    message: str | None = None,
    service: str | None = None,
) -> ServiceError:
    """Преобразует ошибку безопасности в сервисную ошибку.

    Args:
        exc: Исключение слоя безопасности, JWT, cookie или проверки прав.
        operation: Операция, во время которой произошла ошибка.
        message: Пользовательское сообщение для итоговой сервисной ошибки.
        service: Имя сервиса, в котором произошла ошибка.

    Returns:
        Экземпляр `ServiceError` или одного из его подклассов.
    """

    details = _merge_details(
        {"security_error": _exception_payload(exc)},
        service=service,
        operation=operation,
    )

    if isinstance(exc, PermissionDeniedError | PermissionCheckError):
        return PermissionServiceError(
            message,
            action=getattr(exc, "details", {}).get("action"),
            reason=getattr(exc, "details", {}).get("reason"),
            user_id=getattr(exc, "details", {}).get("user_id"),
            resource_id=getattr(exc, "details", {}).get("node_id"),
            resource_type="node",
            details=details,
            cause=exc,
        )

    if isinstance(exc, JwtExpiredError):
        return AuthenticationServiceError(
            message or "Срок действия токена истёк.",
            reason="expired_token",
            code=getattr(exc, "code", ServiceErrorCode.AUTHENTICATION_ERROR),
            details=details,
            cause=exc,
        )

    if isinstance(
        exc,
        JwtInvalidTokenTypeError | JwtInvalidClaimsError | JwtTokenError | CookieError,
    ):
        return AuthenticationServiceError(
            message,
            reason=getattr(getattr(exc, "code", None), "value", None)
            or exc.__class__.__name__,
            details=details,
            cause=exc,
        )

    return ServiceError(
        message or "Ошибка безопасности сервисного слоя.",
        code=ServiceErrorCode.SECURITY_ERROR,
        category=ServiceErrorCategory.AUTHENTICATION,
        status_code=HTTPStatus.UNAUTHORIZED,
        service=service,
        operation=operation,
        details=details,
        cause=exc,
    )


def service_error_from_exception(
    exc: BaseException,
    *,
    operation: str | None = None,
    message: str | None = None,
    service: str | None = None,
) -> ServiceError:
    """Преобразует произвольное исключение в сервисную ошибку.

    Если исключение уже является `ServiceError`, оно возвращается без изменений.
    Для известных типов ошибок используется специализированное преобразование.

    Args:
        exc: Исходное исключение.
        operation: Операция, во время которой произошла ошибка.
        message: Пользовательское сообщение для итоговой сервисной ошибки.
        service: Имя сервиса, в котором произошла ошибка.

    Returns:
        Экземпляр `ServiceError` или одного из его подклассов.
    """

    if isinstance(exc, ServiceError):
        return exc
    if isinstance(exc, DatabaseError):
        return service_error_from_database(
            exc, operation=operation, message=message, service=service
        )
    if isinstance(exc, StorageError):
        return service_error_from_storage(
            exc, operation=operation, message=message, service=service
        )
    if isinstance(exc, PermissionCheckError | JwtTokenError | CookieError):
        return service_error_from_security(
            exc, operation=operation, message=message, service=service
        )

    return ServiceError(
        message or "Непредвиденная ошибка сервисного слоя.",
        code=ServiceErrorCode.UNEXPECTED_ERROR,
        category=ServiceErrorCategory.INTERNAL,
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        service=service,
        operation=operation,
        details={
            "error_type": exc.__class__.__name__,
            "reason": str(exc),
        },
        cause=exc,
    )


def get_service_error_status_code(exc: ServiceError) -> int:
    """Возвращает HTTP-статус сервисной ошибки.

    Args:
        exc: Сервисная ошибка.

    Returns:
        HTTP-статус, связанный с ошибкой.
    """

    return exc.status_code


def service_error_to_response(
    exc: ServiceError, *, request_id: str | None = None
) -> ErrorResponse:
    """Преобразует сервисную ошибку в объект ответа API.

    Args:
        exc: Сервисная ошибка.
        request_id: Идентификатор запроса, который нужно добавить в ответ.

    Returns:
        Объект `ErrorResponse`.
    """

    return exc.to_error_response(request_id=request_id)
