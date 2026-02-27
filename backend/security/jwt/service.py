from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError as JoseJWTError
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError

from core.config import Settings, get_settings
from security.jwt.dto import JwtPayload
from security.jwt.enums import JwtClaimName, JwtErrorCode, JwtTokenType
from security.jwt.exceptions import (
    JwtExpiredError,
    JwtInvalidClaimsError,
    JwtInvalidTokenTypeError,
    JwtTokenError,
)
from security.jwt.validators import (
    claim_timestamp_to_datetime,
    normalize_datetime,
    normalize_subject,
    normalize_token_type,
    require_claims,
    validate_jwt_settings,
    validate_token_value,
)


def create_access_token(
    subject: str | uuid.UUID,
    *,
    additional_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
    settings: Settings | None = None,
) -> str:
    """Создаёт access JWT token для пользователя.

    Args:
        subject: Subject token. Обычно UUID пользователя.
        additional_claims: Дополнительные claims, которые нужно добавить в
            payload token.
        expires_delta: Время жизни token. Если не передано, используется
            значение из настроек security.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        Закодированный access JWT token.

    Raises:
        JwtTokenError: Если настройки JWT некорректны, subject недопустим или
            token не удалось создать.
    """

    app_settings = settings or get_settings()
    expiration_delta = expires_delta or timedelta(
        minutes=app_settings.security.access_token_expire_minutes,
    )

    return create_token(
        subject=subject,
        token_type="access",
        expires_delta=expiration_delta,
        additional_claims=additional_claims,
        settings=app_settings,
    )


def create_refresh_token(
    subject: str | uuid.UUID,
    *,
    additional_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
    settings: Settings | None = None,
) -> str:
    """Создаёт refresh JWT token для пользователя.

    Args:
        subject: Subject token. Обычно UUID пользователя.
        additional_claims: Дополнительные claims, которые нужно добавить в
            payload token.
        expires_delta: Время жизни token. Если не передано, используется
            значение из настроек security.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        Закодированный refresh JWT token.

    Raises:
        JwtTokenError: Если настройки JWT некорректны, subject недопустим или
            token не удалось создать.
    """

    app_settings = settings or get_settings()
    expiration_delta = expires_delta or timedelta(
        days=app_settings.security.refresh_token_expire_days,
    )

    return create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=expiration_delta,
        additional_claims=additional_claims,
        settings=app_settings,
    )


def create_token(
    subject: str | uuid.UUID,
    *,
    token_type: JwtTokenType,
    expires_delta: timedelta,
    additional_claims: dict[str, Any] | None = None,
    settings: Settings | None = None,
    issued_at: datetime | None = None,
    jti: str | None = None,
) -> str:
    """Создаёт JWT token указанного типа.

    Args:
        subject: Subject token. Обычно UUID пользователя.
        token_type: Тип token: `access` или `refresh`.
        expires_delta: Время жизни token.
        additional_claims: Дополнительные claims. Зарезервированные JWT claims
            из `JwtClaimName` не перезаписываются.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.
        issued_at: Момент выпуска token. Если не передан, используется текущее
            время в UTC.
        jti: Уникальный идентификатор token. Если не передан, генерируется
            автоматически.

    Returns:
        Закодированный JWT token.

    Raises:
        JwtTokenError: Если настройки JWT некорректны, входные данные
            недопустимы или token не удалось закодировать.
    """

    app_settings = settings or get_settings()
    validate_jwt_settings(app_settings)

    normalized_token_type = normalize_token_type(token_type)
    now = normalize_datetime(issued_at or datetime.now(UTC))
    expires_at = now + expires_delta

    payload: dict[str, Any] = {
        JwtClaimName.SUBJECT.value: normalize_subject(subject),
        JwtClaimName.TOKEN_TYPE.value: normalized_token_type,
        JwtClaimName.JWT_ID.value: jti or generate_jti(),
        JwtClaimName.ISSUED_AT.value: now,
        JwtClaimName.NOT_BEFORE.value: now,
        JwtClaimName.EXPIRES_AT.value: expires_at,
        JwtClaimName.ISSUER.value: app_settings.security.jwt_issuer,
        JwtClaimName.AUDIENCE.value: app_settings.security.jwt_audience,
    }

    if additional_claims:
        reserved_claims = {claim.value for claim in JwtClaimName}
        payload.update(
            {
                key: value
                for key, value in additional_claims.items()
                if key not in reserved_claims
            }
        )

    try:
        return str(
            jwt.encode(
                claims=payload,
                key=app_settings.security.secret_key,
                algorithm=app_settings.security.jwt_algorithm,
            )
        )
    except Exception as exc:
        raise JwtTokenError(
            "Не удалось создать JWT-токен.",
            code=JwtErrorCode.INVALID_TOKEN,
            details={
                "token_type": normalized_token_type,
                "algorithm": app_settings.security.jwt_algorithm,
            },
            cause=exc,
        ) from exc


