"""Юнит-тесты для проверки секретов (core/secret_validation.py)."""
from __future__ import annotations

import pytest

from core.config import (
    ApplicationSettings,
    CookieSettings,
    DatabaseSettings,
    SecuritySettings,
    Settings,
    StorageSettings,
)
from core.secret_validation import (
    find_insecure_secrets,
    validate_secrets_or_raise,
    warn_if_cookies_insecure,
)

_STRONG_SECRET = "a-strong-random-key-0123456789abcdef"
_STRONG_DB = "strong-db-password-xyz-123"
_STRONG_MINIO = "strong-minio-secret-xyz-123"


def make_settings(
    *,
    debug: bool = False,
    secret_key: str = _STRONG_SECRET,
    postgres_password: str = _STRONG_DB,
    minio_secret_key: str = _STRONG_MINIO,
    cookie_secure: bool = True,
) -> Settings:
    """Собирает Settings с заданными секретами без чтения локального .env."""
    return Settings(
        app=ApplicationSettings(_env_file=None, DEBUG=debug),
        security=SecuritySettings(_env_file=None, SECRET_KEY=secret_key),
        database=DatabaseSettings(_env_file=None, POSTGRES_PASSWORD=postgres_password),
        storage=StorageSettings(_env_file=None, MINIO_SECRET_KEY=minio_secret_key),
        cookies=CookieSettings(_env_file=None, COOKIE_SECURE=cookie_secure),
    )


class TestFindInsecureSecrets:
    def test_strong_secrets_are_clean(self) -> None:
        assert find_insecure_secrets(make_settings()) == []

    def test_change_me_marker_flagged(self) -> None:
        findings = find_insecure_secrets(
            make_settings(postgres_password="localcloud_change_me_in_production")
        )
        assert [f.field for f in findings] == ["POSTGRES_PASSWORD"]

    def test_development_secret_marker_flagged(self) -> None:
        findings = find_insecure_secrets(
            make_settings(
                secret_key="localcloud-development-secret-key-change-me"
            )
        )
        assert any(f.field == "SECRET_KEY" for f in findings)

    def test_minio_default_secret_flagged(self) -> None:
        findings = find_insecure_secrets(
            make_settings(minio_secret_key="localcloud_password")
        )
        assert [f.field for f in findings] == ["MINIO_SECRET_KEY"]

    def test_exact_localcloud_default_flagged(self) -> None:
        findings = find_insecure_secrets(
            make_settings(postgres_password="localcloud")
        )
        assert [f.field for f in findings] == ["POSTGRES_PASSWORD"]

    def test_blank_secret_flagged(self) -> None:
        findings = find_insecure_secrets(make_settings(secret_key="   "))
        assert any(f.field == "SECRET_KEY" for f in findings)

    def test_multiple_insecure_all_reported(self) -> None:
        findings = find_insecure_secrets(
            make_settings(
                secret_key="change-me",
                postgres_password="localcloud",
                minio_secret_key="localcloud_password",
            )
        )
        assert {f.field for f in findings} == {
            "SECRET_KEY",
            "POSTGRES_PASSWORD",
            "MINIO_SECRET_KEY",
        }

    def test_marker_is_case_insensitive(self) -> None:
        findings = find_insecure_secrets(
            make_settings(secret_key="CHANGE-ME-please")
        )
        assert any(f.field == "SECRET_KEY" for f in findings)


class TestValidateSecretsOrRaise:
    def test_clean_secrets_pass(self) -> None:
        validate_secrets_or_raise(make_settings())  # не бросает

    def test_insecure_in_production_raises(self) -> None:
        with pytest.raises(RuntimeError) as excinfo:
            validate_secrets_or_raise(
                make_settings(debug=False, postgres_password="localcloud")
            )
        assert "POSTGRES_PASSWORD" in str(excinfo.value)

    def test_insecure_in_debug_only_warns(self, caplog) -> None:
        # В debug небезопасные секреты допустимы — старт не падает.
        validate_secrets_or_raise(
            make_settings(debug=True, postgres_password="localcloud")
        )

    def test_error_lists_all_insecure_fields(self) -> None:
        with pytest.raises(RuntimeError) as excinfo:
            validate_secrets_or_raise(
                make_settings(
                    debug=False,
                    secret_key="change-me",
                    minio_secret_key="localcloud_password",
                )
            )
        message = str(excinfo.value)
        assert "SECRET_KEY" in message
        assert "MINIO_SECRET_KEY" in message


class TestWarnIfCookiesInsecure:
    def test_insecure_cookies_in_production_warns(self, caplog) -> None:
        import logging

        with caplog.at_level(logging.WARNING):
            warn_if_cookies_insecure(
                make_settings(debug=False, cookie_secure=False)
            )
        assert any("COOKIE_SECURE" in r.message for r in caplog.records)

    def test_secure_cookies_no_warning(self, caplog) -> None:
        import logging

        with caplog.at_level(logging.WARNING):
            warn_if_cookies_insecure(
                make_settings(debug=False, cookie_secure=True)
            )
        assert not any("COOKIE_SECURE" in r.message for r in caplog.records)

    def test_debug_suppresses_warning(self, caplog) -> None:
        import logging

        with caplog.at_level(logging.WARNING):
            warn_if_cookies_insecure(
                make_settings(debug=True, cookie_secure=False)
            )
        assert not any("COOKIE_SECURE" in r.message for r in caplog.records)

    def test_never_raises(self) -> None:
        # Это предупреждение, а не отказ старта — исключений быть не должно.
        warn_if_cookies_insecure(make_settings(debug=False, cookie_secure=False))
