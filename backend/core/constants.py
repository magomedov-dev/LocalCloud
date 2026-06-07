from __future__ import annotations

from pathlib import Path
from re import Pattern, compile
from typing import Final, Literal

# Бюджет подключений на один процесс. Каждый API-worker и фоновый worker
# используют собственный пул, поэтому реальное число подключений в кластере:
#
#     (api_workers + worker_procs) * (POOL_SIZE + MAX_OVERFLOW)
#
# PostgreSQL должен поддерживать это число плюс запас для superuser- и
# maintenance-подключений:
#
#     max_connections >= (api_workers + worker_procs) * (POOL_SIZE + MAX_OVERFLOW) + 10
#
# Фиксированные умеренные значения по умолчанию (15 подключений на процесс)
# позволяют небольшому развертыванию на 5–10 пользователей оставаться в рамках
# стандартного PostgreSQL max_connections=100. Например: 4 API-worker + 1
# фоновый worker = 5 * 15 = 75 + 10 = 85 < 100. Старые значения, масштабируемые
# от CPU, могли превышать 100 уже при ~3 процессах. Для конкретного окружения
# переопределяйте значения через переменные POSTGRES_POOL_SIZE и
# POSTGRES_MAX_OVERFLOW.
DEFAULT_POOL_SIZE: Final[int] = 10
DEFAULT_MAX_OVERFLOW: Final[int] = 5


# Единственный источник конфигурации: `.env` в корне репозитория.
# Все классы Settings загружают этот файл. Путь приводится к абсолютному, чтобы
# он работал независимо от рабочей директории процесса.
ENV_FILE: Final[Path] = Path(__file__).resolve().parents[2] / ".env"


class ApplicationConstants:
    """Константы приложения.

    Хранит базовые значения конфигурации backend-приложения: название,
    версию, описание, режим debug и API-префиксы.

    Attributes:
        APP_NAME: Название приложения.
        APP_VERSION: Версия приложения.
        APP_DESCRIPTION: Описание приложения.
        DEBUG: Признак запуска приложения в debug-режиме.
        API_PREFIX: Общий префикс API.
        API_V1_PREFIX: Префикс API версии 1.
    """

    APP_NAME: Final[str] = "LocalCloud"
    APP_VERSION: Final[str] = "0.1.0"
    APP_DESCRIPTION: Final[str] = "Веб-приложение для персонального хранения файлов"
    DEBUG: Final[bool] = False
    API_PREFIX: Final[str] = "/api"
    API_V1_PREFIX: Final[str] = "/api/v1"


# Допустимые уровни логирования.
LoggingLevels = Literal[
    "NOTSET", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"
]


class LoggingConstants:
    """Константы логирования.

    Хранит значения по умолчанию для настройки логирования приложения:
    уровень логирования, формат вывода, параметры записи в файл и список
    шумных логгеров, уровень которых можно приглушать.

    Attributes:
        LOG_LEVEL: Уровень логирования по умолчанию.
        LOG_JSON: Признак вывода логов в JSON-формате.
        LOG_FILE_ENABLED: Признак включения записи логов в файл.
        LOG_FILE_PATH: Путь к файлу логов.
        DEFAULT_NOISY_LOGGERS: Имена логгеров, которые можно приглушать
            при настройке логирования.
    """

    LOG_LEVEL: Final[LoggingLevels] = "INFO"
    LOG_JSON: Final[bool] = False
    LOG_FILE_ENABLED: Final[bool] = False
    LOG_FILE_PATH: Final[Path] = Path("logs/localcloud.log")
    DEFAULT_NOISY_LOGGERS: Final[tuple[str, ...]] = ("asyncio",)


class SecurityConstants:
    """Константы безопасности приложения.

    Хранит значения по умолчанию для криптографических и JWT-настроек,
    включая секретный ключ, алгоритм подписи, issuer, audience, сроки жизни
    токенов и схему хеширования паролей.

    Attributes:
        SECRET_KEY: Секретный ключ для криптографических операций.
        JWT_ALGORITHM: Алгоритм подписи JWT-токенов.
        JWT_ISSUER: Issuer JWT-токенов.
        JWT_AUDIENCE: Audience JWT-токенов.
        ACCESS_TOKEN_EXPIRE_MINUTES: Время жизни access-токена в минутах.
        REFRESH_TOKEN_EXPIRE_DAYS: Время жизни refresh-токена в днях.
        PASSWORD_HASH_SCHEME: Схема хеширования паролей.
    """

    SECRET_KEY: Final[str] = "localcloud-development-secret-key-change-me"
    JWT_ALGORITHM: Final[str] = "HS256"
    JWT_ISSUER: Final[str] = "localcloud"
    JWT_AUDIENCE: Final[str] = "localcloud-users"
    ACCESS_TOKEN_EXPIRE_MINUTES: Final[int] = 15
    REFRESH_TOKEN_EXPIRE_DAYS: Final[int] = 30
    PASSWORD_HASH_SCHEME: Final[str] = "bcrypt"


