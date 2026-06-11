# LocalCloud — Backend

FastAPI-приложение и фоновый worker для self-hosted хранилища файлов. Координирует
multipart-загрузку напрямую в MinIO/S3, хранит метаданные в PostgreSQL, проверяет
права доступа и выполняет фоновые задачи (архивы, превью, очистка, квоты).

Часть монорепозитория **LocalCloud** — общий обзор и запуск всего стека в
[корневом README](../README.md).

---

## Содержание

- [Стек и зависимости](#стек-и-зависимости)
- [Структура каталогов](#структура-каталогов)
- [Запуск](#запуск)
- [Конфигурация](#конфигурация)
- [Архитектура](#архитектура)
- [База данных](#база-данных)
- [Безопасность](#безопасность)
- [Хранилище (MinIO/S3)](#хранилище-minios3)
- [Фоновый worker](#фоновый-worker)
- [API](#api)
- [Миграции и seed](#миграции-и-seed)
- [Тесты](#тесты)
- [Docker](#docker)

---

## Стек и зависимости

- **Python** `>= 3.13`, менеджер пакетов [`uv`](https://docs.astral.sh/uv/).
- **Web** — FastAPI, uvicorn (`[standard]`).
- **БД** — SQLAlchemy 2 (async) + asyncpg, Alembic (миграции).
- **Конфигурация** — Pydantic v2 + pydantic-settings.
- **Безопасность** — python-jose (JWT), passlib (`[argon2,bcrypt]`).
- **Хранилище** — MinIO SDK (S3-совместимое).
- **Превью** — Pillow (изображения), PyMuPDF/`fitz` (PDF), ffmpeg (кадр из видео).
- **Линтер** — ruff; типы — ty.
- **Тесты** — pytest, pytest-asyncio (`asyncio_mode = "auto"`), pytest-cov; httpx.

Все зависимости и их версии — в [`pyproject.toml`](./pyproject.toml).

---

## Структура каталогов

| Каталог | Назначение |
|---|---|
| `app/` | Жизненный цикл приложения и HTTP-обвязка: `main.py` (сборка FastAPI), `lifecycle.py` (startup/shutdown), `middleware.py` (request-context, backpressure, timeout, security-headers, CORS, gzip), `exception_handlers.py`, `dependencies.py`. |
| `api/` | Роутеры FastAPI: `router.py` (агрегатор), `dependencies.py` (DI сервисов), `v1/*.py` (по одному файлу на домен). |
| `core/` | `config.py` (12 групп настроек Pydantic) и `constants.py` (литералы-дефолты + регулярки/лимиты). |
| `schemas/` | Pydantic-схемы запросов/ответов (DTO) по доменам. |
| `services/` | Бизнес-логика. 16 сервисов: `auth`, `users`, `registration`, `nodes`, `files`, `folders`, `uploads`, `downloads`, `trash`, `permissions`, `access`, `public_links`, `quotas`, `tasks`, `audit`, `health` (+ `exceptions.py`). |
| `database/` | ORM-модели (`models/`), репозитории (`repositories/`), Unit of Work (`unit_of_work.py`), фабрика сессий (`client.py`), health, транзакционные хелперы. |
| `security/` | Аутентификация и права: `jwt/`, `cookies/`, `password/`, `permissions/`, `dependencies/`. |
| `storage/` | Интеграция с MinIO: `client.py`, `buckets.py`, `objects.py`, `multipart.py`, `presigned.py`, `keys.py`, `metadata.py`, `capacity.py`, `integrity.py`, `health.py`. |
| `workers/` | Фоновый процесс: `app.py` (точка входа), `dispatcher.py`, `scheduler.py`, `registry.py`, обработчики (`previews`, `archives`, `cleanup`, `uploads`, `public_links`, `quotas`, `integrity`), `context.py`, `types.py`, `lifecycle.py`. |
| `migrations/` | Alembic: `env.py` + `versions/`. |
| `tests/` | `unit/` и `integration/api/` (+ `conftest.py`). |
| `seed_admin.py` | Идемпотентное создание администратора при старте. |

Поток запроса: **router → service → Unit of Work → repository → модель**; storage
и security вызываются из сервисов. Сервисы не зависят от FastAPI, что упрощает их
переиспользование во worker'е.

---

## Запуск

### В составе стека (Docker)

См. [корневой README](../README.md#быстрый-старт-docker). Контейнеры `api` и
`worker` собираются из одного образа [`Dockerfile`](./Dockerfile); `api` при старте
применяет миграции и создаёт администратора (см. [Docker](#docker)).

### Локально (uv)

Нужны запущенные PostgreSQL и MinIO (см. корневой README) и корневой `.env`.

```bash
cd backend
uv sync                                   # установить зависимости
uv run alembic upgrade head               # миграции
uv run python seed_admin.py               # администратор (идемпотентно)

uv run uvicorn app.main:app --reload      # API → http://localhost:8000
uv run python -m workers.app              # worker (отдельный терминал)
```

Полезные команды:

```bash
uv run ruff check .                        # линтер
uv run pytest                              # все тесты
uv run pytest tests/unit -q                # только unit
uv run pytest --cov=. --cov-report=html    # покрытие
uv run alembic revision --autogenerate -m "msg"   # новая миграция
```

Документация OpenAPI (в debug-режиме) — `http://localhost:8000/docs`.

---

## Конфигурация

Единый источник — корневой `.env` (`ENV_FILE` в `core/constants.py`). Значения
читаются через `core/config.py`: каждая группа — отдельный `BaseSettings` с
env-алиасами в ВЕРХНЕМ_РЕГИСТРЕ; дефолты-литералы лежат в `core/constants.py`.
Доступ — через кэшированный `get_settings()`.

> Значения по умолчанию в коде подобраны для надёжной работы; пресеты
> `.env.example*` под конкретные хосты могут их переопределять (напр. пул БД 5+5
> для 1 ГБ). Подбор `.env` под сервер — [`docs/env-tuning-guide.md`](../docs/env-tuning-guide.md)
> и генератор [`scripts/generate_env.py`](../scripts/generate_env.py).

### Приложение и логирование

| Переменная | Default | Описание |
|---|---|---|
| `APP_NAME` | `LocalCloud` | Название. |
| `APP_VERSION` | `0.1.0` | Версия. |
| `DEBUG` | `false` | Debug-режим (включает `/docs`). |
| `API_PREFIX` / `API_V1_PREFIX` | `/api` / `/api/v1` | Префиксы. |
| `LOG_LEVEL` | `INFO` | Уровень логирования. |
| `LOG_JSON` | `false` | JSON-формат логов. |
| `LOG_FILE_ENABLED` / `LOG_FILE_PATH` | `false` / `logs/localcloud.log` | Запись в файл. |

### Безопасность и cookie

| Переменная | Default | Описание |
|---|---|---|
| `SECRET_KEY` | dev-ключ | Подпись JWT. **Сменить в production.** |
| `JWT_ALGORITHM` | `HS256` | Алгоритм. |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `localcloud` / `localcloud-users` | iss/aud. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | TTL access-токена. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | TTL refresh-токена. |
| `PASSWORD_HASH_SCHEME` | `bcrypt` | Схема хеширования. |
| `ACCESS_COOKIE_NAME` / `REFRESH_COOKIE_NAME` | `localcloud_access` / `localcloud_refresh` | Имена cookie. |
| `COOKIE_SECURE` | `false` | `true` за HTTPS. |
| `COOKIE_HTTPONLY` | `true` | Запрет доступа из JS. |
| `COOKIE_SAMESITE` | `lax` | Политика SameSite. |
| `COOKIE_DOMAIN` / `COOKIE_PATH` | `null` / `/` | Домен/путь. |

### База данных (пул на процесс)

| Переменная | Default | Описание |
|---|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost` / `5432` | Адрес. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `localcloud` | Учётные данные/БД. |
| `POSTGRES_ECHO` | `false` | Логировать SQL. |
| `POSTGRES_POOL_SIZE` | `10` | Базовый размер пула. |
| `POSTGRES_MAX_OVERFLOW` | `5` | Доп. подключения сверх пула. |
| `POSTGRES_POOL_TIMEOUT` | `30` | Таймаут получения подключения, с. |
| `POSTGRES_POOL_RECYCLE` | `1800` | Переподключение, с. |
| `POSTGRES_POOL_PRE_PING` | `true` | Проверка перед использованием. |

> Коннектов в кластере: `(UVICORN_WORKERS + 1) × (POOL_SIZE + MAX_OVERFLOW)`;
> держите ниже `max_connections` PostgreSQL с запасом ~10.

### Хранилище (MinIO/S3)

| Переменная | Default | Описание |
|---|---|---|
| `MINIO_HOST` / `MINIO_PORT` | `localhost` / `9000` | Внутренний endpoint (для подписи). |
| `MINIO_PUBLIC_HOST` / `MINIO_PUBLIC_PORT` | `localhost` / `9000` | Внешний endpoint (как видит клиент). |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | `localcloud` / `localcloud_password` | Ключи. |
| `MINIO_SECURE` | `false` | HTTPS. |
| `MINIO_REGION` | `us-east-1` | Регион. |
| `STORAGE_CAPACITY_BYTES` | `null` | Ёмкость пула квот (иначе 85% диска MinIO). |
| `STORAGE_EXECUTOR_MAX_WORKERS` | `4` | Потоки под блокирующий MinIO SDK (1–64). |

### Worker

| Переменная | Default | Описание |
|---|---|---|
| `WORKER_ENABLED` | `true` | Включить worker. |
| `WORKER_POLL_INTERVAL_SECONDS` | `5` | Интервал опроса очереди. |
| `WORKER_IDLE_SLEEP_SECONDS` | `2` | Пауза при пустой очереди. |
| `WORKER_BATCH_SIZE` | `10` | Размер выборки задач за цикл (1–100). |
| `WORKER_MAX_CONCURRENT_TASKS` | `4` | Параллельных обработчиков (1–32). |
| `WORKER_SHUTDOWN_TIMEOUT_SECONDS` | `30` | Таймаут остановки. |
| `WORKER_TASK_LOCK_TTL_SECONDS` | `300` | TTL блокировки задачи (≥30). |
| `WORKER_STALE_TASK_LOCK_SECONDS` | `900` | Возраст «протухшей» блокировки (≥TTL). |
| `WORKER_RETRY_DELAY_SECONDS` | `60` | Базовая задержка retry. |
| `WORKER_MAX_RETRY_DELAY_SECONDS` | `3600` | Макс. задержка retry. |
| `WORKER_SCHEDULER_ENABLED` | `true` | Периодические задачи. |
| `WORKER_CLEAN_TRASH_INTERVAL_SECONDS` | `3600` | Очистка корзины. |
| `WORKER_CLEAN_EXPIRED_UPLOADS_INTERVAL_SECONDS` | `1800` | Очистка истёкших загрузок. |
| `WORKER_CLEAN_EXPIRED_PUBLIC_LINKS_INTERVAL_SECONDS` | `3600` | Очистка истёкших ссылок. |
| `WORKER_RECALCULATE_QUOTAS_INTERVAL_SECONDS` | `86400` | Пересчёт квот. |
| `WORKER_STORAGE_INTEGRITY_INTERVAL_SECONDS` | `86400` | Проверка целостности. |
| `WORKER_CLEANUP_BATCH_SIZE` / `WORKER_INTEGRITY_BATCH_SIZE` / `WORKER_QUOTA_BATCH_SIZE` | `100` | Размеры batch (1–100). |

### Сервер (backpressure)

| Переменная | Default | Описание |
|---|---|---|
| `MAX_CONCURRENT_REQUESTS` | `64` | Потолок одновременных запросов (сверх — `503 Retry-After`). |
| `REQUEST_TIMEOUT_SECONDS` | `90` | Таймаут формирования ответа (стриминг не ограничивает). |

### Превью

| Переменная | Default | Описание |
|---|---|---|
| `PREVIEW_GENERATION_ENABLED` | `true` | Мастер-флаг; `false` — worker не рендерит (для слабого хоста). |
| `PREVIEW_RENDER_CONCURRENCY` | `1` | Параллельных рендеров (1–16). |
| `PREVIEW_IMAGE_MAX_SOURCE_MB` | `25` | Лимит исходного изображения. |
| `PREVIEW_PDF_MAX_SOURCE_MB` | `30` | Лимит исходного PDF. |
| `PREVIEW_VIDEO_MAX_SOURCE_MB` | `80` | Лимит исходного видео. |
| `PREVIEW_IMAGE_MAX_DIMENSION` | `400` | Длинная сторона растра превью. |
| `PREVIEW_IMAGE_QUALITY` | `75` | Качество WebP (1–100). |
| `PREVIEW_IMAGE_MAX_PIXELS` | `40000000` | Защита от «decompression bomb». |
| `PREVIEW_PDF_RENDER_DPI` | `120` | DPI растрирования PDF (36–600). |
| `PREVIEW_PDF_RENDER_MAX_DIM` | `1600` | Потолок растра PDF, px. |
| `PREVIEW_VIDEO_FFMPEG_TIMEOUT_SECONDS` | `30` | Таймаут ffmpeg. |

### Архивы и скачивание

| Переменная | Default | Описание |
|---|---|---|
| `ARCHIVE_MAX_FILES` | `10000` | Макс. файлов в архиве. |
| `ARCHIVE_MAX_TOTAL_MB` | `2048` | Макс. суммарный размер источников. |
| `ARCHIVE_STREAM_CHUNK_BYTES` | `1048576` | Блок потоковой передачи в ZIP (≥4096). |
| `ARCHIVE_DISK_SAFETY_FACTOR` | `1.1` | Запас места на диске (≥1.0). |
| `THUMBNAIL_BATCH_CONCURRENCY` | `6` | Параллелизм thumbnail-батча (1–64). |

### Флаги функциональности (отдаются фронтенду через `GET /config`)

| Переменная | Default | Описание |
|---|---|---|
| `FEATURE_PREVIEWS_ENABLED` | `true` | Показывать миниатюры. |
| `FEATURE_FILE_VIEWER_ENABLED` | `true` | Просмотрщик содержимого. |
| `FEATURE_MEDIA_PLAYBACK_ENABLED` | `true` | Проигрывание аудио/видео. |
| `FEATURE_FILE_EDITING_ENABLED` | `true` | Редактирование текстовых файлов. |

### Администратор (seed)

`ADMIN_EMAIL` (`admin@localcloud.dev`), `ADMIN_USERNAME` (`admin`),
`ADMIN_PASSWORD` (`Admin@LocalCloud123`).

---

## Архитектура

### HTTP-обвязка (`app/`)

`app/main.py` собирает FastAPI, подключает роутеры и middleware. Цепочка
middleware (снаружи внутрь): **RequestContext** (request/correlation-id,
логирование) → **ConcurrencyLimit** (backpressure, `503` сверх
`MAX_CONCURRENT_REQUESTS`) → **RequestTimeout** (`504` по
`REQUEST_TIMEOUT_SECONDS`) → **SecurityHeaders** → **CORS** → **GZip**.
`lifecycle.py` на старте проверяет БД/хранилище и создаёт бакеты, на остановке
освобождает пулы и storage-executor.

### Слой сервисов (`services/`)

Бизнес-логика, не зависящая от FastAPI. Сервисы получают зависимости через DI
(`api/dependencies.py`), открывают `UnitOfWork`, вызывают репозитории и storage,
пишут аудит. Те же сервисы переиспользуются во worker'е.

### Репозитории и Unit of Work (`database/`)

`UnitOfWork` — транзакционный контейнер: создаёт `AsyncSession` (или принимает
внешнюю), лениво отдаёт репозитории как атрибуты (`uow.users`, `uow.nodes`,
`uow.permissions`, …), коммитит **явно** (`await uow.commit()`) и откатывает при
выходе без коммита. Репозитории инкапсулируют запросы (включая рекурсивные CTE
для деревьев предков/потомков и наследования прав).

---

## База данных

### Модели (`database/models/`)

`users`, `filesystem` (FileSystemNode → File/Folder), `uploads` (UploadSession,
UploadPart), `tokens` (refresh-токены/сессии), `links` (PublicLink), `permissions`
(NodePermission), `quotas` (UserQuota), `registration` (RegistrationRequest),
`tasks` (BackgroundTask), `audit` (AuditLog). Базовый класс — UUID-PK + timestamps
(`base.py`, `mixins.py`); общие перечисления — `enums.py`.

### Репозитории (`database/repositories/`)

`base.py` (дженерик CRUD) + `users`, `files`, `folders`, `nodes`, `permissions`,
`quotas`, `links`, `sessions`, `parts`, `tokens`, `tasks`, `trash`, `registration`,
`audit`.

### Ключевые перечисления (`database/models/enums.py`)

- **SystemRole** — `admin`, `user`.
- **NodeType** — `file`, `folder`.
- **PermissionLevel** — `read`, `download`, `write`, `delete`, `owner`.
- **PermissionSubjectType** — `user`, `role`, `public_link`.
- **PublicLinkPermissionType** — `view`, `download`, `upload`.
- **BackgroundTaskType** — `create_folder_archive`, `clean_trash`,
  `clean_expired_uploads`, `clean_expired_public_links`, `delete_object_from_storage`,
  `check_storage_integrity`, `generate_file_preview`, `recalculate_user_quota`.
- **BackgroundTaskStatus** — `pending`, `running`, `completed`, `failed`, `cancelled`.
- **AuditResourceType**, **AuditAction**, статусы пользователей/превью/объектов и др.

---

## Безопасность

`security/` разбит на подсистемы:

- **`jwt/`** — выпуск/валидация JWT (HS256), проверка `iss`/`aud`/срока, типы токенов.
- **`cookies/`** — установка/очистка httpOnly-cookie access/refresh на ответе,
  извлечение refresh-токена из запроса.
- **`password/`** — хеширование (passlib, bcrypt/argon2) и проверка сложности.
- **`permissions/`** — модель прав (`PermissionLevel`), проверка доступа к узлу с
  учётом владельца и наследования от родительских папок.
- **`dependencies/`** — FastAPI-зависимости: `CurrentActiveUserDependency`
  (требует аутентификации и статуса ACTIVE), `CurrentAdminUserDependency`
  (роль `admin`) и зависимости проверки прав на узел (read/write/delete) прямо в
  сигнатуре эндпоинта.

Поток входа: `POST /auth/login` ставит access/refresh-cookie; при `401` фронтенд
дёргает `POST /auth/refresh` (silent-refresh); `POST /auth/logout` отзывает сессию.

---

## Хранилище (MinIO/S3)

`storage/client.py` — асинхронный фасад над блокирующим MinIO SDK: вызовы
выполняются в общем `ThreadPoolExecutor` (`STORAGE_EXECUTOR_MAX_WORKERS`).

- **Бакеты** — `localcloud-files` (файлы), `localcloud-temp` (multipart/временное),
  `localcloud-archives` (ZIP).
- **Ключи объектов** (`keys.py`) — генерация/валидация путей по `user_id`/`file_id`.
- **Presigned URL** (`presigned.py`) — подпись локальная (без сети); срок по
  умолчанию 15 мин (макс. 7 суток). Backend подписывает под `MINIO_HOST`,
  поэтому шлюз восстанавливает внутренний `Host`.
- **Multipart** (`multipart.py`) — init/part/complete/abort; часть 8 МБ (мин. 5 МБ),
  до 10000 частей.
- **Потоковые операции** (`objects.py`) — скачивание во временный файл и Range,
  чтобы не держать объект целиком в RAM.
- **Capacity / integrity** — ёмкость пула квот и проверка соответствия БД ↔ MinIO.

Файловый трафик идёт **мимо backend** — напрямую браузер ↔ MinIO по presigned-URL.

---

## Фоновый worker

Отдельный процесс (`python -m workers.app`), не обслуживающий HTTP.

- **Dispatcher** (`dispatcher.py`) — опрашивает таблицу `tasks`, берёт батч
  (`WORKER_BATCH_SIZE`), блокирует задачи по `worker_id` с TTL, исполняет
  обработчики из реестра с ограничением `asyncio.Semaphore(WORKER_MAX_CONCURRENT_TASKS)`,
  обновляет статус и освобождает «протухшие» блокировки.
- **Scheduler** (`scheduler.py`) — периодические задачи по интервалам: очистка
  корзины, истёкших загрузок и публичных ссылок, пересчёт квот, проверка
  целостности хранилища.
- **Retry** — экспоненциальная задержка от `WORKER_RETRY_DELAY_SECONDS` до
  `WORKER_MAX_RETRY_DELAY_SECONDS`.

Типы задач и обработчики:

| Тип (`BackgroundTaskType`) | Обработчик | Действие |
|---|---|---|
| `create_folder_archive` | `archives.py` | Сборка ZIP во временный файл, стрим в MinIO; лимиты `ARCHIVE_*`. |
| `generate_file_preview` | `previews.py` | Рендер миниатюры (Pillow/PyMuPDF/ffmpeg); лимиты `PREVIEW_*`. |
| `clean_trash` | `cleanup.py` | Удаление узлов из корзины + объектов. |
| `clean_expired_uploads` | `uploads.py` | Отмена истёкших multipart-сессий. |
| `clean_expired_public_links` | `public_links.py` | Отзыв истёкших ссылок. |
| `delete_object_from_storage` | `cleanup.py` | Удаление объекта из MinIO. |
| `check_storage_integrity` | `integrity.py` | Сверка БД ↔ MinIO. |
| `recalculate_user_quota` | `quotas.py` | Пересчёт занятого объёма. |

---

## API

Все маршруты — под префиксом `/api/v1` (всего **104** эндпоинта). Если не указано
иное — требуется аутентификация (cookie). Полные схемы запросов/ответов — в
OpenAPI (`/docs` при `DEBUG=true`).

**Доступ:** 🌐 публичный (без auth) · 🔑 любой авторизованный · 🛡️ только admin.

### `auth` — `/auth`
| Метод | Путь | Доступ |
|---|---|---|
| POST | `/auth/login` | 🌐 |
| POST | `/auth/refresh` | 🌐 (refresh-cookie) |
| POST | `/auth/logout` | 🔑 |
| GET | `/auth/me` | 🔑 |
| POST | `/auth/password/change` | 🔑 |
| GET | `/auth/sessions` | 🔑 |
| DELETE | `/auth/sessions/{session_id}` | 🔑 |

### `registration` — `/registration`
| Метод | Путь | Доступ |
|---|---|---|
| POST | `/registration/requests` | 🌐 (заявка) |
| POST | `/registration/requests/{request_id}/cancel` | 🌐 |
| GET | `/registration/requests` | 🛡️ |
| GET | `/registration/requests/{request_id}` | 🛡️ |
| POST | `/registration/requests/{request_id}/approve` | 🛡️ |
| POST | `/registration/requests/{request_id}/reject` | 🛡️ |

### `users` — `/users`
| Метод | Путь | Доступ |
|---|---|---|
| GET / PATCH | `/users/me` | 🔑 |
| GET | `/users/lookup` | 🔑 (поиск для шаринга) |
| GET | `/users/` | 🛡️ |
| GET / PATCH / DELETE | `/users/{user_id}` | 🛡️ |
| POST | `/users/{user_id}/approve` · `/reject` · `/block` · `/unblock` · `/change-password` | 🛡️ |

### `quotas` — `/quotas`
| Метод | Путь | Доступ |
|---|---|---|
| GET / POST | `/quotas/me` · `/quotas/check` | 🔑 |
| GET | `/quotas/server/capacity` | 🛡️ |
| GET / PUT | `/quotas/users/{user_id}` · POST `/quotas/recalculate` | 🛡️ |

### `nodes` — `/nodes` (файлы и папки)
| Метод | Путь |
|---|---|
| GET | `/nodes/` · `/nodes/tree` · `/nodes/search` |
| POST | `/nodes/thumbnails/batch` |
| GET | `/nodes/{node_id}` · `/breadcrumbs` · `/content` · `/thumbnail` · `/stream` |
| PATCH | `/nodes/{node_id}` |
| POST | `/nodes/{node_id}/rename` · `/move` · `/copy` · `/download` |
| DELETE | `/nodes/{node_id}` (мягкое удаление) |

Все требуют 🔑 и соответствующего права на узел (read/write/delete).

### `folders` — `/folders`
`POST /folders/` · `GET /folders/{id}` · `PATCH /folders/{id}` ·
`GET /folders/{id}/content` · `POST /folders/{id}/archive` (фоновая задача). 🔑

### `uploads` — `/uploads` (multipart)
`POST /uploads/` (инициировать) · `GET /uploads/` · `GET /uploads/{id}` ·
`GET /uploads/{id}/progress` · `POST /uploads/{id}/parts/presigned` ·
`POST /uploads/{id}/parts/{part_number}/complete` · `POST /uploads/{id}/complete` ·
`POST /uploads/{id}/abort`. 🔑

### `downloads` — `/downloads`
`POST /downloads/archive/{task_id}` (ссылка на готовый архив) ·
`POST /downloads/bulk-archive` (архив набора узлов). 🔑

### `trash` — `/trash`
`GET /trash/` · `POST /trash/{trash_item_id}/restore` ·
`POST /trash/{trash_item_id}/purge` (🔑) · `POST /trash/empty` ·
`POST /trash/cleanup` (🛡️).

### `permissions` — `/permissions` (доступ между пользователями)
`POST /permissions/grant` · `POST /permissions/revoke` · `POST /permissions/check` ·
`PATCH /permissions/{permission_id}` · `GET /permissions/nodes/{node_id}` ·
`GET /permissions/nodes/{node_id}/effective` · `GET /permissions/shared-with-me` ·
`GET /permissions/shared-by-me`. 🔑

### `public_links` — `/public-links`
Управление (🔑): `POST /public-links/` · `GET /public-links/` ·
`GET /public-links/node-ids` · `GET /public-links/{link_id}` ·
`PATCH /public-links/{link_id}` · `POST /public-links/{link_id}/revoke`.
Публичный доступ по токену (🌐, опц. пароль): `GET /public-links/public/{token}` ·
`POST /public-links/public/{token}/access` · `/download` · `/thumbnail` ·
`/folder-download` · `GET …/folder-download/{task_id}`.

### `tasks` — `/tasks` (фоновые задачи)
`GET /tasks/` · `GET /tasks/{id}` · `/progress` · `/result` ·
`POST /tasks/{id}/cancel` (🔑) · `POST /tasks/` · `POST /tasks/{id}/retry` (🛡️).

### `audit` — `/audit` 🛡️
`GET /audit/logs` · `GET /audit/logs/{log_id}` · `GET /audit/summary` ·
`GET /audit/users/{user_id}/latest` · `POST /audit/export`.

### `config` — `/config` 🌐
`GET /config` — публичные флаги функциональности (для фронтенда).

### `health` — `/health`
`GET /health/live` · `GET /health/ready` (🌐) ·
`GET /health/` · `/database` · `/storage` (🛡️).

---

## Миграции и seed

Alembic настроен на `migrations/` (async). История версий:

1. `ac57ae7d7abd` — начальная схема;
2. `b3f1c2d4e5a6` — индекс активных детей узла;
3. `c4d2e6f8a1b3` — чистка enum-значений;
4. `d5e7f9a0b1c2` — удаление верификации email;
5. `e6f8a1b3c4d5` — замена таблицы ролей на enum `SystemRole`;
6. `f7a9c2b4d6e8` — удаление версионирования файлов.

```bash
uv run alembic upgrade head                       # применить
uv run alembic revision --autogenerate -m "msg"   # создать
uv run alembic downgrade -1                        # откатить на шаг
```

`seed_admin.py` идемпотентно создаёт администратора (и его квоту) из `ADMIN_*`.
В Docker запускается автоматически при `RUN_MIGRATIONS=true`.

---

## Тесты

pytest (`asyncio_mode = "auto"`, `pythonpath = ["."]`). Структура:

- `tests/unit/` — модульные тесты (config, сервисы, репозитории, worker, security,
  storage, схемы) — **117** файлов.
- `tests/integration/api/` — тесты эндпоинтов через `TestClient` с подменой
  зависимостей — **14** файлов.

```bash
uv run pytest                          # всё
uv run pytest tests/unit -q            # unit
uv run pytest tests/integration -q     # integration
uv run pytest --cov=. --cov-report=term-missing
```

---

## Docker

[`Dockerfile`](./Dockerfile) — образ на базе `uv:python3.13-bookworm-slim`:
ставит `ffmpeg` (кадры видео), синхронизирует зависимости (`uv sync --frozen`),
делает entrypoint исполняемым, открывает порт `8000`. Один образ используется и
для `api`, и для `worker` (отличаются командой запуска).

[`docker-entrypoint.sh`](./docker-entrypoint.sh): ждёт PostgreSQL и MinIO (таймаут
180 с), при `RUN_MIGRATIONS=true` выполняет `alembic upgrade head` и
`python seed_admin.py`, затем `exec "$@"` (uvicorn для `api`, `workers.app` для
`worker`). Сервис `api` запускается с `RUN_MIGRATIONS=true`, `worker` — с `false`.
