"""Юнит-тесты для AuthService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.models.enums import SessionStatus, SystemRole, UserStatus
from schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
)
from security.password.service import hash_password
from services.auth import AuthService
from services.exceptions import AuthenticationServiceError, ServiceError
from tests.unit.services.conftest import (
    make_token_mock,
    make_uow_factory,
    make_uow_mock,
    make_user_mock,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PASSWORD = "TestPass123!"
PASSWORD_HASH = hash_password(PASSWORD, scheme="bcrypt")

USER_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()


@pytest.fixture
def audit_service():
    svc = MagicMock()
    svc.log_user_event = AsyncMock()
    svc.log_system_event = AsyncMock()
    return svc


@pytest.fixture
def settings():
    from core.config import get_settings

    return get_settings()


def _make_service(uow, audit_service, settings=None):
    if settings is None:
        from core.config import get_settings

        settings = get_settings()
    return AuthService(
        uow_factory=make_uow_factory(uow),
        audit_service=audit_service,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success(audit_service, settings):
    """Успешный вход возвращает LoginResponse с информацией о пользователе."""
    user = make_user_mock(
        user_id=USER_ID,
        email="user@example.com",
        username="testuser",
        status=UserStatus.ACTIVE,
        password_hash=PASSWORD_HASH,
    )
    token = make_token_mock(user_id=USER_ID, token_id=SESSION_ID)

    users_repo = AsyncMock()
    users_repo.get_by_email = AsyncMock(return_value=user)
    users_repo.update_last_login = AsyncMock(return_value=user)
    users_repo.update_password_hash = AsyncMock(return_value=user)

    tokens_repo = AsyncMock()
    tokens_repo.create_token = AsyncMock(return_value=token)


    uow = make_uow_mock(users=users_repo, refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="user@example.com", password=PASSWORD)
    result = await service.login(data)

    assert isinstance(result, LoginResponse)
    assert result.user.email == "user@example.com"


@pytest.mark.asyncio
async def test_login_user_not_found_raises(audit_service, settings):
    """Вход с неизвестным email вызывает AuthenticationServiceError."""
    users_repo = AsyncMock()
    users_repo.get_by_email = AsyncMock(return_value=None)
    users_repo.get_by_username = AsyncMock(return_value=None)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="ghost@example.com", password=PASSWORD)
    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.login(data)

    assert exc_info.value.details.get("reason") == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_wrong_password_raises(audit_service, settings):
    """Вход с неверным паролем вызывает AuthenticationServiceError."""
    user = make_user_mock(
        user_id=USER_ID,
        email="user@example.com",
        status=UserStatus.ACTIVE,
        password_hash=PASSWORD_HASH,
    )
    users_repo = AsyncMock()
    users_repo.get_by_email = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="user@example.com", password="WrongPass999!")
    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.login(data)

    assert exc_info.value.details.get("reason") == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_blocked_user_raises(audit_service, settings):
    """Вход заблокированным пользователем вызывает AuthenticationServiceError с причиной по статусу пользователя."""
    user = make_user_mock(
        user_id=USER_ID,
        email="user@example.com",
        status=UserStatus.BLOCKED,
        password_hash=PASSWORD_HASH,
    )
    # Заблокированный пользователь не может войти
    user.can_login = False

    users_repo = AsyncMock()
    users_repo.get_by_email = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="user@example.com", password=PASSWORD)
    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.login(data)

    # Причина должна содержать значение статуса пользователя ("blocked")
    assert exc_info.value.details.get("reason") == UserStatus.BLOCKED.value


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_with_token_revokes_session(audit_service, settings):
    """logout() с валидным токеном отзывает сессию и возвращает LogoutResponse."""
    token = make_token_mock(token_id=SESSION_ID, user_id=USER_ID)

    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(return_value=token)
    tokens_repo.revoke_token = AsyncMock(return_value=token)

    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    result = await service.logout("some-refresh-token-value")

    assert isinstance(result, LogoutResponse)
    tokens_repo.revoke_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_logout_without_token_skips_db(audit_service, settings):
    """logout(None) полностью пропускает БД и всё равно возвращает LogoutResponse."""
    uow = make_uow_mock()
    factory = make_uow_factory(uow)
    service = AuthService(
        uow_factory=factory,
        audit_service=audit_service,
        settings=settings,
    )

    result = await service.logout(None)

    assert isinstance(result, LogoutResponse)
    # В UoW не должны были входить
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_logout_token_not_in_db_is_silent(audit_service, settings):
    """logout(), когда хеш токена не найден в БД, всё равно тихо отрабатывает."""
    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(return_value=None)

    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    result = await service.logout("unknown-token")
    assert isinstance(result, LogoutResponse)


# ---------------------------------------------------------------------------
# list_sessions validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_invalid_limit_raises(audit_service, settings):
    """list_sessions с limit=0 вызывает AuthenticationServiceError."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.list_sessions(USER_ID, limit=0)

    assert exc_info.value.details.get("reason") == "invalid_limit"


