# Инструкция: сборка `.env` под свой сервер

Полное руководство по подбору значений `.env` **индивидуально под характеристики
вашего хоста**. В отличие от готовых пресетов, здесь даны **формулы**, по которым
вы сами рассчитаете каждое значение под свой CPU, RAM, диск и число пользователей.

Готовые точки отсчёта (берите ближайшую как основу):
- **`.env.example`** — канонический шаблон (= слабый хост, 1 CPU / 1 ГБ);
- **`.env.example.small`** — пресет слабого хоста (1 CPU / 1 ГБ);
- **`.env.example.medium`** — пресет среднего хоста (2 CPU / 4 ГБ / 128 ГБ).

## Быстрый путь: автогенератор

Если не хотите считать вручную — `scripts/generate_env.py` определит ресурсы
хоста, возьмёт от них долю (по умолчанию 85%) и сам соберёт `.env` по формулам
из этого гайда (зависимостей нет, нужен только Python 3):

```bash
# авто: 85% от всех ресурсов хоста → ./.env (со случайными секретами)
python3 scripts/generate_env.py

# отдать приложению ровно столько ресурсов, сколько хотите
python3 scripts/generate_env.py --cpu 2 --ram 4G --disk 128G

# отдать половину ресурсов хоста; посмотреть результат без записи
python3 scripts/generate_env.py --fraction 0.5 --dry-run

# слабый хост-файлопомойка: без генерации/показа превью
python3 scripts/generate_env.py --no-previews
```

Полезные флаги: `--fraction` (доля ресурсов), `--cpu/--ram/--disk` (отдать
ровно столько), `--users` (ожидаемые пользователи, для проверок),
`--no-previews/--no-viewer/--no-playback/--no-editing` (выключить возможности),
`--public-host/--public-port`, `-o/--output`, `-f/--force`, `--dry-run`,
`--no-gen-secrets`. Полный список — `python3 scripts/generate_env.py --help`.

Разделы ниже объясняют **те же формулы**, если хотите понять расчёт или
докрутить значения руками.

> Все параметры приложения читаются из `.env` через `core/config.py` (дефолты —
> в `core/constants.py`). Контейнеры `api` и `worker` получают `.env` целиком
> через `env_file: .env`, а лимиты ресурсов (`*_MEM_LIMIT`, `POSTGRES_*`)
> подставляются в `docker-compose.yml` через `${VAR:-default}`.

---

## 0. Что нужно знать о своём сервере

Запишите четыре числа — всё остальное считается от них:

| Обозначение | Что это | Как узнать |
|-------------|---------|------------|
| **`C`** | Число ядер CPU | `nproc` |
| **`R`** | Объём RAM, МБ | `free -m` → строка `Mem total` |
| **`D`** | Свободно на диске под данные, ГБ | `df -h /` (том, где docker volumes) |
| **`U`** | Ожидаемое число **одновременно активных** пользователей | оценка |

Пример (будем считать по нему сквозной пример): `C=4`, `R=8192` (8 ГБ),
`D=200` ГБ, `U=15`.

---

## 1. Главное правило: два бюджета

Всё сводится к двум ограничениям, которые **нельзя превышать**:

1. **Бюджет памяти.** Сумма `*_MEM_LIMIT` всех контейнеров + запас ОС ≤ `R`.
2. **Бюджет подключений к БД.** Суммарный пул приложения + запас ≤
   `POSTGRES_MAX_CONNECTIONS`.

Если нарушить (1) — ядро будет убивать контейнеры (OOM). Если нарушить (2) —
запросы начнут падать с `too many connections`. Все формулы ниже выстроены так,
чтобы оба бюджета сходились. **Считайте сверху вниз и сверяйтесь с разделом 8.**

---

## 2. CPU: число процессов API

```
UVICORN_WORKERS = C - 1        (минимум 1; на 1 ядре = 1)
```