class CookieConstants:
    """Константы auth-cookie.

    Хранит значения по умолчанию для cookie, используемых при хранении
    access- и refresh-токенов, а также параметры безопасности cookie.

    Attributes:
        ACCESS_COOKIE_NAME: Имя cookie для access-токена.
        REFRESH_COOKIE_NAME: Имя cookie для refresh-токена.
        COOKIE_SECURE: Признак передачи cookie только по HTTPS.
        COOKIE_HTTPONLY: Признак запрета доступа к cookie из JavaScript.
        COOKIE_SAMESITE: Политика SameSite для auth-cookie.
        COOKIE_DOMAIN: Домен cookie или `None`, если домен не задан.
        COOKIE_PATH: Путь cookie.
    """

    ACCESS_COOKIE_NAME: Final[str] = "localcloud_access"
    REFRESH_COOKIE_NAME: Final[str] = "localcloud_refresh"
    COOKIE_SECURE: Final[bool] = False
    COOKIE_HTTPONLY: Final[bool] = True
    COOKIE_SAMESITE: Final[str] = "lax"
    COOKIE_DOMAIN: Final[str | None] = None
    COOKIE_PATH: Final[str] = "/"


class DatabaseConstants:
    """Константы подключения к PostgreSQL.

    Хранит значения по умолчанию для драйвера, адреса, учетных данных,
    имени базы данных и параметров пула подключений.

    Attributes:
        POSTGRES_DRIVER: SQLAlchemy-драйвер PostgreSQL.
        POSTGRES_HOST: Хост PostgreSQL.
        POSTGRES_PORT: Порт PostgreSQL.
        POSTGRES_USER: Имя пользователя PostgreSQL.
        POSTGRES_PASSWORD: Пароль пользователя PostgreSQL.
        POSTGRES_DB: Имя базы данных PostgreSQL.
        POSTGRES_ECHO: Признак вывода SQL-запросов в лог.
        POSTGRES_POOL_SIZE: Базовый размер пула подключений.
        POSTGRES_MAX_OVERFLOW: Максимальное число дополнительных подключений
            сверх базового размера пула.
        POSTGRES_POOL_TIMEOUT: Таймаут ожидания подключения из пула в секундах.
        POSTGRES_POOL_RECYCLE: Время переработки подключения в секундах.
        POSTGRES_POOL_PRE_PING: Признак проверки подключения перед
            использованием.
    """

    POSTGRES_DRIVER: Final[str] = "postgresql+asyncpg"
    POSTGRES_HOST: Final[str] = "localhost"
    POSTGRES_PORT: Final[int] = 5432
    POSTGRES_USER: Final[str] = "localcloud"
    POSTGRES_PASSWORD: Final[str] = "localcloud"
    POSTGRES_DB: Final[str] = "localcloud"
    POSTGRES_ECHO: Final[bool] = False
    POSTGRES_POOL_SIZE: Final[int] = DEFAULT_POOL_SIZE
    POSTGRES_MAX_OVERFLOW: Final[int] = DEFAULT_MAX_OVERFLOW
    POSTGRES_POOL_TIMEOUT: Final[int] = 30
    POSTGRES_POOL_RECYCLE: Final[int] = 1800
    POSTGRES_POOL_PRE_PING: Final[bool] = True


