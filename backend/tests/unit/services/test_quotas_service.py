"""Юнит-тесты для QuotasService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from database import DatabaseError
from database.models.enums import QuotaResourceType
from schemas.quotas import (
    QuotaCheckRequest,
    QuotaRecalculateRequest,
    UserQuotaCreate,
    UserQuotaUpdate,
)
from services.exceptions import (
    QuotaExceededServiceError,
    ServiceError,
    ValidationServiceError,
)
from services.quotas import (
    QuotasService,
    _check_response,
    _optional_int,
    _quota_snapshot,
    _resource_limit_and_used,
    get_quotas_service,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def make_uow(**repos):
    uow = AsyncMock()
    uow.commit = AsyncMock()
    uow.flush_and_refresh = AsyncMock(side_effect=lambda obj: obj)
    uow.flush = AsyncMock()
    uow.refresh = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    for name, repo in repos.items():
        setattr(uow, name, repo)
    return uow


def make_factory(uow):
    return MagicMock(return_value=uow)


def make_audit():
    svc = MagicMock()
    svc.log_user_event = AsyncMock()
    svc.log_system_event = AsyncMock()
    svc.log_event = AsyncMock()
    return svc


def make_quota_mock(
    quota_id=None,
    user_id=None,
    storage_limit_bytes=10 * 1024 * 1024 * 1024,
    storage_used_bytes=0,
    max_file_size_bytes=1024 * 1024 * 1024,
    files_limit=None,
    files_used=0,
    public_links_limit=100,
    public_links_used=0,
    active_upload_sessions_limit=10,
    active_upload_sessions_used=0,
):
    quota = MagicMock()
    quota.id = quota_id or uuid.uuid4()
    quota.user_id = user_id or uuid.uuid4()
    quota.storage_limit_bytes = storage_limit_bytes
    quota.storage_used_bytes = storage_used_bytes
    quota.max_file_size_bytes = max_file_size_bytes
    quota.files_limit = files_limit
    quota.files_used = files_used
    quota.public_links_limit = public_links_limit
    quota.public_links_used = public_links_used
    quota.active_upload_sessions_limit = active_upload_sessions_limit
    quota.active_upload_sessions_used = active_upload_sessions_used
    quota.created_at = datetime.now(UTC)
    quota.updated_at = datetime.now(UTC)
    return quota


def make_capacity_provider(pool=10**18):
    """Мок провайдера ёмкости с заведомо большим пулом."""
    provider = MagicMock()
    provider.get_pool_bytes = AsyncMock(return_value=pool)
    status = MagicMock()
    status.pool_bytes = pool
    status.physical_total_bytes = pool
    status.physical_available_bytes = pool
    status.source = "config"
    status.minio_reachable = True
    provider.resolve = AsyncMock(return_value=status)
    return provider


def make_quotas_service(uow, audit_svc=None, capacity_provider=None):
    # Контроль ёмкости по умолчанию не должен блокировать позитивные тесты:
    # репозиторий квот возвращает нулевую аллокацию, пул — заведомо большой.
    quotas_repo = getattr(uow, "quotas", None)
    if quotas_repo is not None:
        quotas_repo.acquire_capacity_lock = AsyncMock()
        quotas_repo.total_allocated_storage_bytes = AsyncMock(return_value=0)
    return QuotasService(
        uow_factory=make_factory(uow),
        audit_service=audit_svc or make_audit(),
        capacity_provider=capacity_provider or make_capacity_provider(),
    )


# ---------------------------------------------------------------------------
# Тесты: create_quota
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_quota_returns_user_quota_read():
    """create_quota создаёт квоту и возвращает UserQuotaRead."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)

    quotas_repo = AsyncMock()
    quotas_repo.create_quota = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = UserQuotaCreate(
        user_id=user_id,
        storage_limit_bytes=10 * 1024 * 1024 * 1024,
        max_file_size_bytes=1024 * 1024 * 1024,
    )
    result = await service.create_quota(data, actor_id=user_id)

    assert result is not None
    assert str(result.user_id) == str(user_id)
    quotas_repo.create_quota.assert_called_once()


@pytest.mark.asyncio
async def test_create_default_quota_returns_user_quota_read():
    """create_default_quota создаёт квоту со значениями по умолчанию."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)

    quotas_repo = AsyncMock()
    quotas_repo.create_default_quota = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.create_default_quota(user_id)

    assert result is not None
    quotas_repo.create_default_quota.assert_called_once()


# ---------------------------------------------------------------------------
# Тесты: get_quota / get_quota_or_none
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_quota_returns_user_quota_read():
    """get_quota возвращает UserQuotaRead для существующего пользователя."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)

    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.get_quota(user_id)

    assert result is not None
    assert str(result.user_id) == str(user_id)