def decode_token(
    token: str,
    *,
    expected_type: JwtTokenType | None = None,
    settings: Settings | None = None,
    verify_expiration: bool = True,
) -> JwtPayload:
    """Декодирует и валидирует JWT token.

    Args:
        token: JWT token для декодирования.
        expected_type: Ожидаемый тип token. Если передан, payload проверяется
            на соответствие этому типу.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.
        verify_expiration: Проверять ли срок действия token.

    Returns:
        Декодированный и валидированный JWT payload.

    Raises:
        JwtExpiredError: Если срок действия token истёк.
        JwtInvalidClaimsError: Если claims token некорректны.
        JwtInvalidTokenTypeError: Если token имеет неожиданный тип.
        JwtTokenError: Если token недействителен или произошла ошибка
            декодирования.
    """

    app_settings = settings or get_settings()
    validate_jwt_settings(app_settings)
    normalized_token = validate_token_value(token)

    try:
        claims = jwt.decode(
            token=normalized_token,
            key=app_settings.security.secret_key,
            algorithms=[app_settings.security.jwt_algorithm],
            issuer=app_settings.security.jwt_issuer,
            audience=app_settings.security.jwt_audience,
            options={
                "verify_signature": True,
                "verify_exp": verify_expiration,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
                "require_sub": True,
                "require_exp": True,
                "require_iat": True,
                "require_nbf": True,
            },
        )
    except ExpiredSignatureError as exc:
        raise JwtExpiredError(cause=exc) from exc

    except JWTClaimsError as exc:
        raise JwtInvalidClaimsError(details={"reason": str(exc)}, cause=exc) from exc

    except JoseJWTError as exc:
        raise JwtTokenError(
            "JWT-токен недействителен.",
            code=JwtErrorCode.INVALID_TOKEN,
            details={"reason": str(exc)},
            cause=exc,
        ) from exc

    except Exception as exc:
        raise JwtTokenError(
            "При декодировании JWT-токена возникла непредвиденная ошибка.",
            code=JwtErrorCode.INVALID_TOKEN,
            details={"reason": str(exc), "error_type": exc.__class__.__name__},
            cause=exc,
        ) from exc

    payload = parse_jwt_payload(claims)

    if expected_type is not None:
        require_token_type(payload, expected_type)

    return payload


def decode_access_token(token: str, *, settings: Settings | None = None) -> JwtPayload:
    """Декодирует JWT token как access token.

    Args:
        token: Access JWT token.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        Декодированный payload access token.

    Raises:
        JwtExpiredError: Если срок действия token истёк.
        JwtInvalidClaimsError: Если claims token некорректны.
        JwtInvalidTokenTypeError: Если token не является access token.
        JwtTokenError: Если token недействителен.
    """

    return decode_token(token, expected_type="access", settings=settings)


def decode_refresh_token(token: str, *, settings: Settings | None = None) -> JwtPayload:
    """Декодирует JWT token как refresh token.

    Args:
        token: Refresh JWT token.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        Декодированный payload refresh token.

    Raises:
        JwtExpiredError: Если срок действия token истёк.
        JwtInvalidClaimsError: Если claims token некорректны.
        JwtInvalidTokenTypeError: Если token не является refresh token.
        JwtTokenError: Если token недействителен.
    """

    return decode_token(token, expected_type="refresh", settings=settings)


def parse_jwt_payload(claims: dict[str, Any]) -> JwtPayload:
    """Преобразует JWT claims в `JwtPayload`.

    Args:
        claims: Словарь claims, полученный после декодирования JWT.

    Returns:
        DTO `JwtPayload` с нормализованными claims.

    Raises:
        JwtInvalidClaimsError: Если claims не являются словарём или содержат
            некорректные значения.
        JwtTokenError: Если отсутствует обязательный subject или jti.
    """

    if not isinstance(claims, dict):
        raise JwtInvalidClaimsError(
            details={
                "reason": "claims_is_not_dict",
                "value_type": type(claims).__name__,
            }
        )

    require_claims(claims)

    subject = claims.get(JwtClaimName.SUBJECT.value)
    if not isinstance(subject, str) or not subject:
        raise JwtTokenError(
            "JWT-токен не содержит корректный subject.",
            code=JwtErrorCode.MISSING_SUBJECT,
            details={"subject": subject},
        )

    jti = claims.get(JwtClaimName.JWT_ID.value)
    if not isinstance(jti, str) or not jti:
        raise JwtTokenError(
            "JWT-токен не содержит корректный jti.",
            code=JwtErrorCode.MISSING_JTI,
            details={"jti": jti},
        )

    issuer = claims.get(JwtClaimName.ISSUER.value)
    audience = claims.get(JwtClaimName.AUDIENCE.value)

    if not isinstance(issuer, str) or not issuer:
        raise JwtInvalidClaimsError(details={"claim": JwtClaimName.ISSUER.value})

    if not isinstance(audience, str) or not audience:
        raise JwtInvalidClaimsError(details={"claim": JwtClaimName.AUDIENCE.value})

    return JwtPayload(
        subject=subject,
        token_type=normalize_token_type(claims.get(JwtClaimName.TOKEN_TYPE.value)),
        jti=jti,
        issued_at=claim_timestamp_to_datetime(
            claims.get(JwtClaimName.ISSUED_AT.value),
            claim_name=JwtClaimName.ISSUED_AT.value,
        ),
        not_before=claim_timestamp_to_datetime(
            claims.get(JwtClaimName.NOT_BEFORE.value),
            claim_name=JwtClaimName.NOT_BEFORE.value,
        ),
        expires_at=claim_timestamp_to_datetime(
            claims.get(JwtClaimName.EXPIRES_AT.value),
            claim_name=JwtClaimName.EXPIRES_AT.value,
        ),
        issuer=issuer,
        audience=audience,
        claims=dict(claims),
    )


