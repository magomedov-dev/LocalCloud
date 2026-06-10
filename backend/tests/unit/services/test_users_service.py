"""Юнит-тесты для UsersService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.models.enums import UserStatus
from schemas.common import PageResponse
from schemas.users import (
    CurrentUserRead,
    UserAdminUpdate,
    UserBlockRequest,
    UserCreate,
    UserQueryParams,
    UserRead,
    UserRejectRequest,
    UserStatusUpdateRequest,
    UserUpdate,
    UserWithRolesRead,
)
from services.exceptions import (
    NotFoundServiceError,
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
)
from services.users import (
    UsersService,
    _audit_user,
    _matches_created_range,
    _role_list_item,
    get_users_service,
)
from tests.unit.services.conftest import make_uow_factory, make_uow_mock, make_user_mock

USER_ID = uuid.uuid4()


@pytest.fixture
def audit_service():
    svc = MagicMock()
    svc.log_user_event = AsyncMock()
    svc.log_system_event = AsyncMock()
    return svc


def _make_service(uow, audit_service):
    return UsersService(
        uow_factory=make_uow_factory(uow),
        audit_service=audit_service,
    )


def _make_user_snapshot(**kwargs) -> dict[str, Any]:
    base = {
        "id": USER_ID,
        "email": "user@example.com",
        "username": "testuser",
        "status": UserStatus.ACTIVE,
        "last_login_at": None,
        "approved_at": None,
        "blocked_at": None,
        "rejected_at": None,
        "deleted_at": None,
        "block_reason": None,
        "rejection_reason": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(kwargs)
    return base


def _make_role_mock(name: str = "user") -> MagicMock:
    """Вернуть мок, имитирующий ORM-модель Role для снимков ролей."""
    role = MagicMock()
    role.id = uuid.uuid4()
    role.name = name
    role.code = name
    role.display_name = name.capitalize()
    role.is_system = True
    role.is_active = True
    return role


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_success(audit_service):
    """create_user создаёт пользователя и назначает роль по умолчанию."""
    user = make_user_mock(user_id=USER_ID, email="new@example.com", username="newuser")

    role = MagicMock()
    role.id = uuid.uuid4()

    users_repo = AsyncMock()
    users_repo.create_user = AsyncMock(return_value=user)

    roles_repo = AsyncMock()
    roles_repo.get_required_user_role_model = AsyncMock(return_value=role)
    roles_repo.assign_role = AsyncMock()

    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    service = _make_service(uow, audit_service)

    data = UserCreate(
        email="new@example.com",
        username="newuser",
        password="SecurePass123!",
    )
    result = await service.create_user(data)

    assert isinstance(result, UserRead)
    users_repo.create_user.assert_awaited_once()
    roles_repo.assign_role.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_user_weak_password_raises(audit_service):
    """create_user вызывает ValueError для слабого пароля до входа в UoW."""
    # Сервис вызывает _hash_password() до блока try/except, поэтому слабый
    # пароль приводит к пробросу ValueError без оборачивания.
    uow = make_uow_mock()
    service = _make_service(uow, audit_service)

    data = UserCreate(
        email="new@example.com",
        username="newuser",
        password="weakpass",  # 8 символов, все строчные — не проходит require_strong_password
    )
    with pytest.raises(ValueError):
        await service.create_user(data)


@pytest.mark.asyncio
async def test_create_user_without_default_role(audit_service):
    """create_user с assign_default_role=False пропускает назначение роли."""
    user = make_user_mock(user_id=USER_ID, email="new@example.com", username="newuser")

    roles_repo = AsyncMock()
    roles_repo.get_required_user_role_model = AsyncMock()
    roles_repo.assign_role = AsyncMock()

    users_repo = AsyncMock()
    users_repo.create_user = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    service = _make_service(uow, audit_service)

    data = UserCreate(
        email="new@example.com",
        username="newuser",
        password="SecurePass123!",
    )
    result = await service.create_user(data, assign_default_role=False)

    assert isinstance(result, UserRead)
    roles_repo.get_required_user_role_model.assert_not_awaited()
    roles_repo.assign_role.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_success(audit_service):
    """get_user возвращает UserRead для найденного пользователя."""
    user = make_user_mock(user_id=USER_ID)

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.get_user(USER_ID)
    assert isinstance(result, UserRead)
    assert result.id == USER_ID


@pytest.mark.asyncio
async def test_get_user_not_found_wraps_in_service_error(audit_service):
    """get_user оборачивает EntityNotFoundError из репозитория в ServiceError."""
    from database.exceptions import EntityNotFoundError

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(
        side_effect=EntityNotFoundError("User not found")
    )

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_user(USER_ID)


# ---------------------------------------------------------------------------
# update_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_user_no_changes_returns_current_user(audit_service):
    """update_user с пустыми данными возвращает текущего пользователя без записи в БД."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserUpdate()  # поля не заданы
    result = await service.update_user(USER_ID, data)

    assert isinstance(result, UserRead)
    # update_identity_by_id НЕ должен вызываться
    assert not hasattr(users_repo, "update_identity_by_id") or \
        users_repo.update_identity_by_id.await_count == 0


