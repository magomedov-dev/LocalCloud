#!/usr/bin/env python3
"""Генератор `.env` под характеристики конкретного сервера.

Скрипт определяет ресурсы хоста (CPU, RAM, свободный диск), берёт от них долю,
которую вы готовы отдать приложению (по умолчанию 85%), считает значения `.env`
по формулам из `docs/env-tuning-guide.md` и записывает готовый файл.

Зависимостей нет (только стандартная библиотека), поэтому скрипт запускается на
чистом хосте ещё до установки backend-окружения.

Примеры:
    # авто: 85% от всех ресурсов хоста → .env
    python3 scripts/generate_env.py

    # отдать приложению ровно 2 ядра, 4 ГБ ОЗУ и 128 ГБ диска
    python3 scripts/generate_env.py --cpu 2 --ram 4G --disk 128G

    # отдать 50% ресурсов хоста, печать без записи
    python3 scripts/generate_env.py --fraction 0.5 --dry-run

    # слабый хост-файлопомойка: без генерации и показа превью
    python3 scripts/generate_env.py --no-previews
"""

from __future__ import annotations

import argparse
import math
import os
import secrets
import shutil
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / ".env"
DEFAULT_FRACTION = 0.85


# ── Определение и парсинг ресурсов ───────────────────────────────────────────


