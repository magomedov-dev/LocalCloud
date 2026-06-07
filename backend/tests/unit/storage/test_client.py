"""Unit-тесты для StorageClient."""
from __future__ import annotations

import asyncio
import socket
from unittest.mock import MagicMock, patch

import pytest
from minio.error import S3Error

import storage.client as client_module
from storage.client import (
    StorageClient,
    _get_storage_executor,
    shutdown_storage_executor,
)
from storage.exceptions import (
    StorageAuthenticationError,
    StorageConnectionError,
    StorageError,
    StoragePermissionDeniedError,
    StorageTimeoutError,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

class FakeS3Error(S3Error):
    """Лёгкая подмена ``S3Error`` с управляемыми атрибутами."""

    def __init__(
        self,
        *,
        code: str | None = None,
        status_code: int | None = None,
        message: str = "s3 error",
        response: object | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.message = message
        self.request_id = "rid-123"
        self.resource = "/bucket/object"
        self.response = response

    def __str__(self) -> str:  # noqa: D401 - тривиально
        return self.message


def make_settings(
    *,
    endpoint: str = "localhost:9000",
    access_key: str = "minioadmin",
    secret_key: str = "minioadmin",
    secure: bool = False,
    region: str = "us-east-1",
    base_url: str = "http://localhost:9000",
    public_url: str = "http://localhost:9000",
) -> MagicMock:
    settings = MagicMock()
    settings.minio_endpoint = endpoint
    settings.minio_access_key = access_key
    settings.minio_secret_key = secret_key
    settings.minio_secure = secure
    settings.minio_region = region
    settings.minio_base_url = base_url
    settings.minio_public_url = public_url
    return settings


def make_client(**settings_kwargs):
    """Создаёт StorageClient с замоканным конструктором Minio."""
    settings = make_settings(**settings_kwargs)
    with patch.object(client_module, "Minio") as minio_cls:
        minio_instance = MagicMock()
        minio_cls.return_value = minio_instance
        client = StorageClient(settings)
    return client, minio_cls, minio_instance


# ---------------------------------------------------------------------------
# Создание / конфигурация
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_minio_constructed_with_expected_args(self) -> None:
        client, minio_cls, _ = make_client(
            endpoint="minio.example:9000",
            access_key="ak",
            secret_key="sk",
            secure=True,
            region="eu-west-1",
        )
        minio_cls.assert_called_once()
        kwargs = minio_cls.call_args.kwargs
        assert kwargs["endpoint"] == "minio.example:9000"
        assert kwargs["access_key"] == "ak"
        assert kwargs["secret_key"] == "sk"
        assert kwargs["secure"] is True
        assert kwargs["region"] == "eu-west-1"
        assert kwargs["http_client"] is None

    def test_attributes_assigned(self) -> None:
        client, _, minio_instance = make_client()
        assert client.endpoint == "localhost:9000"
        assert client.access_key == "minioadmin"
        assert client.secret_key == "minioadmin"
        assert client.secure is False
        assert client.region == "us-east-1"
        assert client.get_raw_client() is minio_instance

    def test_strips_whitespace_in_required_strings(self) -> None:
        client, _, _ = make_client(endpoint="  localhost:9000  ")
        assert client.endpoint == "localhost:9000"

    def test_empty_region_becomes_none(self) -> None:
        client, minio_cls, _ = make_client(region="")
        assert client.region is None
        assert minio_cls.call_args.kwargs["region"] is None

    def test_http_client_passed_through(self) -> None:
        settings = make_settings()
        http_client = MagicMock()
        with patch.object(client_module, "Minio") as minio_cls:
            minio_cls.return_value = MagicMock()
            client = StorageClient(settings, http_client=http_client)
        assert client.http_client is http_client
        assert minio_cls.call_args.kwargs["http_client"] is http_client

    def test_minio_construction_failure_wrapped(self) -> None:
        settings = make_settings()
        with patch.object(client_module, "Minio", side_effect=ValueError("bad endpoint")):
            with pytest.raises(StorageConnectionError) as exc_info:
                StorageClient(settings)
        assert exc_info.value.details["reason"] == "bad endpoint"
        assert exc_info.value.details["error_type"] == "ValueError"

    def test_non_string_endpoint_raises(self) -> None:
        settings = make_settings()
        settings.minio_endpoint = 12345
        with patch.object(client_module, "Minio"):
            with pytest.raises(StorageConnectionError) as exc_info:
                StorageClient(settings)
        assert exc_info.value.details["field"] == "minio_endpoint"
        assert exc_info.value.details["value_type"] == "int"

    def test_empty_access_key_raises(self) -> None:
        settings = make_settings(access_key="   ")
        with patch.object(client_module, "Minio"):
            with pytest.raises(StorageConnectionError) as exc_info:
                StorageClient(settings)
        assert exc_info.value.details["field"] == "minio_access_key"


# ---------------------------------------------------------------------------
# Свойства
# ---------------------------------------------------------------------------

class TestProperties:
    def test_is_secure_false(self) -> None:
        client, _, _ = make_client(secure=False)
        assert client.is_secure is False

    def test_is_secure_true(self) -> None:
        client, _, _ = make_client(secure=True)
        assert client.is_secure is True

    def test_base_url(self) -> None:
        client, _, _ = make_client(base_url="http://base:9000")
        assert client.base_url == "http://base:9000"

    def test_public_url(self) -> None:
        client, _, _ = make_client(public_url="https://public:9000")
        assert client.public_url == "https://public:9000"


# ---------------------------------------------------------------------------
# Управление executor
# ---------------------------------------------------------------------------

class TestExecutor:
    def test_get_executor_singleton(self) -> None:
        shutdown_storage_executor(wait=True)
        first = _get_storage_executor()
        second = _get_storage_executor()
        assert first is second
        shutdown_storage_executor(wait=True)

    def test_shutdown_resets_executor(self) -> None:
        executor = _get_storage_executor()
        assert client_module._storage_executor is executor
        shutdown_storage_executor(wait=True)
        assert client_module._storage_executor is None

    def test_shutdown_when_already_none_is_safe(self) -> None:
        shutdown_storage_executor(wait=True)
        # Executor отсутствует; повторный вызов не должен падать.
        shutdown_storage_executor(wait=False)
        assert client_module._storage_executor is None


# ---------------------------------------------------------------------------
# execute: успешный путь
# ---------------------------------------------------------------------------

class TestExecuteSuccess:
    @pytest.mark.asyncio
    async def test_runs_operation_in_executor_and_returns_result(self) -> None:
        client, _, _ = make_client()
        calls: list[tuple] = []

        def operation(a, b, *, c):
            calls.append((a, b, c))
            return a + b + c

        result = await client.execute(operation, 1, 2, c=3, operation_name="sum")
        assert result == 6
        assert calls == [(1, 2, 3)]

    @pytest.mark.asyncio
    async def test_success_within_timeout(self) -> None:
        client, _, _ = make_client()

        def operation():
            return "ok"

        result = await client.execute(operation, timeout_seconds=5.0)
        assert result == "ok"


# ---------------------------------------------------------------------------
# execute: оборачивание ошибок
# ---------------------------------------------------------------------------

class TestExecuteErrorWrapping:
    @pytest.mark.asyncio
    async def test_timeout_wrapped(self) -> None:
        client, _, _ = make_client()

        def slow():
            return None

        # Подменяем wait_for, чтобы детерминированно получить TimeoutError.
        async def fake_wait_for(future, timeout):
            future.cancel()
            raise TimeoutError("too slow")

        with patch.object(asyncio, "wait_for", side_effect=fake_wait_for):
            with pytest.raises(StorageTimeoutError) as exc_info:
                await client.execute(slow, operation_name="slow_op", timeout_seconds=0.01)
        assert exc_info.value.details["operation"] == "slow_op"
        assert exc_info.value.details["timeout_seconds"] == 0.01

    @pytest.mark.asyncio
    async def test_s3_permission_denied_mapped(self) -> None:
        client, _, _ = make_client()

        def op():
            raise FakeS3Error(code="AccessDenied")

        with pytest.raises(StoragePermissionDeniedError) as exc_info:
            await client.execute(op, operation_name="op")
        assert exc_info.value.details["operation"] == "op"
        assert exc_info.value.details["code"] == "AccessDenied"

    @pytest.mark.asyncio
    async def test_s3_auth_error_by_code_mapped(self) -> None:
        client, _, _ = make_client()

        def op():
            raise FakeS3Error(code="InvalidAccessKeyId")

        with pytest.raises(StorageAuthenticationError):
            await client.execute(op)

    @pytest.mark.asyncio
    async def test_s3_auth_error_by_status_mapped(self) -> None:
        client, _, _ = make_client()

        def op():
            raise FakeS3Error(code="Whatever", status_code=401)

        with pytest.raises(StorageAuthenticationError):
            await client.execute(op)

    @pytest.mark.asyncio
    async def test_s3_connection_error_by_status_mapped(self) -> None:
        client, _, _ = make_client()

        def op():
            raise FakeS3Error(code="SlowDown", status_code=503, response="<xml/>")

        with pytest.raises(StorageConnectionError) as exc_info:
            await client.execute(op)
        assert exc_info.value.details["status_code"] == 503
        assert exc_info.value.details["response"] == "<xml/>"

    @pytest.mark.asyncio
    async def test_s3_generic_error_mapped_to_storage_error(self) -> None:
        client, _, _ = make_client()

        def op():
            raise FakeS3Error(code="NoSuchKey", status_code=404)

        with pytest.raises(StorageError) as exc_info:
            await client.execute(op)
        # Должен быть базовый StorageError, а не более узкий подтип.
        assert type(exc_info.value) is StorageError
        assert exc_info.value.details["code"] == "NoSuchKey"

    @pytest.mark.asyncio
    async def test_oserror_mapped_to_connection_error(self) -> None:
        client, _, _ = make_client()

        def op():
            raise OSError("connection reset")

        with pytest.raises(StorageConnectionError) as exc_info:
            await client.execute(op, operation_name="net_op")
        assert exc_info.value.details["operation"] == "net_op"
        assert exc_info.value.details["error_type"] == "OSError"

    @pytest.mark.asyncio
    async def test_socket_error_mapped_to_connection_error(self) -> None:
        client, _, _ = make_client()

        def op():
            raise socket.gaierror("name resolution failed")

        with pytest.raises(StorageConnectionError):
            await client.execute(op)

    @pytest.mark.asyncio
    async def test_existing_storage_error_reraised(self) -> None:
        client, _, _ = make_client()
        sentinel = StorageError("already wrapped", details={"x": 1})

        def op():
            raise sentinel

        with pytest.raises(StorageError) as exc_info:
            await client.execute(op)
        assert exc_info.value is sentinel

    @pytest.mark.asyncio
    async def test_generic_exception_wrapped(self) -> None:
        client, _, _ = make_client()

        def op():
            raise ValueError("boom")

        with pytest.raises(StorageError) as exc_info:
            await client.execute(op, operation_name="weird")
        assert type(exc_info.value) is StorageError
        assert exc_info.value.details["operation"] == "weird"
        assert exc_info.value.details["error_type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_operation_name_defaults_to_function_name(self) -> None:
        client, _, _ = make_client()

        def my_named_op():
            raise ValueError("x")

        with pytest.raises(StorageError) as exc_info:
            await client.execute(my_named_op)
        assert exc_info.value.details["operation"] == "my_named_op"


# ---------------------------------------------------------------------------
# Делегирование ping / list_buckets / bucket_exists
# ---------------------------------------------------------------------------

class TestHighLevelOperations:
    @pytest.mark.asyncio
    async def test_ping_calls_list_buckets(self) -> None:
        client, _, minio_instance = make_client()
        minio_instance.list_buckets.return_value = []
        result = await client.ping(timeout_seconds=1.0)
        assert result is True
        minio_instance.list_buckets.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_buckets_delegates(self) -> None:
        client, _, minio_instance = make_client()
        buckets = [MagicMock()]
        minio_instance.list_buckets.return_value = buckets
        result = await client.list_buckets()
        assert result is buckets

    @pytest.mark.asyncio
    async def test_bucket_exists_true(self) -> None:
        client, _, minio_instance = make_client()
        minio_instance.bucket_exists.return_value = True
        result = await client.bucket_exists("my-bucket")
        assert result is True
        minio_instance.bucket_exists.assert_called_once_with("my-bucket")

    @pytest.mark.asyncio
    async def test_bucket_exists_validates_name(self) -> None:
        client, _, _ = make_client()
        with pytest.raises(StorageConnectionError):
            await client.bucket_exists("   ")


# ---------------------------------------------------------------------------
# close / очистка ресурсов
# ---------------------------------------------------------------------------

class TestClose:
    @pytest.mark.asyncio
    async def test_close_noop_when_no_http_client(self) -> None:
        client, _, _ = make_client()
        # http_client равен None -> ранний выход, проверяем лишь отсутствие исключения.
        assert client.http_client is None
        await client.close()

    @pytest.mark.asyncio
    async def test_close_calls_sync_close(self) -> None:
        settings = make_settings()
        http_client = MagicMock()
        http_client.close = MagicMock(return_value=None)
        with patch.object(client_module, "Minio", return_value=MagicMock()):
            client = StorageClient(settings, http_client=http_client)
        await client.close()
        http_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_awaits_async_close(self) -> None:
        settings = make_settings()
        http_client = MagicMock()

        awaited = {"value": False}

        async def async_close():
            awaited["value"] = True

        http_client.close = MagicMock(side_effect=async_close)
        with patch.object(client_module, "Minio", return_value=MagicMock()):
            client = StorageClient(settings, http_client=http_client)
        await client.close()
        assert awaited["value"] is True

    @pytest.mark.asyncio
    async def test_close_falls_back_to_clear(self) -> None:
        settings = make_settings()
        # http_client без close, но с clear.
        http_client = MagicMock(spec=["clear"])
        http_client.clear = MagicMock(return_value=None)
        with patch.object(client_module, "Minio", return_value=MagicMock()):
            client = StorageClient(settings, http_client=http_client)
        await client.close()
        http_client.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_awaits_async_clear(self) -> None:
        settings = make_settings()
        http_client = MagicMock(spec=["clear"])

        awaited = {"value": False}

        async def async_clear():
            awaited["value"] = True

        http_client.clear = MagicMock(side_effect=async_clear)
        with patch.object(client_module, "Minio", return_value=MagicMock()):
            client = StorageClient(settings, http_client=http_client)
        await client.close()
        assert awaited["value"] is True

    @pytest.mark.asyncio
    async def test_close_error_wrapped(self) -> None:
        settings = make_settings()
        http_client = MagicMock()
        http_client.close = MagicMock(side_effect=RuntimeError("cannot close"))
        with patch.object(client_module, "Minio", return_value=MagicMock()):
            client = StorageClient(settings, http_client=http_client)
        with pytest.raises(StorageError) as exc_info:
            await client.close()
        assert exc_info.value.details["reason"] == "cannot close"
        assert exc_info.value.details["error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_close_noop_when_no_close_or_clear(self) -> None:
        settings = make_settings()
        # http_client без вызываемых close и clear.
        http_client = MagicMock(spec=[])
        with patch.object(client_module, "Minio", return_value=MagicMock()):
            client = StorageClient(settings, http_client=http_client)
        await client.close()
