from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from core.config import Settings
from security.jwt.enums import (
    SUPPORTED_JWT_TOKEN_TYPES,
    JwtClaimName,
    JwtErrorCode,
    JwtTokenType,
)
from security.jwt.exceptions import JwtInvalidClaimsError, JwtTokenError


def normalize_subject(subject: str | uuid.UUID) -> str:
    """Нормализует subject JWT token.

    Args:
        subject: Subject token. Обычно UUID пользователя или строковое
            представление идентификатора.

    Returns:
        Нормализованный subject в виде строки.

    Raises:
        JwtTokenError: Если subject не является строкой или UUID либо является
            пустой строкой.
    """

    if isinstance(subject, uuid.UUID):
        return str(subject)

    if not isinstance(subject, str):
        raise JwtTokenError(
            "JWT subject должен быть строкой или UUID.",
            code=JwtErrorCode.INVALID_SUBJECT,
            details={"value_type": type(subject).__name__},
        )

    normalized_subject = subject.strip()

    if not normalized_subject:
        raise JwtTokenError(
            "JWT subject не должен быть пустым.",
            code=JwtErrorCode.MISSING_SUBJECT,
        )

    return normalized_subject


def normalize_token_type(token_type: Any) -> JwtTokenType:
    """Нормализует и проверяет тип JWT token.

    Args:
        token_type: Значение типа token.

    Returns:
        Нормализованный тип token: `access` или `refresh`.

    Raises:
        JwtInvalidClaimsError: Если тип token не является строкой или не входит
            в список поддерживаемых типов.
    """

    if not isinstance(token_type, str):
        raise JwtInvalidClaimsError(
            "Тип JWT-токена должен быть строкой.",
            details={"token_type": token_type, "value_type": type(token_type).__name__},
        )

    normalized_token_type = token_type.strip().lower()

    if normalized_token_type not in SUPPORTED_JWT_TOKEN_TYPES:
        raise JwtInvalidClaimsError(
            "Тип JWT-токена не поддерживается.",
            details={
                "token_type": token_type,
                "allowed_types": list(SUPPORTED_JWT_TOKEN_TYPES),
            },
        )

    return normalized_token_type  # type: ignore[return-value]


def validate_token_value(token: str) -> str:
    """Проверяет и нормализует строковое значение JWT token.

    Args:
        token: JWT token для проверки.

    Returns:
        Нормализованный JWT token без пробелов по краям.

    Raises:
        JwtTokenError: Если token не является строкой или является пустым.
    """

    if not isinstance(token, str):
        raise JwtTokenError(
            "JWT-токен должен быть строкой.",
            code=JwtErrorCode.INVALID_TOKEN,
            details={"value_type": type(token).__name__},
        )

    normalized_token = token.strip()

    if not normalized_token:
        raise JwtTokenError(
            "JWT-токен не должен быть пустым.",
            code=JwtErrorCode.INVALID_TOKEN,
        )

    return normalized_token


def validate_jwt_settings(settings: Settings) -> None:
    """Проверяет настройки JWT в конфигурации приложения.

    Args:
        settings: Настройки приложения.

    Raises:
        JwtTokenError: Если secret key, algorithm, issuer, audience или сроки
            жизни token настроены некорректно.
    """

    security = settings.security

    if not isinstance(security.secret_key, str) or len(security.secret_key) < 16:
        raise JwtTokenError(
            "SECRET_KEY должен быть строкой длиной не менее 16 символов.",
            code=JwtErrorCode.INVALID_SETTINGS,
        )

    for field_name in ("jwt_algorithm", "jwt_issuer", "jwt_audience"):
        value = getattr(security, field_name)

        if not isinstance(value, str) or not value.strip():
            raise JwtTokenError(
                f"{field_name.upper()} должен быть непустой строкой.",
                code=JwtErrorCode.INVALID_SETTINGS,
            )

    if security.access_token_expire_minutes <= 0:
        raise JwtTokenError(
            "ACCESS_TOKEN_EXPIRE_MINUTES должен быть больше нуля.",
            code=JwtErrorCode.INVALID_SETTINGS,
            details={
                "access_token_expire_minutes": security.access_token_expire_minutes,
            },
        )

    if security.refresh_token_expire_days <= 0:
        raise JwtTokenError(
            "REFRESH_TOKEN_EXPIRE_DAYS должен быть больше нуля.",
            code=JwtErrorCode.INVALID_SETTINGS,
            details={"refresh_token_expire_days": security.refresh_token_expire_days},
        )


def normalize_datetime(value: datetime) -> datetime:
    """Нормализует datetime к UTC.

    Args:
        value: Значение datetime.

    Returns:
        Datetime в UTC. Если исходное значение было naive, оно считается UTC.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)


def claim_timestamp_to_datetime(value: Any, *, claim_name: str) -> datetime:
    """Преобразует JWT timestamp claim в datetime.

    Args:
        value: Значение claim. Может быть `datetime`, `int` или `float`.
        claim_name: Имя claim, используемое в диагностических данных ошибки.

    Returns:
        Значение claim как timezone-aware datetime в UTC.

    Raises:
        JwtInvalidClaimsError: Если claim не является timestamp или datetime.
    """

    if isinstance(value, datetime):
        return normalize_datetime(value)

    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC)

    raise JwtInvalidClaimsError(
        "JWT claim должен быть timestamp или datetime.",
        details={
            "claim": claim_name,
            "value": value,
            "value_type": type(value).__name__,
        },
    )


def require_claims(claims: dict[str, Any]) -> None:
    """Проверяет наличие обязательных JWT claims.

    Args:
        claims: JWT claims после декодирования token.

    Raises:
        JwtInvalidClaimsError: Если отсутствует один или несколько обязательных
            claims.
    """

    required = (
        JwtClaimName.SUBJECT.value,
        JwtClaimName.JWT_ID.value,
        JwtClaimName.ISSUED_AT.value,
        JwtClaimName.NOT_BEFORE.value,
        JwtClaimName.EXPIRES_AT.value,
        JwtClaimName.ISSUER.value,
        JwtClaimName.AUDIENCE.value,
    )
    missing = [claim for claim in required if claim not in claims]

    if missing:
        raise JwtInvalidClaimsError(details={"missing_claims": missing})