@pytest.mark.asyncio
async def test_update_user_with_email(audit_service):
    """update_user с новым email вызывает update_identity_by_id."""
    user = make_user_mock(user_id=USER_ID, email="updated@example.com")
    users_repo = AsyncMock()
    users_repo.update_identity_by_id = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserUpdate(email="updated@example.com")  # type: ignore[arg-type]
    result = await service.update_user(USER_ID, data)

    assert isinstance(result, UserRead)
    users_repo.update_identity_by_id.assert_awaited_once()


# ---------------------------------------------------------------------------
# change_password
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_success(audit_service):
    """change_password хеширует и сохраняет новый надёжный пароль."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.update_password_hash_by_id = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.change_password(USER_ID, "NewSecurePass99!")
    assert isinstance(result, UserRead)
    users_repo.update_password_hash_by_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_password_weak_raises(audit_service):
    """change_password вызывает ValidationServiceError для слабого пароля."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service)

    # _hash_password вызывается до блока try/except, поэтому ValueError
    # пробрасывается напрямую, без оборачивания в ValidationServiceError
    with pytest.raises(ValueError):
        await service.change_password(USER_ID, "123")


# ---------------------------------------------------------------------------
# delete_user / approve_user / block_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_user_soft_deletes(audit_service):
    """delete_user помечает пользователя удалённым через mark_deleted."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.DELETED)

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.mark_deleted = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo)
    uow.flush_and_refresh = AsyncMock(return_value=user)
    service = _make_service(uow, audit_service)

    result = await service.delete_user(USER_ID)
    assert isinstance(result, UserRead)
    users_repo.mark_deleted.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_user_rejects_self(audit_service):
    """delete_user запрещает администратору удалять самого себя."""
    users_repo = AsyncMock()
    users_repo.mark_deleted = AsyncMock()

    uow = make_uow_mock(users=users_repo, roles=AsyncMock())
    service = _make_service(uow, audit_service)

    with pytest.raises(PermissionServiceError) as exc_info:
        await service.delete_user(USER_ID, actor_id=USER_ID)

    assert exc_info.value.status_code == 403
    assert exc_info.value.details.get("reason") == "cannot_delete_self"
    users_repo.mark_deleted.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_user_rejects_first_admin(audit_service):
    """delete_user запрещает удаление учётной записи первичного администратора."""
    users_repo = AsyncMock()
    users_repo.mark_deleted = AsyncMock()

    roles_repo = AsyncMock()
    roles_repo.get_first_admin_user_id = AsyncMock(return_value=USER_ID)

    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(PermissionServiceError) as exc_info:
        await service.delete_user(USER_ID, actor_id=uuid.uuid4())

    assert exc_info.value.status_code == 403
    assert exc_info.value.details.get("reason") == "cannot_delete_first_admin"
    users_repo.mark_deleted.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_user_allows_other_non_primary(audit_service):
    """delete_user удаляет обычного пользователя другим администратором."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.DELETED)

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.mark_deleted = AsyncMock(return_value=user)

    roles_repo = AsyncMock()
    roles_repo.get_first_admin_user_id = AsyncMock(return_value=uuid.uuid4())

    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    uow.flush_and_refresh = AsyncMock(return_value=user)
    service = _make_service(uow, audit_service)

    result = await service.delete_user(USER_ID, actor_id=uuid.uuid4())
    assert isinstance(result, UserRead)
    users_repo.mark_deleted.assert_awaited_once()


@pytest.mark.asyncio
async def test_block_user_updates_status(audit_service):
    """block_user вызывает mark_blocked у пользователя."""

    user = make_user_mock(user_id=USER_ID, status=UserStatus.BLOCKED)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.mark_blocked = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo)
    uow.flush_and_refresh = AsyncMock(return_value=user)
    service = _make_service(uow, audit_service)

    block_data = UserBlockRequest(reason="Violated ToS")
    result = await service.block_user(USER_ID, block_data)
    assert isinstance(result, UserRead)
    users_repo.mark_blocked.assert_awaited_once()


# ---------------------------------------------------------------------------
# email_exists / username_exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_exists_returns_true(audit_service):
    """email_exists возвращает True, когда email занят."""
    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(return_value=True)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.email_exists("taken@example.com")
    assert result is True


@pytest.mark.asyncio
async def test_username_exists_returns_false(audit_service):
    """username_exists возвращает False, когда имя пользователя свободно."""
    users_repo = AsyncMock()
    users_repo.username_exists = AsyncMock(return_value=False)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.username_exists("freeuser")
    assert result is False