Каждый uvicorn-worker — отдельный процесс Python (~120–180 МБ) со своим пулом БД.
Оставляем одно ядро под worker, Postgres и nginx.

- `C=1` → `UVICORN_WORKERS=1`
- `C=2` → `UVICORN_WORKERS=2` (можно и 1, если RAM в обрез)
- `C=4` → `UVICORN_WORKERS=4` (или 3, если хотите больше памяти каждому)

**Сквозной пример (`C=4`): `UVICORN_WORKERS=3`** (оставляем запас RAM, см. §8).

Число процессов в кластере: `P = UVICORN_WORKERS + 1` (один фоновый `worker`).
В примере `P = 3 + 1 = 4`.

---

## 3. База данных: пул и подключения

Пул задаётся **на один процесс**. Реальное число коннектов в кластере:

```
коннекты = P * (POSTGRES_POOL_SIZE + POSTGRES_MAX_OVERFLOW)
```

Подбор:

```
POSTGRES_POOL_SIZE     = 5..10   (старт 10; уменьшайте, если процессов много)
POSTGRES_MAX_OVERFLOW  = POSTGRES_POOL_SIZE / 2   (округляя вниз)
POSTGRES_MAX_CONNECTIONS = P * (POOL_SIZE + MAX_OVERFLOW) + 10   (запас под
                           суперюзера/обслуживание; округлите вверх до 10)
```

Прочее оставьте по умолчанию:
`POSTGRES_POOL_TIMEOUT=30`, `POSTGRES_POOL_RECYCLE=1800`, `POSTGRES_POOL_PRE_PING=true`.

**Сквозной пример:** `POOL_SIZE=10`, `MAX_OVERFLOW=5`, `P=4` →
`4 * 15 = 60`, `+10` → **`POSTGRES_MAX_CONNECTIONS=80`** (округлили 70→80 с запасом).

> Эмпирика: на каждого одновременного пользователя `U` в пике нужно ~1–2 активных
> коннекта. Проверьте, что `P*(POOL_SIZE+MAX_OVERFLOW) ≥ 1.5*U`. В примере
> `60 ≥ 1.5*15=22.5` — с большим запасом.

### Тюнинг сервера Postgres (флаги в `docker-compose.yml` из `.env`)

```
POSTGRES_SHARED_BUFFERS            ≈ 25% от POSTGRES_MEM_LIMIT
POSTGRES_EFFECTIVE_CACHE_SIZE      ≈ 60–75% от POSTGRES_MEM_LIMIT
POSTGRES_WORK_MEM                  = 4MB (1 ГБ) … 8–16MB (4 ГБ+)
POSTGRES_MAINTENANCE_WORK_MEM      ≈ 10% от POSTGRES_MEM_LIMIT (32MB…256MB)
POSTGRES_MAX_WORKER_PROCESSES      = C
POSTGRES_MAX_PARALLEL_WORKERS      = C / 2
POSTGRES_MAX_PARALLEL_WORKERS_PER_GATHER = 0 (1 ГБ) … 1–2 (4 ГБ+)
```

**Сквозной пример** (`POSTGRES_MEM_LIMIT=1g`, см. §7):
`SHARED_BUFFERS=256MB`, `EFFECTIVE_CACHE_SIZE=768MB`, `WORK_MEM=8MB`,
`MAINTENANCE_WORK_MEM=96MB`, `MAX_WORKER_PROCESSES=4`, `MAX_PARALLEL_WORKERS=2`,
`MAX_PARALLEL_WORKERS_PER_GATHER=1`.

> ⚠️ `work_mem` выделяется **на операцию сортировки**, а их в пике может быть
> много (≈ число коннектов). Держите `work_mem * макс.коннектов` существенно
> меньше `POSTGRES_MEM_LIMIT`. В примере `8MB * 80 = 640MB` < 1 ГБ — ок.

---

## 4. Backpressure и параллелизм (нагрузка на API)

