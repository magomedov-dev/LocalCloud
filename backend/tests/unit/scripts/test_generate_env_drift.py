"""Drift-guard и валидация для scripts/generate_env.py.

Эти тесты — единственное место, где генератор `.env` сверяется с реальной
поверхностью конфигурации приложения. Они гарантируют, что:

1. генератор эмитит КАЖДЫЙ pydantic-алиас настроек (кроме явно управляемых
   docker-compose), — иначе новая настройка молча «выпала» бы из
   server-tuned `.env` и работала бы на коде-дефолте;
2. все сгенерированные значения проходят валидацию pydantic-границ
   (ge/le/gt/типы) на разных профилях хоста;
3. согласованность пула БД (та же формула, что в core.secret_validation —
   warn_if_db_pool_oversized) выполняется на всех профилях;
4. server-зависимые значения масштабируются по CPU.

Сам генератор не зависит от backend (запускается на чистом хосте), поэтому
сверка живёт здесь, где доступны core.config и pydantic.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from core import config as app_config

# Алиасы, которые НЕ должны попадать в .env: их задаёт docker-compose через
# блок environment (внутренние имена сервисов) или это внутренние константы
# маршрутизации, не предназначенные для тюнинга.
_COMPOSE_MANAGED_ALIASES = {
    "API_PREFIX",
    "API_V1_PREFIX",
    "MINIO_HOST",
    "MINIO_PORT",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
}

_GENERATOR_PATH = (
    Path(__file__).resolve().parents[4] / "scripts" / "generate_env.py"
)


def _load_generator():
    """Импортирует модуль генератора по пути (он вне пакета backend)."""
    spec = importlib.util.spec_from_file_location(
        "generate_env_under_test", _GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _all_pydantic_aliases() -> set[str]:
    """Собирает все env-алиасы из Settings-классов приложения."""
    aliases: set[str] = set()
    for obj in vars(app_config).values():
        if (
            isinstance(obj, type)
            and issubclass(obj, (BaseSettings, BaseModel))
            and obj not in (BaseSettings, BaseModel)
        ):
            for field in getattr(obj, "model_fields", {}).values():
                if field.alias:
                    aliases.add(field.alias)
    return aliases


def _sub_settings_classes() -> list[type[BaseSettings]]:
    return [
        obj
        for obj in vars(app_config).values()
        if isinstance(obj, type)
        and issubclass(obj, BaseSettings)
        and obj is not BaseSettings
    ]


def _generate(gen, *, cpu: int, ram_mb: int, disk_gb: float):
    budget = gen.HostBudget(
        cpu=cpu,
        ram_mb=ram_mb,
        disk_gb=disk_gb,
        users=3,
        total_cpu=cpu,
        total_ram_mb=ram_mb,
        total_disk_gb=disk_gb,
        fraction=1.0,
    )
    return gen.compute_config(
        budget, gen.FeatureToggles(), public_host="localhost", public_port=80
    )


_PROFILES = [
    (1, 1024, 20),  # tiny
    (2, 4096, 100),  # small/medium
    (4, 8192, 500),  # medium
    (8, 16384, 2000),  # large
]


class TestGeneratorCompleteness:
    def test_emits_every_config_alias(self) -> None:
        """Каждая настройка приложения присутствует в сгенерированном .env."""
        gen = _load_generator()
        cfg = _generate(gen, cpu=2, ram_mb=4096, disk_gb=100)
        emitted = set(cfg.values)
        expected = _all_pydantic_aliases() - _COMPOSE_MANAGED_ALIASES

        missing = sorted(expected - emitted)
        assert not missing, (
            "Генератор .env не эмитит настройки: "
            f"{missing}. Добавьте их в scripts/generate_env.py или, если они "
            "управляются docker-compose, в _COMPOSE_MANAGED_ALIASES."
        )

    def test_excluded_aliases_really_exist(self) -> None:
        """Список исключений не содержит «мёртвых» имён (тоже защита от дрейфа)."""
        stale = _COMPOSE_MANAGED_ALIASES - _all_pydantic_aliases()
        assert not stale, f"Исключения ссылаются на несуществующие алиасы: {stale}"


class TestGeneratedValuesValid:
    @pytest.mark.parametrize("cpu,ram,disk", _PROFILES)
    def test_values_pass_pydantic_bounds(self, cpu, ram, disk) -> None:
        """Сгенерированные значения проходят валидацию границ всех Settings."""
        gen = _load_generator()
        cfg = _generate(gen, cpu=cpu, ram_mb=ram, disk_gb=disk)

        saved = dict(os.environ)
        try:
            os.environ.update({k: str(v) for k, v in cfg.values.items()})
            for cls in _sub_settings_classes():
                cls(_env_file=None)  # бросит ValidationError при нарушении границ
        finally:
            os.environ.clear()
            os.environ.update(saved)


class TestPoolConsistency:
    @pytest.mark.parametrize("cpu,ram,disk", _PROFILES)
    def test_db_pool_within_max_connections(self, cpu, ram, disk) -> None:
        """Пул БД согласован с POSTGRES_MAX_CONNECTIONS (формула E6)."""
        gen = _load_generator()
        v = _generate(gen, cpu=cpu, ram_mb=ram, disk_gb=disk).values

        procs = int(v["UVICORN_WORKERS"]) + 1
        per_process = int(v["POSTGRES_POOL_SIZE"]) + int(v["POSTGRES_MAX_OVERFLOW"])
        required = procs * per_process
        max_connections = int(v["POSTGRES_MAX_CONNECTIONS"])
        # +10 — тот же запас, что в warn_if_db_pool_oversized.
        assert required + 10 <= max_connections


class TestServerScaling:
    def test_concurrency_scales_with_cpu(self) -> None:
        """Параллелизм воркера/integrity растёт с числом ядер."""
        gen = _load_generator()
        small = _generate(gen, cpu=1, ram_mb=1024, disk_gb=20).values
        large = _generate(gen, cpu=8, ram_mb=16384, disk_gb=2000).values

        assert int(large["WORKER_MAX_CONCURRENT_TASKS"]) > int(
            small["WORKER_MAX_CONCURRENT_TASKS"]
        )
        assert int(large["WORKER_INTEGRITY_CONCURRENCY"]) > int(
            small["WORKER_INTEGRITY_CONCURRENCY"]
        )
        assert int(large["STORAGE_EXECUTOR_MAX_WORKERS"]) > int(
            small["STORAGE_EXECUTOR_MAX_WORKERS"]
        )

    def test_secret_placeholder_is_flagged_by_validator(self) -> None:
        """Плейсхолдер SECRET_KEY (без --gen-secrets) ловится валидатором B2."""
        from core.secret_validation import _is_insecure

        gen = _load_generator()
        v = _generate(gen, cpu=2, ram_mb=4096, disk_gb=100).values
        # Все три секрета-плейсхолдера должны распознаваться как небезопасные,
        # иначе старт в production не отклонит дефолтный .env.
        assert _is_insecure(v["SECRET_KEY"]) is not None
        assert _is_insecure(v["POSTGRES_PASSWORD"]) is not None
        assert _is_insecure(v["MINIO_SECRET_KEY"]) is not None
