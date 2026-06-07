"""Юнит-тесты для AuditService (логирование и выборка событий аудита)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from database import DatabaseError, EntityNotFoundError
from database.models.enums import AuditAction, AuditResourceType, AuditResult
from schemas.audit import (
    AuditExportRequest,
    AuditLogCreate,
    AuditQueryParams,
)
from services.audit import AuditService, _audit_log_snapshot, get_audit_service
from services.exceptions import (
    NotFoundServiceError,
    ServiceError,
    ValidationServiceError,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def make_uow(**repos):
    uow = AsyncMock()
    uow.commit = AsyncMock()
    uow.flush = AsyncMock()
    uow.refresh = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    # expunge_all должен быть синхронным, чтобы избежать "coroutine never awaited".
    uow.session = MagicMock()
    uow.session.expunge_all = MagicMock()
    for name, repo in repos.items():
        setattr(uow, name, repo)
    return uow


def make_factory(uow):
    return MagicMock(return_value=uow)


def make_full_audit_log_mock(
    *,
    log_id=None,
    user_id=None,
    action=AuditAction.FILE_UPLOADED,
    result=AuditResult.SUCCESS,
    entity_type="file",
    resource_type=AuditResourceType.FILE,
    request_id=None,
    correlation_id=None,
    ip_address=None,
    user_agent=None,
    message="Test event",
    error_code=None,
    metadata=None,
    created_at=None,
):
    """Мок записи аудита с полностью управляемыми полями для фильтра/сортировки/экспорта."""
    log = MagicMock()
    log.id = log_id or uuid.uuid4()
    log.user_id = user_id
    log.action = action
    log.result = result
    log.entity_type = entity_type
    log.entity_id = uuid.uuid4()
    log.resource_type = resource_type
    log.request_id = request_id
    log.correlation_id = correlation_id
    log.ip_address = ip_address
    log.user_agent = user_agent
    log.message = message
    log.error_code = error_code
    log.metadata_ = metadata
    log.created_at = created_at or datetime.now(UTC)
    return log


def make_audit_log_mock(
    log_id=None,
    user_id=None,
    action=AuditAction.FILE_UPLOADED,
    result=AuditResult.SUCCESS,
):
    log = MagicMock()
    log.id = log_id or uuid.uuid4()
    log.user_id = user_id or uuid.uuid4()
    log.action = action
    log.result = result
    log.entity_type = "file"
    log.entity_id = uuid.uuid4()
    log.resource_type = AuditResourceType.FILE
    log.request_id = None
    log.correlation_id = None
    log.ip_address = None
    log.user_agent = None
    log.message = "Test event"
    log.error_code = None
    log.metadata_ = None
    log.created_at = datetime.now(UTC)
    return log


# ---------------------------------------------------------------------------
# Тесты: log_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_event_returns_audit_log_read():
    """log_event создаёт запись и возвращает AuditLogRead."""
    user_id = uuid.uuid4()
    log = make_audit_log_mock(user_id=user_id)

    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    result = await service.log_event(
        action=AuditAction.FILE_UPLOADED,
        result=AuditResult.SUCCESS,
        user_id=user_id,
        message="File uploaded",
    )

    assert result is not None
    audit_repo.create_event.assert_called_once()


@pytest.mark.asyncio
async def test_log_event_propagates_database_error():
    """log_event преобразует DatabaseError в ServiceError."""
    from database import DatabaseError

    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(side_effect=DatabaseError("DB error"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError):
        await service.log_event(action=AuditAction.FILE_UPLOADED)


# ---------------------------------------------------------------------------
# Тесты: log_user_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_user_event_passes_user_id():
    """log_user_event передаёт user_id в нижележащий log_event."""
    user_id = uuid.uuid4()
    log = make_audit_log_mock(user_id=user_id)

    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    result = await service.log_user_event(
        user_id=user_id,
        action=AuditAction.FILE_UPLOADED,
        message="User uploaded a file",
    )

    assert result is not None
    call_kwargs = audit_repo.create_event.call_args.kwargs
    assert call_kwargs["user_id"] == user_id


# ---------------------------------------------------------------------------
# Тесты: log_system_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_system_event_has_no_user_id():
    """log_system_event передаёт user_id=None в create_event."""
    log = make_audit_log_mock()

    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    result = await service.log_system_event(
        action=AuditAction.BACKGROUND_TASK_CREATED,
        message="System task created",
    )

    assert result is not None
    call_kwargs = audit_repo.create_event.call_args.kwargs
    assert call_kwargs["user_id"] is None


# ---------------------------------------------------------------------------
# Тесты: log_success / log_failure / log_denied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_success_sets_success_result():
    log = make_audit_log_mock(result=AuditResult.SUCCESS)
    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    result = await service.log_success(action=AuditAction.FILE_UPLOADED)
    call_kwargs = audit_repo.create_event.call_args.kwargs
    assert call_kwargs["result"] == AuditResult.SUCCESS
    assert result is not None


@pytest.mark.asyncio
async def test_log_failure_sets_failure_result():
    log = make_audit_log_mock(result=AuditResult.FAILURE)
    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    result = await service.log_failure(action=AuditAction.FILE_UPLOADED, error_code="ERR")
    call_kwargs = audit_repo.create_event.call_args.kwargs
    assert call_kwargs["result"] == AuditResult.FAILURE
    assert result is not None


@pytest.mark.asyncio
async def test_log_denied_sets_denied_result():
    log = make_audit_log_mock(result=AuditResult.DENIED)
    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    result = await service.log_denied(action=AuditAction.FILE_UPLOADED)
    call_kwargs = audit_repo.create_event.call_args.kwargs
    assert call_kwargs["result"] == AuditResult.DENIED
    assert result is not None


# ---------------------------------------------------------------------------
# Тесты: list_logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_logs_returns_page_response():
    """list_logs возвращает PageResponse с AuditLogListItem."""
    from schemas.audit import AuditQueryParams

    log = make_audit_log_mock()

    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=[log])

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    params = AuditQueryParams()
    result = await service.list_logs(params)

    assert result is not None
    assert hasattr(result, "items")
    assert hasattr(result, "meta")


@pytest.mark.asyncio
async def test_list_logs_empty_returns_empty_page():
    """list_logs без результатов возвращает пустой список items."""
    from schemas.audit import AuditQueryParams

    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=[])

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    params = AuditQueryParams()
    result = await service.list_logs(params)

    assert result.items == []
    assert result.meta.total == 0


# ---------------------------------------------------------------------------
# Тесты: оборачивание ошибок log_event и точки входа схемы/хелперов
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_event_wraps_unexpected_error():
    """Не-БД исключение преобразуется в обобщённый ServiceError."""
    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.log_event(action=AuditAction.FILE_UPLOADED)
    assert exc_info.value.operation == "log_event"


@pytest.mark.asyncio
async def test_log_event_normalizes_message_and_metadata():
    """log_event обрезает message и json-нормализует metadata перед сохранением."""
    log = make_full_audit_log_mock()
    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    nested_uuid = uuid.uuid4()
    await service.log_event(
        action=AuditAction.FILE_UPLOADED,
        message="   padded   ",
        metadata={"key": nested_uuid, "n": 1},
    )

    call_kwargs = audit_repo.create_event.call_args.kwargs
    assert call_kwargs["message"] == "padded"
    assert call_kwargs["metadata"] == {"key": str(nested_uuid), "n": 1}
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_from_schema_forwards_fields():
    """log_from_schema переносит поля AuditLogCreate в create_event."""
    user_id = uuid.uuid4()
    log = make_full_audit_log_mock(user_id=user_id)
    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    data = AuditLogCreate(
        user_id=user_id,
        action=AuditAction.FILE_UPLOADED,
        result=AuditResult.SUCCESS,
        message="from schema",
    )
    result = await service.log_from_schema(data)

    assert result is not None
    call_kwargs = audit_repo.create_event.call_args.kwargs
    assert call_kwargs["user_id"] == user_id
    assert call_kwargs["action"] == AuditAction.FILE_UPLOADED


# ---------------------------------------------------------------------------
# Тесты: get_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_log_returns_read():
    log = make_full_audit_log_mock()
    audit_repo = AsyncMock()
    audit_repo.get_required_log_by_id = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    result = await service.get_log(log.id)
    assert result.id == log.id
    audit_repo.get_required_log_by_id.assert_awaited_once_with(log.id)


@pytest.mark.asyncio
async def test_get_log_not_found_raises_not_found_service_error():
    log_id = uuid.uuid4()
    audit_repo = AsyncMock()
    audit_repo.get_required_log_by_id = AsyncMock(
        side_effect=EntityNotFoundError(entity_name="AuditLog", entity_id=log_id)
    )

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(NotFoundServiceError):
        await service.get_log(log_id)


@pytest.mark.asyncio
async def test_get_log_database_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.get_required_log_by_id = AsyncMock(side_effect=DatabaseError("db"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError):
        await service.get_log(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_log_unexpected_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.get_required_log_by_id = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.get_log(uuid.uuid4())
    assert exc_info.value.operation == "get_log"


# ---------------------------------------------------------------------------
# Тесты: фильтры list_logs, пагинация, сортировка, ошибки
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_logs_applies_service_filters_and_pagination():
    """Сервисный фильтр по result применяется, а пагинация нарезает результаты."""
    matching = [
        make_full_audit_log_mock(result=AuditResult.FAILURE, message=f"m{i}")
        for i in range(5)
    ]
    non_matching = make_full_audit_log_mock(result=AuditResult.SUCCESS)
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=[*matching, non_matching])

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    params = AuditQueryParams(result=AuditResult.FAILURE, limit=2, offset=1)
    result = await service.list_logs(params)

    # 5 подходят под фильтр FAILURE; страница из 2 начиная со смещения 1.
    assert result.meta.total == 5
    assert result.meta.count == 2
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_list_logs_service_sort_field_triggers_service_sort():
    """Поле сортировки только для сервиса (result) включает сортировку в сервисе."""
    logs = [
        make_full_audit_log_mock(result=AuditResult.SUCCESS),
        make_full_audit_log_mock(result=AuditResult.FAILURE),
        make_full_audit_log_mock(result=AuditResult.DENIED),
    ]
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=logs)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    params = AuditQueryParams(sort_by="result", sort_desc=False)
    result = await service.list_logs(params)
    results = [item.result for item in result.items]
    assert results == sorted(results, key=lambda r: r.value)


@pytest.mark.asyncio
async def test_list_logs_unknown_sort_field_defaults_created_at():
    """Неподдерживаемое поле сортировки нормализуется в created_at для репозитория."""
    logs = [make_full_audit_log_mock()]
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=logs)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    params = AuditQueryParams(sort_by="not_a_field")
    await service.list_logs(params)
    assert audit_repo.list_logs.call_args.kwargs["sort_by"] == "created_at"


@pytest.mark.asyncio
async def test_list_logs_repository_sort_field_passed_through():
    """Поддерживаемое репозиторием поле сортировки с desc передаётся напрямую в репозиторий."""
    logs = [make_full_audit_log_mock()]
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=logs)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    params = AuditQueryParams(sort_by="action", sort_desc=True)
    await service.list_logs(params)
    assert audit_repo.list_logs.call_args.kwargs["sort_by"] == "action"
    assert audit_repo.list_logs.call_args.kwargs["sort_direction"] == "desc"


@pytest.mark.asyncio
async def test_list_logs_database_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(side_effect=DatabaseError("db"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError):
        await service.list_logs(AuditQueryParams())


@pytest.mark.asyncio
async def test_list_logs_unexpected_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.list_logs(AuditQueryParams())
    assert exc_info.value.operation == "list_logs"


# ---------------------------------------------------------------------------
# Тесты: покрытие _matches_params / _matches_query через list_logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_logs_filters_by_all_service_fields():
    """Применяются все фильтры: resource_type, request_id, correlation_id и query."""
    good = make_full_audit_log_mock(
        resource_type=AuditResourceType.FILE,
        request_id="req-1",
        correlation_id="corr-1",
        message="needle in message",
    )
    bad_resource = make_full_audit_log_mock(
        resource_type=AuditResourceType.FOLDER,
        request_id="req-1",
        correlation_id="corr-1",
        message="needle",
    )
    bad_request = make_full_audit_log_mock(
        resource_type=AuditResourceType.FILE,
        request_id="other",
        correlation_id="corr-1",
        message="needle",
    )
    bad_corr = make_full_audit_log_mock(
        resource_type=AuditResourceType.FILE,
        request_id="req-1",
        correlation_id="other",
        message="needle",
    )
    bad_query = make_full_audit_log_mock(
        resource_type=AuditResourceType.FILE,
        request_id="req-1",
        correlation_id="corr-1",
        message="nothing here",
    )
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(
        return_value=[good, bad_resource, bad_request, bad_corr, bad_query]
    )

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    params = AuditQueryParams(
        resource_type=AuditResourceType.FILE,
        request_id="req-1",
        correlation_id="corr-1",
        query="NEEDLE",
    )
    result = await service.list_logs(params)
    assert result.meta.total == 1
    assert result.items[0].id == good.id


@pytest.mark.asyncio
async def test_list_logs_query_matches_resource_type_value():
    """Текстовый запрос может совпадать и со значением enum resource_type."""
    good = make_full_audit_log_mock(
        resource_type=AuditResourceType.FOLDER, message="x", error_code=None
    )
    bad = make_full_audit_log_mock(
        resource_type=None, message="x", error_code=None
    )
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=[good, bad])

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    params = AuditQueryParams(query=AuditResourceType.FOLDER.value)
    result = await service.list_logs(params)
    assert result.meta.total == 1
    assert result.items[0].id == good.id


# ---------------------------------------------------------------------------
# Тесты: get_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_summary_aggregates_counts():
    logs = [
        make_full_audit_log_mock(
            result=AuditResult.SUCCESS, resource_type=AuditResourceType.FILE
        ),
        make_full_audit_log_mock(
            result=AuditResult.FAILURE, resource_type=AuditResourceType.FILE
        ),
        make_full_audit_log_mock(
            result=AuditResult.DENIED, resource_type=AuditResourceType.FOLDER
        ),
        make_full_audit_log_mock(
            result=AuditResult.WARNING, resource_type=None
        ),
    ]
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=logs)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    summary = await service.get_summary(AuditQueryParams())
    assert summary.total_count == 4
    assert summary.success_count == 1
    assert summary.failure_count == 1
    assert summary.denied_count == 1
    assert summary.warning_count == 1
    assert summary.by_resource_type[AuditResourceType.FILE] == 2
    assert summary.by_resource_type[AuditResourceType.FOLDER] == 1
    assert AuditResourceType.FILE in summary.by_resource_type


@pytest.mark.asyncio
async def test_get_summary_database_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(side_effect=DatabaseError("db"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError):
        await service.get_summary(AuditQueryParams())


@pytest.mark.asyncio
async def test_get_summary_unexpected_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.get_summary(AuditQueryParams())
    assert exc_info.value.operation == "get_summary"


# ---------------------------------------------------------------------------
# Тесты: export_logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_logs_json_with_metadata():
    import json

    log = make_full_audit_log_mock(
        user_id=uuid.uuid4(),
        resource_type=AuditResourceType.FILE,
        ip_address="10.0.0.1",
        metadata={"k": "v"},
    )
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=[log])

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    payload = await service.export_logs(
        AuditExportRequest(format="json", include_metadata=True)
    )
    assert payload["format"] == "json"
    assert payload["filename"] == "audit_logs.json"
    assert payload["content_type"] == "application/json"
    assert payload["count"] == 1
    rows = json.loads(payload["content"])
    assert rows[0]["metadata"] == {"k": "v"}
    assert rows[0]["ip_address"] == "10.0.0.1"
    assert rows[0]["resource_type"] == AuditResourceType.FILE.value


@pytest.mark.asyncio
async def test_export_logs_csv_serializes_complex_values():
    log = make_full_audit_log_mock(metadata={"k": "v"})
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=[log])

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    payload = await service.export_logs(
        AuditExportRequest(format="csv", include_metadata=True)
    )
    assert payload["format"] == "csv"
    assert payload["filename"] == "audit_logs.csv"
    assert payload["content_type"] == "text/csv; charset=utf-8"
    content = payload["content"]
    assert "metadata" in content.splitlines()[0]
    # Метаданные-словарь JSON-кодируются внутри ячейки CSV.
    assert '{""k"": ""v""}' in content or '{"k": "v"}' in content


@pytest.mark.asyncio
async def test_export_logs_csv_empty_returns_empty_string():
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=[])

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    payload = await service.export_logs(AuditExportRequest(format="csv"))
    assert payload["content"] == ""
    assert payload["count"] == 0


@pytest.mark.asyncio
async def test_export_logs_respects_limit():
    logs = [make_full_audit_log_mock() for _ in range(5)]
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=logs)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    payload = await service.export_logs(
        AuditExportRequest(format="json", limit=2)
    )
    assert payload["count"] == 2


@pytest.mark.asyncio
async def test_export_logs_unsupported_format_raises_validation_error(monkeypatch):
    """Неподдерживаемый формат доходит до ветки экспорта и вызывает ошибку валидации."""
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=[])

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    request = AuditExportRequest(format="json")
    # Обходим валидатор уровня схемы, чтобы проверить защиту на стороне сервиса.
    object.__setattr__(request, "format", "xml")

    with pytest.raises(ValidationServiceError) as exc_info:
        await service.export_logs(request)
    assert exc_info.value.details.get("field") == "format"


@pytest.mark.asyncio
async def test_export_logs_database_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(side_effect=DatabaseError("db"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError):
        await service.export_logs(AuditExportRequest(format="json"))


@pytest.mark.asyncio
async def test_export_logs_unexpected_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.export_logs(AuditExportRequest(format="json"))
    assert exc_info.value.operation == "export_logs"


# ---------------------------------------------------------------------------
# Тесты: get_latest_user_logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_latest_user_logs_returns_items():
    user_id = uuid.uuid4()
    logs = [make_full_audit_log_mock(user_id=user_id) for _ in range(3)]
    audit_repo = AsyncMock()
    audit_repo.get_latest_user_logs = AsyncMock(return_value=logs)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    items = await service.get_latest_user_logs(user_id, limit=3)
    assert len(items) == 3
    audit_repo.get_latest_user_logs.assert_awaited_once_with(user_id, limit=3)


@pytest.mark.asyncio
async def test_get_latest_user_logs_invalid_limit_raises_validation():
    service = AuditService(uow_factory=make_factory(make_uow(audit=AsyncMock())))
    with pytest.raises(ValidationServiceError):
        await service.get_latest_user_logs(uuid.uuid4(), limit=0)
    with pytest.raises(ValidationServiceError):
        await service.get_latest_user_logs(uuid.uuid4(), limit=101)


@pytest.mark.asyncio
async def test_get_latest_user_logs_database_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.get_latest_user_logs = AsyncMock(side_effect=DatabaseError("db"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError):
        await service.get_latest_user_logs(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_latest_user_logs_unexpected_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.get_latest_user_logs = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.get_latest_user_logs(uuid.uuid4())
    assert exc_info.value.operation == "get_latest_user_logs"


# ---------------------------------------------------------------------------
# Тесты: cleanup_before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_before_returns_deleted_count():
    audit_repo = AsyncMock()
    audit_repo.delete_logs_before = AsyncMock(return_value=7)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    before = datetime.now(UTC) - timedelta(days=30)
    deleted = await service.cleanup_before(
        created_before=before,
        action=AuditAction.FILE_UPLOADED,
        entity_type="file",
        system_only=True,
    )
    assert deleted == 7
    uow.commit.assert_awaited_once()
    call_kwargs = audit_repo.delete_logs_before.call_args.kwargs
    assert call_kwargs["created_before"] == before
    assert call_kwargs["action"] == AuditAction.FILE_UPLOADED
    assert call_kwargs["system_only"] is True


@pytest.mark.asyncio
async def test_cleanup_before_database_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.delete_logs_before = AsyncMock(side_effect=DatabaseError("db"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError):
        await service.cleanup_before(created_before=datetime.now(UTC))


@pytest.mark.asyncio
async def test_cleanup_before_unexpected_error_wrapped():
    audit_repo = AsyncMock()
    audit_repo.delete_logs_before = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.cleanup_before(created_before=datetime.now(UTC))
    assert exc_info.value.operation == "cleanup_before"


# ---------------------------------------------------------------------------
# Тесты: чистые вспомогательные методы
# ---------------------------------------------------------------------------


def test_normalize_optional_string():
    assert AuditService._normalize_optional_string(None) is None
    assert AuditService._normalize_optional_string("   ") is None
    assert AuditService._normalize_optional_string("  hi  ") == "hi"


def test_normalize_metadata_none_and_jsonable():
    service = AuditService(uow_factory=make_factory(make_uow(audit=AsyncMock())))
    assert service._normalize_metadata(None) is None
    out = service._normalize_metadata({1: "a"})
    assert out == {"1": "a"}


def test_jsonable_covers_all_branches():
    nested_uuid = uuid.uuid4()
    now = datetime.now(UTC)

    class Dummy:
        def model_dump(self):
            return {"x": 1}

    assert AuditService._jsonable(None) is None
    assert AuditService._jsonable("s") == "s"
    assert AuditService._jsonable(3) == 3
    assert AuditService._jsonable(nested_uuid) == str(nested_uuid)
    assert AuditService._jsonable(now) == now.isoformat()
    assert AuditService._jsonable(AuditResult.SUCCESS) == AuditResult.SUCCESS.value
    assert AuditService._jsonable({"k": nested_uuid}) == {"k": str(nested_uuid)}
    assert AuditService._jsonable([1, nested_uuid]) == [1, str(nested_uuid)]
    assert AuditService._jsonable({nested_uuid}) == [str(nested_uuid)]
    assert AuditService._jsonable(Dummy()) == {"x": 1}
    assert AuditService._jsonable(object()).startswith("<object")


def test_normalize_sort_by():
    service = AuditService(uow_factory=make_factory(make_uow(audit=AsyncMock())))
    assert service._normalize_sort_by(" action ") == "action"
    assert service._normalize_sort_by("nope") == "created_at"


def test_validate_limit_ok_and_error():
    AuditService._validate_limit(50, max_limit=100)
    with pytest.raises(ValidationServiceError):
        AuditService._validate_limit(0, max_limit=100)


def test_audit_log_snapshot_includes_all_fields():
    log = make_full_audit_log_mock(ip_address="1.2.3.4", metadata={"a": 1})
    snapshot = _audit_log_snapshot(log)
    assert snapshot["id"] == log.id
    assert snapshot["ip_address"] == "1.2.3.4"
    assert snapshot["metadata_"] == {"a": 1}


def test_audit_log_snapshot_none_ip():
    log = make_full_audit_log_mock(ip_address=None)
    snapshot = _audit_log_snapshot(log)
    assert snapshot["ip_address"] is None


def test_jsonable_metadata_with_enum_value():
    """Не-строковое значение-enum в metadata нормализуется в .value (ветка enum)."""
    from enum import Enum

    class Color(Enum):
        RED = "red"

    service = AuditService(uow_factory=make_factory(make_uow(audit=AsyncMock())))
    out = service._normalize_metadata({"c": Color.RED})
    assert out == {"c": "red"}


@pytest.mark.asyncio
async def test_log_event_reraises_service_error():
    """ServiceError, возникший при commit, пробрасывается без изменений."""
    log = make_full_audit_log_mock()
    sentinel = ServiceError("commit boom", service="audit", operation="log_event")
    audit_repo = AsyncMock()
    audit_repo.create_event = AsyncMock(return_value=log)

    uow = make_uow(audit=audit_repo)
    uow.commit = AsyncMock(side_effect=sentinel)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.log_event(action=AuditAction.FILE_UPLOADED)
    assert exc_info.value is sentinel


def test_matches_query_empty_string_matches():
    """Запрос из одних пробелов сразу считается совпадением."""
    service = AuditService(uow_factory=make_factory(make_uow(audit=AsyncMock())))
    log = make_full_audit_log_mock()
    assert service._matches_query(log, "   ") is True


def test_sort_logs_handles_uuid_field():
    """Сортировка по UUID-полю приводит значение к строке."""
    service = AuditService(uow_factory=make_factory(make_uow(audit=AsyncMock())))
    logs = [make_full_audit_log_mock() for _ in range(3)]
    ordered = service._sort_logs(logs, sort_by="entity_id", sort_desc=False)
    keys = [str(log.entity_id) for log in ordered]
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_load_filtered_logs_applies_pagination_when_not_ignored():
    """Прямой вызов с ignore_pagination=False нарезает по offset/limit."""
    logs = [make_full_audit_log_mock() for _ in range(5)]
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(return_value=logs)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    params = AuditQueryParams(limit=2, offset=1)
    page = await service._load_filtered_logs(params=params, ignore_pagination=False)
    assert len(page) == 2


@pytest.mark.asyncio
async def test_list_logs_reraises_service_error():
    """ServiceError, возникший по ходу, пробрасывается без изменений (ветка except)."""
    sentinel = ServiceError("boom", service="audit", operation="list_logs")
    audit_repo = AsyncMock()
    audit_repo.list_logs = AsyncMock(side_effect=sentinel)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.list_logs(AuditQueryParams())
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_get_log_reraises_service_error():
    """get_log пробрасывает чистый ServiceError без повторного оборачивания."""
    sentinel = ServiceError("boom", service="audit", operation="get_log")
    audit_repo = AsyncMock()
    audit_repo.get_required_log_by_id = AsyncMock(side_effect=sentinel)

    uow = make_uow(audit=audit_repo)
    service = AuditService(uow_factory=make_factory(uow))

    with pytest.raises(ServiceError) as exc_info:
        await service.get_log(uuid.uuid4())
    assert exc_info.value is sentinel


def test_get_audit_service_returns_instance():
    uow = make_uow(audit=AsyncMock())
    service = get_audit_service(uow_factory=make_factory(uow))
    assert isinstance(service, AuditService)
    assert service.uow_factory is not None
