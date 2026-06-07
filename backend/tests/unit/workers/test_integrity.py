"""Unit-тесты для воркера проверки целостности (workers/integrity.py)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.exceptions import DatabaseConnectionError
from database.models.enums import StorageObjectStatus as DbStorageObjectStatus
from storage.exceptions import StorageConnectionError, StorageError
from storage.types import StorageIntegrityProblemType
from workers.integrity import (
    _expected_checksum,
    _expected_checksum_algorithm,
    _first_corruption_type,
    _has_corruption_problem,
    _optional_payload_uuid,
    _problem_payload,
    check_storage_integrity_handler,
)
from workers.types import WorkerTaskExecutionResult


# ---------------------------------------------------------------------------
# Вспомогательные функции / фикстуры
# ---------------------------------------------------------------------------


def make_file_row(
    *,
    file_id=None,
    bucket="files",
    key="objects/key",
    size_bytes=100,
    checksum="abc123",
    checksum_algorithm="sha256",
):
    row = MagicMock()
    row.id = file_id or uuid.uuid4()
    row.storage_bucket = bucket
    row.storage_key = key
    row.size_bytes = size_bytes
    row.checksum = checksum
    row.checksum_algorithm = checksum_algorithm
    return row


def make_problem(problem_type):
    status = MagicMock()
    status.problem_type = problem_type
    return status


def make_report(*, object_exists=True, problems=None):
    report = MagicMock()
    report.object_exists = object_exists
    report.problems = problems or []
    return report


def make_uow():
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()

    uow.files = AsyncMock()
    uow.files.get_by_id = AsyncMock(return_value=None)
    uow.files.search_user_files = AsyncMock(return_value=[])
    uow.files.list_by_storage_status = AsyncMock(return_value=[])
    uow.files.mark_storage_missing = AsyncMock(return_value=None)
    uow.files.mark_storage_corrupted = AsyncMock(return_value=None)
    return uow


def make_ctx(payload=None, *, uow=None, batch_size=100):
    ctx = MagicMock()
    ctx.task_id = uuid.uuid4()
    ctx.payload = payload if payload is not None else {}
    ctx.worker_id = "w-001"
    ctx.settings = MagicMock()
    ctx.worker_settings = MagicMock()
    ctx.worker_settings.worker_integrity_batch_size = batch_size

    uow = uow or make_uow()
    ctx.uow_factory = MagicMock(return_value=uow)

    storage = MagicMock()
    storage.verify_file_object = AsyncMock(return_value=make_report())
    ctx.storage_service = storage

    ctx.services = MagicMock()

    return ctx, uow


# ---------------------------------------------------------------------------
# Чистые вспомогательные функции
# ---------------------------------------------------------------------------


class TestExpectedChecksum:
    def test_returns_normalized_checksum(self) -> None:
        row = make_file_row(checksum="  abc  ")
        assert _expected_checksum(row) == "abc"

    def test_non_string_returns_none(self) -> None:
        row = make_file_row(checksum=12345)
        assert _expected_checksum(row) is None

    def test_blank_returns_none(self) -> None:
        row = make_file_row(checksum="   ")
        assert _expected_checksum(row) is None


class TestExpectedChecksumAlgorithm:
    def test_none_returns_none(self) -> None:
        row = make_file_row(checksum_algorithm=None)
        assert _expected_checksum_algorithm(row) is None

    def test_enum_value_returned(self) -> None:
        algo = MagicMock()
        algo.value = "SHA256"
        row = make_file_row(checksum_algorithm=algo)
        assert _expected_checksum_algorithm(row) == "SHA256"

    def test_string_normalized_lower(self) -> None:
        row = make_file_row(checksum_algorithm="  SHA256 ")
        assert _expected_checksum_algorithm(row) == "sha256"

    def test_blank_string_returns_none(self) -> None:
        row = make_file_row(checksum_algorithm="   ")
        assert _expected_checksum_algorithm(row) is None

    def test_other_type_returns_none(self) -> None:
        row = make_file_row(checksum_algorithm=123)
        assert _expected_checksum_algorithm(row) is None


class TestHasCorruptionProblem:
    def test_size_mismatch_true(self) -> None:
        report = make_report(
            problems=[make_problem(StorageIntegrityProblemType.SIZE_MISMATCH)]
        )
        assert _has_corruption_problem(report) is True

    def test_checksum_mismatch_true(self) -> None:
        report = make_report(
            problems=[make_problem(StorageIntegrityProblemType.CHECKSUM_MISMATCH)]
        )
        assert _has_corruption_problem(report) is True

    def test_other_problem_false(self) -> None:
        report = make_report(
            problems=[make_problem(StorageIntegrityProblemType.METADATA_MISMATCH)]
        )
        assert _has_corruption_problem(report) is False

    def test_no_problems_false(self) -> None:
        assert _has_corruption_problem(make_report(problems=[])) is False

    def test_report_without_problems_attr(self) -> None:
        assert _has_corruption_problem(object()) is False


class TestFirstCorruptionType:
    def test_returns_first_matching(self) -> None:
        report = make_report(
            problems=[
                make_problem(StorageIntegrityProblemType.METADATA_MISMATCH),
                make_problem(StorageIntegrityProblemType.SIZE_MISMATCH),
            ]
        )
        assert (
            _first_corruption_type(report)
            == StorageIntegrityProblemType.SIZE_MISMATCH
        )

    def test_defaults_to_checksum_mismatch(self) -> None:
        report = make_report(problems=[])
        assert (
            _first_corruption_type(report)
            == StorageIntegrityProblemType.CHECKSUM_MISMATCH
        )

    def test_non_enum_problem_type_ignored(self) -> None:
        report = make_report(problems=[make_problem("size_mismatch")])
        assert (
            _first_corruption_type(report)
            == StorageIntegrityProblemType.CHECKSUM_MISMATCH
        )


class TestProblemPayload:
    def test_with_problem_type_and_details(self) -> None:
        fid = uuid.uuid4()
        payload = _problem_payload(
            file_id=fid,
            bucket="b",
            object_key="k",
            problem_type=StorageIntegrityProblemType.SIZE_MISMATCH,
            message="msg",
            details={"reason": "x"},
        )
        assert payload["file_id"] == str(fid)
        assert payload["bucket"] == "b"
        assert payload["object_key"] == "k"
        assert payload["problem_type"] == "size_mismatch"
        assert payload["message"] == "msg"
        assert payload["details"] == {"reason": "x"}

    def test_none_problem_type_no_details(self) -> None:
        payload = _problem_payload(
            file_id=uuid.uuid4(),
            bucket="b",
            object_key="k",
            problem_type=None,
            message="msg",
        )
        assert payload["problem_type"] is None
        assert "details" not in payload


class TestOptionalPayloadUuid:
    def test_none_when_missing(self) -> None:
        assert _optional_payload_uuid({}, "user_id") is None

    def test_uuid_instance(self) -> None:
        uid = uuid.uuid4()
        assert _optional_payload_uuid({"user_id": uid}, "user_id") == uid

    def test_uuid_from_string(self) -> None:
        uid = uuid.uuid4()
        assert _optional_payload_uuid({"user_id": str(uid)}, "user_id") == uid

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError):
            _optional_payload_uuid({"user_id": 12345}, "user_id")

    def test_invalid_uuid_string_raises(self) -> None:
        with pytest.raises(ValueError):
            _optional_payload_uuid({"user_id": "not-a-uuid"}, "user_id")


# ---------------------------------------------------------------------------
# Обработчик: загрузка файлов для проверки
# ---------------------------------------------------------------------------


class TestLoadFilesBranches:
    @pytest.mark.asyncio
    async def test_single_file_id_found(self) -> None:
        fid = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(fid)})
        uow.files.get_by_id = AsyncMock(return_value=make_file_row(file_id=fid))

        result = await check_storage_integrity_handler(ctx)

        assert result.success is True
        uow.files.get_by_id.assert_awaited_once_with(fid)
        assert result.result_data["checked_count"] == 1

    @pytest.mark.asyncio
    async def test_single_file_id_missing_node(self) -> None:
        fid = uuid.uuid4()
        ctx, uow = make_ctx(payload={"file_id": str(fid)})
        uow.files.get_by_id = AsyncMock(return_value=None)

        result = await check_storage_integrity_handler(ctx)

        assert result.success is True
        assert result.result_data["checked_count"] == 0
        assert result.result_data["problems_count"] == 0
        ctx.storage_service.verify_file_object.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_id_branch(self) -> None:
        uid = uuid.uuid4()
        ctx, uow = make_ctx(payload={"user_id": str(uid)})
        uow.files.search_user_files = AsyncMock(return_value=[make_file_row()])

        result = await check_storage_integrity_handler(ctx)

        assert result.success is True
        uow.files.search_user_files.assert_awaited_once_with(
            owner_id=uid,
            include_deleted_nodes=False,
            storage_status=DbStorageObjectStatus.AVAILABLE,
            offset=0,
            limit=100,
        )
        assert result.result_data["checked_count"] == 1

    @pytest.mark.asyncio
    async def test_batch_branch_no_filters(self) -> None:
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(
            return_value=[make_file_row(), make_file_row()]
        )

        result = await check_storage_integrity_handler(ctx)

        assert result.success is True
        uow.files.list_by_storage_status.assert_awaited_once_with(
            storage_status=DbStorageObjectStatus.AVAILABLE,
            owner_id=None,
            include_deleted_nodes=False,
            offset=0,
            limit=100,
        )
        assert result.result_data["checked_count"] == 2

    @pytest.mark.asyncio
    async def test_custom_limit_used(self) -> None:
        ctx, uow = make_ctx(payload={"limit": 7})
        await check_storage_integrity_handler(ctx)
        _, kwargs = uow.files.list_by_storage_status.call_args
        assert kwargs["limit"] == 7

    @pytest.mark.asyncio
    async def test_none_limit_falls_back_to_batch_size(self) -> None:
        # payload_int возвращает None, когда и значение в payload, и значение
        # по умолчанию равны None — проверяем ветку отката `if limit is None`.
        ctx, uow = make_ctx(payload={}, batch_size=None)
        ctx.worker_settings.worker_integrity_batch_size = None

        result = await check_storage_integrity_handler(ctx)

        assert result.success is True
        _, kwargs = uow.files.list_by_storage_status.call_args
        assert kwargs["limit"] is None


# ---------------------------------------------------------------------------
# Обработчик: результаты проверки
# ---------------------------------------------------------------------------


class TestVerificationOutcomes:
    @pytest.mark.asyncio
    async def test_all_ok_success_no_problems(self) -> None:
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(
            return_value=[make_file_row(), make_file_row()]
        )
        ctx.storage_service.verify_file_object = AsyncMock(
            return_value=make_report(object_exists=True, problems=[])
        )

        result = await check_storage_integrity_handler(ctx)

        assert isinstance(result, WorkerTaskExecutionResult)
        assert result.success is True
        assert result.progress_percent == 100
        assert result.result_data["checked_count"] == 2
        assert result.result_data["problems_count"] == 0
        assert result.result_data["missing_count"] == 0
        assert result.result_data["corrupted_count"] == 0
        assert result.result_data["problems"] == []
        uow.files.mark_storage_missing.assert_not_awaited()
        uow.files.mark_storage_corrupted.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_expected_values_to_checker(self) -> None:
        row = make_file_row(
            bucket="b1",
            key="k1",
            size_bytes=512,
            checksum="deadbeef",
            checksum_algorithm="sha256",
        )
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(return_value=[row])

        await check_storage_integrity_handler(ctx)

        ctx.storage_service.verify_file_object.assert_awaited_once_with(
            bucket="b1",
            object_key="k1",
            expected_size_bytes=512,
            expected_checksum="deadbeef",
            expected_checksum_algorithm="sha256",
        )

    @pytest.mark.asyncio
    async def test_missing_object_marked_and_counted(self) -> None:
        fid = uuid.uuid4()
        row = make_file_row(file_id=fid)
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(return_value=[row])
        ctx.storage_service.verify_file_object = AsyncMock(
            return_value=make_report(object_exists=False)
        )

        result = await check_storage_integrity_handler(ctx)

        assert result.success is True
        assert result.result_data["missing_count"] == 1
        assert result.result_data["problems_count"] == 1
        uow.files.mark_storage_missing.assert_awaited_once_with(
            file_id=fid, flush=True, refresh=False
        )
        uow.commit.assert_awaited()
        problem = result.result_data["problems"][0]
        assert problem["problem_type"] == "object_not_found"

    @pytest.mark.asyncio
    async def test_corrupted_object_marked_and_counted(self) -> None:
        fid = uuid.uuid4()
        row = make_file_row(file_id=fid)
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(return_value=[row])
        ctx.storage_service.verify_file_object = AsyncMock(
            return_value=make_report(
                object_exists=True,
                problems=[make_problem(StorageIntegrityProblemType.CHECKSUM_MISMATCH)],
            )
        )

        result = await check_storage_integrity_handler(ctx)

        assert result.success is True
        assert result.result_data["corrupted_count"] == 1
        assert result.result_data["problems_count"] == 1
        uow.files.mark_storage_corrupted.assert_awaited_once_with(
            file_id=fid, flush=True, refresh=False
        )
        problem = result.result_data["problems"][0]
        assert problem["problem_type"] == "checksum_mismatch"

    @pytest.mark.asyncio
    async def test_size_mismatch_corruption(self) -> None:
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(return_value=[make_file_row()])
        ctx.storage_service.verify_file_object = AsyncMock(
            return_value=make_report(
                object_exists=True,
                problems=[make_problem(StorageIntegrityProblemType.SIZE_MISMATCH)],
            )
        )

        result = await check_storage_integrity_handler(ctx)
        assert result.result_data["corrupted_count"] == 1
        assert result.result_data["problems"][0]["problem_type"] == "size_mismatch"

    @pytest.mark.asyncio
    async def test_per_file_verify_exception_counted_as_failed(self) -> None:
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(return_value=[make_file_row()])
        ctx.storage_service.verify_file_object = AsyncMock(
            side_effect=ValueError("boom")
        )

        result = await check_storage_integrity_handler(ctx)

        assert result.success is True
        assert result.result_data["problems_count"] == 1
        assert result.result_data["missing_count"] == 0
        assert result.result_data["corrupted_count"] == 0
        problem = result.result_data["problems"][0]
        assert problem["problem_type"] is None
        assert problem["details"]["error_type"] == "ValueError"
        assert problem["details"]["reason"] == "boom"

    @pytest.mark.asyncio
    async def test_mixed_results_aggregated(self) -> None:
        ok = make_file_row()
        missing = make_file_row()
        corrupted = make_file_row()
        ctx, uow = make_ctx(payload={})
        # у всех строк одинаковый ключ по умолчанию, поэтому различаем ключи
        ok.storage_key = "k-ok"
        missing.storage_key = "k-missing"
        corrupted.storage_key = "k-corrupt"
        uow.files.list_by_storage_status = AsyncMock(
            return_value=[ok, missing, corrupted]
        )

        reports = {
            "k-ok": make_report(object_exists=True, problems=[]),
            "k-missing": make_report(object_exists=False),
            "k-corrupt": make_report(
                object_exists=True,
                problems=[make_problem(StorageIntegrityProblemType.SIZE_MISMATCH)],
            ),
        }

        async def verify_async(*, object_key, **_kwargs):
            return reports[object_key]

        ctx.storage_service.verify_file_object = AsyncMock(side_effect=verify_async)

        result = await check_storage_integrity_handler(ctx)

        assert result.result_data["checked_count"] == 3
        assert result.result_data["missing_count"] == 1
        assert result.result_data["corrupted_count"] == 1
        assert result.result_data["problems_count"] == 2


# ---------------------------------------------------------------------------
# Обработчик: ветки ошибок верхнего уровня
# ---------------------------------------------------------------------------


class TestTopLevelErrors:
    @pytest.mark.asyncio
    async def test_storage_connection_error_retries(self) -> None:
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(
            side_effect=StorageConnectionError("down")
        )

        result = await check_storage_integrity_handler(ctx)

        assert result.success is False
        assert result.retry is True
        assert result.error_code == "temporary_unavailable"
        assert result.result_data["error_type"] == "StorageConnectionError"

    @pytest.mark.asyncio
    async def test_database_connection_error_retries(self) -> None:
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(
            side_effect=DatabaseConnectionError("db down")
        )

        result = await check_storage_integrity_handler(ctx)

        assert result.success is False
        assert result.retry is True
        assert result.error_code == "temporary_unavailable"

    @pytest.mark.asyncio
    async def test_storage_error_returns_failure(self) -> None:
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(
            side_effect=StorageError("storage broke")
        )

        result = await check_storage_integrity_handler(ctx)

        assert result.success is False
        assert result.retry is False
        assert result.error_code == "integrity_check_failed"
        assert result.progress_percent == 0

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_failure(self) -> None:
        ctx, uow = make_ctx(payload={})
        uow.files.list_by_storage_status = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        result = await check_storage_integrity_handler(ctx)

        assert result.success is False
        assert result.retry is False
        assert result.error_code == "unexpected_integrity_check_error"
        assert result.result_data["error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_invalid_payload_uuid_returns_unexpected_failure(self) -> None:
        # ValueError из _optional_payload_uuid всплывает в общий обработчик
        ctx, uow = make_ctx(payload={"user_id": "not-a-uuid"})

        result = await check_storage_integrity_handler(ctx)

        assert result.success is False
        assert result.error_code == "unexpected_integrity_check_error"
