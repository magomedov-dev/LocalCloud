from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

if TYPE_CHECKING:
    from services.users import UsersService

from fastapi import Response

from core.config import Settings, get_settings
from core.logging import get_logger
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    AuditResult,
    UserStatus,
)
from database.models.roles import Role
from database.models.tokens import RefreshToken
from database.models.users import User
from schemas.auth import (
    AuthSessionRead,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RefreshTokenResponse,
    TokenPair,
)
from schemas.roles import RoleListItem
from schemas.users import CurrentUserRead
from security.cookies import clear_auth_cookies, set_auth_cookies
from security.jwt import (
    JwtExpiredError,
    JwtTokenError,
    create_access_token,
    create_refresh_token,
    create_token,
    decode_access_token,
    decode_refresh_token,
    decode_token,
    hash_token,
)
from security.password import verify_and_update_password_hash
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    AuthenticationServiceError,
    ServiceError,
    service_error_from_database,
    service_error_from_exception,
)

logger = get_logger("services.auth")

SERVICE_NAME = "auth"
MAX_SESSION_LIMIT = 1000

# Тип результата сервисной операции, который не должен быть `None`.
T = TypeVar("T")


class AuthService:
    """Бизнес-сервис JWT-аутентификации и refresh-token сессий.

    Сервис выполняет вход пользователя, выпуск JWT-пары, ротацию refresh token,
    выход из системы, отзыв сессий и получение текущего пользователя по access
    token. Также сервис обновляет hash пароля при необходимости и пишет события
    аудита для auth-операций.

    Attributes:
        uow_factory: Фабрика UnitOfWork для создания транзакционных контекстов.
        audit_service: Сервис аудита для записи событий аутентификации.
        settings: Настройки приложения, используемые JWT и cookie-слоями.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
        audit_service: AuditService | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Инициализирует сервис аутентификации.

        Args:
            uow_factory: Фабрика UnitOfWork. Если не передана, создаётся
                стандартная фабрика через `create_unit_of_work_factory()`.
            audit_service: Сервис аудита. Если не передан, создаётся сервис
                аудита с той же фабрикой UnitOfWork.
            settings: Настройки приложения. Если не переданы, загружаются через
                `get_settings()`.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory,
        )
        self.settings = settings or get_settings()

    async def login(
        self,
        data: LoginRequest,
        *,
        response: Response | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> LoginResponse:
        """Аутентифицирует пользователя и создаёт refresh-token сессию.

        Метод возвращает только публичный DTO ответа. Внутренняя JWT-пара
        создаётся методом `login_with_tokens()`. Если передан `response`,
        access и refresh token устанавливаются в cookie.

        Args:
            data: Данные входа пользователя.
            response: HTTP-ответ, в который нужно установить auth-cookie.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            device_name: Название устройства или клиента.

        Returns:
            DTO успешного входа с текущим пользователем.

        Raises:
            AuthenticationServiceError: Если логин или пароль неверны либо
                пользователь не может войти.
            ServiceError: Если вход не удалось выполнить.
        """

        login_response, _tokens = await self.login_with_tokens(
            data,
            response=response,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
        )
        return login_response

    async def login_with_tokens(
        self,
        data: LoginRequest,
        *,
        response: Response | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> tuple[LoginResponse, TokenPair]:
        """Аутентифицирует пользователя и возвращает ответ вместе с JWT-парой.

        Метод проверяет пользователя по email или username, валидирует пароль,
        при необходимости обновляет hash пароля, создаёт access и refresh token,
        сохраняет refresh-token сессию и обновляет время последнего входа.

        Args:
            data: Данные входа пользователя.
            response: HTTP-ответ, в который нужно установить auth-cookie.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            device_name: Название устройства или клиента.

        Returns:
            Кортеж из публичного DTO входа и внутренней JWT-пары.

        Raises:
            AuthenticationServiceError: Если учётные данные неверны или
                пользователь не может войти.
            ServiceError: Если вход не удалось выполнить.
        """

        operation = "login"
        user_snapshot: dict[str, Any] = {}
        roles: list[Role] = []
        token_pair: TokenPair | None = None
        session_id: UUID | None = None

        try:
            async with self.uow_factory() as uow:
                user = await self._find_user_for_login(
                    uow=uow,
                    email_or_username=data.email_or_username,
                )
                if user is None:
                    await self._safe_log_login_failure(
                        email_or_username=data.email_or_username,
                        reason="user_not_found",
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                    raise self._invalid_credentials_error(operation=operation)

                password_valid, new_password_hash = verify_and_update_password_hash(
                    plain_password=data.password,
                    password_hash=user.password_hash,
                )
                if not password_valid:
                    await self._safe_log_login_failure(
                        email_or_username=data.email_or_username,
                        reason="invalid_password",
                        user_id=user.id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                    raise self._invalid_credentials_error(operation=operation)

                if not user.can_login:
                    await self._safe_log_login_failure(
                        email_or_username=data.email_or_username,
                        reason=f"user_status_{user.status.value}",
                        user_id=user.id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                    raise AuthenticationServiceError(
                        "Учётная запись не может войти в систему.",
                        user_id=user.id,
                        reason=user.status.value,
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                if new_password_hash is not None:
                    await uow.users.update_password_hash(
                        user,
                        password_hash=new_password_hash,
                        flush=True,
                        refresh=False,
                    )

                token_pair = self._create_token_pair(user.id)
                refresh_token_model = await uow.refresh_tokens.create_token(
                    user_id=user.id,
                    token_hash=hash_token(
                        token_pair.refresh_token,
                        settings=self.settings,
                    ),
                    expires_at=self._require_datetime(
                        token_pair.refresh_expires_at,
                        operation=operation,
                        field="refresh_expires_at",
                    ),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    device_name=device_name,
                    flush=True,
                    refresh=True,
                    check_user_exists=False,
                    check_duplicate=True,
                )
                session_id = refresh_token_model.id
                await uow.users.update_last_login(
                    user,
                    last_login_at=datetime.now(UTC),
                    flush=True,
                    refresh=True,
                )
                roles = await uow.roles.get_user_roles(
                    user.id,
                    only_active_roles=True,
                    order_by_name=True,
                )
                user_snapshot = _user_snapshot(user)
                await uow.commit()

            issued_tokens = self._require_result(token_pair, operation=operation)

            if response is not None:
                self._set_response_cookies(response, issued_tokens)

            await self._safe_log_auth_event(
                actor_id=user_snapshot["id"],
                action=AuditAction.USER_LOGIN,
                result=AuditResult.SUCCESS,
                entity_id=session_id,
                ip_address=ip_address,
                user_agent=user_agent,
                message="Пользователь вошёл в систему.",
                metadata={
                    "operation": operation,
                    "user": _audit_user(user_snapshot),
                    "session_id": str(session_id) if session_id else None,
                },
            )
            return (
                LoginResponse(user=_current_user_read(user_snapshot, roles)),
                issued_tokens,
            )

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось выполнить вход в систему.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при входе в систему.",
            ) from exc

    async def refresh_session(
        self,
        refresh_token: str,
        *,
        response: Response | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> RefreshTokenResponse:
        """Ротирует refresh token и создаёт новую JWT-пару.

        Метод возвращает только публичный DTO ответа. Внутренняя JWT-пара
        создаётся методом `refresh_session_with_tokens()`. Если передан
        `response`, новые access и refresh token устанавливаются в cookie.

        Args:
            refresh_token: Исходный refresh token.
            response: HTTP-ответ, в который нужно установить новые auth-cookie.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            device_name: Название устройства или клиента.

        Returns:
            DTO успешного обновления сессии.

        Raises:
            AuthenticationServiceError: Если refresh token недействителен,
                отозван, истёк или не соответствует пользователю.
            ServiceError: Если сессию не удалось обновить.
        """

        refresh_response, _tokens = await self.refresh_session_with_tokens(
            refresh_token,
            response=response,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
        )
        return refresh_response

    async def refresh_session_with_tokens(
        self,
        refresh_token: str,
        *,
        response: Response | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> tuple[RefreshTokenResponse, TokenPair]:
        """Ротирует refresh token и возвращает ответ вместе с новой JWT-парой.

        Метод декодирует refresh token, ищет соответствующую сессию по hash,
        проверяет возможность использования токена, отзывает старую сессию,
        создаёт новую refresh-token сессию и возвращает новую JWT-пару.

        Args:
            refresh_token: Исходный refresh token.
            response: HTTP-ответ, в который нужно установить новые auth-cookie.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            device_name: Название устройства или клиента.

        Returns:
            Кортеж из публичного DTO обновления сессии и новой JWT-пары.

        Raises:
            AuthenticationServiceError: Если refresh token недействителен,
                повторно использован, не найден, истёк или принадлежит другому
                пользователю.
            ServiceError: Если сессию не удалось обновить.
        """

        operation = "refresh_session"
        token_pair: TokenPair | None = None
        user_snapshot: dict[str, Any] = {}
        roles: list[Role] = []
        new_session_id: UUID | None = None
        old_session_id: UUID | None = None

        try:
            payload = decode_refresh_token(refresh_token, settings=self.settings)
            old_token_hash = hash_token(refresh_token, settings=self.settings)

            async with self.uow_factory() as uow:
                existing_token = await uow.refresh_tokens.get_by_hash(old_token_hash)
                if existing_token is None:
                    raise AuthenticationServiceError(
                        "Refresh token не найден или уже недействителен.",
                        reason="refresh_token_not_found",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                old_session_id = existing_token.id
                if not existing_token.can_be_used_at(datetime.now(UTC)):
                    await uow.refresh_tokens.revoke_all_user_tokens(
                        existing_token.user_id,
                        reason="refresh token reuse detected",
                        flush=True,
                    )
                    await uow.commit()
                    await self._safe_log_auth_event(
                        actor_id=existing_token.user_id,
                        action=AuditAction.USER_SESSION_REVOKED,
                        result=AuditResult.WARNING,
                        entity_id=existing_token.id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        message="Обнаружено повторное использование refresh-токена.",
                        metadata={"operation": operation},
                    )
                    raise AuthenticationServiceError(
                        "Refresh token уже не может быть использован.",
                        user_id=existing_token.user_id,
                        session_id=existing_token.id,
                        reason="refresh_token_reuse_detected",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                if payload.user_id != existing_token.user_id:
                    await uow.refresh_tokens.revoke_all_user_tokens(
                        existing_token.user_id,
                        reason="refresh token subject mismatch",
                        flush=True,
                    )
                    await uow.commit()
                    raise AuthenticationServiceError(
                        "Refresh token содержит некорректного пользователя.",
                        user_id=existing_token.user_id,
                        session_id=existing_token.id,
                        reason="subject_mismatch",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                user = await uow.users.get_required_user_by_id(existing_token.user_id)
                if not user.can_login:
                    await uow.refresh_tokens.revoke_all_user_tokens(
                        user.id,
                        reason=f"user status is {user.status.value}",
                        flush=True,
                    )
                    await uow.commit()
                    raise AuthenticationServiceError(
                        "Учётная запись больше не может обновлять сессию.",
                        user_id=user.id,
                        reason=user.status.value,
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                token_pair = self._create_token_pair(user.id)
                new_token = await uow.refresh_tokens.rotate_token(
                    old_token=existing_token,
                    new_token_hash=hash_token(
                        token_pair.refresh_token,
                        settings=self.settings,
                    ),
                    new_expires_at=self._require_datetime(
                        token_pair.refresh_expires_at,
                        operation=operation,
                        field="refresh_expires_at",
                    ),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    device_name=device_name,
                    revoke_reason="refresh token rotated",
                    flush=True,
                    refresh=True,
                    check_duplicate=True,
                )
                new_session_id = new_token.id
                roles = await uow.roles.get_user_roles(
                    user.id,
                    only_active_roles=True,
                    order_by_name=True,
                )
                user_snapshot = _user_snapshot(user)
                await uow.commit()

            issued_tokens = self._require_result(token_pair, operation=operation)

            if response is not None:
                self._set_response_cookies(response, issued_tokens)

            await self._safe_log_auth_event(
                actor_id=user_snapshot["id"],
                action=AuditAction.USER_REFRESH_TOKEN_ROTATED,
                result=AuditResult.SUCCESS,
                entity_id=new_session_id,
                ip_address=ip_address,
                user_agent=user_agent,
                message="Refresh-токен был обновлён.",
                metadata={
                    "operation": operation,
                    "old_session_id": str(old_session_id) if old_session_id else None,
                    "new_session_id": str(new_session_id) if new_session_id else None,
                },
            )
            return (
                RefreshTokenResponse(user=_current_user_read(user_snapshot, roles)),
                issued_tokens,
            )

        except JwtTokenError as exc:
            raise AuthenticationServiceError(
                "Refresh token недействителен.",
                reason=getattr(getattr(exc, "code", None), "value", None)
                or exc.__class__.__name__,
                details={"service": SERVICE_NAME, "operation": operation},
                cause=exc,
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось обновить сессию.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при обновлении сессии.",
            ) from exc

    async def logout(
        self,
        refresh_token: str | None = None,
        *,
        response: Response | None = None,
        reason: str = "logout",
    ) -> LogoutResponse:
        """Завершает текущую refresh-token сессию и очищает cookie.

        Если refresh token передан и найден в хранилище, соответствующая сессия
        отзывается. Если передан `response`, auth-cookie очищаются независимо
        от наличия refresh token.

        Args:
            refresh_token: Refresh token текущей сессии.
            response: HTTP-ответ, в котором нужно очистить auth-cookie.
            reason: Причина отзыва refresh-token сессии.

        Returns:
            DTO успешного выхода из системы.

        Raises:
            ServiceError: Если выход из системы не удалось выполнить.
        """

        operation = "logout"
        user_id: UUID | None = None
        session_id: UUID | None = None

        try:
            if refresh_token:
                token_hash = hash_token(refresh_token, settings=self.settings)
                async with self.uow_factory() as uow:
                    token = await uow.refresh_tokens.get_by_hash(token_hash)
                    if token is not None:
                        user_id = token.user_id
                        session_id = token.id
                        await uow.refresh_tokens.revoke_token(
                            token,
                            reason=reason,
                            flush=True,
                            refresh=False,
                        )
                        await uow.commit()

            if response is not None:
                clear_auth_cookies(response, settings=self.settings)

            await self._safe_log_auth_event(
                actor_id=user_id,
                action=AuditAction.USER_LOGOUT,
                result=AuditResult.SUCCESS,
                entity_id=session_id,
                message="Пользователь вышел из системы.",
                metadata={"operation": operation},
            )
            return LogoutResponse()

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось выполнить выход из системы.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при выходе из системы.",
            ) from exc

    async def logout_all(
        self,
        user_id: UUID,
        *,
        response: Response | None = None,
        reason: str = "logout all sessions",
    ) -> LogoutResponse:
        """Завершает все refresh-token сессии пользователя.

        Args:
            user_id: Идентификатор пользователя, сессии которого нужно
                завершить.
            response: HTTP-ответ, в котором нужно очистить auth-cookie.
            reason: Причина массового отзыва сессий.

        Returns:
            DTO успешного завершения всех сессий.

        Raises:
            ServiceError: Если сессии пользователя не удалось завершить.
        """

        operation = "logout_all"
        revoked_count = 0

        try:
            async with self.uow_factory() as uow:
                await uow.users.get_required_user_by_id(user_id)
                revoked_count = await uow.refresh_tokens.revoke_all_user_tokens(
                    user_id,
                    reason=reason,
                    flush=True,
                )
                await uow.commit()

            if response is not None:
                clear_auth_cookies(response, settings=self.settings)

            await self._safe_log_auth_event(
                actor_id=user_id,
                action=AuditAction.USER_SESSION_REVOKED,
                result=AuditResult.SUCCESS,
                entity_id=None,
                message="Все пользовательские сессии были отозваны.",
                metadata={"operation": operation, "revoked_count": revoked_count},
            )
            return LogoutResponse(message="Все сессии завершены.")

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось завершить все сессии пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при завершении всех сессий.",
            ) from exc

    async def get_current_user_from_access_token(
        self,
        access_token: str,
    ) -> CurrentUserRead:
        """Возвращает текущего пользователя по access token.

        Метод декодирует access token, загружает пользователя и его активные
        роли, а затем формирует DTO текущего пользователя.

        Args:
            access_token: JWT access token.

        Returns:
            DTO текущего пользователя.

        Raises:
            AuthenticationServiceError: Если access token недействителен или
                пользователь не может войти.
            ServiceError: Если пользователя не удалось получить.
        """

        operation = "get_current_user_from_access_token"
        current_user: CurrentUserRead | None = None

        try:
            payload = decode_access_token(access_token, settings=self.settings)
            async with self.uow_factory() as uow:
                user = await uow.users.get_required_user_by_id(payload.user_id)
                if not user.can_login:
                    raise AuthenticationServiceError(
                        "Учётная запись неактивна.",
                        user_id=user.id,
                        reason=user.status.value,
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                roles = await uow.roles.get_user_roles(
                    user.id,
                    only_active_roles=True,
                    order_by_name=True,
                )
                current_user = _current_user_read(_user_snapshot(user), roles)

        except JwtTokenError as exc:
            raise AuthenticationServiceError(
                "Access token недействителен.",
                reason=getattr(getattr(exc, "code", None), "value", None)
                or exc.__class__.__name__,
                details={"service": SERVICE_NAME, "operation": operation},
                cause=exc,
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить пользователя по access token.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при проверке access token.",
            ) from exc

        return self._require_result(current_user, operation=operation)

    async def list_sessions(
        self,
        user_id: UUID,
        *,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuthSessionRead]:
        """Возвращает список refresh-token сессий пользователя.

        Args:
            user_id: Идентификатор пользователя.
            include_inactive: Если `True`, включает отозванные, истёкшие и
                неактивные сессии.
            limit: Максимальное количество сессий в ответе.
            offset: Смещение первой сессии.

        Returns:
            Список сессий пользователя.

        Raises:
            AuthenticationServiceError: Если параметры пагинации некорректны.
            ServiceError: Если список сессий не удалось получить.
        """

        operation = "list_sessions"
        sessions: list[AuthSessionRead] | None = None
        self._validate_session_pagination(
            limit=limit, offset=offset, operation=operation
        )

        try:
            async with self.uow_factory() as uow:
                await uow.users.get_required_user_by_id(user_id)
                tokens = await uow.refresh_tokens.list_user_tokens(
                    user_id,
                    offset=offset,
                    limit=limit,
                    include_inactive=include_inactive,
                    include_revoked=include_inactive,
                    include_expired=include_inactive,
                    order_by_created_desc=True,
                )
                sessions = [_auth_session_read(token) for token in tokens]

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить список сессий.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении списка сессий.",
            ) from exc

        return self._require_result(sessions, operation=operation)

    async def revoke_session(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        reason: str = "session revoked",
    ) -> AuthSessionRead:
        """Отзывает одну refresh-token сессию пользователя.

        Args:
            user_id: Идентификатор владельца сессии.
            session_id: Идентификатор refresh-token сессии.
            reason: Причина отзыва сессии.

        Returns:
            DTO отозванной сессии.

        Raises:
            AuthenticationServiceError: Если сессия не принадлежит указанному
                пользователю.
            ServiceError: Если сессию не удалось отозвать.
        """

        operation = "revoke_session"
        result: AuthSessionRead | None = None

        try:
            async with self.uow_factory() as uow:
                token = await uow.refresh_tokens.get_required_token_by_id(session_id)
                if token.user_id != user_id:
                    raise AuthenticationServiceError(
                        "Сессия не принадлежит указанному пользователю.",
                        user_id=user_id,
                        session_id=session_id,
                        reason="session_owner_mismatch",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                revoked_token = await uow.refresh_tokens.revoke_token(
                    token,
                    reason=reason,
                    flush=True,
                    refresh=True,
                )
                result = _auth_session_read(revoked_token)
                await uow.commit()

            await self._safe_log_auth_event(
                actor_id=user_id,
                action=AuditAction.USER_SESSION_REVOKED,
                result=AuditResult.SUCCESS,
                entity_id=session_id,
                message="Пользовательская сессия была отозвана.",
                metadata={"operation": operation},
            )
            return self._require_result(result, operation=operation)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось отозвать сессию.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при отзыве сессии.",
            ) from exc

    async def request_password_reset(
        self,
        data: PasswordResetRequest,
    ) -> PasswordResetRequestResponse:
        """Инициирует сброс пароля пользователя.

        Ищет пользователя по email. Если пользователь найден и активен,
        создаёт JWT-токен сброса пароля. Ответ не раскрывает, зарегистрирован
        ли указанный email.

        Args:
            data: Запрос на сброс пароля с email пользователя.

        Returns:
            Токен сброса пароля и срок его действия.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "request_password_reset"
        _RESET_TTL = timedelta(minutes=30)
        _PLACEHOLDER_EXPIRES = datetime.now(UTC) + _RESET_TTL

        found_user_id: UUID | None = None
        is_active: bool = False

        try:
            async with self.uow_factory() as uow:
                user = await uow.users.get_by_email(data.email, include_deleted=False)
                if user is not None:
                    found_user_id = user.id
                    is_active = user.status == UserStatus.ACTIVE
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Ошибка базы данных при запросе сброса пароля.",
            ) from exc
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при запросе сброса пароля.",
            ) from exc

        if found_user_id is None or not is_active:
            # Не раскрывайте, зарегистрирован ли email.
            return PasswordResetRequestResponse(
                reset_token="",
                expires_at=_PLACEHOLDER_EXPIRES,
                message="Если указанный email зарегистрирован, вы получите инструкции для сброса пароля.",
            )

        reset_token = create_token(
            found_user_id,
            token_type="password_reset",
            expires_delta=_RESET_TTL,
            settings=self.settings,
        )
        payload = decode_token(reset_token, settings=self.settings)

        await self._safe_log_auth_event(
            actor_id=found_user_id,
            action=AuditAction.USER_UPDATED,
            result=AuditResult.SUCCESS,
            entity_id=found_user_id,
            message="Был запрошен сброс пароля.",
            metadata={"operation": operation},
        )

        return PasswordResetRequestResponse(
            reset_token=reset_token,
            expires_at=payload.expires_at,
            message="Если указанный email зарегистрирован, вы получите инструкции для сброса пароля.",
        )

    async def confirm_password_reset(
        self,
        data: PasswordResetConfirmRequest,
        *,
        users_service: UsersService,
    ) -> PasswordResetConfirmResponse:
        """Подтверждает сброс пароля и устанавливает новый пароль.

        Валидирует JWT-токен сброса пароля, извлекает идентификатор
        пользователя и делегирует изменение пароля в UsersService.

        Args:
            data: Запрос подтверждения с токеном и новым паролем.
            users_service: Сервис пользователей для изменения пароля.

        Returns:
            Сообщение об успешном изменении пароля.

        Raises:
            AuthenticationServiceError: Если токен недействителен или истёк.
            ServiceError: Если изменение пароля не удалось выполнить.
        """

        operation = "confirm_password_reset"

        try:
            payload = decode_token(
                data.token,
                expected_type="password_reset",
                settings=self.settings,
            )
        except JwtExpiredError as exc:
            raise AuthenticationServiceError(
                "Токен сброса пароля истёк.",
                reason="token_expired",
                details={"service": SERVICE_NAME, "operation": operation},
            ) from exc
        except JwtTokenError as exc:
            raise AuthenticationServiceError(
                "Недействительный токен сброса пароля.",
                reason="invalid_token",
                details={"service": SERVICE_NAME, "operation": operation},
            ) from exc

        await users_service.change_password(
            payload.user_id,
            data.new_password,
            actor_id=payload.user_id,
        )

        return PasswordResetConfirmResponse(message="Пароль успешно изменён.")

    def _create_token_pair(self, user_id: UUID) -> TokenPair:
        """Создаёт access и refresh token для пользователя.

        Args:
            user_id: Идентификатор пользователя, для которого создаётся
                JWT-пара.

        Returns:
            DTO с access token, refresh token и датами их истечения.

        Raises:
            JwtTokenError: Если созданный токен не удалось декодировать для
                получения срока действия.
        """

        access_token = create_access_token(user_id, settings=self.settings)
        refresh_token = create_refresh_token(user_id, settings=self.settings)
        access_payload = decode_access_token(access_token, settings=self.settings)
        refresh_payload = decode_refresh_token(refresh_token, settings=self.settings)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_payload.expires_at,
            refresh_expires_at=refresh_payload.expires_at,
        )

    async def _find_user_for_login(
        self,
        *,
        uow: Any,
        email_or_username: str,
    ) -> User | None:
        """Ищет пользователя для входа по email или username.

        Если строка содержит символ `@`, сначала выполняется поиск по email.
        Если пользователь по email не найден, выполняется поиск по username.

        Args:
            uow: Активный UnitOfWork с репозиторием пользователей.
            email_or_username: Email или username пользователя.

        Returns:
            ORM-модель пользователя или `None`, если пользователь не найден.
        """

        if "@" in email_or_username:
            user = await uow.users.get_by_email(
                email_or_username,
                include_deleted=False,
            )
            if user is not None:
                return user
        return await uow.users.get_by_username(
            email_or_username,
            include_deleted=False,
        )

    def _set_response_cookies(self, response: Response, token_pair: TokenPair) -> None:
        """Устанавливает auth-cookie в HTTP-ответ.

        Args:
            response: HTTP-ответ FastAPI.
            token_pair: JWT-пара, которую нужно записать в cookie.
        """

        set_auth_cookies(
            response,
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            settings=self.settings,
        )

    @staticmethod
    def _require_datetime(
        value: datetime | None,
        *,
        operation: str,
        field: str,
    ) -> datetime:
        """Проверяет, что JWT-сервис вернул дату истечения токена.

        Args:
            value: Дата истечения токена или `None`.
            operation: Название операции сервиса.
            field: Имя проверяемого поля.

        Returns:
            Переданную дату истечения токена.

        Raises:
            ServiceError: Если дата отсутствует.
        """

        if value is None:
            raise ServiceError(
                "JWT-сервис не вернул дату истечения токена.",
                service=SERVICE_NAME,
                operation=operation,
                details={"field": field},
            )
        return value

    @staticmethod
    def _validate_session_pagination(
        *,
        limit: int,
        offset: int,
        operation: str,
    ) -> None:
        """Проверяет параметры пагинации списка сессий.

        Args:
            limit: Максимальное количество сессий в ответе.
            offset: Смещение первой сессии.
            operation: Название операции сервиса.

        Raises:
            AuthenticationServiceError: Если `limit` меньше 1, превышает
                `MAX_SESSION_LIMIT` или `offset` отрицательный.
        """

        if limit < 1 or limit > MAX_SESSION_LIMIT:
            raise AuthenticationServiceError(
                "Некорректный размер страницы списка сессий.",
                reason="invalid_limit",
                details={
                    "service": SERVICE_NAME,
                    "operation": operation,
                    "limit": limit,
                },
            )
        if offset < 0:
            raise AuthenticationServiceError(
                "Смещение списка сессий не может быть отрицательным.",
                reason="invalid_offset",
                details={
                    "service": SERVICE_NAME,
                    "operation": operation,
                    "offset": offset,
                },
            )

    @staticmethod
    def _invalid_credentials_error(*, operation: str) -> AuthenticationServiceError:
        """Создаёт ошибку неверных учётных данных.

        Args:
            operation: Название операции сервиса.

        Returns:
            Ошибка аутентификации с причиной `invalid_credentials`.
        """

        return AuthenticationServiceError(
            "Неверный логин или пароль.",
            reason="invalid_credentials",
            details={"service": SERVICE_NAME, "operation": operation},
        )

    @staticmethod
    def _require_result(result: T | None, *, operation: str) -> T:
        """Проверяет, что операция сервиса вернула результат.

        Args:
            result: Результат операции или `None`.
            operation: Название операции сервиса.

        Returns:
            Переданный результат, если он не равен `None`.

        Raises:
            ServiceError: Если результат отсутствует.
        """

        if result is None:
            raise ServiceError(
                "Сервис аутентификации не вернул результат операции.",
                service=SERVICE_NAME,
                operation=operation,
            )
        return result

    @staticmethod
    def _database_error(
        exc: DatabaseError, *, operation: str, message: str
    ) -> ServiceError:
        """Преобразует ошибку базы данных в сервисную ошибку auth-сервиса.

        Args:
            exc: Исходная ошибка базы данных.
            operation: Название операции сервиса.
            message: Сообщение для итоговой сервисной ошибки.

        Returns:
            Сервисная ошибка, соответствующая ошибке базы данных.
        """

        return service_error_from_database(
            exc,
            operation=operation,
            message=message,
            service=SERVICE_NAME,
        )

    @staticmethod
    def _unexpected_error(
        exc: Exception, *, operation: str, message: str
    ) -> ServiceError:
        """Логирует непредвиденную ошибку и преобразует её в `ServiceError`.

        Args:
            exc: Исходное исключение.
            operation: Название операции сервиса.
            message: Сообщение для логирования и итоговой сервисной ошибки.

        Returns:
            Сервисная ошибка, созданная из исходного исключения.
        """

        logger.exception(
            message,
            extra={"operation": operation, "error_type": exc.__class__.__name__},
        )
        return service_error_from_exception(
            exc,
            operation=operation,
            message=message,
            service=SERVICE_NAME,
        )

    async def _safe_log_login_failure(
        self,
        *,
        email_or_username: str,
        reason: str,
        user_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Безопасно записывает событие неуспешного входа.

        Ошибка аудита не прерывает основную auth-операцию, так как
        `_safe_log_auth_event()` подавляет и логирует ошибки записи аудита.

        Args:
            email_or_username: Email или username, использованный при входе.
            reason: Причина неуспешного входа.
            user_id: Идентификатор пользователя, если он был найден.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
        """

        await self._safe_log_auth_event(
            actor_id=user_id,
            action=AuditAction.USER_LOGIN_FAILED,
            result=AuditResult.FAILURE,
            entity_id=None,
            ip_address=ip_address,
            user_agent=user_agent,
            message="Не удалось выполнить вход пользователя.",
            error_code=reason,
            metadata={
                "operation": "login",
                "email_or_username": email_or_username,
                "reason": reason,
            },
        )

    async def _safe_log_auth_event(
        self,
        *,
        actor_id: UUID | None,
        action: AuditAction,
        result: AuditResult,
        entity_id: UUID | None,
        message: str,
        metadata: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Безопасно записывает пользовательское или системное auth-событие.

        Если `actor_id` отсутствует, записывается системное событие. Ошибки
        аудита не прерывают основную операцию и логируются как предупреждения.

        Args:
            actor_id: Идентификатор пользователя-инициатора. Если `None`,
                событие записывается как системное.
            action: Тип события аудита.
            result: Результат события аудита.
            entity_id: Идентификатор auth-сущности, обычно refresh-token
                сессии.
            message: Сообщение события аудита.
            metadata: Дополнительные JSON-сериализуемые данные события.
            error_code: Код ошибки для неуспешного события.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
        """

        try:
            if actor_id is None:
                await self.audit_service.log_system_event(
                    action=action,
                    result=result,
                    entity_type=AuditResourceType.SESSION.value,
                    entity_id=entity_id,
                    resource_type=AuditResourceType.SESSION,
                    message=message,
                    error_code=error_code,
                    metadata=metadata,
                )
                return

            await self.audit_service.log_user_event(
                user_id=actor_id,
                action=action,
                result=result,
                entity_type=AuditResourceType.SESSION.value,
                entity_id=entity_id,
                resource_type=AuditResourceType.SESSION,
                ip_address=ip_address,
                user_agent=user_agent,
                message=message,
                error_code=error_code,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита для сервиса аутентификации",
                extra={
                    "action": action.value,
                    "entity_id": str(entity_id) if entity_id else None,
                    "actor_id": str(actor_id) if actor_id else None,
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )


def _user_snapshot(user: User) -> dict[str, Any]:
    """Создаёт словарный снимок пользователя для DTO.

    Args:
        user: ORM-модель пользователя.

    Returns:
        Словарь с основными полями пользователя.
    """

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "status": user.status,
        "is_email_verified": user.is_email_verified,
        "last_login_at": user.last_login_at,
    }


def _role_snapshot(role: Role) -> dict[str, Any]:
    """Создаёт словарный снимок роли для DTO.

    Args:
        role: ORM-модель роли.

    Returns:
        Словарь с основными полями роли.
    """

    return {
        "id": role.id,
        "name": role.name,
        "code": role.code,
        "display_name": role.display_name,
        "is_system": role.is_system,
        "is_active": role.is_active,
    }


def _role_list_item(role: Role) -> RoleListItem:
    """Создаёт DTO элемента списка ролей.

    Args:
        role: ORM-модель роли.

    Returns:
        DTO `RoleListItem`.
    """

    return RoleListItem.model_validate(_role_snapshot(role))


def _current_user_read(
    snapshot: Mapping[str, Any],
    roles: list[Role],
) -> CurrentUserRead:
    """Создаёт DTO текущего пользователя.

    Args:
        snapshot: Словарный снимок пользователя.
        roles: Активные роли пользователя.

    Returns:
        DTO `CurrentUserRead` с вложенным списком ролей.
    """

    payload = dict(snapshot)
    payload["roles"] = [_role_list_item(role) for role in roles]
    return CurrentUserRead.model_validate(payload)


def _auth_session_read(token: RefreshToken) -> AuthSessionRead:
    """Создаёт DTO auth-сессии из refresh token.

    Args:
        token: ORM-модель refresh token.

    Returns:
        DTO `AuthSessionRead`.
    """

    return AuthSessionRead.model_validate(_refresh_token_snapshot(token))


def _refresh_token_snapshot(token: RefreshToken) -> dict[str, Any]:
    """Создаёт словарный снимок refresh-token сессии.

    Args:
        token: ORM-модель refresh token.

    Returns:
        Словарь с полями refresh-token сессии, включая вычисленный признак
        активности.
    """

    return {
        "id": token.id,
        "user_id": token.user_id,
        "status": _enum_or_value(token.status),
        "expires_at": token.expires_at,
        "revoked_at": token.revoked_at,
        "revoke_reason": token.revoke_reason,
        "replaced_by_token_id": token.replaced_by_token_id,
        "parent_token_id": token.parent_token_id,
        "ip_address": str(token.ip_address) if token.ip_address else None,
        "user_agent": token.user_agent,
        "device_name": token.device_name,
        "is_active": token.can_be_used_at(datetime.now(UTC)),
        "created_at": token.created_at,
    }


def _audit_user(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Создаёт payload пользователя для записи в аудит.

    Args:
        snapshot: Словарный снимок пользователя.

    Returns:
        JSON-сериализуемый словарь с ключевыми полями пользователя.
    """

    return {
        "id": str(snapshot["id"]),
        "email": str(snapshot["email"]),
        "username": snapshot["username"],
        "status": snapshot["status"].value
        if isinstance(snapshot["status"], UserStatus)
        else str(snapshot["status"]),
    }


def _enum_or_value(value: Any) -> Any:
    """Возвращает значение enum или исходный объект.

    Args:
        value: Enum-значение или произвольный объект.

    Returns:
        `value.value`, если объект похож на enum, иначе исходное значение.
    """

    return getattr(value, "value", value)


def get_auth_service(
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    audit_service: AuditService | None = None,
    settings: Settings | None = None,
) -> AuthService:
    """Создаёт экземпляр сервиса аутентификации.

    Args:
        uow_factory: Фабрика UnitOfWork. Если не передана, сервис создаст
            стандартную фабрику самостоятельно.
        audit_service: Сервис аудита. Если не передан, будет создан сервис
            аудита с той же фабрикой UnitOfWork.
        settings: Настройки приложения. Если не переданы, сервис загрузит их
            через `get_settings()`.

    Returns:
        Экземпляр `AuthService`.
    """

    return AuthService(
        uow_factory=uow_factory,
        audit_service=audit_service,
        settings=settings,
    )
