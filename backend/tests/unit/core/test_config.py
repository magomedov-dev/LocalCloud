"""Тесты конфигурации: валидаторы настроек и вычисляемые поля."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import (
    ApplicationSettings,
    ArchiveSettings,
    DatabaseSettings,
    FeatureSettings,
    LoggingSettings,
    PreviewSettings,
    SecuritySettings,
    ServerSettings,
    Settings,
    StorageSettings,
    WorkerSettings,
    get_settings,
)
from core.constants import ApplicationConstants as APC
from core.constants import ArchiveConstants as ARC
from core.constants import FeatureConstants as FTC
from core.constants import PreviewConstants as PVC
from core.constants import SecurityConstants as SCC
from core.constants import ServerConstants as SVC
from core.constants import StorageConstants as STC


class TestApplicationSettings:
    def test_default_app_name(self) -> None:
        settings = ApplicationSettings()
        assert settings.app_name == APC.APP_NAME

    def test_default_api_prefix_has_slash(self) -> None:
        settings = ApplicationSettings()
        assert settings.api_prefix.startswith("/")

    def test_default_api_v1_prefix_has_slash(self) -> None:
        settings = ApplicationSettings()
        assert settings.api_v1_prefix.startswith("/")

    def test_ensure_leading_slash_adds_slash_to_api_prefix(self) -> None:
        value = ApplicationSettings.ensure_leading_slash("api")
        assert value == "/api"

    def test_ensure_leading_slash_keeps_existing_slash(self) -> None:
        value = ApplicationSettings.ensure_leading_slash("/api")
        assert value == "/api"

    def test_ensure_leading_slash_no_double_slash(self) -> None:
        value = ApplicationSettings.ensure_leading_slash("/api")
        assert not value.startswith("//")

    def test_ensure_leading_slash_empty_string_gets_slash(self) -> None:
        value = ApplicationSettings.ensure_leading_slash("")
        assert value == "/"

    def test_debug_default_is_false(self) -> None:
        settings = ApplicationSettings()
        assert settings.debug is False


class TestLoggingSettings:
    def test_normalize_log_level_uppercase(self) -> None:
        result = LoggingSettings.normalize_log_level("debug")
        assert result == "DEBUG"

    def test_normalize_log_level_already_uppercase(self) -> None:
        result = LoggingSettings.normalize_log_level("INFO")
        assert result == "INFO"

    def test_normalize_log_level_non_string_returned_unchanged(self) -> None:
        result = LoggingSettings.normalize_log_level(42)
        assert result == 42

    def test_default_log_level(self) -> None:
        settings = LoggingSettings()
        assert settings.log_level == "INFO"

    def test_log_json_accepts_bool(self) -> None:
        settings = LoggingSettings(LOG_JSON=False)
        assert settings.log_json is False
        settings_true = LoggingSettings(LOG_JSON=True)
        assert settings_true.log_json is True


class TestWorkerSettingsValidators:
    """Тесты валидаторов-классметодов WorkerSettings при прямом вызове."""

    def test_positive_interval_passes(self) -> None:
        assert WorkerSettings.validate_positive_intervals(1) == 1

    def test_positive_interval_large_value_passes(self) -> None:
        assert WorkerSettings.validate_positive_intervals(86400) == 86400

    def test_zero_interval_raises(self) -> None:
        with pytest.raises(ValueError, match="больше нуля"):
            WorkerSettings.validate_positive_intervals(0)

    def test_negative_interval_raises(self) -> None:
        with pytest.raises(ValueError):
            WorkerSettings.validate_positive_intervals(-1)

    def test_batch_size_one_passes(self) -> None:
        assert WorkerSettings.validate_batch_size(1) == 1

    def test_batch_size_100_passes(self) -> None:
        assert WorkerSettings.validate_batch_size(100) == 100

    def test_batch_size_50_passes(self) -> None:
        assert WorkerSettings.validate_batch_size(50) == 50

    def test_batch_size_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="от 1 до 100"):
            WorkerSettings.validate_batch_size(0)

    def test_batch_size_101_raises(self) -> None:
        with pytest.raises(ValueError, match="от 1 до 100"):
            WorkerSettings.validate_batch_size(101)

    def test_max_concurrent_tasks_one_passes(self) -> None:
        assert WorkerSettings.validate_max_concurrent_tasks(1) == 1

    def test_max_concurrent_tasks_32_passes(self) -> None:
        assert WorkerSettings.validate_max_concurrent_tasks(32) == 32

    def test_max_concurrent_tasks_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="от 1 до 32"):
            WorkerSettings.validate_max_concurrent_tasks(0)

    def test_max_concurrent_tasks_33_raises(self) -> None:
        with pytest.raises(ValueError, match="от 1 до 32"):
            WorkerSettings.validate_max_concurrent_tasks(33)

    def test_lock_ttl_30_passes(self) -> None:
        assert WorkerSettings.validate_lock_ttl(30) == 30

    def test_lock_ttl_300_passes(self) -> None:
        assert WorkerSettings.validate_lock_ttl(300) == 300

    def test_lock_ttl_29_raises(self) -> None:
        with pytest.raises(ValueError, match="30 секунд"):
            WorkerSettings.validate_lock_ttl(29)

    def test_lock_ttl_0_raises(self) -> None:
        with pytest.raises(ValueError):
            WorkerSettings.validate_lock_ttl(0)

    def test_retry_delay_one_passes(self) -> None:
        assert WorkerSettings.validate_retry_delay(1) == 1

    def test_retry_delay_60_passes(self) -> None:
        assert WorkerSettings.validate_retry_delay(60) == 60

    def test_retry_delay_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="больше нуля"):
            WorkerSettings.validate_retry_delay(0)

    def test_retry_delay_negative_raises(self) -> None:
        with pytest.raises(ValueError):
            WorkerSettings.validate_retry_delay(-5)


class TestWorkerSettingsCrossFieldValidation:
    def test_valid_defaults_pass(self) -> None:
        settings = WorkerSettings()
        assert settings.worker_stale_task_lock_seconds >= settings.worker_task_lock_ttl_seconds
        assert settings.worker_max_retry_delay_seconds >= settings.worker_retry_delay_seconds

    def test_stale_lock_less_than_ttl_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            WorkerSettings(
                WORKER_TASK_LOCK_TTL_SECONDS=300,
                WORKER_STALE_TASK_LOCK_SECONDS=100,
            )
        assert "stale" in str(exc_info.value).lower() or "lock" in str(exc_info.value).lower()

    def test_stale_lock_equal_to_ttl_passes(self) -> None:
        settings = WorkerSettings(
            WORKER_TASK_LOCK_TTL_SECONDS=300,
            WORKER_STALE_TASK_LOCK_SECONDS=300,
        )
        assert settings.worker_stale_task_lock_seconds == settings.worker_task_lock_ttl_seconds

    def test_max_retry_less_than_base_retry_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkerSettings(
                WORKER_RETRY_DELAY_SECONDS=120,
                WORKER_MAX_RETRY_DELAY_SECONDS=60,
            )

    def test_max_retry_equal_to_base_retry_passes(self) -> None:
        settings = WorkerSettings(
            WORKER_RETRY_DELAY_SECONDS=60,
            WORKER_MAX_RETRY_DELAY_SECONDS=60,
        )
        assert settings.worker_max_retry_delay_seconds == settings.worker_retry_delay_seconds


class TestStorageSettingsComputedFields:
    def _make(self, **kwargs: object) -> StorageSettings:
        defaults = dict(
            MINIO_HOST="minio-host",
            MINIO_PORT=9000,
            MINIO_PUBLIC_HOST="minio-public",
            MINIO_PUBLIC_PORT=9001,
            MINIO_SECURE=False,
            MINIO_REGION="us-east-1",
            MINIO_ACCESS_KEY="key",
            MINIO_SECRET_KEY="secret",
        )
        defaults.update(kwargs)
        return StorageSettings(**defaults)  # type: ignore[arg-type]

    def test_minio_endpoint_combines_host_and_port(self) -> None:
        settings = self._make(MINIO_HOST="myhost", MINIO_PORT=9000)
        assert settings.minio_endpoint == "myhost:9000"

    def test_minio_public_endpoint_combines_public_host_and_port(self) -> None:
        settings = self._make(MINIO_PUBLIC_HOST="pub", MINIO_PUBLIC_PORT=8080)
        assert settings.minio_public_endpoint == "pub:8080"

    def test_minio_scheme_is_http_when_not_secure(self) -> None:
        settings = self._make(MINIO_SECURE=False)
        assert settings.minio_scheme == "http"

    def test_minio_scheme_is_https_when_secure(self) -> None:
        settings = self._make(MINIO_SECURE=True)
        assert settings.minio_scheme == "https"

    def test_minio_base_url_format(self) -> None:
        settings = self._make(MINIO_HOST="minio-server", MINIO_PORT=9000, MINIO_SECURE=False)
        assert settings.minio_base_url == "http://minio-server:9000"

    def test_minio_base_url_https_when_secure(self) -> None:
        settings = self._make(MINIO_HOST="minio-server", MINIO_PORT=9000, MINIO_SECURE=True)
        assert settings.minio_base_url == "https://minio-server:9000"

    def test_minio_public_url_format(self) -> None:
        settings = self._make(MINIO_PUBLIC_HOST="public.minio", MINIO_PUBLIC_PORT=9001, MINIO_SECURE=False)
        assert settings.minio_public_url == "http://public.minio:9001"

    def test_minio_base_url_and_public_url_differ_when_hosts_differ(self) -> None:
        settings = self._make(
            MINIO_HOST="internal",
            MINIO_PORT=9000,
            MINIO_PUBLIC_HOST="external",
            MINIO_PUBLIC_PORT=9001,
            MINIO_SECURE=False,
        )
        assert settings.minio_base_url != settings.minio_public_url


class TestDatabaseSettingsComputedField:
    def test_database_url_uses_asyncpg_driver(self) -> None:
        settings = DatabaseSettings()
        assert "postgresql+asyncpg" in settings.database_url

    def test_database_url_contains_host(self) -> None:
        settings = DatabaseSettings(POSTGRES_HOST="db-server")
        assert "db-server" in settings.database_url

    def test_database_url_contains_port(self) -> None:
        settings = DatabaseSettings(POSTGRES_PORT=5433)
        assert "5433" in settings.database_url

    def test_database_url_contains_db_name(self) -> None:
        settings = DatabaseSettings(POSTGRES_DB="mydb")
        assert "mydb" in settings.database_url

    def test_database_url_contains_user(self) -> None:
        settings = DatabaseSettings(POSTGRES_USER="myuser")
        assert "myuser" in settings.database_url

    def test_database_url_format(self) -> None:
        settings = DatabaseSettings(
            POSTGRES_HOST="localhost",
            POSTGRES_PORT=5432,
            POSTGRES_USER="user",
            POSTGRES_PASSWORD="pass",
            POSTGRES_DB="db",
        )
        assert settings.database_url.startswith("postgresql+asyncpg://")
        assert "localhost" in settings.database_url
        assert "5432" in settings.database_url


class TestServerSettings:
    def test_defaults_match_constants(self) -> None:
        # _env_file=None: дефолты проверяются без локального .env разработчика.
        settings = ServerSettings(_env_file=None)
        assert settings.max_concurrent_requests == SVC.MAX_CONCURRENT_REQUESTS
        assert settings.request_timeout_seconds == SVC.REQUEST_TIMEOUT_SECONDS

    def test_env_override(self) -> None:
        settings = ServerSettings(
            MAX_CONCURRENT_REQUESTS=256,
            REQUEST_TIMEOUT_SECONDS=120.5,
        )
        assert settings.max_concurrent_requests == 256
        assert settings.request_timeout_seconds == 120.5

    def test_non_positive_concurrency_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ServerSettings(MAX_CONCURRENT_REQUESTS=0)

    def test_non_positive_timeout_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ServerSettings(REQUEST_TIMEOUT_SECONDS=0)


class TestPreviewSettings:
    def test_defaults_match_constants(self) -> None:
        # _env_file=None: дефолты проверяются без локального .env разработчика.
        settings = PreviewSettings(_env_file=None)
        assert settings.generation_enabled is PVC.GENERATION_ENABLED
        assert settings.render_concurrency == PVC.RENDER_CONCURRENCY
        assert settings.image_max_source_mb == PVC.IMAGE_MAX_SOURCE_MB
        assert settings.pdf_render_dpi == PVC.PDF_RENDER_DPI

    def test_byte_helpers_convert_megabytes(self) -> None:
        settings = PreviewSettings(
            PREVIEW_IMAGE_MAX_SOURCE_MB=10,
            PREVIEW_PDF_MAX_SOURCE_MB=20,
            PREVIEW_VIDEO_MAX_SOURCE_MB=30,
        )
        assert settings.image_max_source_bytes == 10 * 1024 * 1024
        assert settings.pdf_max_source_bytes == 20 * 1024 * 1024
        assert settings.video_max_source_bytes == 30 * 1024 * 1024

    def test_generation_can_be_disabled(self) -> None:
        settings = PreviewSettings(PREVIEW_GENERATION_ENABLED=False)
        assert settings.generation_enabled is False

    def test_render_concurrency_upper_bound_enforced(self) -> None:
        with pytest.raises(ValidationError):
            PreviewSettings(PREVIEW_RENDER_CONCURRENCY=17)

    def test_image_quality_bounds_enforced(self) -> None:
        with pytest.raises(ValidationError):
            PreviewSettings(PREVIEW_IMAGE_QUALITY=0)
        with pytest.raises(ValidationError):
            PreviewSettings(PREVIEW_IMAGE_QUALITY=101)


class TestArchiveSettings:
    def test_defaults_match_constants(self) -> None:
        # _env_file=None: дефолты проверяются без локального .env разработчика.
        settings = ArchiveSettings(_env_file=None)
        assert settings.max_files == ARC.MAX_FILES
        assert settings.max_total_mb == ARC.MAX_TOTAL_MB
        assert settings.stream_chunk_bytes == ARC.STREAM_CHUNK_BYTES
        assert settings.disk_safety_factor == ARC.DISK_SAFETY_FACTOR

    def test_max_total_bytes_helper(self) -> None:
        settings = ArchiveSettings(ARCHIVE_MAX_TOTAL_MB=4)
        assert settings.max_total_bytes == 4 * 1024 * 1024

    def test_env_override(self) -> None:
        settings = ArchiveSettings(
            ARCHIVE_MAX_FILES=50_000,
            ARCHIVE_DISK_SAFETY_FACTOR=1.5,
        )
        assert settings.max_files == 50_000
        assert settings.disk_safety_factor == 1.5

    def test_disk_safety_factor_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ArchiveSettings(ARCHIVE_DISK_SAFETY_FACTOR=0.9)


class TestFeatureSettings:
    def test_defaults_all_enabled(self) -> None:
        settings = FeatureSettings()
        assert settings.previews_enabled is FTC.PREVIEWS_ENABLED
        assert settings.file_viewer_enabled is FTC.FILE_VIEWER_ENABLED
        assert settings.media_playback_enabled is FTC.MEDIA_PLAYBACK_ENABLED
        assert settings.file_editing_enabled is FTC.FILE_EDITING_ENABLED

    def test_flags_can_be_disabled(self) -> None:
        settings = FeatureSettings(
            FEATURE_PREVIEWS_ENABLED=False,
            FEATURE_FILE_VIEWER_ENABLED=False,
            FEATURE_MEDIA_PLAYBACK_ENABLED=False,
            FEATURE_FILE_EDITING_ENABLED=False,
        )
        assert settings.previews_enabled is False
        assert settings.file_viewer_enabled is False
        assert settings.media_playback_enabled is False
        assert settings.file_editing_enabled is False


class TestStorageExecutorSetting:
    def test_default_matches_constant(self) -> None:
        # _env_file=None: дефолты проверяются без локального .env разработчика.
        settings = StorageSettings(_env_file=None)
        assert (
            settings.storage_executor_max_workers
            == STC.STORAGE_EXECUTOR_MAX_WORKERS
        )

    def test_env_override(self) -> None:
        settings = StorageSettings(STORAGE_EXECUTOR_MAX_WORKERS=8)
        assert settings.storage_executor_max_workers == 8

    def test_zero_workers_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StorageSettings(STORAGE_EXECUTOR_MAX_WORKERS=0)


class TestSettingsAggregate:
    def test_settings_has_all_sub_settings(self) -> None:
        settings = Settings()
        assert settings.app is not None
        assert settings.logging is not None
        assert settings.security is not None
        assert settings.cookies is not None
        assert settings.database is not None
        assert settings.storage is not None
        assert settings.workers is not None
        assert settings.server is not None
        assert settings.previews is not None
        assert settings.archives is not None
        assert settings.features is not None

    def test_sub_settings_are_correct_types(self) -> None:
        from core.config import (
            ApplicationSettings,
            CookieSettings,
            DatabaseSettings,
            LoggingSettings,
            SecuritySettings,
            StorageSettings,
            WorkerSettings,
        )
        settings = Settings()
        assert isinstance(settings.app, ApplicationSettings)
        assert isinstance(settings.logging, LoggingSettings)
        assert isinstance(settings.security, SecuritySettings)
        assert isinstance(settings.cookies, CookieSettings)
        assert isinstance(settings.database, DatabaseSettings)
        assert isinstance(settings.storage, StorageSettings)
        assert isinstance(settings.workers, WorkerSettings)
        assert isinstance(settings.server, ServerSettings)
        assert isinstance(settings.previews, PreviewSettings)
        assert isinstance(settings.archives, ArchiveSettings)
        assert isinstance(settings.features, FeatureSettings)


class TestSecuritySettings:
    def test_default_algorithm(self) -> None:
        settings = SecuritySettings()
        assert settings.jwt_algorithm == SCC.JWT_ALGORITHM

    def test_secret_key_is_non_empty_string(self) -> None:
        settings = SecuritySettings()
        assert isinstance(settings.secret_key, str)
        assert len(settings.secret_key) >= 16

    def test_default_access_expire_minutes_positive(self) -> None:
        settings = SecuritySettings()
        assert settings.access_token_expire_minutes > 0

    def test_default_refresh_expire_days_positive(self) -> None:
        settings = SecuritySettings()
        assert settings.refresh_token_expire_days > 0

    def test_custom_secret_key_stored(self) -> None:
        settings = SecuritySettings(SECRET_KEY="my-custom-secret-key-1234567890")
        assert settings.secret_key == "my-custom-secret-key-1234567890"


class TestGetSettings:
    def test_returns_settings_instance(self) -> None:
        # Очищаем lru_cache, чтобы строка создания объекта реально выполнилась.
        get_settings.cache_clear()
        try:
            result = get_settings()
            assert isinstance(result, Settings)
        finally:
            get_settings.cache_clear()

    def test_is_cached(self) -> None:
        get_settings.cache_clear()
        try:
            first = get_settings()
            second = get_settings()
            assert first is second
        finally:
            get_settings.cache_clear()


class TestSettingsProxy:
    def test_getattr_delegates_to_settings(self) -> None:
        from core.config import settings

        # Доступ к атрибуту прокси должен делегироваться реальному Settings.
        assert isinstance(settings.app, ApplicationSettings)

    def test_repr_delegates_to_settings(self) -> None:
        from core.config import settings

        assert "app=" in repr(settings) or "ApplicationSettings" in repr(settings)
