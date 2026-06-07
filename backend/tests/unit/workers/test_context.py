"""Тесты контекста воркера: генерация worker_id и сборка зависимостей."""

from __future__ import annotations

import os
import socket
from unittest.mock import MagicMock, patch

from core.constants import WorkerConstants
from workers.context import (
    WorkerContext,
    WorkerServices,
    build_worker_context,
    generate_worker_id,
)


class TestGenerateWorkerId:
    def test_returns_non_empty_string(self) -> None:
        worker_id = generate_worker_id()
        assert isinstance(worker_id, str)
        assert len(worker_id) > 0

    def test_contains_default_prefix(self) -> None:
        worker_id = generate_worker_id()
        assert worker_id.startswith(WorkerConstants.WORKER_NAME_PREFIX)

    def test_contains_hostname(self) -> None:
        worker_id = generate_worker_id()
        hostname = socket.gethostname().strip().lower() or "unknown-host"
        assert hostname in worker_id

    def test_contains_pid(self) -> None:
        worker_id = generate_worker_id()
        pid = str(os.getpid())
        assert pid in worker_id

    def test_with_custom_prefix_uses_it(self) -> None:
        worker_id = generate_worker_id(prefix="my-service")
        assert worker_id.startswith("my-service")

    def test_with_none_prefix_uses_default(self) -> None:
        worker_id = generate_worker_id(prefix=None)
        assert worker_id.startswith(WorkerConstants.WORKER_NAME_PREFIX)

    def test_with_empty_string_prefix_uses_default(self) -> None:
        worker_id = generate_worker_id(prefix="")
        assert worker_id.startswith(WorkerConstants.WORKER_NAME_PREFIX)

    def test_with_whitespace_only_prefix_uses_default(self) -> None:
        worker_id = generate_worker_id(prefix="   ")
        assert worker_id.startswith(WorkerConstants.WORKER_NAME_PREFIX)

    def test_two_calls_return_different_values(self) -> None:
        id1 = generate_worker_id()
        id2 = generate_worker_id()
        # Короткий фрагмент UUID (последние 8 hex-символов) должен отличаться
        assert id1 != id2

    def test_format_has_four_dash_separated_segments(self) -> None:
        # Ожидаемый формат: {prefix}-{hostname}-{pid}-{short_uuid}
        # prefix и hostname могут содержать дефисы,
        # поэтому проверяем хотя бы short_uuid (8 hex-символов) в конце
        worker_id = generate_worker_id(prefix="worker")
        parts = worker_id.split("-")
        # Последний сегмент — 8-символьный hex-фрагмент UUID
        assert len(parts[-1]) == 8
        assert all(c in "0123456789abcdef" for c in parts[-1])

    def test_whitespace_stripped_from_prefix(self) -> None:
        worker_id = generate_worker_id(prefix="  myprefix  ")
        assert worker_id.startswith("myprefix")


# ---------------------------------------------------------------------------
# build_worker_context
# ---------------------------------------------------------------------------


class TestBuildWorkerContext:
    def _run(self, worker_id=None, worker_name="cfg-worker-name"):
        settings = MagicMock()
        settings.workers = MagicMock()
        settings.workers.worker_name = worker_name
        settings.storage = MagicMock()

        targets = {
            "get_settings": MagicMock(return_value=settings),
            "create_unit_of_work_factory": MagicMock(),
            "get_storage_service": MagicMock(),
            "get_access_service": MagicMock(),
            "get_audit_service": MagicMock(),
            "get_tasks_service": MagicMock(),
            "get_trash_service": MagicMock(),
            "get_uploads_service": MagicMock(),
            "get_public_links_service": MagicMock(),
            "get_downloads_service": MagicMock(),
            "get_quotas_service": MagicMock(),
            "get_health_service": MagicMock(),
        }
        patchers = [patch(f"workers.context.{name}", mock) for name, mock in targets.items()]
        for p in patchers:
            p.start()
        try:
            ctx = build_worker_context(worker_id=worker_id)
        finally:
            for p in patchers:
                p.stop()
        return ctx, settings, targets

    def test_returns_worker_context(self) -> None:
        ctx, settings, targets = self._run()
        assert isinstance(ctx, WorkerContext)
        assert ctx.settings is settings
        assert ctx.worker_settings is settings.workers

    def test_uses_uow_factory_and_storage_service(self) -> None:
        ctx, settings, targets = self._run()
        assert ctx.uow_factory is targets["create_unit_of_work_factory"].return_value
        assert ctx.storage_service is targets["get_storage_service"].return_value
        targets["get_storage_service"].assert_called_once_with(
            settings=settings.storage
        )

    def test_services_container_is_populated(self) -> None:
        ctx, settings, targets = self._run()
        assert isinstance(ctx.services, WorkerServices)
        assert ctx.services.access is targets["get_access_service"].return_value
        assert ctx.services.audit is targets["get_audit_service"].return_value
        assert ctx.services.tasks is targets["get_tasks_service"].return_value
        assert ctx.services.trash is targets["get_trash_service"].return_value
        assert ctx.services.uploads is targets["get_uploads_service"].return_value
        assert (
            ctx.services.public_links
            is targets["get_public_links_service"].return_value
        )
        assert ctx.services.quotas is targets["get_quotas_service"].return_value
        assert ctx.services.downloads is targets["get_downloads_service"].return_value
        assert ctx.services.health is targets["get_health_service"].return_value

    def test_explicit_worker_id_wins(self) -> None:
        ctx, _settings, _targets = self._run(worker_id="explicit-id")
        assert ctx.worker_id == "explicit-id"

    def test_falls_back_to_settings_worker_name(self) -> None:
        ctx, _settings, _targets = self._run(
            worker_id=None, worker_name="cfg-worker-name"
        )
        assert ctx.worker_id == "cfg-worker-name"

    def test_generates_worker_id_when_none_available(self) -> None:
        ctx, _settings, _targets = self._run(worker_id=None, worker_name=None)
        assert ctx.worker_id.startswith(WorkerConstants.WORKER_NAME_PREFIX)

    def test_services_wired_with_shared_dependencies(self) -> None:
        ctx, settings, targets = self._run()
        uow = targets["create_unit_of_work_factory"].return_value
        audit = targets["get_audit_service"].return_value
        targets["get_access_service"].assert_called_once_with(uow_factory=uow)
        targets["get_audit_service"].assert_called_once_with(uow_factory=uow)
        targets["get_tasks_service"].assert_called_once_with(
            uow_factory=uow, audit_service=audit
        )
