"""Юнит-тесты для RegistrationService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from database import DatabaseError
from database.models.enums import RegistrationRequestStatus
from schemas.registration import (
    RegistrationApproveRequest,
    RegistrationCancelRequest,
    RegistrationDecisionResponse,
    RegistrationQueryParams,
    RegistrationRejectRequest,
    RegistrationRequestRead,
)
from services.exceptions import ConflictServiceError, ServiceError, ValidationServiceError
from tests.unit.services.conftest import make_uow_factory, make_uow_mock


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

def make_audit_service() -> MagicMock:
    svc = MagicMock()
    svc.log_user_event = AsyncMock()
    svc.log_system_event = AsyncMock()
    return svc


def make_request_mock(
    *,
    request_id: uuid.UUID | None = None,
    email: str = "newuser@example.com",
    username: str = "newuser",
    password_hash: str = "$2b$12$fakehash",
    status: RegistrationRequestStatus = RegistrationRequestStatus.PENDING,
    comment: str | None = None,
    rejection_reason: str | None = None,
    reviewed_at: datetime | None = None,
    reviewed_by: uuid.UUID | None = None,
    created_user_id: uuid.UUID | None = None,
) -> MagicMock:
    req = MagicMock()
    req.id = request_id or uuid.uuid4()
    req.email = email
    req.username = username
    req.password_hash = password_hash
    req.status = status
    req.comment = comment
    req.rejection_reason = rejection_reason
    req.reviewed_at = reviewed_at
    req.reviewed_by = reviewed_by
    req.created_user_id = created_user_id
    req.created_at = datetime.now(UTC)
    return req


def make_user_mock(user_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = "newuser@example.com"
    user.username = "newuser"
    return user


def make_capacity_provider(pool=10**18):
    """Мок провайдера ёмкости с заведомо большим пулом."""
    provider = MagicMock()
    provider.get_pool_bytes = AsyncMock(return_value=pool)
    return provider


def make_service(uow_mock, audit_mock=None, capacity_provider=None):
    from services.registration import RegistrationService
    audit = audit_mock or make_audit_service()
    factory = make_uow_factory(uow_mock)
    # Контроль ёмкости по умолчанию не должен блокировать позитивные тесты.
    quotas_repo = getattr(uow_mock, "quotas", None)
    if quotas_repo is not None:
        quotas_repo.acquire_capacity_lock = AsyncMock()
        quotas_repo.total_allocated_storage_bytes = AsyncMock(return_value=0)
    return RegistrationService(
        uow_factory=factory,
        audit_service=audit,
        capacity_provider=capacity_provider or make_capacity_provider(),
    )


# ---------------------------------------------------------------------------
# submit_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_request_success():
    """Создаёт заявку, когда email и имя пользователя свободны."""
    request = make_request_mock()

    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=False)

    reg_repo = AsyncMock()
    reg_repo.create_request = AsyncMock(return_value=request)

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    from schemas.registration import RegistrationRequestCreate
    data = RegistrationRequestCreate(
        email="newuser@example.com",
        username="newuser",
        password="StrongPass123!",
    )
    result = await service.submit_request(data)

    assert isinstance(result, RegistrationRequestRead)
    reg_repo.create_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_request_email_taken_raises_conflict():
    """Вызывает ConflictServiceError, когда email уже зарегистрирован."""
    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=True)
    users_repo.username_exists = AsyncMock(return_value=False)

    reg_repo = AsyncMock()

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    from schemas.registration import RegistrationRequestCreate
    data = RegistrationRequestCreate(
        email="taken@example.com",
        username="newuser",
        password="StrongPass123!",
    )
    with pytest.raises(ConflictServiceError):
        await service.submit_request(data)


@pytest.mark.asyncio
async def test_submit_request_weak_password_raises_validation_error():
    """Вызывает ValidationServiceError, когда пароль слишком слабый."""
    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=False)

    reg_repo = AsyncMock()

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    from schemas.registration import RegistrationRequestCreate
    # Обходим валидацию минимальной длины Pydantic, чтобы дойти до проверки сервиса
    data = RegistrationRequestCreate.model_construct(
        email="newuser@example.com",
        username="newuser",
        password="weak",
    )
    with pytest.raises((ValidationServiceError, ValueError)):
        await service.submit_request(data)


@pytest.mark.asyncio
async def test_submit_request_username_taken_raises_conflict():
    """Вызывает ConflictServiceError, когда имя пользователя уже зарегистрировано."""
    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=True)

    reg_repo = AsyncMock()

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    from schemas.registration import RegistrationRequestCreate
    data = RegistrationRequestCreate(
        email="newuser@example.com",
        username="taken",
        password="StrongPass123!",
    )
    with pytest.raises(ConflictServiceError):
        await service.submit_request(data)


# ---------------------------------------------------------------------------
# get_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_request_returns_read():
    """Возвращает RegistrationRequestRead для существующей заявки."""
    request = make_request_mock()

    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(return_value=request)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    result = await service.get_request(request.id)
    assert isinstance(result, RegistrationRequestRead)
    assert result.id == request.id


@pytest.mark.asyncio
async def test_get_request_not_found_raises_service_error():
    """Вызывает ServiceError, когда заявка не найдена."""
    from database import DatabaseError

    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(
        side_effect=DatabaseError("not found")
    )

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_request(uuid.uuid4())


# ---------------------------------------------------------------------------
# approve_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_request_success():
    """Одобряет ожидающую заявку и возвращает RegistrationDecisionResponse."""
    reviewer_id = uuid.uuid4()
    user_mock = make_user_mock()
    request = make_request_mock()
    approved_request = make_request_mock(
        request_id=request.id,
        status=RegistrationRequestStatus.APPROVED,
        reviewed_by=reviewer_id,
        created_user_id=user_mock.id,
    )

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user_mock)
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=False)
    users_repo.create_user = AsyncMock(return_value=user_mock)

    roles_repo = AsyncMock()
    role_mock = MagicMock()
    role_mock.id = uuid.uuid4()
    roles_repo.get_required_user_role_model = AsyncMock(return_value=role_mock)
    roles_repo.assign_role = AsyncMock()

    quotas_repo = AsyncMock()
    quotas_repo.create_default_quota = AsyncMock()

    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(return_value=request)
    reg_repo.approve_request = AsyncMock(return_value=approved_request)

    uow = make_uow_mock(
        users=users_repo,
        roles=roles_repo,
        quotas=quotas_repo,
        registration_requests=reg_repo,
    )
    service = make_service(uow)

    data = RegistrationApproveRequest(comment="Approved", is_email_verified=True)
    result = await service.approve_request(request.id, data, reviewed_by=reviewer_id)

    assert isinstance(result, RegistrationDecisionResponse)
    assert result.created_user_id == user_mock.id


# ---------------------------------------------------------------------------
# reject_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_request_success():
    """Отклоняет ожидающую заявку и возвращает RegistrationDecisionResponse."""
    reviewer_id = uuid.uuid4()
    request = make_request_mock()
    rejected_request = make_request_mock(
        request_id=request.id,
        status=RegistrationRequestStatus.REJECTED,
        reviewed_by=reviewer_id,
    )

    reviewer_mock = make_user_mock(user_id=reviewer_id)

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=reviewer_mock)

    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(return_value=request)
    reg_repo.reject_request = AsyncMock(return_value=rejected_request)

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationRejectRequest(
        rejection_reason="Policy violation",
        comment="Rejected",
    )
    result = await service.reject_request(request.id, data, reviewed_by=reviewer_id)

    assert isinstance(result, RegistrationDecisionResponse)
    reg_repo.reject_request.assert_awaited_once()


# ---------------------------------------------------------------------------
# cancel_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_request_success():
    """Отменяет ожидающую заявку и возвращает RegistrationDecisionResponse."""
    request = make_request_mock()
    cancelled_request = make_request_mock(
        request_id=request.id,
        status=RegistrationRequestStatus.CANCELLED,
    )

    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(return_value=request)
    reg_repo.cancel_request = AsyncMock(return_value=cancelled_request)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationCancelRequest(reason="Changed mind")
    result = await service.cancel_request(request.id, data)

    assert isinstance(result, RegistrationDecisionResponse)
    reg_repo.cancel_request.assert_awaited_once()


# ---------------------------------------------------------------------------
# list_requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_requests_returns_page():
    """Возвращает постраничный список заявок на регистрацию."""
    requests = [make_request_mock() for _ in range(3)]

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(return_value=requests)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(limit=10, offset=0)
    result = await service.list_requests(params)

    assert result.meta.total == 3
    assert result.meta.count == 3
    assert len(result.items) == 3


@pytest.mark.asyncio
async def test_list_requests_invalid_limit_raises_validation_error():
    """Вызывает ValidationServiceError, когда limit вне диапазона."""
    uow = make_uow_mock()
    service = make_service(uow)

    params = RegistrationQueryParams.model_construct(limit=0, offset=0)
    with pytest.raises(ValidationServiceError):
        await service.list_requests(params)


@pytest.mark.asyncio
async def test_list_requests_negative_offset_raises_validation_error():
    """Вызывает ValidationServiceError, когда offset отрицателен."""
    uow = make_uow_mock()
    service = make_service(uow)

    params = RegistrationQueryParams.model_construct(limit=10, offset=-1)
    with pytest.raises(ValidationServiceError):
        await service.list_requests(params)


# ---------------------------------------------------------------------------
# count_pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_pending_returns_count():
    """Возвращает количество ожидающих заявок на регистрацию."""
    reg_repo = AsyncMock()
    reg_repo.count_pending = AsyncMock(return_value=5)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    result = await service.count_pending()
    assert result == 5


# ---------------------------------------------------------------------------
# has_pending_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_pending_request_true():
    """Возвращает True, когда есть ожидающая заявка."""
    pending_mock = make_request_mock()

    reg_repo = AsyncMock()
    reg_repo.get_pending_by_email_or_username = AsyncMock(return_value=pending_mock)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    result = await service.has_pending_request(
        email="newuser@example.com", username="newuser"
    )
    assert result is True


@pytest.mark.asyncio
async def test_has_pending_request_false():
    """Возвращает False, когда нет ожидающей заявки."""
    reg_repo = AsyncMock()
    reg_repo.get_pending_by_email_or_username = AsyncMock(return_value=None)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    result = await service.has_pending_request(
        email="newuser@example.com", username="newuser"
    )
    assert result is False


# ---------------------------------------------------------------------------
# submit_request — оборачивание ошибок
# ---------------------------------------------------------------------------


def _make_submit_data():
    from schemas.registration import RegistrationRequestCreate

    return RegistrationRequestCreate(
        email="newuser@example.com",
        username="newuser",
        password="StrongPass123!",
    )


@pytest.mark.asyncio
async def test_submit_request_logs_audit_event():
    """Логирует системное событие аудита после успешной отправки заявки."""
    request = make_request_mock()

    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=False)

    reg_repo = AsyncMock()
    reg_repo.create_request = AsyncMock(return_value=request)

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    audit = make_audit_service()
    service = make_service(uow, audit)

    await service.submit_request(_make_submit_data())

    audit.log_system_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_request_database_error_wrapped():
    """Оборачивает DatabaseError в ServiceError."""
    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=False)

    reg_repo = AsyncMock()
    reg_repo.create_request = AsyncMock(side_effect=DatabaseError("db down"))

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.submit_request(_make_submit_data())


@pytest.mark.asyncio
async def test_submit_request_unexpected_error_wrapped():
    """Оборачивает непредвиденное исключение в ServiceError."""
    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=False)

    reg_repo = AsyncMock()
    reg_repo.create_request = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.submit_request(_make_submit_data())


@pytest.mark.asyncio
async def test_submit_request_value_error_inside_uow_wrapped_as_validation():
    """ValueError внутри UoW преобразуется в ValidationServiceError.

    Пароль хешируется до try-блока, поэтому чтобы задействовать обработчик
    ValueError внутри блока, мы заставляем вызов репозитория бросить ValueError."""
    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=False)

    reg_repo = AsyncMock()
    reg_repo.create_request = AsyncMock(side_effect=ValueError("bad value"))

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.submit_request(_make_submit_data())


# ---------------------------------------------------------------------------
# get_request — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_request_unexpected_error_wrapped():
    """Оборачивает непредвиденную ошибку в get_request в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_request(uuid.uuid4())


