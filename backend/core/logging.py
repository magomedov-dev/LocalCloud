from __future__ import annotations

import json
import logging
import logging.config
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.constants import LoggingConstants

if TYPE_CHECKING:
    from core.config import LoggingSettings


class JsonFormatter(logging.Formatter):
    """Форматтер логов в JSON.

    Преобразует объект `logging.LogRecord` в JSON-строку, включая базовые поля
    записи, сведения об исключении, stack trace и дополнительные поля,
    переданные через `extra`.

    Methods:
        format: Формирует JSON-представление записи лога.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Форматирует запись лога в JSON-строку.

        Собирает стандартные поля записи лога, добавляет данные об исключении
        и stack trace при их наличии, а также переносит пользовательские поля
        `extra` в отдельный блок.

        Args:
            record: Запись лога, которую необходимо отформатировать.

        Returns:
            JSON-строка с данными записи лога.
        """

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        reserved = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
        }

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in reserved and not key.startswith("_")
        }

        if extras:
            payload["extra"] = extras

        return json.dumps(payload, ensure_ascii=False, default=str)


class PlainFormatter(logging.Formatter):
    """Форматтер логов для чтения человеком.

    Используется для локальной разработки и выводит время, уровень,
    имя логгера, модуль, строку и сообщение в компактном текстовом формате.

    Attributes:
        default_format: Формат строки лога по умолчанию.
    """

    default_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(module)s:%(lineno)d | %(message)s"
    )

    def __init__(self) -> None:
        """Инициализирует plain-форматтер логов.

        Настраивает формат сообщения и формат даты, используемые стандартным
        `logging.Formatter`.
        """

        super().__init__(
            fmt=self.default_format,
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def build_logging_config(settings: LoggingSettings) -> dict[str, Any]:
    """Создаёт конфигурацию логирования для `dictConfig`.

    Формирует словарь конфигурации logging с console-handler и, при включённой
    файловой записи, file-handler на основе `RotatingFileHandler`. Выбирает
    JSON- или plain-форматтер в зависимости от настроек. При включённой записи
    в файл также создаёт родительскую директорию файла логов.

    Args:
        settings: Настройки логирования приложения.

    Returns:
        Словарь конфигурации логирования, совместимый с
        `logging.config.dictConfig`.
    """

    formatter_name = "json" if settings.log_json else "plain"

    handlers: dict[str, Any] = {
        "console": {
            "class": "logging.StreamHandler",
            "level": settings.log_level,
            "formatter": formatter_name,
            "stream": "ext://sys.stdout",
        },
    }

    root_handlers = ["console"]

    if settings.log_file_enabled:
        log_file_path = Path(settings.log_file_path)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": settings.log_level,
            "formatter": formatter_name,
            "filename": str(log_file_path),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        }

        root_handlers.append("file")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {
                "()": PlainFormatter,
            },
            "json": {
                "()": JsonFormatter,
            },
        },
        "handlers": handlers,
        "loggers": {
            "": {
                "handlers": root_handlers,
                "level": settings.log_level,
            }
        },
    }


def setup_logging(settings: LoggingSettings) -> None:
    """Настраивает логирование приложения.

    Строит конфигурацию логирования, применяет её через `dictConfig` и пишет
    debug-сообщение о применённых параметрах. Функцию следует вызывать один раз
    при запуске backend-приложения.

    Args:
        settings: Настройки логирования приложения.
    """

    config = build_logging_config(settings)
    logging.config.dictConfig(config)

    logger = logging.getLogger("localcloud.core.logging")
    logger.debug(
        "Логирование настроено",
        extra={
            "log_level": settings.log_level,
            "log_json": settings.log_json,
            "log_file_enabled": settings.log_file_enabled,
        },
    )


def get_logger(name: str) -> logging.Logger:
    """Возвращает логгер приложения.

    Создаёт или получает логгер с единым префиксом `localcloud`. Если имя уже
    начинается с `localcloud`, оно используется без изменений. Если имя пустое,
    возвращается корневой логгер приложения.

    Args:
        name: Имя логгера или имя модуля.

    Returns:
        Логгер приложения.
    """

    if not name:
        return logging.getLogger("localcloud")

    if name.startswith("localcloud"):
        return logging.getLogger(name)

    return logging.getLogger(f"localcloud.{name}")


def silence_noisy_loggers(
    logger_names: Iterable[str] | None = None,
    level: int | str = logging.WARNING,
) -> None:
    """Уменьшает шум от сторонних библиотек.

    Устанавливает указанный уровень логирования для переданных логгеров.
    Если список имён не передан, используются стандартные шумные логгеры
    из `LoggingConstants.DEFAULT_NOISY_LOGGERS`.

    Args:
        logger_names: Имена логгеров, которые нужно приглушить. Если `None`,
            используются стандартные шумные логгеры.
        level: Уровень логирования, который нужно установить для указанных
            логгеров.
    """

    names = (
        LoggingConstants.DEFAULT_NOISY_LOGGERS if logger_names is None else logger_names
    )

    for logger_name in names:
        logging.getLogger(logger_name).setLevel(level)


def configure_root_exception_logging() -> None:
    """Настраивает резервное логирование неперехваченных исключений.

    Устанавливает пользовательский `sys.excepthook`, который записывает
    неперехваченные исключения в критический лог. Исключение `KeyboardInterrupt`
    передаётся стандартному обработчику Python.

    Этот обработчик не заменяет обработчики исключений FastAPI и нужен только
    для ошибок, вышедших за пределы приложения.
    """

    def handle_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: Any,
    ) -> None:
        """Логирует неперехваченное исключение.

        Args:
            exc_type: Тип неперехваченного исключения.
            exc_value: Экземпляр неперехваченного исключения.
            exc_traceback: Traceback неперехваченного исключения.
        """

        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger = get_logger("core.uncaught")
        logger.critical(
            "Неперехваченное исключение",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = handle_exception
