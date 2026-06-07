from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Request

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"
FORWARDED_FOR_HEADER = "X-Forwarded-For"
USER_AGENT_HEADER = "User-Agent"


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Контекст текущего HTTP-запроса.

    Хранит технические метаданные запроса, которые используются для логирования,
    трассировки, аудита и передачи информации о клиенте в сервисный слой.

    Attributes:
        request_id: Уникальный идентификатор текущего запроса.
        correlation_id: Идентификатор корреляции для связывания нескольких
            связанных запросов или операций.
        client_ip: IP-адрес клиента, если его удалось корректно определить.
        user_agent: Значение HTTP-заголовка User-Agent, если оно передано.
    """

    request_id: str
    correlation_id: str
    client_ip: str | None = None
    user_agent: str | None = None


def build_request_context(request: Request) -> RequestContext:
    """Собирает контекст запроса из состояния и HTTP-заголовков.

    Если контекст уже был создан ранее и сохранён в `request.state`, возвращает
    существующий объект. В противном случае формирует новый контекст на основе
    заголовков запроса, данных клиента и fallback-значений, после чего сохраняет
    его в состоянии запроса.

    Args:
        request: Текущий HTTP-запрос FastAPI.

    Returns:
        Контекст текущего HTTP-запроса.

    Raises:
        AttributeError: Если объект запроса не содержит ожидаемого состояния
            приложения или состояния запроса.
    """

    existing = getattr(request.state, "request_context", None)
    if isinstance(existing, RequestContext):
        return existing

    request_id = _normalize_identifier(
        request.headers.get(REQUEST_ID_HEADER),
        fallback=uuid4().hex,
    )
    correlation_id = _normalize_identifier(
        request.headers.get(CORRELATION_ID_HEADER),
        fallback=request_id,
    )
    context = RequestContext(
        request_id=request_id,
        correlation_id=correlation_id,
        client_ip=_extract_client_ip(request),
        user_agent=_normalize_optional_text(request.headers.get(USER_AGENT_HEADER)),
    )
    request.state.request_context = context
    request.state.request_id = context.request_id
    request.state.correlation_id = context.correlation_id
    return context


def get_request_context(request: Request) -> RequestContext:
    """Возвращает контекст текущего HTTP-запроса.

    Используется как FastAPI-зависимость для получения объекта `RequestContext`
    в эндпоинтах и других зависимостях.

    Args:
        request: Текущий HTTP-запрос FastAPI.

    Returns:
        Контекст текущего HTTP-запроса.
    """

    return build_request_context(request)


def get_request_id(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> str:
    """Возвращает идентификатор запроса.

    Args:
        context: Контекст текущего HTTP-запроса.

    Returns:
        Уникальный идентификатор текущего запроса.
    """

    return context.request_id


RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]
RequestIdDependency = Annotated[str, Depends(get_request_id)]


def _extract_client_ip(request: Request) -> str | None:
    """Извлекает и валидирует IP-адрес клиента из запроса.

    Сначала пытается получить первый адрес из заголовка `X-Forwarded-For`.
    Если заголовок отсутствует или содержит некорректный адрес, использует
    адрес клиента из `request.client`.

    Args:
        request: Текущий HTTP-запрос FastAPI.

    Returns:
        Валидный IP-адрес клиента или `None`, если адрес не удалось определить.
    """

    forwarded_for = request.headers.get(FORWARDED_FOR_HEADER)
    if forwarded_for:
        first_ip = forwarded_for.split(",", maxsplit=1)[0]
        normalized_ip = _normalize_optional_text(first_ip)
        if _is_valid_ip_address(normalized_ip):
            return normalized_ip

    if request.client is None:
        return None

    host = _normalize_optional_text(request.client.host)
    if _is_valid_ip_address(host):
        return host
    return None


def _normalize_identifier(value: str | None, *, fallback: str) -> str:
    """Нормализует строковый идентификатор.

    Удаляет пробельные символы по краям значения и возвращает fallback,
    если исходное значение отсутствует или после нормализации стало пустым.

    Args:
        value: Исходное значение идентификатора.
        fallback: Значение, возвращаемое при отсутствии валидного
            идентификатора.

    Returns:
        Нормализованный идентификатор или fallback-значение.
    """

    normalized_value = _normalize_optional_text(value)
    return normalized_value or fallback


def _normalize_optional_text(value: str | None) -> str | None:
    """Нормализует необязательное текстовое значение.

    Удаляет пробельные символы по краям строки. Пустые строки после
    нормализации преобразует в `None`.

    Args:
        value: Исходное текстовое значение.

    Returns:
        Нормализованная строка или `None`, если значение отсутствует или
        является пустым.
    """

    if value is None:
        return None

    normalized_value = value.strip()
    return normalized_value or None


def _is_valid_ip_address(value: str | None) -> bool:
    """Проверяет корректность IP-адреса.

    Валидирует строковое значение как IPv4- или IPv6-адрес с помощью
    стандартного модуля `ipaddress`.

    Args:
        value: Проверяемое значение IP-адреса.

    Returns:
        `True`, если значение является корректным IP-адресом, иначе `False`.
    """

    if value is None:
        return False

    try:
        ip_address(value)
    except ValueError:
        return False
    return True