# ---------------------------------------------------------------------------
# approve_request — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_request_database_error_wrapped():
    """Оборачивает DatabaseError при одобрении в ServiceError."""
    reviewer_id = uuid.uuid4()
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(
        side_effect=DatabaseError("reviewer missing")
    )

    reg_repo = AsyncMock()
    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationApproveRequest(comment="ok", is_email_verified=True)
    with pytest.raises(ServiceError):
        await service.approve_request(uuid.uuid4(), data, reviewed_by=reviewer_id)


@pytest.mark.asyncio
async def test_approve_request_conflict_propagates():
    """ConflictServiceError из повторной проверки идентичности пробрасывается без изменений."""
    reviewer_id = uuid.uuid4()
    user_mock = make_user_mock()
    request = make_request_mock()

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user_mock)
    users_repo.email_exists = AsyncMock(return_value=True)
    users_repo.username_exists = AsyncMock(return_value=False)

    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(return_value=request)

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationApproveRequest(comment="ok", is_email_verified=True)
    with pytest.raises(ConflictServiceError):
        await service.approve_request(request.id, data, reviewed_by=reviewer_id)


@pytest.mark.asyncio
async def test_approve_request_unexpected_error_wrapped():
    """Оборачивает непредвиденную ошибку при одобрении в ServiceError."""
    reviewer_id = uuid.uuid4()
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("boom"))

    reg_repo = AsyncMock()
    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationApproveRequest(comment="ok", is_email_verified=True)
    with pytest.raises(ServiceError):
        await service.approve_request(uuid.uuid4(), data, reviewed_by=reviewer_id)


