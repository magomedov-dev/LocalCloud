"""Unit-тесты для recalculate_user_quota_handler."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from workers.quotas import recalculate_user_quota_handler
from workers.types import WorkerTaskExecutionResult


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_uow():
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.users = AsyncMock()
    uow.users.list_active_users = AsyncMock(return_value=[])
    return uow


def make_exec_context(payload=None):
    ctx = MagicMock()
    ctx.task_id = uuid.uuid4()
    ctx.payload = payload or {}
    ctx.worker_id = "w-001"
    ctx.settings = MagicMock()
    ctx.worker_settings = MagicMock()
    ctx.worker_settings.worker_quota_batch_size = 50

    uow = make_uow()
    ctx.uow_factory = MagicMock(return_value=uow)

    quotas_service = MagicMock()
    quotas_service.recalculate_quota = AsyncMock(return_value=None)

    services = MagicMock()
    services.quotas = quotas_service
    ctx.services = services

    return ctx, uow


# ---------------------------------------------------------------------------
# recalculate_user_quota_handler — один пользователь
# ---------------------------------------------------------------------------

class TestRecalculateUserQuotaHandlerSingleUser:
    @pytest.mark.asyncio
    async def test_valid_user_id_returns_success(self) -> None:
        user_id = uuid.uuid4()
        ctx, uow = make_exec_context(payload={"user_id": str(user_id)})
        result = await recalculate_user_quota_handler(ctx)

        assert isinstance(result, WorkerTaskExecutionResult)
        assert result.success is True
        assert result.result_data["users_processed"] == 1
        assert result.result_data["recalculated_count"] == 1
        assert result.result_data["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_valid_uuid_object_in_payload_returns_success(self) -> None:
        user_id = uuid.uuid4()
        ctx, uow = make_exec_context(payload={"user_id": user_id})
        result = await recalculate_user_quota_handler(ctx)

        assert result.success is True
        assert result.result_data["recalculated_count"] == 1

    @pytest.mark.asyncio
    async def test_service_error_for_single_user_counted_as_failed(self) -> None:
        user_id = uuid.uuid4()
        ctx, uow = make_exec_context(payload={"user_id": str(user_id)})
        ctx.services.quotas.recalculate_quota = AsyncMock(
            side_effect=RuntimeError("quota service down")
        )

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is True
        assert result.result_data["recalculated_count"] == 0
        assert result.result_data["failed_count"] == 1


# ---------------------------------------------------------------------------
# recalculate_user_quota_handler — пакетный режим (без user_id)
# ---------------------------------------------------------------------------

class TestRecalculateUserQuotaHandlerBatch:
    @pytest.mark.asyncio
    async def test_no_users_returns_success_with_zero_counts(self) -> None:
        ctx, uow = make_exec_context()  # без user_id в payload
        uow.users.list_active_users = AsyncMock(return_value=[])

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is True
        assert result.result_data["users_processed"] == 0
        assert result.result_data["recalculated_count"] == 0
        assert result.result_data["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_batch_processes_all_users(self) -> None:
        ctx, uow = make_exec_context()
        users = [MagicMock(id=uuid.uuid4()) for _ in range(3)]
        uow.users.list_active_users = AsyncMock(return_value=users)

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is True
        assert result.result_data["users_processed"] == 3
        assert result.result_data["recalculated_count"] == 3
        assert result.result_data["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_batch_counts_failed_users(self) -> None:
        ctx, uow = make_exec_context()
        users = [MagicMock(id=uuid.uuid4()) for _ in range(4)]
        uow.users.list_active_users = AsyncMock(return_value=users)

        call_count = 0

        async def quota_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise RuntimeError("recalculate failed for this user")

        ctx.services.quotas.recalculate_quota = AsyncMock(side_effect=quota_side_effect)

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is True
        assert result.result_data["users_processed"] == 4
        assert result.result_data["recalculated_count"] == 2
        assert result.result_data["failed_count"] == 2

    @pytest.mark.asyncio
    async def test_with_custom_limit(self) -> None:
        ctx, uow = make_exec_context(payload={"limit": 10})
        users = [MagicMock(id=uuid.uuid4()) for _ in range(2)]
        uow.users.list_active_users = AsyncMock(return_value=users)

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is True
        uow.users.list_active_users.assert_called_once_with(limit=10)


# ---------------------------------------------------------------------------
# recalculate_user_quota_handler — обработка ошибок
# ---------------------------------------------------------------------------

class TestRecalculateUserQuotaHandlerErrors:
    @pytest.mark.asyncio
    async def test_database_connection_error_returns_retry(self) -> None:
        from database.exceptions import DatabaseConnectionError
        ctx, uow = make_exec_context()
        uow.users.list_active_users = AsyncMock(
            side_effect=DatabaseConnectionError("db unreachable")
        )

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is False
        assert result.retry is True
        assert result.error_code == "temporary_unavailable"

    @pytest.mark.asyncio
    async def test_service_error_returns_failure(self) -> None:
        from services.exceptions import ServiceError
        ctx, uow = make_exec_context()
        uow.users.list_active_users = AsyncMock(
            side_effect=ServiceError("service broken")
        )

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is False
        assert result.retry is False
        assert result.error_code == "recalculate_user_quota_failed"

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_failure(self) -> None:
        ctx, uow = make_exec_context()
        uow.users.list_active_users = AsyncMock(
            side_effect=Exception("unexpected crash")
        )

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is False
        assert result.error_code == "unexpected_recalculate_user_quota_error"

    @pytest.mark.asyncio
    async def test_invalid_user_id_string_raises(self) -> None:
        ctx, uow = make_exec_context(payload={"user_id": "not-a-valid-uuid"})

        # ValueError из UUID("not-a-valid-uuid") должна всплыть как непредвиденное исключение
        result = await recalculate_user_quota_handler(ctx)

        # Должно быть перехвачено и возвращено как неуспех
        assert result.success is False

    @pytest.mark.asyncio
    async def test_non_uuid_user_id_type_raises(self) -> None:
        # user_id, который не UUID и не str, задействует ветку ValueError
        # в _optional_payload_uuid (Поле payload должно быть UUID или строкой UUID).
        ctx, uow = make_exec_context(payload={"user_id": 12345})

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is False


# ---------------------------------------------------------------------------
# откат limit, когда настройка batch-size равна None
# ---------------------------------------------------------------------------

class TestRecalculateUserQuotaHandlerLimitFallback:
    @pytest.mark.asyncio
    async def test_limit_falls_back_to_batch_size_when_payload_limit_absent(
        self,
    ) -> None:
        # Когда limit нельзя получить из payload (настройка batch-size равна None,
        # и значение по умолчанию payload_int тоже None), обработчик оставляет limit None.
        ctx, uow = make_exec_context()
        ctx.worker_settings.worker_quota_batch_size = None
        uow.users.list_active_users = AsyncMock(return_value=[])

        result = await recalculate_user_quota_handler(ctx)

        assert result.success is True
        assert result.result_data["users_processed"] == 0
