from __future__ import annotations

from security.jwt.dto import JwtPayload
from security.jwt.enums import (
    SUPPORTED_JWT_TOKEN_TYPES,
    JwtClaimName,
    JwtErrorCode,
    JwtTokenType,
)
from security.jwt.exceptions import (
    JwtExpiredError,
    JwtInvalidClaimsError,
    JwtInvalidTokenTypeError,
    JwtTokenError,
)
from security.jwt.service import (
    create_access_token,
    create_refresh_token,
    create_token,
    decode_access_token,
    decode_refresh_token,
    decode_token,
    generate_jti,
    get_token_jti,
    get_token_subject,
    get_token_user_id,
    hash_token,
    parse_jwt_payload,
    require_token_type,
    verify_token_hash,
)
from security.jwt.validators import (
    claim_timestamp_to_datetime,
    normalize_datetime,
    normalize_subject,
    normalize_token_type,
    validate_jwt_settings,
    validate_token_value,
)

__all__ = [
    "JwtTokenType",
    "JwtClaimName",
    "JwtErrorCode",
    "JwtTokenError",
    "JwtExpiredError",
    "JwtInvalidClaimsError",
    "JwtInvalidTokenTypeError",
    "JwtPayload",
    "SUPPORTED_JWT_TOKEN_TYPES",
    "create_access_token",
    "create_refresh_token",
    "create_token",
    "decode_token",
    "decode_access_token",
    "decode_refresh_token",
    "parse_jwt_payload",
    "require_token_type",
    "get_token_subject",
    "get_token_user_id",
    "get_token_jti",
    "hash_token",
    "verify_token_hash",
    "generate_jti",
    "normalize_subject",
    "normalize_token_type",
    "validate_token_value",
    "validate_jwt_settings",
    "normalize_datetime",
    "claim_timestamp_to_datetime",
]