# ---------------------------------------------------------------------------
# reject_request — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_request_database_error_wrapped():
    """Оборачивает DatabaseError при отклонении в ServiceError."""
    reviewer_id = uuid.uuid4()
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(
        side_effect=DatabaseError("reviewer missing")
    )

    reg_repo = AsyncMock()
    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationRejectRequest(rejection_reason="nope", comment="c")
    with pytest.raises(ServiceError):
        await service.reject_request(uuid.uuid4(), data, reviewed_by=reviewer_id)


@pytest.mark.asyncio
async def test_reject_request_unexpected_error_wrapped():
    """Оборачивает непредвиденную ошибку при отклонении в ServiceError."""
    reviewer_id = uuid.uuid4()
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("boom"))

    reg_repo = AsyncMock()
    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationRejectRequest(rejection_reason="nope", comment="c")
    with pytest.raises(ServiceError):
        await service.reject_request(uuid.uuid4(), data, reviewed_by=reviewer_id)


# ---------------------------------------------------------------------------
# cancel_request — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_request_database_error_wrapped():
    """Оборачивает DatabaseError при отмене в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(
        side_effect=DatabaseError("not found")
    )

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationCancelRequest(reason="changed mind")
    with pytest.raises(ServiceError):
        await service.cancel_request(uuid.uuid4(), data)


@pytest.mark.asyncio
async def test_cancel_request_unexpected_error_wrapped():
    """Оборачивает непредвиденную ошибку при отмене в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationCancelRequest(reason="changed mind")
    with pytest.raises(ServiceError):
        await service.cancel_request(uuid.uuid4(), data)