@pytest.mark.asyncio
async def test_get_quota_or_none_returns_none_when_no_quota():
    """get_quota_or_none возвращает None, когда квоты не существует."""
    user_id = uuid.uuid4()

    quotas_repo = AsyncMock()
    quotas_repo.get_by_user_id = AsyncMock(return_value=None)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.get_quota_or_none(user_id)

    assert result is None


@pytest.mark.asyncio
async def test_get_quota_or_none_returns_quota_when_exists():
    """get_quota_or_none возвращает UserQuotaRead, когда квота существует."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)

    quotas_repo = AsyncMock()
    quotas_repo.get_by_user_id = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.get_quota_or_none(user_id)

    assert result is not None
    assert str(result.user_id) == str(user_id)


# ---------------------------------------------------------------------------
# Тесты: check_quota / require_quota
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_quota_returns_check_response_allowed():
    """check_quota возвращает allowed=True при достаточном свободном месте."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(
        user_id=user_id,
        storage_limit_bytes=10 * 1024 * 1024 * 1024,
        storage_used_bytes=0,
    )

    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaCheckRequest(
        user_id=user_id,
        resource_type=QuotaResourceType.STORAGE_BYTES,
        requested_amount=1024 * 1024,  # 1 МБ, с запасом в пределах лимита
    )
    result = await service.check_quota(data)

    assert result is not None
    assert result.allowed is True


@pytest.mark.asyncio
async def test_check_quota_returns_denied_when_exceeded():
    """check_quota возвращает allowed=False при превышении квоты."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(
        user_id=user_id,
        storage_limit_bytes=1024,  # крошечный лимит
        storage_used_bytes=1024,   # уже на лимите
    )

    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaCheckRequest(
        user_id=user_id,
        resource_type=QuotaResourceType.STORAGE_BYTES,
        requested_amount=1024,  # превышает доступное
    )
    result = await service.check_quota(data)

    assert result is not None
    assert result.allowed is False


@pytest.mark.asyncio
async def test_require_quota_raises_when_exceeded():
    """require_quota вызывает QuotaExceededServiceError при превышении лимита."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(
        user_id=user_id,
        storage_limit_bytes=1024,
        storage_used_bytes=1024,
    )

    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaCheckRequest(
        user_id=user_id,
        resource_type=QuotaResourceType.STORAGE_BYTES,
        requested_amount=1024,
    )

    with pytest.raises(QuotaExceededServiceError):
        await service.require_quota(data)


# ---------------------------------------------------------------------------
# Тесты: update_quota
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_quota_returns_updated_quota():
    """update_quota обновляет лимиты и возвращает обновлённый UserQuotaRead."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id, storage_limit_bytes=5 * 1024 * 1024 * 1024)

    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)
    quotas_repo.update_limits = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    uow.flush_and_refresh = AsyncMock(return_value=quota)
    service = make_quotas_service(uow)

    data = UserQuotaUpdate(storage_limit_bytes=5 * 1024 * 1024 * 1024)
    result = await service.update_quota(user_id, data)

    assert result is not None


@pytest.mark.asyncio
async def test_update_quota_empty_returns_current():
    """update_quota без полей возвращает текущую квоту без записи в БД."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)

    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = UserQuotaUpdate()  # пустое обновление
    result = await service.update_quota(user_id, data)

    assert result is not None
    # get_required_by_user_id должен вызываться для резервного вызова get_quota
    quotas_repo.get_required_by_user_id.assert_called()


# ---------------------------------------------------------------------------
# Тесты: ensure_default_quota
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_default_quota_returns_existing():
    """ensure_default_quota возвращает существующую квоту без создания новой."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)

    quotas_repo = AsyncMock()
    quotas_repo.get_by_user_id = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.ensure_default_quota(user_id)

    assert result is not None
    quotas_repo.get_by_user_id.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_default_quota_creates_when_not_exists():
    """ensure_default_quota создаёт новую квоту, когда её нет."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)

    quotas_repo = AsyncMock()
    quotas_repo.get_by_user_id = AsyncMock(return_value=None)
    quotas_repo.create_default_quota = AsyncMock(return_value=quota)

    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.ensure_default_quota(user_id)

    assert result is not None
    quotas_repo.create_default_quota.assert_called_once()