```
MAX_CONCURRENT_REQUESTS   = 32 * C        (потолок одновременных запросов → 503)
REQUEST_TIMEOUT_SECONDS   = 90            (увеличьте, если рендеры/архивы крупные)
STORAGE_EXECUTOR_MAX_WORKERS = max(4, 2 * C)
```

- `MAX_CONCURRENT_REQUESTS` — сколько запросов API обрабатывает разом; сверх —
  отдаёт `503 Retry-After`, не давая очереди выедать память/коннекты.
- `STORAGE_EXECUTOR_MAX_WORKERS` — пул потоков под блокирующий MinIO SDK.

**Сквозной пример (`C=4`):** `MAX_CONCURRENT_REQUESTS=128`,
`REQUEST_TIMEOUT_SECONDS=90`, `STORAGE_EXECUTOR_MAX_WORKERS=8`.

---

## 5. Генерация превью (нагрузка на worker, RAM/CPU)

Рендер превью — самая память- и CPU-затратная фоновая операция.

```
PREVIEW_GENERATION_ENABLED   = true   (false — полностью выключить на слабом хосте)
PREVIEW_RENDER_CONCURRENCY   = max(1, C / 2)   (1 на 1 ядре)
```

Лимиты исходного размера (файлы крупнее превью не получают — `NOT_REQUIRED`).
**`PDF_MAX_SOURCE_MB` — главный драйвер памяти worker** (замеренный пик anon ≈
`127 + 3.1 × PDF_MAX`, см. Приложение B): подбирайте его так, чтобы рендер влез
в `WORKER_MEM_LIMIT`.

| RAM (`R`) | IMAGE_MAX_SOURCE_MB | PDF_MAX_SOURCE_MB | VIDEO_MAX_SOURCE_MB |
|-----------|---------------------|-------------------|---------------------|
| ~1 ГБ | 25 | **10** | 64 |
| ~2 ГБ | 40 | 25 | 160 |
| ~4 ГБ | 60 | 50 | 256 |
| ~8 ГБ+ | 100 | 80 | 512 |

> На 1 ГБ `PDF_MAX=30` приводил к OOM worker'а (замерено) — поэтому здесь `10`.

Качество/размер растров (выше = чётче превью, но больше RAM на рендер и вес):

```
PREVIEW_IMAGE_MAX_DIMENSION  = 400 (≤2 ГБ) … 512 (4 ГБ+)
PREVIEW_IMAGE_QUALITY        = 75  (≤2 ГБ) … 80–85 (4 ГБ+)
PREVIEW_IMAGE_MAX_PIXELS     = 40000000 (≤2 ГБ) … 60000000 (4 ГБ+)   # защита от bomb
PREVIEW_PDF_RENDER_DPI       = 120 (≤2 ГБ) … 144 (4 ГБ+)
PREVIEW_PDF_RENDER_MAX_DIM   = 1600 (≤2 ГБ) … 2048 (4 ГБ+)
PREVIEW_VIDEO_FFMPEG_TIMEOUT_SECONDS = 30 … 45 (крупное видео)
```

**Сквозной пример (`C=4`, `R=8 ГБ`):** `RENDER_CONCURRENCY=2`,
`IMAGE_MAX_SOURCE_MB=100`, `PDF_MAX_SOURCE_MB=150`, `VIDEO_MAX_SOURCE_MB=512`,
`IMAGE_MAX_DIMENSION=512`, `IMAGE_QUALITY=82`, `IMAGE_MAX_PIXELS=60000000`,
`PDF_RENDER_DPI=144`, `PDF_RENDER_MAX_DIM=2048`, `FFMPEG_TIMEOUT_SECONDS=45`.

> 💡 **Совсем слабый хост или диск-хранилка без UI-превью:** поставьте
> `PREVIEW_GENERATION_ENABLED=false` и `FEATURE_PREVIEWS_ENABLED=false` — worker
> вообще не будет качать и рендерить файлы.

---

## 6. Архивы (фоновая сборка ZIP — нагрузка на диск)

