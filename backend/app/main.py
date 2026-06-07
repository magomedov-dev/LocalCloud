from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from api import api_router
from fastapi import FastAPI

from app.exception_handlers import register_exception_handlers
from app.lifecycle import get_app_settings, shutdown_backend, startup_backend
from app.middleware import install_middleware
from core.config import get_settings
from schemas.common import StatusResponse


@asynccontextmanager
async def app_lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Управляет startup/shutdown жизненным циклом приложения.

    Выполняет startup-инициализацию backend-приложения перед началом обработки
    запросов и гарантирует корректное освобождение ресурсов при завершении
    работы приложения.

    Args:
        app: Экземпляр FastAPI-приложения, для которого выполняется жизненный
            цикл.

    Yields:
        Управление приложению на время его работы.

    Raises:
        Exception: Если ошибка возникла во время startup или shutdown и не была
            обработана внутри соответствующих функций жизненного цикла.
    """

    await startup_backend(app)
    try:
        yield
    finally:
        await shutdown_backend(app)


def create_app() -> FastAPI:
    """Создаёт и настраивает FastAPI-приложение LocalCloud.

    Загружает настройки приложения, создаёт экземпляр FastAPI, подключает
    middleware, регистрирует обработчики исключений и добавляет основной
    маршрутизатор API. Также регистрирует корневой эндпоинт `/` для проверки
    доступности backend-приложения.

    Returns:
        Настроенный экземпляр FastAPI-приложения LocalCloud.
    """

    settings = get_settings()

    application = FastAPI(
        title=settings.app.app_name,
        version=settings.app.app_version,
        description=settings.app.app_description,
        debug=settings.app.debug,
        lifespan=app_lifespan,
    )

    install_middleware(application)
    register_exception_handlers(application)
    application.include_router(api_router)

    @application.get("/", response_model=StatusResponse, tags=["root"])
    async def root() -> StatusResponse:
        """Возвращает базовую информацию о backend-приложении.

        Получает актуальные настройки приложения и возвращает статусный ответ,
        подтверждающий, что backend запущен и доступен.

        Returns:
            Статусный ответ с сообщением о работе backend-приложения.
        """

        app_settings = get_app_settings(application)
        return StatusResponse(
            message=f"{app_settings.app.app_name} backend is running.",
            success=True,
            status="ok",
        )

    return application


app = create_app()
