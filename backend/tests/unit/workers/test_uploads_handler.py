"""Тесты обработчика очистки истёкших загрузок (clean_expired_uploads_handler)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from workers.types import WorkerTaskExecutionResult
from workers.uploads import clean_expired_uploads_handler


def make_exec_ctx(payload=None):
    ctx = MagicMock()
    ctx.task_id = uuid.uuid4()
    ctx.payload = payload or {}
    ctx.worker_id = "w-001"

    ctx.worker_settings = MagicMock()
    ctx.worker_settings.worker_cleanup_batch_size = 10

    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.upload_sessions = AsyncMock()
    uow.upload_sessions.find_expired_sessions = AsyncMock(return_value=[])
    uow.quotas = AsyncMock()
    ctx.uow_factory = MagicMock(return_value=uow)

    ctx.storage_service = MagicMock()
    ctx.storage_service.abort_multipart_upload = AsyncMock(return_value=True)

    # Сервис uploads без clean_expired_uploads (None = не вызывается)
    ctx.services = MagicMock()
    ctx.services.uploads.clean_expired_uploads = None  # не вызывается → используется fallback

    return ctx, uow


class TestCleanExpiredUploadsHandler:
    @pytest.mark.asyncio
    async def test_returns_success_with_empty_sessions(self) -> None:
        ctx, uow = make_exec_ctx()
        result = await clean_expired_uploads_handler(ctx)
        assert isinstance(result, WorkerTaskExecutionResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_result_data_contains_counts(self) -> None:
        ctx, uow = make_exec_ctx()
        result = await clean_expired_uploads_handler(ctx)
        assert result.result_data is not None
        assert "scanned_count" in result.result_data
        assert "expired_count" in result.result_data

    @pytest.mark.asyncio
    async def test_uses_service_if_available(self) -> None:
        ctx, uow = make_exec_ctx()
        # Предоставляем clean_expired_uploads в сервисах
        ctx.services.uploads = MagicMock()
        ctx.services.uploads.clean_expired_uploads = AsyncMock(
            return_value={"scanned_count": 5, "expired_count": 3,
                          "aborted_storage_uploads_count": 3, "failed_count": 0}
        )
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True
        assert result.result_data["scanned_count"] == 5
        assert result.result_data["expired_count"] == 3

    @pytest.mark.asyncio
    async def test_db_connection_error_returns_retry(self) -> None:
        from database.exceptions import DatabaseConnectionError
        ctx, uow = make_exec_ctx()
        uow.upload_sessions.find_expired_sessions = AsyncMock(
            side_effect=DatabaseConnectionError("DB down")
        )
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is False
        assert result.retry is True

    @pytest.mark.asyncio
    async def test_storage_abort_error_recorded_as_failed_count(self) -> None:
        from storage.exceptions import StorageConnectionError
        ctx, uow = make_exec_ctx()
        ctx.storage_service.abort_multipart_upload = AsyncMock(
            side_effect=StorageConnectionError("Storage down")
        )
        mock_session = MagicMock()
        mock_session.id = uuid.uuid4()
        mock_session.user_id = uuid.uuid4()
        mock_session.storage_bucket = "temp"
        mock_session.storage_key = "path/to/upload"
        mock_session.upload_id = "upload-id-123"
        uow.upload_sessions.find_expired_sessions = AsyncMock(return_value=[mock_session])
        uow.upload_sessions.mark_expired = AsyncMock()
        uow.quotas.decrease_active_upload_sessions_used = AsyncMock()
        result = await clean_expired_uploads_handler(ctx)
        # Ошибки хранилища по отдельной сессии не вызывают retry — общий результат успешен
        assert result.success is True
        # Счётчик прерванных загрузок равен 0, так как abort упал
        assert result.result_data["aborted_storage_uploads_count"] == 0

    @pytest.mark.asyncio
    async def test_expired_before_from_payload(self) -> None:
        expired_before = datetime.now(UTC).isoformat()
        ctx, uow = make_exec_ctx(payload={"expired_before": expired_before})
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_limit_from_payload(self) -> None:
        ctx, uow = make_exec_ctx(payload={"limit": 5})
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_sessions_expire_and_quota_decremented(self) -> None:
        ctx, uow = make_exec_ctx()
        mock_session = MagicMock()
        mock_session.id = uuid.uuid4()
        mock_session.user_id = uuid.uuid4()
        mock_session.storage_bucket = "temp"
        mock_session.storage_key = "path/to/upload"
        mock_session.upload_id = "upload-id"
        uow.upload_sessions.find_expired_sessions = AsyncMock(return_value=[mock_session])
        uow.upload_sessions.mark_expired = AsyncMock()
        uow.quotas.decrease_active_upload_sessions_used = AsyncMock()

        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True
        assert result.result_data["scanned_count"] == 1

    @pytest.mark.asyncio
    async def test_limit_explicit_none_uses_batch_size_default(self) -> None:
        # Явный None в limit -> payload_int возвращает размер пакета по умолчанию.
        ctx, uow = make_exec_ctx(payload={"limit": None})
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True
        call_kwargs = uow.upload_sessions.find_expired_sessions.call_args[1]
        assert call_kwargs["limit"] == 10

    @pytest.mark.asyncio
    async def test_service_typeerror_falls_back_to_manual_path(self) -> None:
        ctx, uow = make_exec_ctx()
        ctx.services.uploads = MagicMock()
        # Несовпадение сигнатуры сервиса даёт TypeError -> используется fallback.
        ctx.services.uploads.clean_expired_uploads = MagicMock(
            side_effect=TypeError("unexpected kwargs")
        )
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True
        # Fallback-путь обратился к репозиторию.
        uow.upload_sessions.find_expired_sessions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_service_non_dict_result_falls_back(self) -> None:
        ctx, uow = make_exec_ctx()
        ctx.services.uploads = MagicMock()
        # Результат не-dict игнорируется; обработчик переходит к fallback.
        ctx.services.uploads.clean_expired_uploads = AsyncMock(return_value="nope")
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True
        uow.upload_sessions.find_expired_sessions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_quota_decrease_failure_does_not_fail_session(self) -> None:
        ctx, uow = make_exec_ctx()
        mock_session = MagicMock()
        mock_session.id = uuid.uuid4()
        mock_session.user_id = uuid.uuid4()
        mock_session.storage_bucket = "temp"
        mock_session.storage_key = "k"
        mock_session.upload_id = "u"
        uow.upload_sessions.find_expired_sessions = AsyncMock(
            return_value=[mock_session]
        )
        uow.upload_sessions.mark_expired = AsyncMock()
        # Уменьшение квоты падает, но ошибка поглощается; сессия всё равно истекает.
        uow.quotas.decrease_active_upload_sessions_used = AsyncMock(
            side_effect=RuntimeError("quota glitch")
        )
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True
        assert result.result_data["expired_count"] == 1
        assert result.result_data["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_mark_expired_failure_increments_failed_count(self) -> None:
        ctx, uow = make_exec_ctx()
        mock_session = MagicMock()
        mock_session.id = uuid.uuid4()
        mock_session.user_id = uuid.uuid4()
        mock_session.storage_bucket = "temp"
        mock_session.storage_key = "k"
        mock_session.upload_id = "u"
        uow.upload_sessions.find_expired_sessions = AsyncMock(
            return_value=[mock_session]
        )
        uow.upload_sessions.mark_expired = AsyncMock(
            side_effect=RuntimeError("db write failed")
        )
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True
        assert result.result_data["expired_count"] == 0
        assert result.result_data["failed_count"] == 1

    @pytest.mark.asyncio
    async def test_service_error_returns_failure(self) -> None:
        from services.exceptions import ServiceError

        ctx, uow = make_exec_ctx()
        uow.upload_sessions.find_expired_sessions = AsyncMock(
            side_effect=ServiceError("service broke")
        )
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is False
        assert result.retry is False
        assert result.error_code == "cleanup_uploads_failed"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_failure(self) -> None:
        ctx, uow = make_exec_ctx()
        uow.upload_sessions.find_expired_sessions = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is False
        assert result.error_code == "unexpected_cleanup_uploads_error"

    @pytest.mark.asyncio
    async def test_limit_falls_back_when_batch_size_setting_is_none(self) -> None:
        # Настройка batch-size None => значение по умолчанию payload_int None => limit None,
        # задействуя ветку отката `if limit is None`.
        ctx, uow = make_exec_ctx()
        ctx.worker_settings.worker_cleanup_batch_size = None
        uow.upload_sessions.find_expired_sessions = AsyncMock(return_value=[])
        result = await clean_expired_uploads_handler(ctx)
        assert result.success is True