# ---------------------------------------------------------------------------
# валидация пагинации list_users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_negative_offset_raises(audit_service):
    """list_users вызывает ValidationServiceError для отрицательного offset."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service)

    # Обходим валидацию схемы Pydantic, чтобы передать сервису некорректные параметры
    params = UserQueryParams.model_construct(offset=-1, limit=10)
    with pytest.raises(ValidationServiceError) as exc_info:
        await service.list_users(params)

    assert exc_info.value.details.get("field") == "offset"


@pytest.mark.asyncio
async def test_list_users_invalid_limit_raises(audit_service):
    """list_users вызывает ValidationServiceError для limit=0."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service)

    # Обходим валидацию схемы Pydantic, чтобы передать сервису некорректные параметры
    params = UserQueryParams.model_construct(offset=0, limit=0)
    with pytest.raises(ValidationServiceError) as exc_info:
        await service.list_users(params)

    assert exc_info.value.details.get("field") == "limit"


@pytest.mark.asyncio
async def test_list_users_returns_page(audit_service):
    """list_users возвращает PageResponse с элементами."""
    user = make_user_mock(user_id=USER_ID)

    users_repo = AsyncMock()
    users_repo.list_users = AsyncMock(return_value=[user])

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    params = UserQueryParams(offset=0, limit=10)
    page = await service.list_users(params)

    assert page.meta.total == 1
    assert len(page.items) == 1


# ---------------------------------------------------------------------------
# get_status_counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_counts_returns_dict(audit_service):
    """get_status_counts возвращает словарь со всеми ключами UserStatus."""
    counts = {UserStatus.ACTIVE: 5, UserStatus.PENDING: 2}
    users_repo = AsyncMock()
    users_repo.get_status_counts = AsyncMock(return_value=counts)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.get_status_counts()
    assert result[UserStatus.ACTIVE] == 5
    assert result[UserStatus.PENDING] == 2
    # Отсутствующие статусы по умолчанию равны 0
    assert result[UserStatus.BLOCKED] == 0


# ---------------------------------------------------------------------------
# проброс ошибки базы данных
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_database_error_propagates(audit_service):
    """DatabaseError из get_required_user_by_id оборачивается в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=DBError("connection lost"))

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_user(USER_ID)


# ---------------------------------------------------------------------------
# оборачивание ошибок create_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_database_error_wraps(audit_service):
    """create_user оборачивает DatabaseError из репозитория в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.create_user = AsyncMock(side_effect=DBError("dup"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserCreate(email="a@example.com", username="auser", password="SecurePass123!")
    with pytest.raises(ServiceError):
        await service.create_user(data)


@pytest.mark.asyncio
async def test_create_user_unexpected_error_wraps(audit_service):
    """create_user оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.create_user = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserCreate(email="a@example.com", username="auser", password="SecurePass123!")
    with pytest.raises(ServiceError):
        await service.create_user(data)


@pytest.mark.asyncio
async def test_create_user_system_audit_when_no_actor(audit_service):
    """create_user логирует системное событие аудита, когда actor_id равен None."""
    user = make_user_mock(user_id=USER_ID)
    role = _make_role_mock()
    users_repo = AsyncMock()
    users_repo.create_user = AsyncMock(return_value=user)
    roles_repo = AsyncMock()
    roles_repo.get_required_user_role_model = AsyncMock(return_value=role)
    roles_repo.assign_role = AsyncMock()
    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    service = _make_service(uow, audit_service)

    data = UserCreate(email="a@example.com", username="auser", password="SecurePass123!")
    await service.create_user(data, actor_id=None)

    audit_service.log_system_event.assert_awaited_once()
    audit_service.log_user_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_user_user_audit_when_actor(audit_service):
    """create_user логирует пользовательское событие аудита, когда задан actor_id."""
    actor = uuid.uuid4()
    user = make_user_mock(user_id=USER_ID)
    role = _make_role_mock()
    users_repo = AsyncMock()
    users_repo.create_user = AsyncMock(return_value=user)
    roles_repo = AsyncMock()
    roles_repo.get_required_user_role_model = AsyncMock(return_value=role)
    roles_repo.assign_role = AsyncMock()
    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    service = _make_service(uow, audit_service)

    data = UserCreate(email="a@example.com", username="auser", password="SecurePass123!")
    await service.create_user(data, actor_id=actor)

    audit_service.log_user_event.assert_awaited_once()
    audit_service.log_system_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_user_audit_failure_is_swallowed(audit_service):
    """Сбой аудита во время create_user не пробрасывается."""
    user = make_user_mock(user_id=USER_ID)
    role = _make_role_mock()
    users_repo = AsyncMock()
    users_repo.create_user = AsyncMock(return_value=user)
    roles_repo = AsyncMock()
    roles_repo.get_required_user_role_model = AsyncMock(return_value=role)
    roles_repo.assign_role = AsyncMock()
    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    audit_service.log_system_event = AsyncMock(side_effect=RuntimeError("audit down"))
    service = _make_service(uow, audit_service)

    data = UserCreate(email="a@example.com", username="auser", password="SecurePass123!")
    result = await service.create_user(data)
    assert isinstance(result, UserRead)


# ---------------------------------------------------------------------------
# get_user_with_roles / get_current_user_read / по email / по username
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_with_roles_success(audit_service):
    """get_user_with_roles возвращает пользователя вместе с ролями."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    roles_repo = AsyncMock()
    roles_repo.get_user_roles = AsyncMock(return_value=[_make_role_mock("admin")])
    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    service = _make_service(uow, audit_service)

    result = await service.get_user_with_roles(USER_ID)
    assert isinstance(result, UserWithRolesRead)
    assert len(result.roles) == 1


@pytest.mark.asyncio
async def test_get_user_with_roles_database_error(audit_service):
    """get_user_with_roles оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo, roles=AsyncMock())
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_user_with_roles(USER_ID)


@pytest.mark.asyncio
async def test_get_user_with_roles_unexpected_error(audit_service):
    """get_user_with_roles оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo, roles=AsyncMock())
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_user_with_roles(USER_ID)


@pytest.mark.asyncio
async def test_get_current_user_read_success(audit_service):
    """get_current_user_read возвращает CurrentUserRead с активными ролями."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    roles_repo = AsyncMock()
    roles_repo.get_user_roles = AsyncMock(return_value=[_make_role_mock("user")])
    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    service = _make_service(uow, audit_service)

    result = await service.get_current_user_read(USER_ID)
    assert isinstance(result, CurrentUserRead)
    roles_repo.get_user_roles.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_current_user_read_database_error(audit_service):
    """get_current_user_read оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo, roles=AsyncMock())
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_current_user_read(USER_ID)