def detect_total_ram_mb() -> int:
    """Возвращает общий объём оперативной памяти хоста в мегабайтах.

    Сначала пробует `/proc/meminfo` (Linux), затем `os.sysconf`. Если ничего
    не доступно, возвращает 1024 как безопасный минимум.

    Returns:
        Общий объём RAM в МБ.
    """

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return max(1, kb // 1024)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return max(1, (pages * page_size) // (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        return 1024


def detect_free_disk_gb(path: Path) -> float:
    """Возвращает объём свободного места на диске для указанного пути, ГБ.

    Args:
        path: Путь, для тома которого измеряется свободное место.

    Returns:
        Свободное место в гигабайтах.
    """

    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    return shutil.disk_usage(target).free / (1024**3)


def parse_size_mb(value: str) -> int:
    """Разбирает размер памяти (`512`, `512M`, `4G`, `2g`) в мегабайты.

    Args:
        value: Строка размера. Без суффикса трактуется как мегабайты.

    Returns:
        Размер в мегабайтах.

    Raises:
        ValueError: Если строку не удалось разобрать.
    """

    text = value.strip().lower().rstrip("b")
    if not text:
        raise ValueError("пустой размер")
    multiplier = 1
    if text.endswith("g"):
        multiplier, text = 1024, text[:-1]
    elif text.endswith("m"):
        multiplier, text = 1, text[:-1]
    elif text.endswith("k"):
        multiplier, text = 1 / 1024, text[:-1]
    return max(1, int(float(text) * multiplier))


def parse_size_gb(value: str) -> float:
    """Разбирает размер диска (`128`, `128G`, `500g`) в гигабайты.

    Args:
        value: Строка размера. Без суффикса трактуется как гигабайты.

    Returns:
        Размер в гигабайтах.
    """

    text = value.strip().lower().rstrip("b")
    if text.endswith("t"):
        return float(text[:-1]) * 1024
    if text.endswith("g"):
        return float(text[:-1])
    if text.endswith("m"):
        return float(text[:-1]) / 1024
    return float(text)


# ── Расчёт значений конфигурации ─────────────────────────────────────────────


@dataclass
class HostBudget:
    """Ресурсы, выделяемые приложению.

    Attributes:
        cpu: Число ядер CPU, отдаваемых приложению.
        ram_mb: Объём RAM в МБ, отдаваемый приложению.
        disk_gb: Объём диска в ГБ, отдаваемый приложению.
        users: Ожидаемое число одновременно активных пользователей.
        total_cpu: Всего ядер на хосте (для справки).
        total_ram_mb: Всего RAM на хосте, МБ (для справки).
        total_disk_gb: Всего свободного диска на хосте, ГБ (для справки).
        fraction: Доля ресурсов хоста, отданная приложению (для справки).
    """

    cpu: int
    ram_mb: int
    disk_gb: float
    users: int
    total_cpu: int
    total_ram_mb: int
    total_disk_gb: float
    fraction: float


@dataclass
class FeatureToggles:
    """Флаги функциональности приложения.

    Attributes:
        preview_generation: Генерировать ли превью на worker'е.
        previews: Показывать ли превью-миниатюры в UI.
        viewer: Доступен ли просмотрщик содержимого файлов.
        playback: Доступно ли проигрывание аудио/видео.
        editing: Доступно ли редактирование текстовых файлов.
    """

    preview_generation: bool = True
    previews: bool = True
    viewer: bool = True
    playback: bool = True
    editing: bool = True


@dataclass
class GeneratedConfig:
    """Полный набор вычисленных значений `.env`.

    Attributes:
        budget: Использованный бюджет ресурсов.
        values: Имя переменной → строковое значение.
        warnings: Предупреждения, найденные при расчёте.
    """

    budget: HostBudget
    values: dict[str, str]
    warnings: list[str] = field(default_factory=list)


def _round_mb(value: float, step: int = 16) -> int:
    """Округляет мегабайты до ближайшего кратного `step`."""

    return max(step, int(round(value / step) * step))


def _ceil_to_10(value: float) -> int:
    """Округляет вверх до ближайшего кратного 10."""

    return int(math.ceil(value / 10.0) * 10)


def _fmt_mem(mb: int) -> str:
    """Форматирует МБ для docker mem_limit (`2g` либо `768m`)."""

    if mb >= 1024 and mb % 1024 == 0:
        return f"{mb // 1024}g"
    return f"{mb}m"


def preview_anon_mb(pdf_max_source_mb: int, generation_enabled: bool) -> int:
    """Оценивает пик anon-памяти worker при генерации превью, МиБ.

    Формула выведена эмпирически (замеры рендера PDF на реальных файлах,
    при MALLOC_ARENA_MAX=2): пик anon ≈ 127 + 3.1 × PREVIEW_PDF_MAX_SOURCE_MB
    (158 МиБ при PDF=10, 220 МиБ при PDF=30). PDF-рендер доминирует над
    картинками и видео. Если генерация выключена — worker остаётся на idle.

    Args:
        pdf_max_source_mb: Лимит исходного PDF для превью, МБ.
        generation_enabled: Включена ли генерация превью.

    Returns:
        Ожидаемый пик anon-памяти worker в МиБ.
    """

    if not generation_enabled:
        return 110
    return int(round(127 + 3.1 * pdf_max_source_mb))


def worker_mem_floor(pdf_max_source_mb: int, generation_enabled: bool) -> int:
    """Минимальный WORKER_MEM_LIMIT под генерацию превью, МиБ.

    Берёт оценку пика anon с запасом 1.25 (на reclaimable page-cache временных
    файлов и всплески), не ниже 220 при включённой генерации.

    Args:
        pdf_max_source_mb: Лимит исходного PDF для превью, МБ.
        generation_enabled: Включена ли генерация превью.

    Returns:
        Минимальный mem_limit worker в МиБ.
    """

    anon = preview_anon_mb(pdf_max_source_mb, generation_enabled)
    if not generation_enabled:
        return 160
    return max(220, _round_mb(anon * 1.25))


def allocate_memory(ram_mb: int, worker_floor: int = 200) -> dict[str, int]:
    """Распределяет бюджет RAM между контейнерами.

    Маленькие контейнеры (frontend, nginx) получают фиксированный минимум, а
    остаток делится между postgres/api/minio/worker по весам с учётом
    минимальных порогов. Порог worker задаётся отдельно (`worker_floor`), так
    как рендер превью требует измеримо больше памяти, чем idle (см.
    `worker_mem_floor`).

    Args:
        ram_mb: Бюджет RAM в МБ.
        worker_floor: Минимальный mem_limit worker в МБ (под превью).

    Returns:
        Имя контейнера → mem_limit в МБ.
    """

    frontend = 32 if ram_mb < 2048 else 64
    nginx = 40 if ram_mb < 2048 else 64
    pool = max(0, ram_mb - frontend - nginx)

    weights = {"postgres": 0.30, "api": 0.27, "minio": 0.23, "worker": 0.20}
    minimums = {"postgres": 220, "api": 200, "minio": 256, "worker": worker_floor}

    alloc = {
        name: max(minimums[name], _round_mb(pool * weight))
        for name, weight in weights.items()
    }
    alloc["frontend"] = frontend
    alloc["nginx"] = nginx
    return alloc


def _preview_limits(ram_mb: int) -> dict[str, int]:
    """Возвращает лимиты/качество превью под объём RAM."""

    # PDF-лимит подобран по замеренной формуле пика anon worker:
    #   preview_anon ≈ 127 + 3.1 × pdf_mb (МиБ, при MALLOC_ARENA_MAX=2),
    # чтобы рендер влезал в WORKER_MEM_LIMIT (см. preview_anon_mb ниже).
    if ram_mb < 1536:
        src = (25, 10, 64)
    elif ram_mb < 3072:
        src = (40, 25, 160)
    elif ram_mb < 6144:
        src = (60, 50, 256)
    else:
        src = (100, 80, 512)

    if ram_mb < 3072:
        quality = dict(dim=400, q=75, pixels=40_000_000, dpi=120, maxdim=1600, ffmpeg=30)
    else:
        quality = dict(dim=512, q=82, pixels=60_000_000, dpi=144, maxdim=2048, ffmpeg=45)

    return {
        "image_mb": src[0],
        "pdf_mb": src[1],
        "video_mb": src[2],
        **quality,
    }


def compute_config(budget: HostBudget, features: FeatureToggles,
                   public_host: str, public_port: int) -> GeneratedConfig:
    """Вычисляет все значения `.env` из бюджета ресурсов.

    Args:
        budget: Ресурсы, отданные приложению.
        features: Флаги функциональности.
        public_host: Внешний хост MinIO (как его видит клиент).
        public_port: Внешний порт MinIO.

    Returns:
        Сгенерированная конфигурация со значениями и предупреждениями.
    """

    warnings: list[str] = []
    cpu = budget.cpu
    ram = budget.ram_mb
    disk = budget.disk_gb

    # ── CPU / процессы ───────────────────────────────────────────────────────
    workers = cpu if cpu <= 2 else cpu - 1
    procs = workers + 1

    # ── Пул БД и подключения ─────────────────────────────────────────────────
    pool_size = 5 if ram < 2048 else 10
    max_overflow = 5
    needed_conns = procs * (pool_size + max_overflow)
    max_connections = max(25, _ceil_to_10(needed_conns + 10))
    if pool_size + max_overflow < math.ceil(1.5 * budget.users / procs):
        warnings.append(
            f"Пул на процесс ({pool_size}+{max_overflow}) может быть мал под "
            f"{budget.users} пользователей; рассмотрите больше RAM/ядер."
        )

    # ── Превью (нужно до памяти: задаёт минимум WORKER_MEM_LIMIT) ─────────────
    pv = _preview_limits(ram)
    render_concurrency = max(1, cpu // 2)

    # ── Память контейнеров ───────────────────────────────────────────────────
    # Порог worker зависит от лимита PDF-превью: рендер PDF — главный потребитель
    # памяти worker (эмпирически anon ≈ 127 + 3.1×pdf_mb МиБ). Без этого worker
    # упирался в лимит и падал по OOM при рендере.
    w_floor = worker_mem_floor(pv["pdf_mb"], features.preview_generation)
    mem = allocate_memory(ram, worker_floor=w_floor)
    mem_total = sum(mem.values())
    if mem_total > ram:
        warnings.append(
            f"Сумма mem_limit ({mem_total} МБ) превышает выделенный RAM "
            f"({ram} МБ): хост слишком мал. Лимиты подняты до минимумов — "
            f"возможны перезапуски контейнеров под пиковой нагрузкой."
        )
    if features.preview_generation:
        anon = preview_anon_mb(pv["pdf_mb"], True)
        if mem["worker"] < anon:
            warnings.append(
                f"WORKER_MEM_LIMIT ({mem['worker']} МБ) ниже ожидаемого пика "
                f"anon при рендере PDF ({anon} МБ, PDF<= {pv['pdf_mb']}МБ): риск "
                f"OOM. Снизьте PREVIEW_PDF_MAX_SOURCE_MB или дайте больше RAM."
            )

    # ── Тюнинг Postgres (от его mem_limit) ───────────────────────────────────
    pg_mb = mem["postgres"]
    shared_buffers = _round_mb(pg_mb * 0.25)
    effective_cache = _round_mb(pg_mb * 0.70)
    maintenance = min(512, max(32, _round_mb(pg_mb * 0.10)))
    work_mem = 4 if ram < 2048 else (8 if ram < 8192 else 16)
    if work_mem * max_connections > pg_mb * 0.5:
        warnings.append(
            f"work_mem ({work_mem}MB) * max_connections ({max_connections}) "
            f"велик относительно postgres mem_limit ({pg_mb}МБ)."
        )
    max_worker_processes = max(2, cpu)
    max_parallel_workers = max(1, cpu // 2)
    max_parallel_per_gather = 0 if ram < 2048 else 1

    # ── Backpressure / параллелизм ───────────────────────────────────────────
    max_concurrent = 32 * cpu
    storage_executor = max(4, 2 * cpu)

    # ── Worker: параллелизм задач масштабируем по CPU ────────────────────────
    # Большинство задач worker — I/O (storage), но рендеры превью CPU-затратны
    # (отдельно ограничены render_concurrency). 2 задачи на ядро — разумный
    # баланс, не ниже 2. Проверка целостности ограничена пулом storage-потоков.
    worker_max_concurrent = max(2, 2 * cpu)
    integrity_concurrency = max(2, min(storage_executor, 2 * cpu))

    # ── Архивы / ёмкость хранилища ───────────────────────────────────────────
    archive_total_mb = max(512, int(disk * 1024 / 8))
    archive_max_files = 10000 if disk < 64 else 50000
    archive_chunk = 1048576 if ram < 4096 else 4194304
    safety = 1.1
    reserve_gb = max(5.0, archive_total_mb / 1024 * safety)
    capacity_gb = max(1.0, disk - reserve_gb)
    capacity_bytes = int(capacity_gb * (1024**3))

    values: dict[str, str] = {
        # App
        "APP_NAME": "LocalCloud",
        "APP_VERSION": "0.1.0",
        "APP_DESCRIPTION": "Веб-приложение для персонального хранения файлов",
        "DEBUG": "false",
        # Logging
        "LOG_LEVEL": "INFO",
        "LOG_JSON": "true",
        "LOG_FILE_ENABLED": "false",
        "LOG_FILE_PATH": "logs/app.log",
        # Database pool
        "POSTGRES_USER": "localcloud",
        "POSTGRES_PASSWORD": "localcloud_change_me_in_production",
        "POSTGRES_DB": "localcloud",
        "POSTGRES_ECHO": "false",
        "POSTGRES_POOL_SIZE": str(pool_size),
        "POSTGRES_MAX_OVERFLOW": str(max_overflow),
        "POSTGRES_POOL_TIMEOUT": "30",
        "POSTGRES_POOL_RECYCLE": "1800",
        "POSTGRES_POOL_PRE_PING": "true",
        # MinIO
        "MINIO_ACCESS_KEY": "localcloud",
        "MINIO_SECRET_KEY": "localcloud_change_me_in_production",
        "MINIO_SECURE": "false",
        "MINIO_REGION": "us-east-1",
        "MINIO_PUBLIC_HOST": public_host,
        "MINIO_PUBLIC_PORT": str(public_port),
        "STORAGE_CAPACITY_BYTES": str(capacity_bytes),
        "STORAGE_EXECUTOR_MAX_WORKERS": str(storage_executor),
        # Socket-таймауты MinIO и готовность хранилища на старте. Статичны:
        # зависят от сети/диска, а не от размера хоста. read — на каждое чтение,
        # большие файлы не рвутся.
        "MINIO_CONNECT_TIMEOUT_SECONDS": "5",
        "MINIO_READ_TIMEOUT_SECONDS": "60",
        "STORAGE_STARTUP_TIMEOUT_SECONDS": "30",
        # Авто-аборт незавершённых multipart-загрузок (дни). 0 — выключить.
        "INCOMPLETE_MULTIPART_EXPIRY_DAYS": "7",
        # Security
        "SECRET_KEY": "change-me-to-a-long-random-string-before-production",
        "JWT_ALGORITHM": "HS256",
        "JWT_ISSUER": "localcloud",
        "JWT_AUDIENCE": "localcloud",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
        "REFRESH_TOKEN_EXPIRE_DAYS": "30",
        "PASSWORD_HASH_SCHEME": "bcrypt",
        # Защита от перебора пароля публичных ссылок (БД-блокировка).
        "PUBLIC_LINK_PASSWORD_MAX_ATTEMPTS": "5",
        "PUBLIC_LINK_PASSWORD_LOCKOUT_SECONDS": "900",
        # Rate-limit чувствительных точек по IP (скользящее окно на процесс).
        # Статичны: зависят от политики, а не от железа.
        "RATE_LIMIT_AUTH_ATTEMPTS": "10",
        "RATE_LIMIT_AUTH_WINDOW_SECONDS": "300",
        "RATE_LIMIT_PUBLIC_ACCESS_ATTEMPTS": "30",
        "RATE_LIMIT_PUBLIC_ACCESS_WINDOW_SECONDS": "300",
        # Cookies
        "ACCESS_COOKIE_NAME": "access_token",
        "REFRESH_COOKIE_NAME": "refresh_token",
        "COOKIE_SECURE": "false",
        "COOKIE_HTTPONLY": "true",
        "COOKIE_SAMESITE": "lax",
        "COOKIE_DOMAIN": "",
        "COOKIE_PATH": "/",
        # Admin
        "ADMIN_EMAIL": "admin@localcloud.dev",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "Admin@LocalCloud123",
        # Uvicorn
        "UVICORN_WORKERS": str(workers),
        # Backpressure
        "MAX_CONCURRENT_REQUESTS": str(max_concurrent),
        "REQUEST_TIMEOUT_SECONDS": "90",
        # Worker (фоновый обработчик задач). Параллелизм масштабируется по CPU;
        # интервалы/лимиты/backoff статичны (зависят от политики, не от железа).
        "WORKER_ENABLED": "true",
        "WORKER_NAME": "localcloud-worker",
        "WORKER_POLL_INTERVAL_SECONDS": "5",
        "WORKER_IDLE_SLEEP_SECONDS": "2",
        "WORKER_BATCH_SIZE": "10",
        "WORKER_MAX_CONCURRENT_TASKS": str(worker_max_concurrent),
        "WORKER_SHUTDOWN_TIMEOUT_SECONDS": "30",
        "WORKER_TASK_LOCK_TTL_SECONDS": "300",
        "WORKER_STALE_TASK_LOCK_SECONDS": "900",
        "WORKER_RETRY_DELAY_SECONDS": "60",
        "WORKER_MAX_RETRY_DELAY_SECONDS": "3600",
        "WORKER_CLEANUP_BATCH_SIZE": "100",
        "WORKER_INTEGRITY_BATCH_SIZE": "100",
        "WORKER_INTEGRITY_CONCURRENCY": str(integrity_concurrency),
        "WORKER_QUOTA_BATCH_SIZE": "100",
        # Worker scheduler (периодические системные задачи).
        "WORKER_SCHEDULER_ENABLED": "true",
        "WORKER_CLEAN_TRASH_INTERVAL_SECONDS": "3600",
        "WORKER_CLEAN_EXPIRED_UPLOADS_INTERVAL_SECONDS": "1800",
        "WORKER_CLEAN_EXPIRED_PUBLIC_LINKS_INTERVAL_SECONDS": "3600",
        "WORKER_RECALCULATE_QUOTAS_INTERVAL_SECONDS": "86400",
        "WORKER_STORAGE_INTEGRITY_INTERVAL_SECONDS": "86400",
        # Preview
        "PREVIEW_GENERATION_ENABLED": _b(features.preview_generation),
        "PREVIEW_IMAGE_MAX_SOURCE_MB": str(pv["image_mb"]),
        "PREVIEW_PDF_MAX_SOURCE_MB": str(pv["pdf_mb"]),
        "PREVIEW_VIDEO_MAX_SOURCE_MB": str(pv["video_mb"]),
        "PREVIEW_RENDER_CONCURRENCY": str(render_concurrency),
        "PREVIEW_IMAGE_MAX_DIMENSION": str(pv["dim"]),
        "PREVIEW_IMAGE_QUALITY": str(pv["q"]),
        "PREVIEW_IMAGE_MAX_PIXELS": str(pv["pixels"]),
        "PREVIEW_PDF_RENDER_DPI": str(pv["dpi"]),
        "PREVIEW_PDF_RENDER_MAX_DIM": str(pv["maxdim"]),
        "PREVIEW_VIDEO_FFMPEG_TIMEOUT_SECONDS": str(pv["ffmpeg"]),
        # Archives
        "ARCHIVE_MAX_FILES": str(archive_max_files),
        "ARCHIVE_MAX_TOTAL_MB": str(archive_total_mb),
        "ARCHIVE_STREAM_CHUNK_BYTES": str(archive_chunk),
        "ARCHIVE_DISK_SAFETY_FACTOR": "1.1",
        # Feature flags
        "FEATURE_PREVIEWS_ENABLED": _b(features.previews),
        "FEATURE_FILE_VIEWER_ENABLED": _b(features.viewer),
        "FEATURE_MEDIA_PLAYBACK_ENABLED": _b(features.playback),
        "FEATURE_FILE_EDITING_ENABLED": _b(features.editing),
        # Resource limits
        "POSTGRES_MEM_LIMIT": _fmt_mem(mem["postgres"]),
        "POSTGRES_CPU_SHARES": "1024",
        "MINIO_MEM_LIMIT": _fmt_mem(mem["minio"]),
        "MINIO_CPU_SHARES": "768",
        "API_MEM_LIMIT": _fmt_mem(mem["api"]),
        "API_CPU_SHARES": "1024",
        "WORKER_MEM_LIMIT": _fmt_mem(mem["worker"]),
        "WORKER_CPU_SHARES": "256",
        "FRONTEND_MEM_LIMIT": _fmt_mem(mem["frontend"]),
        "FRONTEND_CPU_SHARES": "256",
        "NGINX_MEM_LIMIT": _fmt_mem(mem["nginx"]),
        "NGINX_CPU_SHARES": "512",
        # Postgres server tuning
        "POSTGRES_MAX_CONNECTIONS": str(max_connections),
        "POSTGRES_SHARED_BUFFERS": f"{shared_buffers}MB",
        "POSTGRES_EFFECTIVE_CACHE_SIZE": f"{effective_cache}MB",
        "POSTGRES_WORK_MEM": f"{work_mem}MB",
        "POSTGRES_MAINTENANCE_WORK_MEM": f"{maintenance}MB",
        "POSTGRES_MAX_WORKER_PROCESSES": str(max_worker_processes),
        "POSTGRES_MAX_PARALLEL_WORKERS": str(max_parallel_workers),
        "POSTGRES_MAX_PARALLEL_WORKERS_PER_GATHER": str(max_parallel_per_gather),
    }

    return GeneratedConfig(budget=budget, values=values, warnings=warnings)


def _b(flag: bool) -> str:
    """Преобразует bool в `true`/`false` для `.env`."""

    return "true" if flag else "false"


# ── Секреты ──────────────────────────────────────────────────────────────────


def generate_strong_password(length: int = 20) -> str:
    """Генерирует пароль с гарантированными классами символов.

    Args:
        length: Желаемая длина пароля (минимум 12).

    Returns:
        Случайный пароль, содержащий буквы обоих регистров, цифру и спецсимвол.
    """

    length = max(12, length)
    # Только символы, безопасные в project .env: docker-compose и python-dotenv
    # интерполируют `$`/`${}`, поэтому `$` исключён; `#`, кавычки и `\` — тоже,
    # чтобы значение гарантированно читалось как литерал.
    specials = "!@%^&*-_+."
    alphabet = string.ascii_letters + string.digits + specials
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)
            and any(c.isdigit() for c in candidate)
            and any(c in specials for c in candidate)
        ):
            return candidate


_SECRET_KEYS = ("SECRET_KEY", "POSTGRES_PASSWORD", "MINIO_SECRET_KEY", "ADMIN_PASSWORD")

# Подстроки-маркеры незаменённого/дефолтного секрета (совпадает с проверкой на
# старте backend — core.secret_validation). Точные дефолты добавлены отдельно.
_PLACEHOLDER_MARKERS = ("change-me", "change_me", "changeme", "development-secret",
                        "localcloud_password")
_PLACEHOLDER_EXACT = ("localcloud", "admin@localcloud123")


def _is_placeholder_secret(value: str) -> bool:
    """Проверяет, является ли значение секрета дефолтным/плейсхолдером."""

    low = value.strip().lower()
    if not low or low in _PLACEHOLDER_EXACT:
        return True
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def read_existing_secrets(path: Path) -> dict[str, str]:
    """Читает «настоящие» секреты из существующего `.env`.

    Возвращает только непустые, не-плейсхолдерные значения секретных ключей —
    именно их нужно сохранить при повторной генерации, чтобы не сломать уже
    инициализированную БД (Postgres задаёт пароль только при первом создании
    тома) и не разлогинить пользователей (смена SECRET_KEY).

    Args:
        path: Путь к существующему файлу `.env`.

    Returns:
        Словарь `имя_секрета -> значение` для пригодных к переиспользованию.
    """

    if not path.exists():
        return {}
    found: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key in _SECRET_KEYS and val and not _is_placeholder_secret(val):
            found[key] = val
    return found


def apply_generated_secrets(
    values: dict[str, str],
    *,
    existing: dict[str, str] | None = None,
    rotate: bool = False,
) -> tuple[dict[str, str], dict[str, str]]:
    """Заполняет секреты: сохраняет существующие, генерирует недостающие.

    По умолчанию переиспользует пригодные секреты из ``existing`` (чтобы
    повторная генерация под новые ресурсы НЕ меняла пароль БД и не ломала уже
    инициализированный том Postgres). Недостающие или плейсхолдерные значения
    генерируются случайно. При ``rotate=True`` все секреты генерируются заново.

    Args:
        values: Словарь значений конфигурации (изменяется на месте).
        existing: Секреты из существующего `.env` (см. ``read_existing_secrets``).
        rotate: Принудительно сгенерировать новые секреты, игнорируя existing.

    Returns:
        Кортеж ``(generated, reused)``: сгенерированные и переиспользованные
        секреты (имя → значение) для показа пользователю.
    """

    existing = existing or {}
    factory = {
        "SECRET_KEY": lambda: secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
        "MINIO_SECRET_KEY": lambda: secrets.token_urlsafe(24),
        "ADMIN_PASSWORD": lambda: generate_strong_password(20),
    }
    generated: dict[str, str] = {}
    reused: dict[str, str] = {}
    for key, make in factory.items():
        prev = existing.get(key)
        if not rotate and prev:
            values[key] = prev
            reused[key] = prev
        else:
            values[key] = make()
            generated[key] = values[key]
    return generated, reused


# ── Рендеринг файла ──────────────────────────────────────────────────────────


def _section(title: str) -> str:
    """Возвращает строку-заголовок секции фиксированной ширины."""

    prefix = f"# ── {title} "
    return prefix + "─" * max(0, 78 - len(prefix))


def render_env(config: GeneratedConfig) -> str:
    """Собирает текст `.env` из вычисленных значений.

    Args:
        config: Сгенерированная конфигурация.

    Returns:
        Полное содержимое файла `.env` в виде строки.
    """

    v = config.values
    b = config.budget
    lines: list[str] = []

    lines.append(_section("LocalCloud — сгенерировано scripts/generate_env.py"))
    lines.append(
        f"# Хост: {b.total_cpu} CPU / {b.total_ram_mb} МБ ОЗУ / "
        f"{b.total_disk_gb:.0f} ГБ свободно на диске."
    )
    lines.append(
        f"# Выделено приложению (~{b.fraction:.0%}): {b.cpu} CPU / {b.ram_mb} МБ "
        f"ОЗУ / {b.disk_gb:.0f} ГБ диск; ожидаемых пользователей: {b.users}."
    )
    lines.append("# Под другие характеристики см. docs/env-tuning-guide.md.")
    lines.append("# ВНИМАНИЕ: смените секреты ниже, если они не сгенерированы автоматически.")

    def block(title: str, keys: list[str]) -> None:
        lines.append("")
        lines.append(_section(title))
        for key in keys:
            lines.append(f"{key}={v[key]}")

    block("App", ["APP_NAME", "APP_VERSION", "APP_DESCRIPTION", "DEBUG"])
    block("Logging", ["LOG_LEVEL", "LOG_JSON", "LOG_FILE_ENABLED", "LOG_FILE_PATH"])
    block("Database (пул подключений приложения)", [
        "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_ECHO",
        "POSTGRES_POOL_SIZE", "POSTGRES_MAX_OVERFLOW", "POSTGRES_POOL_TIMEOUT",
        "POSTGRES_POOL_RECYCLE", "POSTGRES_POOL_PRE_PING",
    ])
    block("MinIO / S3", [
        "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_SECURE", "MINIO_REGION",
        "MINIO_PUBLIC_HOST", "MINIO_PUBLIC_PORT", "STORAGE_CAPACITY_BYTES",
        "STORAGE_EXECUTOR_MAX_WORKERS", "MINIO_CONNECT_TIMEOUT_SECONDS",
        "MINIO_READ_TIMEOUT_SECONDS", "STORAGE_STARTUP_TIMEOUT_SECONDS",
        "INCOMPLETE_MULTIPART_EXPIRY_DAYS",
    ])
    block("Security", [
        "SECRET_KEY", "JWT_ALGORITHM", "JWT_ISSUER", "JWT_AUDIENCE",
        "ACCESS_TOKEN_EXPIRE_MINUTES", "REFRESH_TOKEN_EXPIRE_DAYS",
        "PASSWORD_HASH_SCHEME", "PUBLIC_LINK_PASSWORD_MAX_ATTEMPTS",
        "PUBLIC_LINK_PASSWORD_LOCKOUT_SECONDS", "RATE_LIMIT_AUTH_ATTEMPTS",
        "RATE_LIMIT_AUTH_WINDOW_SECONDS", "RATE_LIMIT_PUBLIC_ACCESS_ATTEMPTS",
        "RATE_LIMIT_PUBLIC_ACCESS_WINDOW_SECONDS",
    ])
    block("Cookies", [
        "ACCESS_COOKIE_NAME", "REFRESH_COOKIE_NAME", "COOKIE_SECURE",
        "COOKIE_HTTPONLY", "COOKIE_SAMESITE", "COOKIE_DOMAIN", "COOKIE_PATH",
    ])
    block("Admin", ["ADMIN_EMAIL", "ADMIN_USERNAME", "ADMIN_PASSWORD"])
    block("Uvicorn (API-сервер)", ["UVICORN_WORKERS"])
    block("Backpressure (защита API от перегрузки)", [
        "MAX_CONCURRENT_REQUESTS", "REQUEST_TIMEOUT_SECONDS",
    ])
    block("Worker (фоновый обработчик задач)", [
        "WORKER_ENABLED", "WORKER_NAME", "WORKER_POLL_INTERVAL_SECONDS",
        "WORKER_IDLE_SLEEP_SECONDS", "WORKER_BATCH_SIZE",
        "WORKER_MAX_CONCURRENT_TASKS", "WORKER_SHUTDOWN_TIMEOUT_SECONDS",
        "WORKER_TASK_LOCK_TTL_SECONDS", "WORKER_STALE_TASK_LOCK_SECONDS",
        "WORKER_RETRY_DELAY_SECONDS", "WORKER_MAX_RETRY_DELAY_SECONDS",
        "WORKER_CLEANUP_BATCH_SIZE", "WORKER_INTEGRITY_BATCH_SIZE",
        "WORKER_INTEGRITY_CONCURRENCY", "WORKER_QUOTA_BATCH_SIZE",
    ])
    block("Worker scheduler (периодические системные задачи)", [
        "WORKER_SCHEDULER_ENABLED", "WORKER_CLEAN_TRASH_INTERVAL_SECONDS",
        "WORKER_CLEAN_EXPIRED_UPLOADS_INTERVAL_SECONDS",
        "WORKER_CLEAN_EXPIRED_PUBLIC_LINKS_INTERVAL_SECONDS",
        "WORKER_RECALCULATE_QUOTAS_INTERVAL_SECONDS",
        "WORKER_STORAGE_INTEGRITY_INTERVAL_SECONDS",
    ])
    block("Preview generation (фоновый рендер миниатюр)", [
        "PREVIEW_GENERATION_ENABLED", "PREVIEW_IMAGE_MAX_SOURCE_MB",
        "PREVIEW_PDF_MAX_SOURCE_MB", "PREVIEW_VIDEO_MAX_SOURCE_MB",
        "PREVIEW_RENDER_CONCURRENCY", "PREVIEW_IMAGE_MAX_DIMENSION",
        "PREVIEW_IMAGE_QUALITY", "PREVIEW_IMAGE_MAX_PIXELS",
        "PREVIEW_PDF_RENDER_DPI", "PREVIEW_PDF_RENDER_MAX_DIM",
        "PREVIEW_VIDEO_FFMPEG_TIMEOUT_SECONDS",
    ])
    block("Archives (фоновая сборка ZIP папок)", [
        "ARCHIVE_MAX_FILES", "ARCHIVE_MAX_TOTAL_MB", "ARCHIVE_STREAM_CHUNK_BYTES",
        "ARCHIVE_DISK_SAFETY_FACTOR",
    ])
    block("Feature flags (возможности UI; GET /config)", [
        "FEATURE_PREVIEWS_ENABLED", "FEATURE_FILE_VIEWER_ENABLED",
        "FEATURE_MEDIA_PLAYBACK_ENABLED", "FEATURE_FILE_EDITING_ENABLED",
    ])
    block("Resource limits (лимиты контейнеров; docker-compose.yml)", [
        "POSTGRES_MEM_LIMIT", "POSTGRES_CPU_SHARES", "MINIO_MEM_LIMIT",
        "MINIO_CPU_SHARES", "API_MEM_LIMIT", "API_CPU_SHARES", "WORKER_MEM_LIMIT",
        "WORKER_CPU_SHARES", "FRONTEND_MEM_LIMIT", "FRONTEND_CPU_SHARES",
        "NGINX_MEM_LIMIT", "NGINX_CPU_SHARES",
    ])
    block("Postgres server tuning (docker-compose.yml)", [
        "POSTGRES_MAX_CONNECTIONS", "POSTGRES_SHARED_BUFFERS",
        "POSTGRES_EFFECTIVE_CACHE_SIZE", "POSTGRES_WORK_MEM",
        "POSTGRES_MAINTENANCE_WORK_MEM", "POSTGRES_MAX_WORKER_PROCESSES",
        "POSTGRES_MAX_PARALLEL_WORKERS", "POSTGRES_MAX_PARALLEL_WORKERS_PER_GATHER",
    ])

    return "\n".join(lines) + "\n"


# ── CLI ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Создаёт парсер аргументов командной строки."""

    parser = argparse.ArgumentParser(
        description=(
            "Генерирует .env под характеристики сервера (по умолчанию 85% "
            "ресурсов хоста). Значения считаются по docs/env-tuning-guide.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    res = parser.add_argument_group("ресурсы (сколько отдать приложению)")
    res.add_argument(
        "--fraction", type=float, default=DEFAULT_FRACTION,
        help="доля ресурсов хоста для приложения (0..1), по умолчанию 0.85",
    )
    res.add_argument(
        "--cpu", type=int, default=None,
        help="отдать ровно N ядер CPU (иначе round(всего*доля))",
    )
    res.add_argument(
        "--ram", type=str, default=None,
        help="отдать столько RAM (напр. 4G, 2048M; иначе всего*доля)",
    )
    res.add_argument(
        "--disk", type=str, default=None,
        help="отдать столько диска (напр. 128G; иначе свободно*доля)",
    )
    res.add_argument(
        "--disk-path", type=str, default="/var/lib/docker",
        help="путь, по тому которого мерить свободный диск (по умолчанию "
             "/var/lib/docker, иначе /)",
    )
    res.add_argument(
        "--users", type=int, default=3,
        help="ожидаемое число одновременно активных пользователей (для проверок)",
    )

    feat = parser.add_argument_group("функциональность")
    feat.add_argument("--no-previews", action="store_true",
                      help="выключить генерацию и показ превью (для слабых хостов)")
    feat.add_argument("--no-viewer", action="store_true",
                      help="выключить просмотрщик содержимого файлов")
    feat.add_argument("--no-playback", action="store_true",
                      help="выключить проигрывание аудио/видео")
    feat.add_argument("--no-editing", action="store_true",
                      help="выключить редактирование текстовых файлов")

    net = parser.add_argument_group("сеть")
    net.add_argument("--public-host", type=str, default="localhost",
                     help="внешний хост MinIO (как клиент видит сервер)")
    net.add_argument("--public-port", type=int, default=80,
                     help="внешний порт MinIO (по умолчанию 80)")

    out = parser.add_argument_group("вывод")
    out.add_argument("-o", "--output", type=str, default=str(DEFAULT_OUTPUT),
                     help="путь файла .env (по умолчанию ./.env)")
    out.add_argument("-f", "--force", action="store_true",
                     help="перезаписать существующий файл")
    out.add_argument("--dry-run", action="store_true",
                     help="напечатать в stdout, не записывать файл")
    out.add_argument("--no-gen-secrets", action="store_true",
                     help="не генерировать секреты (оставить плейсхолдеры)")
    out.add_argument("--rotate-secrets", action="store_true",
                     help="сгенерировать НОВЫЕ секреты, даже если в существующем "
                          ".env есть рабочие (ВНИМАНИЕ: сменит пароль БД — на уже "
                          "инициализированном томе Postgres контейнер не поднимется)")

    return parser


def resolve_budget(args: argparse.Namespace) -> HostBudget:
    """Определяет итоговый бюджет ресурсов из аргументов и характеристик хоста.

    Args:
        args: Разобранные аргументы командной строки.

    Returns:
        Итоговый бюджет ресурсов приложения.

    Raises:
        SystemExit: Если переданы некорректные значения.
    """

    if not 0.0 < args.fraction <= 1.0:
        raise SystemExit("--fraction должен быть в диапазоне (0, 1].")

    total_cpu = os.cpu_count() or 1
    total_ram = detect_total_ram_mb()
    total_disk = detect_free_disk_gb(Path(args.disk_path))

    cpu = args.cpu if args.cpu else max(1, round(total_cpu * args.fraction))
    ram = parse_size_mb(args.ram) if args.ram else max(256, int(total_ram * args.fraction))
    disk = parse_size_gb(args.disk) if args.disk else max(1.0, total_disk * args.fraction)

    if cpu < 1:
        raise SystemExit("--cpu должен быть ≥ 1.")

    return HostBudget(
        cpu=cpu, ram_mb=ram, disk_gb=disk, users=max(1, args.users),
        total_cpu=total_cpu, total_ram_mb=total_ram, total_disk_gb=total_disk,
        fraction=args.fraction,
    )


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: Список аргументов (по умолчанию `sys.argv`).

    Returns:
        Код возврата процесса.
    """

    args = build_parser().parse_args(argv)
    budget = resolve_budget(args)

    features = FeatureToggles(
        preview_generation=not args.no_previews,
        previews=not args.no_previews,
        viewer=not args.no_viewer,
        playback=not args.no_playback,
        editing=not args.no_editing,
    )

    config = compute_config(
        budget, features,
        public_host=args.public_host, public_port=args.public_port,
    )

    output_path = Path(args.output)

    generated_secrets: dict[str, str] = {}
    reused_secrets: dict[str, str] = {}
    if not args.no_gen_secrets:
        # Сохраняем рабочие секреты из существующего .env — иначе повторная
        # генерация под новые ресурсы сменила бы POSTGRES_PASSWORD и api не
        # смог бы подключиться к уже инициализированному тому Postgres.
        existing = read_existing_secrets(output_path)
        generated_secrets, reused_secrets = apply_generated_secrets(
            config.values, existing=existing, rotate=args.rotate_secrets,
        )

    content = render_env(config)

    # ── Печать сводки в stderr (чтобы stdout содержал чистый .env при --dry-run)
    summary = [
        "",
        f"Хост:      {budget.total_cpu} CPU / {budget.total_ram_mb} МБ / "
        f"{budget.total_disk_gb:.0f} ГБ свободно",
        f"Выделено:  {budget.cpu} CPU / {budget.ram_mb} МБ / "
        f"{budget.disk_gb:.0f} ГБ  (доля ~{budget.fraction:.0%})",
        f"Процессы:  UVICORN_WORKERS={config.values['UVICORN_WORKERS']}, "
        f"worker=1 → пул БД {config.values['POSTGRES_POOL_SIZE']}+"
        f"{config.values['POSTGRES_MAX_OVERFLOW']} на процесс, "
        f"max_connections={config.values['POSTGRES_MAX_CONNECTIONS']}",
        f"Память:    api {config.values['API_MEM_LIMIT']}, worker "
        f"{config.values['WORKER_MEM_LIMIT']}, postgres "
        f"{config.values['POSTGRES_MEM_LIMIT']}, minio "
        f"{config.values['MINIO_MEM_LIMIT']}",
    ]
    for line in summary:
        print(line, file=sys.stderr)
    for warning in config.warnings:
        print(f"⚠ {warning}", file=sys.stderr)

    if args.dry_run:
        print(content, end="")
        return 0

    if output_path.exists() and not args.force:
        print(
            f"\n✗ Файл уже существует: {output_path}. Перезапись отменена "
            f"(используйте --force).",
            file=sys.stderr,
        )
        return 1

    output_path.write_text(content, encoding="utf-8")
    try:
        output_path.chmod(0o600)
    except OSError:
        pass

    print(f"\n✓ Записан {output_path}", file=sys.stderr)
    if reused_secrets:
        print(
            f"\n🔒 Сохранены секреты из существующего .env "
            f"({', '.join(sorted(reused_secrets))}) — пароль БД не изменён, "
            "стек поднимется на текущем томе Postgres.",
            file=sys.stderr,
        )
    if generated_secrets and "ADMIN_PASSWORD" in generated_secrets:
        print("\nСгенерированы новые секреты (сохраните пароль администратора):",
              file=sys.stderr)
        print(f"  ADMIN_USERNAME = {config.values['ADMIN_USERNAME']}",
              file=sys.stderr)
        print(f"  ADMIN_PASSWORD = {generated_secrets['ADMIN_PASSWORD']}",
              file=sys.stderr)
    if generated_secrets and "POSTGRES_PASSWORD" in generated_secrets:
        print(
            "  ⚠ Сгенерирован НОВЫЙ POSTGRES_PASSWORD. Если том Postgres уже был "
            "инициализирован старым паролем, синхронизируйте его (см. README, "
            "раздел восстановления) или контейнер api не поднимется.",
            file=sys.stderr,
        )
    if args.no_gen_secrets:
        print(
            "\n⚠ Секреты НЕ сгенерированы (--no-gen-secrets): смените "
            "POSTGRES_PASSWORD / MINIO_SECRET_KEY / SECRET_KEY / ADMIN_PASSWORD "
            "вручную перед production-запуском.",
            file=sys.stderr,
        )

    print("\nДалее:\n  docker compose up -d --build\n  docker compose restart nginx",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
