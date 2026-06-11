"""Тесты генератора .env (scripts/generate_env.py).

Запуск:
    backend/.venv/bin/python -m pytest scripts/test_generate_env.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "generate_env", Path(__file__).with_name("generate_env.py")
)
gen = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
# Регистрируем модуль до exec_module: dataclasses резолвят аннотации через
# sys.modules[cls.__module__], иначе сборка @dataclass падает.
sys.modules["generate_env"] = gen
_SPEC.loader.exec_module(gen)


def _budget(cpu: int, ram_mb: int, disk_gb: float, users: int = 3) -> gen.HostBudget:
    return gen.HostBudget(
        cpu=cpu, ram_mb=ram_mb, disk_gb=disk_gb, users=users,
        total_cpu=cpu, total_ram_mb=ram_mb, total_disk_gb=disk_gb, fraction=0.85,
    )


def _config(cpu: int, ram_mb: int, disk_gb: float, **kw) -> gen.GeneratedConfig:
    return gen.compute_config(
        _budget(cpu, ram_mb, disk_gb, kw.pop("users", 3)),
        kw.pop("features", gen.FeatureToggles()),
        public_host=kw.pop("public_host", "localhost"),
        public_port=kw.pop("public_port", 80),
    )


class TestSizeParsing:
    @pytest.mark.parametrize("text,mb", [
        ("512", 512), ("512M", 512), ("4G", 4096), ("2g", 2048), ("1024k", 1),
    ])
    def test_parse_size_mb(self, text: str, mb: int) -> None:
        assert gen.parse_size_mb(text) == mb

    @pytest.mark.parametrize("text,gb", [
        ("128", 128.0), ("128G", 128.0), ("1T", 1024.0), ("512m", 0.5),
    ])
    def test_parse_size_gb(self, text: str, gb: float) -> None:
        assert gen.parse_size_gb(text) == gb


class TestMemoryAllocation:
    def test_sum_fits_budget_on_normal_host(self) -> None:
        alloc = gen.allocate_memory(4096)
        assert sum(alloc.values()) <= 4096

    def test_minimums_enforced_on_tiny_host(self) -> None:
        alloc = gen.allocate_memory(1024)
        assert alloc["postgres"] >= 220
        assert alloc["api"] >= 200
        assert alloc["minio"] >= 256
        assert alloc["worker"] >= 200

    def test_fixed_small_containers(self) -> None:
        assert gen.allocate_memory(1024)["frontend"] == 32
        assert gen.allocate_memory(8192)["frontend"] == 64


class TestComputeInvariants:
    def test_connection_budget_holds(self) -> None:
        cfg = _config(4, 8192, 200)
        procs = int(cfg.values["UVICORN_WORKERS"]) + 1
        per = int(cfg.values["POSTGRES_POOL_SIZE"]) + int(cfg.values["POSTGRES_MAX_OVERFLOW"])
        assert procs * per + 10 <= int(cfg.values["POSTGRES_MAX_CONNECTIONS"])

    def test_workers_scale_with_cpu(self) -> None:
        assert _config(1, 1024, 20).values["UVICORN_WORKERS"] == "1"
        assert _config(2, 4096, 64).values["UVICORN_WORKERS"] == "2"
        assert _config(4, 8192, 200).values["UVICORN_WORKERS"] == "3"

    def test_tiny_host_emits_memory_warning(self) -> None:
        cfg = _config(1, 1024, 20)
        assert any("mem_limit" in w for w in cfg.warnings)

    def test_thumbnail_below_pool(self) -> None:
        cfg = _config(4, 8192, 200)
        per = int(cfg.values["POSTGRES_POOL_SIZE"]) + int(cfg.values["POSTGRES_MAX_OVERFLOW"])
        assert int(cfg.values["THUMBNAIL_BATCH_CONCURRENCY"]) < per

    def test_preview_limits_grow_with_ram(self) -> None:
        small = int(_config(1, 1024, 20).values["PREVIEW_IMAGE_MAX_SOURCE_MB"])
        big = int(_config(4, 8192, 200).values["PREVIEW_IMAGE_MAX_SOURCE_MB"])
        assert big > small

    def test_storage_capacity_leaves_disk_reserve(self) -> None:
        disk_gb = 200
        cfg = _config(4, 8192, disk_gb)
        assert int(cfg.values["STORAGE_CAPACITY_BYTES"]) < disk_gb * (1024**3)

    def test_render_concurrency_at_least_one(self) -> None:
        assert int(_config(1, 1024, 20).values["PREVIEW_RENDER_CONCURRENCY"]) >= 1


class TestFeatureToggles:
    def test_disabled_previews_propagate(self) -> None:
        cfg = _config(2, 4096, 64, features=gen.FeatureToggles(
            preview_generation=False, previews=False))
        assert cfg.values["PREVIEW_GENERATION_ENABLED"] == "false"
        assert cfg.values["FEATURE_PREVIEWS_ENABLED"] == "false"

    def test_all_enabled_by_default(self) -> None:
        cfg = _config(2, 4096, 64)
        assert cfg.values["FEATURE_FILE_EDITING_ENABLED"] == "true"


class TestSecrets:
    def test_strong_password_has_all_classes(self) -> None:
        pw = gen.generate_strong_password(20)
        assert any(c.islower() for c in pw)
        assert any(c.isupper() for c in pw)
        assert any(c.isdigit() for c in pw)

    def test_secrets_have_no_interpolation_chars(self) -> None:
        # `$` ломает интерполяцию docker-compose/python-dotenv — его быть не должно.
        for _ in range(50):
            assert "$" not in gen.generate_strong_password(20)
        values: dict[str, str] = {}
        gen.apply_generated_secrets(values)
        assert "$" not in values["ADMIN_PASSWORD"]
        assert "$" not in values["SECRET_KEY"]


class TestRendering:
    def test_render_contains_all_keys(self) -> None:
        cfg = _config(2, 4096, 64)
        text = gen.render_env(cfg)
        for key in cfg.values:
            assert f"{key}=" in text

    def test_mem_formatting(self) -> None:
        assert gen._fmt_mem(2048) == "2g"
        assert gen._fmt_mem(768) == "768m"
