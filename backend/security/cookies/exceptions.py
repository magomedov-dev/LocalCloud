from __future__ import annotations

from security.cookies.enums import CookieErrorCode


class CookieError(Exception):
    """Базовое исключение для ошибок работы с cookie.

    Используется для ошибок валидации, чтения, установки и удаления cookie.
    Хранит человекочитаемое сообщение, машинный код ошибки, дополнительные
    диагностические данные и исходное исключение.

    Attributes:
        message: Человекочитаемое описание ошибки.
        code: Машинный код ошибки cookie.
        details: Дополнительные диагностические данные.
        cause: Исходное исключение, которое стало причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Ошибка работы с cookie.",
        *,
        code: CookieErrorCode = CookieErrorCode.INVALID_SETTINGS,
        details: dict[str, object] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение cookie.

        Args:
            message: Человекочитаемое описание ошибки.
            code: Машинный код ошибки cookie.
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

    def to_dict(self) -> dict[str, object]:
        """Преобразует ошибку в сериализуемый словарь.

        Returns:
            Словарь с именем ошибки, кодом, сообщением, дополнительными
            данными и причиной ошибки, если она есть.
        """

        payload: dict[str, object] = {
            "error": self.__class__.__name__,
            "code": self.code.value,
            "message": self.message,
        }

        if self.details:
            payload["details"] = self.details

        if self.cause is not None:
            payload["cause"] = self.cause.__class__.__name__

        return payload