@pytest.mark.asyncio
async def test_list_sessions_negative_offset_raises(audit_service, settings):
    """list_sessions с offset=-1 вызывает AuthenticationServiceError."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.list_sessions(USER_ID, limit=10, offset=-1)

    assert exc_info.value.details.get("reason") == "invalid_offset"


@pytest.mark.asyncio
async def test_list_sessions_success(audit_service, settings):
    """list_sessions возвращает список AuthSessionRead."""
    user = make_user_mock(user_id=USER_ID)
    token = make_token_mock(token_id=SESSION_ID, user_id=USER_ID)

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    tokens_repo = AsyncMock()
    tokens_repo.list_user_tokens = AsyncMock(return_value=[token])

    uow = make_uow_mock(users=users_repo, refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    sessions = await service.list_sessions(USER_ID, limit=10)
    assert len(sessions) == 1
    assert sessions[0].id == SESSION_ID


# ---------------------------------------------------------------------------
# revoke_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_session_wrong_owner_raises(audit_service, settings):
    """revoke_session вызывает AuthenticationServiceError, когда токен принадлежит другому пользователю."""
    different_user_id = uuid.uuid4()
    token = make_token_mock(token_id=SESSION_ID, user_id=different_user_id)

    tokens_repo = AsyncMock()
    tokens_repo.get_required_token_by_id = AsyncMock(return_value=token)

    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.revoke_session(user_id=USER_ID, session_id=SESSION_ID)

    assert exc_info.value.details.get("reason") == "session_owner_mismatch"


@pytest.mark.asyncio
async def test_revoke_session_success(audit_service, settings):
    """revoke_session возвращает AuthSessionRead для корректного владельца."""
    token = make_token_mock(token_id=SESSION_ID, user_id=USER_ID)
    revoked = make_token_mock(
        token_id=SESSION_ID,
        user_id=USER_ID,
        status=SessionStatus.REVOKED,
        can_be_used=False,
    )

    tokens_repo = AsyncMock()
    tokens_repo.get_required_token_by_id = AsyncMock(return_value=token)
    tokens_repo.revoke_token = AsyncMock(return_value=revoked)

    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    result = await service.revoke_session(user_id=USER_ID, session_id=SESSION_ID)
    assert result.id == SESSION_ID


# ---------------------------------------------------------------------------
# refresh_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_session_token_not_found_raises(audit_service, settings):
    """refresh_session вызывает AuthenticationServiceError, когда хеш токена не найден."""
    from security.jwt import create_refresh_token

    valid_refresh_token = create_refresh_token(USER_ID, settings=settings)

    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(return_value=None)

    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.refresh_session(valid_refresh_token)

    assert exc_info.value.details.get("reason") == "refresh_token_not_found"


@pytest.mark.asyncio
async def test_refresh_session_invalid_jwt_raises(audit_service, settings):
    """refresh_session вызывает AuthenticationServiceError для мусорного JWT."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError):
        await service.refresh_session("this-is-not-a-jwt")


