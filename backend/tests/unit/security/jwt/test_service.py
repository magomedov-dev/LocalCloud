"""Тесты сервиса JWT: создание, декодирование, хеширование и разбор токенов."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from core.config import Settings
from security.jwt.enums import JwtErrorCode
from security.jwt.exceptions import (
    JwtExpiredError,
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


class TestCreateAccessToken:
    def test_returns_non_empty_string(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_has_three_jwt_parts(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        assert token.count(".") == 2

    def test_decoded_type_is_access(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        payload = decode_access_token(token, settings=test_settings)
        assert payload.is_access_token

    def test_subject_matches_user_id(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(user_id, settings=test_settings)
        payload = decode_access_token(token, settings=test_settings)
        assert payload.user_id == user_id

    def test_string_subject_accepted(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(str(user_id), settings=test_settings)
        payload = decode_access_token(token, settings=test_settings)
        assert payload.user_id == user_id

    def test_custom_expiry_applied(self, test_settings: Settings) -> None:
        delta = timedelta(hours=2)
        before = datetime.now(UTC)
        token = create_access_token(uuid.uuid4(), expires_delta=delta, settings=test_settings)
        payload = decode_access_token(token, settings=test_settings)
        after = datetime.now(UTC)
        expected_min = before + delta - timedelta(seconds=5)
        expected_max = after + delta + timedelta(seconds=5)
        assert expected_min <= payload.expires_at <= expected_max

    def test_additional_claims_included(self, test_settings: Settings) -> None:
        token = create_access_token(
            uuid.uuid4(),
            additional_claims={"custom_field": "custom_value"},
            settings=test_settings,
        )
        payload = decode_access_token(token, settings=test_settings)
        assert payload.claims.get("custom_field") == "custom_value"

    def test_reserved_claims_not_overwritten_by_additional(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(
            user_id,
            additional_claims={"sub": "attacker", "type": "hacked"},
            settings=test_settings,
        )
        payload = decode_access_token(token, settings=test_settings)
        assert payload.user_id == user_id
        assert payload.is_access_token

    def test_different_calls_produce_different_tokens(self, test_settings: Settings) -> None:
        token1 = create_access_token(uuid.uuid4(), settings=test_settings)
        token2 = create_access_token(uuid.uuid4(), settings=test_settings)
        assert token1 != token2

    def test_issuer_matches_settings(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        payload = decode_access_token(token, settings=test_settings)
        assert payload.issuer == test_settings.security.jwt_issuer

    def test_audience_matches_settings(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        payload = decode_access_token(token, settings=test_settings)
        assert payload.audience == test_settings.security.jwt_audience


class TestCreateRefreshToken:
    def test_returns_non_empty_string(self, test_settings: Settings) -> None:
        token = create_refresh_token(uuid.uuid4(), settings=test_settings)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decoded_type_is_refresh(self, test_settings: Settings) -> None:
        token = create_refresh_token(uuid.uuid4(), settings=test_settings)
        payload = decode_refresh_token(token, settings=test_settings)
        assert payload.is_refresh_token

    def test_subject_matches_user_id(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token = create_refresh_token(user_id, settings=test_settings)
        payload = decode_refresh_token(token, settings=test_settings)
        assert payload.user_id == user_id

    def test_access_token_is_rejected_as_refresh(self, test_settings: Settings) -> None:
        access_token = create_access_token(uuid.uuid4(), settings=test_settings)
        with pytest.raises(JwtInvalidTokenTypeError):
            decode_refresh_token(access_token, settings=test_settings)

    def test_refresh_token_is_rejected_as_access(self, test_settings: Settings) -> None:
        refresh_token = create_refresh_token(uuid.uuid4(), settings=test_settings)
        with pytest.raises(JwtInvalidTokenTypeError):
            decode_access_token(refresh_token, settings=test_settings)


class TestCreateToken:
    def test_password_reset_token_type(self, test_settings: Settings) -> None:
        token = create_token(
            uuid.uuid4(),
            token_type="password_reset",
            expires_delta=timedelta(minutes=30),
            settings=test_settings,
        )
        payload = decode_token(token, expected_type="password_reset", settings=test_settings)
        assert payload.token_type == "password_reset"

    def test_custom_jti_used(self, test_settings: Settings) -> None:
        custom_jti = "my-custom-jti"
        token = create_token(
            uuid.uuid4(),
            token_type="access",
            expires_delta=timedelta(minutes=15),
            jti=custom_jti,
            settings=test_settings,
        )
        payload = decode_token(token, settings=test_settings)
        assert payload.jti == custom_jti

    def test_jti_auto_generated_when_not_provided(self, test_settings: Settings) -> None:
        token = create_token(
            uuid.uuid4(),
            token_type="access",
            expires_delta=timedelta(minutes=15),
            settings=test_settings,
        )
        payload = decode_token(token, settings=test_settings)
        assert payload.jti
        assert len(payload.jti) > 0

    def test_custom_issued_at_used(self, test_settings: Settings) -> None:
        # используем недавний прошлый iat, чтобы exp оставался в будущем
        custom_iat = datetime.now(UTC) - timedelta(minutes=5)
        token = create_token(
            uuid.uuid4(),
            token_type="access",
            expires_delta=timedelta(hours=1),
            issued_at=custom_iat,
            settings=test_settings,
        )
        payload = decode_token(token, settings=test_settings)
        # iat должен отличаться от custom_iat не более чем на 10 секунд
        diff = abs((payload.issued_at - custom_iat).total_seconds())
        assert diff < 10

    def test_empty_subject_raises(self, test_settings: Settings) -> None:
        with pytest.raises(JwtTokenError):
            create_token(
                "",
                token_type="access",
                expires_delta=timedelta(minutes=15),
                settings=test_settings,
            )

    def test_encode_failure_raises_jwt_token_error(self, test_settings: Settings) -> None:
        from unittest.mock import patch

        with patch(
            "security.jwt.service.jwt.encode",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(JwtTokenError):
                create_token(
                    uuid.uuid4(),
                    token_type="access",
                    expires_delta=timedelta(minutes=15),
                    settings=test_settings,
                )


class TestDecodeTokenErrorMapping:
    def test_jwt_claims_error_maps_to_invalid_claims_error(
        self, test_settings: Settings
    ) -> None:
        from unittest.mock import patch

        from jose.exceptions import JWTClaimsError

        from security.jwt.exceptions import JwtInvalidClaimsError

        token = create_access_token(uuid.uuid4(), settings=test_settings)
        with patch(
            "security.jwt.service.jwt.decode",
            side_effect=JWTClaimsError("bad audience"),
        ):
            with pytest.raises(JwtInvalidClaimsError):
                decode_token(token, settings=test_settings)

    def test_unexpected_exception_maps_to_jwt_token_error(
        self, test_settings: Settings
    ) -> None:
        from unittest.mock import patch

        token = create_access_token(uuid.uuid4(), settings=test_settings)
        with patch(
            "security.jwt.service.jwt.decode",
            side_effect=RuntimeError("unexpected"),
        ):
            with pytest.raises(JwtTokenError):
                decode_token(token, settings=test_settings)


class TestDecodeToken:
    def test_decode_valid_token_returns_payload(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(user_id, settings=test_settings)
        payload = decode_token(token, settings=test_settings)
        assert payload.user_id == user_id

    def test_decode_with_wrong_expected_type_raises(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        with pytest.raises(JwtInvalidTokenTypeError):
            decode_token(token, expected_type="refresh", settings=test_settings)

    def test_decode_expired_token_raises_jwt_expired_error(self, test_settings: Settings) -> None:
        # iat=2 часа назад, exp=1 час назад — корректно сформированный просроченный токен
        past_iat = datetime.now(UTC) - timedelta(hours=2)
        token = create_token(
            uuid.uuid4(),
            token_type="access",
            expires_delta=timedelta(hours=1),
            issued_at=past_iat,
            settings=test_settings,
        )
        with pytest.raises(JwtExpiredError):
            decode_token(token, settings=test_settings)

    def test_decode_invalid_string_raises_jwt_token_error(self, test_settings: Settings) -> None:
        with pytest.raises(JwtTokenError):
            decode_token("not.a.valid.jwt.token", settings=test_settings)

    def test_decode_empty_string_raises_jwt_token_error(self, test_settings: Settings) -> None:
        with pytest.raises(JwtTokenError):
            decode_token("", settings=test_settings)

    def test_decode_tampered_token_raises(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        parts = token.split(".")
        parts[1] = parts[1][::-1]  # переворачиваем байты payload
        tampered = ".".join(parts)
        with pytest.raises(JwtTokenError):
            decode_token(tampered, settings=test_settings)

    def test_token_signed_with_wrong_key_rejected(self, test_settings: Settings) -> None:
        from core.config import SecuritySettings, Settings as S
        wrong_key_settings = S(
            security=SecuritySettings(
                SECRET_KEY="different-secret-key-not-matching!",
                JWT_ALGORITHM="HS256",
                JWT_ISSUER=test_settings.security.jwt_issuer,
                JWT_AUDIENCE=test_settings.security.jwt_audience,
            )
        )
        token = create_access_token(uuid.uuid4(), settings=wrong_key_settings)
        with pytest.raises(JwtTokenError):
            decode_token(token, settings=test_settings)


class TestHashToken:
    def test_returns_non_empty_hex_string(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        h = hash_token(token, settings=test_settings)
        assert isinstance(h, str)
        assert len(h) == 64  # hex-дайджест SHA-256
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_token_always_same_hash(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        h1 = hash_token(token, settings=test_settings)
        h2 = hash_token(token, settings=test_settings)
        assert h1 == h2

    def test_different_tokens_different_hashes(self, test_settings: Settings) -> None:
        t1 = create_access_token(uuid.uuid4(), settings=test_settings)
        t2 = create_access_token(uuid.uuid4(), settings=test_settings)
        assert hash_token(t1, settings=test_settings) != hash_token(t2, settings=test_settings)

    def test_empty_token_raises(self, test_settings: Settings) -> None:
        with pytest.raises(JwtTokenError):
            hash_token("", settings=test_settings)


class TestVerifyTokenHash:
    def test_correct_hash_returns_true(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        token_hash = hash_token(token, settings=test_settings)
        assert verify_token_hash(token, token_hash, settings=test_settings) is True

    def test_wrong_hash_returns_false(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        assert verify_token_hash(token, "a" * 64, settings=test_settings) is False

    def test_none_hash_returns_false(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        assert verify_token_hash(token, None, settings=test_settings) is False  # type: ignore[arg-type]

    def test_empty_hash_returns_false(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        assert verify_token_hash(token, "", settings=test_settings) is False

    def test_different_tokens_hashes_not_interchangeable(self, test_settings: Settings) -> None:
        t1 = create_access_token(uuid.uuid4(), settings=test_settings)
        t2 = create_access_token(uuid.uuid4(), settings=test_settings)
        h2 = hash_token(t2, settings=test_settings)
        assert verify_token_hash(t1, h2, settings=test_settings) is False


class TestGenerateJti:
    def test_returns_non_empty_string(self) -> None:
        jti = generate_jti()
        assert isinstance(jti, str)
        assert len(jti) > 0

    def test_generates_unique_values(self) -> None:
        jtis = {generate_jti() for _ in range(100)}
        assert len(jtis) == 100

    def test_returns_hex_string(self) -> None:
        jti = generate_jti()
        assert all(c in "0123456789abcdef" for c in jti)


class TestParseJwtPayload:
    def test_valid_claims_returns_payload(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(user_id, settings=test_settings)
        payload = decode_access_token(token, settings=test_settings)
        assert payload.user_id == user_id

    def test_non_dict_raises_invalid_claims_error(self) -> None:
        from security.jwt.exceptions import JwtInvalidClaimsError
        with pytest.raises(JwtInvalidClaimsError):
            parse_jwt_payload("not a dict")  # type: ignore[arg-type]

    def test_missing_subject_raises_jwt_token_error(self) -> None:
        from datetime import UTC, datetime
        now = datetime.now(UTC).timestamp()
        claims = {
            "jti": "some-jti",
            "iat": now,
            "nbf": now,
            "exp": now + 900,
            "iss": "issuer",
            "aud": "audience",
            "type": "access",
        }
        with pytest.raises(JwtTokenError):
            parse_jwt_payload(claims)

    @staticmethod
    def _base_claims() -> dict:
        from datetime import UTC, datetime
        now = datetime.now(UTC).timestamp()
        return {
            "sub": str(uuid.uuid4()),
            "jti": "some-jti",
            "iat": now,
            "nbf": now,
            "exp": now + 900,
            "iss": "issuer",
            "aud": "audience",
            "type": "access",
        }

    def test_missing_jti_raises_invalid_claims_error(self) -> None:
        from security.jwt.exceptions import JwtInvalidClaimsError
        claims = self._base_claims()
        del claims["jti"]
        # require_claims срабатывает первым и отмечает отсутствующий jti
        with pytest.raises(JwtInvalidClaimsError):
            parse_jwt_payload(claims)

    def test_empty_jti_raises_jwt_token_error(self) -> None:
        claims = self._base_claims()
        # присутствует, но пустой -> проходит require_claims, но не проходит проверку значения jti
        claims["jti"] = ""
        with pytest.raises(JwtTokenError):
            parse_jwt_payload(claims)

    def test_missing_issuer_raises_invalid_claims_error(self) -> None:
        from security.jwt.exceptions import JwtInvalidClaimsError
        claims = self._base_claims()
        claims["iss"] = ""
        with pytest.raises(JwtInvalidClaimsError):
            parse_jwt_payload(claims)

    def test_missing_audience_raises_invalid_claims_error(self) -> None:
        from security.jwt.exceptions import JwtInvalidClaimsError
        claims = self._base_claims()
        claims["aud"] = ""
        with pytest.raises(JwtInvalidClaimsError):
            parse_jwt_payload(claims)


class TestRequireTokenType:
    def test_matching_type_does_not_raise(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        payload = decode_token(token, settings=test_settings)
        require_token_type(payload, "access")  # без исключения

    def test_mismatched_type_raises_invalid_token_type_error(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        payload = decode_token(token, settings=test_settings)
        with pytest.raises(JwtInvalidTokenTypeError):
            require_token_type(payload, "refresh")


class TestHelperFunctions:
    def test_get_token_subject_returns_subject_string(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(user_id, settings=test_settings)
        assert get_token_subject(token, settings=test_settings) == str(user_id)

    def test_get_token_user_id_returns_uuid(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token = create_access_token(user_id, settings=test_settings)
        assert get_token_user_id(token, settings=test_settings) == user_id

    def test_get_token_jti_returns_jti(self, test_settings: Settings) -> None:
        custom_jti = "my-test-jti-value"
        token = create_token(
            uuid.uuid4(),
            token_type="access",
            expires_delta=timedelta(minutes=15),
            jti=custom_jti,
            settings=test_settings,
        )
        assert get_token_jti(token, settings=test_settings) == custom_jti

    def test_get_token_subject_with_wrong_expected_type_raises(self, test_settings: Settings) -> None:
        token = create_access_token(uuid.uuid4(), settings=test_settings)
        with pytest.raises(JwtInvalidTokenTypeError):
            get_token_subject(token, expected_type="refresh", settings=test_settings)
