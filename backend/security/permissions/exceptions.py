from __future__ import annotations

import uuid
from typing import Any

from security.permissions.enums import (
    PermissionAction,
    PermissionDeniedReason,
    PermissionErrorCode,
)


class PermissionCheckError(Exception):
    """Базовое исключение для ошибок проверки прав доступа.

    Используется для ошибок валидации, проверки и обработки прав доступа.
    Хранит человекочитаемое сообщение, машинный код ошибки, дополнительные
    диагностические данные и исходное исключение.

    Attributes:
        message: Человекочитаемое описание ошибки.
        code: Машинный код ошибки прав доступа.
        details: Дополнительные диагностические данные.
        cause: Исходное исключение, которое стало причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Ошибка проверки прав доступа.",
        *,
        code: PermissionErrorCode = PermissionErrorCode.PERMISSION_DENIED,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку проверки прав доступа.

        Args:
            message: Человекочитаемое описание ошибки.
            code: Машинный код ошибки прав доступа.
            details: Дополнительные диагностические данные.
            cause: Исходное исключение, которое стало причиной ошибки.
        """

        self.message = message
        self.code = code
        self.details = details.copy() if details else {}
        self.cause = cause

        super().__init__(self.message)

        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        """Возвращает человекочитаемое представление ошибки.

        Returns:
            Сообщение об ошибке. Если есть дополнительные данные, они
            добавляются к сообщению.
        """

        if not self.details:
            return self.message

        return f"{self.message} Details: {self.details}"

    def to_dict(self) -> dict[str, Any]:
        """Преобразует ошибку в сериализуемый словарь.

        Returns:
            Словарь с именем ошибки, кодом, сообщением, дополнительными
            данными и причиной ошибки, если она есть.
        """

        payload: dict[str, Any] = {
            "error": self.__class__.__name__,
            "code": self.code.value,
            "message": self.message,
        }

        if self.details:
            payload["details"] = self.details

        if self.cause is not None:
            payload["cause"] = self.cause.__class__.__name__

        return payload


class PermissionDeniedError(PermissionCheckError):
    """Исключение для отказа в доступе.

    Используется, когда пользователь не имеет достаточных прав для выполнения
    действия над объектом файловой системы или административной операции.

    Attributes:
        message: Человекочитаемое описание ошибки.
        code: Машинный код ошибки. Всегда `permission_denied`.
        details: Дополнительные диагностические данные, включая действие,
            причину отказа, пользователя и объект файловой системы.
    """

    def __init__(
        self,
        message: str = "Недостаточно прав для выполнения операции.",
        *,
        action: PermissionAction | str | None = None,
        reason: PermissionDeniedReason | str | None = None,
        user_id: uuid.UUID | str | None = None,
        node_id: uuid.UUID | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Инициализирует ошибку отказа в доступе.

        Args:
            message: Человекочитаемое описание ошибки.
            action: Действие, для которого доступ был запрещён.
            reason: Причина отказа в доступе.
            user_id: Идентификатор пользователя, которому отказано в доступе.
            node_id: Идентификатор объекта файловой системы.
            details: Дополнительные диагностические данные.
        """

        merged_details = details.copy() if details else {}

        if action is not None:
            merged_details["action"] = str(action)

        if reason is not None:
            merged_details["reason"] = str(reason)

        if user_id is not None:
            merged_details["user_id"] = str(user_id)

        if node_id is not None:
            merged_details["node_id"] = str(node_id)

        super().__init__(
            message,
            code=PermissionErrorCode.PERMISSION_DENIED,
            details=merged_details,
        )
