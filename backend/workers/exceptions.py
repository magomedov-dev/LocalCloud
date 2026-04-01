from __future__ import annotations

from typing import Any
from uuid import UUID


class WorkerError(Exception):
    """Базовая ошибка worker-модуля.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        details: Дополнительные JSON-совместимые детали ошибки.
        cause: Исходное исключение, из-за которого возникла worker-ошибка.
    """

    def __init__(
        self,
        message: str = "В процессе работы worker возникла ошибка.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует базовую worker-ошибку.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        self.message = message
        self.details = details.copy() if details is not None else {}
        self.cause = cause

        super().__init__(self.message)

        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        """Возвращает строковое представление ошибки.

        Returns:
            Сообщение об ошибке. Если есть детали, добавляет их к сообщению.
        """

        if not self.details:
            return self.message

        return f"{self.message} Details: {self.details}"

    def to_dict(self) -> dict[str, Any]:
        """Преобразует ошибку в словарь.

        Returns:
            Словарь с типом ошибки, сообщением, деталями и типом исходной причины,
            если она задана.
        """

        payload: dict[str, Any] = {
            "error": self.__class__.__name__,
            "message": self.message,
        }

        if self.details:
            payload["details"] = self.details

        if self.cause is not None:
            payload["cause"] = self.cause.__class__.__name__

        return payload


class WorkerConfigurationError(WorkerError):
    """Ошибка конфигурации worker-процесса.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        details: Дополнительные детали ошибки.
        cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
    """

    def __init__(
        self,
        message: str = "Конфигурация worker содержит некорректные значения.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку конфигурации worker-процесса.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        super().__init__(message, details=details, cause=cause)


class WorkerLifecycleError(WorkerError):
    """Ошибка жизненного цикла worker-процесса.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        details: Дополнительные детали ошибки.
        cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
    """

    def __init__(
        self,
        message: str = "Произошла ошибка жизненного цикла worker-процесса.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку жизненного цикла worker-процесса.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        super().__init__(message, details=details, cause=cause)


class WorkerTaskError(WorkerError):
    """Базовая ошибка обработки фоновой задачи worker-процессом.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        details: Дополнительные детали ошибки, включая task_id, task_type и
            operation, если они переданы.
        cause: Исходное исключение, из-за которого возникла ошибка задачи.
    """

    def __init__(
        self,
        message: str = "Произошла ошибка при обработке фоновой задачи.",
        *,
        task_id: UUID | None = None,
        task_type: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку обработки фоновой задачи.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            task_id: Идентификатор фоновой задачи.
            task_type: Тип фоновой задачи.
            operation: Название worker-операции, во время которой возникла ошибка.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        merged_details = details.copy() if details is not None else {}

        if task_id is not None:
            merged_details["task_id"] = str(task_id)

        if task_type is not None:
            merged_details["task_type"] = task_type

        if operation is not None:
            merged_details["operation"] = operation

        super().__init__(message, details=merged_details, cause=cause)


class WorkerTaskNotFoundError(WorkerTaskError):
    """Фоновая задача не найдена.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        task_id: Идентификатор фоновой задачи.
        task_type: Тип фоновой задачи.
        operation: Название worker-операции, во время которой возникла ошибка.
        details: Дополнительные детали ошибки.
        cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
    """

    def __init__(
        self,
        message: str = "Фоновая задача не найдена.",
        *,
        task_id: UUID | None = None,
        task_type: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку отсутствующей фоновой задачи.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            task_id: Идентификатор фоновой задачи.
            task_type: Тип фоновой задачи.
            operation: Название worker-операции, во время которой возникла ошибка.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        super().__init__(
            message,
            task_id=task_id,
            task_type=task_type,
            operation=operation,
            details=details,
            cause=cause,
        )


class WorkerTaskLockError(WorkerTaskError):
    """Не удалось захватить или обновить блокировку задачи.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        task_id: Идентификатор фоновой задачи.
        task_type: Тип фоновой задачи.
        operation: Название worker-операции, во время которой возникла ошибка.
        details: Дополнительные детали ошибки.
        cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
    """

    def __init__(
        self,
        message: str = "Не удалось установить блокировку фоновой задачи.",
        *,
        task_id: UUID | None = None,
        task_type: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку блокировки фоновой задачи.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            task_id: Идентификатор фоновой задачи.
            task_type: Тип фоновой задачи.
            operation: Название worker-операции, во время которой возникла ошибка.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        super().__init__(
            message,
            task_id=task_id,
            task_type=task_type,
            operation=operation,
            details=details,
            cause=cause,
        )


class WorkerTaskDispatchError(WorkerTaskError):
    """Не удалось определить или запустить обработчик задачи.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        task_id: Идентификатор фоновой задачи.
        task_type: Тип фоновой задачи.
        operation: Название worker-операции, во время которой возникла ошибка.
        details: Дополнительные детали ошибки.
        cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
    """

    def __init__(
        self,
        message: str = "Не удалось отправить задачу в обработчик.",
        *,
        task_id: UUID | None = None,
        task_type: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку отправки фоновой задачи в обработчик.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            task_id: Идентификатор фоновой задачи.
            task_type: Тип фоновой задачи.
            operation: Название worker-операции, во время которой возникла ошибка.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        super().__init__(
            message,
            task_id=task_id,
            task_type=task_type,
            operation=operation,
            details=details,
            cause=cause,
        )


class WorkerTaskHandlerError(WorkerTaskError):
    """Ошибка во время выполнения обработчика задачи.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        task_id: Идентификатор фоновой задачи.
        task_type: Тип фоновой задачи.
        operation: Название worker-операции, во время которой возникла ошибка.
        details: Дополнительные детали ошибки.
        cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
    """

    def __init__(
        self,
        message: str = "Во время выполнения обработчика задачи произошла ошибка.",
        *,
        task_id: UUID | None = None,
        task_type: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку выполнения обработчика фоновой задачи.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            task_id: Идентификатор фоновой задачи.
            task_type: Тип фоновой задачи.
            operation: Название worker-операции, во время которой возникла ошибка.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        super().__init__(
            message,
            task_id=task_id,
            task_type=task_type,
            operation=operation,
            details=details,
            cause=cause,
        )


class WorkerSchedulerError(WorkerError):
    """Ошибка планировщика периодических задач worker-процесса.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        details: Дополнительные детали ошибки.
        cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
    """

    def __init__(
        self,
        message: str = "Произошла ошибка планировщика worker-процесса.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку планировщика worker-процесса.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        super().__init__(message, details=details, cause=cause)


class WorkerShutdownError(WorkerLifecycleError):
    """Ошибка корректного завершения worker-процесса.

    Attributes:
        message: Человекочитаемое сообщение об ошибке.
        details: Дополнительные детали ошибки.
        cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
    """

    def __init__(
        self,
        message: str = "Не удалось корректно завершить worker-процесс.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку корректного завершения worker-процесса.

        Args:
            message: Человекочитаемое сообщение об ошибке.
            details: Дополнительные детали ошибки.
            cause: Исходное исключение. Если передано, сохраняется в `__cause__`.
        """

        super().__init__(message, details=details, cause=cause)