@pytest.mark.asyncio
async def test_get_current_user_read_unexpected_error(audit_service):
    """get_current_user_read оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo, roles=AsyncMock())
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_current_user_read(USER_ID)


@pytest.mark.asyncio
async def test_get_user_by_email_success(audit_service):
    """get_user_by_email возвращает UserRead."""
    user = make_user_mock(user_id=USER_ID, email="found@example.com")
    users_repo = AsyncMock()
    users_repo.get_required_by_email = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.get_user_by_email("found@example.com")
    assert isinstance(result, UserRead)


@pytest.mark.asyncio
async def test_get_user_by_email_not_found(audit_service):
    """get_user_by_email оборачивает EntityNotFoundError в NotFoundServiceError."""
    from database.exceptions import EntityNotFoundError

    users_repo = AsyncMock()
    users_repo.get_required_by_email = AsyncMock(
        side_effect=EntityNotFoundError("no user")
    )
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(NotFoundServiceError):
        await service.get_user_by_email("missing@example.com")


@pytest.mark.asyncio
async def test_get_user_by_email_unexpected_error(audit_service):
    """get_user_by_email оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_required_by_email = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_user_by_email("x@example.com")


@pytest.mark.asyncio
async def test_get_user_by_username_success(audit_service):
    """get_user_by_username возвращает UserRead."""
    user = make_user_mock(user_id=USER_ID, username="founduser")
    users_repo = AsyncMock()
    users_repo.get_required_by_username = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.get_user_by_username("founduser")
    assert isinstance(result, UserRead)


@pytest.mark.asyncio
async def test_get_user_by_username_database_error(audit_service):
    """get_user_by_username оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.get_required_by_username = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_user_by_username("u")


@pytest.mark.asyncio
async def test_get_user_by_username_unexpected_error(audit_service):
    """get_user_by_username оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_required_by_username = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_user_by_username("u")


# ---------------------------------------------------------------------------
# Путь ошибки _exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_exists_database_error(audit_service):
    """email_exists оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.email_exists = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.email_exists("x@example.com")


@pytest.mark.asyncio
async def test_username_exists_with_exclude(audit_service):
    """username_exists передаёт exclude_user_id в репозиторий."""
    users_repo = AsyncMock()
    users_repo.username_exists = AsyncMock(return_value=True)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.username_exists("u", exclude_user_id=USER_ID)
    assert result is True
    _, kwargs = users_repo.username_exists.call_args
    assert kwargs["exclude_user_id"] == USER_ID


# ---------------------------------------------------------------------------
# list_users: поиск, фильтрация, сортировка, ошибки
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_with_query_uses_search(audit_service):
    """list_users со строкой поиска вызывает search_users."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.search_users = AsyncMock(return_value=[user])
    users_repo.list_users = AsyncMock(return_value=[])
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    params = UserQueryParams(offset=0, limit=10, query="test")
    page = await service.list_users(params)

    assert isinstance(page, PageResponse)
    users_repo.search_users.assert_awaited_once()
    users_repo.list_users.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_users_filters_by_created_range(audit_service):
    """list_users исключает пользователей вне диапазона created_from/created_to."""
    old = make_user_mock(user_id=uuid.uuid4())
    old.created_at = datetime(2000, 1, 1, tzinfo=UTC)
    recent = make_user_mock(user_id=uuid.uuid4())
    recent.created_at = datetime(2024, 1, 1, tzinfo=UTC)

    users_repo = AsyncMock()
    users_repo.list_users = AsyncMock(return_value=[old, recent])
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    params = UserQueryParams(
        offset=0,
        limit=10,
        created_from=datetime(2023, 1, 1, tzinfo=UTC),
        created_to=datetime(2025, 1, 1, tzinfo=UTC),
    )
    page = await service.list_users(params)
    assert page.meta.total == 1


