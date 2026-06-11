from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import cast

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from core.constants import ENV_FILE, LoggingLevels
from core.constants import ApplicationConstants as APC
from core.constants import ArchiveConstants as ARC
from core.constants import CookieConstants as CKC
from core.constants import DatabaseConstants as DTC
from core.constants import FeatureConstants as FTC
from core.constants import LoggingConstants as LGC
from core.constants import PreviewConstants as PVC
from core.constants import SecurityConstants as SCC
from core.constants import ServerConstants as SVC
from core.constants import StorageConstants as STC
from core.constants import WorkerConstants as WRC


class ApplicationSettings(BaseSettings):
    """Настройки приложения.

    Описывает базовые параметры backend-приложения: название, версию,
    описание, режим debug и API-префиксы. Значения могут быть переопределены
    через переменные окружения или файл `.env`.

    Attributes:
        app_name: Название приложения.
        app_version: Версия приложения.
        app_description: Описание приложения.
        debug: Признак запуска приложения в debug-режиме.
        api_prefix: Общий префикс API.
        api_v1_prefix: Префикс API версии 1.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = Field(default=APC.APP_NAME, alias="APP_NAME")
    app_version: str = Field(default=APC.APP_VERSION, alias="APP_VERSION")
    app_description: str = Field(default=APC.APP_DESCRIPTION, alias="APP_DESCRIPTION")
    debug: bool = Field(default=APC.DEBUG, alias="DEBUG")
    api_prefix: str = Field(default=APC.API_PREFIX, alias="API_PREFIX")
    api_v1_prefix: str = Field(default=APC.API_V1_PREFIX, alias="API_V1_PREFIX")

    @field_validator("api_prefix", "api_v1_prefix")
    @classmethod
    def ensure_leading_slash(cls, value: str) -> str:
        """Добавляет ведущий слеш к API-префиксу.

        Нормализует значения `api_prefix` и `api_v1_prefix`, чтобы они всегда
        начинались с символа `/`. Если слеш уже присутствует, значение
        возвращается без изменений.

        Args:
            value: Исходное значение API-префикса.

        Returns:
            API-префикс с ведущим слешем.
        """

        if not value.startswith("/"):
            return f"/{value}"
        return value


class LoggingSettings(BaseSettings):
    """Настройки логирования.

    Описывает уровень логирования, формат вывода логов и параметры записи
    логов в файл. Значения могут быть переопределены через переменные окружения
    или файл `.env`.

    Attributes:
        log_level: Уровень логирования приложения.
        log_json: Признак вывода логов в JSON-формате.
        log_file_enabled: Признак включения записи логов в файл.
        log_file_path: Путь к файлу логов.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    log_level: LoggingLevels = Field(
        default=LGC.LOG_LEVEL,
        alias="LOG_LEVEL",
    )
    log_json: bool = Field(default=LGC.LOG_JSON, alias="LOG_JSON")
    log_file_enabled: bool = Field(
        default=LGC.LOG_FILE_ENABLED,
        alias="LOG_FILE_ENABLED",
    )
    log_file_path: Path = Field(default=LGC.LOG_FILE_PATH, alias="LOG_FILE_PATH")

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        """Нормализует уровень логирования.

        Приводит строковое значение уровня логирования из переменных окружения
        к верхнему регистру, чтобы оно соответствовало допустимым значениям
        перечисления уровней логирования.

        Args:
            value: Исходное значение уровня логирования.

        Returns:
            Нормализованное значение уровня логирования.
        """

        if isinstance(value, str):
            return value.upper()
        return value