# ---------------------------------------------------------------------------
# list_requests — ветки, оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_requests_search_branch():
    """Использует search_requests, когда задана строка поиска."""
    requests = [make_request_mock(username=f"user{i}") for i in range(2)]

    reg_repo = AsyncMock()
    reg_repo.search_requests = AsyncMock(return_value=requests)
    reg_repo.list_requests = AsyncMock(return_value=[])

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(limit=10, offset=0, query="user")
    result = await service.list_requests(params)

    reg_repo.search_requests.assert_awaited()
    reg_repo.list_requests.assert_not_awaited()
    assert result.meta.total == 2


@pytest.mark.asyncio
async def test_list_requests_paginates_repository_batches():
    """Загружает несколько пакетов из репозитория, когда возвращается полная страница."""
    from services import registration as reg_module

    full_batch = [make_request_mock() for _ in range(reg_module.REPOSITORY_PAGE_LIMIT)]
    tail_batch = [make_request_mock()]

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(side_effect=[full_batch, tail_batch])

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(limit=10, offset=0)
    result = await service.list_requests(params)

    assert reg_repo.list_requests.await_count == 2
    assert result.meta.total == reg_module.REPOSITORY_PAGE_LIMIT + 1


@pytest.mark.asyncio
async def test_list_requests_filters_by_reviewed_by():
    """Применяет фильтр reviewed_by к загруженным снимкам."""
    reviewer_id = uuid.uuid4()
    matching = make_request_mock(reviewed_by=reviewer_id)
    other = make_request_mock(reviewed_by=uuid.uuid4())

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(return_value=[matching, other])

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(limit=10, offset=0, reviewed_by=reviewer_id)
    result = await service.list_requests(params)

    assert result.meta.total == 1
    assert result.items[0].id == matching.id