@pytest.mark.asyncio
async def test_list_users_sorts_by_username_desc(audit_service):
    """list_users сортирует снимки по запрошенному полю и направлению."""
    a = make_user_mock(user_id=uuid.uuid4(), username="alice")
    b = make_user_mock(user_id=uuid.uuid4(), username="bob")
    users_repo = AsyncMock()
    users_repo.list_users = AsyncMock(return_value=[a, b])
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    params = UserQueryParams(offset=0, limit=10, sort_by="username", sort_desc=True)
    page = await service.list_users(params)
    assert [item.username for item in page.items] == ["bob", "alice"]


@pytest.mark.asyncio
async def test_list_users_pagination_full_batch(audit_service):
    """list_users продолжает постранично читать, пока возвращается полный пакет REPOSITORY_PAGE_LIMIT."""
    import services.users as users_module

    monkey_limit = 2
    orig = users_module.REPOSITORY_PAGE_LIMIT
    users_module.REPOSITORY_PAGE_LIMIT = monkey_limit
    try:
        first = [make_user_mock(user_id=uuid.uuid4()) for _ in range(monkey_limit)]
        second = [make_user_mock(user_id=uuid.uuid4())]
        users_repo = AsyncMock()
        users_repo.list_users = AsyncMock(side_effect=[first, second])
        uow = make_uow_mock(users=users_repo)
        service = _make_service(uow, audit_service)

        params = UserQueryParams(offset=0, limit=100)
        page = await service.list_users(params)
        assert page.meta.total == 3
        assert users_repo.list_users.await_count == 2
    finally:
        users_module.REPOSITORY_PAGE_LIMIT = orig


@pytest.mark.asyncio
async def test_list_users_database_error(audit_service):
    """list_users оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.list_users = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    params = UserQueryParams(offset=0, limit=10)
    with pytest.raises(ServiceError):
        await service.list_users(params)


@pytest.mark.asyncio
async def test_list_users_unexpected_error(audit_service):
    """list_users оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.list_users = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    params = UserQueryParams(offset=0, limit=10)
    with pytest.raises(ServiceError):
        await service.list_users(params)


# ---------------------------------------------------------------------------
# пути ошибок update_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_user_database_error(audit_service):
    """update_user оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.update_identity_by_id = AsyncMock(side_effect=DBError("dup"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserUpdate(username="newname")
    with pytest.raises(ServiceError):
        await service.update_user(USER_ID, data)


@pytest.mark.asyncio
async def test_update_user_unexpected_error(audit_service):
    """update_user оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.update_identity_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserUpdate(username="newname")
    with pytest.raises(ServiceError):
        await service.update_user(USER_ID, data)


# ---------------------------------------------------------------------------
# admin_update_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_update_user_no_changes_returns_current(audit_service):
    """admin_update_user с пустой полезной нагрузкой возвращает текущего пользователя."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.admin_update_user(USER_ID, UserAdminUpdate())
    assert isinstance(result, UserRead)


@pytest.mark.asyncio
async def test_admin_update_user_all_fields(audit_service):
    """admin_update_user обновляет идентичность и статус."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.BLOCKED)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.update_identity = AsyncMock(return_value=user)
    users_repo.update_status = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserAdminUpdate(
        email="admin@example.com",  # type: ignore[arg-type]
        username="adminuser",
        status=UserStatus.BLOCKED,
        block_reason="abuse",
    )
    result = await service.admin_update_user(USER_ID, data, actor_id=uuid.uuid4())
    assert isinstance(result, UserRead)
    users_repo.update_identity.assert_awaited_once()
    users_repo.update_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_update_user_database_error(audit_service):
    """admin_update_user оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserAdminUpdate(username="adminuser")
    with pytest.raises(ServiceError):
        await service.admin_update_user(USER_ID, data)


@pytest.mark.asyncio
async def test_admin_update_user_unexpected_error(audit_service):
    """admin_update_user оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserAdminUpdate(username="adminuser")
    with pytest.raises(ServiceError):
        await service.admin_update_user(USER_ID, data)


# ---------------------------------------------------------------------------
# диспетчеризация update_status
# ---------------------------------------------------------------------------