class SecuritySettings(BaseSettings):
    """Настройки безопасности и JWT.

    Описывает параметры подписи и проверки JWT-токенов, сроки действия access
    и refresh токенов, а также схему хеширования паролей. Значения могут быть
    переопределены через переменные окружения или файл `.env`.

    Attributes:
        secret_key: Секретный ключ для криптографических операций.
        jwt_algorithm: Алгоритм подписи JWT-токенов.
        jwt_issuer: Ожидаемый issuer JWT-токенов.
        jwt_audience: Ожидаемая audience JWT-токенов.
        access_token_expire_minutes: Время жизни access-токена в минутах.
        refresh_token_expire_days: Время жизни refresh-токена в днях.
        password_hash_scheme: Схема хеширования паролей.
        public_link_password_max_attempts: Число неверных паролей публичной
            ссылки до временной блокировки проверок пароля.
        public_link_password_lockout_seconds: Длительность блокировки проверок
            пароля публичной ссылки после исчерпания попыток.
        rate_limit_auth_attempts: Число запросов к чувствительным auth-точкам
            с одного IP за окно.
        rate_limit_auth_window_seconds: Размер окна лимита auth-запросов.
        rate_limit_public_access_attempts: Число проверок доступа к публичным
            ссылкам с одного IP за окно.
        rate_limit_public_access_window_seconds: Размер окна лимита проверок
            публичных ссылок.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    secret_key: str = Field(default=SCC.SECRET_KEY, alias="SECRET_KEY")
    jwt_algorithm: str = Field(default=SCC.JWT_ALGORITHM, alias="JWT_ALGORITHM")
    jwt_issuer: str = Field(default=SCC.JWT_ISSUER, alias="JWT_ISSUER")
    jwt_audience: str = Field(default=SCC.JWT_AUDIENCE, alias="JWT_AUDIENCE")
    access_token_expire_minutes: int = Field(
        default=SCC.ACCESS_TOKEN_EXPIRE_MINUTES,
        alias="ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    refresh_token_expire_days: int = Field(
        default=SCC.REFRESH_TOKEN_EXPIRE_DAYS,
        alias="REFRESH_TOKEN_EXPIRE_DAYS",
    )
    password_hash_scheme: str = Field(
        default=SCC.PASSWORD_HASH_SCHEME,
        alias="PASSWORD_HASH_SCHEME",
    )
    public_link_password_max_attempts: int = Field(
        default=SCC.PUBLIC_LINK_PASSWORD_MAX_ATTEMPTS,
        ge=1,
        le=100,
        alias="PUBLIC_LINK_PASSWORD_MAX_ATTEMPTS",
    )
    public_link_password_lockout_seconds: int = Field(
        default=SCC.PUBLIC_LINK_PASSWORD_LOCKOUT_SECONDS,
        ge=1,
        alias="PUBLIC_LINK_PASSWORD_LOCKOUT_SECONDS",
    )
    rate_limit_auth_attempts: int = Field(
        default=SCC.RATE_LIMIT_AUTH_ATTEMPTS,
        ge=1,
        alias="RATE_LIMIT_AUTH_ATTEMPTS",
    )
    rate_limit_auth_window_seconds: int = Field(
        default=SCC.RATE_LIMIT_AUTH_WINDOW_SECONDS,
        ge=1,
        alias="RATE_LIMIT_AUTH_WINDOW_SECONDS",
    )
    rate_limit_public_access_attempts: int = Field(
        default=SCC.RATE_LIMIT_PUBLIC_ACCESS_ATTEMPTS,
        ge=1,
        alias="RATE_LIMIT_PUBLIC_ACCESS_ATTEMPTS",
    )
    rate_limit_public_access_window_seconds: int = Field(
        default=SCC.RATE_LIMIT_PUBLIC_ACCESS_WINDOW_SECONDS,
        ge=1,
        alias="RATE_LIMIT_PUBLIC_ACCESS_WINDOW_SECONDS",
    )


class CookieSettings(BaseSettings):
    """Настройки auth cookie.

    Описывает имена cookie для access и refresh токенов, а также параметры
    безопасности cookie: `secure`, `httponly`, `samesite`, домен и путь.
    Значения могут быть переопределены через переменные окружения или файл
    `.env`.

    Attributes:
        access_cookie_name: Имя cookie для access-токена.
        refresh_cookie_name: Имя cookie для refresh-токена.
        cookie_secure: Признак передачи cookie только по HTTPS.
        cookie_httponly: Признак запрета доступа к cookie из JavaScript.
        cookie_samesite: Политика SameSite для auth-cookie.
        cookie_domain: Домен cookie или `None`, если домен не задан.
        cookie_path: Путь cookie.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    access_cookie_name: str = Field(
        default=CKC.ACCESS_COOKIE_NAME,
        alias="ACCESS_COOKIE_NAME",
    )
    refresh_cookie_name: str = Field(
        default=CKC.REFRESH_COOKIE_NAME,
        alias="REFRESH_COOKIE_NAME",
    )
    cookie_secure: bool = Field(default=CKC.COOKIE_SECURE, alias="COOKIE_SECURE")
    cookie_httponly: bool = Field(
        default=CKC.COOKIE_HTTPONLY,
        alias="COOKIE_HTTPONLY",
    )
    cookie_samesite: str = Field(default=CKC.COOKIE_SAMESITE, alias="COOKIE_SAMESITE")
    cookie_domain: str | None = Field(
        default=CKC.COOKIE_DOMAIN,
        alias="COOKIE_DOMAIN",
    )
    cookie_path: str = Field(default=CKC.COOKIE_PATH, alias="COOKIE_PATH")