# ---------------------------------------------------------------------------
# проброс ошибки базы данных
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_database_error_propagates(audit_service, settings):
    """DatabaseError из репозитория оборачивается в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.get_by_email = AsyncMock(side_effect=DBError("DB is down"))

    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="user@example.com", password=PASSWORD)
    with pytest.raises(ServiceError):
        await service.login(data)


# ---------------------------------------------------------------------------
# logout_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_all_revokes_all_sessions(audit_service, settings):
    """logout_all отзывает все сессии пользователя и возвращает LogoutResponse."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)

    tokens_repo = AsyncMock()
    tokens_repo.revoke_all_user_tokens = AsyncMock(return_value=3)

    uow = make_uow_mock(users=users_repo, refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    result = await service.logout_all(USER_ID)
    assert isinstance(result, LogoutResponse)
    tokens_repo.revoke_all_user_tokens.assert_awaited_once_with(
        USER_ID, reason="logout all sessions", flush=True
    )


# ---------------------------------------------------------------------------
# Extra helpers
# ---------------------------------------------------------------------------


def _make_response_mock():
    """Вернуть мок, похожий на Response, который фиксирует операции с cookie."""
    response = MagicMock()
    response.set_cookie = MagicMock()
    response.delete_cookie = MagicMock()
    return response


def _login_uow(audit_service, settings, *, status=UserStatus.ACTIVE, role=SystemRole.USER):
    user = make_user_mock(
        user_id=USER_ID,
        email="user@example.com",
        username="testuser",
        status=status,
        password_hash=PASSWORD_HASH,
        role=role,
    )
    token = make_token_mock(user_id=USER_ID, token_id=SESSION_ID)

    users_repo = AsyncMock()
    users_repo.get_by_email = AsyncMock(return_value=user)
    users_repo.update_last_login = AsyncMock(return_value=user)
    users_repo.update_password_hash = AsyncMock(return_value=user)

    tokens_repo = AsyncMock()
    tokens_repo.create_token = AsyncMock(return_value=token)

    uow = make_uow_mock(users=users_repo, refresh_tokens=tokens_repo)
    return uow, users_repo, tokens_repo


# ---------------------------------------------------------------------------
# login — extra branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_roles_builds_current_user(audit_service, settings):
    """Вход возвращает системную роль в DTO CurrentUserRead."""
    uow, *_ = _login_uow(audit_service, settings, role=SystemRole.ADMIN)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="user@example.com", password=PASSWORD)
    result = await service.login(data)

    assert result.user.role == SystemRole.ADMIN
    audit_service.log_user_event.assert_awaited()


@pytest.mark.asyncio
async def test_login_username_lookup_path(audit_service, settings):
    """Вход по имени пользователя (без '@') ищет пользователей по username."""
    user = make_user_mock(
        user_id=USER_ID,
        email="user@example.com",
        username="bob",
        status=UserStatus.ACTIVE,
        password_hash=PASSWORD_HASH,
    )
    token = make_token_mock(user_id=USER_ID, token_id=SESSION_ID)
    users_repo = AsyncMock()
    users_repo.get_by_username = AsyncMock(return_value=user)
    users_repo.get_by_email = AsyncMock(return_value=None)
    users_repo.update_last_login = AsyncMock(return_value=user)
    tokens_repo = AsyncMock()
    tokens_repo.create_token = AsyncMock(return_value=token)

    uow = make_uow_mock(users=users_repo, refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="bob", password=PASSWORD)
    result = await service.login(data)

    assert isinstance(result, LoginResponse)
    users_repo.get_by_username.assert_awaited_once()
    users_repo.get_by_email.assert_not_called()


@pytest.mark.asyncio
async def test_login_email_then_username_fallback(audit_service, settings):
    """Когда поиск по email не дал результата, вход откатывается к поиску по username."""
    user = make_user_mock(
        user_id=USER_ID, status=UserStatus.ACTIVE, password_hash=PASSWORD_HASH
    )
    token = make_token_mock(user_id=USER_ID, token_id=SESSION_ID)
    users_repo = AsyncMock()
    users_repo.get_by_email = AsyncMock(return_value=None)
    users_repo.get_by_username = AsyncMock(return_value=user)
    users_repo.update_last_login = AsyncMock(return_value=user)
    tokens_repo = AsyncMock()
    tokens_repo.create_token = AsyncMock(return_value=token)

    uow = make_uow_mock(users=users_repo, refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="user@example.com", password=PASSWORD)
    result = await service.login(data)

    assert isinstance(result, LoginResponse)
    users_repo.get_by_email.assert_awaited_once()
    users_repo.get_by_username.assert_awaited_once()


@pytest.mark.asyncio
async def test_login_sets_cookies_on_response(audit_service, settings):
    """Вход с объектом Response устанавливает cookie аутентификации (покрывает путь cookie)."""
    uow, *_ = _login_uow(audit_service, settings)
    service = _make_service(uow, audit_service, settings)
    response = _make_response_mock()

    data = LoginRequest(email_or_username="user@example.com", password=PASSWORD)
    await service.login(data, response=response, ip_address="1.2.3.4", user_agent="ua")

    response.set_cookie.assert_called()


@pytest.mark.asyncio
async def test_login_rehashes_password_when_needed(audit_service, settings):
    """Вход обновляет хеш пароля, когда verify_and_update возвращает новый хеш."""
    uow, users_repo, *_ = _login_uow(audit_service, settings)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="user@example.com", password=PASSWORD)
    with patch(
        "services.auth.verify_and_update_password_hash",
        return_value=(True, "new-hash"),
    ):
        await service.login(data)

    users_repo.update_password_hash.assert_awaited_once()


