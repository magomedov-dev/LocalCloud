# LocalCloud — Backend

Серверная часть LocalCloud: REST API на FastAPI и фоновый worker для координации загрузки и
скачивания файлов, хранения метаданных в PostgreSQL, работы с объектным хранилищем MinIO и
обработки долгих операций — архивирования, генерации превью, очистки корзины.

> Часть монорепозитория [LocalCloud](../README.md). Общий обзор, схема сервисов и быстрый
> старт через Docker Compose — в корневом `README.md`. История изменений —
> в [`CHANGELOG.md`](../CHANGELOG.md).

---

## Содержание

1. [Стек и версии](#стек-и-версии)
2. [Архитектура](#архитектура)
3. [Структура проекта](#структура-проекта)
4. [Установка и запуск](#установка-и-запуск)
5. [Конфигурация](#конфигурация)
6. [База данных](#база-данных)
7. [Модели данных](#модели-данных)
8. [Безопасность и аутентификация](#безопасность-и-аутентификация)
9. [Загрузка файлов (multipart upload)](#загрузка-файлов-multipart-upload)
10. [Хранилище MinIO](#хранилище-minio)
11. [Фоновый worker](#фоновый-worker)
12. [API](#api)
13. [Миграции](#миграции)
14. [Инициализация администратора](#инициализация-администратора)
15. [Разработка](#разработка)

---

## Стек и версии

| Компонент | Версия | Назначение |
|-----------|--------|-----------|
| **Python** | `≥ 3.13` | Язык |
| **FastAPI** | `≥ 0.125` | Web-фреймворк |
| **Uvicorn** | `≥ 0.48` | ASGI-сервер |
| **SQLAlchemy** | `≥ 2.0` (async) | ORM |
| **asyncpg** | `≥ 0.31` | PostgreSQL async-драйвер |
| **Alembic** | `≥ 1.17` | Миграции схемы БД |
| **Pydantic v2** | `≥ 2.13` | Схемы запросов/ответов |
| **pydantic-settings** | `≥ 2.14` | Конфигурация через `.env` |
| **python-jose** | `≥ 3.5` | JWT (HS256) |
| **passlib** | `≥ 1.7` | Хеширование паролей (bcrypt / argon2) |
| **MinIO SDK** | `≥ 7.2` | Объектное хранилище |
| **Pillow** | `≥ 12.2` | Генерация превью изображений |
| **uv** | — | Пакетный менеджер |
| **ruff** | — | Линт и форматирование |
| **ty** | — | Статическая типизация |

---

## Архитектура

```
┌──────────────────────────────────────────────────────────────────────┐
│  HTTP / HTTPS                                                        │
│                                                                      │
│  ┌──────────────────────────────────────────────────┐               │
│  │  FastAPI (api/v1/)                               │               │
│  │  auth · nodes · files · folders · uploads        │               │
│  │  downloads · permissions · public_links          │               │
│  │  trash · quotas · tasks · users · audit · health │               │
│  └──────────────────┬───────────────────────────────┘               │
│                     │                                                │
│  ┌──────────────────▼───────────────────────────────┐               │
│  │  Services (бизнес-логика)                        │               │
│  │  AuthService · FilesService · UploadsService     │               │
│  │  PermissionsService · QuotasService · …          │               │
│  └────────┬────────────────────────┬────────────────┘               │
│           │                        │                                 │
│  ┌────────▼────────┐    ┌──────────▼──────────────────┐             │
│  │  Unit of Work   │    │  StorageService             │             │
│  │  repositories   │    │  (MinIO SDK)                │             │
│  │  (SQLAlchemy)   │    │  presigned · multipart      │             │
│  └────────┬────────┘    └─────────────────────────────┘             │
│           │                                                          │
│  ┌────────▼────────┐    ┌─────────────────────────────┐             │
│  │  PostgreSQL     │    │  MinIO (объектное хранилище)│             │
│  │  (asyncpg)      │    │                             │             │
│  └─────────────────┘    └─────────────────────────────┘             │
│                                                                      │
│  ┌──────────────────────────────────────────────────┐               │
│  │  Worker (workers/)                               │               │
│  │  Dispatcher → BackgroundTask (DB) → Handler      │               │
│  │  Scheduler → периодические задания               │               │
│  └──────────────────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────────────────┘
```

Все компоненты — **async-first**: I/O с базой данных идёт через asyncpg без промежуточного
синхронного пула, запросы к MinIO выполняются в ThreadPoolExecutor (SDK синхронный), что
не блокирует event loop. Фоновый worker — отдельный процесс, он читает очередь задач из той же
PostgreSQL-таблицы; никакого Redis или брокера сообщений для базовых сценариев не требуется.

---

## Структура проекта

```
backend/
├── app/
│   ├── main.py                 # create_app() → глобальный экземпляр app
│   ├── lifecycle.py            # startup_backend / shutdown_backend
│   ├── middleware.py           # CORS, GZip, логирование запросов
│   └── exception_handlers.py  # Перевод доменных исключений в HTTP-ответы
│
├── api/
│   ├── router.py               # Сборка корневого роутера
│   ├── dependencies.py         # Инъекция сервисов через Depends
│   └── v1/                     # Роутеры по доменам
│       ├── auth.py             # /auth
│       ├── users.py            # /users
│       ├── registration.py     # /registration
│       ├── nodes.py            # /nodes
│       ├── folders.py          # /folders
│       ├── uploads.py          # /uploads
│       ├── downloads.py        # /downloads (presigned URL)
│       ├── trash.py            # /trash
│       ├── permissions.py      # /permissions
│       ├── public_links.py     # /public-links
│       ├── quotas.py           # /quotas
│       ├── tasks.py            # /tasks
│       ├── audit.py            # /audit
│       └── health.py           # /health
│
├── services/                   # Бизнес-логика; один модуль на домен
│   ├── auth.py
│   ├── users.py
│   ├── files.py
│   ├── folders.py
│   ├── nodes.py
│   ├── uploads.py
│   ├── downloads.py
│   ├── permissions.py
│   ├── public_links.py
│   ├── quotas.py
│   ├── trash.py
│   ├── registration.py
│   ├── audit.py
│   ├── tasks.py
│   └── health.py
│
├── database/
│   ├── client.py               # AsyncEngine, async_sessionmaker, ping_database
│   ├── unit_of_work.py         # UnitOfWork, UnitOfWorkFactory
│   ├── transactions.py         # Вспомогательные функции транзакций
│   ├── exceptions.py           # Иерархия DatabaseError
│   ├── health.py               # Проверка доступности БД
│   ├── models/
│   │   ├── base.py             # Declarative Base, соглашения об именовании
│   │   ├── enums.py            # Все StrEnum-перечисления
│   │   ├── mixins.py           # TimestampMixin, SoftDeleteMixin, …
│   │   ├── users.py            # User
│   │   ├── filesystem.py       # FileSystemNode, File, Folder, FileVersion, TrashItem
│   │   ├── tokens.py           # RefreshToken
│   │   ├── registration.py     # RegistrationRequest
│   │   ├── roles.py            # Role, UserRole
│   │   ├── permissions.py      # NodePermission
│   │   ├── quotas.py           # UserQuota
│   │   ├── uploads.py          # UploadSession, UploadPart
│   │   ├── links.py            # PublicLink
│   │   ├── tasks.py            # BackgroundTask
│   │   └── audit.py            # AuditLog
│   └── repositories/           # Доступ к данным; один модуль на модель
│       ├── base.py             # BaseRepository с generic CRUD
│       ├── users.py
│       ├── roles.py
│       ├── nodes.py
│       ├── files.py
│       ├── folders.py
│       ├── versions.py
│       ├── trash.py
│       ├── permissions.py
│       ├── links.py
│       ├── quotas.py
│       ├── tokens.py
│       ├── sessions.py
│       ├── parts.py
│       ├── tasks.py
│       ├── audit.py
│       └── registration.py
│
├── storage/
│   ├── client.py               # StorageClient (обёртка MinIO SDK)
│   ├── service.py              # StorageService (высокоуровневое API)
│   ├── buckets.py              # Создание и проверка бакетов
│   ├── multipart.py            # Multipart upload
│   ├── presigned.py            # Presigned URL (GET и PUT)
│   ├── keys.py                 # Формирование ключей объектов
│   ├── metadata.py             # Кастомные заголовки объектов
│   ├── integrity.py            # Проверка контрольных сумм
│   ├── health.py               # Healthcheck хранилища
│   └── exceptions.py           # StorageError и подклассы
│
├── security/
│   ├── jwt/                    # JWT: создание, валидация, DTO
│   ├── password/               # Хеширование паролей (bcrypt/argon2)
│   ├── cookies/                # Чтение и установка auth-кук
│   ├── permissions/            # Проверка уровней доступа
│   └── dependencies/           # FastAPI-зависимости (CurrentUser, RequireAdmin, …)
│
├── schemas/                    # Pydantic-схемы запросов и ответов
│
├── workers/
│   ├── app.py                  # Точка входа: python -m workers.app
│   ├── dispatcher.py           # Выборка и выполнение задач
│   ├── scheduler.py            # Периодические задания
│   ├── registry.py             # Реестр обработчиков задач
│   ├── context.py              # WorkerContext (соединения, фабрика UoW)
│   ├── lifecycle.py            # Инициализация ресурсов worker-процесса
│   ├── archives.py             # Обработчик CREATE_FOLDER_ARCHIVE
│   ├── previews.py             # Обработчик GENERATE_FILE_PREVIEW
│   ├── cleanup.py              # CLEAN_TRASH, DELETE_OBJECT_FROM_STORAGE
│   ├── uploads.py              # Обработчик CLEAN_EXPIRED_UPLOADS
│   ├── public_links.py         # Деактивация просроченных публичных ссылок
│   ├── integrity.py            # Проверка целостности хранилища
│   ├── quotas.py               # Пересчёт квот пользователей
│   ├── tasks.py                # Утилиты работы с задачами
│   ├── health.py               # Проверка состояния worker-процесса
│   ├── types.py                # Типы и DTO обработчиков
│   └── exceptions.py           # Исключения worker
│
├── core/
│   ├── config.py               # AppSettings (агрегирует все подгруппы настроек)
│   ├── constants.py            # Числовые константы и пути
│   └── logging.py              # Настройка structlog / stdlib logging
│
├── migrations/
│   ├── env.py                  # Конфигурация Alembic
│   └── versions/               # Ревизии
│       ├── ac57ae7d7abd_initial_schema.py
│       ├── b3f1c2d4e5a6_add_ix_fsn_parent_active_name.py
│       └── c4d2e6f8a1b3_drop_backup_enum_values.py
│
├── seed_admin.py               # Создание ролей и учётки администратора
├── Dockerfile
├── docker-entrypoint.sh
├── alembic.ini
└── pyproject.toml
```

---

## Установка и запуск

### Зависимости

- PostgreSQL ≥ 14
- MinIO (или любой S3-совместимый сервис)
- Python ≥ 3.13 + [`uv`](https://docs.astral.sh/uv/)

Для разработки проще всего поднять PostgreSQL и MinIO через Docker (команды — в корневом
`README.md`). Конфигурация читается из **единого** корневого `.env`; отдельного
`backend/.env` нет.

```bash
# В корне проекта
cp .env.example .env
# Отредактируйте .env: SECRET_KEY, пароли БД и MinIO, ADMIN_PASSWORD

cd backend
uv sync                           # установить зависимости в .venv

uv run alembic upgrade head       # применить миграции
uv run python seed_admin.py       # создать роли и учётку администратора

# API (dev-режим, с hot-reload)
uv run uvicorn app.main:app --reload --port 8000

# Worker (отдельный процесс / терминал)
uv run python -m workers.app
```

После запуска API-документация доступна по адресам:

- **Swagger UI** — `http://localhost:8000/docs`
- **ReDoc** — `http://localhost:8000/redoc`

### Production

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
uv run python -m workers.app
```

> **Пул соединений.** Каждый uvicorn-воркер и каждый worker-процесс держат независимый пул
> (`POSTGRES_POOL_SIZE + POSTGRES_MAX_OVERFLOW` соединений). При 4 API-воркерах и 1
> worker-процессе потребуется минимум `5 × (pool_size + max_overflow) + резерв` соединений.
> Значения по умолчанию: `pool_size = 20`, `max_overflow = 10`, итого до 150 соединений плюс
> резерв PostgreSQL. Скорректируйте `POSTGRES_POOL_SIZE` под реальную нагрузку.

### Docker

В корневом `docker-compose.yml` backend собирается в один образ, который поддерживает оба
режима запуска через переопределение команды. `docker-entrypoint.sh` ждёт готовности PostgreSQL
и MinIO по TCP, а в сервисе `api` (при `RUN_MIGRATIONS=true`) прогоняет миграции и создаёт
администратора перед стартом Uvicorn.

---

## Конфигурация

Все настройки читаются из переменных окружения или из корневого файла `.env`. Доступ к
объекту настроек во всём проекте:

```python
from core.config import get_settings
settings = get_settings()  # ленивый синглтон, кешируется через @lru_cache
```

### Приложение

| Переменная | Тип | По умолчанию | Описание |
|---|---|---|---|
| `APP_NAME` | `str` | `"LocalCloud"` | Название приложения |
| `APP_VERSION` | `str` | `"0.1.0"` | Версия |
| `DEBUG` | `bool` | `false` | Режим отладки (подробные ошибки) |
| `API_V1_PREFIX` | `str` | `"/api/v1"` | Префикс всех v1-маршрутов |

### Логирование

| Переменная | Тип | По умолчанию | Описание |
|---|---|---|---|
| `LOG_LEVEL` | `str` | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_JSON` | `bool` | `false` | Вывод логов в JSON (для log-агрегаторов) |
| `LOG_FILE_ENABLED` | `bool` | `false` | Запись логов в файл |
| `LOG_FILE_PATH` | `Path` | `"logs/localcloud.log"` | Путь к файлу логов |

### Безопасность и JWT

| Переменная | Тип | По умолчанию | Описание |
|---|---|---|---|
| `SECRET_KEY` | `str` | — | **Обязателен.** Ключ подписи JWT. Генерируйте: `openssl rand -hex 32` |
| `JWT_ALGORITHM` | `str` | `"HS256"` | Алгоритм подписи |
| `JWT_ISSUER` | `str` | `"localcloud"` | Claim `iss` в токене |
| `JWT_AUDIENCE` | `str` | `"localcloud-users"` | Claim `aud` в токене |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `int` | `15` | Срок жизни access-токена |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `int` | `30` | Срок жизни refresh-токена |
| `PASSWORD_HASH_SCHEME` | `str` | `"bcrypt"` | `"bcrypt"` или `"argon2"` |

### Cookies

| Переменная | Тип | По умолчанию | Описание |
|---|---|---|---|
| `ACCESS_COOKIE_NAME` | `str` | `"localcloud_access"` | Имя cookie с access-токеном |
| `REFRESH_COOKIE_NAME` | `str` | `"localcloud_refresh"` | Имя cookie с refresh-токеном |
| `COOKIE_SECURE` | `bool` | `false` | `Secure`-флаг (только HTTPS; в проде `true`) |
| `COOKIE_HTTPONLY` | `bool` | `true` | `HttpOnly`-флаг (недоступна из JS) |
| `COOKIE_SAMESITE` | `str` | `"lax"` | `"lax"`, `"strict"` или `"none"` |
| `COOKIE_DOMAIN` | `str \| None` | `null` | Домен cookie; `null` = текущий хост |
| `COOKIE_PATH` | `str` | `"/"` | Путь cookie |

### База данных

| Переменная | Тип | По умолчанию | Описание |
|---|---|---|---|
| `POSTGRES_HOST` | `str` | `"localhost"` | Хост PostgreSQL |
| `POSTGRES_PORT` | `int` | `5432` | Порт |
| `POSTGRES_USER` | `str` | `"localcloud"` | Пользователь |
| `POSTGRES_PASSWORD` | `str` | `"localcloud"` | Пароль |
| `POSTGRES_DB` | `str` | `"localcloud"` | Имя базы данных |
| `POSTGRES_ECHO` | `bool` | `false` | Логирование SQL-запросов |
| `POSTGRES_POOL_SIZE` | `int` | `10` | Размер пула соединений на воркер |
| `POSTGRES_MAX_OVERFLOW` | `int` | `5` | Дополнительные соединения сверх пула |
| `POSTGRES_POOL_TIMEOUT` | `int` | `30` | Таймаут ожидания свободного соединения, сек |
| `POSTGRES_POOL_RECYCLE` | `int` | `1800` | Принудительное переоткрытие соединения, сек |
| `POSTGRES_POOL_PRE_PING` | `bool` | `true` | Проверка соединения перед использованием |

DSN вычисляется автоматически как `postgresql+asyncpg://user:password@host:port/db`.

### Хранилище (MinIO)

| Переменная | Тип | По умолчанию | Описание |
|---|---|---|---|
| `MINIO_HOST` | `str` | `"localhost"` | Хост MinIO (внутренний, для API) |
| `MINIO_PORT` | `int` | `9000` | Порт |
| `MINIO_PUBLIC_HOST` | `str` | `"localhost"` | Хост для presigned-URL (видит браузер) |
| `MINIO_PUBLIC_PORT` | `int` | `9000` | Публичный порт |
| `MINIO_ACCESS_KEY` | `str` | `"localcloud"` | Access key |
| `MINIO_SECRET_KEY` | `str` | `"localcloud_password"` | Secret key |
| `MINIO_SECURE` | `bool` | `false` | Использовать HTTPS |
| `MINIO_REGION` | `str` | `"us-east-1"` | Регион (влияет на подпись URL) |

`MINIO_PUBLIC_HOST` / `MINIO_PUBLIC_PORT` важны при работе за reverse-proxy: API обращается
к MinIO по внутреннему адресу, а presigned-URL должен содержать адрес, доступный браузеру.

### Worker

| Переменная | Тип | По умолчанию | Описание |
|---|---|---|---|
| `WORKER_ENABLED` | `bool` | `true` | Включить выполнение задач |
| `WORKER_POLL_INTERVAL_SECONDS` | `int` | `5` | Интервал опроса очереди, сек |
| `WORKER_BATCH_SIZE` | `int` | `10` | Задач на один цикл (1–100) |
| `WORKER_MAX_CONCURRENT_TASKS` | `int` | `4` | Параллельных задач (1–32) |
| `WORKER_SHUTDOWN_TIMEOUT_SECONDS` | `int` | `30` | Ожидание завершения задач при остановке |
| `WORKER_TASK_LOCK_TTL_SECONDS` | `int` | `300` | TTL блокировки задачи |
| `WORKER_STALE_TASK_LOCK_SECONDS` | `int` | `900` | После этого времени блокировка считается устаревшей |
| `WORKER_RETRY_DELAY_SECONDS` | `int` | `60` | Базовая задержка повтора |
| `WORKER_MAX_RETRY_DELAY_SECONDS` | `int` | `3600` | Максимальная задержка повтора |
| `WORKER_CLEAN_TRASH_INTERVAL_SECONDS` | `int` | `3600` | Интервал очистки корзины |
| `WORKER_CLEAN_EXPIRED_UPLOADS_INTERVAL_SECONDS` | `int` | `1800` | Интервал очистки просроченных upload-сессий |
| `WORKER_CLEAN_EXPIRED_PUBLIC_LINKS_INTERVAL_SECONDS` | `int` | `3600` | Интервал деактивации просроченных публичных ссылок |
| `WORKER_RECALCULATE_QUOTAS_INTERVAL_SECONDS` | `int` | `86400` | Интервал пересчёта квот |
| `WORKER_STORAGE_INTEGRITY_INTERVAL_SECONDS` | `int` | `86400` | Интервал проверки целостности хранилища |

### Администратор (сидирование)

| Переменная | По умолчанию |
|---|---|
| `ADMIN_EMAIL` | `admin@localcloud.dev` |
| `ADMIN_USERNAME` | `admin` |
| `ADMIN_PASSWORD` | `Admin@LocalCloud123` |

> ⚠️ Перед публичным развёртыванием обязательно смените `SECRET_KEY`, пароли БД и MinIO,
> а также `ADMIN_PASSWORD`.

---

## База данных

### Клиент и пул соединений

Модуль `database/client.py` хранит глобальный `AsyncEngine` и `async_sessionmaker`. Движок
инициализируется один раз при старте приложения через `init_db_client(settings)` и закрывается
при остановке через `close_db_client()`. Для проверки доступности используется
`await ping_database()` — выполняет `SELECT 1` и возвращает `bool`.

### Unit of Work

Весь доступ к данным идёт через `UnitOfWork` — обёртку над одной `AsyncSession`, которая
ленно инициализирует репозитории при первом обращении и чётко разграничивает транзакцию.

```python
from database.unit_of_work import create_unit_of_work_factory

uow_factory = create_unit_of_work_factory()

async with uow_factory() as uow:
    user = await uow.users.get_by_id(user_id)
    user.status = UserStatus.ACTIVE
    await uow.commit()
```

`UnitOfWork` — контекстный менеджер: при нормальном выходе транзакция **не коммитится**
автоматически (если не передан `commit_on_exit=True`), при исключении — откатывается.
Явный `await uow.commit()` — намеренное решение, чтобы не фиксировать изменения случайно.

**Доступные репозитории:**

```python
uow.users              # UsersRepository
uow.roles              # RolesRepository
uow.registration_requests  # RegistrationRequestsRepository
uow.refresh_tokens     # RefreshTokensRepository
uow.nodes              # FileSystemNodeRepository
uow.files              # FileRepository
uow.folders            # FolderRepository
uow.versions           # FileVersionRepository
uow.trash              # TrashItemRepository
uow.permissions        # NodePermissionsRepository
uow.links              # PublicLinksRepository
uow.upload_sessions    # UploadSessionsRepository
uow.upload_parts       # UploadPartsRepository
uow.quotas             # UserQuotaRepository
uow.audit              # AuditLogRepository
uow.tasks              # BackgroundTasksRepository
```

### Исключения

`database/exceptions.py` определяет иерархию исключений, которые `exception_handlers.py`
автоматически переводит в HTTP-ответы:

```
DatabaseError
├── DatabaseConnectionError        → 503 Service Unavailable
├── DatabaseTimeoutError           → 504 Gateway Timeout
├── TransactionError
│   ├── TransactionCommitError     → 500
│   └── TransactionRollbackError   → 500
├── RepositoryError
│   ├── DuplicateEntityError       → 409 Conflict
│   ├── EntityNotFoundError        → 404 Not Found
│   ├── ConstraintViolationError   → 422 Unprocessable Entity
│   └── InvalidQueryError          → 400 Bad Request
│       └── InvalidPaginationError → 400 Bad Request
└── UnitOfWorkError                → 500
```

---

## Модели данных

Все модели наследуют от `Base` (SQLAlchemy Declarative Base с соглашениями об именовании)
и при необходимости от миксинов.

**Миксины (`database/models/mixins.py`):**

```python
TimestampMixin    # created_at, updated_at (UTC, auto-update)
CreatedAtMixin    # только created_at
SoftDeleteMixin   # is_deleted (bool), deleted_at (datetime | None)
UUIDPrimaryKeyMixin  # id: UUID = uuid4()
```

### Таблицы

#### `users`

Центральная сущность. Основные поля: `id (UUID PK)`, `email (unique)`, `username (unique)`,
`password_hash`, `status (UserStatus)`, `is_email_verified`, временны́е метки событий
(`last_login_at`, `approved_at`, `blocked_at`, `rejected_at`, `deleted_at`) и причины
изменений статуса (`block_reason`, `rejection_reason`).

`UserStatus`: `pending` → `active` | `rejected`; `active` → `blocked` | `deleted`.

Индексы: `(email, status)`, `(username, status)`, `(status, created_at)`, `last_login_at`.

#### `file_system_nodes`

Единая таблица для файлов и папок — материализованное дерево. Поля: `id`, `owner_id`,
`parent_id` (self-referential FK), `name`, `node_type (NodeType: file | folder)`,
`visibility (NodeVisibility: private | shared | public)`, `path` (материализованный путь,
например `"/folder1/subfolder/"`), `depth`. Мягкое удаление через `SoftDeleteMixin`.

Индекс `(owner_id, parent_id, name)` ускоряет поиск дочерних узлов по имени — критичен
при навигации по директориям.

#### `files`

Расширение `FileSystemNode` для файлов. `node_id (PK, FK → file_system_nodes)`,
`mime_type`, `size_bytes`, `object_key` (ключ объекта в MinIO), `processing_status`,
`preview_status`, `preview_object_key`.

#### `folders`

Расширение `FileSystemNode` для папок: `node_id (PK, FK)`, а также `description` (описание) и
`color` (цветовая метка папки в интерфейсе).

#### `file_versions`

История версий файла: `id`, `file_id (FK → files)`, `version_number`, `status
(FileVersionStatus: active | archived | deleted)`, `object_key`, `size_bytes`, `mime_type`.

#### `trash_items`

Запись о мягко-удалённом узле: `node_id (FK → file_system_nodes)`, `status
(TrashItemStatus: in_trash | restored | purged)`.

#### `roles` / `user_roles`

`roles`: `id`, `name`, `code (unique)`, `display_name`, `is_system`, `is_active`.
`user_roles`: связующая таблица `(user_id, role_id)` с `assigned_at` и `assigned_by`.
Уникальный constraint `(user_id, role_id)` предотвращает дублирование ролей.

Системные роли: `admin` и `user` — создаются при сидировании и не удаляются.

#### `node_permissions`

Гранулярный контроль доступа: `node_id`, `subject_type (user | role | public_link)`,
`subject_id`, `permission_level (read | download | write | delete | owner)`, `is_active`,
`granted_by`.

#### `refresh_tokens`

`user_id`, `token_value (unique)`, `token_type`, `expires_at`, `revoked_at`. Хранится
хеш значения токена, а не сам токен.

#### `public_links`

Публичный доступ к узлу: `node_id`, `token (unique, случайная строка)`, `status
(active | disabled | expired | revoked)`, `permission_type (view | download | upload)`,
`expires_at`, `password_hash`, `download_limit`, `download_count`.

#### `upload_sessions`

Состояние multipart upload: `node_id`, `filename`, `mime_type`, `status
(created | uploading | completed | failed | aborted | expired)`, `minio_upload_id`,
`expires_at`.

#### `upload_parts`

Каждая часть multipart upload: `session_id`, `part_number`, `size_bytes`,
`status (pending | uploaded | failed)`, `etag`.
Unique constraint `(session_id, part_number)`.

#### `user_quotas`

Лимиты и использование ресурсов пользователя: `storage_limit_bytes`, `storage_used_bytes`,
`max_file_size_bytes`, `files_limit`, `files_used`, `public_links_limit`,
`public_links_used`, `active_upload_sessions_limit`, `active_upload_sessions_used`.

#### `registration_requests`

Заявка на регистрацию: `email`, `username`, `status (pending | approved | rejected |
cancelled)`, `created_by`, `reviewed_by`, `rejection_reason`.

#### `background_tasks`

Очередь задач для worker: `task_type`, `status (pending | running | completed | failed |
cancelled)`, `priority (low | normal | high | critical)`, `created_by`, `locked_by`,
`locked_until`, `attempts_count`, `max_attempts`, `progress_percent`, `idempotency_key`,
`payload (JSONB)`, `result_data (JSONB)`.

#### `audit_logs`

Неизменяемый журнал действий: `user_id`, `action (AuditAction)`, `resource_type`,
`resource_id`, `result (success | failure | denied | warning)`, `details (JSON)`,
`client_ip`, `user_agent`. Таблица только для записи; обновление и удаление записей
не предусмотрено.

---

## Безопасность и аутентификация

### Схема JWT + cookie

Приложение использует **два токена**:

- **Access-токен** — короткоживущий (30 мин по умолчанию), хранится в `HttpOnly`-cookie
  `access_token`. Используется для авторизации каждого запроса.
- **Refresh-токен** — долгоживущий (30 дней), хранится в `HttpOnly`-cookie `refresh_token`.
  Используется только в `POST /auth/refresh`. При каждом refresh старый токен отзывается
  и выдаётся новая пара.

**Структура JWT payload:**

```json
{
  "sub": "<user_id_as_uuid_string>",
  "iss": "localcloud",
  "aud": "localcloud-users",
  "type": "access",
  "iat": 1720000000,
  "exp": 1720001800
}
```

Токены подписываются `HS256` с ключом из `SECRET_KEY`. При верификации проверяются `iss`,
`aud`, `exp` и `type` — лишний шаг, который предотвращает случайное использование
refresh-токена вместо access.

### FastAPI-зависимости авторизации

```python
# Гарантирует активного пользователя (status = active)
current_user: CurrentActiveUserDependency

# То же плюс проверка роли admin
current_user: CurrentAdminUserDependency

# Возвращает пользователя или None (для публичных маршрутов с опциональной авторизацией)
current_user: OptionalCurrentUserDependency
```

Зависимости ищут токен сначала в заголовке `Authorization: Bearer <token>`, затем в
cookie `access_token`. Это позволяет использовать API как из браузера (cookie), так и
из CLI/скриптов (заголовок).

### Хеширование паролей

По умолчанию используется **bcrypt** с `rounds=12`. Если переключить на `argon2`, параметры:
`time_cost=3`, `memory_cost=65536`, `parallelism=4`. Passlib автоматически пересчитывает хеш
при верификации, если схема изменилась — безопасная миграция без принудительного сброса паролей.

### Сброс пароля

1. `POST /auth/password-reset` — по email создаётся токен сброса (тип `password_reset`),
   срок жизни определяется настройкой. Ответ содержит сам токен (в production токен
   отправляется по email — реализация SMTP остаётся на усмотрение деплоя).
2. `POST /auth/password-reset/confirm` — токен + новый пароль. После успеха токен отзывается.

---

## Загрузка файлов (multipart upload)

Загрузка идёт напрямую из браузера в MinIO по presigned-URL — API-сервер не является
транзитом для байтов файла, что снимает нагрузку и убирает ограничение по времени запроса.

### Последовательность

```
Браузер                    API (backend)                    MinIO
   │                            │                              │
   │  POST /uploads/            │                              │
   │  { filename, mime_type,    │                              │
   │    size_bytes, parts_count}│                              │
   │ ─────────────────────────→ │                              │
   │                            │  init_multipart_upload()     │
   │                            │ ───────────────────────────→ │
   │                            │ ←─────────────── upload_id ─ │
   │                            │  INSERT upload_session (DB)  │
   │ ←── UploadSessionRead ──── │                              │
   │                            │                              │
   │  POST /uploads/{id}/       │                              │
   │       parts/presigned      │                              │
   │ ─────────────────────────→ │                              │
   │                            │  create_upload_part_urls()   │
   │                            │  для каждой части            │
   │                            │ ───────────────────────────→ │
   │                            │ ←──── [presigned PUT URL] ── │
   │ ←── [url1, url2, …] ────── │                              │
   │                            │                              │
   │  PUT presigned_url_1       │                              │
   │  (тело = байты части 1)    │                              │
   │ ──────────────────────────────────────────────────────→  │
   │ ←──────────────────────────────────────────── ETag ────  │
   │                            │                              │
   │  POST /uploads/{id}/parts/ │                              │
   │       {n}/complete         │                              │
   │  { part_number: 1,         │                              │
   │    etag: "abc123",         │                              │
   │    size_bytes: 8388608 }   │                              │
   │ ─────────────────────────→ │                              │
   │                            │  UPDATE upload_part (DB)     │
   │ ←── UploadPartRead ──────  │                              │
   │                            │                              │
   │  (повтор для частей 2, 3…) │                              │
   │                            │                              │
   │  POST /uploads/{id}/       │                              │
   │       complete             │                              │
   │  { parts: [{part_number,   │                              │
   │             etag}…] }      │                              │
   │ ─────────────────────────→ │                              │
   │                            │  complete_multipart_upload() │
   │                            │ ───────────────────────────→ │
   │                            │ ←───────────────────── ok ── │
   │                            │  INSERT file_system_node     │
   │                            │  INSERT file                 │
   │                            │  INSERT file_version         │
   │                            │  UPDATE quota (used_bytes)   │
   │ ←── UploadCompleteResponse │                              │
```

Если браузер закрылся или возникла ошибка, клиент вызывает `POST /uploads/{id}/abort` —
API отменяет multipart upload в MinIO и освобождает слот квоты. Worker дополнительно
периодически очищает сессии с истёкшим `expires_at`.

### Размер части

По умолчанию 8 МБ. При отправке клиент должен разбить файл на части указанного размера
(последняя часть может быть меньше). MinIO накладывает ограничение: минимальный размер части
5 МБ (кроме последней), минимальное количество частей — 1.

---

## Хранилище MinIO

### Бакеты

При старте приложения `StorageService.ensure_buckets_ready()` проверяет и при необходимости
создаёт три бакета (имена — в `core/constants.py`):

| Бакет | Содержимое |
|---|---|
| `localcloud-files` | Пользовательские файлы и их версии |
| `localcloud-temp` | Временные объекты (в т. ч. превью) |
| `localcloud-archives` | ZIP-архивы для скачивания папок |

### Ключи объектов

Ключи — плоские строки в MinIO, которые конвенционально выглядят как пути:

```
users/{user_id}/files/{file_id}
users/{user_id}/files/{file_id}/versions/{version_id}
users/{user_id}/previews/{file_id}/preview[.jpg]
users/{user_id}/archives/{task_id}/archive.zip
users/{user_id}/uploads/{upload_session_id}/parts/{part_number}
```

### Метаданные объектов

Каждый объект хранит кастомные заголовки (x-amz-meta-*):

```
x-amz-meta-file-id:        {node_id}
x-amz-meta-user-id:        {owner_id}
x-amz-meta-original-name:  document.pdf
x-amz-meta-mime-type:      application/pdf
x-amz-meta-checksum:       sha256:<hex>
x-amz-meta-created-by:     {user_id}
```

### Presigned URL

- **Скачивание (GET)**: `StorageService.create_download_url(...)` — возвращает URL с
  встроенной подписью. Браузер может скачать файл без авторизации.
- **Загрузка части (PUT)**: `StorageService.create_upload_part_url(...)` /
  `create_upload_part_urls(...)` — используется при multipart upload.

Срок жизни presigned-URL по умолчанию — 900 секунд (15 минут). Фронтенд кеширует эти URL в
`sessionStorage` с TTL 12 минут (чуть меньше срока действия, чтобы не попасть на 403).

---

## Фоновый worker

Worker запускается как отдельный процесс: `python -m workers.app`. Он не использует
отдельного брокера — задачи хранятся в таблице `background_tasks`, что упрощает
инфраструктуру и даёт транзакционные гарантии: задача создаётся в той же транзакции,
что и порождающее её действие.

### Запуск

```bash
uv run python -m workers.app                    # стандартный режим
uv run python -m workers.app --once             # один цикл и выход
uv run python -m workers.app --no-scheduler     # только очередь, без планировщика
uv run python -m workers.app --scheduler-only   # только планировщик, без очереди
uv run python -m workers.app --worker-id my-w1  # метка воркера для логов
uv run python -m workers.app --poll-interval 2  # интервал опроса очереди, сек
```

### Dispatcher

Каждый цикл (`TaskDispatcher.run_once()`):

1. Освободить задачи с устаревшей блокировкой (`locked_at` + TTL < now) и пометить
   их как `FAILED`.
2. Выбрать до `WORKER_BATCH_SIZE` задач в статусе `PENDING` по приоритету.
3. Для каждой задачи атомарно установить `locked_by` (UUID воркера) и `locked_at`.
4. Запустить соответствующий обработчик.
5. Обновить статус задачи (`COMPLETED`, `FAILED` или `PENDING` для повтора).

Несколько экземпляров worker-процесса могут работать параллельно — блокировка через
`locked_by` предотвращает двойную обработку одной задачи.

### Retry с экспоненциальной задержкой

```
delay = min(WORKER_RETRY_DELAY_SECONDS × 2^retry_count, WORKER_MAX_RETRY_DELAY_SECONDS)
```

После достижения `task.max_attempts` (по умолчанию 1) задача переводится в `FAILED`
навсегда. Обработчики сами решают, стоит ли retry, возвращая
`WorkerTaskExecutionResult.retry(delay, reason)` или `.failure(error)`.

### Типы задач

| Тип | Обработчик | Описание |
|---|---|---|
| `CREATE_FOLDER_ARCHIVE` | `workers/archives.py` | Рекурсивно упаковывает папку или набор узлов в ZIP, загружает в MinIO |
| `GENERATE_FILE_PREVIEW` | `workers/previews.py` | Генерирует превью изображения или PDF через Pillow |
| `CLEAN_TRASH` | `workers/cleanup.py` | Удаляет объекты из MinIO для узлов в корзине старше порога |
| `CLEAN_EXPIRED_UPLOADS` | `workers/uploads.py` | Прерывает и очищает просроченные multipart-сессии |
| `CLEAN_EXPIRED_PUBLIC_LINKS` | `workers/public_links.py` | Деактивирует публичные ссылки с истёкшим `expires_at` |
| `DELETE_OBJECT_FROM_STORAGE` | `workers/cleanup.py` | Удаляет конкретный объект из MinIO (используется при окончательном удалении) |
| `CHECK_STORAGE_INTEGRITY` | `workers/integrity.py` | Сверяет контрольные суммы объектов в MinIO с метаданными в БД |
| `RECALCULATE_USER_QUOTA` | `workers/quotas.py` | Пересчитывает `storage_used_bytes` и счётчики файлов из актуального состояния БД |

### Scheduler

Периодические задания создаются автоматически по истечении интервала. Если задание с таким
типом уже есть в статусе `PENDING` или `RUNNING`, новое не создаётся — защита от накопления
дублей при задержке выполнения.

| Задание | Интервал по умолчанию |
|---|---|
| `CLEAN_TRASH` | 1 час |
| `CLEAN_EXPIRED_UPLOADS` | 30 минут |
| `CLEAN_EXPIRED_PUBLIC_LINKS` | 1 час |
| `CHECK_STORAGE_INTEGRITY` | 24 часа |
| `RECALCULATE_USER_QUOTA` | 24 часа |

---

## API

Все маршруты доступны под префиксом `/api/v1`. Ответы пагинируемых списков имеют вид
`PageResponse[T]` с полями `items: list[T]`, `total: int` и `meta: PageMeta`.

### Аутентификация — `/auth`

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/auth/login` | Вход: email/username + пароль → access + refresh cookie |
| `POST` | `/auth/refresh` | Ротация токенов: refresh → новая пара access/refresh |
| `POST` | `/auth/logout` | Выход: отзывает текущий refresh-токен, удаляет cookies |
| `GET` | `/auth/me` | Текущий пользователь по access-токену |
| `GET` | `/auth/sessions` | Список активных сессий пользователя |
| `DELETE` | `/auth/sessions/{session_id}` | Отозвать конкретную сессию |
| `POST` | `/auth/password/change` | Смена пароля текущего пользователя |
| `POST` | `/auth/password/reset/request` | Запрос сброса пароля по email |
| `POST` | `/auth/password/reset/confirm` | Подтверждение сброса пароля по токену |

### Пользователи — `/users`

| Метод | Путь | Права | Описание |
|---|---|---|---|
| `GET` | `/users/me` | — | Профиль текущего пользователя |
| `PATCH` | `/users/me` | — | Обновление профиля |
| `GET` | `/users/` | admin | Список пользователей с фильтрацией |
| `GET` | `/users/{user_id}` | admin | Профиль пользователя по ID |
| `PATCH` | `/users/{user_id}` | admin | Обновить пользователя |
| `POST` | `/users/{user_id}/block` | admin | Заблокировать пользователя |
| `POST` | `/users/{user_id}/unblock` | admin | Разблокировать |
| `POST` | `/users/{user_id}/approve` | admin | Подтвердить регистрацию |
| `POST` | `/users/{user_id}/reject` | admin | Отклонить регистрацию |
| `POST` | `/users/{user_id}/change-password` | admin | Принудительная смена пароля |
| `DELETE` | `/users/{user_id}` | admin | Удалить пользователя |

### Регистрация — `/registration`

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/registration/requests` | Создать заявку на регистрацию |
| `GET` | `/registration/requests` | Список заявок (admin) |
| `GET` | `/registration/requests/{request_id}` | Заявка по ID (admin) |
| `POST` | `/registration/requests/{request_id}/approve` | Одобрить заявку (admin) |
| `POST` | `/registration/requests/{request_id}/reject` | Отклонить заявку (admin) |
| `POST` | `/registration/requests/{request_id}/cancel` | Отменить заявку |

### Узлы файловой системы — `/nodes`

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/nodes/` | Список узлов (фильтр по родителю и др.) |
| `GET` | `/nodes/tree` | Дерево узлов |
| `GET` | `/nodes/search` | Поиск узлов по имени/типу |
| `POST` | `/nodes/thumbnails/batch` | Batch-запрос превью для списка ID |
| `GET` | `/nodes/{id}` | Получить узел по ID |
| `PATCH` | `/nodes/{id}` | Обновить узел |
| `POST` | `/nodes/{id}/rename` | Переименовать |
| `POST` | `/nodes/{id}/move` | Переместить в другую папку |
| `DELETE` | `/nodes/{id}` | Мягкое удаление (в корзину) |
| `POST` | `/nodes/{id}/download` | Presigned URL для скачивания файла |
| `GET` | `/nodes/{id}/stream` | Потоковая отдача (просмотр в браузере) |
| `GET` | `/nodes/{id}/thumbnail` | Presigned URL превью |
| `GET` | `/nodes/{id}/breadcrumbs` | Хлебные крошки (путь до корня) |
| `GET` | `/nodes/{id}/content` | Содержимое папки (пагинация) |

### Папки — `/folders`

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/folders/` | Создать папку |
| `GET` | `/folders/{id}` | Получить папку |
| `PATCH` | `/folders/{id}` | Обновить (описание, цвет) |
| `GET` | `/folders/{id}/content` | Содержимое (папки + файлы, пагинация) |
| `POST` | `/folders/{id}/archive` | Запустить фоновое архивирование → `BackgroundTask` |

> Переименование, перемещение и удаление папок выполняются через общий ресурс
> `/nodes/{id}` (`/rename`, `/move`, `DELETE`).

### Загрузка — `/uploads`

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/uploads/` | Создать upload-сессию |
| `GET` | `/uploads/` | Список сессий текущего пользователя |
| `GET` | `/uploads/{id}` | Состояние сессии |
| `POST` | `/uploads/{id}/parts/presigned` | Получить presigned PUT URL для частей |
| `POST` | `/uploads/{id}/parts/{part_number}/complete` | Подтвердить загрузку части (ETag) |
| `POST` | `/uploads/{id}/complete` | Завершить multipart upload |
| `POST` | `/uploads/{id}/abort` | Отменить и освободить ресурсы |
| `GET` | `/uploads/{id}/progress` | Прогресс загрузки |

### Скачивание — `/downloads`

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/downloads/bulk-archive` | Запустить архивирование набора узлов → `BackgroundTask` |
| `POST` | `/downloads/archive/{task_id}` | Presigned URL готового архива по задаче |

### Корзина — `/trash`

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/trash/` | Содержимое корзины |
| `POST` | `/trash/{id}/restore` | Восстановить элемент |
| `POST` | `/trash/{id}/purge` | Окончательно удалить элемент |
| `POST` | `/trash/empty` | Очистить всю корзину |
| `POST` | `/trash/cleanup` | Очистка истёкших элементов (admin) |

### Разрешения — `/permissions`

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/permissions/nodes/{node_id}` | Список разрешений узла |
| `POST` | `/permissions/grant` | Выдать доступ к узлу |
| `PATCH` | `/permissions/{id}` | Изменить уровень доступа |
| `POST` | `/permissions/revoke` | Отозвать доступ |
| `POST` | `/permissions/check` | Проверить право доступа |
| `GET` | `/permissions/nodes/{node_id}/effective` | Эффективные права на узел |

### Публичные ссылки — `/public-links`

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/public-links/` | Создать публичную ссылку |
| `GET` | `/public-links/` | Список ссылок пользователя |
| `GET` | `/public-links/{id}` | Получить ссылку |
| `PATCH` | `/public-links/{id}` | Обновить параметры |
| `POST` | `/public-links/{id}/revoke` | Отозвать |
| `GET` | `/public-links/public/{token}` | Публичный просмотр (без авторизации) |
| `POST` | `/public-links/public/{token}/access` | Доступ к защищённой ссылке (пароль) |
| `POST` | `/public-links/public/{token}/download` | Скачать файл по ссылке |
| `POST` | `/public-links/public/{token}/folder-download` | Создать архив публичной папки |
| `GET` | `/public-links/public/{token}/folder-download/{task_id}` | Статус / presigned URL архива |

### Квоты — `/quotas`

| Метод | Путь | Права | Описание |
|---|---|---|---|
| `GET` | `/quotas/me` | — | Квота текущего пользователя |
| `GET` | `/quotas/users/{user_id}` | admin | Квота пользователя |
| `PUT` | `/quotas/users/{user_id}` | admin | Создать/изменить лимиты |
| `POST` | `/quotas/check` | — | Проверить лимит для операции |
| `POST` | `/quotas/recalculate` | admin | Пересчитать использование |

### Фоновые задачи — `/tasks`

| Метод | Путь | Права | Описание |
|---|---|---|---|
| `POST` | `/tasks/` | admin / owner | Создать задачу |
| `GET` | `/tasks/` | admin / owner | Список задач |
| `GET` | `/tasks/{id}` | admin / owner | Состояние задачи |
| `GET` | `/tasks/{id}/result` | admin / owner | Результат выполнения |
| `GET` | `/tasks/{id}/progress` | admin / owner | Прогресс выполнения |
| `POST` | `/tasks/{id}/cancel` | admin / owner | Отменить задачу |
| `POST` | `/tasks/{id}/retry` | admin / owner | Повторить задачу |

### Аудит — `/audit`

| Метод | Путь | Права | Описание |
|---|---|---|---|
| `GET` | `/audit/logs` | admin | Журнал событий с фильтрацией |
| `GET` | `/audit/logs/{id}` | admin | Запись журнала |
| `GET` | `/audit/summary` | admin | Агрегированная сводка |
| `POST` | `/audit/export` | admin | Экспорт логов |
| `GET` | `/audit/users/{user_id}/latest` | admin | Последние события пользователя |

### Health — `/health`

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/health/live` | Liveness-проба (процесс жив) |
| `GET` | `/health/ready` | Readiness-проба (готов принимать трафик) |
| `GET` | `/health/` | Сводный health-check |
| `GET` | `/health/database` | Доступность PostgreSQL |
| `GET` | `/health/storage` | Доступность MinIO/S3 |

---

## Миграции

```bash
# Применить все ожидающие миграции
uv run alembic upgrade head

# Создать новую ревизию по изменениям в моделях
uv run alembic revision --autogenerate -m "краткое описание"

# Откатить последнюю ревизию
uv run alembic downgrade -1

# Посмотреть текущую ревизию
uv run alembic current

# История ревизий
uv run alembic history --verbose
```

**Существующие ревизии:**

- `ac57ae7d7abd` — Начальная схема: все таблицы, индексы, constraint'ы.
- `b3f1c2d4e5a6` — Добавлен составной индекс `(owner_id, parent_id, name)` на
  `file_system_nodes` для ускорения навигации по дереву.
- `c4d2e6f8a1b3` — Удалены неиспользуемые backup-значения из enum-перечислений
  (`BackgroundTaskType`, `AuditAction`).

При автогенерации Alembic сравнивает текущую схему БД с метаданными моделей SQLAlchemy.
После генерации ревизии **обязательно** проверяйте созданный файл — автогенератор не всегда
корректно обрабатывает сложные constraint'ы, частичные индексы и изменения enum-значений.

---

## Инициализация администратора

```bash
uv run python seed_admin.py

# Или с кастомными учётными данными:
ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD="MyPass123!" uv run python seed_admin.py
```

Скрипт идемпотентен: при повторном запуске ничего не перезаписывает, только сообщает
о состоянии каждого ресурса. Порядок действий:

1. Создать системные роли `admin` и `user` (если отсутствуют).
2. Создать пользователя-администратора (если отсутствует).
3. Назначить роль `admin` (если не назначена).
4. Создать квоту по умолчанию: 10 ГБ хранилища, макс. файл 1 ГБ, 10 000 файлов,
   100 публичных ссылок, 10 одновременных upload-сессий.

---

## Разработка

```bash
# Линт
uv run ruff check .

# Автоисправление
uv run ruff check --fix .

# Форматирование
uv run ruff format .

# Проверка типов
uv run ty check
```

Конфигурация ruff находится в `pyproject.toml`. Перед коммитом рекомендуется запускать
`ruff check` и `ty check` — CI проверяет оба.

При добавлении новой модели SQLAlchemy:

1. Создать файл в `database/models/`.
2. Добавить импорт в `database/models/__init__.py` (иначе Alembic не увидит модель).
3. Добавить репозиторий в `database/repositories/`.
4. Зарегистрировать репозиторий как свойство `UnitOfWork` в `database/unit_of_work.py`.
5. Сгенерировать миграцию: `alembic revision --autogenerate -m "add_<model_name>"`.