class DatabaseSettings(BaseSettings):
    """Настройки базы данных.

    Описывает параметры подключения к PostgreSQL: хост, порт, учетные данные,
    имя базы данных, режим echo и параметры пула подключений. Также формирует
    итоговый SQLAlchemy URL для подключения.

    Attributes:
        postgres_host: Хост PostgreSQL.
        postgres_port: Порт PostgreSQL.
        postgres_user: Имя пользователя PostgreSQL.
        postgres_password: Пароль пользователя PostgreSQL.
        postgres_db: Имя базы данных PostgreSQL.
        postgres_echo: Признак вывода SQL-запросов в лог.
        postgres_pool_size: Базовый размер пула подключений.
        postgres_max_overflow: Максимальное число дополнительных подключений
            сверх базового размера пула.
        postgres_pool_timeout: Таймаут ожидания подключения из пула в секундах.
        postgres_pool_recycle: Время переработки подключения в секундах.
        postgres_pool_pre_ping: Признак проверки подключения перед
            использованием.
        database_url: SQLAlchemy URL для подключения к PostgreSQL.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    postgres_host: str = Field(default=DTC.POSTGRES_HOST, alias="POSTGRES_HOST")
    postgres_port: int = Field(default=DTC.POSTGRES_PORT, alias="POSTGRES_PORT")
    postgres_user: str = Field(default=DTC.POSTGRES_USER, alias="POSTGRES_USER")
    postgres_password: str = Field(
        default=DTC.POSTGRES_PASSWORD,
        alias="POSTGRES_PASSWORD",
    )
    postgres_db: str = Field(default=DTC.POSTGRES_DB, alias="POSTGRES_DB")
    postgres_echo: bool = Field(default=DTC.POSTGRES_ECHO, alias="POSTGRES_ECHO")
    postgres_pool_size: int = Field(
        default=DTC.POSTGRES_POOL_SIZE,
        alias="POSTGRES_POOL_SIZE",
    )
    postgres_max_overflow: int = Field(
        default=DTC.POSTGRES_MAX_OVERFLOW,
        alias="POSTGRES_MAX_OVERFLOW",
    )
    postgres_pool_timeout: int = Field(
        default=DTC.POSTGRES_POOL_TIMEOUT,
        alias="POSTGRES_POOL_TIMEOUT",
    )
    postgres_pool_recycle: int = Field(
        default=DTC.POSTGRES_POOL_RECYCLE,
        alias="POSTGRES_POOL_RECYCLE",
    )
    postgres_pool_pre_ping: bool = Field(
        default=DTC.POSTGRES_POOL_PRE_PING,
        alias="POSTGRES_POOL_PRE_PING",
    )

    @computed_field
    @property
    def database_url(self) -> str:
        """Формирует SQLAlchemy URL для подключения к PostgreSQL.

        Returns:
            Строка подключения к PostgreSQL в формате SQLAlchemy URL.
        """

        return URL.create(
            drivername=DTC.POSTGRES_DRIVER,
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(
            hide_password=False,
        )


class StorageSettings(BaseSettings):
    """Настройки объектного хранилища MinIO/S3.

    Описывает параметры подключения к MinIO, включая внутренний и публичный
    endpoint, учетные данные, регион и HTTP-схему. Также предоставляет
    вычисляемые URL для SDK и внешнего доступа.

    Attributes:
        minio_host: Внутренний хост MinIO.
        minio_port: Внутренний порт MinIO.
        minio_public_host: Публичный хост MinIO.
        minio_public_port: Публичный порт MinIO.
        minio_access_key: Access key для MinIO.
        minio_secret_key: Secret key для MinIO.
        minio_secure: Признак использования HTTPS при подключении к MinIO.
        minio_region: Регион S3-хранилища.
        minio_endpoint: Внутренний endpoint MinIO для SDK.
        minio_public_endpoint: Публичный endpoint MinIO.
        minio_scheme: HTTP-схема подключения к MinIO.
        minio_base_url: Базовый внутренний URL MinIO.
        minio_public_url: Публичный URL MinIO.
        storage_capacity_bytes: Явно заданная общая ёмкость пула хранилища
            в байтах. Если не задана, пул определяется автоматически как доля
            от физической ёмкости диска, которую видит MinIO.
        storage_executor_max_workers: Размер пула потоков для блокирующего
            MinIO SDK.
        minio_connect_timeout_seconds: Таймаут установки TCP-соединения с MinIO.
        minio_read_timeout_seconds: Таймаут ожидания данных на каждое чтение
            из сокета MinIO (не суммарное время передачи файла).
        storage_startup_timeout_seconds: Потолок ожидания готовности хранилища
            на старте приложения.
        incomplete_multipart_expiry_days: Через сколько дней MinIO авто-абортит
            незавершённые multipart-загрузки (0 — правило не ставится).
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    minio_host: str = Field(default=STC.MINIO_HOST, alias="MINIO_HOST")
    minio_port: int = Field(default=STC.MINIO_PORT, alias="MINIO_PORT")
    minio_public_host: str = Field(
        default=STC.MINIO_PUBLIC_HOST,
        alias="MINIO_PUBLIC_HOST",
    )
    minio_public_port: int = Field(
        default=STC.MINIO_PUBLIC_PORT,
        alias="MINIO_PUBLIC_PORT",
    )
    minio_access_key: str = Field(
        default=STC.MINIO_ACCESS_KEY,
        alias="MINIO_ACCESS_KEY",
    )
    minio_secret_key: str = Field(
        default=STC.MINIO_SECRET_KEY,
        alias="MINIO_SECRET_KEY",
    )
    minio_secure: bool = Field(default=STC.MINIO_SECURE, alias="MINIO_SECURE")
    minio_region: str = Field(default=STC.MINIO_REGION, alias="MINIO_REGION")
    storage_capacity_bytes: int | None = Field(
        default=None,
        ge=0,
        alias="STORAGE_CAPACITY_BYTES",
    )
    storage_executor_max_workers: int = Field(
        default=STC.STORAGE_EXECUTOR_MAX_WORKERS,
        ge=1,
        le=64,
        alias="STORAGE_EXECUTOR_MAX_WORKERS",
    )
    minio_connect_timeout_seconds: float = Field(
        default=STC.MINIO_CONNECT_TIMEOUT_SECONDS,
        gt=0,
        alias="MINIO_CONNECT_TIMEOUT_SECONDS",
    )
    minio_read_timeout_seconds: float = Field(
        default=STC.MINIO_READ_TIMEOUT_SECONDS,
        gt=0,
        alias="MINIO_READ_TIMEOUT_SECONDS",
    )
    storage_startup_timeout_seconds: float = Field(
        default=STC.STORAGE_STARTUP_TIMEOUT_SECONDS,
        gt=0,
        alias="STORAGE_STARTUP_TIMEOUT_SECONDS",
    )
    incomplete_multipart_expiry_days: int = Field(
        default=STC.INCOMPLETE_MULTIPART_EXPIRY_DAYS,
        ge=0,
        alias="INCOMPLETE_MULTIPART_EXPIRY_DAYS",
    )

    @computed_field
    @property
    def minio_endpoint(self) -> str:
        """Возвращает внутренний endpoint MinIO для SDK.

        Returns:
            Endpoint в формате `host:port`.
        """

        return f"{self.minio_host}:{self.minio_port}"

    @computed_field
    @property
    def minio_public_endpoint(self) -> str:
        """Возвращает публичный endpoint MinIO.

        Returns:
            Публичный endpoint в формате `host:port`.
        """

        return f"{self.minio_public_host}:{self.minio_public_port}"

    @computed_field
    @property
    def minio_scheme(self) -> str:
        """Возвращает HTTP-схему подключения к MinIO.

        Returns:
            Строка `https`, если включен secure-режим, иначе `http`.
        """

        return "https" if self.minio_secure else "http"

    @computed_field
    @property
    def minio_base_url(self) -> str:
        """Возвращает базовый внутренний URL MinIO.

        Returns:
            Внутренний URL MinIO со схемой и endpoint.
        """

        return f"{self.minio_scheme}://{self.minio_endpoint}"

    @computed_field
    @property
    def minio_public_url(self) -> str:
        """Возвращает публичный URL MinIO.

        Returns:
            Публичный URL MinIO со схемой и endpoint.
        """

        return f"{self.minio_scheme}://{self.minio_public_endpoint}"