@pytest.mark.asyncio
async def test_login_unexpected_error_wrapped(audit_service, settings):
    """Не-DatabaseError при входе оборачивается в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_by_email = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="user@example.com", password=PASSWORD)
    with pytest.raises(ServiceError):
        await service.login(data)


# ---------------------------------------------------------------------------
# refresh_session — full coverage
# ---------------------------------------------------------------------------


def _valid_refresh_token(settings):
    from security.jwt import create_refresh_token

    return create_refresh_token(USER_ID, settings=settings)


@pytest.mark.asyncio
async def test_refresh_session_success_rotates(audit_service, settings):
    """refresh_session ротирует токен и возвращает RefreshTokenResponse."""
    from schemas.auth import RefreshTokenResponse

    refresh_token = _valid_refresh_token(settings)
    existing = make_token_mock(token_id=SESSION_ID, user_id=USER_ID, can_be_used=True)
    new_token = make_token_mock(user_id=USER_ID)
    user = make_user_mock(user_id=USER_ID, status=UserStatus.ACTIVE)

    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(return_value=existing)
    tokens_repo.rotate_token = AsyncMock(return_value=new_token)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)

    uow = make_uow_mock(users=users_repo, refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    response = _make_response_mock()
    result = await service.refresh_session(refresh_token, response=response)

    assert isinstance(result, RefreshTokenResponse)
    tokens_repo.rotate_token.assert_awaited_once()
    response.set_cookie.assert_called()
    audit_service.log_user_event.assert_awaited()


@pytest.mark.asyncio
async def test_refresh_session_reuse_detected_revokes_all(audit_service, settings):
    """Использованный/просроченный refresh-токен запускает обнаружение повторного использования и отзывает все сессии."""
    refresh_token = _valid_refresh_token(settings)
    existing = make_token_mock(token_id=SESSION_ID, user_id=USER_ID, can_be_used=False)

    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(return_value=existing)
    tokens_repo.revoke_all_user_tokens = AsyncMock(return_value=2)

    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.refresh_session(refresh_token)

    assert exc_info.value.details.get("reason") == "refresh_token_reuse_detected"
    tokens_repo.revoke_all_user_tokens.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_session_subject_mismatch_revokes_all(audit_service, settings):
    """Refresh-токен с subject, отличным от сохранённого пользователя, отзывает все сессии."""
    refresh_token = _valid_refresh_token(settings)
    other_user = uuid.uuid4()
    existing = make_token_mock(token_id=SESSION_ID, user_id=other_user, can_be_used=True)

    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(return_value=existing)
    tokens_repo.revoke_all_user_tokens = AsyncMock(return_value=1)

    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.refresh_session(refresh_token)

    assert exc_info.value.details.get("reason") == "subject_mismatch"
    tokens_repo.revoke_all_user_tokens.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_session_blocked_user_revokes_all(audit_service, settings):
    """Если пользователь больше не может входить, refresh отзывает все сессии и бросает ошибку."""
    refresh_token = _valid_refresh_token(settings)
    existing = make_token_mock(token_id=SESSION_ID, user_id=USER_ID, can_be_used=True)
    blocked = make_user_mock(user_id=USER_ID, status=UserStatus.BLOCKED)
    blocked.can_login = False

    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(return_value=existing)
    tokens_repo.revoke_all_user_tokens = AsyncMock(return_value=1)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=blocked)

    uow = make_uow_mock(users=users_repo, refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.refresh_session(refresh_token)

    assert exc_info.value.details.get("reason") == UserStatus.BLOCKED.value
    tokens_repo.revoke_all_user_tokens.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_session_database_error_wrapped(audit_service, settings):
    """DatabaseError при refresh оборачивается в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    refresh_token = _valid_refresh_token(settings)
    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(side_effect=DBError("db down"))
    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError) as exc_info:
        await service.refresh_session(refresh_token)
    assert not isinstance(exc_info.value, AuthenticationServiceError)


@pytest.mark.asyncio
async def test_refresh_session_unexpected_error_wrapped(audit_service, settings):
    """Не-DatabaseError при refresh оборачивается в ServiceError."""
    refresh_token = _valid_refresh_token(settings)
    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.refresh_session(refresh_token)


