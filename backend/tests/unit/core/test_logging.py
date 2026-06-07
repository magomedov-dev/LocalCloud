"""Тесты модуля core.logging: форматтеры, настройка и обработка исключений."""

from __future__ import annotations

import logging

import pytest

from core.logging import (
    JsonFormatter,
    PlainFormatter,
    build_logging_config,
    configure_root_exception_logging,
    get_logger,
    setup_logging,
    silence_noisy_loggers,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def make_logging_settings(
    log_level: str = "DEBUG",
    log_json: bool = False,
    log_file_enabled: bool = False,
    log_file_path: str = "/tmp/localcloud-test.log",
) -> object:
    """Возвращает минимальный объект, похожий на LoggingSettings."""
    from core.config import LoggingSettings

    return LoggingSettings(
        LOG_LEVEL=log_level,
        LOG_JSON=log_json,
        LOG_FILE_ENABLED=log_file_enabled,
        LOG_FILE_PATH=log_file_path,
    )


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_logger_instance(self) -> None:
        logger = get_logger("test.module")
        assert logger is not None
        assert isinstance(logger, logging.Logger)

    def test_empty_name_returns_root_app_logger(self) -> None:
        logger = get_logger("")
        assert logger.name == "localcloud"

    def test_name_already_prefixed_is_unchanged(self) -> None:
        logger = get_logger("localcloud.something")
        assert logger.name == "localcloud.something"

    def test_name_without_prefix_gets_prefixed(self) -> None:
        logger = get_logger("security.auth")
        assert logger.name == "localcloud.security.auth"

    def test_same_name_returns_consistent_logger(self) -> None:
        logger1 = get_logger("mymodule")
        logger2 = get_logger("mymodule")
        assert logger1 is logger2

    def test_logger_can_log_info(self) -> None:
        logger = get_logger("test.info")
        # Не должно выбрасывать исключение
        logger.info("test info message")

    def test_logger_can_log_warning(self) -> None:
        logger = get_logger("test.warning")
        logger.warning("test warning message")

    def test_logger_can_log_error(self) -> None:
        logger = get_logger("test.error")
        logger.error("test error message")

    def test_logger_can_log_with_extra(self) -> None:
        logger = get_logger("test.extra")
        logger.info("test", extra={"key": "value", "number": 42})


# ---------------------------------------------------------------------------
# setup_logging / build_logging_config
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_setup_logging_does_not_raise_plain(self) -> None:
        settings = make_logging_settings(log_json=False, log_level="WARNING")
        setup_logging(settings)  # type: ignore[arg-type]

    def test_setup_logging_does_not_raise_json(self) -> None:
        settings = make_logging_settings(log_json=True, log_level="ERROR")
        setup_logging(settings)  # type: ignore[arg-type]

    def test_setup_logging_with_debug_level(self) -> None:
        settings = make_logging_settings(log_level="DEBUG")
        setup_logging(settings)  # type: ignore[arg-type]


class TestBuildLoggingConfig:
    def test_plain_formatter_config(self) -> None:
        settings = make_logging_settings(log_json=False)
        config = build_logging_config(settings)  # type: ignore[arg-type]
        assert config["version"] == 1
        assert "plain" in config["formatters"]
        assert "console" in config["handlers"]

    def test_json_formatter_config(self) -> None:
        settings = make_logging_settings(log_json=True)
        config = build_logging_config(settings)  # type: ignore[arg-type]
        assert "json" in config["formatters"]
        assert config["handlers"]["console"]["formatter"] == "json"

    def test_file_handler_added_when_enabled(self, tmp_path) -> None:
        log_file = str(tmp_path / "app.log")
        settings = make_logging_settings(log_file_enabled=True, log_file_path=log_file)
        config = build_logging_config(settings)  # type: ignore[arg-type]
        assert "file" in config["handlers"]

    def test_no_file_handler_when_disabled(self) -> None:
        settings = make_logging_settings(log_file_enabled=False)
        config = build_logging_config(settings)  # type: ignore[arg-type]
        assert "file" not in config["handlers"]

    def test_disable_existing_loggers_false(self) -> None:
        settings = make_logging_settings()
        config = build_logging_config(settings)  # type: ignore[arg-type]
        assert config["disable_existing_loggers"] is False


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------


class TestJsonFormatter:
    def test_format_basic_record(self) -> None:
        import json

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "hello world"
        assert data["level"] == "INFO"
        assert "timestamp" in data

    def test_format_with_extra_fields(self) -> None:
        import json

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.custom_field = "custom_value"  # type: ignore[attr-defined]
        output = formatter.format(record)
        data = json.loads(output)
        assert "extra" in data
        assert data["extra"].get("custom_field") == "custom_value"

    def test_format_includes_exception(self) -> None:
        import json
        import sys

        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_format_includes_stack_info(self) -> None:
        import json

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="with stack",
            args=(),
            exc_info=None,
        )
        record.stack_info = "Stack (most recent call last):\n  fake frame"
        output = formatter.format(record)
        data = json.loads(output)
        assert "stack" in data
        assert "fake frame" in data["stack"]


