from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from core.logging import get_logger
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import AuditAction, AuditResourceType, UserStatus
from database.models.roles import Role
from database.models.users import User
from schemas.common import PageMeta, PageResponse
from schemas.roles import RoleListItem
from schemas.users import (
    CurrentUserRead,
    UserAdminUpdate,
    UserBlockRequest,
    UserCreate,
    UserListItem,
    UserQueryParams,
    UserRead,
    UserRejectRequest,
    UserStatusUpdateRequest,
    UserUpdate,
    UserWithRolesRead,
)
from security.password import hash_password, require_strong_password
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
)

logger = get_logger("services.users")

SERVICE_NAME = "users"
MAX_PAGE_LIMIT = 1000
REPOSITORY_PAGE_LIMIT = 1000
USER_SORT_FIELDS = {
    "created_at",
    "updated_at",
    "email",
    "username",
    "status",
    "last_login_at",
}


class UsersService:
    """Сервис бизнес-логики для учетных записей пользователей.

    Управляет созданием, чтением, обновлением и изменением статусов пользователей.
    Сервис валидирует пароли, вызывает репозитории пользователей и ролей через
    Unit of Work, формирует схемы ответа и записывает события аудита.

    Attributes:
        uow_factory: Фабрика Unit of Work для работы с базой данных.
        audit_service: Сервис записи событий аудита.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        """Инициализирует сервис пользователей.

        Если зависимости не переданы явно, создает их через стандартные фабрики
        и функции получения сервисов.

        Args:
            uow_factory: Фабрика Unit of Work. Если None, создается стандартная
                фабрика.
            audit_service: Сервис аудита. Если None, создается стандартный сервис
                аудита.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory,
        )

    async def create_user(
        self,
        data: UserCreate,
        *,
        actor_id: UUID | None = None,
        assign_default_role: bool = True,
    ) -> UserRead:
        """Создает пользователя.

        Проверяет надежность пароля, хеширует его, создает учетную запись и при
        необходимости назначает стандартную роль пользователя. После успешного
        создания записывает пользовательское или системное событие аудита.

        Args:
            data: Данные для создания пользователя.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие аудита записывается как системное.
            assign_default_role: Нужно ли назначить пользователю стандартную роль.

        Returns:
            Данные созданного пользователя.

        Raises:
            ValidationServiceError: Если пароль не прошел проверку надежности.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "create_user"
        password_hash = self._hash_password(data.password)
        snapshot: dict[str, Any] = {}

        try:
            async with self.uow_factory() as uow:
                user = await uow.users.create_user(
                    email=str(data.email),
                    username=data.username,
                    password_hash=password_hash,
                    status=data.status,
                    is_email_verified=data.is_email_verified,
                    flush=True,
                    refresh=True,
                    check_duplicates=True,
                )

                if assign_default_role:
                    role = await uow.roles.get_required_user_role_model()
                    await uow.roles.assign_role(
                        user_id=user.id,
                        role_id=role.id,
                        assigned_by=actor_id,
                        flush=True,
                        refresh=False,
                        check_user_exists=False,
                        check_role_exists=False,
                        ignore_existing=True,
                    )

                snapshot = _user_snapshot(user)
                await uow.commit()

            await self._safe_log_user_or_system_event(
                actor_id=actor_id,
                action=AuditAction.USER_CREATED,
                entity_id=snapshot["id"],
                message="Пользователь был создан.",
                metadata={"operation": operation, "user": _audit_user(snapshot)},
            )
            return _user_read(snapshot)

        except ValueError as exc:
            raise ValidationServiceError(
                "Пароль пользователя не прошёл проверку.",
                field="password",
                reason="invalid_password",
                details={"service": SERVICE_NAME, "operation": operation},
                cause=exc,
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось создать пользователя."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при создании пользователя.",
            ) from exc

    async def get_user(self, user_id: UUID) -> UserRead:
        """Возвращает пользователя по идентификатору.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Данные найденного пользователя.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        operation = "get_user"
        result: UserRead | None = None
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.get_required_user_by_id(user_id)
                result = _user_read(_user_snapshot(user))
            return self._require_result(result, operation=operation)
        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Пользователь не найден."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении пользователя.",
            ) from exc

    async def get_user_with_roles(self, user_id: UUID) -> UserWithRolesRead:
        """Возвращает пользователя вместе со всеми его ролями.

        Загружает пользователя и его роли, включая неактивные роли, затем формирует
        расширенную схему ответа.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Данные пользователя со списком ролей.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        operation = "get_user_with_roles"
        result: UserWithRolesRead | None = None
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.get_required_user_by_id(user_id)
                roles = await uow.roles.get_user_roles(
                    user.id, only_active_roles=False, order_by_name=True
                )
                first_admin_id = await uow.roles.get_first_admin_user_id()
                snapshot = _user_snapshot(user)
                snapshot["is_primary_admin"] = (
                    first_admin_id is not None and user.id == first_admin_id
                )
                result = _user_with_roles_read(snapshot, roles)
            return self._require_result(result, operation=operation)
        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Пользователь не найден."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении пользователя с ролями.",
            ) from exc

    async def get_current_user_read(self, user_id: UUID) -> CurrentUserRead:
        """Возвращает данные текущего пользователя.

        Загружает пользователя и его активные роли для ответа текущей сессии.

        Args:
            user_id: Идентификатор текущего пользователя.

        Returns:
            Данные текущего пользователя с активными ролями.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        operation = "get_current_user_read"
        result: CurrentUserRead | None = None
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.get_required_user_by_id(user_id)
                roles = await uow.roles.get_user_roles(
                    user.id, only_active_roles=True, order_by_name=True
                )
                result = _current_user_read(_user_snapshot(user), roles)
            return self._require_result(result, operation=operation)
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить текущего пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении текущего пользователя.",
            ) from exc

    async def get_user_by_email(self, email: str) -> UserRead:
        """Возвращает пользователя по email.

        Args:
            email: Email пользователя.

        Returns:
            Данные найденного пользователя.

        Raises:
            ServiceError: Если пользователь с указанным email не найден, произошла
                ошибка базы данных или непредвиденная ошибка сервиса.
        """

        operation = "get_user_by_email"
        result: UserRead | None = None
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.get_required_by_email(email)
                result = _user_read(_user_snapshot(user))
            return self._require_result(result, operation=operation)
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Пользователь с указанным email не найден.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении пользователя по email.",
            ) from exc

    async def get_user_by_username(self, username: str) -> UserRead:
        """Возвращает пользователя по username.

        Args:
            username: Username пользователя.

        Returns:
            Данные найденного пользователя.

        Raises:
            ServiceError: Если пользователь с указанным username не найден,
                произошла ошибка базы данных или непредвиденная ошибка сервиса.
        """

        operation = "get_user_by_username"
        result: UserRead | None = None
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.get_required_by_username(username)
                result = _user_read(_user_snapshot(user))
            return self._require_result(result, operation=operation)
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Пользователь с указанным username не найден.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении пользователя по username.",
            ) from exc

    async def email_exists(
        self, email: str, *, exclude_user_id: UUID | None = None
    ) -> bool:
        """Проверяет существование email.

        Args:
            email: Email для проверки.
            exclude_user_id: Идентификатор пользователя, которого нужно исключить
                из проверки. Используется при обновлении профиля.

        Returns:
            True, если email уже существует, иначе False.

        Raises:
            ServiceError: Если произошла ошибка базы данных.
        """

        return await self._exists(
            operation="email_exists",
            call_name="email_exists",
            value=email,
            exclude_user_id=exclude_user_id,
        )

    async def username_exists(
        self, username: str, *, exclude_user_id: UUID | None = None
    ) -> bool:
        """Проверяет существование username.

        Args:
            username: Username для проверки.
            exclude_user_id: Идентификатор пользователя, которого нужно исключить
                из проверки. Используется при обновлении профиля.

        Returns:
            True, если username уже существует, иначе False.

        Raises:
            ServiceError: Если произошла ошибка базы данных.
        """

        return await self._exists(
            operation="username_exists",
            call_name="username_exists",
            value=username,
            exclude_user_id=exclude_user_id,
        )

    async def list_users(self, params: UserQueryParams) -> PageResponse[UserListItem]:
        """Возвращает список пользователей.

        Загружает пользователей батчами, фильтрует по диапазону даты создания,
        сортирует результат и формирует страницу ответа.

        Args:
            params: Параметры фильтрации, поиска, сортировки и пагинации
                пользователей.

        Returns:
            Страница пользователей и метаданные пагинации.

        Raises:
            ValidationServiceError: Если параметры пагинации некорректны.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_users"
        self._validate_pagination(offset=params.offset, limit=params.limit)
        snapshots: list[dict[str, Any]] = []

        try:
            async with self.uow_factory() as uow:
                snapshots = await self._collect_user_snapshots(uow=uow, params=params)
                first_admin_id = await uow.roles.get_first_admin_user_id()

            snapshots = self._sort_snapshots(
                snapshots, sort_by=params.sort_by, sort_desc=params.sort_desc
            )
            total = len(snapshots)
            page = snapshots[params.offset : params.offset + params.limit]
            for snapshot in page:
                snapshot["is_primary_admin"] = (
                    first_admin_id is not None and snapshot["id"] == first_admin_id
                )

            return PageResponse[UserListItem](
                items=[_user_list_item(snapshot) for snapshot in page],
                meta=PageMeta(
                    limit=params.limit,
                    offset=params.offset,
                    total=total,
                    count=len(page),
                ),
            )

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить список пользователей.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении списка пользователей.",
            ) from exc

    async def update_user(
        self,
        user_id: UUID,
        data: UserUpdate,
        *,
        actor_id: UUID | None = None,
    ) -> UserRead:
        """Обновляет идентификационные данные пользователя.

        Обновляет только явно переданные поля email и username. Если данные
        обновления пустые, возвращает текущего пользователя без изменений.

        Args:
            user_id: Идентификатор обновляемого пользователя.
            data: Данные обновления пользователя.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                в аудит записывается событие от имени самого пользователя.

        Returns:
            Обновленные данные пользователя.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        operation = "update_user"
        values = data.model_dump(exclude_unset=True)
        if not values:
            return await self.get_user(user_id)

        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.update_identity_by_id(
                    user_id,
                    email=str(values["email"])
                    if values.get("email") is not None
                    else None,
                    username=values.get("username"),
                    flush=True,
                    refresh=True,
                    check_duplicates=True,
                )
                snapshot = _user_snapshot(user)
                await uow.commit()

            await self._safe_log_user_or_system_event(
                actor_id=actor_id or user_id,
                action=AuditAction.USER_UPDATED,
                entity_id=user_id,
                message="Идентификационные данные пользователя были обновлены.",
                metadata={
                    "operation": operation,
                    "user": _audit_user(snapshot),
                    "updated_fields": sorted(values),
                },
            )
            return _user_read(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось обновить пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при обновлении пользователя.",
            ) from exc

    async def admin_update_user(
        self,
        user_id: UUID,
        data: UserAdminUpdate,
        *,
        actor_id: UUID | None = None,
    ) -> UserRead:
        """Административно обновляет пользователя.

        Может обновить email, username, статус, причины блокировки или отклонения,
        а также признак подтверждения email. Если данные обновления пустые,
        возвращает текущего пользователя без изменений.

        Args:
            user_id: Идентификатор обновляемого пользователя.
            data: Данные административного обновления.
            actor_id: Идентификатор администратора, выполняющего операцию. Если None,
                событие аудита записывается как системное.

        Returns:
            Обновленные данные пользователя.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        operation = "admin_update_user"
        values = data.model_dump(exclude_unset=True)
        if not values:
            return await self.get_user(user_id)

        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.get_required_user_by_id(user_id)
                identity_values = {
                    key: values[key]
                    for key in ("email", "username")
                    if key in values and values[key] is not None
                }
                if identity_values:
                    user = await uow.users.update_identity(
                        user,
                        email=str(identity_values.get("email"))
                        if identity_values.get("email") is not None
                        else None,
                        username=identity_values.get("username"),
                        flush=True,
                        refresh=True,
                        check_duplicates=True,
                    )

                if "status" in values and values["status"] is not None:
                    user = await uow.users.update_status(
                        user,
                        values["status"],
                        block_reason=values.get("block_reason"),
                        rejection_reason=values.get("rejection_reason"),
                        flush=True,
                        refresh=True,
                    )

                if "is_email_verified" in values:
                    user = await uow.users.set_email_verified(
                        user,
                        is_verified=bool(values["is_email_verified"]),
                        flush=True,
                        refresh=True,
                    )

                snapshot = _user_snapshot(user)
                await uow.commit()

            await self._safe_log_user_or_system_event(
                actor_id=actor_id,
                action=AuditAction.USER_UPDATED,
                entity_id=user_id,
                message="Пользователь был обновлен администратором.",
                metadata={
                    "operation": operation,
                    "user": _audit_user(snapshot),
                    "updated_fields": sorted(values),
                },
            )
            return _user_read(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось административно обновить пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при административном обновлении пользователя.",
            ) from exc

    async def update_status(
        self,
        user_id: UUID,
        data: UserStatusUpdateRequest,
        *,
        actor_id: UUID | None = None,
    ) -> UserRead:
        """Обновляет статус пользователя.

        Делегирует изменение статуса специализированным методам: approve_user,
        block_user, reject_user или delete_user. Для блокировки и отклонения требует
        указать причину.

        Args:
            user_id: Идентификатор пользователя.
            data: Данные обновления статуса.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие аудита может быть записано как системное.

        Returns:
            Данные пользователя после изменения статуса.

        Raises:
            ValidationServiceError: Если для блокировки или отклонения не указана
                причина.
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        if data.status == UserStatus.ACTIVE:
            return await self.approve_user(
                user_id, actor_id=actor_id, is_email_verified=True
            )
        if data.status == UserStatus.BLOCKED:
            if not data.reason:
                raise ValidationServiceError(
                    "Для блокировки пользователя нужно указать причину.",
                    field="reason",
                    reason="missing_block_reason",
                    details={"service": SERVICE_NAME, "operation": "update_status"},
                )
            return await self.block_user(
                user_id, UserBlockRequest(reason=data.reason), actor_id=actor_id
            )
        if data.status == UserStatus.REJECTED:
            if not data.reason:
                raise ValidationServiceError(
                    "Для отклонения пользователя нужно указать причину.",
                    field="reason",
                    reason="missing_rejection_reason",
                    details={"service": SERVICE_NAME, "operation": "update_status"},
                )
            return await self.reject_user(
                user_id, UserRejectRequest(reason=data.reason), actor_id=actor_id
            )
        if data.status == UserStatus.DELETED:
            return await self.delete_user(user_id, actor_id=actor_id)
        return await self.admin_update_user(
            user_id,
            UserAdminUpdate(status=data.status),
            actor_id=actor_id,
        )

    async def approve_user(
        self,
        user_id: UUID,
        *,
        actor_id: UUID | None = None,
        is_email_verified: bool = True,
    ) -> UserRead:
        """Одобряет пользователя и переводит его в активный статус.

        Args:
            user_id: Идентификатор пользователя.
            actor_id: Идентификатор пользователя, выполняющего операцию.
            is_email_verified: Нужно ли установить email как подтвержденный.

        Returns:
            Данные одобренного пользователя.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        snapshot = await self._mutate_status(
            user_id=user_id,
            actor_id=actor_id,
            action=AuditAction.USER_UPDATED,
            operation="approve_user",
            message="Пользователь был одобрен.",
            mutator=lambda uow, user: uow.users.mark_active(
                user, flush=True, refresh=False
            ),
            after=lambda user: setattr(user, "is_email_verified", is_email_verified),
        )
        return _user_read(snapshot)

    async def block_user(
        self,
        user_id: UUID,
        data: UserBlockRequest,
        *,
        actor_id: UUID | None = None,
    ) -> UserRead:
        """Блокирует пользователя.

        Args:
            user_id: Идентификатор пользователя.
            data: Данные блокировки, включая причину.
            actor_id: Идентификатор пользователя, выполняющего блокировку.

        Returns:
            Данные заблокированного пользователя.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        snapshot = await self._mutate_status(
            user_id=user_id,
            actor_id=actor_id,
            action=AuditAction.USER_BLOCKED,
            operation="block_user",
            message="Пользователь был заблокирован.",
            mutator=lambda uow, user: uow.users.mark_blocked(
                user, reason=data.reason, flush=True, refresh=False
            ),
        )
        return _user_read(snapshot)

    async def unblock_user(
        self,
        user_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> UserRead:
        """Разблокирует пользователя.

        Args:
            user_id: Идентификатор пользователя.
            actor_id: Идентификатор пользователя, выполняющего разблокировку.

        Returns:
            Данные разблокированного пользователя.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        snapshot = await self._mutate_status(
            user_id=user_id,
            actor_id=actor_id,
            action=AuditAction.USER_UNBLOCKED,
            operation="unblock_user",
            message="Пользователь был разблокирован.",
            mutator=lambda uow, user: uow.users.unblock(
                user, flush=True, refresh=False
            ),
        )
        return _user_read(snapshot)

    async def reject_user(
        self,
        user_id: UUID,
        data: UserRejectRequest,
        *,
        actor_id: UUID | None = None,
    ) -> UserRead:
        """Отклоняет пользователя.

        Args:
            user_id: Идентификатор пользователя.
            data: Данные отклонения, включая причину.
            actor_id: Идентификатор пользователя, выполняющего отклонение.

        Returns:
            Данные отклоненного пользователя.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        snapshot = await self._mutate_status(
            user_id=user_id,
            actor_id=actor_id,
            action=AuditAction.USER_UPDATED,
            operation="reject_user",
            message="Пользователь был отклонен.",
            mutator=lambda uow, user: uow.users.mark_rejected(
                user, reason=data.reason, flush=True, refresh=False
            ),
        )
        return _user_read(snapshot)

    async def _get_first_admin_id(self, *, operation: str) -> UUID | None:
        """Возвращает идентификатор первичного администратора.

        Args:
            operation: Название операции для контекста ошибок.

        Returns:
            Идентификатор первого администратора или ``None``.

        Raises:
            ServiceError: Если произошла ошибка базы данных.
        """

        try:
            async with self.uow_factory() as uow:
                return await uow.roles.get_first_admin_user_id()
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось определить первичного администратора.",
            ) from exc

    async def delete_user(
        self,
        user_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> UserRead:
        """Мягко удаляет пользователя.

        Переводит пользователя в статус удаления через общую мутацию статуса.

        Args:
            user_id: Идентификатор пользователя.
            actor_id: Идентификатор пользователя, выполняющего удаление.

        Returns:
            Данные мягко удаленного пользователя.

        Raises:
            PermissionServiceError: Если администратор пытается удалить
                собственную учётную запись или учётную запись первичного
                администратора.
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        operation = "delete_user"

        # Администратор не может удалить сам себя.
        if actor_id is not None and actor_id == user_id:
            raise PermissionServiceError(
                "Невозможно удалить собственную учётную запись.",
                reason="cannot_delete_self",
                details={"operation": operation},
            )

        # Учётная запись первичного администратора защищена от удаления.
        first_admin_id = await self._get_first_admin_id(operation=operation)
        if first_admin_id is not None and user_id == first_admin_id:
            raise PermissionServiceError(
                "Невозможно удалить учётную запись первичного администратора.",
                reason="cannot_delete_first_admin",
                details={"operation": operation},
            )

        snapshot = await self._mutate_status(
            user_id=user_id,
            actor_id=actor_id,
            action=AuditAction.USER_DELETED,
            operation=operation,
            message="Пользователь был мягко удален.",
            mutator=lambda uow, user: uow.users.mark_deleted(
                user, flush=True, refresh=False
            ),
        )
        return _user_read(snapshot)

    async def set_email_verified(
        self,
        user_id: UUID,
        *,
        is_verified: bool = True,
        actor_id: UUID | None = None,
    ) -> UserRead:
        """Обновляет признак подтверждения email пользователя.

        Args:
            user_id: Идентификатор пользователя.
            is_verified: Новое значение признака подтверждения email.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                в аудит записывается событие от имени самого пользователя.

        Returns:
            Данные пользователя после обновления признака подтверждения email.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        operation = "set_email_verified"
        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.set_email_verified_by_id(
                    user_id,
                    is_verified=is_verified,
                    flush=True,
                    refresh=True,
                )
                snapshot = _user_snapshot(user)
                await uow.commit()

            await self._safe_log_user_or_system_event(
                actor_id=actor_id or user_id,
                action=AuditAction.USER_UPDATED,
                entity_id=user_id,
                message="Признак подтверждения email пользователя был обновлен.",
                metadata={
                    "operation": operation,
                    "user": _audit_user(snapshot),
                    "is_email_verified": is_verified,
                },
            )
            return _user_read(snapshot)

        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось обновить признак подтверждения email.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при обновлении признака email.",
            ) from exc

    async def change_password(
        self,
        user_id: UUID,
        new_password: str,
        *,
        actor_id: UUID | None = None,
    ) -> UserRead:
        """Изменяет пароль пользователя.

        Проверяет надежность нового пароля, хеширует его и сохраняет новый hash
        пароля в базе данных.

        Args:
            user_id: Идентификатор пользователя.
            new_password: Новый пароль пользователя.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                в аудит записывается событие от имени самого пользователя.

        Returns:
            Данные пользователя после изменения пароля.

        Raises:
            ValidationServiceError: Если новый пароль не прошел проверку надежности.
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        operation = "change_password"
        password_hash = self._hash_password(new_password)
        snapshot: dict[str, Any] = {}

        try:
            async with self.uow_factory() as uow:
                user = await uow.users.update_password_hash_by_id(
                    user_id,
                    password_hash=password_hash,
                    flush=True,
                    refresh=True,
                )
                snapshot = _user_snapshot(user)
                await uow.commit()

            await self._safe_log_user_or_system_event(
                actor_id=actor_id or user_id,
                action=AuditAction.USER_UPDATED,
                entity_id=user_id,
                message="Пароль пользователя был изменен.",
                metadata={"operation": operation, "user": _audit_user(snapshot)},
            )
            return _user_read(snapshot)

        except ValueError as exc:
            raise ValidationServiceError(
                "Пароль пользователя не прошёл проверку.",
                field="new_password",
                reason="invalid_password",
                details={"service": SERVICE_NAME, "operation": operation},
                cause=exc,
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось изменить пароль пользователя.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при изменении пароля пользователя.",
            ) from exc

    async def mark_login(self, user_id: UUID) -> UserRead:
        """Обновляет время последнего входа пользователя.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            Данные пользователя с обновленным last_login_at.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        operation = "mark_login"
        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.update_last_login_by_id(
                    user_id,
                    last_login_at=datetime.now(UTC),
                    flush=True,
                    refresh=True,
                )
                snapshot = _user_snapshot(user)
                await uow.commit()
            return _user_read(snapshot)
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось обновить время последнего входа.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при обновлении времени входа.",
            ) from exc

    async def get_status_counts(self) -> dict[UserStatus, int]:
        """Возвращает количество пользователей по статусам.

        Returns:
            Словарь, где ключ — статус пользователя, а значение — количество
            пользователей с этим статусом.

        Raises:
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "get_status_counts"
        result: dict[UserStatus, int] | None = None
        try:
            async with self.uow_factory() as uow:
                counts = await uow.users.get_status_counts()
                result = {status: counts.get(status, 0) for status in UserStatus}

            if result is None:
                raise ServiceError(
                    "Не удалось получить статистику пользователей.",
                    service=SERVICE_NAME,
                    operation=operation,
                )
            return result
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось получить статистику пользователей.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при получении статистики пользователей.",
            ) from exc

    async def _exists(
        self,
        *,
        operation: str,
        call_name: str,
        value: str,
        exclude_user_id: UUID | None,
    ) -> bool:
        """Проверяет существование email или username.

        Args:
            operation: Название операции для контекста ошибок.
            call_name: Имя проверки: email_exists или username_exists.
            value: Проверяемое значение email или username.
            exclude_user_id: Идентификатор пользователя, которого нужно исключить
                из проверки.

        Returns:
            True, если значение уже существует, иначе False.

        Raises:
            ServiceError: Если произошла ошибка базы данных.
        """

        result = False
        try:
            async with self.uow_factory() as uow:
                if call_name == "email_exists":
                    result = await uow.users.email_exists(
                        value,
                        exclude_user_id=exclude_user_id,
                        include_deleted=True,
                    )
                else:
                    result = await uow.users.username_exists(
                        value,
                        exclude_user_id=exclude_user_id,
                        include_deleted=True,
                    )
            return result
        except DatabaseError as exc:
            raise self._database_error(
                exc,
                operation=operation,
                message="Не удалось проверить уникальность пользователя.",
            ) from exc

    async def _collect_user_snapshots(
        self, *, uow: Any, params: UserQueryParams
    ) -> list[dict[str, Any]]:
        """Загружает снимки пользователей батчами.

        Если указан query, выполняет поиск пользователей. Иначе загружает список
        пользователей. Дополнительно фильтрует снимки по диапазону даты создания.
        Данные читаются страницами до тех пор, пока очередной батч не станет меньше
        REPOSITORY_PAGE_LIMIT.

        Args:
            uow: Unit of Work с репозиторием пользователей.
            params: Параметры поиска и фильтрации пользователей.

        Returns:
            Список снимков пользователей.
        """

        statuses = [params.status] if params.status is not None else None
        offset = 0
        snapshots: list[dict[str, Any]] = []

        while True:
            if params.query:
                users = await uow.users.search_users(
                    params.query,
                    offset=offset,
                    limit=REPOSITORY_PAGE_LIMIT,
                    statuses=statuses,
                    include_deleted=False,
                    only_email_verified=params.is_email_verified,
                )
            else:
                users = await uow.users.list_users(
                    offset=offset,
                    limit=REPOSITORY_PAGE_LIMIT,
                    statuses=statuses,
                    include_deleted=False,
                    only_email_verified=params.is_email_verified,
                    order_by_created_desc=True,
                )

            snapshots.extend(
                snapshot
                for snapshot in (_user_snapshot(user) for user in users)
                if _matches_created_range(snapshot, params)
            )

            if len(users) < REPOSITORY_PAGE_LIMIT:
                break
            offset += REPOSITORY_PAGE_LIMIT

        return snapshots

    async def _mutate_status(
        self,
        *,
        user_id: UUID,
        actor_id: UUID | None,
        action: AuditAction,
        operation: str,
        message: str,
        mutator: Any,
        after: Any | None = None,
    ) -> dict[str, Any]:
        """Выполняет общую мутацию статуса пользователя.

        Загружает пользователя, применяет mutator, опционально выполняет after,
        обновляет ORM-объект, сохраняет изменения и записывает событие аудита.

        Args:
            user_id: Идентификатор пользователя.
            actor_id: Идентификатор пользователя, выполняющего операцию. Если None,
                событие аудита записывается как системное.
            action: Действие аудита.
            operation: Название операции для контекста ошибок.
            message: Сообщение события аудита.
            mutator: Функция, изменяющая пользователя через Unit of Work.
            after: Дополнительная функция, применяемая к пользователю после mutator.

        Returns:
            Снимок пользователя после изменения.

        Raises:
            ServiceError: Если пользователь не найден, произошла ошибка базы данных
                или непредвиденная ошибка сервиса.
        """

        snapshot: dict[str, Any] = {}
        try:
            async with self.uow_factory() as uow:
                user = await uow.users.get_required_user_by_id(user_id)
                user = await mutator(uow, user)
                if after is not None:
                    after(user)
                user = await uow.flush_and_refresh(user)
                snapshot = _user_snapshot(user)
                await uow.commit()

            await self._safe_log_user_or_system_event(
                actor_id=actor_id,
                action=action,
                entity_id=user_id,
                message=message,
                metadata={"operation": operation, "user": _audit_user(snapshot)},
            )
            return snapshot

        except DatabaseError as exc:
            raise self._database_error(
                exc, operation=operation, message="Не удалось изменить пользователя."
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при изменении пользователя.",
            ) from exc

    @staticmethod
    def _hash_password(password: str) -> str:
        """Проверяет пароль и возвращает его хеш.

        Args:
            password: Пароль пользователя.

        Returns:
            Хеш пароля.

        Raises:
            ValueError: Если пароль не прошел проверку надежности.
        """

        require_strong_password(password)
        return hash_password(password)

    @staticmethod
    def _validate_pagination(*, offset: int, limit: int) -> None:
        """Проверяет параметры пагинации списка пользователей.

        Args:
            offset: Смещение страницы.
            limit: Размер страницы.

        Raises:
            ValidationServiceError: Если offset отрицательный или limit находится
                вне диапазона от 1 до MAX_PAGE_LIMIT.
        """

        if offset < 0:
            raise ValidationServiceError(
                "offset не может быть отрицательным.",
                field="offset",
                value=offset,
                reason="negative_offset",
                details={"service": SERVICE_NAME, "operation": "validate_pagination"},
            )
        if limit < 1 or limit > MAX_PAGE_LIMIT:
            raise ValidationServiceError(
                f"limit должен быть от 1 до {MAX_PAGE_LIMIT}.",
                field="limit",
                value=limit,
                reason="invalid_limit",
                details={"service": SERVICE_NAME, "operation": "validate_pagination"},
            )

    @staticmethod
    def _sort_snapshots(
        snapshots: list[dict[str, Any]], *, sort_by: str, sort_desc: bool
    ) -> list[dict[str, Any]]:
        """Сортирует снимки пользователей.

        Если поле сортировки не поддерживается, используется created_at.

        Args:
            snapshots: Список снимков пользователей.
            sort_by: Поле сортировки.
            sort_desc: Нужно ли сортировать по убыванию.

        Returns:
            Отсортированный список снимков пользователей.
        """

        normalized_sort_by = sort_by if sort_by in USER_SORT_FIELDS else "created_at"
        return sorted(
            snapshots,
            key=lambda item: (
                item.get(normalized_sort_by) is None,
                item.get(normalized_sort_by),
            ),
            reverse=sort_desc,
        )

    @staticmethod
    def _require_result(result: Any | None, *, operation: str) -> Any:
        """Возвращает результат или выбрасывает ошибку при его отсутствии.

        Args:
            result: Результат операции.
            operation: Название операции для контекста ошибки.

        Returns:
            Переданный результат, если он не None.

        Raises:
            ServiceError: Если result равен None.
        """

        if result is None:
            raise ServiceError(
                "Сервис пользователей не вернул результат операции.",
                service=SERVICE_NAME,
                operation=operation,
            )
        return result

    @staticmethod
    def _database_error(
        exc: DatabaseError, *, operation: str, message: str
    ) -> ServiceError:
        """Преобразует ошибку базы данных в ошибку сервиса пользователей.

        Args:
            exc: Исходная ошибка базы данных.
            operation: Название операции, во время которой возникла ошибка.
            message: Сообщение для создаваемой ошибки сервиса.

        Returns:
            Ошибка сервисного уровня с контекстом сервиса пользователей.
        """

        return service_error_from_database(
            exc, operation=operation, message=message, service=SERVICE_NAME
        )

    @staticmethod
    def _unexpected_error(
        exc: Exception, *, operation: str, message: str
    ) -> ServiceError:
        """Преобразует непредвиденное исключение в ошибку сервиса.

        Дополнительно пишет исключение в лог с названием операции и типом ошибки.

        Args:
            exc: Исходное исключение.
            operation: Название операции, во время которой возникла ошибка.
            message: Сообщение для лога и создаваемой ошибки сервиса.

        Returns:
            Ошибка сервисного уровня с контекстом исходного исключения.
        """

        logger.exception(
            message,
            extra={"operation": operation, "error_type": exc.__class__.__name__},
        )
        return service_error_from_exception(
            exc, operation=operation, message=message, service=SERVICE_NAME
        )

    async def _safe_log_user_or_system_event(
        self,
        *,
        actor_id: UUID | None,
        action: AuditAction,
        entity_id: UUID | None,
        message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Безопасно записывает событие пользователя в аудит.

        Если actor_id равен None, записывает системное событие. Иначе записывает
        пользовательское событие от имени actor_id. Ошибки аудита не пробрасываются
        выше.

        Args:
            actor_id: Идентификатор пользователя, выполнившего операцию. Если None,
                событие считается системным.
            action: Действие аудита.
            entity_id: Идентификатор пользователя, связанного с событием.
            message: Сообщение события аудита.
            metadata: Дополнительные метаданные события.
        """

        try:
            if actor_id is None:
                await self.audit_service.log_system_event(
                    action=action,
                    entity_type=AuditResourceType.USER.value,
                    entity_id=entity_id,
                    resource_type=AuditResourceType.USER,
                    message=message,
                    metadata=metadata,
                )
                return
            await self.audit_service.log_user_event(
                user_id=actor_id,
                action=action,
                entity_type=AuditResourceType.USER.value,
                entity_id=entity_id,
                resource_type=AuditResourceType.USER,
                message=message,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита сервиса пользователей.",
                extra={
                    "action": action.value,
                    "entity_id": str(entity_id) if entity_id else None,
                    "actor_id": str(actor_id) if actor_id else None,
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )


def _user_snapshot(user: User) -> dict[str, Any]:
    """Создает снимок пользователя.

    Args:
        user: ORM-модель пользователя.

    Returns:
        Словарь с идентификатором, email, username, статусом, признаком
        подтверждения email, временем последнего входа, датами изменения статуса,
        причинами блокировки или отклонения и временными метками.
    """

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "status": user.status,
        "is_email_verified": user.is_email_verified,
        "last_login_at": user.last_login_at,
        "approved_at": user.approved_at,
        "blocked_at": user.blocked_at,
        "rejected_at": user.rejected_at,
        "deleted_at": user.deleted_at,
        "block_reason": user.block_reason,
        "rejection_reason": user.rejection_reason,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def _role_snapshot(role: Role) -> dict[str, Any]:
    """Создает снимок роли.

    Args:
        role: ORM-модель роли.

    Returns:
        Словарь с идентификатором, именем, кодом, отображаемым названием,
        системным признаком и активностью роли.
    """

    return {
        "id": role.id,
        "name": role.name,
        "code": role.code,
        "display_name": role.display_name,
        "is_system": role.is_system,
        "is_active": role.is_active,
    }


def _user_read(snapshot: Mapping[str, Any]) -> UserRead:
    """Преобразует снимок пользователя в схему чтения.

    Args:
        snapshot: Снимок пользователя.

    Returns:
        Схема чтения пользователя.
    """

    return UserRead.model_validate(dict(snapshot))


def _user_list_item(snapshot: Mapping[str, Any]) -> UserListItem:
    """Преобразует снимок пользователя в элемент списка.

    Args:
        snapshot: Снимок пользователя.

    Returns:
        Элемент списка пользователей.
    """

    return UserListItem.model_validate(dict(snapshot))


def _user_with_roles_read(
    snapshot: Mapping[str, Any], roles: list[Role]
) -> UserWithRolesRead:
    """Преобразует снимок пользователя и роли в расширенную схему.

    Args:
        snapshot: Снимок пользователя.
        roles: Список ролей пользователя.

    Returns:
        Схема пользователя со списком ролей.
    """

    payload = dict(snapshot)
    payload["roles"] = [_role_list_item(role) for role in roles]
    return UserWithRolesRead.model_validate(payload)


def _current_user_read(
    snapshot: Mapping[str, Any], roles: list[Role]
) -> CurrentUserRead:
    """Преобразует снимок пользователя и активные роли в схему текущего пользователя.

    Args:
        snapshot: Снимок пользователя.
        roles: Список активных ролей пользователя.

    Returns:
        Схема текущего пользователя.
    """

    payload = dict(snapshot)
    payload["roles"] = [_role_list_item(role) for role in roles]
    return CurrentUserRead.model_validate(payload)


def _role_list_item(role: Role) -> RoleListItem:
    """Преобразует роль в элемент списка ролей.

    Args:
        role: ORM-модель роли.

    Returns:
        Элемент списка ролей.
    """

    return RoleListItem.model_validate(_role_snapshot(role))


def _audit_user(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует метаданные пользователя для аудита.

    Args:
        snapshot: Снимок пользователя.

    Returns:
        Словарь с идентификатором, email, username и статусом пользователя.
    """

    return {
        "id": str(snapshot["id"]),
        "email": str(snapshot["email"]),
        "username": snapshot["username"],
        "status": snapshot["status"].value
        if isinstance(snapshot["status"], UserStatus)
        else str(snapshot["status"]),
    }


def _matches_created_range(
    snapshot: Mapping[str, Any], params: UserQueryParams
) -> bool:
    """Проверяет соответствие пользователя диапазону даты создания.

    Args:
        snapshot: Снимок пользователя.
        params: Параметры фильтрации пользователей.

    Returns:
        True, если дата создания пользователя попадает в заданный диапазон
        или дата создания отсутствует.
    """

    created_at = snapshot.get("created_at")
    if not isinstance(created_at, datetime):
        return True
    if params.created_from is not None and created_at < params.created_from:
        return False
    if params.created_to is not None and created_at > params.created_to:
        return False
    return True


def get_users_service(
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    audit_service: AuditService | None = None,
) -> UsersService:
    """Создаёт экземпляр сервиса пользователей.

    Args:
        uow_factory: Фабрика UnitOfWork. Если не передана, сервис создаст
            стандартную фабрику самостоятельно.
        audit_service: Сервис аудита. Если не передан, будет создан стандартный
            сервис аудита.

    Returns:
        Экземпляр `UsersService`.
    """

    return UsersService(uow_factory=uow_factory, audit_service=audit_service)