# ---------------------------------------------------------------------------
# logout — оборачивание ошибок и cookie
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_clears_cookies(audit_service, settings):
    """logout с объектом Response очищает cookie аутентификации."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service, settings)
    response = _make_response_mock()

    result = await service.logout(None, response=response)
    assert isinstance(result, LogoutResponse)
    response.delete_cookie.assert_called()


@pytest.mark.asyncio
async def test_logout_logs_user_event_when_token_found(audit_service, settings):
    """logout записывает пользовательское событие аудита при отзыве сессии."""
    token = make_token_mock(token_id=SESSION_ID, user_id=USER_ID)
    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(return_value=token)
    tokens_repo.revoke_token = AsyncMock(return_value=token)
    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    await service.logout("token-value")
    audit_service.log_user_event.assert_awaited()


@pytest.mark.asyncio
async def test_logout_database_error_wrapped(audit_service, settings):
    """DatabaseError при logout оборачивается в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(side_effect=DBError("db down"))
    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.logout("token-value")


@pytest.mark.asyncio
async def test_logout_unexpected_error_wrapped(audit_service, settings):
    """Не-DatabaseError при logout оборачивается в ServiceError."""
    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.logout("token-value")


# ---------------------------------------------------------------------------
# logout_all — cookie и оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_all_clears_cookies(audit_service, settings):
    """logout_all с объектом Response очищает cookie и логирует событие."""
    user = make_user_mock(user_id=USER_ID)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    tokens_repo = AsyncMock()
    tokens_repo.revoke_all_user_tokens = AsyncMock(return_value=2)
    uow = make_uow_mock(users=users_repo, refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)
    response = _make_response_mock()

    await service.logout_all(USER_ID, response=response)
    response.delete_cookie.assert_called()
    audit_service.log_user_event.assert_awaited()


@pytest.mark.asyncio
async def test_logout_all_database_error_wrapped(audit_service, settings):
    """DatabaseError при logout_all оборачивается в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=DBError("db down"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.logout_all(USER_ID)


@pytest.mark.asyncio
async def test_logout_all_unexpected_error_wrapped(audit_service, settings):
    """Не-DatabaseError при logout_all оборачивается в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.logout_all(USER_ID)


# ---------------------------------------------------------------------------
# get_current_user_from_access_token
# ---------------------------------------------------------------------------


def _valid_access_token(settings):
    from security.jwt import create_access_token

    return create_access_token(USER_ID, settings=settings)


@pytest.mark.asyncio
async def test_get_current_user_success(audit_service, settings):
    """get_current_user_from_access_token возвращает CurrentUserRead с ролью."""
    from schemas.users import CurrentUserRead

    access_token = _valid_access_token(settings)
    user = make_user_mock(
        user_id=USER_ID, status=UserStatus.ACTIVE, role=SystemRole.ADMIN
    )
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=user)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    result = await service.get_current_user_from_access_token(access_token)
    assert isinstance(result, CurrentUserRead)
    assert result.id == USER_ID
    assert result.role == SystemRole.ADMIN


@pytest.mark.asyncio
async def test_get_current_user_invalid_token_raises(audit_service, settings):
    """Мусорный access-токен вызывает AuthenticationServiceError."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError):
        await service.get_current_user_from_access_token("not-a-jwt")


@pytest.mark.asyncio
async def test_get_current_user_blocked_raises(audit_service, settings):
    """Неактивный пользователь за валидным токеном вызывает AuthenticationServiceError."""
    access_token = _valid_access_token(settings)
    blocked = make_user_mock(user_id=USER_ID, status=UserStatus.BLOCKED)
    blocked.can_login = False
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=blocked)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(AuthenticationServiceError) as exc_info:
        await service.get_current_user_from_access_token(access_token)
    assert exc_info.value.details.get("reason") == UserStatus.BLOCKED.value


@pytest.mark.asyncio
async def test_get_current_user_database_error_wrapped(audit_service, settings):
    """DatabaseError при загрузке пользователя оборачивается в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    access_token = _valid_access_token(settings)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=DBError("db down"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError) as exc_info:
        await service.get_current_user_from_access_token(access_token)
    assert not isinstance(exc_info.value, AuthenticationServiceError)


@pytest.mark.asyncio
async def test_get_current_user_unexpected_error_wrapped(audit_service, settings):
    """Не-DatabaseError при загрузке пользователя оборачивается в ServiceError."""
    access_token = _valid_access_token(settings)
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.get_current_user_from_access_token(access_token)