# ---------------------------------------------------------------------------
# Тесты: оборачивание ошибок create_quota / create_default_quota + аудит
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_quota_logs_system_event_when_no_actor():
    """create_quota логирует системное событие аудита, когда actor_id равен None."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)
    quotas_repo = AsyncMock()
    quotas_repo.create_quota = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    audit = make_audit()
    service = make_quotas_service(uow, audit_svc=audit)

    data = UserQuotaCreate(
        user_id=user_id,
        storage_limit_bytes=10 * 1024,
        max_file_size_bytes=1024,
    )
    result = await service.create_quota(data)

    assert result is not None
    audit.log_system_event.assert_awaited_once()
    audit.log_user_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_quota_database_error_wrapped():
    """create_quota преобразует DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    quotas_repo = AsyncMock()
    quotas_repo.create_quota = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = UserQuotaCreate(
        user_id=user_id, storage_limit_bytes=10, max_file_size_bytes=10
    )
    with pytest.raises(ServiceError):
        await service.create_quota(data)


@pytest.mark.asyncio
async def test_create_quota_unexpected_error_wrapped():
    """create_quota преобразует непредвиденную ошибку в ServiceError."""
    user_id = uuid.uuid4()
    quotas_repo = AsyncMock()
    quotas_repo.create_quota = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = UserQuotaCreate(
        user_id=user_id, storage_limit_bytes=10, max_file_size_bytes=10
    )
    with pytest.raises(ServiceError):
        await service.create_quota(data)