ZIP собирается во временный файл на диске и потоково отдаётся в MinIO (память не
зависит от размера архива). Лимиты привязаны к **диску `D`**:

```
ARCHIVE_MAX_TOTAL_MB        ≈ (D * 1024) / 8     (не более ~1/8 свободного диска
                              под один временный архив; см. ниже про запас)
ARCHIVE_MAX_FILES           = 10000 (малый) … 50000 (большой диск)
ARCHIVE_STREAM_CHUNK_BYTES  = 1048576 (1 МБ; 4194304 = 4 МБ при RAM 4 ГБ+)
ARCHIVE_DISK_SAFETY_FACTOR  = 1.1
```

> На время сборки нужно `ARCHIVE_MAX_TOTAL_MB * ARCHIVE_DISK_SAFETY_FACTOR`
> свободного места под временный ZIP. Не задавайте лимит больше, чем реально
> поместится одновременно с пользовательскими данными.

**Сквозной пример (`D=200` ГБ):** `ARCHIVE_MAX_TOTAL_MB=16384` (16 ГБ),
`ARCHIVE_MAX_FILES=50000`, `ARCHIVE_STREAM_CHUNK_BYTES=4194304`,
`ARCHIVE_DISK_SAFETY_FACTOR=1.1`.

### Ёмкость хранилища (квоты)

```
STORAGE_CAPACITY_BYTES = (D - запас_под_временные_и_систему) * 1024^3
```

Оставьте 5–10 ГБ под временные ZIP, логи и систему. Можно **закомментировать** —
тогда пул определится автоматически как 85% ёмкости тома MinIO.

**Сквозной пример:** оставляем ~16 ГБ запаса →
`STORAGE_CAPACITY_BYTES=197568495616` (184 ГБ).

---

## 7. Бюджет памяти контейнеров (`*_MEM_LIMIT`)

Распределите `R` между контейнерами. Базовый рецепт (доли от `R`):

| Контейнер | Доля `R` | Минимум | Формула памяти |
|-----------|----------|---------|----------------|
| `API_MEM_LIMIT` | ~25% | 200m | `≈ UVICORN_WORKERS * 180МБ + 64МБ` |
| `WORKER_MEM_LIMIT` | ~18% | 220m | `≥ 1.25 × (127 + 3.1 × PDF_MAX_SOURCE_MB)` — пик anon рендера PDF (Прил. B) |
| `POSTGRES_MEM_LIMIT` | ~25% | 220m | — |
| `MINIO_MEM_LIMIT` | ~18% | 256m | — |
| `FRONTEND_MEM_LIMIT` | — | 32m | статика (nginx внутри) |
| `NGINX_MEM_LIMIT` | — | 40m | reverse-proxy |
| **Запас ОС** | **~15%** | 256m | docker, ядро, буферы |

`*_CPU_SHARES` — относительный вес при конкуренции за ядра (база 1024). Оставьте:
`API=1024`, `POSTGRES=1024`, `MINIO=768`, `WORKER=256` (worker намеренно ниже —
чтобы рендеры превью не вытесняли API/БД), `NGINX=512`, `FRONTEND=256`.

> `memswap_limit == mem_limit` в compose отключает swap — это намеренно (нет
> своп-тормозов; при превышении контейнер перезапускается, а не висит).

**Сквозной пример (`R=8 ГБ`, `UVICORN_WORKERS=3`):**
`API_MEM_LIMIT=1g` (3*180+64≈600МБ, берём 1g с запасом),
`WORKER_MEM_LIMIT=1g`, `POSTGRES_MEM_LIMIT=2g`, `MINIO_MEM_LIMIT=1500m`,
`FRONTEND_MEM_LIMIT=64m`, `NGINX_MEM_LIMIT=64m`.
Сумма ≈ `1+1+2+1.5+0.06+0.06 = 5.6 ГБ`, запас ОС ≈ `2.4 ГБ` — здорово.
(Можно поднять Postgres/worker, раз есть запас — см. §8 про итерацию.)