class WorkerSettings(BaseSettings):
    """Настройки worker-процесса LocalCloud.

    Описывает параметры запуска фонового worker-процесса, интервалы опроса
    очереди, ограничения параллельной обработки задач, настройки блокировок,
    retry-механизма, scheduler-задач и batch-обработки.

    Attributes:
        worker_enabled: Признак включения worker-процесса.
        worker_name: Имя worker-процесса или `None`, если имя не задано.
        worker_poll_interval_seconds: Интервал опроса очереди задач в секундах.
        worker_idle_sleep_seconds: Пауза при отсутствии задач в секундах.
        worker_batch_size: Размер batch-а задач для обработки.
        worker_max_concurrent_tasks: Максимальное число задач, выполняемых
            одновременно.
        worker_shutdown_timeout_seconds: Таймаут завершения worker-процесса
            в секундах.
        worker_task_lock_ttl_seconds: TTL блокировки задачи в секундах.
        worker_stale_task_lock_seconds: Возраст блокировки, после которого она
            считается устаревшей, в секундах.
        worker_retry_delay_seconds: Начальная задержка повторной попытки
            в секундах.
        worker_max_retry_delay_seconds: Максимальная задержка повторной попытки
            в секундах.
        worker_scheduler_enabled: Признак включения scheduler-задач.
        worker_clean_trash_interval_seconds: Интервал очистки корзины
            в секундах.
        worker_clean_expired_uploads_interval_seconds: Интервал очистки
            истекших загрузок в секундах.
        worker_clean_expired_public_links_interval_seconds: Интервал очистки
            истекших публичных ссылок в секундах.
        worker_recalculate_quotas_interval_seconds: Интервал пересчета квот
            в секундах.
        worker_storage_integrity_interval_seconds: Интервал проверки
            целостности хранилища в секундах.
        worker_cleanup_batch_size: Размер batch-а для задач очистки.
        worker_integrity_batch_size: Размер batch-а для проверки целостности.
        worker_quota_batch_size: Размер batch-а для пересчета квот.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    worker_enabled: bool = Field(default=True, alias="WORKER_ENABLED")
    worker_name: str | None = Field(default=None, alias="WORKER_NAME")
    worker_poll_interval_seconds: int = Field(
        default=WRC.WORKER_POLL_INTERVAL_SECONDS,
        alias="WORKER_POLL_INTERVAL_SECONDS",
    )
    worker_idle_sleep_seconds: int = Field(
        default=WRC.WORKER_IDLE_SLEEP_SECONDS,
        alias="WORKER_IDLE_SLEEP_SECONDS",
    )
    worker_batch_size: int = Field(
        default=WRC.WORKER_BATCH_SIZE,
        alias="WORKER_BATCH_SIZE",
    )
    worker_max_concurrent_tasks: int = Field(
        default=WRC.WORKER_MAX_CONCURRENT_TASKS,
        alias="WORKER_MAX_CONCURRENT_TASKS",
    )
    worker_shutdown_timeout_seconds: int = Field(
        default=WRC.WORKER_SHUTDOWN_TIMEOUT_SECONDS,
        alias="WORKER_SHUTDOWN_TIMEOUT_SECONDS",
    )
    worker_task_lock_ttl_seconds: int = Field(
        default=WRC.WORKER_TASK_LOCK_TTL_SECONDS,
        alias="WORKER_TASK_LOCK_TTL_SECONDS",
    )
    worker_stale_task_lock_seconds: int = Field(
        default=WRC.WORKER_STALE_TASK_LOCK_SECONDS,
        alias="WORKER_STALE_TASK_LOCK_SECONDS",
    )
    worker_retry_delay_seconds: int = Field(
        default=WRC.WORKER_RETRY_DELAY_SECONDS,
        alias="WORKER_RETRY_DELAY_SECONDS",
    )
    worker_max_retry_delay_seconds: int = Field(
        default=WRC.WORKER_MAX_RETRY_DELAY_SECONDS,
        alias="WORKER_MAX_RETRY_DELAY_SECONDS",
    )
    worker_scheduler_enabled: bool = Field(
        default=True, alias="WORKER_SCHEDULER_ENABLED"
    )
    worker_clean_trash_interval_seconds: int = Field(
        default=WRC.CLEAN_TRASH_INTERVAL_SECONDS,
        alias="WORKER_CLEAN_TRASH_INTERVAL_SECONDS",
    )
    worker_clean_expired_uploads_interval_seconds: int = Field(
        default=WRC.CLEAN_EXPIRED_UPLOADS_INTERVAL_SECONDS,
        alias="WORKER_CLEAN_EXPIRED_UPLOADS_INTERVAL_SECONDS",
    )
    worker_clean_expired_public_links_interval_seconds: int = Field(
        default=WRC.CLEAN_EXPIRED_PUBLIC_LINKS_INTERVAL_SECONDS,
        alias="WORKER_CLEAN_EXPIRED_PUBLIC_LINKS_INTERVAL_SECONDS",
    )
    worker_recalculate_quotas_interval_seconds: int = Field(
        default=WRC.RECALCULATE_QUOTAS_INTERVAL_SECONDS,
        alias="WORKER_RECALCULATE_QUOTAS_INTERVAL_SECONDS",
    )
    worker_storage_integrity_interval_seconds: int = Field(
        default=WRC.CHECK_STORAGE_INTEGRITY_INTERVAL_SECONDS,
        alias="WORKER_STORAGE_INTEGRITY_INTERVAL_SECONDS",
    )
    worker_cleanup_batch_size: int = Field(
        default=WRC.CLEANUP_BATCH_SIZE,
        alias="WORKER_CLEANUP_BATCH_SIZE",
    )
    worker_integrity_batch_size: int = Field(
        default=WRC.INTEGRITY_BATCH_SIZE,
        alias="WORKER_INTEGRITY_BATCH_SIZE",
    )
    worker_quota_batch_size: int = Field(
        default=WRC.QUOTA_BATCH_SIZE,
        alias="WORKER_QUOTA_BATCH_SIZE",
    )

    @field_validator(
        "worker_poll_interval_seconds",
        "worker_idle_sleep_seconds",
        "worker_shutdown_timeout_seconds",
        "worker_clean_trash_interval_seconds",
        "worker_clean_expired_uploads_interval_seconds",
        "worker_clean_expired_public_links_interval_seconds",
        "worker_recalculate_quotas_interval_seconds",
        "worker_storage_integrity_interval_seconds",
        mode="after",
    )
    @classmethod
    def validate_positive_intervals(cls, value: int) -> int:
        """Проверяет, что значение интервала больше нуля.

        Args:
            value: Проверяемое значение интервала.

        Returns:
            Проверенное значение интервала.

        Raises:
            ValueError: Если значение меньше или равно нулю.
        """

        if value <= 0:
            raise ValueError("Значение интервала должно быть больше нуля.")
        return value

    @field_validator(
        "worker_batch_size",
        "worker_cleanup_batch_size",
        "worker_integrity_batch_size",
        "worker_quota_batch_size",
        mode="after",
    )
    @classmethod
    def validate_batch_size(cls, value: int) -> int:
        """Проверяет размер batch-а.

        Args:
            value: Проверяемый размер batch-а.

        Returns:
            Проверенный размер batch-а.

        Raises:
            ValueError: Если размер batch-а не входит в диапазон от 1 до 100.
        """

        if value < 1 or value > 100:
            raise ValueError("Размер batch должен быть в диапазоне от 1 до 100.")
        return value

    @field_validator("worker_max_concurrent_tasks", mode="after")
    @classmethod
    def validate_max_concurrent_tasks(cls, value: int) -> int:
        """Проверяет число параллельных задач.

        Args:
            value: Проверяемое число параллельных задач.

        Returns:
            Проверенное число параллельных задач.

        Raises:
            ValueError: Если число задач не входит в диапазон от 1 до 32.
        """

        if value < 1 or value > 32:
            raise ValueError(
                "Количество параллельных задач должно быть в диапазоне от 1 до 32."
            )
        return value

    @field_validator("worker_task_lock_ttl_seconds", mode="after")
    @classmethod
    def validate_lock_ttl(cls, value: int) -> int:
        """Проверяет TTL блокировки задач.

        Args:
            value: Проверяемый TTL блокировки в секундах.

        Returns:
            Проверенный TTL блокировки.

        Raises:
            ValueError: Если TTL меньше 30 секунд.
        """

        if value < 30:
            raise ValueError("TTL блокировки задачи должен быть не меньше 30 секунд.")
        return value

    @field_validator("worker_retry_delay_seconds", mode="after")
    @classmethod
    def validate_retry_delay(cls, value: int) -> int:
        """Проверяет базовую задержку повторной попытки.

        Args:
            value: Проверяемая задержка retry в секундах.

        Returns:
            Проверенная задержка retry.

        Raises:
            ValueError: Если задержка меньше или равна нулю.
        """

        if value <= 0:
            raise ValueError("Задержка повторной попытки должна быть больше нуля.")
        return value

    @model_validator(mode="after")
    def validate_cross_fields(self) -> WorkerSettings:
        """Проверяет согласованность взаимосвязанных настроек worker-а.

        Сравнивает TTL блокировки со временем stale-блокировки, а также базовую
        задержку retry с максимальной задержкой retry.

        Returns:
            Текущий экземпляр настроек worker-а.

        Raises:
            ValueError: Если stale-блокировка меньше TTL блокировки задачи.
            ValueError: Если максимальная задержка retry меньше базовой.
        """

        if self.worker_stale_task_lock_seconds < self.worker_task_lock_ttl_seconds:
            raise ValueError(
                "Время stale-блокировки должно быть не меньше TTL блокировки задачи."
            )
        if self.worker_max_retry_delay_seconds < self.worker_retry_delay_seconds:
            raise ValueError(
                "Максимальная задержка retry должна быть не меньше базовой задержки retry."
            )
        return self


class ServerSettings(BaseSettings):
    """Настройки обработки HTTP-запросов (backpressure и таймауты).

    Описывает потолок одновременно обрабатываемых запросов и таймаут фазы
    формирования ответа. Параметры влияют на потребление памяти, число
    одновременных подключений к БД и устойчивость хоста под пиковой нагрузкой.
    Значения по умолчанию подобраны под маленький хост и переопределяются
    через переменные окружения или `.env`.

    Attributes:
        max_concurrent_requests: Потолок одновременно обрабатываемых запросов,
            сверх которого backpressure отдаёт 503.
        request_timeout_seconds: Таймаут фазы формирования ответа в секундах,
            после которого отдаётся 504.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    max_concurrent_requests: int = Field(
        default=SVC.MAX_CONCURRENT_REQUESTS,
        ge=1,
        alias="MAX_CONCURRENT_REQUESTS",
    )
    request_timeout_seconds: float = Field(
        default=SVC.REQUEST_TIMEOUT_SECONDS,
        gt=0,
        alias="REQUEST_TIMEOUT_SECONDS",
    )