@pytest.mark.asyncio
async def test_create_default_quota_database_error_wrapped():
    """create_default_quota преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.create_default_quota = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.create_default_quota(uuid.uuid4())


@pytest.mark.asyncio
async def test_create_default_quota_unexpected_error_wrapped():
    """create_default_quota преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.create_default_quota = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.create_default_quota(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: пути ошибок get_quota / get_quota_or_none / get_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_quota_database_error_wrapped():
    """get_quota преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.get_quota(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_quota_unexpected_error_wrapped():
    """get_quota преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.get_quota(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_quota_or_none_database_error_wrapped():
    """get_quota_or_none преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_by_user_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.get_quota_or_none(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_quota_or_none_unexpected_error_wrapped():
    """get_quota_or_none преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_by_user_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.get_quota_or_none(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_usage_returns_usage_read():
    """get_usage возвращает QuotaUsageRead с текущими счётчиками."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(
        user_id=user_id,
        storage_limit_bytes=1000,
        storage_used_bytes=250,
        files_used=3,
    )
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.get_usage(user_id)

    assert str(result.user_id) == str(user_id)
    assert result.storage_used_bytes == 250
    assert result.files_used == 3


@pytest.mark.asyncio
async def test_get_usage_database_error_wrapped():
    """get_usage преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.get_usage(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_usage_unexpected_error_wrapped():
    """get_usage преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.get_usage(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: update_quota (limits + counters branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_quota_all_counters_and_limits():
    """update_quota вызывает каждый сеттер счётчика и обновление лимитов."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)
    quotas_repo.update_limits = AsyncMock(return_value=quota)
    quotas_repo.update_storage_used = AsyncMock(return_value=quota)
    quotas_repo.set_files_used = AsyncMock(return_value=quota)
    quotas_repo.set_public_links_used = AsyncMock(return_value=quota)
    quotas_repo.set_active_upload_sessions_used = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    audit = make_audit()
    service = make_quotas_service(uow, audit_svc=audit)

    data = UserQuotaUpdate(
        storage_limit_bytes=2048,
        max_file_size_bytes=512,
        files_limit=50,
        public_links_limit=20,
        active_upload_sessions_limit=5,
        storage_used_bytes=100,
        files_used=4,
        public_links_used=2,
        active_upload_sessions_used=1,
    )
    result = await service.update_quota(user_id, data, actor_id=user_id)

    assert result is not None
    quotas_repo.update_limits.assert_awaited_once()
    quotas_repo.update_storage_used.assert_awaited_once()
    quotas_repo.set_files_used.assert_awaited_once()
    quotas_repo.set_public_links_used.assert_awaited_once()
    quotas_repo.set_active_upload_sessions_used.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_quota_database_error_wrapped():
    """update_quota преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = UserQuotaUpdate(storage_limit_bytes=1024)
    with pytest.raises(ServiceError):
        await service.update_quota(uuid.uuid4(), data)


@pytest.mark.asyncio
async def test_update_quota_unexpected_error_wrapped():
    """update_quota преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = UserQuotaUpdate(storage_limit_bytes=1024)
    with pytest.raises(ServiceError):
        await service.update_quota(uuid.uuid4(), data)


# ---------------------------------------------------------------------------
# Тесты: оборачивание ошибок check_quota + ресурсы без лимита
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_quota_unlimited_resource_allowed():
    """check_quota разрешает запросы, когда у ресурса нет лимита."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id, files_limit=None, files_used=5)
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaCheckRequest(
        user_id=user_id,
        resource_type=QuotaResourceType.FILE_COUNT,
        requested_amount=1000,
    )
    result = await service.check_quota(data)

    assert result.allowed is True
    assert result.limit is None
    assert result.available is None


@pytest.mark.asyncio
async def test_check_quota_database_error_wrapped():
    """check_quota преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaCheckRequest(
        user_id=uuid.uuid4(),
        resource_type=QuotaResourceType.STORAGE_BYTES,
        requested_amount=1,
    )
    with pytest.raises(ServiceError):
        await service.check_quota(data)


@pytest.mark.asyncio
async def test_check_quota_unexpected_error_wrapped():
    """check_quota преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaCheckRequest(
        user_id=uuid.uuid4(),
        resource_type=QuotaResourceType.STORAGE_BYTES,
        requested_amount=1,
    )
    with pytest.raises(ServiceError):
        await service.check_quota(data)


@pytest.mark.asyncio
async def test_require_quota_returns_when_allowed():
    """require_quota возвращает ответ, когда квота допускает запрос."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(
        user_id=user_id, storage_limit_bytes=10 * 1024, storage_used_bytes=0
    )
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaCheckRequest(
        user_id=user_id,
        resource_type=QuotaResourceType.STORAGE_BYTES,
        requested_amount=1024,
    )
    result = await service.require_quota(data)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_require_quota_logs_audit_on_exceed():
    """require_quota логирует событие аудита перед выбросом ошибки при превышении."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(
        user_id=user_id, storage_limit_bytes=1024, storage_used_bytes=1024
    )
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    audit = make_audit()
    service = make_quotas_service(uow, audit_svc=audit)

    data = QuotaCheckRequest(
        user_id=user_id,
        resource_type=QuotaResourceType.STORAGE_BYTES,
        requested_amount=1024,
    )
    with pytest.raises(QuotaExceededServiceError):
        await service.require_quota(data, actor_id=user_id)
    audit.log_user_event.assert_awaited_once()


# ---------------------------------------------------------------------------
# Тесты: increase_usage / decrease_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_type,method",
    [
        (QuotaResourceType.STORAGE_BYTES, "increase_used_space"),
        (QuotaResourceType.FILE_COUNT, "increase_files_used"),
        (QuotaResourceType.PUBLIC_LINK_COUNT, "increase_public_links_used"),
        (QuotaResourceType.UPLOAD_SESSION_COUNT, "increase_active_upload_sessions_used"),
    ],
)
async def test_increase_usage_dispatches_per_resource(resource_type, method):
    """increase_usage с отключённой проверкой вызывает нужный инкремент репозитория."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)
    quotas_repo = AsyncMock()
    setattr(quotas_repo, method, AsyncMock(return_value=quota))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.increase_usage(
        user_id, resource_type, amount=2, check_limit=False
    )
    assert result is not None
    getattr(quotas_repo, method).assert_awaited_once()


@pytest.mark.asyncio
async def test_increase_usage_with_check_limit_runs_require():
    """increase_usage с check_limit сначала выполняет проверку квоты."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(
        user_id=user_id, storage_limit_bytes=10 * 1024, storage_used_bytes=0
    )
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)
    quotas_repo.increase_used_space = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.increase_usage(
        user_id, QuotaResourceType.STORAGE_BYTES, amount=1024, check_limit=True
    )
    assert result is not None
    quotas_repo.get_required_by_user_id.assert_awaited()
    quotas_repo.increase_used_space.assert_awaited_once()


@pytest.mark.asyncio
async def test_increase_usage_invalid_amount_raises_validation():
    """increase_usage отклоняет неположительное значение количества."""
    uow = make_uow(quotas=AsyncMock())
    service = make_quotas_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.increase_usage(
            uuid.uuid4(), QuotaResourceType.FILE_COUNT, amount=0, check_limit=False
        )


@pytest.mark.asyncio
async def test_increase_usage_bool_amount_raises_validation():
    """increase_usage отклоняет булево значение количества."""
    uow = make_uow(quotas=AsyncMock())
    service = make_quotas_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.increase_usage(
            uuid.uuid4(), QuotaResourceType.FILE_COUNT, amount=True, check_limit=False
        )


@pytest.mark.asyncio
async def test_increase_usage_database_error_wrapped():
    """increase_usage преобразует DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    quotas_repo = AsyncMock()
    quotas_repo.increase_files_used = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.increase_usage(
            user_id, QuotaResourceType.FILE_COUNT, amount=1, check_limit=False
        )


@pytest.mark.asyncio
async def test_increase_usage_unexpected_error_wrapped():
    """increase_usage преобразует непредвиденную ошибку в ServiceError."""
    user_id = uuid.uuid4()
    quotas_repo = AsyncMock()
    quotas_repo.increase_files_used = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.increase_usage(
            user_id, QuotaResourceType.FILE_COUNT, amount=1, check_limit=False
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_type,method",
    [
        (QuotaResourceType.STORAGE_BYTES, "decrease_used_space"),
        (QuotaResourceType.FILE_COUNT, "decrease_files_used"),
        (QuotaResourceType.PUBLIC_LINK_COUNT, "decrease_public_links_used"),
        (QuotaResourceType.UPLOAD_SESSION_COUNT, "decrease_active_upload_sessions_used"),
    ],
)
async def test_decrease_usage_dispatches_per_resource(resource_type, method):
    """decrease_usage вызывает нужный декремент репозитория по типу ресурса."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)
    quotas_repo = AsyncMock()
    setattr(quotas_repo, method, AsyncMock(return_value=quota))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.decrease_usage(user_id, resource_type, amount=1)
    assert result is not None
    getattr(quotas_repo, method).assert_awaited_once()


@pytest.mark.asyncio
async def test_decrease_usage_invalid_amount_raises_validation():
    """decrease_usage отклоняет отрицательное значение."""
    uow = make_uow(quotas=AsyncMock())
    service = make_quotas_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.decrease_usage(
            uuid.uuid4(), QuotaResourceType.FILE_COUNT, amount=-1
        )


@pytest.mark.asyncio
async def test_decrease_usage_database_error_wrapped():
    """decrease_usage преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.decrease_files_used = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.decrease_usage(uuid.uuid4(), QuotaResourceType.FILE_COUNT)


@pytest.mark.asyncio
async def test_decrease_usage_unexpected_error_wrapped():
    """decrease_usage преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.decrease_files_used = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.decrease_usage(uuid.uuid4(), QuotaResourceType.FILE_COUNT)


# ---------------------------------------------------------------------------
# Тесты: can_store_file / require_file_can_be_stored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_store_file_returns_true():
    """can_store_file возвращает решение репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.can_store_file = AsyncMock(return_value=True)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    assert await service.can_store_file(uuid.uuid4(), 1024) is True


@pytest.mark.asyncio
async def test_can_store_file_allows_zero_size():
    """can_store_file принимает файл нулевого размера."""
    quotas_repo = AsyncMock()
    quotas_repo.can_store_file = AsyncMock(return_value=True)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    assert await service.can_store_file(uuid.uuid4(), 0) is True


@pytest.mark.asyncio
async def test_can_store_file_invalid_size_raises_validation():
    """can_store_file отклоняет отрицательный размер файла."""
    uow = make_uow(quotas=AsyncMock())
    service = make_quotas_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.can_store_file(uuid.uuid4(), -1)


@pytest.mark.asyncio
async def test_can_store_file_none_result_raises_service_error():
    """can_store_file вызывает ServiceError, когда репозиторий возвращает None."""
    quotas_repo = AsyncMock()
    quotas_repo.can_store_file = AsyncMock(return_value=None)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.can_store_file(uuid.uuid4(), 1024)


@pytest.mark.asyncio
async def test_can_store_file_database_error_wrapped():
    """can_store_file преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.can_store_file = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.can_store_file(uuid.uuid4(), 1024)


@pytest.mark.asyncio
async def test_can_store_file_unexpected_error_wrapped():
    """can_store_file преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.can_store_file = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.can_store_file(uuid.uuid4(), 1024)


@pytest.mark.asyncio
async def test_require_file_can_be_stored_allowed_returns_none():
    """require_file_can_be_stored возвращает None, когда хранение разрешено."""
    quotas_repo = AsyncMock()
    quotas_repo.can_store_file = AsyncMock(return_value=True)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    result = await service.require_file_can_be_stored(uuid.uuid4(), 1024)
    assert result is None


@pytest.mark.asyncio
async def test_require_file_can_be_stored_raises_when_denied():
    """require_file_can_be_stored вызывает QuotaExceededServiceError и пишет аудит."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(
        user_id=user_id, storage_limit_bytes=1024, storage_used_bytes=1024
    )
    quotas_repo = AsyncMock()
    quotas_repo.can_store_file = AsyncMock(return_value=False)
    quotas_repo.get_required_by_user_id = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    audit = make_audit()
    service = make_quotas_service(uow, audit_svc=audit)

    with pytest.raises(QuotaExceededServiceError):
        await service.require_file_can_be_stored(user_id, 4096, actor_id=user_id)
    audit.log_user_event.assert_awaited_once()


# ---------------------------------------------------------------------------
# Тесты: recalculate_quota (all branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recalculate_quota_all_resources():
    """recalculate_quota без resource_types пересчитывает всё."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)
    quotas_repo = AsyncMock()
    quotas_repo.recalculate_all = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    audit = make_audit()
    service = make_quotas_service(uow, audit_svc=audit)

    data = QuotaRecalculateRequest(user_id=user_id, resource_types=None)
    result = await service.recalculate_quota(data, actor_id=user_id)

    assert result is not None
    quotas_repo.recalculate_all.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_recalculate_quota_storage_only():
    """recalculate_quota только со storage пересчитывает использование."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)
    quotas_repo = AsyncMock()
    quotas_repo.recalculate_usage = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaRecalculateRequest(
        user_id=user_id, resource_types=[QuotaResourceType.STORAGE_BYTES]
    )
    result = await service.recalculate_quota(data)

    assert result is not None
    quotas_repo.recalculate_usage.assert_awaited_once()


@pytest.mark.asyncio
async def test_recalculate_quota_counters_only():
    """recalculate_quota без типа storage пересчитывает счётчики."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)
    quotas_repo = AsyncMock()
    quotas_repo.recalculate_counters = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaRecalculateRequest(
        user_id=user_id, resource_types=[QuotaResourceType.FILE_COUNT]
    )
    result = await service.recalculate_quota(data)

    assert result is not None
    quotas_repo.recalculate_counters.assert_awaited_once()


@pytest.mark.asyncio
async def test_recalculate_quota_mixed_storage_and_counters():
    """recalculate_quota со storage и счётчиком выполняет оба пересчёта."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)
    quotas_repo = AsyncMock()
    quotas_repo.recalculate_usage = AsyncMock(return_value=quota)
    quotas_repo.recalculate_counters = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaRecalculateRequest(
        user_id=user_id,
        resource_types=[
            QuotaResourceType.STORAGE_BYTES,
            QuotaResourceType.FILE_COUNT,
        ],
    )
    result = await service.recalculate_quota(data)

    assert result is not None
    quotas_repo.recalculate_usage.assert_awaited_once()
    quotas_repo.recalculate_counters.assert_awaited_once()


@pytest.mark.asyncio
async def test_recalculate_quota_database_error_wrapped():
    """recalculate_quota преобразует DatabaseError в ServiceError."""
    user_id = uuid.uuid4()
    quotas_repo = AsyncMock()
    quotas_repo.recalculate_all = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaRecalculateRequest(user_id=user_id)
    with pytest.raises(ServiceError):
        await service.recalculate_quota(data)


@pytest.mark.asyncio
async def test_recalculate_quota_unexpected_error_wrapped():
    """recalculate_quota преобразует непредвиденную ошибку в ServiceError."""
    user_id = uuid.uuid4()
    quotas_repo = AsyncMock()
    quotas_repo.recalculate_all = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaRecalculateRequest(user_id=user_id)
    with pytest.raises(ServiceError):
        await service.recalculate_quota(data)


# ---------------------------------------------------------------------------
# Тесты: list_near_limit / list_over_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_near_limit_returns_page():
    """list_near_limit возвращает постраничную страницу квот, близких к лимиту."""
    quota = make_quota_mock()
    quotas_repo = AsyncMock()
    quotas_repo.list_near_limit = AsyncMock(return_value=[quota])
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    page = await service.list_near_limit(threshold_percent=80.0, offset=0, limit=10)

    assert page.meta.total == 1
    assert page.meta.count == 1
    assert len(page.items) == 1


@pytest.mark.asyncio
async def test_list_near_limit_paginates_multiple_batches():
    """list_near_limit читает несколько пакетов из репозитория, когда они полные."""
    first_batch = [make_quota_mock() for _ in range(1000)]
    second_batch = [make_quota_mock() for _ in range(3)]
    quotas_repo = AsyncMock()
    quotas_repo.list_near_limit = AsyncMock(side_effect=[first_batch, second_batch])
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    page = await service.list_near_limit(offset=0, limit=10)

    assert page.meta.total == 1003
    assert quotas_repo.list_near_limit.await_count == 2


@pytest.mark.asyncio
async def test_list_near_limit_invalid_limit_raises_validation():
    """list_near_limit отклоняет limit вне диапазона."""
    uow = make_uow(quotas=AsyncMock())
    service = make_quotas_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.list_near_limit(limit=0)


@pytest.mark.asyncio
async def test_list_near_limit_negative_offset_raises_validation():
    """list_near_limit отклоняет отрицательный offset."""
    uow = make_uow(quotas=AsyncMock())
    service = make_quotas_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.list_near_limit(offset=-1)


@pytest.mark.asyncio
async def test_list_near_limit_database_error_wrapped():
    """list_near_limit преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.list_near_limit = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.list_near_limit()


@pytest.mark.asyncio
async def test_list_near_limit_unexpected_error_wrapped():
    """list_near_limit преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.list_near_limit = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.list_near_limit()


@pytest.mark.asyncio
async def test_list_over_limit_returns_page():
    """list_over_limit возвращает постраничную страницу квот сверх лимита."""
    quota = make_quota_mock()
    quotas_repo = AsyncMock()
    quotas_repo.list_over_limit = AsyncMock(return_value=[quota])
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    page = await service.list_over_limit(offset=0, limit=10)

    assert page.meta.total == 1
    assert page.meta.count == 1


@pytest.mark.asyncio
async def test_list_over_limit_paginates_multiple_batches():
    """list_over_limit читает несколько пакетов из репозитория, когда они полные."""
    first_batch = [make_quota_mock() for _ in range(1000)]
    second_batch = [make_quota_mock() for _ in range(2)]
    quotas_repo = AsyncMock()
    quotas_repo.list_over_limit = AsyncMock(side_effect=[first_batch, second_batch])
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    page = await service.list_over_limit(offset=0, limit=10)

    assert page.meta.total == 1002
    assert quotas_repo.list_over_limit.await_count == 2


@pytest.mark.asyncio
async def test_list_over_limit_invalid_limit_raises_validation():
    """list_over_limit отклоняет limit вне диапазона."""
    uow = make_uow(quotas=AsyncMock())
    service = make_quotas_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.list_over_limit(limit=99999)


@pytest.mark.asyncio
async def test_list_over_limit_database_error_wrapped():
    """list_over_limit преобразует DatabaseError в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.list_over_limit = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.list_over_limit()


@pytest.mark.asyncio
async def test_list_over_limit_unexpected_error_wrapped():
    """list_over_limit преобразует непредвиденную ошибку в ServiceError."""
    quotas_repo = AsyncMock()
    quotas_repo.list_over_limit = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.list_over_limit()


# ---------------------------------------------------------------------------
# Тесты: _safe_log_quota_event swallows audit failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_quota_swallows_audit_failure():
    """Сбой аудита во время create_quota не ломает операцию."""
    user_id = uuid.uuid4()
    quota = make_quota_mock(user_id=user_id)
    quotas_repo = AsyncMock()
    quotas_repo.create_quota = AsyncMock(return_value=quota)
    uow = make_uow(quotas=quotas_repo)
    audit = make_audit()
    audit.log_user_event = AsyncMock(side_effect=RuntimeError("audit down"))
    service = make_quotas_service(uow, audit_svc=audit)

    data = UserQuotaCreate(
        user_id=user_id, storage_limit_bytes=1024, max_file_size_bytes=1024
    )
    result = await service.create_quota(data, actor_id=user_id)
    assert result is not None


# ---------------------------------------------------------------------------
# Тесты: module-level helpers
# ---------------------------------------------------------------------------


def test_get_quotas_service_returns_instance():
    """get_quotas_service собирает QuotasService с внедрёнными зависимостями."""
    uow = make_uow(quotas=AsyncMock())
    service = get_quotas_service(uow_factory=make_factory(uow), audit_service=make_audit())
    assert isinstance(service, QuotasService)


def test_quota_snapshot_zero_limit_with_usage():
    """_quota_snapshot сообщает 100% использования, когда лимит ноль, но использование есть."""
    quota = make_quota_mock(storage_limit_bytes=0, storage_used_bytes=10)
    snapshot = _quota_snapshot(quota)
    assert snapshot["usage_percent"] == 100.0
    assert snapshot["is_storage_full"] is True
    assert snapshot["available_storage_bytes"] == 0


def test_quota_snapshot_partial_usage_percent():
    """_quota_snapshot вычисляет округлённый процент использования при частичном использовании."""
    quota = make_quota_mock(storage_limit_bytes=1000, storage_used_bytes=250)
    snapshot = _quota_snapshot(quota)
    assert snapshot["usage_percent"] == 25.0
    assert snapshot["available_storage_bytes"] == 750
    assert snapshot["is_storage_full"] is False


def test_optional_int_handles_none_and_value():
    """_optional_int преобразует значения и пропускает None."""
    assert _optional_int(None) is None
    assert _optional_int("5") == 5


def test_resource_limit_and_used_invalid_type_raises():
    """_resource_limit_and_used вызывает ошибку для неподдерживаемого типа ресурса."""
    snapshot = _quota_snapshot(make_quota_mock())
    with pytest.raises(ValidationServiceError):
        _resource_limit_and_used(snapshot, "not_a_resource")


@pytest.mark.parametrize(
    "resource_type",
    [
        QuotaResourceType.STORAGE_BYTES,
        QuotaResourceType.FILE_COUNT,
        QuotaResourceType.PUBLIC_LINK_COUNT,
        QuotaResourceType.UPLOAD_SESSION_COUNT,
    ],
)
def test_resource_limit_and_used_each_resource(resource_type):
    """_resource_limit_and_used возвращает кортеж (limit, used) по ресурсу."""
    snapshot = _quota_snapshot(
        make_quota_mock(
            files_limit=10, public_links_limit=5, active_upload_sessions_limit=2
        )
    )
    limit, used = _resource_limit_and_used(snapshot, resource_type)
    assert isinstance(used, int)
    assert limit is None or isinstance(limit, int)


def test_check_response_invalid_resource_type_raises():
    """_check_response вызывает ValidationServiceError для неизвестного типа ресурса."""
    snapshot = _quota_snapshot(make_quota_mock())
    with pytest.raises(ValidationServiceError):
        _check_response(snapshot, "bogus", 1)


# ---------------------------------------------------------------------------
# Тесты: ветки сквозного проброса ServiceError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_quota_service_error_passthrough():
    """create_quota пробрасывает ServiceError, возникший внутри unit of work."""
    quotas_repo = AsyncMock()
    quotas_repo.create_quota = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = UserQuotaCreate(
        user_id=uuid.uuid4(), storage_limit_bytes=1, max_file_size_bytes=1
    )
    with pytest.raises(ServiceError):
        await service.create_quota(data)


@pytest.mark.asyncio
async def test_create_default_quota_service_error_passthrough():
    """create_default_quota пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.create_default_quota = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.create_default_quota(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_quota_service_error_passthrough():
    """get_quota пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.get_quota(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_quota_or_none_service_error_passthrough():
    """get_quota_or_none пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.get_by_user_id = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.get_quota_or_none(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_usage_service_error_passthrough():
    """get_usage пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.get_usage(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_quota_service_error_passthrough():
    """update_quota пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.update_quota(uuid.uuid4(), UserQuotaUpdate(storage_limit_bytes=1))


@pytest.mark.asyncio
async def test_check_quota_service_error_passthrough():
    """check_quota пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.get_required_by_user_id = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    data = QuotaCheckRequest(
        user_id=uuid.uuid4(),
        resource_type=QuotaResourceType.STORAGE_BYTES,
        requested_amount=1,
    )
    with pytest.raises(ServiceError):
        await service.check_quota(data)


@pytest.mark.asyncio
async def test_increase_usage_invalid_resource_type_raises_validation():
    """increase_usage вызывает ValidationServiceError для неизвестного типа ресурса."""
    quotas_repo = AsyncMock()
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.increase_usage(
            uuid.uuid4(), "bogus_resource", amount=1, check_limit=False
        )


@pytest.mark.asyncio
async def test_decrease_usage_invalid_resource_type_raises_validation():
    """decrease_usage вызывает ValidationServiceError для неизвестного типа ресурса."""
    quotas_repo = AsyncMock()
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.decrease_usage(uuid.uuid4(), "bogus_resource", amount=1)


@pytest.mark.asyncio
async def test_recalculate_quota_service_error_passthrough():
    """recalculate_quota пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.recalculate_all = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.recalculate_quota(QuotaRecalculateRequest(user_id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_list_near_limit_service_error_passthrough():
    """list_near_limit пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.list_near_limit = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.list_near_limit()


@pytest.mark.asyncio
async def test_list_over_limit_service_error_passthrough():
    """list_over_limit пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.list_over_limit = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.list_over_limit()


@pytest.mark.asyncio
async def test_increase_usage_service_error_passthrough():
    """increase_usage пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.increase_files_used = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.increase_usage(
            uuid.uuid4(), QuotaResourceType.FILE_COUNT, amount=1, check_limit=False
        )


@pytest.mark.asyncio
async def test_decrease_usage_service_error_passthrough():
    """decrease_usage пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.decrease_files_used = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.decrease_usage(uuid.uuid4(), QuotaResourceType.FILE_COUNT)


@pytest.mark.asyncio
async def test_can_store_file_service_error_passthrough():
    """can_store_file пробрасывает ServiceError из репозитория."""
    quotas_repo = AsyncMock()
    quotas_repo.can_store_file = AsyncMock(
        side_effect=ServiceError("boom", service="quotas", operation="x")
    )
    uow = make_uow(quotas=quotas_repo)
    service = make_quotas_service(uow)

    with pytest.raises(ServiceError):
        await service.can_store_file(uuid.uuid4(), 1)


def test_require_result_none_raises_service_error():
    """_require_result вызывает ServiceError, когда результат None."""
    with pytest.raises(ServiceError):
        QuotasService._require_result(None, operation="get_quota")


def test_require_result_returns_value():
    """_require_result возвращает значение, когда оно не None."""
    sentinel = object()
    assert QuotasService._require_result(sentinel, operation="get_quota") is sentinel