---

## 8. Сверка бюджетов (обязательный шаг)

После заполнения проверьте оба неравенства:

**Память:**
```
API_MEM + WORKER_MEM + POSTGRES_MEM + MINIO_MEM + FRONTEND_MEM + NGINX_MEM
    ≤ R * 0.85
```

**Подключения:**
```
(UVICORN_WORKERS + 1) * (POSTGRES_POOL_SIZE + POSTGRES_MAX_OVERFLOW) + 10
    ≤ POSTGRES_MAX_CONNECTIONS
```

И согласованность Postgres:
```
POSTGRES_SHARED_BUFFERS               ≤ ~30% POSTGRES_MEM_LIMIT
POSTGRES_WORK_MEM * POSTGRES_MAX_CONNECTIONS  ≪ POSTGRES_MEM_LIMIT
```

Если память не сходится — снижайте по приоритету: сначала `*_SOURCE_MB` и
`PREVIEW_RENDER_CONCURRENCY` (worker), затем `UVICORN_WORKERS`, затем
`POSTGRES_MEM_LIMIT`/`MINIO_MEM_LIMIT`.

---

## 9. Флаги функциональности UI (`FEATURE_*`)

Не влияют на формулы — это выключатели возможностей фронтенда (отдаются через
`GET /api/v1/config`). Отключайте на слабых/ограниченных серверах:

```
FEATURE_PREVIEWS_ENABLED        = true   # миниатюры в гриде
FEATURE_FILE_VIEWER_ENABLED     = true   # просмотрщик содержимого
FEATURE_MEDIA_PLAYBACK_ENABLED  = true   # плеер аудио/видео (иначе — «скачать»)
FEATURE_FILE_EDITING_ENABLED    = true   # редактирование текстовых файлов
```

Рекомендации:
- **1 CPU/1 ГБ как файлопомойка:** `PREVIEW_GENERATION_ENABLED=false`,
  `FEATURE_PREVIEWS_ENABLED=false` (остальные можно оставить — это лишь клиент).
- **Публичный/недоверенный доступ:** отключите `FEATURE_FILE_EDITING_ENABLED`.

---

## 10. Секреты (поменять обязательно)

Не зависят от железа, но **без них в production нельзя**:

```
POSTGRES_PASSWORD   — длинный случайный
MINIO_SECRET_KEY    — длинный случайный
SECRET_KEY          — длинная случайная строка (подпись JWT)
ADMIN_PASSWORD      — пароль первого администратора
MINIO_PUBLIC_HOST / MINIO_PUBLIC_PORT — внешний адрес (как клиент видит сервер)
COOKIE_SECURE=true  — если за HTTPS
```

Сгенерировать секрет: `openssl rand -base64 36`.

---

## 11. Итоговый чек-лист

1. Записал `C`, `R`, `D`, `U` (§0).
2. `UVICORN_WORKERS = C-1`, посчитал `P` (§2).
3. Пул БД и `POSTGRES_MAX_CONNECTIONS` (§3), тюнинг Postgres.
4. Backpressure и параллелизм (§4).
5. Лимиты и качество превью по таблице RAM (§5).
6. Лимиты архивов по диску `D` + `STORAGE_CAPACITY_BYTES` (§6).
7. `*_MEM_LIMIT` по долям `R` (§7).
8. **Сверил оба бюджета** (§8) — если не сходится, итерация.
9. `FEATURE_*` под сценарий (§9).
10. Поменял секреты (§10).
11. Запуск и проверка (§12).

---

## 12. Применение и проверка

```bash
cp .env.example .env          # или .env.example.small / .env.example.medium как основа
# отредактируйте по разделам выше
docker compose up -d --build
docker compose restart nginx  # сбросить кэш upstream-IP

# Проверки:
curl -s http://localhost/api/v1/config            # флаги функциональности
docker compose ps                                 # все healthy
docker stats --no-stream                          # фактическая память vs *_MEM_LIMIT
docker compose exec postgres \
  psql -U localcloud -d localcloud -c "show max_connections;"
docker compose logs worker --tail=20              # нет OOM/ошибок рендера
```

