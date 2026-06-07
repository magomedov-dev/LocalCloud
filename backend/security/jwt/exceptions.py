from __future__ import annotations

from typing import Any

from security.jwt.enums import JwtErrorCode, JwtTokenType


class JwtTokenError(Exception):
    """Базовое исключение для ошибок обработки JWT token.

    Используется для ошибок создания, декодирования и валидации JWT.
    Хранит человекочитаемое сообщение, машинный код ошибки, дополнительные
    диагностические данные и исходное исключение.

    Attributes:
        message: Человекочитаемое описание ошибки.
        code: Машинный код ошибки JWT.
        details: Дополнительные диагностические данные.
        cause: Исходное исключение, которое стало причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Ошибка обработки JWT-токена.",
        *,
        code: JwtErrorCode = JwtErrorCode.INVALID_TOKEN,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение JWT.

        Args:
            message: Человекочитаемое описание ошибки.
            code: Машинный код ошибки JWT.
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


class JwtExpiredError(JwtTokenError):
    """Исключение для JWT token с истёкшим сроком действия.

    Используется, когда claim `exp` указывает на момент времени в прошлом.

    Attributes:
        message: Человекочитаемое описание ошибки.
        code: Машинный код ошибки. Всегда `expired_token`.
        details: Дополнительные диагностические данные.
        cause: Исходное исключение, которое стало причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Срок действия JWT-токена истёк.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку истёкшего JWT token.

        Args:
            message: Человекочитаемое описание ошибки.
            details: Дополнительные диагностические данные.
            cause: Исходное исключение, которое стало причиной ошибки.
        """

        super().__init__(
            message,
            code=JwtErrorCode.EXPIRED_TOKEN,
            details=details,
            cause=cause,
        )


class JwtInvalidClaimsError(JwtTokenError):
    """Исключение для JWT token с некорректными claims.

    Используется, когда token не содержит обязательные claims или содержит
    claims с некорректными значениями.

    Attributes:
        message: Человекочитаемое описание ошибки.
        code: Машинный код ошибки. Всегда `invalid_claims`.
        details: Дополнительные диагностические данные.
        cause: Исходное исключение, которое стало причиной ошибки.
    """

    def __init__(
        self,
        message: str = "JWT-токен содержит некорректные claims.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует ошибку некорректных JWT claims.

        Args:
            message: Человекочитаемое описание ошибки.
            details: Дополнительные диагностические данные.
            cause: Исходное исключение, которое стало причиной ошибки.
        """

        super().__init__(
            message,
            code=JwtErrorCode.INVALID_CLAIMS,
            details=details,
            cause=cause,
        )


class JwtInvalidTokenTypeError(JwtTokenError):
    """Исключение для JWT token с недопустимым типом.

    Используется, когда ожидается один тип token, например `access`, но в claim
    token передан другой тип или тип отсутствует.

    Attributes:
        message: Человекочитаемое описание ошибки.
        code: Машинный код ошибки. Всегда `invalid_token_type`.
        details: Дополнительные диагностические данные с ожидаемым и
            фактическим типом token.
    """

    def __init__(
        self,
        *,
        expected_type: JwtTokenType,
        actual_type: str | None,
        message: str | None = None,
    ) -> None:
        """Инициализирует ошибку недопустимого типа JWT token.

        Args:
            expected_type: Ожидаемый тип token.
            actual_type: Фактический тип token или None, если тип отсутствует.
            message: Человекочитаемое описание ошибки. Если не передано,
                используется сообщение по умолчанию.
        """

        super().__init__(
            message or "JWT-токен имеет недопустимый тип.",
            code=JwtErrorCode.INVALID_TOKEN_TYPE,
            details={"expected_type": expected_type, "actual_type": actual_type},
        )
