# LocalCloud

**Self-hosted облачное хранилище файлов** — приватная альтернатива Google Drive / Dropbox,
которую можно развернуть на собственном сервере. Загрузка больших файлов напрямую в объектное
хранилище, папки с вложенностью, корзина, общий доступ по ссылкам, фоновая упаковка в архивы,
квоты и админ-панель.

> Проект рассчитан на небольшие команды (**5–10 одновременных пользователей**).

---

## Возможности

- 📁 **Файлы и папки** — древовидная структура с произвольной вложенностью, перемещение,
  переименование, массовые операции.
- ⬆️ **Многочастичная загрузка** — клиент пишет части напрямую в MinIO/S3 по presigned-URL,
  backend только координирует сессию (не проксирует трафик файлов).
- ⬇️ **Скачивание архивами** — папки и произвольный набор элементов упаковываются в ZIP фоновым
  воркером и отдаются по временной ссылке.
- 🗑️ **Корзина** — мягкое удаление с восстановлением.
- 🔗 **Публичные ссылки** — общий доступ к файлам/папкам с настройками.
- 📊 **Квоты** — лимиты на объём и количество активных сессий загрузки.
- 🖼️ **Превью** — миниатюры изображений генерируются фоновым воркером.
- 👤 **Аутентификация** — JWT в httpOnly-cookie, регистрация по заявке с одобрением
  администратором, роли и права.
- 🛠️ **Админ-панель** — пользователи, заявки на регистрацию, журнал аудита, фоновые задачи.
- 📱 **Адаптивный интерфейс** — тёмная/светлая тема, мобильная вёрстка.

---

## Архитектура

```
┌──────────────┐    presigned PUT / GET     ┌──────────────┐
│   Браузер    │ ─────────────────────────► │  MinIO / S3  │
│ (React SPA)  │ ◄───────────────────────── │  (объекты)   │
└──────┬───────┘                            └──────▲───────┘
       │ REST  /api/v1                             │
       ▼                                           │ presign / put / get
┌──────────────┐      asyncpg        ┌──────────────┐
│   FastAPI    │ ──────────────────► │  PostgreSQL  │
│  (API)       │ ◄────────────────── │  (метаданные)│
└──────┬───────┘                     └──────▲───────┘
       │ ставит задачи (таблица tasks)      │
       ▼                                    │
┌──────────────┐                            │
│ Worker-проц. │ ───────────────────────────┘
│ (архивы,     │   читает объекты, строит ZIP,
│  превью,     │   чистит истёкшие сессии и т.д.
│  очистка)    │
└──────────────┘
```

- **Backend** координирует загрузку/скачивание, хранит метаданные в PostgreSQL и ставит фоновые
  задачи. Сам файловый трафик идёт мимо него — напрямую между браузером и хранилищем.
- **Worker** — отдельный процесс, разбирающий очередь задач (`CREATE_FOLDER_ARCHIVE`, генерация
  превью, очистка истёкших upload-сессий, обслуживание публичных ссылок).
- **Frontend** — SPA на React, общается с backend по `/api/v1`, а с хранилищем — по presigned-URL.

---

## Стек

| Слой | Технологии |
|---|---|
| **Frontend** | React 19.2, TypeScript 6, Vite 8, React Router 7, TanStack Query 5, Tailwind CSS v4, Shadcn UI / Radix UI, Axios, Sonner |
| **Backend** | Python 3.13+, FastAPI 0.125+, SQLAlchemy 2 (async) + asyncpg, Pydantic v2, Alembic, python-jose (JWT), passlib (bcrypt/argon2), Pillow |
| **Хранилище** | PostgreSQL 16 (метаданные), MinIO / S3-совместимое (объекты, MinIO SDK 7.2+) |
| **Инфраструктура** | Docker Compose, nginx (шлюз + SPA-сервер), `uv` (Python), `npm`, `ruff` + `ty`, ESLint + Prettier |

---

## Структура репозитория

```
LocalCloud/
├── backend/            FastAPI API + фоновый worker  →  backend/README.md
│   ├── Dockerfile          образ api + worker (uv)
│   └── docker-entrypoint.sh ожидание БД/MinIO, миграции, seed
├── frontend/           React SPA (Vite)              →  frontend/README.md
│   ├── Dockerfile          сборка SPA → статика в nginx
│   └── nginx.conf          SPA-сервер (history-fallback)
├── nginx/              Шлюз / reverse-proxy
│   ├── Dockerfile
│   └── nginx.conf          / → SPA, /api → api, bucket-пути → MinIO
├── docker-compose.yml  Весь стек (6 сервисов)
├── .env.example        Шаблон конфигурации Docker-стека (→ копируется в .env)
├── CHANGELOG.md        История изменений (Keep a Changelog, SemVer)
└── README.md           Этот файл
```

---

## Запуск в Docker (рекомендуется)

Нужен только **Docker** с плагином Compose. Скопируйте шаблон конфигурации и
поднимите стек:

```bash
git clone https://github.com/magomedov-dev/LocalCloud && cd LocalCloud
cp .env.example .env        # при необходимости поправьте секреты
docker compose up -d --build
```

Compose автоматически читает корневой `.env` (и для подстановки `${VAR}`, и как
`env_file` контейнеров `api`/`worker`) — отдельный флаг `--env-file` не нужен.
`.env` в `.gitignore`, в репозитории лежит только шаблон `.env.example`.

Поднимаются шесть сервисов:

