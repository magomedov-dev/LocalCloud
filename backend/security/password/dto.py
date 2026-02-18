from __future__ import annotations

from dataclasses import dataclass

from security.password.enums import PasswordValidationErrorCode


@dataclass(frozen=True, slots=True)
class PasswordValidationError:
    """Ошибка валидации пароля.

    Attributes:
        code: Машинный код ошибки валидации пароля.
        message: Человекочитаемое описание ошибки.
    """

    code: PasswordValidationErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class PasswordValidationResult:
    """Результат валидации пароля.

    Attributes:
        is_valid: True, если пароль прошёл все проверки, иначе False.
        errors: Список ошибок валидации пароля.
    """

    is_valid: bool
    errors: tuple[PasswordValidationError, ...] = ()

    @property
    def messages(self) -> tuple[str, ...]:
        """Возвращает сообщения всех ошибок валидации.

        Returns:
            Кортеж человекочитаемых сообщений об ошибках.
        """

        return tuple(error.message for error in self.errors)
