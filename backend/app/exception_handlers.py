from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import DatabaseConnectionError, DatabaseError, DatabaseTimeoutError
from schemas.common import ErrorResponse, ValidationErrorItem, ValidationErrorResponse
from security import (
    CookieError,
    JwtExpiredError,
    JwtInvalidClaimsError,
    JwtInvalidTokenTypeError,
    JwtTokenError,
    PermissionCheckError,
    PermissionDeniedError,
)
from services.exceptions import ServiceError
from storage import (
    StorageConnectionError,
    StorageError,
    StorageHealthCheckError,
    StorageTimeoutError,
)


def register_exception_handlers(app: FastAPI) -> None:
    """Регистрирует единые обработчики исключений FastAPI.

    Подключает к приложению обработчики для сервисных ошибок, ошибок базы
    данных, объектного хранилища, cookie- и JWT-аутентификации, ошибок проверки
    прав доступа, ошибок валидации, стандартных HTTP-исключений и
    непредвиденных исключений.

    Args:
        app: Экземпляр FastAPI-приложения, в котором регистрируются
            обработчики исключений.

    Returns:
        None.
    """

    app.add_exception_handler(ServiceError, cast(Any, service_error_handler))
    app.add_exception_handler(DatabaseError, cast(Any, database_error_handler))
    app.add_exception_handler(StorageError, cast(Any, storage_error_handler))
    app.add_exception_handler(CookieError, cast(Any, cookie_error_handler))
    app.add_exception_handler(JwtTokenError, cast(Any, jwt_error_handler))
    app.add_exception_handler(
        PermissionDeniedError,
        cast(Any, permission_denied_handler),
    )
    app.add_exception_handler(
        PermissionCheckError,
        cast(Any, permission_check_handler),
    )
    app.add_exception_handler(
        RequestValidationError,
        cast(Any, request_validation_error_handler),
    )
    app.add_exception_handler(
        ValidationError,
        cast(Any, pydantic_validation_error_handler),
    )
    app.add_exception_handler(StarletteHTTPException, cast(Any, http_exception_handler))
    app.add_exception_handler(Exception, cast(Any, unexpected_exception_handler))


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """Возвращает сервисную ошибку в стандартизированном формате.

    Преобразует исключение сервисного слоя в модель ответа об ошибке и
    возвращает JSON-ответ со статусом, заданным самим исключением.

    Args:
        request: Текущий HTTP-запрос.
        exc: Исключение сервисного слоя.

    Returns:
        JSON-ответ с описанием сервисной ошибки.
    """

    payload = exc.to_error_response(request_id=_get_request_id(request))
    return _json_response(payload.model_dump(mode="json"), status_code=exc.status_code)


async def database_error_handler(request: Request, exc: DatabaseError) -> JSONResponse:
    """Возвращает ошибку базы данных.

    Формирует стандартизированный ответ для ошибок базы данных. Ошибки
    подключения и таймаута возвращаются как временная недоступность сервиса,
    остальные ошибки базы данных возвращаются как внутренняя ошибка сервера.

    Args:
        request: Текущий HTTP-запрос.
        exc: Исключение базы данных.

    Returns:
        JSON-ответ с описанием ошибки базы данных.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    if not isinstance(exc, DatabaseConnectionError | DatabaseTimeoutError):
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    payload = ErrorResponse(
        error=exc.__class__.__name__,
        message=exc.message,
        details=exc.details or None,
        request_id=_get_request_id(request),
    )
    return _json_response(payload.model_dump(mode="json"), status_code=status_code)


async def storage_error_handler(request: Request, exc: StorageError) -> JSONResponse:
    """Возвращает ошибку объектного хранилища.

    Формирует стандартизированный ответ для ошибок хранилища. Ошибки
    подключения, таймаута и health-check возвращаются как временная
    недоступность сервиса, остальные ошибки хранилища возвращаются как
    внутренняя ошибка сервера.

    Args:
        request: Текущий HTTP-запрос.
        exc: Исключение объектного хранилища.

    Returns:
        JSON-ответ с описанием ошибки хранилища.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    if not isinstance(
        exc, StorageConnectionError | StorageTimeoutError | StorageHealthCheckError
    ):
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    payload = ErrorResponse(
        error=exc.__class__.__name__,
        message=exc.message,
        details=exc.details or None,
        request_id=_get_request_id(request),
    )
    return _json_response(payload.model_dump(mode="json"), status_code=status_code)