# ---------------------------------------------------------------------------
# list_sessions — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_database_error_wrapped(audit_service, settings):
    """DatabaseError при list_sessions оборачивается в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=DBError("db down"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.list_sessions(USER_ID, limit=10)


@pytest.mark.asyncio
async def test_list_sessions_unexpected_error_wrapped(audit_service, settings):
    """Не-DatabaseError при list_sessions оборачивается в ServiceError."""
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.list_sessions(USER_ID, limit=10)


# ---------------------------------------------------------------------------
# revoke_session — оборачивание ошибок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_session_database_error_wrapped(audit_service, settings):
    """DatabaseError при revoke_session оборачивается в ServiceError."""
    from database.exceptions import DatabaseError as DBError

    tokens_repo = AsyncMock()
    tokens_repo.get_required_token_by_id = AsyncMock(side_effect=DBError("db down"))
    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.revoke_session(user_id=USER_ID, session_id=SESSION_ID)


@pytest.mark.asyncio
async def test_revoke_session_unexpected_error_wrapped(audit_service, settings):
    """Не-DatabaseError при revoke_session оборачивается в ServiceError."""
    tokens_repo = AsyncMock()
    tokens_repo.get_required_token_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError):
        await service.revoke_session(user_id=USER_ID, session_id=SESSION_ID)


# ---------------------------------------------------------------------------
# Static helpers & module-level functions
# ---------------------------------------------------------------------------


def test_require_datetime_none_raises():
    """_require_datetime вызывает ServiceError, когда значение None."""
    with pytest.raises(ServiceError):
        AuthService._require_datetime(None, operation="op", field="exp")


def test_require_datetime_passthrough():
    """_require_datetime возвращает значение, когда оно задано."""
    now = datetime.now(UTC)
    assert AuthService._require_datetime(now, operation="op", field="exp") is now


def test_require_result_none_raises():
    """_require_result вызывает ServiceError, когда результат None."""
    with pytest.raises(ServiceError):
        AuthService._require_result(None, operation="op")


def test_get_auth_service_factory(audit_service, settings):
    """get_auth_service возвращает настроенный экземпляр AuthService."""
    from services.auth import get_auth_service

    uow = make_uow_mock()
    service = get_auth_service(
        uow_factory=make_uow_factory(uow),
        audit_service=audit_service,
        settings=settings,
    )
    assert isinstance(service, AuthService)
    assert service.audit_service is audit_service


@pytest.mark.asyncio
async def test_audit_failure_is_swallowed(audit_service, settings):
    """Сбой бэкенда аудита не ломает операцию аутентификации."""
    audit_service.log_user_event = AsyncMock(side_effect=RuntimeError("audit down"))
    uow, *_ = _login_uow(audit_service, settings)
    service = _make_service(uow, audit_service, settings)

    data = LoginRequest(email_or_username="user@example.com", password=PASSWORD)
    result = await service.login(data)
    assert isinstance(result, LoginResponse)


@pytest.mark.asyncio
async def test_safe_log_system_event_used_without_actor(audit_service, settings):
    """logout без известного пользователя логирует системное событие аудита (actor_id равен None)."""
    uow = make_uow_mock()
    service = _make_service(uow, audit_service, settings)

    await service.logout(None)
    audit_service.log_system_event.assert_awaited()


# ---------------------------------------------------------------------------
# Ветки проброса ServiceError (не должны оборачиваться повторно)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_service_error_reraised(audit_service, settings):
    """ServiceError, возникший внутри logout, пробрасывается без изменений."""
    sentinel = ServiceError("boom", service="auth", operation="logout")
    tokens_repo = AsyncMock()
    tokens_repo.get_by_hash = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(refresh_tokens=tokens_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError) as exc_info:
        await service.logout("token-value")
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_logout_all_service_error_reraised(audit_service, settings):
    """ServiceError, возникший внутри logout_all, пробрасывается без изменений."""
    sentinel = ServiceError("boom", service="auth", operation="logout_all")
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError) as exc_info:
        await service.logout_all(USER_ID)
    assert exc_info.value is sentinel


@pytest.mark.asyncio
async def test_list_sessions_service_error_reraised(audit_service, settings):
    """ServiceError, возникший внутри list_sessions, пробрасывается без изменений."""
    sentinel = ServiceError("boom", service="auth", operation="list_sessions")
    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(side_effect=sentinel)
    uow = make_uow_mock(users=users_repo)
    service = _make_service(uow, audit_service, settings)

    with pytest.raises(ServiceError) as exc_info:
        await service.list_sessions(USER_ID, limit=10)
    assert exc_info.value is sentinel