def require_token_type(payload: JwtPayload, expected_type: JwtTokenType) -> None:
    """Проверяет, что JWT payload имеет ожидаемый тип token.

    Args:
        payload: JWT payload для проверки.
        expected_type: Ожидаемый тип token.

    Raises:
        JwtInvalidTokenTypeError: Если фактический тип token не совпадает с
            ожидаемым.
    """

    normalized_expected_type = normalize_token_type(expected_type)

    if payload.token_type != normalized_expected_type:
        raise JwtInvalidTokenTypeError(
            expected_type=normalized_expected_type,
            actual_type=payload.token_type,
        )


def get_token_subject(
    token: str,
    *,
    expected_type: JwtTokenType | None = None,
    settings: Settings | None = None,
) -> str:
    """Возвращает subject из JWT token.

    Args:
        token: JWT token.
        expected_type: Ожидаемый тип token. Если передан, token проверяется на
            соответствие этому типу.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        Subject JWT token.

    Raises:
        JwtTokenError: Если token недействителен или subject некорректен.
    """

    return decode_token(token, expected_type=expected_type, settings=settings).subject


def get_token_user_id(
    token: str,
    *,
    expected_type: JwtTokenType | None = None,
    settings: Settings | None = None,
) -> uuid.UUID:
    """Возвращает UUID пользователя из JWT token.

    Args:
        token: JWT token.
        expected_type: Ожидаемый тип token. Если передан, token проверяется на
            соответствие этому типу.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        UUID пользователя из JWT subject.

    Raises:
        JwtTokenError: Если token недействителен или subject не является
            корректным UUID.
    """

    return decode_token(token, expected_type=expected_type, settings=settings).user_id


def get_token_jti(
    token: str,
    *,
    expected_type: JwtTokenType | None = None,
    settings: Settings | None = None,
) -> str:
    """Возвращает JWT ID из token.

    Args:
        token: JWT token.
        expected_type: Ожидаемый тип token. Если передан, token проверяется на
            соответствие этому типу.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        Значение claim `jti`.

    Raises:
        JwtTokenError: Если token недействителен или jti отсутствует.
    """

    return decode_token(token, expected_type=expected_type, settings=settings).jti


def hash_token(token: str, *, settings: Settings | None = None) -> str:
    """Создаёт HMAC-SHA256 hash для JWT token.

    Args:
        token: JWT token, который нужно захешировать.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        Hex digest HMAC-SHA256 hash.

    Raises:
        JwtTokenError: Если token некорректен.
    """

    app_settings = settings or get_settings()
    normalized_token = validate_token_value(token)

    return hmac.new(
        key=app_settings.security.secret_key.encode("utf-8"),
        msg=normalized_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_token_hash(
    token: str,
    token_hash: str | None,
    *,
    settings: Settings | None = None,
) -> bool:
    """Проверяет соответствие JWT token и его hash.

    Args:
        token: JWT token.
        token_hash: Ожидаемый hash token.
        settings: Настройки приложения. Если не переданы, используются
            глобальные настройки через `get_settings()`.

    Returns:
        True, если hash соответствует token, иначе False.

    Raises:
        JwtTokenError: Если token некорректен.
    """

    if not isinstance(token_hash, str) or not token_hash:
        return False

    return hmac.compare_digest(hash_token(token, settings=settings), token_hash)


def generate_jti() -> str:
    """Генерирует уникальный JWT ID.

    Returns:
        Случайный UUID4 в hex-формате.
    """

    return uuid.uuid4().hex