async def cookie_error_handler(request: Request, exc: CookieError) -> JSONResponse:
    """Возвращает ошибку cookie-аутентификации.

    Преобразует ошибку работы с cookie в стандартизированный ответ API
    со статусом `401 Unauthorized`.

    Args:
        request: Текущий HTTP-запрос.
        exc: Исключение cookie-аутентификации.

    Returns:
        JSON-ответ с описанием ошибки cookie-аутентификации.
    """

    payload = ErrorResponse(
        error=exc.__class__.__name__,
        message=exc.message,
        details=exc.details or None,
        request_id=_get_request_id(request),
    )
    return _json_response(
        payload.model_dump(mode="json"), status_code=status.HTTP_401_UNAUTHORIZED
    )


async def jwt_error_handler(request: Request, exc: JwtTokenError) -> JSONResponse:
    """Возвращает ошибку JWT-аутентификации.

    Преобразует ошибки JWT-токена, включая истечение срока действия,
    некорректные claims и неверный тип токена, в стандартизированный ответ API
    со статусом `401 Unauthorized`.

    Args:
        request: Текущий HTTP-запрос.
        exc: Исключение JWT-аутентификации.

    Returns:
        JSON-ответ с описанием ошибки JWT-аутентификации.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    if isinstance(
        exc, JwtInvalidClaimsError | JwtInvalidTokenTypeError | JwtExpiredError
    ):
        status_code = status.HTTP_401_UNAUTHORIZED

    payload = ErrorResponse(
        error=exc.__class__.__name__,
        message=exc.message,
        details=exc.details or None,
        request_id=_get_request_id(request),
    )
    return _json_response(payload.model_dump(mode="json"), status_code=status_code)


async def permission_denied_handler(
    request: Request,
    exc: PermissionDeniedError,
) -> JSONResponse:
    """Возвращает ошибку отказа в доступе.

    Формирует стандартизированный ответ для случая, когда пользователю
    запрещено выполнение операции.

    Args:
        request: Текущий HTTP-запрос.
        exc: Исключение отказа в доступе.

    Returns:
        JSON-ответ с описанием ошибки доступа.
    """

    payload = ErrorResponse(
        error=exc.__class__.__name__,
        message=exc.message,
        details=exc.details or None,
        request_id=_get_request_id(request),
    )
    return _json_response(
        payload.model_dump(mode="json"), status_code=status.HTTP_403_FORBIDDEN
    )


async def permission_check_handler(
    request: Request,
    exc: PermissionCheckError,
) -> JSONResponse:
    """Возвращает ошибку проверки прав доступа.

    Формирует стандартизированный ответ для ошибок, возникающих во время
    проверки прав доступа.

    Args:
        request: Текущий HTTP-запрос.
        exc: Исключение проверки прав доступа.

    Returns:
        JSON-ответ с описанием ошибки проверки прав.
    """

    payload = ErrorResponse(
        error=exc.__class__.__name__,
        message=exc.message,
        details=exc.details or None,
        request_id=_get_request_id(request),
    )
    return _json_response(
        payload.model_dump(mode="json"), status_code=status.HTTP_403_FORBIDDEN
    )


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Возвращает ошибки валидации входного HTTP-запроса.

    Преобразует ошибки валидации FastAPI в список стандартизированных элементов
    ошибок и возвращает ответ со статусом `422 Unprocessable Entity`.

    Args:
        request: Текущий HTTP-запрос.
        exc: Исключение валидации входного запроса FastAPI.

    Returns:
        JSON-ответ со списком ошибок валидации.
    """

    payload = ValidationErrorResponse(
        errors=_build_validation_items(exc.errors()),
        request_id=_get_request_id(request),
    )
    return _json_response(
        payload.model_dump(mode="json"),
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


async def pydantic_validation_error_handler(
    request: Request,
    exc: ValidationError,
) -> JSONResponse:
    """Возвращает ошибки валидации Pydantic.

    Преобразует ошибки Pydantic в список стандартизированных элементов ошибок
    и возвращает ответ со статусом `422 Unprocessable Entity`.

    Args:
        request: Текущий HTTP-запрос.
        exc: Исключение валидации Pydantic.

    Returns:
        JSON-ответ со списком ошибок валидации.
    """

    payload = ValidationErrorResponse(
        errors=_build_validation_items(exc.errors()),
        request_id=_get_request_id(request),
    )
    return _json_response(
        payload.model_dump(mode="json"),
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Нормализует HTTPException в общий формат ошибок API.

    Преобразует стандартное HTTP-исключение Starlette в модель `ErrorResponse`,
    сохраняя HTTP-статус и заголовки исключения.

    Args:
        request: Текущий HTTP-запрос.
        exc: HTTP-исключение Starlette.

    Returns:
        JSON-ответ с нормализованным описанием HTTP-ошибки.
    """

    payload = ErrorResponse(
        error="HTTPException",
        message=_http_exception_message(exc.detail),
        details=_http_exception_details(exc.detail),
        request_id=_get_request_id(request),
    )
    return _json_response(
        payload.model_dump(mode="json"),
        status_code=exc.status_code,
        headers=dict(exc.headers) if exc.headers is not None else None,
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Возвращает ответ для непредвиденных ошибок.

    Формирует стандартизированный ответ для исключений, которые не были
    обработаны специализированными обработчиками.

    Args:
        request: Текущий HTTP-запрос.
        exc: Непредвиденное исключение.

    Returns:
        JSON-ответ с описанием внутренней ошибки сервера.
    """

    payload = ErrorResponse(
        error=exc.__class__.__name__,
        message="Внутренняя ошибка сервера.",
        details={"reason": str(exc)},
        request_id=_get_request_id(request),
    )
    return _json_response(
        payload.model_dump(mode="json"),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _build_validation_items(
    errors: Sequence[Mapping[str, Any] | Any],
) -> list[ValidationErrorItem]:
    """Преобразует ошибки валидации в элементы ответа API.

    Извлекает путь поля, сообщение, код ошибки и исходное значение из элементов
    ошибок FastAPI или Pydantic.

    Args:
        errors: Последовательность ошибок валидации.

    Returns:
        Список стандартизированных элементов ошибок валидации.
    """

    items: list[ValidationErrorItem] = []
    for item in errors:
        error_item = cast(Mapping[str, Any], item)
        loc = error_item.get("loc", ())
        field = ".".join(str(part) for part in loc if part is not None) or "body"
        items.append(
            ValidationErrorItem(
                field=field,
                message=str(error_item.get("msg", "Некорректное значение.")),
                code=_normalize_optional_str(error_item.get("type")),
                value=error_item.get("input"),
            ),
        )
    return items


def _http_exception_message(detail: Any) -> str:
    """Извлекает сообщение HTTP-ошибки.

    Получает человекочитаемое сообщение из значения `detail`. Для строк
    возвращает нормализованное значение, для словарей пытается использовать
    поле `message`. Если сообщение определить не удалось, возвращает
    стандартный текст HTTP-ошибки.

    Args:
        detail: Детали HTTP-исключения.

    Returns:
        Сообщение HTTP-ошибки.
    """

    if isinstance(detail, str):
        normalized_detail = detail.strip()
        if normalized_detail:
            return normalized_detail

    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    return "HTTP-ошибка."


def _http_exception_details(detail: Any) -> dict[str, Any] | None:
    """Извлекает дополнительные детали HTTP-ошибки.

    Возвращает `detail` как словарь, если он уже имеет словарную структуру.
    Для остальных типов деталей возвращает `None`.

    Args:
        detail: Детали HTTP-исключения.

    Returns:
        Словарь с деталями HTTP-ошибки или `None`.
    """

    if isinstance(detail, dict):
        return detail
    return None


def _get_request_id(request: Request) -> str | None:
    """Извлекает идентификатор запроса.

    Пытается получить идентификатор запроса из контекста запроса,
    затем из `request.state.request_id`, затем из HTTP-заголовка
    `X-Request-ID`.

    Args:
        request: Текущий HTTP-запрос.

    Returns:
        Идентификатор запроса или `None`, если его не удалось определить.
    """

    context = getattr(request.state, "request_context", None)
    request_id = getattr(context, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id.strip()

    state_request_id = getattr(request.state, "request_id", None)
    if isinstance(state_request_id, str) and state_request_id.strip():
        return state_request_id.strip()

    header_request_id = request.headers.get("X-Request-ID")
    if header_request_id is None:
        return None

    normalized_header = header_request_id.strip()
    return normalized_header or None


def _normalize_optional_str(value: Any) -> str | None:
    """Нормализует необязательное строковое значение.

    Преобразует значение в строку, удаляет пробельные символы по краям и
    возвращает `None`, если результат пустой.

    Args:
        value: Исходное значение.

    Returns:
        Нормализованная строка или `None`.
    """

    if value is None:
        return None

    normalized_value = str(value).strip()
    return normalized_value or None


def _json_response(
    content: dict[str, Any],
    *,
    status_code: int,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Создаёт JSON-ответ FastAPI.

    Нормализует заголовки ответа и создаёт объект `JSONResponse` с указанным
    содержимым и HTTP-статусом.

    Args:
        content: JSON-совместимое содержимое ответа.
        status_code: HTTP-статус ответа.
        headers: Дополнительные HTTP-заголовки ответа.

    Returns:
        JSON-ответ FastAPI.
    """

    normalized_headers = dict(headers) if headers is not None else None
    return JSONResponse(
        content=content,
        status_code=status_code,
        headers=normalized_headers,
    )
