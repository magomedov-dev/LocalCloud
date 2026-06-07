from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from security.jwt.enums import JwtErrorCode, JwtTokenType
from security.jwt.exceptions import JwtTokenError


@dataclass(frozen=True, slots=True)
class JwtPayload:
    """Payload JWT token после декодирования и валидации.

    Attributes:
        subject: Subject token. Обычно содержит UUID пользователя.
        token_type: Тип token: access или refresh.
        jti: Уникальный идентификатор JWT.
        issued_at: Дата и время выпуска token.
        not_before: Дата и время, раньше которых token считается недействительным.
        expires_at: Дата и время истечения срока действия token.
        issuer: Издатель token.
        audience: Получатель token.
        claims: Дополнительные claims token.
    """

    subject: str
    token_type: JwtTokenType
    jti: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    issuer: str
    audience: str
    claims: dict[str, Any]

    @property
    def user_id(self) -> uuid.UUID:
        """Возвращает subject token как UUID пользователя.

        Returns:
            UUID пользователя из JWT subject.

        Raises:
            JwtTokenError: Если subject не является корректным UUID.
        """

        try:
            return uuid.UUID(self.subject)

        except ValueError as exc:
            raise JwtTokenError(
                "JWT subject не является корректным UUID.",
                code=JwtErrorCode.INVALID_SUBJECT,
                details={"subject": self.subject},
                cause=exc,
            ) from exc

    @property
    def is_access_token(self) -> bool:
        """Проверяет, является ли token access token.

        Returns:
            True, если token имеет тип access, иначе False.
        """

        return self.token_type == "access"

    @property
    def is_refresh_token(self) -> bool:
        """Проверяет, является ли token refresh token.

        Returns:
            True, если token имеет тип refresh, иначе False.
        """

        return self.token_type == "refresh"

    def is_expired_at(self, moment: datetime | None = None) -> bool:
        """Проверяет, истёк ли token на указанный момент времени.

        Args:
            moment: Момент времени для проверки. Если не передан, используется
                текущее время в UTC.

        Returns:
            True, если token истёк на указанный момент, иначе False.
        """

        current_moment = moment or datetime.now(UTC)

        return self.expires_at <= current_moment