@pytest.mark.asyncio
async def test_list_requests_filters_by_created_range():
    """Отфильтровывает заявки, чей created_at вне заданного диапазона."""
    now = datetime.now(UTC)
    inside = make_request_mock()
    inside.created_at = now
    outside = make_request_mock()
    outside.created_at = now - timedelta(days=10)

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(return_value=[inside, outside])

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(
        limit=10,
        offset=0,
        created_from=now - timedelta(days=1),
        created_to=now + timedelta(days=1),
    )
    result = await service.list_requests(params)

    assert result.meta.total == 1
    assert result.items[0].id == inside.id


@pytest.mark.asyncio
async def test_list_requests_filters_by_reviewed_range():
    """Фильтрует по диапазону reviewed_at, отбрасывая заявки без рассмотрения."""
    now = datetime.now(UTC)
    reviewed = make_request_mock(
        status=RegistrationRequestStatus.APPROVED,
        reviewed_at=now,
        reviewed_by=uuid.uuid4(),
    )
    not_reviewed = make_request_mock()
    not_reviewed.reviewed_at = None

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(return_value=[reviewed, not_reviewed])

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(
        limit=10,
        offset=0,
        reviewed_from=now - timedelta(days=1),
        reviewed_to=now + timedelta(days=1),
    )
    result = await service.list_requests(params)

    assert result.meta.total == 1
    assert result.items[0].id == reviewed.id


@pytest.mark.asyncio
async def test_list_requests_sort_by_unknown_field_falls_back():
    """Откатывается к created_at, когда sort_by не является поддерживаемым полем."""
    requests = [make_request_mock() for _ in range(2)]

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(return_value=requests)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams.model_construct(
        limit=10,
        offset=0,
        query=None,
        status=None,
        reviewed_by=None,
        created_from=None,
        created_to=None,
        reviewed_from=None,
        reviewed_to=None,
        sort_by="not_a_real_field",
        sort_desc=False,
    )
    result = await service.list_requests(params)

    assert result.meta.total == 2


@pytest.mark.asyncio
async def test_list_requests_with_status_filter():
    """Передаёт статус списком в репозиторий, когда он задан."""
    requests = [make_request_mock(status=RegistrationRequestStatus.APPROVED)]

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(return_value=requests)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(
        limit=10, offset=0, status=RegistrationRequestStatus.APPROVED
    )
    await service.list_requests(params)

    _, kwargs = reg_repo.list_requests.await_args
    assert kwargs["statuses"] == [RegistrationRequestStatus.APPROVED]


@pytest.mark.asyncio
async def test_list_requests_database_error_wrapped():
    """Оборачивает DatabaseError при получении списка в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(side_effect=DatabaseError("db down"))

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(limit=10, offset=0)
    with pytest.raises(ServiceError):
        await service.list_requests(params)


@pytest.mark.asyncio
async def test_list_requests_unexpected_error_wrapped():
    """Оборачивает непредвиденную ошибку при получении списка в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(limit=10, offset=0)
    with pytest.raises(ServiceError):
        await service.list_requests(params)


# ---------------------------------------------------------------------------
# count_pending — оборачивание ошибок / результат None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_pending_none_result_raises_service_error():
    """Вызывает ServiceError, когда репозиторий возвращает None."""
    reg_repo = AsyncMock()
    reg_repo.count_pending = AsyncMock(return_value=None)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.count_pending()


@pytest.mark.asyncio
async def test_count_pending_database_error_wrapped():
    """Оборачивает DatabaseError из count_pending в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.count_pending = AsyncMock(side_effect=DatabaseError("db down"))

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.count_pending()


@pytest.mark.asyncio
async def test_count_pending_unexpected_error_wrapped():
    """Оборачивает непредвиденную ошибку из count_pending в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.count_pending = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.count_pending()