class StorageConstants:
    """Константы S3-совместимого хранилища MinIO.

    Хранит значения по умолчанию для подключения к MinIO, имен bucket-ов,
    health-check-объектов, лимитов multipart-загрузки, presigned URL,
    пользовательской metadata, имен файлов и регулярных выражений валидации.

    Attributes:
        MINIO_HOST: Внутренний хост MinIO.
        MINIO_PORT: Внутренний порт MinIO.
        MINIO_PUBLIC_HOST: Публичный хост MinIO.
        MINIO_PUBLIC_PORT: Публичный порт MinIO.
        MINIO_ACCESS_KEY: Access key для MinIO.
        MINIO_SECRET_KEY: Secret key для MinIO.
        MINIO_SECURE: Признак использования HTTPS при подключении к MinIO.
        MINIO_REGION: Регион S3-хранилища.
        MINIO_BUCKET_FILES: Bucket для пользовательских файлов.
        MINIO_BUCKET_TEMP: Bucket для временных объектов.
        MINIO_BUCKET_ARCHIVES: Bucket для архивов.
        STORAGE_HEALTHCHECK_OBJECT_PREFIX: Префикс health-check-объекта.
        STORAGE_HEALTHCHECK_OBJECT_CONTENT_TYPE: Content-Type health-check-объекта.
        STORAGE_HEALTHCHECK_OBJECT_PAYLOAD: Содержимое health-check-объекта.
        MULTIPART_MAX_PARTS: Максимальное число частей multipart-загрузки.
        S3_BUCKET_NAME_MIN_LENGTH: Минимальная длина имени bucket-а.
        S3_BUCKET_NAME_MAX_LENGTH: Максимальная длина имени bucket-а.
        S3_OBJECT_KEY_MAX_LENGTH: Максимальная длина object key.
        S3_MULTIPART_MIN_PART_NUMBER: Минимальный номер части multipart-загрузки.
        STORAGE_EXTENSION_MAX_LENGTH: Максимальная длина расширения файла.
        STORAGE_METADATA_KEY_MAX_LENGTH: Максимальная длина ключа metadata.
        S3_MULTIPART_MIN_PART_SIZE_BYTES: Минимальный размер части
            multipart-загрузки в байтах.
        S3_MULTIPART_MAX_PART_NUMBER: Максимальный номер части multipart-загрузки.
        S3_PRESIGNED_MIN_EXPIRES_IN_SECONDS: Минимальный срок действия
            presigned URL в секундах.
        STORAGE_METADATA_VALUE_MAX_LENGTH: Максимальная длина значения metadata.
        PRESIGNED_UPLOAD_EXPIRE_SECONDS: Срок действия presigned URL для загрузки.
        STORAGE_METADATA_TOTAL_MAX_SIZE: Максимальный общий размер metadata.
        STORAGE_FILENAME_METADATA_MAX_LENGTH: Максимальная длина имени файла
            в metadata.
        PRESIGNED_DOWNLOAD_EXPIRE_SECONDS: Срок действия presigned URL
            для скачивания.
        MULTIPART_PART_SIZE_BYTES: Размер части multipart-загрузки по умолчанию.
        STORAGE_DEFAULT_LATENCY_THRESHOLD_MS: Порог задержки хранилища
            по умолчанию в миллисекундах.
        STORAGE_DEFAULT_CHECKSUM_CHUNK_SIZE: Размер блока для вычисления checksum.
        S3_PRESIGNED_MAX_EXPIRES_IN_SECONDS: Максимальный срок действия
            presigned URL в секундах.
        S3_MULTIPART_MIN_NON_LAST_PART_SIZE_BYTES: Минимальный размер
            непоследней части multipart-загрузки в байтах.
        S3_POST_POLICY_MAX_OBJECT_SIZE_BYTES: Максимальный размер объекта
            для POST policy.
        SYSTEM_PATH_PREFIX_PATTERN: Шаблон Windows-пути с буквой диска.
        UNSAFE_EXTENSION_CHARS_PATTERN: Шаблон небезопасных символов
            в расширении файла.
        FORBIDDEN_METADATA_VALUE_CHARS_PATTERN: Шаблон запрещенных символов
            в значении metadata.
        IP_ADDRESS_LIKE_PATTERN: Шаблон строки, похожей на IPv4-адрес.
        BUCKET_NAME_PATTERN: Шаблон допустимого имени bucket-а.
        UNSAFE_FILENAME_CHARS_PATTERN: Шаблон небезопасных символов
            в имени файла.
        ALLOWED_METADATA_KEY_PATTERN: Шаблон допустимого ключа metadata.
        FORBIDDEN_OBJECT_KEY_PARTS: Запрещенные части object key.
        RESERVED_METADATA_KEYS: Зарезервированные ключи metadata.
        STORAGE_EXECUTOR_MAX_WORKERS: Количество обработчиков.
    """

    MINIO_HOST: Final[str] = "localhost"
    MINIO_PORT: Final[int] = 9000
    MINIO_PUBLIC_HOST: Final[str] = "localhost"
    MINIO_PUBLIC_PORT: Final[int] = 9000
    MINIO_ACCESS_KEY: Final[str] = "localcloud"
    MINIO_SECRET_KEY: Final[str] = "localcloud_password"
    MINIO_SECURE: Final[bool] = False
    MINIO_REGION: Final[str] = "us-east-1"

    MINIO_BUCKET_FILES: Final[str] = "localcloud-files"
    MINIO_BUCKET_TEMP: Final[str] = "localcloud-temp"
    MINIO_BUCKET_ARCHIVES: Final[str] = "localcloud-archives"
    STORAGE_HEALTHCHECK_OBJECT_PREFIX: Final[str] = "health-check"
    STORAGE_HEALTHCHECK_OBJECT_CONTENT_TYPE: Final[str] = "text/plain"
    STORAGE_HEALTHCHECK_OBJECT_PAYLOAD: Final[bytes] = (
        b"localcloud-storage-health-check"
    )

    MULTIPART_MAX_PARTS: Final[int] = 10_000
    S3_BUCKET_NAME_MIN_LENGTH: Final[int] = 3
    S3_BUCKET_NAME_MAX_LENGTH: Final[int] = 63
    S3_OBJECT_KEY_MAX_LENGTH: Final[int] = 1024
    S3_MULTIPART_MIN_PART_NUMBER: Final[int] = 1
    STORAGE_EXTENSION_MAX_LENGTH: Final[int] = 32
    STORAGE_METADATA_KEY_MAX_LENGTH: Final[int] = 64
    S3_MULTIPART_MIN_PART_SIZE_BYTES: Final[int] = 1
    S3_MULTIPART_MAX_PART_NUMBER: Final[int] = 10_000
    S3_PRESIGNED_MIN_EXPIRES_IN_SECONDS: Final[int] = 1
    STORAGE_METADATA_VALUE_MAX_LENGTH: Final[int] = 2048
    PRESIGNED_UPLOAD_EXPIRE_SECONDS: Final[int] = 60 * 15
    STORAGE_METADATA_TOTAL_MAX_SIZE: Final[int] = 8 * 1024
    STORAGE_FILENAME_METADATA_MAX_LENGTH: Final[int] = 255
    PRESIGNED_DOWNLOAD_EXPIRE_SECONDS: Final[int] = 60 * 15
    MULTIPART_PART_SIZE_BYTES: Final[int] = 8 * 1024 * 1024
    STORAGE_DEFAULT_LATENCY_THRESHOLD_MS: Final[float] = 500.0
    STORAGE_DEFAULT_CHECKSUM_CHUNK_SIZE: Final[int] = 1024 * 1024
    S3_PRESIGNED_MAX_EXPIRES_IN_SECONDS: Final[int] = 7 * 24 * 60 * 60
    S3_MULTIPART_MIN_NON_LAST_PART_SIZE_BYTES: Final[int] = 5 * 1024 * 1024
    S3_POST_POLICY_MAX_OBJECT_SIZE_BYTES: Final[int] = 5 * 1024 * 1024 * 1024

    SYSTEM_PATH_PREFIX_PATTERN: Final[Pattern] = compile(r"^[a-zA-Z]:/")
    UNSAFE_EXTENSION_CHARS_PATTERN: Final[Pattern] = compile(r"[^a-z0-9]+")
    FORBIDDEN_METADATA_VALUE_CHARS_PATTERN: Final[Pattern] = compile(r"[\r\n]")
    IP_ADDRESS_LIKE_PATTERN: Final[Pattern] = compile(r"^\d{1,3}(\.\d{1,3}){3}$")
    BUCKET_NAME_PATTERN: Final[Pattern] = compile(r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$")
    UNSAFE_FILENAME_CHARS_PATTERN: Final[Pattern] = compile(r"[\x00-\x1f\x7f/\\]+")
    ALLOWED_METADATA_KEY_PATTERN: Final[Pattern] = compile(r"^[a-z0-9][a-z0-9_-]*$")

    FORBIDDEN_OBJECT_KEY_PARTS: Final[set[str]] = {"", ".", ".."}
    RESERVED_METADATA_KEYS: Final[set[str]] = {
        "user_id",
        "file_id",
        "version_id",
        "upload_session_id",
        "task_id",
        "checksum",
        "checksum_algorithm",
        "original_filename",
        "content_type",
        "created_by",
    }

    STORAGE_EXECUTOR_MAX_WORKERS: Final[int] = 8


class WorkerConstants:
    """Константы worker-процесса.

    Хранит базовые параметры фонового worker-процесса: настройки опроса
    очереди, ограничения параллельной обработки задач, интервалы повторных
    попыток, периодические задачи scheduler, параметры блокировок, архивирования
    и batch-обработки.

    Attributes:
        WORKER_NAME_PREFIX: Префикс имени worker-процесса.
        WORKER_POLL_INTERVAL_SECONDS: Интервал опроса очереди задач в секундах.
        WORKER_IDLE_SLEEP_SECONDS: Пауза при отсутствии задач в секундах.
        WORKER_BATCH_SIZE: Размер batch-а задач для обработки.
        WORKER_MAX_CONCURRENT_TASKS: Максимальное число задач, выполняемых
            одновременно.
        WORKER_SHUTDOWN_TIMEOUT_SECONDS: Таймаут завершения worker-процесса
            в секундах.
        WORKER_RETRY_DELAY_SECONDS: Начальная задержка повторной попытки
            обработки задачи в секундах.
        WORKER_MAX_RETRY_DELAY_SECONDS: Максимальная задержка повторной попытки
            обработки задачи в секундах.
        CLEAN_TRASH_INTERVAL_SECONDS: Интервал очистки корзины в секундах.
        CLEAN_EXPIRED_UPLOADS_INTERVAL_SECONDS: Интервал очистки истекших
            загрузок в секундах.
        CLEAN_EXPIRED_PUBLIC_LINKS_INTERVAL_SECONDS: Интервал очистки истекших
            публичных ссылок в секундах.
        RECALCULATE_QUOTAS_INTERVAL_SECONDS: Интервал пересчета квот в секундах.
        CHECK_STORAGE_INTEGRITY_INTERVAL_SECONDS: Интервал проверки целостности
            хранилища в секундах.
        WORKER_TASK_LOCK_TTL_SECONDS: TTL блокировки задачи в секундах.
        WORKER_STALE_TASK_LOCK_SECONDS: Возраст блокировки, после которого она
            считается устаревшей, в секундах.
        CLEANUP_BATCH_SIZE: Размер batch-а для задач очистки.
        INTEGRITY_BATCH_SIZE: Размер batch-а для проверки целостности.
        QUOTA_BATCH_SIZE: Размер batch-а для пересчета квот.
    """

    WORKER_NAME_PREFIX: Final[str] = "localcloud-worker"
    WORKER_POLL_INTERVAL_SECONDS: Final[int] = 5
    WORKER_IDLE_SLEEP_SECONDS: Final[int] = 2
    WORKER_BATCH_SIZE: Final[int] = 10
    WORKER_MAX_CONCURRENT_TASKS: Final[int] = 4
    WORKER_SHUTDOWN_TIMEOUT_SECONDS: Final[int] = 30

    WORKER_RETRY_DELAY_SECONDS: Final[int] = 60
    WORKER_MAX_RETRY_DELAY_SECONDS: Final[int] = 3600

    CLEAN_TRASH_INTERVAL_SECONDS: Final[int] = 3600
    CLEAN_EXPIRED_UPLOADS_INTERVAL_SECONDS: Final[int] = 1800
    CLEAN_EXPIRED_PUBLIC_LINKS_INTERVAL_SECONDS: Final[int] = 3600
    RECALCULATE_QUOTAS_INTERVAL_SECONDS: Final[int] = 86400
    CHECK_STORAGE_INTEGRITY_INTERVAL_SECONDS: Final[int] = 86400

    WORKER_TASK_LOCK_TTL_SECONDS: Final[int] = 300
    WORKER_STALE_TASK_LOCK_SECONDS: Final[int] = 900

    CLEANUP_BATCH_SIZE: Final[int] = 100
    INTEGRITY_BATCH_SIZE: Final[int] = 100
    QUOTA_BATCH_SIZE: Final[int] = 100