def _status_service(audit_service, user):
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.mark_active = AsyncMock(return_value=user)
    users_repo.mark_blocked = AsyncMock(return_value=user)
    users_repo.mark_rejected = AsyncMock(return_value=user)
    users_repo.mark_deleted = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    uow.flush_and_refresh = AsyncMock(return_value=user)
    return _make_service(uow, audit_service), users_repo


@pytest.mark.asyncio
async def test_update_status_active_calls_approve(audit_service):
    """update_status с ACTIVE одобряет пользователя."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.ACTIVE)
    service, users_repo = _status_service(audit_service, user)

    data = UserStatusUpdateRequest(status=UserStatus.ACTIVE)
    result = await service.update_status(USER_ID, data)
    assert isinstance(result, UserRead)
    users_repo.mark_active.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_blocked_requires_reason(audit_service):
    """update_status с BLOCKED без причины вызывает ValidationServiceError."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service)

    data = UserStatusUpdateRequest(status=UserStatus.BLOCKED)
    with pytest.raises(ValidationServiceError) as exc_info:
        await service.update_status(USER_ID, data)
    assert exc_info.value.details.get("field") == "reason"


@pytest.mark.asyncio
async def test_update_status_blocked_with_reason(audit_service):
    """update_status с BLOCKED и причиной блокирует пользователя."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.BLOCKED)
    service, users_repo = _status_service(audit_service, user)

    data = UserStatusUpdateRequest(status=UserStatus.BLOCKED, reason="abuse")
    result = await service.update_status(USER_ID, data)
    assert isinstance(result, UserRead)
    users_repo.mark_blocked.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_rejected_requires_reason(audit_service):
    """update_status с REJECTED без причины вызывает ValidationServiceError."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service)

    data = UserStatusUpdateRequest(status=UserStatus.REJECTED)
    with pytest.raises(ValidationServiceError) as exc_info:
        await service.update_status(USER_ID, data)
    assert exc_info.value.details.get("field") == "reason"


@pytest.mark.asyncio
async def test_update_status_rejected_with_reason(audit_service):
    """update_status с REJECTED и причиной отклоняет пользователя."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.REJECTED)
    service, users_repo = _status_service(audit_service, user)

    data = UserStatusUpdateRequest(status=UserStatus.REJECTED, reason="spam")
    result = await service.update_status(USER_ID, data)
    assert isinstance(result, UserRead)
    users_repo.mark_rejected.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_deleted_calls_delete(audit_service):
    """update_status с DELETED мягко удаляет пользователя."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.DELETED)
    service, users_repo = _status_service(audit_service, user)

    data = UserStatusUpdateRequest(status=UserStatus.DELETED)
    result = await service.update_status(USER_ID, data)
    assert isinstance(result, UserRead)
    users_repo.mark_deleted.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_other_falls_back_to_admin_update(audit_service):
    """update_status с PENDING откатывается к admin_update_user."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.PENDING)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.update_status = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    data = UserStatusUpdateRequest(status=UserStatus.PENDING)
    result = await service.update_status(USER_ID, data)
    assert isinstance(result, UserRead)
    users_repo.update_status.assert_awaited_once()


# ---------------------------------------------------------------------------
# пути mutate_status для approve / unblock / reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_user_marks_active(audit_service):
    """approve_user помечает пользователя активным."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.ACTIVE)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.mark_active = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    uow.flush_and_refresh = AsyncMock(return_value=user)
    service = _make_service(uow, audit_service)

    result = await service.approve_user(USER_ID)
    assert isinstance(result, UserRead)
    users_repo.mark_active.assert_awaited_once()


@pytest.mark.asyncio
async def test_unblock_user_calls_unblock(audit_service):
    """unblock_user вызывает unblock у репозитория."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.ACTIVE)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.unblock = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    uow.flush_and_refresh = AsyncMock(return_value=user)
    service = _make_service(uow, audit_service)

    result = await service.unblock_user(USER_ID, actor_id=uuid.uuid4())
    assert isinstance(result, UserRead)
    users_repo.unblock.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_user_calls_mark_rejected(audit_service):
    """reject_user вызывает mark_rejected с причиной."""
    user = make_user_mock(user_id=USER_ID, status=UserStatus.REJECTED)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.mark_rejected = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    uow.flush_and_refresh = AsyncMock(return_value=user)
    service = _make_service(uow, audit_service)

    result = await service.reject_user(USER_ID, UserRejectRequest(reason="spam"))
    assert isinstance(result, UserRead)
    users_repo.mark_rejected.assert_awaited_once()


@pytest.mark.asyncio
async def test_mutate_status_database_error(audit_service):
    """_mutate_status оборачивает DatabaseError из мутатора в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.mark_deleted = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.delete_user(USER_ID)