# ---------------------------------------------------------------------------
# get_status_counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_counts_returns_counts():
    """Возвращает отображение статус-количество из репозитория."""
    counts = {
        RegistrationRequestStatus.PENDING: 3,
        RegistrationRequestStatus.APPROVED: 1,
    }

    reg_repo = AsyncMock()
    reg_repo.get_status_counts = AsyncMock(return_value=counts)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    result = await service.get_status_counts()
    assert result == counts


@pytest.mark.asyncio
async def test_get_status_counts_none_result_raises_service_error():
    """Вызывает ServiceError, когда репозиторий возвращает None."""
    reg_repo = AsyncMock()
    reg_repo.get_status_counts = AsyncMock(return_value=None)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_status_counts()


@pytest.mark.asyncio
async def test_get_status_counts_database_error_wrapped():
    """Оборачивает DatabaseError из get_status_counts в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.get_status_counts = AsyncMock(side_effect=DatabaseError("db down"))

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_status_counts()


@pytest.mark.asyncio
async def test_get_status_counts_unexpected_error_wrapped():
    """Оборачивает непредвиденную ошибку из get_status_counts в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.get_status_counts = AsyncMock(side_effect=RuntimeError("boom"))

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_status_counts()


# ---------------------------------------------------------------------------
# has_pending_request — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_pending_request_database_error_wrapped():
    """Оборачивает DatabaseError из has_pending_request в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.get_pending_by_email_or_username = AsyncMock(
        side_effect=DatabaseError("db down")
    )

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.has_pending_request(email="a@b.com", username="a")


@pytest.mark.asyncio
async def test_has_pending_request_unexpected_error_wrapped():
    """Оборачивает непредвиденную ошибку из has_pending_request в ServiceError."""
    reg_repo = AsyncMock()
    reg_repo.get_pending_by_email_or_username = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.has_pending_request(email="a@b.com", username="a")


# ---------------------------------------------------------------------------
# устойчивость к сбою аудита + нормализация наивного datetime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_request_audit_failure_is_swallowed():
    """Сбой записи аудита не ломает успешную отправку заявки."""
    request = make_request_mock()

    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=False)

    reg_repo = AsyncMock()
    reg_repo.create_request = AsyncMock(return_value=request)

    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    audit = make_audit_service()
    audit.log_system_event = AsyncMock(side_effect=RuntimeError("audit down"))
    service = make_service(uow, audit)

    result = await service.submit_request(_make_submit_data())
    assert isinstance(result, RegistrationRequestRead)


@pytest.mark.asyncio
async def test_approve_request_audit_failure_is_swallowed():
    """Сбой записи пользовательского события аудита не ломает одобрение."""
    reviewer_id = uuid.uuid4()
    user_mock = make_user_mock()
    request = make_request_mock()
    approved_request = make_request_mock(
        request_id=request.id,
        status=RegistrationRequestStatus.APPROVED,
        reviewed_by=reviewer_id,
        created_user_id=user_mock.id,
    )

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user_mock)
    users_repo.email_exists = AsyncMock(return_value=False)
    users_repo.username_exists = AsyncMock(return_value=False)
    users_repo.create_user = AsyncMock(return_value=user_mock)

    roles_repo = AsyncMock()
    role_mock = MagicMock()
    role_mock.id = uuid.uuid4()
    roles_repo.get_required_user_role_model = AsyncMock(return_value=role_mock)
    roles_repo.assign_role = AsyncMock()

    quotas_repo = AsyncMock()
    quotas_repo.create_default_quota = AsyncMock()

    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(return_value=request)
    reg_repo.approve_request = AsyncMock(return_value=approved_request)

    uow = make_uow_mock(
        users=users_repo,
        roles=roles_repo,
        quotas=quotas_repo,
        registration_requests=reg_repo,
    )
    audit = make_audit_service()
    audit.log_user_event = AsyncMock(side_effect=RuntimeError("audit down"))
    service = make_service(uow, audit)

    data = RegistrationApproveRequest(comment="ok", is_email_verified=True)
    result = await service.approve_request(request.id, data, reviewed_by=reviewer_id)
    assert isinstance(result, RegistrationDecisionResponse)


@pytest.mark.asyncio
async def test_list_requests_normalizes_naive_datetimes():
    """Наивные значения created_at нормализуются в UTC для фильтрации по диапазону."""
    naive_now = datetime.now()  # noqa: DTZ005 - намеренно наивный
    inside = make_request_mock()
    inside.created_at = naive_now

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(return_value=[inside])

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(
        limit=10,
        offset=0,
        created_from=datetime.now(UTC) - timedelta(days=1),
        created_to=datetime.now(UTC) + timedelta(days=1),
    )
    result = await service.list_requests(params)

    assert result.meta.total == 1


@pytest.mark.asyncio
async def test_list_requests_non_datetime_value_excluded_by_range():
    """Значение created_at не типа datetime исключается, если задана граница диапазона."""
    bad = make_request_mock()
    bad.created_at = None

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(return_value=[bad])

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(
        limit=10,
        offset=0,
        created_from=datetime.now(UTC) - timedelta(days=1),
    )
    result = await service.list_requests(params)

    assert result.meta.total == 0


# ---------------------------------------------------------------------------
# фабрика
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_requests_excludes_created_after_upper_bound():
    """Исключает заявку, чей created_at позже границы created_to."""
    now = datetime.now(UTC)
    too_new = make_request_mock()
    too_new.created_at = now + timedelta(days=5)

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(return_value=[too_new])

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(
        limit=10,
        offset=0,
        created_to=now,
    )
    result = await service.list_requests(params)

    assert result.meta.total == 0


# ---------------------------------------------------------------------------
# Проброс ServiceError без оборачивания
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_request_service_error_propagates():
    """ServiceError, возникший внутри UoW, пробрасывается без изменений."""
    inner = ServiceError("boom", service="registration", operation="x")

    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(side_effect=inner)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_request(uuid.uuid4())
    assert exc_info.value is inner


@pytest.mark.asyncio
async def test_list_requests_service_error_propagates():
    """ServiceError, возникший при получении списка, пробрасывается без изменений."""
    inner = ServiceError("boom", service="registration", operation="x")

    reg_repo = AsyncMock()
    reg_repo.list_requests = AsyncMock(side_effect=inner)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    params = RegistrationQueryParams(limit=10, offset=0)
    with pytest.raises(ServiceError) as exc_info:
        await service.list_requests(params)
    assert exc_info.value is inner


@pytest.mark.asyncio
async def test_reject_request_service_error_propagates():
    """ServiceError, возникший при отклонении, пробрасывается без изменений."""
    inner = ServiceError("boom", service="registration", operation="x")

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=inner)

    reg_repo = AsyncMock()
    uow = make_uow_mock(users=users_repo, registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationRejectRequest(rejection_reason="nope", comment="c")
    with pytest.raises(ServiceError) as exc_info:
        await service.reject_request(uuid.uuid4(), data, reviewed_by=uuid.uuid4())
    assert exc_info.value is inner


@pytest.mark.asyncio
async def test_cancel_request_service_error_propagates():
    """ServiceError, возникший при отмене, пробрасывается без изменений."""
    inner = ServiceError("boom", service="registration", operation="x")

    reg_repo = AsyncMock()
    reg_repo.get_required_request_by_id = AsyncMock(side_effect=inner)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    data = RegistrationCancelRequest(reason="changed mind")
    with pytest.raises(ServiceError) as exc_info:
        await service.cancel_request(uuid.uuid4(), data)
    assert exc_info.value is inner


@pytest.mark.asyncio
async def test_has_pending_request_service_error_propagates():
    """ServiceError, возникший при проверке ожидающей заявки, пробрасывается без изменений."""
    inner = ServiceError("boom", service="registration", operation="x")

    reg_repo = AsyncMock()
    reg_repo.get_pending_by_email_or_username = AsyncMock(side_effect=inner)

    uow = make_uow_mock(registration_requests=reg_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError) as exc_info:
        await service.has_pending_request(email="a@b.com", username="a")
    assert exc_info.value is inner


def test_get_registration_service_uses_injected_dependencies():
    """Фабрика возвращает RegistrationService с внедрёнными зависимостями."""
    from services.registration import RegistrationService, get_registration_service

    uow = make_uow_mock()
    factory = make_uow_factory(uow)
    audit = make_audit_service()

    service = get_registration_service(uow_factory=factory, audit_service=audit)

    assert isinstance(service, RegistrationService)
    assert service.uow_factory is factory
    assert service.audit_service is audit