class PreviewSettings(BaseSettings):
    """Настройки генерации preview-миниатюр.

    Описывает мастер-флаг генерации, параллелизм тяжёлых рендеров, лимиты
    исходного размера (защита памяти и от «decompression bomb»), параметры
    растрирования PDF, размеры/качество растров изображений и таймаут ffmpeg.
    Значения по умолчанию подобраны под маленький хост (1 ГБ ОЗУ) и
    переопределяются через переменные окружения или `.env`.

    Attributes:
        generation_enabled: Мастер-флаг генерации превью. Если выключен,
            worker помечает файлы `NOT_REQUIRED` и не тратит RAM/CPU.
        render_concurrency: Максимальное число одновременных тяжёлых рендеров.
        image_max_source_mb: Лимит исходного размера изображения в мегабайтах.
        pdf_max_source_mb: Лимит исходного размера PDF в мегабайтах.
        video_max_source_mb: Лимит исходного размера видео в мегабайтах.
        image_max_dimension: Потолок длинной стороны растра превью изображения.
        image_quality: Качество WebP-превью изображения (1–100).
        image_max_pixels: Глобальный предел Pillow на число пикселей растра.
        pdf_render_dpi: DPI растрирования первой страницы PDF.
        pdf_render_max_dim: Потолок длинной стороны растра PDF в пикселях.
        video_ffmpeg_timeout_seconds: Таймаут вызова ffmpeg в секундах.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    generation_enabled: bool = Field(
        default=PVC.GENERATION_ENABLED,
        alias="PREVIEW_GENERATION_ENABLED",
    )
    render_concurrency: int = Field(
        default=PVC.RENDER_CONCURRENCY,
        ge=1,
        le=16,
        alias="PREVIEW_RENDER_CONCURRENCY",
    )
    image_max_source_mb: int = Field(
        default=PVC.IMAGE_MAX_SOURCE_MB,
        ge=1,
        alias="PREVIEW_IMAGE_MAX_SOURCE_MB",
    )
    pdf_max_source_mb: int = Field(
        default=PVC.PDF_MAX_SOURCE_MB,
        ge=1,
        alias="PREVIEW_PDF_MAX_SOURCE_MB",
    )
    video_max_source_mb: int = Field(
        default=PVC.VIDEO_MAX_SOURCE_MB,
        ge=1,
        alias="PREVIEW_VIDEO_MAX_SOURCE_MB",
    )
    image_max_dimension: int = Field(
        default=PVC.IMAGE_MAX_DIMENSION,
        ge=16,
        alias="PREVIEW_IMAGE_MAX_DIMENSION",
    )
    image_quality: int = Field(
        default=PVC.IMAGE_QUALITY,
        ge=1,
        le=100,
        alias="PREVIEW_IMAGE_QUALITY",
    )
    image_max_pixels: int = Field(
        default=PVC.IMAGE_MAX_PIXELS,
        ge=1,
        alias="PREVIEW_IMAGE_MAX_PIXELS",
    )
    pdf_render_dpi: int = Field(
        default=PVC.PDF_RENDER_DPI,
        ge=36,
        le=600,
        alias="PREVIEW_PDF_RENDER_DPI",
    )
    pdf_render_max_dim: int = Field(
        default=PVC.PDF_RENDER_MAX_DIM,
        ge=64,
        alias="PREVIEW_PDF_RENDER_MAX_DIM",
    )
    video_ffmpeg_timeout_seconds: int = Field(
        default=PVC.VIDEO_FFMPEG_TIMEOUT_SECONDS,
        ge=1,
        alias="PREVIEW_VIDEO_FFMPEG_TIMEOUT_SECONDS",
    )

    @computed_field
    @property
    def image_max_source_bytes(self) -> int:
        """Возвращает лимит исходного размера изображения в байтах."""

        return self.image_max_source_mb * 1024 * 1024

    @computed_field
    @property
    def pdf_max_source_bytes(self) -> int:
        """Возвращает лимит исходного размера PDF в байтах."""

        return self.pdf_max_source_mb * 1024 * 1024

    @computed_field
    @property
    def video_max_source_bytes(self) -> int:
        """Возвращает лимит исходного размера видео в байтах."""

        return self.video_max_source_mb * 1024 * 1024


class ArchiveSettings(BaseSettings):
    """Настройки фоновой сборки ZIP-архивов.

    Описывает лимиты архива и параметры потокового копирования объектов в ZIP.
    Нужны, чтобы сборка архива не выела диск под временный файл и не загрузила
    в память слишком большой список записей. Значения по умолчанию подобраны
    под маленький хост и переопределяются через переменные окружения или `.env`.

    Attributes:
        max_files: Максимальное число файлов в одном архиве.
        max_total_mb: Максимальный суммарный размер источников в мегабайтах.
        stream_chunk_bytes: Размер блока потоковой передачи объекта в ZIP.
        disk_safety_factor: Множитель запаса свободного места на диске
            относительно суммарного размера источников.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    max_files: int = Field(
        default=ARC.MAX_FILES,
        ge=1,
        alias="ARCHIVE_MAX_FILES",
    )
    max_total_mb: int = Field(
        default=ARC.MAX_TOTAL_MB,
        ge=1,
        alias="ARCHIVE_MAX_TOTAL_MB",
    )
    stream_chunk_bytes: int = Field(
        default=ARC.STREAM_CHUNK_BYTES,
        ge=4096,
        alias="ARCHIVE_STREAM_CHUNK_BYTES",
    )
    disk_safety_factor: float = Field(
        default=ARC.DISK_SAFETY_FACTOR,
        ge=1.0,
        alias="ARCHIVE_DISK_SAFETY_FACTOR",
    )

    @computed_field
    @property
    def max_total_bytes(self) -> int:
        """Возвращает максимальный суммарный размер источников в байтах."""

        return self.max_total_mb * 1024 * 1024


