"""Unit-тесты для StorageHealthChecker."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from storage.exceptions import StorageError, StorageHealthCheckError
from storage.health import StorageHealthChecker
from storage.types import StorageHealthState, StorageHealthStatus


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_checker():
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)

    bucket_manager = MagicMock()
    bucket_manager.check_bucket_access = AsyncMock(return_value=True)

    object_manager = MagicMock()
    # put_object, stat_object, get_object_bytes, delete_object
    object_manager.put_object = AsyncMock(return_value=MagicMock(size_bytes=13))
    object_manager.stat_object = AsyncMock(return_value=MagicMock(size_bytes=13))
    object_manager.get_object_bytes = AsyncMock(
        return_value=MagicMock(data=b"LocalCloud OK")
    )
    object_manager.delete_object = AsyncMock(return_value=True)
    object_manager.object_exists = AsyncMock(return_value=True)

    checker = StorageHealthChecker(
        client=client,
        bucket_manager=bucket_manager,
        object_manager=object_manager,
    )
    return checker, client, bucket_manager, object_manager


# ---------------------------------------------------------------------------
# check_storage_connection
# ---------------------------------------------------------------------------

class TestCheckStorageConnection:
    @pytest.mark.asyncio
    async def test_ping_success_returns_true(self) -> None:
        checker, client, *_ = make_checker()
        result = await checker.check_storage_connection()
        assert result is True
        client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_ping_raises_storage_error_raises_health_check_error(self) -> None:
        checker, client, *_ = make_checker()
        client.ping = AsyncMock(side_effect=StorageError("connection refused"))

        with pytest.raises(StorageHealthCheckError):
            await checker.check_storage_connection()

    @pytest.mark.asyncio
    async def test_ping_raises_generic_exception_raises_health_check_error(self) -> None:
        checker, client, *_ = make_checker()
        client.ping = AsyncMock(side_effect=RuntimeError("socket error"))

        with pytest.raises(StorageHealthCheckError):
            await checker.check_storage_connection()


# ---------------------------------------------------------------------------
# check_bucket_access
# ---------------------------------------------------------------------------

class TestCheckBucketAccess:
    @pytest.mark.asyncio
    async def test_bucket_access_success_returns_true(self) -> None:
        checker, client, bucket_manager, *_ = make_checker()
        result = await checker.check_bucket_access(bucket="test-bucket")
        assert result is True
        bucket_manager.check_bucket_access.assert_called_once_with("test-bucket")

    @pytest.mark.asyncio
    async def test_bucket_access_storage_error_raises_health_check_error(self) -> None:
        checker, client, bucket_manager, *_ = make_checker()
        bucket_manager.check_bucket_access = AsyncMock(
            side_effect=StorageError("bucket not found")
        )

        with pytest.raises(StorageHealthCheckError):
            await checker.check_bucket_access(bucket="missing-bucket")

    @pytest.mark.asyncio
    async def test_bucket_access_generic_error_raises_health_check_error(self) -> None:
        checker, client, bucket_manager, *_ = make_checker()
        bucket_manager.check_bucket_access = AsyncMock(
            side_effect=RuntimeError("unexpected error")
        )

        with pytest.raises(StorageHealthCheckError):
            await checker.check_bucket_access(bucket="test-bucket")


# ---------------------------------------------------------------------------
# check_storage_latency
# ---------------------------------------------------------------------------

class TestCheckStorageLatency:
    @pytest.mark.asyncio
    async def test_returns_float_ms(self) -> None:
        checker, client, *_ = make_checker()
        latency = await checker.check_storage_latency()
        assert isinstance(latency, float)
        assert latency >= 0.0

    @pytest.mark.asyncio
    async def test_ping_error_raises_health_check_error(self) -> None:
        checker, client, *_ = make_checker()
        client.ping = AsyncMock(side_effect=StorageError("timeout"))

        with pytest.raises(StorageHealthCheckError):
            await checker.check_storage_latency()

    @pytest.mark.asyncio
    async def test_generic_error_raises_health_check_error(self) -> None:
        checker, client, *_ = make_checker()
        client.ping = AsyncMock(side_effect=ConnectionResetError("reset"))

        with pytest.raises(StorageHealthCheckError):
            await checker.check_storage_latency()


# ---------------------------------------------------------------------------
# check_storage_read_write
# ---------------------------------------------------------------------------

class TestCheckStorageReadWrite:
    @pytest.mark.asyncio
    async def test_success_returns_true(self) -> None:
        from core.constants import StorageConstants
        checker, client, bucket_manager, object_manager = make_checker()
        payload = StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
        object_manager.stat_object = AsyncMock(
            return_value=MagicMock(size_bytes=len(payload))
        )
        object_manager.get_object_bytes = AsyncMock(
            return_value=MagicMock(data=payload)
        )
        result = await checker.check_storage_read_write(bucket="test-bucket")
        assert result is True

    @pytest.mark.asyncio
    async def test_size_mismatch_raises_health_check_error(self) -> None:
        checker, client, bucket_manager, object_manager = make_checker()
        object_manager.stat_object = AsyncMock(
            return_value=MagicMock(size_bytes=999)  # неверный размер
        )

        with pytest.raises(StorageHealthCheckError):
            await checker.check_storage_read_write(bucket="test-bucket")

    @pytest.mark.asyncio
    async def test_content_mismatch_raises_health_check_error(self) -> None:
        from core.constants import StorageConstants
        checker, client, bucket_manager, object_manager = make_checker()
        payload = StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
        object_manager.stat_object = AsyncMock(
            return_value=MagicMock(size_bytes=len(payload))
        )
        object_manager.get_object_bytes = AsyncMock(
            return_value=MagicMock(data=b"wrong content")  # несовпадение содержимого
        )

        with pytest.raises(StorageHealthCheckError):
            await checker.check_storage_read_write(bucket="test-bucket")


# ---------------------------------------------------------------------------
# check_storage_health
# ---------------------------------------------------------------------------

class TestCheckStorageHealth:
    @pytest.mark.asyncio
    async def test_all_ok_returns_healthy_status(self) -> None:
        from core.constants import StorageConstants
        checker, client, bucket_manager, object_manager = make_checker()
        payload = StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
        object_manager.stat_object = AsyncMock(
            return_value=MagicMock(size_bytes=len(payload))
        )
        object_manager.get_object_bytes = AsyncMock(
            return_value=MagicMock(data=payload)
        )
        status = await checker.check_storage_health(bucket="test-bucket")
        assert isinstance(status, StorageHealthStatus)
        assert status.state == StorageHealthState.HEALTHY
        assert status.connection_ok is True
        assert status.bucket_access_ok is True

    @pytest.mark.asyncio
    async def test_connection_failure_returns_unhealthy(self) -> None:
        checker, client, bucket_manager, object_manager = make_checker()
        client.ping = AsyncMock(side_effect=StorageError("no connection"))

        status = await checker.check_storage_health(bucket="test-bucket")
        assert status.state == StorageHealthState.UNHEALTHY
        assert status.connection_ok is False

    @pytest.mark.asyncio
    async def test_bucket_access_failure_returns_unhealthy(self) -> None:
        checker, client, bucket_manager, object_manager = make_checker()
        bucket_manager.check_bucket_access = AsyncMock(
            side_effect=StorageError("bucket not found")
        )

        status = await checker.check_storage_health(bucket="test-bucket")
        assert status.state == StorageHealthState.UNHEALTHY
        assert status.bucket_access_ok is False

    @pytest.mark.asyncio
    async def test_skipped_read_write_check_returns_degraded(self) -> None:
        checker, client, bucket_manager, object_manager = make_checker()
        status = await checker.check_storage_health(
            bucket="test-bucket",
            check_read_write=False,
        )
        assert status.state in {StorageHealthState.DEGRADED, StorageHealthState.HEALTHY}

    @pytest.mark.asyncio
    async def test_read_write_failure_returns_unhealthy(self) -> None:
        checker, client, bucket_manager, object_manager = make_checker()
        object_manager.put_object = AsyncMock(
            side_effect=StorageError("upload failed")
        )

        status = await checker.check_storage_health(bucket="test-bucket")
        assert status.state == StorageHealthState.UNHEALTHY
        assert status.read_write_ok is False


# ---------------------------------------------------------------------------
# validate_latency_threshold
# ---------------------------------------------------------------------------

class TestValidateLatencyThreshold:
    def test_valid_threshold(self) -> None:
        result = StorageHealthChecker.validate_latency_threshold(100.0)
        assert result == 100.0

    def test_int_threshold_accepted(self) -> None:
        result = StorageHealthChecker.validate_latency_threshold(200)
        assert result == 200.0

    def test_zero_raises(self) -> None:
        with pytest.raises(StorageHealthCheckError):
            StorageHealthChecker.validate_latency_threshold(0)

    def test_negative_raises(self) -> None:
        with pytest.raises(StorageHealthCheckError):
            StorageHealthChecker.validate_latency_threshold(-50.0)

    def test_bool_raises(self) -> None:
        with pytest.raises(StorageHealthCheckError):
            StorageHealthChecker.validate_latency_threshold(True)  # type: ignore[arg-type]

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(StorageHealthCheckError):
            StorageHealthChecker.validate_latency_threshold("100ms")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# resolve_health_state
# ---------------------------------------------------------------------------

class TestResolveHealthState:
    def test_all_ok_returns_healthy(self) -> None:
        state = StorageHealthChecker.resolve_health_state(
            connection_ok=True,
            bucket_access_ok=True,
            read_write_ok=True,
            latency_ms=10.0,
            latency_threshold_ms=500.0,
            read_write_check_enabled=True,
        )
        assert state == StorageHealthState.HEALTHY

    def test_connection_failed_returns_unhealthy(self) -> None:
        state = StorageHealthChecker.resolve_health_state(
            connection_ok=False,
            bucket_access_ok=True,
            read_write_ok=True,
            latency_ms=10.0,
            latency_threshold_ms=500.0,
            read_write_check_enabled=True,
        )
        assert state == StorageHealthState.UNHEALTHY

    def test_bucket_access_failed_returns_unhealthy(self) -> None:
        state = StorageHealthChecker.resolve_health_state(
            connection_ok=True,
            bucket_access_ok=False,
            read_write_ok=True,
            latency_ms=10.0,
            latency_threshold_ms=500.0,
            read_write_check_enabled=True,
        )
        assert state == StorageHealthState.UNHEALTHY

    def test_high_latency_returns_degraded(self) -> None:
        state = StorageHealthChecker.resolve_health_state(
            connection_ok=True,
            bucket_access_ok=True,
            read_write_ok=True,
            latency_ms=1000.0,
            latency_threshold_ms=500.0,  # задержка превышает порог
            read_write_check_enabled=True,
        )
        assert state == StorageHealthState.DEGRADED

    def test_no_latency_info_returns_degraded(self) -> None:
        state = StorageHealthChecker.resolve_health_state(
            connection_ok=True,
            bucket_access_ok=True,
            read_write_ok=True,
            latency_ms=None,  # задержка не измерялась
            latency_threshold_ms=500.0,
            read_write_check_enabled=True,
        )
        assert state == StorageHealthState.DEGRADED

    def test_read_write_check_disabled_returns_degraded(self) -> None:
        state = StorageHealthChecker.resolve_health_state(
            connection_ok=True,
            bucket_access_ok=True,
            read_write_ok=None,
            latency_ms=10.0,
            latency_threshold_ms=500.0,
            read_write_check_enabled=False,
        )
        assert state == StorageHealthState.DEGRADED

    def test_read_write_failed_returns_unhealthy(self) -> None:
        state = StorageHealthChecker.resolve_health_state(
            connection_ok=True,
            bucket_access_ok=True,
            read_write_ok=False,
            latency_ms=10.0,
            latency_threshold_ms=500.0,
            read_write_check_enabled=True,
        )
        assert state == StorageHealthState.UNHEALTHY


# ---------------------------------------------------------------------------
# check_storage_read_write — общее исключение + ветки очистки
# ---------------------------------------------------------------------------

class TestCheckStorageReadWriteExtra:
    @pytest.mark.asyncio
    async def test_generic_exception_raises_health_check_error(self) -> None:
        checker, client, bucket_manager, object_manager = make_checker()
        # Не-StorageError возникает до создания объекта -> общая ветка (275-276).
        object_manager.put_object = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(StorageHealthCheckError) as exc_info:
            await checker.check_storage_read_write(bucket="test-bucket")
        assert exc_info.value.details["error_type"] == "RuntimeError"
        # Объект не создавался -> попытки очистки быть не должно.
        object_manager.delete_object.assert_not_called()

    @pytest.mark.asyncio
    async def test_storage_error_after_create_triggers_cleanup(self) -> None:
        checker, client, bucket_manager, object_manager = make_checker()
        # put_object успешен (объект создан), stat_object падает со StorageError.
        object_manager.stat_object = AsyncMock(
            side_effect=StorageError("stat failed")
        )

        with pytest.raises(StorageHealthCheckError):
            await checker.check_storage_read_write(bucket="test-bucket")
        # object_created равен True -> очистка удаляет тестовый объект.
        object_manager.delete_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_object_key_is_used(self) -> None:
        from core.constants import StorageConstants
        checker, client, bucket_manager, object_manager = make_checker()
        payload = StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
        object_manager.stat_object = AsyncMock(
            return_value=MagicMock(size_bytes=len(payload))
        )
        object_manager.get_object_bytes = AsyncMock(
            return_value=MagicMock(data=payload)
        )
        result = await checker.check_storage_read_write(
            bucket="test-bucket",
            object_key="custom/healthcheck.txt",
        )
        assert result is True


# ---------------------------------------------------------------------------
# check_storage_health — ошибка задержки + детали превышения порога задержки
# ---------------------------------------------------------------------------

class TestCheckStorageHealthDetails:
    @pytest.mark.asyncio
    async def test_latency_check_failure_recorded_in_details(self) -> None:
        from core.constants import StorageConstants
        checker, client, bucket_manager, object_manager = make_checker()
        payload = StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
        object_manager.stat_object = AsyncMock(
            return_value=MagicMock(size_bytes=len(payload))
        )
        object_manager.get_object_bytes = AsyncMock(
            return_value=MagicMock(data=payload)
        )

        # Первый ping (соединение) успешен, второй (задержка) падает.
        calls = {"n": 0}

        async def ping_side_effect() -> bool:
            calls["n"] += 1
            if calls["n"] == 1:
                return True
            raise StorageError("latency ping failed")

        client.ping = AsyncMock(side_effect=ping_side_effect)

        status = await checker.check_storage_health(bucket="test-bucket")
        # Соединение ок, задержка не измерена -> degraded с деталью latency_error (350-351).
        assert status.connection_ok is True
        assert "latency_error" in status.details
        assert status.state == StorageHealthState.DEGRADED

    @pytest.mark.asyncio
    async def test_latency_threshold_exceeded_detail_set(self, monkeypatch) -> None:
        from core.constants import StorageConstants
        checker, client, bucket_manager, object_manager = make_checker()
        payload = StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
        object_manager.stat_object = AsyncMock(
            return_value=MagicMock(size_bytes=len(payload))
        )
        object_manager.get_object_bytes = AsyncMock(
            return_value=MagicMock(data=payload)
        )

        # Принудительно задаём задержку, превышающую крошечный порог.
        monkeypatch.setattr(
            StorageHealthChecker,
            "check_storage_latency",
            AsyncMock(return_value=10_000.0),
        )

        status = await checker.check_storage_health(
            bucket="test-bucket",
            latency_threshold_ms=1.0,
        )
        assert status.details.get("latency_threshold_exceeded") is True
        assert status.state == StorageHealthState.DEGRADED


# ---------------------------------------------------------------------------
# get_storage_health_report
# ---------------------------------------------------------------------------

class TestGetStorageHealthReport:
    @pytest.mark.asyncio
    async def test_returns_status_on_success(self) -> None:
        from core.constants import StorageConstants
        checker, client, bucket_manager, object_manager = make_checker()
        payload = StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
        object_manager.stat_object = AsyncMock(
            return_value=MagicMock(size_bytes=len(payload))
        )
        object_manager.get_object_bytes = AsyncMock(
            return_value=MagicMock(data=payload)
        )
        status = await checker.get_storage_health_report(bucket="test-bucket")
        assert isinstance(status, StorageHealthStatus)
        assert status.state == StorageHealthState.HEALTHY

    @pytest.mark.asyncio
    async def test_health_check_error_swallowed_returns_unhealthy(
        self, monkeypatch
    ) -> None:
        checker, *_ = make_checker()
        monkeypatch.setattr(
            StorageHealthChecker,
            "check_storage_health",
            AsyncMock(side_effect=StorageHealthCheckError("hc boom")),
        )
        status = await checker.get_storage_health_report(bucket="b")
        assert status.state == StorageHealthState.UNHEALTHY
        assert status.details["error"] == "StorageHealthCheckError"
        assert status.details["message"] == "hc boom"

    @pytest.mark.asyncio
    async def test_health_check_error_reraised_when_raise_on_error(
        self, monkeypatch
    ) -> None:
        checker, *_ = make_checker()
        monkeypatch.setattr(
            StorageHealthChecker,
            "check_storage_health",
            AsyncMock(side_effect=StorageHealthCheckError("hc boom")),
        )
        with pytest.raises(StorageHealthCheckError):
            await checker.get_storage_health_report(
                bucket="b", raise_on_error=True
            )

    @pytest.mark.asyncio
    async def test_storage_error_swallowed_returns_unhealthy(
        self, monkeypatch
    ) -> None:
        checker, *_ = make_checker()
        monkeypatch.setattr(
            StorageHealthChecker,
            "check_storage_health",
            AsyncMock(side_effect=StorageError("storage boom")),
        )
        status = await checker.get_storage_health_report(bucket="b")
        assert status.state == StorageHealthState.UNHEALTHY
        assert status.details["error"] == "StorageError"

    @pytest.mark.asyncio
    async def test_storage_error_reraised_when_raise_on_error(
        self, monkeypatch
    ) -> None:
        checker, *_ = make_checker()
        monkeypatch.setattr(
            StorageHealthChecker,
            "check_storage_health",
            AsyncMock(side_effect=StorageError("storage boom")),
        )
        with pytest.raises(StorageError):
            await checker.get_storage_health_report(
                bucket="b", raise_on_error=True
            )

    @pytest.mark.asyncio
    async def test_generic_error_swallowed_returns_unhealthy(
        self, monkeypatch
    ) -> None:
        checker, *_ = make_checker()
        monkeypatch.setattr(
            StorageHealthChecker,
            "check_storage_health",
            AsyncMock(side_effect=RuntimeError("generic boom")),
        )
        status = await checker.get_storage_health_report(bucket="b")
        assert status.state == StorageHealthState.UNHEALTHY
        assert status.details["error"] == "RuntimeError"
        assert status.details["operation"] == "get_storage_health_report"

    @pytest.mark.asyncio
    async def test_generic_error_reraised_when_raise_on_error(
        self, monkeypatch
    ) -> None:
        checker, *_ = make_checker()
        monkeypatch.setattr(
            StorageHealthChecker,
            "check_storage_health",
            AsyncMock(side_effect=RuntimeError("generic boom")),
        )
        with pytest.raises(RuntimeError):
            await checker.get_storage_health_report(
                bucket="b", raise_on_error=True
            )

    @pytest.mark.asyncio
    async def test_custom_latency_threshold_validated(self, monkeypatch) -> None:
        from core.constants import StorageConstants
        checker, client, bucket_manager, object_manager = make_checker()
        payload = StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PAYLOAD
        object_manager.stat_object = AsyncMock(
            return_value=MagicMock(size_bytes=len(payload))
        )
        object_manager.get_object_bytes = AsyncMock(
            return_value=MagicMock(data=payload)
        )
        status = await checker.get_storage_health_report(
            bucket="test-bucket",
            latency_threshold_ms=250.0,
        )
        assert status.latency_threshold_ms == 250.0


# ---------------------------------------------------------------------------
# build_healthcheck_object_key + safe_delete_healthcheck_object
# ---------------------------------------------------------------------------

class TestBuildHealthcheckObjectKey:
    def test_returns_prefixed_key(self) -> None:
        from core.constants import StorageConstants
        checker, *_ = make_checker()
        key = checker.build_healthcheck_object_key()
        assert StorageConstants.STORAGE_HEALTHCHECK_OBJECT_PREFIX in key
        assert key.endswith(".txt")


class TestSafeDeleteHealthcheckObject:
    @pytest.mark.asyncio
    async def test_delete_called(self) -> None:
        checker, client, bucket_manager, object_manager = make_checker()
        await checker.safe_delete_healthcheck_object(
            bucket="b", object_key="k"
        )
        object_manager.delete_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_storage_error_suppressed(self) -> None:
        checker, client, bucket_manager, object_manager = make_checker()
        object_manager.delete_object = AsyncMock(
            side_effect=StorageError("delete failed")
        )
        # Не должно выбрасывать исключение (558-559).
        result = await checker.safe_delete_healthcheck_object(
            bucket="b", object_key="k"
        )
        assert result is None


# ---------------------------------------------------------------------------
# _validate_payload / _validate_content_type
# ---------------------------------------------------------------------------

class TestValidatePayload:
    def test_valid_payload_returned(self) -> None:
        result = StorageHealthChecker._validate_payload(b"data")
        assert result == b"data"

    def test_non_bytes_raises(self) -> None:
        with pytest.raises(StorageHealthCheckError):
            StorageHealthChecker._validate_payload("not bytes")  # type: ignore[arg-type]

    def test_empty_payload_raises(self) -> None:
        with pytest.raises(StorageHealthCheckError):
            StorageHealthChecker._validate_payload(b"")


class TestValidateContentType:
    def test_valid_content_type_returned(self) -> None:
        result = StorageHealthChecker._validate_content_type("text/plain")
        assert result == "text/plain"

    def test_content_type_stripped(self) -> None:
        result = StorageHealthChecker._validate_content_type("  text/plain  ")
        assert result == "text/plain"

    def test_non_string_raises(self) -> None:
        with pytest.raises(StorageHealthCheckError):
            StorageHealthChecker._validate_content_type(123)  # type: ignore[arg-type]

    def test_empty_content_type_raises(self) -> None:
        with pytest.raises(StorageHealthCheckError):
            StorageHealthChecker._validate_content_type("   ")
