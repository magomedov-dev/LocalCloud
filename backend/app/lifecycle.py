from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI

from core.config import Settings, get_settings
from core.logging import (
    configure_root_exception_logging,
    get_logger,
    setup_logging,
    silence_noisy_loggers,
)
from core.secret_validation import (
    validate_secrets_or_raise,
    warn_if_cookies_insecure,
)
from database import (
    close_db_client,
    init_db_client,
    is_db_client_initialized,
    ping_database,
)
from services import get_health_service
from storage import StorageService, get_storage_service, shutdown_storage_executor
from storage.capacity import get_capacity_provider

logger = get_logger("app.lifecycle")


async def startup_backend(app: FastAPI) -> None:
    """Выполняет startup backend-приложения.

    Настраивает логирование, сохраняет настройки и время запуска в состоянии
    приложения, инициализирует клиент базы данных, проверяет подключение
    к базе данных, подготавливает бакеты объектного хранилища и создаёт сервис
    проверки состояния приложения.

    Если на одном из этапов запуска возникает ошибка, выполняется безопасное
    освобождение уже инициализированных ресурсов.

    Args:
        app: Экземпляр FastAPI-приложения, для которого выполняется startup.

    Returns:
        None.

    Raises:
        Exception: Если не удалось инициализировать базу данных, объектное
            хранилище, health-сервис или другой обязательный ресурс приложения.
    """

    settings = get_settings()
    storage_service: StorageService | None = None

    setup_logging(settings.logging)
    silence_noisy_loggers()
    configure_root_exception_logging()

    try:
        app.state.settings = settings
        app.state.started_at = datetime.now(UTC)

        # Падаем сразу, если в production остались дефолтные секреты — лучше
        # явный отказ на старте, чем тихая компрометация.
        validate_secrets_or_raise(settings)
        warn_if_cookies_insecure(settings)

        if not is_db_client_initialized():
            init_db_client(settings.database)
        await ping_database()

        storage_service = get_storage_service(settings=settings.storage)
        await storage_service.ensure_buckets_ready(create_missing=True)

        # Определяем пул хранилища и проверяем конфигурацию ёмкости. Падаем на
        # старте, если задано больше реального диска или пул нельзя определить.
        capacity_provider = get_capacity_provider(settings.storage)
        await capacity_provider.validate_on_startup()

        app.state.storage_service = storage_service
        app.state.capacity_provider = capacity_provider
        app.state.health_service = get_health_service(
            settings=settings,
            storage_service=storage_service,
        )

        logger.info(
            "Backend успешно запущен.",
            extra={
                "app_name": settings.app.app_name,
                "app_version": settings.app.app_version,
                "debug": settings.app.debug,
            },
        )
    except Exception:
        await _safe_shutdown_resources(storage_service)
        raise


async def shutdown_backend(app: FastAPI) -> None:
    """Выполняет корректное завершение backend-приложения.

    Получает сервис объектного хранилища из состояния приложения, закрывает
    связанные ресурсы, закрывает клиент базы данных и очищает ссылки на сервисы
    в `app.state`.

    Args:
        app: Экземпляр FastAPI-приложения, для которого выполняется shutdown.

    Returns:
        None.
    """

    storage_service = _get_state_value(app, "storage_service")
    await _safe_shutdown_resources(storage_service)

    app.state.storage_service = None
    app.state.health_service = None

    logger.info("Backend корректно остановлен.")


def get_app_settings(app: FastAPI) -> Settings:
    """Возвращает настройки приложения.

    Пытается получить объект настроек из `app.state.settings`. Если настройки
    ещё не сохранены в состоянии приложения или имеют неподходящий тип,
    возвращает настройки через стандартную функцию `get_settings`.

    Args:
        app: Экземпляр FastAPI-приложения.

    Returns:
        Настройки приложения.
    """

    state_settings = _get_state_value(app, "settings")
    if isinstance(state_settings, Settings):
        return state_settings
    return get_settings()


async def _safe_shutdown_resources(storage_service: StorageService | None) -> None:
    """Безопасно освобождает инфраструктурные ресурсы приложения.

    Закрывает клиент объектного хранилища, если он был передан, и клиент базы
    данных, если он был инициализирован. Ошибки закрытия ресурсов не пробрасывает
    дальше, а записывает в лог предупреждение.

    Args:
        storage_service: Сервис объектного хранилища, клиент которого нужно
            закрыть.

    Returns:
        None.
    """

    if storage_service is not None:
        try:
            await storage_service.client.close()
        except Exception as exc:
            logger.warning(
                "Не удалось корректно закрыть storage client.",
                extra={"reason": str(exc), "error_type": exc.__class__.__name__},
            )

    # Process-wide storage thread pool — shut it down once on app shutdown.
    try:
        shutdown_storage_executor()
    except Exception as exc:
        logger.warning(
            "Не удалось остановить пул потоков хранилища.",
            extra={"reason": str(exc), "error_type": exc.__class__.__name__},
        )

    if is_db_client_initialized():
        try:
            await close_db_client()
        except Exception as exc:
            logger.warning(
                "Не удалось корректно закрыть клиент базы данных.",
                extra={"reason": str(exc), "error_type": exc.__class__.__name__},
            )


def _get_state_value(app: FastAPI, name: str) -> Any | None:
    """Возвращает значение из состояния приложения.

    Извлекает атрибут из `app.state` по имени. Если атрибут отсутствует,
    возвращает `None`.

    Args:
        app: Экземпляр FastAPI-приложения.
        name: Имя атрибута в состоянии приложения.

    Returns:
        Значение из состояния приложения или `None`.
    """

    return getattr(app.state, name, None)