class FeatureSettings(BaseSettings):
    """Флаги функциональности приложения.

    Описывают возможности, которые имеет смысл отключать на слабых серверах
    или в ограниченных развёртываниях. Флаги отдаются фронтенду через
    публичный endpoint конфигурации и управляют отображением превью,
    просмотром, проигрыванием и редактированием файлов. Переопределяются
    через переменные окружения или `.env`.

    Attributes:
        previews_enabled: Показывать ли в UI preview-миниатюры файлов.
        file_viewer_enabled: Доступен ли просмотр содержимого файлов в UI.
        media_playback_enabled: Доступно ли проигрывание аудио/видео в UI.
        file_editing_enabled: Доступно ли редактирование текстовых файлов в UI.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    previews_enabled: bool = Field(
        default=FTC.PREVIEWS_ENABLED,
        alias="FEATURE_PREVIEWS_ENABLED",
    )
    file_viewer_enabled: bool = Field(
        default=FTC.FILE_VIEWER_ENABLED,
        alias="FEATURE_FILE_VIEWER_ENABLED",
    )
    media_playback_enabled: bool = Field(
        default=FTC.MEDIA_PLAYBACK_ENABLED,
        alias="FEATURE_MEDIA_PLAYBACK_ENABLED",
    )
    file_editing_enabled: bool = Field(
        default=FTC.FILE_EDITING_ENABLED,
        alias="FEATURE_FILE_EDITING_ENABLED",
    )


class Settings(BaseModel):
    """Общие настройки приложения.

    Агрегирует настройки всех основных подсистем backend-приложения:
    приложения, логирования, безопасности, cookie, базы данных, объектного
    хранилища, worker-процессов, обработки запросов, генерации превью,
    архивов и флагов функциональности.

    Attributes:
        app: Настройки приложения.
        logging: Настройки логирования.
        security: Настройки безопасности и JWT.
        cookies: Настройки auth-cookie.
        database: Настройки подключения к базе данных.
        storage: Настройки объектного хранилища.
        workers: Настройки worker-процессов.
        server: Настройки обработки HTTP-запросов (backpressure и таймауты).
        previews: Настройки генерации preview-миниатюр.
        archives: Настройки фоновой сборки ZIP-архивов.
        features: Флаги функциональности приложения.
    """

    app: ApplicationSettings = Field(default_factory=ApplicationSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    cookies: CookieSettings = Field(default_factory=CookieSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    workers: WorkerSettings = Field(default_factory=WorkerSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    previews: PreviewSettings = Field(default_factory=PreviewSettings)
    archives: ArchiveSettings = Field(default_factory=ArchiveSettings)
    features: FeatureSettings = Field(default_factory=FeatureSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает кэшированный экземпляр настроек.

    Создаёт объект `Settings` при первом вызове и переиспользует его при
    последующих обращениях. Это предотвращает повторное чтение переменных
    окружения и файла `.env` в рамках одного процесса приложения.

    Returns:
        Кэшированный экземпляр общих настроек приложения.
    """

    return Settings()


class _SettingsProxy:
    """Ленивый proxy для безопасного импорта настроек.

    Позволяет использовать импорт вида `from core import settings` без
    немедленного создания объекта настроек на этапе импорта модуля. Реальный
    объект настроек создаётся только при обращении к атрибутам proxy.

    Methods:
        __getattr__: Делегирует доступ к атрибутам объекту `Settings`.
        __repr__: Возвращает строковое представление текущих настроек.
    """

    def __getattr__(self, name: str) -> object:
        """Возвращает атрибут текущих настроек.

        Делегирует получение атрибута объекту, возвращаемому `get_settings`.

        Args:
            name: Имя запрашиваемого атрибута настроек.

        Returns:
            Значение атрибута текущих настроек.

        Raises:
            AttributeError: Если запрашиваемый атрибут отсутствует
                в объекте настроек.
        """

        return getattr(get_settings(), name)

    def __repr__(self) -> str:
        """Возвращает строковое представление текущих настроек.

        Returns:
            Строковое представление объекта `Settings`.
        """

        return repr(get_settings())


settings = cast(Settings, _SettingsProxy())