**Нагрузочно:** залейте пачку файлов в несколько вкладок, понаблюдайте
`docker stats`. Признаки, что пора подкрутить:
- контейнер перезапускается / в логах OOM → поднимите его `*_MEM_LIMIT` или
  снизьте источники превью / `UVICORN_WORKERS`;
- `503` под нагрузкой → поднимите `MAX_CONCURRENT_REQUESTS` (если есть RAM);
- `too many connections` → увеличьте `POSTGRES_MAX_CONNECTIONS` (и проверьте §3);
- превью долго не появляются → поднимите `PREVIEW_RENDER_CONCURRENCY` (если есть
  ядра) или лимиты `*_SOURCE_MB`.

---

## Приложение A. Готовые точки отсчёта

| Параметр | 1 CPU / 1 ГБ | 2 CPU / 4 ГБ | 4 CPU / 8 ГБ (пример) |
|----------|--------------|--------------|-----------------------|
| `UVICORN_WORKERS` | 1 | 2 | 3 |
| `POSTGRES_POOL_SIZE` / `MAX_OVERFLOW` | 5 / 5 | 10 / 5 | 10 / 5 |
| `POSTGRES_MAX_CONNECTIONS` | 50 | 80 | 80 |
| `MAX_CONCURRENT_REQUESTS` | 64 | 128 | 128 |
| `STORAGE_EXECUTOR_MAX_WORKERS` | 4 | 8 | 8 |
| `PREVIEW_RENDER_CONCURRENCY` | 1 | 2 | 2 |
| `PREVIEW_*_MAX_SOURCE_MB` (img/pdf/vid) | 25/30/80 | 60/80/256 | 100/150/512 |
| `ARCHIVE_MAX_TOTAL_MB` | 2048 | 16384 | 16384+ |
| `API_MEM_LIMIT` | 220m | 1g | 1g |
| `WORKER_MEM_LIMIT` | 220m | 768m | 1g |
| `POSTGRES_MEM_LIMIT` | 220m | 1g | 2g |
| `MINIO_MEM_LIMIT` | 256m | 1g | 1500m |
| `POSTGRES_SHARED_BUFFERS` | 64MB | 256MB | 512MB |

Колонка «1 CPU/1 ГБ» — это `.env.example` и `.env.example.small`, «2 CPU/4 ГБ» —
`.env.example.medium`. Берите ближайший файл как основу и двигайте значения по
формулам под своё железо.

---

## Приложение B. Эмпирические замеры и формулы

Раздел основан на **реальных замерах** (хост 12 ядер/15 ГБ, нагрузка — 83 PDF до
44 МБ и 34 PNG, настоящий multipart-путь). Память worker измерена по cgroup v2,
отдельно **anon** (невозвратная, именно она вызывает OOM) и **page-cache**
(reclaimable, ядро вытесняет до OOM).

### Память контейнеров на холостом ходу (1 ГБ-профиль)

| Контейнер | RSS idle | Лимит |
|---|---|---|
| api (1 uvicorn) | ~127 МиБ | 220m |
| worker | ~107 МиБ | 220m |
| minio | ~124 МиБ | 256m |
| postgres | ~51 МиБ | 220m |
| nginx / frontend | ~10 МиБ | 40m / 32m |

### Генерация превью — главный потребитель памяти worker

| Сценарий (worker) | **anon** | page-cache | вывод |
|---|---|---|---|
| 1 PDF (27 МиБ) | +86 МиБ | | один рендер |
| 18 PDF, `PDF_MAX=30`, без тюнинга | **261 МиБ** | 57 | OOM при лимите 220m |
| 18 PDF, `PDF_MAX=30`, `MALLOC_ARENA_MAX=2` | **220 МиБ** | 49 | −16% |
| 18 PDF, `PDF_MAX=10`, `MALLOC_ARENA_MAX=2` | **158 МиБ** | 13 | влезает в 220m |
| картинки (PNG) | +~10 МиБ | | дёшево |