@pytest.mark.asyncio
async def test_mutate_status_unexpected_error(audit_service):
    """_mutate_status оборачивает непредвиденную ошибку из мутатора в ServiceError."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.mark_deleted = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.delete_user(USER_ID)


# ---------------------------------------------------------------------------
# пути ошибок change_password
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_database_error(audit_service):
    """change_password оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.update_password_hash_by_id = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.change_password(USER_ID, "NewSecurePass99!", actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_change_password_unexpected_error(audit_service):
    """change_password оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.update_password_hash_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.change_password(USER_ID, "NewSecurePass99!")


# ---------------------------------------------------------------------------
# mark_login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_login_success(audit_service):
    """mark_login обновляет last_login_at и возвращает UserRead."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.update_last_login_by_id = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    result = await service.mark_login(USER_ID)
    assert isinstance(result, UserRead)
    users_repo.update_last_login_by_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_login_database_error(audit_service):
    """mark_login оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.update_last_login_by_id = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.mark_login(USER_ID)


@pytest.mark.asyncio
async def test_mark_login_unexpected_error(audit_service):
    """mark_login оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.update_last_login_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.mark_login(USER_ID)


# ---------------------------------------------------------------------------
# ошибки get_status_counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_counts_database_error(audit_service):
    """get_status_counts оборачивает DatabaseError в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.get_status_counts = AsyncMock(side_effect=DBError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_status_counts()


@pytest.mark.asyncio
async def test_get_status_counts_unexpected_error(audit_service):
    """get_status_counts оборачивает непредвиденную ошибку в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_status_counts = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_status_counts()


# ---------------------------------------------------------------------------
# путь сбоя аудита в _safe_log_user_or_system_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_audit_failure_is_swallowed(audit_service):
    """Сбой пользовательского аудита во время операции не пробрасывается."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.update_password_hash_by_id = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    audit_service.log_user_event = AsyncMock(side_effect=RuntimeError("audit down"))
    service = _make_service(uow, audit_service)

    result = await service.change_password(
        USER_ID, "NewSecurePass99!", actor_id=uuid.uuid4()
    )
    assert isinstance(result, UserRead)


# ---------------------------------------------------------------------------
# хелперы уровня модуля
# ---------------------------------------------------------------------------


def test_role_list_item_converts_role():
    """_role_list_item собирает RoleListItem из мока роли."""
    from schemas.roles import RoleListItem

    item = _role_list_item(_make_role_mock("editor"))
    assert isinstance(item, RoleListItem)
    assert item.name == "editor"


def test_audit_user_with_enum_status():
    """_audit_user сериализует enum-статус в его значение."""
    snapshot = _make_user_snapshot(status=UserStatus.BLOCKED)
    result = _audit_user(snapshot)
    assert result["status"] == UserStatus.BLOCKED.value
    assert result["id"] == str(USER_ID)


def test_audit_user_with_string_status():
    """_audit_user сериализует не-enum статус через str()."""
    snapshot = _make_user_snapshot(status="custom")
    result = _audit_user(snapshot)
    assert result["status"] == "custom"


def test_matches_created_range_no_datetime():
    """_matches_created_range возвращает True, когда created_at отсутствует или не datetime."""
    snapshot = _make_user_snapshot(created_at=None)
    params = UserQueryParams(offset=0, limit=10)
    assert _matches_created_range(snapshot, params) is True


def test_matches_created_range_before_from():
    """_matches_created_range возвращает False до created_from."""
    snapshot = _make_user_snapshot(created_at=datetime(2000, 1, 1, tzinfo=UTC))
    params = UserQueryParams(
        offset=0, limit=10, created_from=datetime(2020, 1, 1, tzinfo=UTC)
    )
    assert _matches_created_range(snapshot, params) is False


def test_matches_created_range_after_to():
    """_matches_created_range возвращает False после created_to."""
    snapshot = _make_user_snapshot(created_at=datetime(2030, 1, 1, tzinfo=UTC))
    params = UserQueryParams(
        offset=0, limit=10, created_to=datetime(2020, 1, 1, tzinfo=UTC)
    )
    assert _matches_created_range(snapshot, params) is False


def test_get_users_service_returns_instance():
    """get_users_service возвращает настроенный UsersService."""
    uow = make_uow_mock()
    svc = get_users_service(
        uow_factory=make_uow_factory(uow), audit_service=MagicMock()
    )
    assert isinstance(svc, UsersService)


# ---------------------------------------------------------------------------
# Дополнительное покрытие веток: ValueError в UoW, проброс ServiceError,
# оборачивание непредвиденных ошибок для простых геттеров, _require_result, счётчиков статусов
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_value_error_inside_uow_wraps(audit_service):
    """ValueError внутри UoW преобразуется в ValidationServiceError."""
    users_repo = AsyncMock()
    users_repo.create_user = AsyncMock(side_effect=ValueError("bad"))
    uow = make_uow_mock(users=users_repo, roles=AsyncMock())
    service = _make_service(uow, audit_service)

    data = UserCreate(email="a@example.com", username="auser", password="SecurePass123!")
    with pytest.raises(ValidationServiceError):
        await service.create_user(data)


@pytest.mark.asyncio
async def test_create_user_service_error_reraised(audit_service):
    """ServiceError, возникший внутри create_user, пробрасывается без изменений."""
    sentinel = ServiceError("boom", service="users", operation="create_user")
    users_repo = AsyncMock()
    users_repo.create_user = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo, roles=AsyncMock())
    service = _make_service(uow, audit_service)

    data = UserCreate(email="a@example.com", username="auser", password="SecurePass123!")
    with pytest.raises(ServiceError) as exc_info:
        await service.create_user(data)
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_get_user_unexpected_error_wraps(audit_service):
    """get_user оборачивает не-DatabaseError исключение в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_user(USER_ID)


@pytest.mark.asyncio
async def test_get_user_service_error_reraised(audit_service):
    """get_user пробрасывает ServiceError без повторного оборачивания."""
    sentinel = ServiceError("inner", service="users", operation="get_user")
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_user(USER_ID)
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_list_users_service_error_reraised(audit_service):
    """list_users пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="list_users")
    users_repo = AsyncMock()
    users_repo.list_users = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    params = UserQueryParams(offset=0, limit=10)
    with pytest.raises(ServiceError) as exc_info:
        await service.list_users(params)
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_update_user_service_error_reraised(audit_service):
    """update_user пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="update_user")
    users_repo = AsyncMock()
    users_repo.update_identity_by_id = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.update_user(USER_ID, UserUpdate(username="newname"))
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_admin_update_user_service_error_reraised(audit_service):
    """admin_update_user пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="admin_update_user")
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.admin_update_user(USER_ID, UserAdminUpdate(username="adminuser"))
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_change_password_service_error_reraised(audit_service):
    """change_password пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="change_password")
    users_repo = AsyncMock()
    users_repo.update_password_hash_by_id = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.change_password(USER_ID, "NewSecurePass99!")
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_mark_login_service_error_reraised(audit_service):
    """mark_login пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="mark_login")
    users_repo = AsyncMock()
    users_repo.update_last_login_by_id = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.mark_login(USER_ID)
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_get_user_with_roles_unexpected_wraps_distinct(audit_service):
    """get_user_with_roles оборачивает ошибку из get_user_roles в ServiceError."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    roles_repo = AsyncMock()
    roles_repo.get_user_roles = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_user_with_roles(USER_ID)