| Сервис     | Что это | Доступ |
|------------|---------|--------|
| `nginx`    | Шлюз / reverse-proxy — единая точка входа | **http://localhost** |
| `frontend` | Статический SPA (nginx отдаёт собранный Vite-бандл) | через шлюз |
| `api`      | FastAPI (uvicorn, число воркеров — `UVICORN_WORKERS` в `.env`) | через шлюз → `/api` |
| `worker`   | Фоновый обработчик задач (архивы, превью, очистка) | — |
| `postgres` | PostgreSQL 16 (метаданные) | внутренняя сеть |
| `minio`    | MinIO (объекты) | консоль на **http://localhost:9090** |

Один origin (`http://localhost`) обслуживает SPA, `/api` и presigned-ссылки на
объекты — поэтому CORS не нужен. Шлюз `nginx` проксирует bucket-пути в MinIO,
**восстанавливая внутренний `Host`**, под который backend подписывает
presigned-URL (иначе MinIO вернёт `SignatureDoesNotMatch`).

При первом старте сервис `api` сам применяет миграции (`alembic upgrade head`) и
создаёт администратора. Бакеты создаются автоматически. Готово, когда `api`
перейдёт в статус healthy:

```bash
docker compose ps
docker compose logs -f api          # следить за стартом
```

Откройте **http://localhost** и войдите (учётка по умолчанию ниже).

```bash
docker compose down                 # остановить (данные в volume сохранятся)
docker compose down -v              # остановить и удалить данные (postgres + minio)
```

> Postgres и MinIO **не** публикуются на хост — стек не конфликтует с локальными
> dev-контейнерами на портах 5432/9000/9001. Наружу открыты только `80` (шлюз) и
> `9090` (консоль MinIO).

> ⚙️ Число uvicorn-воркеров задаётся `UVICORN_WORKERS` в `.env` (по умолчанию 4).
> Каждый воркер-процесс держит независимый пул соединений. При 4 API-воркерах и 1
> worker-процессе потребуется `5 × (POSTGRES_POOL_SIZE + POSTGRES_MAX_OVERFLOW)` соединений
> плюс резерв для системных задач. Значения по умолчанию: `POOL_SIZE=20`,
> `MAX_OVERFLOW=10` — итого до 150 соединений; стандартный `max_connections=200`
> PostgreSQL покрывает это с запасом. При увеличении числа воркеров пересчитайте формулу.

> ⚠️ Перед публичным развёртыванием смените секреты в `.env` (`SECRET_KEY`,
> `POSTGRES_PASSWORD`, `MINIO_SECRET_KEY`, `ADMIN_PASSWORD`), выставьте
> `COOKIE_SECURE=true` за HTTPS и задайте `MINIO_PUBLIC_HOST/PORT` под ваш домен.

---

## Локальная разработка (без Docker)

Нужны **Docker** (для PostgreSQL и MinIO), **Python 3.13+** с [`uv`](https://docs.astral.sh/uv/)
и **Node.js 20+**.

### 1. Поднять зависимости в Docker

```bash
# PostgreSQL
docker run -d --name localcloud-postgres \
  -e POSTGRES_USER=localcloud -e POSTGRES_PASSWORD=localcloud -e POSTGRES_DB=localcloud \
  -p 5432:5432 postgres:16

# MinIO (консоль на :9001)
docker run -d --name localcloud-minio \
  -e MINIO_ROOT_USER=localcloud -e MINIO_ROOT_PASSWORD=localcloud \
  -p 9000:9000 -p 9001:9001 \
  minio/minio server /data --console-address ":9001"
```

Бакеты создаются автоматически при старте backend (`storage_service.ensure_buckets_ready`).

### 2. Backend

Конфигурация — единый **корневой** `.env` (один на весь проект). Для локального
запуска переопределите `MINIO_PUBLIC_PORT=9000` (без шлюза браузер ходит в MinIO
напрямую).

```bash
cp .env.example .env          # в корне проекта; поправьте значения при необходимости

cd backend
uv sync                       # установить зависимости
uv run alembic upgrade head   # применить миграции (читает корневой .env)
uv run python seed_admin.py   # создать админа (если ещё не создан)

uv run uvicorn app.main:app --reload          # API на http://localhost:8000
uv run python -m workers.app                  # фоновый worker (в отдельном терминале)
```

Подробности — [`backend/README.md`](./backend/README.md).

### 3. Frontend

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173 (проксирует /api на :8000)
```

Подробности — [`frontend/README.md`](./frontend/README.md).

### 4. Вход

Учётка администратора по умолчанию (см. корневой `.env`, секция `ADMIN_*`):

```
email:    admin@localcloud.dev
пароль:   Admin@LocalCloud123
```

> ⚠️ Поменяйте `SECRET_KEY`, пароли БД/MinIO и учётку админа перед любым публичным развёртыванием.

---

## Документация

- **[`backend/README.md`](./backend/README.md)** — полный справочник по backend: стек с версиями,
  слои архитектуры, конфигурация (все переменные окружения с дефолтами), база данных (Unit of Work,
  модели, исключения), безопасность (JWT, cookie, auth-зависимости), multipart upload (sequence
  diagram), хранилище MinIO (бакеты, ключи, presigned URL), фоновый worker (dispatcher, scheduler,
  типы задач, retry), полный список API-эндпоинтов, миграции, инициализация администратора.
- **[`frontend/README.md`](./frontend/README.md)** — полный справочник по frontend: стек с версиями,
  маршрутизация, API-слой (axios + silent refresh interceptor), загрузка файлов (multipart,
  очередь, параллелизм, drag-and-drop папок), файловый браузер (InfiniteQuery, оптимистичные
  обновления, миниатюры), контексты, хуки, компоненты, страницы, темизация (FOUC, CSS-переменные),
  все числовые константы.
- **[`CHANGELOG.md`](./CHANGELOG.md)** — история изменений проекта по версиям (формат
  Keep a Changelog, семантическое версионирование).

---

## Лицензия

См. [`LICENSE`](./LICENSE).
