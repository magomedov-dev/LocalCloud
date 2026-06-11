from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.dependencies import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    RequestContext,
    build_request_context,
)
from core.config import get_settings
from core.logging import get_logger

logger = get_logger("app.middleware")


# Пути, которые не должны отбрасываться backpressure (иначе healthcheck начнёт
# падать и контейнер уйдёт в рестарт-петлю).
_HEALTH_PATHS: frozenset[str] = frozenset({"/", "/health", "/healthz"})

DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Назначает request/correlation id и ведёт request-логирование.

    Middleware создаёт или переиспользует контекст текущего HTTP-запроса,
    записывает лог начала обработки, передаёт запрос следующему обработчику
    и после завершения добавляет идентификаторы запроса и корреляции
    в заголовки ответа.

    При возникновении исключения во время обработки запроса middleware
    записывает ошибку в лог и пробрасывает исключение дальше.

    Attributes:
        dispatch: Основной метод обработки HTTP-запроса middleware.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Обрабатывает HTTP-запрос и добавляет контекст запроса.

        Создаёт или получает существующий `RequestContext`, логирует начало
        обработки запроса, измеряет длительность выполнения, добавляет
        `X-Request-ID` и `X-Correlation-ID` в ответ и логирует результат.

        Args:
            request: Текущий HTTP-запрос.
            call_next: Следующий обработчик в цепочке middleware.

        Returns:
            HTTP-ответ следующего обработчика с добавленными заголовками
            идентификаторов запроса и корреляции.

        Raises:
            Exception: Если следующий обработчик или нижележащий код приложения
                выбросил исключение.
        """

        context = self._get_or_create_context(request)
        started_at = time.perf_counter()

        logger.info(
            "HTTP request started.",
            extra={
                "method": request.method,
                "path": request.url.path,
                "request_id": context.request_id,
                "correlation_id": context.correlation_id,
                "client_ip": context.client_ip,
                "user_agent": context.user_agent,
            },
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
            logger.exception(
                "HTTP request failed.",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "request_id": context.request_id,
                    "correlation_id": context.correlation_id,
                    "duration_ms": duration_ms,
                    "error_type": exc.__class__.__name__,
                },
            )
            raise

        duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
        response.headers[REQUEST_ID_HEADER] = context.request_id
        response.headers[CORRELATION_ID_HEADER] = context.correlation_id

        logger.info(
            "HTTP request finished.",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "request_id": context.request_id,
                "correlation_id": context.correlation_id,
                "duration_ms": duration_ms,
            },
        )
        return response

    @staticmethod
    def _get_or_create_context(request: Request) -> RequestContext:
        """Возвращает существующий или создаёт новый контекст запроса.

        Проверяет наличие `RequestContext` в `request.state`. Если контекст
        отсутствует, создаёт его на основе HTTP-заголовков и данных клиента.
        Дополнительно гарантирует наличие непустого `request_id`.

        Args:
            request: Текущий HTTP-запрос.

        Returns:
            Контекст текущего HTTP-запроса.
        """

        existing = getattr(request.state, "request_context", None)
        if isinstance(existing, RequestContext):
            return existing

        context = build_request_context(request)
        if not context.request_id:
            context = RequestContext(
                request_id=uuid4().hex,
                correlation_id=context.correlation_id or uuid4().hex,
                client_ip=context.client_ip,
                user_agent=context.user_agent,
            )
            request.state.request_context = context
            request.state.request_id = context.request_id
            request.state.correlation_id = context.correlation_id
        return context


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Добавляет базовые security headers к ответам.

    Middleware устанавливает набор защитных HTTP-заголовков, если они ещё
    не были заданы нижележащими обработчиками. Заголовки уменьшают риск
    MIME-sniffing, clickjacking и нежелательного доступа к браузерным
    возможностям.

    Attributes:
        dispatch: Основной метод обработки HTTP-запроса middleware.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Обрабатывает запрос и добавляет security headers в ответ.

        Передаёт запрос следующему обработчику, затем дополняет ответ базовыми
        заголовками безопасности.

        Args:
            request: Текущий HTTP-запрос.
            call_next: Следующий обработчик в цепочке middleware.

        Returns:
            HTTP-ответ с добавленными security headers.
        """

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        return response


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """Ограничивает число одновременно обрабатываемых запросов (backpressure).

    На маленьком хосте неограниченная очередь входящих запросов (например, шторм
    thumbnail-батчей) выедает память и коннекты к БД, что приводит к OOM или
    таймаутам пула. Этот middleware держит счётчик «в обработке» и при превышении
    потолка немедленно отвечает 503 с Retry-After, не запуская обработчик.

    Счётчик безопасен без блокировок: событийный цикл однопоточный, между
    проверкой и инкрементом нет await.

    Attributes:
        dispatch: Основной метод обработки HTTP-запроса middleware.
    """

    def __init__(self, app: FastAPI, *, max_concurrency: int) -> None:
        """Инициализирует middleware с потолком одновременных запросов."""

        super().__init__(app)
        self._max = max_concurrency
        self._inflight = 0

    async def dispatch(self, request: Request, call_next) -> Response:
        """Пропускает запрос, если не превышен потолок, иначе отдаёт 503."""

        # Health-проверки не отбрасываем — иначе оркестратор уведёт в рестарт.
        if request.url.path in _HEALTH_PATHS:
            return await call_next(request)

        if self._inflight >= self._max:
            logger.warning(
                "Запрос отклонён backpressure (превышен потолок одновременных).",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "inflight": self._inflight,
                    "max_concurrency": self._max,
                },
            )
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error": "ServiceUnavailable",
                    "message": "Сервер перегружен, повторите запрос позже.",
                },
                headers={"Retry-After": "2"},
            )

        self._inflight += 1
        try:
            return await call_next(request)
        finally:
            self._inflight -= 1


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Ограничивает время работы обработчика запроса.

    Защищает от зависших обработчиков, удерживающих коннект к БД/потоки. Таймаут
    охватывает фазу формирования ответа (до возврата обработчика); потоковая
    отдача тела (скачивание/стрим) происходит позже и под таймаут не попадает,
    поэтому большие загрузки/скачивания не обрываются.

    Attributes:
        dispatch: Основной метод обработки HTTP-запроса middleware.
    """

    def __init__(self, app: FastAPI, *, timeout_seconds: float) -> None:
        """Инициализирует middleware с таймаутом обработчика в секундах."""

        super().__init__(app)
        self._timeout = timeout_seconds

    async def dispatch(self, request: Request, call_next) -> Response:
        """Выполняет обработчик с таймаутом; при превышении отдаёт 504."""

        try:
            return await asyncio.wait_for(call_next(request), timeout=self._timeout)
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning(
                "Обработчик запроса превысил таймаут.",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "timeout_seconds": self._timeout,
                },
            )
            return JSONResponse(
                status_code=504,
                content={
                    "success": False,
                    "error": "GatewayTimeout",
                    "message": "Превышено время обработки запроса.",
                },
            )


def install_middleware(app: FastAPI) -> None:
    """Подключает middleware backend-приложения.

    Регистрирует GZip-сжатие, CORS-настройки, middleware security headers
    и middleware контекста запроса. Порядок подключения учитывает цепочку
    выполнения middleware FastAPI.

    Args:
        app: Экземпляр FastAPI-приложения, к которому подключаются middleware.

    Returns:
        None.
    """

    # Порядок выполнения = обратный порядку регистрации. Целевая цепочка
    # снаружи внутрь: RequestContext (логирование) → ConcurrencyLimit (сброс
    # перегрузки) → RequestTimeout → Security → CORS → GZip → обработчик.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEFAULT_CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=[
            "Accept",
            "Content-Type",
            REQUEST_ID_HEADER,
            CORRELATION_ID_HEADER,
        ],
        expose_headers=[REQUEST_ID_HEADER, CORRELATION_ID_HEADER],
    )
    server_settings = get_settings().server
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RequestTimeoutMiddleware,
        timeout_seconds=server_settings.request_timeout_seconds,
    )
    app.add_middleware(
        ConcurrencyLimitMiddleware,
        max_concurrency=server_settings.max_concurrent_requests,
    )
    app.add_middleware(RequestContextMiddleware)