@pytest.mark.asyncio
async def test_get_current_user_read_unexpected_from_roles(audit_service):
    """get_current_user_read оборачивает ошибку из get_user_roles в ServiceError."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    roles_repo = AsyncMock()
    roles_repo.get_user_roles = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow_mock(users=users_repo, roles=roles_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError):
        await service.get_current_user_read(USER_ID)


@pytest.mark.asyncio
async def test_get_status_counts_service_error_reraised(audit_service):
    """get_status_counts пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="get_status_counts")
    users_repo = AsyncMock()
    users_repo.get_status_counts = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_status_counts()
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_get_user_with_roles_service_error_reraised(audit_service):
    """get_user_with_roles пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="get_user_with_roles")
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo, roles=AsyncMock())
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_user_with_roles(USER_ID)
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_get_current_user_read_service_error_reraised(audit_service):
    """get_current_user_read пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="get_current_user_read")
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo, roles=AsyncMock())
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_current_user_read(USER_ID)
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_get_user_by_email_service_error_reraised(audit_service):
    """get_user_by_email пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="get_user_by_email")
    users_repo = AsyncMock()
    users_repo.get_required_by_email = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_user_by_email("x@example.com")
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_get_user_by_username_service_error_reraised(audit_service):
    """get_user_by_username пробрасывает ServiceError, возникший внутри UoW."""
    sentinel = ServiceError("inner", service="users", operation="get_user_by_username")
    users_repo = AsyncMock()
    users_repo.get_required_by_username = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_user_by_username("u")
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_change_password_value_error_inside_uow_wraps(audit_service):
    """ValueError внутри UoW в change_password преобразуется в ValidationServiceError."""
    users_repo = AsyncMock()
    users_repo.update_password_hash_by_id = AsyncMock(side_effect=ValueError("bad"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ValidationServiceError):
        await service.change_password(USER_ID, "NewSecurePass99!")


@pytest.mark.asyncio
async def test_mutate_status_service_error_reraised(audit_service):
    """_mutate_status пробрасывает ServiceError, возникший в мутаторе."""
    sentinel = ServiceError("inner", service="users", operation="delete_user")
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    users_repo.mark_deleted = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service)

    with pytest.raises(ServiceError) as exc_info:
        await service.delete_user(USER_ID)
    assert exc_info.value is sentinel