# ---------------------------------------------------------------------------
# PlainFormatter
# ---------------------------------------------------------------------------


class TestPlainFormatter:
    def test_format_returns_string(self) -> None:
        formatter = PlainFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="plain message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert isinstance(output, str)
        assert "plain message" in output


# ---------------------------------------------------------------------------
# silence_noisy_loggers
# ---------------------------------------------------------------------------


class TestSilenceNoisyLoggers:
    def test_silences_specified_loggers(self) -> None:
        silence_noisy_loggers(["uvicorn", "httpx"])
        for name in ["uvicorn", "httpx"]:
            assert logging.getLogger(name).level == logging.WARNING

    def test_uses_default_loggers_when_none_passed(self) -> None:
        # Не должно выбрасывать исключение
        silence_noisy_loggers()

    def test_custom_level_applied(self) -> None:
        silence_noisy_loggers(["boto3"], level=logging.ERROR)
        assert logging.getLogger("boto3").level == logging.ERROR


# ---------------------------------------------------------------------------
# configure_root_exception_logging
# ---------------------------------------------------------------------------


class TestConfigureRootExceptionLogging:
    def test_does_not_raise(self) -> None:
        configure_root_exception_logging()

    def test_installs_excepthook(self) -> None:
        import sys

        original = sys.excepthook
        try:
            configure_root_exception_logging()
            assert sys.excepthook is not original
        finally:
            sys.excepthook = original

    def test_excepthook_logs_critical_for_regular_exception(self) -> None:
        import sys
        from unittest.mock import MagicMock, patch

        original = sys.excepthook
        try:
            configure_root_exception_logging()
            hook = sys.excepthook

            mock_logger = MagicMock()
            with patch("core.logging.get_logger", return_value=mock_logger):
                try:
                    raise RuntimeError("uncaught")
                except RuntimeError:
                    exc_type, exc_value, exc_tb = sys.exc_info()
                    hook(exc_type, exc_value, exc_tb)

            mock_logger.critical.assert_called_once()
            assert mock_logger.critical.call_args.kwargs["exc_info"] == (
                exc_type,
                exc_value,
                exc_tb,
            )
        finally:
            sys.excepthook = original

    def test_excepthook_delegates_keyboard_interrupt(self) -> None:
        import sys
        from unittest.mock import patch

        original = sys.excepthook
        try:
            configure_root_exception_logging()
            hook = sys.excepthook

            with patch("sys.__excepthook__") as default_hook:
                exc = KeyboardInterrupt()
                hook(KeyboardInterrupt, exc, None)

            default_hook.assert_called_once_with(KeyboardInterrupt, exc, None)
        finally:
            sys.excepthook = original
