"""Unit-тесты для clean_expired_public_links_handler."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from workers.public_links import clean_expired_public_links_handler
from workers.types import WorkerTaskExecutionResult


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_uow():
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.links = AsyncMock()
    uow.links.find_expired_links = AsyncMock(return_value=[])
    uow.links.mark_link_expired_by_id = AsyncMock(return_value=None)
    return uow


def make_exec_context(payload=None):
    ctx = MagicMock()
    ctx.task_id = uuid.uuid4()
    ctx.payload = payload or {}
    ctx.worker_id = "w-001"
    ctx.settings = MagicMock()
    ctx.worker_settings = MagicMock()

    uow = make_uow()
    ctx.uow_factory = MagicMock(return_value=uow)

    ctx.storage_service = MagicMock()
    ctx.services = MagicMock(spec=[])  # по умолчанию сервисов нет
    return ctx, uow


# ---------------------------------------------------------------------------
# clean_expired_public_links_handler — пустой список ссылок
# ---------------------------------------------------------------------------

class TestCleanExpiredPublicLinksHandlerEmpty:
    @pytest.mark.asyncio
    async def test_empty_expired_links_returns_success_with_zero_count(self) -> None:
        ctx, uow = make_exec_context()
        uow.links.find_expired_links = AsyncMock(return_value=[])

        result = await clean_expired_public_links_handler(ctx)

        assert isinstance(result, WorkerTaskExecutionResult)
        assert result.success is True
        assert result.result_data["scanned_count"] == 0
        assert result.result_data["expired_count"] == 0
        assert result.result_data["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_with_expired_before_in_payload(self) -> None:
        expired_before = datetime.now(UTC).isoformat()
        ctx, uow = make_exec_context(payload={"expired_before": expired_before})
        uow.links.find_expired_links = AsyncMock(return_value=[])

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is True


# ---------------------------------------------------------------------------
# clean_expired_public_links_handler — со ссылками
# ---------------------------------------------------------------------------

class TestCleanExpiredPublicLinksHandlerWithLinks:
    @pytest.mark.asyncio
    async def test_single_link_marked_expired(self) -> None:
        ctx, uow = make_exec_context()

        link = MagicMock()
        link.id = uuid.uuid4()
        link.node_id = uuid.uuid4()

        # Первый вызов UoW: find_expired_links
        # Второй вызов UoW: mark_link_expired_by_id
        updated_link = MagicMock()
        updated_link.id = link.id
        updated_link.node_id = link.node_id

        uow.links.find_expired_links = AsyncMock(return_value=[link])
        uow.links.mark_link_expired_by_id = AsyncMock(return_value=updated_link)

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is True
        assert result.result_data["scanned_count"] == 1
        assert result.result_data["expired_count"] == 1
        assert result.result_data["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_multiple_links_all_marked(self) -> None:
        ctx, uow = make_exec_context()

        links = []
        for _ in range(3):
            link = MagicMock()
            link.id = uuid.uuid4()
            link.node_id = uuid.uuid4()
            links.append(link)

        uow.links.find_expired_links = AsyncMock(return_value=links)
        uow.links.mark_link_expired_by_id = AsyncMock(
            side_effect=[
                MagicMock(id=lnk.id, node_id=lnk.node_id) for lnk in links
            ]
        )

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is True
        assert result.result_data["scanned_count"] == 3
        assert result.result_data["expired_count"] == 3
        assert result.result_data["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_failed_link_counted_in_failed(self) -> None:
        ctx, uow = make_exec_context()

        links = [MagicMock(id=uuid.uuid4(), node_id=uuid.uuid4()) for _ in range(2)]
        uow.links.find_expired_links = AsyncMock(return_value=links)

        call_count = 0

        async def mark_side_effect(link_id, flush, refresh):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("db failure")
            return MagicMock(id=link_id, node_id=uuid.uuid4())

        uow.links.mark_link_expired_by_id = AsyncMock(side_effect=mark_side_effect)

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is True
        assert result.result_data["scanned_count"] == 2
        assert result.result_data["expired_count"] == 1
        assert result.result_data["failed_count"] == 1

    @pytest.mark.asyncio
    async def test_with_custom_limit(self) -> None:
        ctx, uow = make_exec_context(payload={"limit": 100})
        uow.links.find_expired_links = AsyncMock(return_value=[])

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is True
        call_kwargs = uow.links.find_expired_links.call_args[1]
        assert call_kwargs.get("limit") == 100


# ---------------------------------------------------------------------------
# обработка ошибок
# ---------------------------------------------------------------------------

class TestCleanExpiredPublicLinksHandlerErrors:
    @pytest.mark.asyncio
    async def test_database_connection_error_returns_retry(self) -> None:
        from database.exceptions import DatabaseConnectionError
        ctx, uow = make_exec_context()
        uow.links.find_expired_links = AsyncMock(
            side_effect=DatabaseConnectionError("db unreachable")
        )

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is False
        assert result.retry is True
        assert result.error_code == "temporary_unavailable"

    @pytest.mark.asyncio
    async def test_storage_connection_error_returns_retry(self) -> None:
        from storage.exceptions import StorageConnectionError
        ctx, uow = make_exec_context()
        uow.links.find_expired_links = AsyncMock(
            side_effect=StorageConnectionError("storage unreachable")
        )

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is False
        assert result.retry is True

    @pytest.mark.asyncio
    async def test_service_error_returns_failure(self) -> None:
        from services.exceptions import ServiceError
        ctx, uow = make_exec_context()
        uow.links.find_expired_links = AsyncMock(
            side_effect=ServiceError("service failed")
        )

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is False
        assert result.retry is False
        assert result.error_code == "cleanup_expired_public_links_failed"

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_failure(self) -> None:
        ctx, uow = make_exec_context()
        uow.links.find_expired_links = AsyncMock(
            side_effect=Exception("unexpected crash")
        )

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is False
        assert result.error_code == "unexpected_cleanup_expired_public_links_error"


# ---------------------------------------------------------------------------
# логирование аудита (опционально)
# ---------------------------------------------------------------------------

class TestAuditLogging:
    @pytest.mark.asyncio
    async def test_audit_service_called_when_available(self) -> None:
        ctx, uow = make_exec_context()

        link = MagicMock()
        link.id = uuid.uuid4()
        link.node_id = uuid.uuid4()
        updated_link = MagicMock(id=link.id, node_id=link.node_id)

        uow.links.find_expired_links = AsyncMock(return_value=[link])
        uow.links.mark_link_expired_by_id = AsyncMock(return_value=updated_link)

        # Добавляем сервис аудита
        audit_service = MagicMock()
        audit_service.log_success = MagicMock(return_value=None)
        ctx.services = MagicMock()
        ctx.services.audit = audit_service

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is True
        audit_service.log_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_log_success_not_callable_is_skipped(self) -> None:
        # Если log_success есть, но не вызываемый, хелпер аудита завершается
        # рано без исключения, и обработчик всё равно успешен.
        ctx, uow = make_exec_context()

        link = MagicMock()
        link.id = uuid.uuid4()
        link.node_id = uuid.uuid4()
        updated_link = MagicMock(id=link.id, node_id=link.node_id)

        uow.links.find_expired_links = AsyncMock(return_value=[link])
        uow.links.mark_link_expired_by_id = AsyncMock(return_value=updated_link)

        audit_service = MagicMock()
        audit_service.log_success = "not-callable"  # атрибут есть, но не вызываемый
        ctx.services = MagicMock()
        ctx.services.audit = audit_service

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is True
        assert result.result_data["expired_count"] == 1

    @pytest.mark.asyncio
    async def test_audit_log_success_async_result_is_awaited(self) -> None:
        # Если log_success возвращает awaitable, обработчик его ожидает.
        ctx, uow = make_exec_context()

        link = MagicMock()
        link.id = uuid.uuid4()
        link.node_id = uuid.uuid4()
        updated_link = MagicMock(id=link.id, node_id=link.node_id)

        uow.links.find_expired_links = AsyncMock(return_value=[link])
        uow.links.mark_link_expired_by_id = AsyncMock(return_value=updated_link)

        audit_service = MagicMock()
        audit_service.log_success = AsyncMock(return_value=None)
        ctx.services = MagicMock()
        ctx.services.audit = audit_service

        result = await clean_expired_public_links_handler(ctx)

        assert result.success is True
        audit_service.log_success.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_audit_error_does_not_break_handler(self) -> None:
        ctx, uow = make_exec_context()

        link = MagicMock()
        link.id = uuid.uuid4()
        link.node_id = uuid.uuid4()
        updated_link = MagicMock(id=link.id, node_id=link.node_id)

        uow.links.find_expired_links = AsyncMock(return_value=[link])
        uow.links.mark_link_expired_by_id = AsyncMock(return_value=updated_link)

        # Добавляем падающий сервис аудита
        audit_service = MagicMock()
        audit_service.log_success = MagicMock(side_effect=RuntimeError("audit failed"))
        ctx.services = MagicMock()
        ctx.services.audit = audit_service

        result = await clean_expired_public_links_handler(ctx)

        # Сбой аудита не должен приводить к сбою обработчика
        assert result.success is True
        assert result.result_data["expired_count"] == 1