- `WORKER_MEM_LIMIT=220m` + `PDF_MAX=30` → **OOM-kill подтверждён ядром**
  (`anon-rss:221864kB`). Исправлено: `PDF_MAX=10` → пик 184 МиБ, OOM нет
  (проверено: 18/18 превью, `restarts=0`). `WORKER_MEM_LIMIT=320m` + `PDF=30`
  тоже выживает (проверено).
- `PREVIEW_RENDER_CONCURRENCY` 1 vs 2 на пик почти не влияет: рендерится только
  первая страница PDF, рендер быстрый, пик определяет удержание аллокатора.

**Формула пика anon-памяти worker (при `MALLOC_ARENA_MAX=2`):**

```
preview_anon (МиБ) ≈ 127 + 3.1 × PREVIEW_PDF_MAX_SOURCE_MB
```
(158 при PDF=10, 220 при PDF=30 — обе точки замерены.)

**Отсюда минимум WORKER_MEM_LIMIT при включённой генерации превью:**
```
WORKER_MEM_LIMIT ≥ 1.25 × (127 + 3.1 × PREVIEW_PDF_MAX_SOURCE_MB),  но не ниже 220m
```
| PDF_MAX | preview_anon | WORKER_MEM_LIMIT |
|---|---|---|
| 10 | 158 МиБ | 220m |
| 30 | 220 МиБ | ~300m |
| 60 | 313 МиБ | ~400m |
| 80 | 375 МиБ | ~480m |

На 1 ГБ контейнерный бюджет не вмещает worker ≥300m вместе с api/pg/minio,
поэтому 1 ГБ-профиль использует **`PREVIEW_PDF_MAX_SOURCE_MB=10`** (а не 30).
Альтернатива для совсем слабых хостов — `PREVIEW_GENERATION_ENABLED=false`.

### Архив — память НЕ растёт с размером

Архив 404 МиБ исходников → worker **anon всего 147 МиБ** (+ 334 МиБ reclaimable
page-cache временного ZIP). Сборка действительно потоковая: anon ограничен и от
размера архива не зависит. `ARCHIVE_MAX_TOTAL_MB` ограничивает **диск** (под
временный ZIP), а не RAM worker.

### Backpressure и подключения к БД — формулы подтверждены точно

- 160 одновременных запросов при `MAX_CONCURRENT_REQUESTS=64` → **ровно 64
  пропущено, 96 отклонено с `503`**. Формула: `отклонено = max(0, одновременных −
  MAX_CONCURRENT_REQUESTS)`.
- Пик подключений к БД под нагрузкой = **15** при потолке `(workers+1)×(pool+
  overflow) = (1+1)×(5+5) = 20`. Формула — корректная верхняя граница.

### Что исправлено по итогам замеров

1. **1 ГБ-профили** (`.env.example`, `.env.example.small`): `PREVIEW_PDF_MAX_SOURCE_MB`
   30 → **10** (иначе worker падал по OOM).
2. **docker-compose (worker)**: добавлены `MALLOC_ARENA_MAX=2` и
   `MALLOC_TRIM_THRESHOLD_` (−16% пика anon).
3. **generate_env.py**: `WORKER_MEM_LIMIT` теперь считается от `PDF_MAX` по
   формуле выше; PDF-лимиты по тирам RAM снижены; добавлено предупреждение о
   риске OOM.
4. **Баг фоновых задач**: задача, прерванная смертью worker (OOM) после
   исчерпания попыток, навсегда зависала в `pending` (dispatcher берёт только
   `attempts_count < max_attempts`). Теперь `release_stale_running_tasks`
   переводит такие задачи в `failed`.
