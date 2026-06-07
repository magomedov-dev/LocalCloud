from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
)
from database.models.enums import SystemRole
from database.models.roles import Role, UserRole
from database.models.users import User
from database.repositories.base import BaseRepository


class RolesRepository(BaseRepository[Role]):
    """Репозиторий ролей и назначений ролей пользователям.

    Инкапсулирует операции получения, создания, обновления, активации,
    деактивации и удаления ролей, а также операции назначения, удаления,
    замены и проверки ролей пользователей.

    Работает с моделями ``Role`` и ``UserRole`` через асинхронную
    SQLAlchemy-сессию.

    Репозиторий не вызывает ``commit``. Все изменения фиксируются на уровне
    сервисов или Unit of Work.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий ролей.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=Role)

    # ------------------------------------------------------------------
    # Получение ролей
    # ------------------------------------------------------------------

    async def get_role_by_id(
        self,
        role_id: uuid.UUID,
    ) -> Role | None:
        """Возвращает роль по идентификатору.

        Args:
            role_id: Идентификатор роли.

        Returns:
            Найденная роль или ``None``.
        """

        return await self.get_by_id(role_id)

    async def get_required_role_by_id(
        self,
        role_id: uuid.UUID,
    ) -> Role:
        """Возвращает обязательную роль по идентификатору.

        Args:
            role_id: Идентификатор роли.

        Returns:
            Найденная роль.

        Raises:
            EntityNotFoundError: Если роль не найдена.
        """

        return await self.get_required_by_id(role_id)

    async def get_role_by_name(
        self,
        name: str,
        *,
        case_sensitive: bool = False,
    ) -> Role | None:
        """Возвращает роль по системному имени.

        Args:
            name: Системное имя роли.
            case_sensitive: Учитывать ли регистр при поиске.

        Returns:
            Найденная роль или ``None``.
        """

        normalized_name = self._normalize_role_value(name)

        if not normalized_name:
            return None

        if case_sensitive:
            statement = select(Role).where(Role.name == normalized_name)
        else:
            statement = select(Role).where(
                func.lower(Role.name) == normalized_name.lower(),
            )

        return await self.scalar_one_or_none(
            statement,
            operation="get_role_by_name",
        )

    async def get_required_role_by_name(
        self,
        name: str,
        *,
        case_sensitive: bool = False,
    ) -> Role:
        """Возвращает обязательную роль по системному имени.

        Args:
            name: Системное имя роли.
            case_sensitive: Учитывать ли регистр при поиске.

        Returns:
            Найденная роль.

        Raises:
            EntityNotFoundError: Если роль не найдена.
        """

        role = await self.get_role_by_name(
            name,
            case_sensitive=case_sensitive,
        )

        if role is None:
            raise EntityNotFoundError(
                "Role",
                lookup={"name": name},
                repository=self.repository_name,
            )

        return role

    async def get_role_by_code(
        self,
        code: str | SystemRole,
        *,
        case_sensitive: bool = False,
    ) -> Role | None:
        """Возвращает роль по стабильному коду.

        Args:
            code: Код роли. Можно передать строку или ``SystemRole``.
            case_sensitive: Учитывать ли регистр при поиске.

        Returns:
            Найденная роль или ``None``.
        """

        normalized_code = self._normalize_role_value(code)

        if not normalized_code:
            return None

        if case_sensitive:
            statement = select(Role).where(Role.code == normalized_code)
        else:
            statement = select(Role).where(
                func.lower(Role.code) == normalized_code.lower(),
            )

        return await self.scalar_one_or_none(
            statement,
            operation="get_role_by_code",
        )

    async def get_required_role_by_code(
        self,
        code: str | SystemRole,
        *,
        case_sensitive: bool = False,
    ) -> Role:
        """Возвращает обязательную роль по стабильному коду.

        Args:
            code: Код роли. Можно передать строку или ``SystemRole``.
            case_sensitive: Учитывать ли регистр при поиске.

        Returns:
            Найденная роль.

        Raises:
            EntityNotFoundError: Если роль не найдена.
        """

        role = await self.get_role_by_code(
            code,
            case_sensitive=case_sensitive,
        )

        if role is None:
            raise EntityNotFoundError(
                "Role",
                lookup={"code": str(code)},
                repository=self.repository_name,
            )

        return role

    async def get_admin_role(self) -> Role | None:
        """Возвращает системную роль администратора.

        Returns:
            Роль администратора или ``None``.
        """

        return await self.get_role_by_code(SystemRole.ADMIN)

    async def get_user_role_model(self) -> Role | None:
        """Возвращает системную роль обычного пользователя.

        Returns:
            Роль обычного пользователя или ``None``.
        """

        return await self.get_role_by_code(SystemRole.USER)

    async def get_required_admin_role(self) -> Role:
        """Возвращает обязательную системную роль администратора.

        Returns:
            Роль администратора.

        Raises:
            EntityNotFoundError: Если роль администратора не найдена.
        """

        return await self.get_required_role_by_code(SystemRole.ADMIN)

    async def get_required_user_role_model(self) -> Role:
        """Возвращает обязательную системную роль обычного пользователя.

        Returns:
            Роль обычного пользователя.

        Raises:
            EntityNotFoundError: Если роль пользователя не найдена.
        """

        return await self.get_required_role_by_code(SystemRole.USER)

    async def role_exists(
        self,
        *,
        name: str | None = None,
        code: str | SystemRole | None = None,
        exclude_role_id: uuid.UUID | None = None,
        case_sensitive: bool = False,
    ) -> bool:
        """Проверяет существование роли по имени или коду.

        Args:
            name: Системное имя роли.
            code: Код роли. Можно передать строку или ``SystemRole``.
            exclude_role_id: Идентификатор роли, которую нужно исключить из
                проверки.
            case_sensitive: Учитывать ли регистр при проверке.

        Returns:
            ``True``, если роль с указанным именем или кодом существует,
            иначе ``False``.

        Raises:
            InvalidQueryError: Если не переданы ни ``name``, ни ``code``.
        """

        if name is None and code is None:
            raise InvalidQueryError(
                "Для проверки существования роли нужно указать name или code.",
                repository=self.repository_name,
                operation="role_exists",
            )

        conditions: list[ColumnElement[bool]] = []

        if name is not None:
            normalized_name = self._normalize_role_value(name)
            if case_sensitive:
                conditions.append(Role.name == normalized_name)
            else:
                conditions.append(func.lower(Role.name) == normalized_name.lower())

        if code is not None:
            normalized_code = self._normalize_role_value(code)
            if case_sensitive:
                conditions.append(Role.code == normalized_code)
            else:
                conditions.append(func.lower(Role.code) == normalized_code.lower())

        if exclude_role_id is not None:
            conditions.append(Role.id != exclude_role_id)

        return await self.exists(*conditions)

    # ------------------------------------------------------------------
    # Создание и изменение ролей
    # ------------------------------------------------------------------

    async def create_role(
        self,
        *,
        name: str,
        code: str | SystemRole | None = None,
        display_name: str,
        description: str | None = None,
        is_system: bool = False,
        is_active: bool = True,
        flush: bool = True,
        refresh: bool = False,
        check_duplicate: bool = True,
    ) -> Role:
        """Создаёт новую роль.

        Args:
            name: Системное имя роли.
            code: Стабильный код роли. Если не передан, используется ``name``.
            display_name: Отображаемое имя роли.
            description: Описание роли.
            is_system: Признак системной роли.
            is_active: Признак активности роли.
            flush: Выполнить ``flush`` после создания.
            refresh: Обновить роль из базы после ``flush``.
            check_duplicate: Проверять существование роли с таким именем или
                кодом перед созданием.

        Returns:
            Созданная роль.

        Raises:
            InvalidQueryError: Если имя, код или отображаемое имя пустые.
            DuplicateEntityError: Если роль с таким ``name`` или ``code`` уже
                существует.
        """

        normalized_name = self._normalize_role_value(name)
        normalized_code = self._normalize_role_value(code or normalized_name)
        normalized_display_name = display_name.strip()

        if not normalized_name:
            raise InvalidQueryError(
                "Имя роли не может быть пустым.",
                repository=self.repository_name,
                operation="create_role",
            )

        if not normalized_code:
            raise InvalidQueryError(
                "Код роли не может быть пустым.",
                repository=self.repository_name,
                operation="create_role",
            )

        if not normalized_display_name:
            raise InvalidQueryError(
                "Отображаемое имя роли не может быть пустым.",
                repository=self.repository_name,
                operation="create_role",
            )

        if check_duplicate:
            if await self.role_exists(name=normalized_name):
                raise DuplicateEntityError(
                    "Role",
                    field="name",
                    value=normalized_name,
                    repository=self.repository_name,
                )

            if await self.role_exists(code=normalized_code):
                raise DuplicateEntityError(
                    "Role",
                    field="code",
                    value=normalized_code,
                    repository=self.repository_name,
                )

        role = Role(
            name=normalized_name,
            code=normalized_code,
            display_name=normalized_display_name,
            description=description.strip() if description else None,
            is_system=is_system,
            is_active=is_active,
        )

        return await self.create(
            role,
            flush=flush,
            refresh=refresh,
        )

    async def ensure_system_roles(
        self,
        *,
        flush: bool = True,
    ) -> list[Role]:
        """Создаёт базовые системные роли, если они отсутствуют.

        Args:
            flush: Выполнить ``flush`` после создания недостающих ролей.

        Returns:
            Список существующих или созданных системных ролей.
        """

        roles: list[Role] = []

        admin_role = await self.get_role_by_code(SystemRole.ADMIN)
        if admin_role is None:
            admin_role = Role.create_admin_role()
            self.session.add(admin_role)

        roles.append(admin_role)

        user_role = await self.get_role_by_code(SystemRole.USER)
        if user_role is None:
            user_role = Role.create_user_role()
            self.session.add(user_role)

        roles.append(user_role)

        if flush:
            await self.flush()

        return roles

    async def update_role(
        self,
        role: Role,
        values: dict[str, Any],
        *,
        flush: bool = True,
        refresh: bool = False,
        exclude_none: bool = False,
    ) -> Role:
        """Обновляет роль.

        Для системных ролей запрещено менять ``name``, ``code`` и ``is_system``.

        Args:
            role: Роль для обновления.
            values: Словарь обновляемых полей.
            flush: Выполнить ``flush`` после изменения.
            refresh: Обновить роль из базы после ``flush``.
            exclude_none: Не применять значения ``None``.

        Returns:
            Обновлённая роль.

        Raises:
            InvalidQueryError: Если выполняется попытка изменить защищённые
                поля системной роли.
        """

        protected_system_fields = {"name", "code", "is_system"}

        if role.is_system and protected_system_fields.intersection(values):
            raise InvalidQueryError(
                "Нельзя изменять защищённые поля системной роли.",
                repository=self.repository_name,
                operation="update_role",
                details={
                    "role_id": str(role.id),
                    "protected_fields": sorted(protected_system_fields),
                    "received_fields": sorted(values.keys()),
                },
            )

        normalized_values = dict(values)

        if "name" in normalized_values and normalized_values["name"] is not None:
            normalized_values["name"] = self._normalize_role_value(
                normalized_values["name"],
            )

        if "code" in normalized_values and normalized_values["code"] is not None:
            normalized_values["code"] = self._normalize_role_value(
                normalized_values["code"],
            )

        if (
            "display_name" in normalized_values
            and normalized_values["display_name"] is not None
        ):
            normalized_values["display_name"] = str(
                normalized_values["display_name"],
            ).strip()

        if (
            "description" in normalized_values
            and normalized_values["description"] is not None
        ):
            normalized_values["description"] = str(
                normalized_values["description"],
            ).strip()

        return await self.update(
            role,
            normalized_values,
            flush=flush,
            refresh=refresh,
            exclude_none=exclude_none,
            allowed_fields={
                "name",
                "code",
                "display_name",
                "description",
                "is_system",
                "is_active",
            },
        )

    async def activate_role(
        self,
        role_id: uuid.UUID,
        *,
        flush: bool = True,
    ) -> Role:
        """Активирует роль.

        Args:
            role_id: Идентификатор роли.
            flush: Выполнить ``flush`` после изменения.

        Returns:
            Активированная роль.

        Raises:
            EntityNotFoundError: Если роль не найдена.
        """

        role = await self.get_required_role_by_id(role_id)
        role.activate()

        if flush:
            await self.flush()

        return role

    async def deactivate_role(
        self,
        role_id: uuid.UUID,
        *,
        flush: bool = True,
        forbid_system_role: bool = True,
    ) -> Role:
        """Деактивирует роль.

        Args:
            role_id: Идентификатор роли.
            flush: Выполнить ``flush`` после изменения.
            forbid_system_role: Если ``True``, запрещает деактивацию системной
                роли.

        Returns:
            Деактивированная роль.

        Raises:
            EntityNotFoundError: Если роль не найдена.
            InvalidQueryError: Если выполняется попытка деактивировать
                системную роль.
        """

        role = await self.get_required_role_by_id(role_id)

        if forbid_system_role and role.is_system:
            raise InvalidQueryError(
                "Системную роль нельзя деактивировать.",
                repository=self.repository_name,
                operation="deactivate_role",
                details={"role_id": str(role_id), "code": role.code},
            )

        role.deactivate()

        if flush:
            await self.flush()

        return role

    async def delete_role(
        self,
        role_id: uuid.UUID,
        *,
        flush: bool = True,
        forbid_system_role: bool = True,
    ) -> bool:
        """Физически удаляет роль.

        Обычно пользовательские роли лучше деактивировать, а не удалять.

        Args:
            role_id: Идентификатор роли.
            flush: Выполнить ``flush`` после удаления.
            forbid_system_role: Если ``True``, запрещает удаление системной роли.

        Returns:
            ``True``, если роль удалена.

        Raises:
            EntityNotFoundError: Если роль не найдена.
            InvalidQueryError: Если выполняется попытка удалить системную роль.
        """

        role = await self.get_required_role_by_id(role_id)

        if forbid_system_role and role.is_system:
            raise InvalidQueryError(
                "Системную роль нельзя удалить.",
                repository=self.repository_name,
                operation="delete_role",
                details={"role_id": str(role_id), "code": role.code},
            )

        await self.delete(role, flush=flush)
        return True

    async def list_roles(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        only_active: bool | None = None,
        only_system: bool | None = None,
        search: str | None = None,
        order_by_name: bool = True,
    ) -> list[Role]:
        """Возвращает список ролей с пагинацией и фильтрами.

        Args:
            offset: Смещение выборки.
            limit: Максимальное количество записей.
            only_active: Фильтр по активности роли.
            only_system: Фильтр по признаку системной роли.
            search: Поисковая строка по имени, коду или отображаемому имени.
            order_by_name: Если ``True``, сортирует по имени роли, иначе —
                по дате создания.

        Returns:
            Список ролей.

        Raises:
            InvalidQueryError: Если параметры пагинации некорректны.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = select(Role)

        if only_active is not None:
            statement = statement.where(Role.is_active == only_active)

        if only_system is not None:
            statement = statement.where(Role.is_system == only_system)

        if search:
            normalized_search = f"%{search.strip()}%"
            statement = statement.where(
                Role.name.ilike(normalized_search)
                | Role.code.ilike(normalized_search)
                | Role.display_name.ilike(normalized_search),
            )

        if order_by_name:
            statement = statement.order_by(Role.name.asc())
        else:
            statement = statement.order_by(Role.created_at.asc())

        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(
            statement,
            operation="list_roles",
        )

    # ------------------------------------------------------------------
    # Назначение ролей пользователю
    # ------------------------------------------------------------------

    async def assign_role(
        self,
        *,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        assigned_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
        check_role_exists: bool = True,
        ignore_existing: bool = True,
    ) -> UserRole:
        """Назначает роль пользователю.

        Args:
            user_id: Идентификатор пользователя.
            role_id: Идентификатор роли.
            assigned_by: Идентификатор пользователя, назначившего роль.
            flush: Выполнить ``flush`` после назначения.
            refresh: Обновить назначение из базы после ``flush``.
            check_user_exists: Проверять существование пользователя.
            check_role_exists: Проверять существование роли.
            ignore_existing: Если ``True``, возвращает существующее назначение
                вместо ошибки.

        Returns:
            Запись назначения роли пользователю.

        Raises:
            EntityNotFoundError: Если пользователь или роль не найдены.
            DuplicateEntityError: Если роль уже назначена пользователю и
                ``ignore_existing`` равен ``False``.
        """

        if check_user_exists:
            await self._ensure_user_exists(user_id)

        if check_role_exists:
            await self.get_required_role_by_id(role_id)

        existing_user_role = await self.get_user_role(
            user_id=user_id,
            role_id=role_id,
        )

        if existing_user_role is not None:
            if ignore_existing:
                return existing_user_role

            raise DuplicateEntityError(
                "UserRole",
                field="user_id,role_id",
                value=f"{user_id},{role_id}",
                repository=self.repository_name,
                message="Роль уже назначена пользователю.",
            )

        user_role = UserRole(
            user_id=user_id,
            role_id=role_id,
            assigned_by=assigned_by,
        )

        try:
            self.session.add(user_role)

            if flush:
                await self.flush()

            if refresh:
                await self.session.refresh(user_role)

            return user_role

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="assign_role",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="assign_role",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "role_id": str(role_id),
                    "assigned_by": str(assigned_by) if assigned_by else None,
                },
                cause=exc,
            ) from exc

    async def assign_role_by_name(
        self,
        *,
        user_id: uuid.UUID,
        role_name: str,
        assigned_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
        ignore_existing: bool = True,
    ) -> UserRole:
        """Назначает пользователю роль по имени.

        Args:
            user_id: Идентификатор пользователя.
            role_name: Системное имя роли.
            assigned_by: Идентификатор пользователя, назначившего роль.
            flush: Выполнить ``flush`` после назначения.
            refresh: Обновить назначение из базы после ``flush``.
            check_user_exists: Проверять существование пользователя.
            ignore_existing: Если ``True``, возвращает существующее назначение
                вместо ошибки.

        Returns:
            Запись назначения роли пользователю.

        Raises:
            EntityNotFoundError: Если пользователь или роль не найдены.
            DuplicateEntityError: Если роль уже назначена пользователю и
                ``ignore_existing`` равен ``False``.
        """

        role = await self.get_required_role_by_name(role_name)

        return await self.assign_role(
            user_id=user_id,
            role_id=role.id,
            assigned_by=assigned_by,
            flush=flush,
            refresh=refresh,
            check_user_exists=check_user_exists,
            check_role_exists=False,
            ignore_existing=ignore_existing,
        )

    async def assign_role_by_code(
        self,
        *,
        user_id: uuid.UUID,
        role_code: str | SystemRole,
        assigned_by: uuid.UUID | None = None,
        flush: bool = True,
        refresh: bool = False,
        check_user_exists: bool = True,
        ignore_existing: bool = True,
    ) -> UserRole:
        """Назначает пользователю роль по коду.

        Args:
            user_id: Идентификатор пользователя.
            role_code: Код роли. Можно передать строку или ``SystemRole``.
            assigned_by: Идентификатор пользователя, назначившего роль.
            flush: Выполнить ``flush`` после назначения.
            refresh: Обновить назначение из базы после ``flush``.
            check_user_exists: Проверять существование пользователя.
            ignore_existing: Если ``True``, возвращает существующее назначение
                вместо ошибки.

        Returns:
            Запись назначения роли пользователю.

        Raises:
            EntityNotFoundError: Если пользователь или роль не найдены.
            DuplicateEntityError: Если роль уже назначена пользователю и
                ``ignore_existing`` равен ``False``.
        """

        role = await self.get_required_role_by_code(role_code)

        return await self.assign_role(
            user_id=user_id,
            role_id=role.id,
            assigned_by=assigned_by,
            flush=flush,
            refresh=refresh,
            check_user_exists=check_user_exists,
            check_role_exists=False,
            ignore_existing=ignore_existing,
        )

    async def assign_admin_role(
        self,
        *,
        user_id: uuid.UUID,
        assigned_by: uuid.UUID | None = None,
        flush: bool = True,
    ) -> UserRole:
        """Назначает пользователю роль администратора.

        Args:
            user_id: Идентификатор пользователя.
            assigned_by: Идентификатор пользователя, назначившего роль.
            flush: Выполнить ``flush`` после назначения.

        Returns:
            Запись назначения роли администратора пользователю.

        Raises:
            EntityNotFoundError: Если пользователь или роль администратора
                не найдены.
            DuplicateEntityError: Если роль уже назначена пользователю.
        """

        return await self.assign_role_by_code(
            user_id=user_id,
            role_code=SystemRole.ADMIN,
            assigned_by=assigned_by,
            flush=flush,
        )

    async def assign_user_role(
        self,
        *,
        user_id: uuid.UUID,
        assigned_by: uuid.UUID | None = None,
        flush: bool = True,
    ) -> UserRole:
        """Назначает пользователю базовую роль пользователя.

        Args:
            user_id: Идентификатор пользователя.
            assigned_by: Идентификатор пользователя, назначившего роль.
            flush: Выполнить ``flush`` после назначения.

        Returns:
            Запись назначения базовой роли пользователю.

        Raises:
            EntityNotFoundError: Если пользователь или базовая роль не найдены.
            DuplicateEntityError: Если роль уже назначена пользователю.
        """

        return await self.assign_role_by_code(
            user_id=user_id,
            role_code=SystemRole.USER,
            assigned_by=assigned_by,
            flush=flush,
        )

    async def remove_role(
        self,
        *,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        flush: bool = True,
        required: bool = False,
    ) -> bool:
        """Удаляет назначение роли у пользователя.

        Args:
            user_id: Идентификатор пользователя.
            role_id: Идентификатор роли.
            flush: Выполнить ``flush`` после удаления.
            required: Если ``True``, отсутствие назначения считается ошибкой.

        Returns:
            ``True``, если назначение было удалено. ``False``, если назначение
            не найдено и ``required`` равен ``False``.

        Raises:
            EntityNotFoundError: Если назначение не найдено и ``required``
                равен ``True``.
        """

        user_role = await self.get_user_role(
            user_id=user_id,
            role_id=role_id,
        )

        if user_role is None:
            if required:
                raise EntityNotFoundError(
                    "UserRole",
                    lookup={
                        "user_id": user_id,
                        "role_id": role_id,
                    },
                    repository=self.repository_name,
                )

            return False

        try:
            await self.session.delete(user_role)

            if flush:
                await self.flush()

            return True

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="remove_role",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="remove_role",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "role_id": str(role_id),
                },
                cause=exc,
            ) from exc

    async def remove_role_by_name(
        self,
        *,
        user_id: uuid.UUID,
        role_name: str,
        flush: bool = True,
        required: bool = False,
    ) -> bool:
        """Удаляет роль у пользователя по имени роли.

        Args:
            user_id: Идентификатор пользователя.
            role_name: Системное имя роли.
            flush: Выполнить ``flush`` после удаления.
            required: Если ``True``, отсутствие назначения считается ошибкой.

        Returns:
            ``True``, если назначение было удалено. ``False``, если назначение
            не найдено и ``required`` равен ``False``.

        Raises:
            EntityNotFoundError: Если роль или назначение не найдены.
        """

        role = await self.get_required_role_by_name(role_name)

        return await self.remove_role(
            user_id=user_id,
            role_id=role.id,
            flush=flush,
            required=required,
        )

    async def remove_role_by_code(
        self,
        *,
        user_id: uuid.UUID,
        role_code: str | SystemRole,
        flush: bool = True,
        required: bool = False,
    ) -> bool:
        """Удаляет роль у пользователя по коду роли.

        Args:
            user_id: Идентификатор пользователя.
            role_code: Код роли. Можно передать строку или ``SystemRole``.
            flush: Выполнить ``flush`` после удаления.
            required: Если ``True``, отсутствие назначения считается ошибкой.

        Returns:
            ``True``, если назначение было удалено. ``False``, если назначение
            не найдено и ``required`` равен ``False``.

        Raises:
            EntityNotFoundError: Если роль или назначение не найдены.
        """

        role = await self.get_required_role_by_code(role_code)

        return await self.remove_role(
            user_id=user_id,
            role_id=role.id,
            flush=flush,
            required=required,
        )

    async def user_has_role(
        self,
        *,
        user_id: uuid.UUID,
        role_id: uuid.UUID | None = None,
        role_name: str | None = None,
        role_code: str | SystemRole | None = None,
        only_active_roles: bool = True,
    ) -> bool:
        """Проверяет, есть ли у пользователя указанная роль.

        Роль можно указать через ``role_id``, ``role_name`` или ``role_code``.

        Args:
            user_id: Идентификатор пользователя.
            role_id: Идентификатор роли.
            role_name: Системное имя роли.
            role_code: Код роли. Можно передать строку или ``SystemRole``.
            only_active_roles: Учитывать только активные роли.

        Returns:
            ``True``, если у пользователя есть указанная роль, иначе ``False``.

        Raises:
            InvalidQueryError: Если указано не ровно одно поле роли.
        """

        provided = [
            role_id is not None,
            role_name is not None,
            role_code is not None,
        ]

        if sum(provided) != 1:
            raise InvalidQueryError(
                "Нужно указать ровно один параметр: role_id, role_name или role_code.",
                repository=self.repository_name,
                operation="user_has_role",
            )

        try:
            statement = (
                select(UserRole)
                .join(Role, Role.id == UserRole.role_id)
                .where(UserRole.user_id == user_id)
            )

            if role_id is not None:
                statement = statement.where(UserRole.role_id == role_id)

            if role_name is not None:
                normalized_name = self._normalize_role_value(role_name)
                statement = statement.where(
                    func.lower(Role.name) == normalized_name.lower(),
                )

            if role_code is not None:
                normalized_code = self._normalize_role_value(role_code)
                statement = statement.where(
                    func.lower(Role.code) == normalized_code.lower(),
                )

            if only_active_roles:
                statement = statement.where(Role.is_active.is_(True))

            result = await self.session.execute(
                select(statement.exists()),
            )

            return bool(result.scalar_one())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="user_has_role",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "role_id": str(role_id) if role_id else None,
                    "role_name": role_name,
                    "role_code": str(role_code) if role_code else None,
                },
                cause=exc,
            ) from exc

    async def user_is_admin(
        self,
        user_id: uuid.UUID,
    ) -> bool:
        """Проверяет, имеет ли пользователь роль администратора.

        Args:
            user_id: Идентификатор пользователя.

        Returns:
            ``True``, если пользователь имеет активную роль администратора,
            иначе ``False``.
        """

        return await self.user_has_role(
            user_id=user_id,
            role_code=SystemRole.ADMIN,
            only_active_roles=True,
        )

    # ------------------------------------------------------------------
    # Получение назначений ролей
    # ------------------------------------------------------------------

    async def get_user_role(
        self,
        *,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
    ) -> UserRole | None:
        """Возвращает назначение роли пользователю.

        Args:
            user_id: Идентификатор пользователя.
            role_id: Идентификатор роли.

        Returns:
            Найденное назначение роли или ``None``.
        """

        try:
            statement = select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )

            result = await self.session.execute(statement)

            return result.scalar_one_or_none()

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_user_role",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "role_id": str(role_id),
                },
                cause=exc,
            ) from exc

    async def exists_user_role(
        self,
        *,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
    ) -> bool:
        """Проверяет существование назначения роли пользователю.

        Args:
            user_id: Идентификатор пользователя.
            role_id: Идентификатор роли.

        Returns:
            ``True``, если назначение роли существует, иначе ``False``.
        """

        try:
            statement = select(
                select(UserRole)
                .where(
                    UserRole.user_id == user_id,
                    UserRole.role_id == role_id,
                )
                .exists(),
            )

            result = await self.session.execute(statement)

            return bool(result.scalar_one())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="exists_user_role",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "role_id": str(role_id),
                },
                cause=exc,
            ) from exc

    async def get_user_roles(
        self,
        user_id: uuid.UUID,
        *,
        only_active_roles: bool = True,
        order_by_name: bool = True,
    ) -> list[Role]:
        """Возвращает роли пользователя.

        Args:
            user_id: Идентификатор пользователя.
            only_active_roles: Возвращать только активные роли.
            order_by_name: Если ``True``, сортирует роли по имени. Иначе
                сортирует по дате назначения.

        Returns:
            Список ролей пользователя.
        """

        try:
            statement = (
                select(Role)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id)
            )

            if only_active_roles:
                statement = statement.where(Role.is_active.is_(True))

            if order_by_name:
                statement = statement.order_by(Role.name.asc())
            else:
                statement = statement.order_by(UserRole.assigned_at.asc())

            result = await self.session.execute(statement)

            return list(result.scalars().unique().all())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_user_roles",
                reason=str(exc),
                details={"user_id": str(user_id)},
                cause=exc,
            ) from exc

    async def get_user_role_assignments(
        self,
        user_id: uuid.UUID,
        *,
        order_by_assigned_at: bool = True,
    ) -> list[UserRole]:
        """Возвращает записи назначений ролей пользователя.

        Args:
            user_id: Идентификатор пользователя.
            order_by_assigned_at: Если ``True``, сортирует назначения по дате
                назначения.

        Returns:
            Список записей назначений ролей пользователя.
        """

        try:
            statement = select(UserRole).where(UserRole.user_id == user_id)

            if order_by_assigned_at:
                statement = statement.order_by(UserRole.assigned_at.asc())

            result = await self.session.execute(statement)

            return list(result.scalars().all())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_user_role_assignments",
                reason=str(exc),
                details={"user_id": str(user_id)},
                cause=exc,
            ) from exc

    async def get_user_role_names(
        self,
        user_id: uuid.UUID,
        *,
        only_active_roles: bool = True,
        order_by_name: bool = True,
    ) -> list[str]:
        """Возвращает системные имена ролей пользователя.

        Args:
            user_id: Идентификатор пользователя.
            only_active_roles: Возвращать только активные роли.
            order_by_name: Если ``True``, сортирует роли по имени. Иначе
                сортирует по дате назначения.

        Returns:
            Список системных имён ролей пользователя.
        """

        try:
            statement = (
                select(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id)
            )

            if only_active_roles:
                statement = statement.where(Role.is_active.is_(True))

            if order_by_name:
                statement = statement.order_by(Role.name.asc())
            else:
                statement = statement.order_by(UserRole.assigned_at.asc())

            result = await self.session.execute(statement)

            return list(result.scalars().all())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_user_role_names",
                reason=str(exc),
                details={"user_id": str(user_id)},
                cause=exc,
            ) from exc

    async def get_user_role_codes(
        self,
        user_id: uuid.UUID,
        *,
        only_active_roles: bool = True,
        order_by_code: bool = True,
    ) -> list[str]:
        """Возвращает коды ролей пользователя.

        Args:
            user_id: Идентификатор пользователя.
            only_active_roles: Возвращать только активные роли.
            order_by_code: Если ``True``, сортирует роли по коду. Иначе
                сортирует по дате назначения.

        Returns:
            Список кодов ролей пользователя.
        """

        try:
            statement = (
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id)
            )

            if only_active_roles:
                statement = statement.where(Role.is_active.is_(True))

            if order_by_code:
                statement = statement.order_by(Role.code.asc())
            else:
                statement = statement.order_by(UserRole.assigned_at.asc())

            result = await self.session.execute(statement)

            return list(result.scalars().all())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_user_role_codes",
                reason=str(exc),
                details={"user_id": str(user_id)},
                cause=exc,
            ) from exc

    async def get_users_by_role(
        self,
        *,
        role_id: uuid.UUID | None = None,
        role_name: str | None = None,
        role_code: str | SystemRole | None = None,
        only_active_users: bool | None = None,
        offset: int = 0,
        limit: int = 100,
        order_by_username: bool = True,
    ) -> list[User]:
        """Возвращает пользователей, которым назначена указанная роль.

        Роль можно указать через ``role_id``, ``role_name`` или ``role_code``.

        Args:
            role_id: Идентификатор роли.
            role_name: Системное имя роли.
            role_code: Код роли. Можно передать строку или ``SystemRole``.
            only_active_users: Если ``True``, возвращает только активных
                пользователей. Если ``False``, возвращает только неактивных
                пользователей. Если ``None``, фильтр не применяется.
            offset: Смещение выборки.
            limit: Максимальное количество записей.
            order_by_username: Если ``True``, сортирует пользователей по имени.
                Иначе сортирует по дате создания.

        Returns:
            Список пользователей, которым назначена указанная роль.

        Raises:
            InvalidQueryError: Если указано не ровно одно поле роли или
                параметры пагинации некорректны.
            EntityNotFoundError: Если роль не найдена.
        """

        self._validate_pagination(offset=offset, limit=limit)

        provided = [
            role_id is not None,
            role_name is not None,
            role_code is not None,
        ]

        if sum(provided) != 1:
            raise InvalidQueryError(
                "Нужно указать ровно один параметр: role_id, role_name или role_code.",
                repository=self.repository_name,
                operation="get_users_by_role",
            )

        if role_id is None:
            if role_name is not None:
                role = await self.get_required_role_by_name(role_name)
            else:
                role = await self.get_required_role_by_code(role_code or "")
            role_id = role.id

        try:
            statement = (
                select(User)
                .join(UserRole, UserRole.user_id == User.id)
                .where(UserRole.role_id == role_id)
            )

            if only_active_users is not None:
                statement = statement.where(User.status == "active")

            if order_by_username:
                statement = statement.order_by(User.username.asc())
            else:
                statement = statement.order_by(User.created_at.asc())

            statement = statement.offset(offset).limit(limit)

            result = await self.session.execute(statement)

            return list(result.scalars().unique().all())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_users_by_role",
                reason=str(exc),
                details={
                    "role_id": str(role_id),
                    "role_name": role_name,
                    "role_code": str(role_code) if role_code else None,
                },
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Замена ролей пользователя
    # ------------------------------------------------------------------

    async def replace_user_roles(
        self,
        *,
        user_id: uuid.UUID,
        role_ids: Sequence[uuid.UUID],
        assigned_by: uuid.UUID | None = None,
        flush: bool = True,
        check_user_exists: bool = True,
        check_roles_exist: bool = True,
    ) -> list[UserRole]:
        """Полностью заменяет набор ролей пользователя.

        Args:
            user_id: Идентификатор пользователя.
            role_ids: Новые идентификаторы ролей пользователя.
            assigned_by: Идентификатор пользователя, назначившего роли.
            flush: Выполнить ``flush`` после замены.
            check_user_exists: Проверять существование пользователя.
            check_roles_exist: Проверять существование всех ролей.

        Returns:
            Список новых записей назначений ролей.

        Raises:
            EntityNotFoundError: Если пользователь или одна из ролей не найдены.
        """

        unique_role_ids = list(dict.fromkeys(role_ids))

        if check_user_exists:
            await self._ensure_user_exists(user_id)

        if check_roles_exist:
            await self._ensure_roles_exist(unique_role_ids)

        try:
            await self.session.execute(
                delete(UserRole).where(UserRole.user_id == user_id),
            )

            new_assignments = [
                UserRole(
                    user_id=user_id,
                    role_id=role_id,
                    assigned_by=assigned_by,
                )
                for role_id in unique_role_ids
            ]

            if new_assignments:
                self.session.add_all(new_assignments)

            if flush:
                await self.flush()

            return new_assignments

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="replace_user_roles",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="replace_user_roles",
                reason=str(exc),
                details={
                    "user_id": str(user_id),
                    "role_ids": [str(role_id) for role_id in unique_role_ids],
                    "assigned_by": str(assigned_by) if assigned_by else None,
                },
                cause=exc,
            ) from exc

    async def replace_user_roles_by_codes(
        self,
        *,
        user_id: uuid.UUID,
        role_codes: Sequence[str | SystemRole],
        assigned_by: uuid.UUID | None = None,
        flush: bool = True,
        check_user_exists: bool = True,
    ) -> list[UserRole]:
        """Полностью заменяет роли пользователя по кодам ролей.

        Args:
            user_id: Идентификатор пользователя.
            role_codes: Новые коды ролей пользователя.
            assigned_by: Идентификатор пользователя, назначившего роли.
            flush: Выполнить ``flush`` после замены.
            check_user_exists: Проверять существование пользователя.

        Returns:
            Список новых записей назначений ролей.

        Raises:
            EntityNotFoundError: Если пользователь или одна из ролей не найдены.
        """

        roles = await self.get_roles_by_codes(role_codes)
        requested_codes = {self._normalize_role_value(code) for code in role_codes}
        existing_codes = {role.code for role in roles}
        missing_codes = sorted(requested_codes - existing_codes)

        if missing_codes:
            raise EntityNotFoundError(
                "Role",
                lookup={"missing_codes": missing_codes},
                repository=self.repository_name,
            )

        return await self.replace_user_roles(
            user_id=user_id,
            role_ids=[role.id for role in roles],
            assigned_by=assigned_by,
            flush=flush,
            check_user_exists=check_user_exists,
            check_roles_exist=False,
        )

    async def clear_user_roles(
        self,
        *,
        user_id: uuid.UUID,
        flush: bool = True,
    ) -> int:
        """Удаляет все роли пользователя.

        Args:
            user_id: Идентификатор пользователя.
            flush: Выполнить ``flush`` после удаления.

        Returns:
            Количество удалённых назначений ролей.
        """

        try:
            result = await self.session.execute(
                delete(UserRole).where(UserRole.user_id == user_id),
            )

            if flush:
                await self.flush()

            return int(getattr(result, "rowcount", 0) or 0)

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="clear_user_roles",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="clear_user_roles",
                reason=str(exc),
                details={"user_id": str(user_id)},
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Массовое получение ролей
    # ------------------------------------------------------------------

    async def get_roles_by_ids(
        self,
        role_ids: Sequence[uuid.UUID],
    ) -> list[Role]:
        """Возвращает роли по списку идентификаторов.

        Args:
            role_ids: Последовательность идентификаторов ролей.

        Returns:
            Список найденных ролей.
        """

        unique_role_ids = list(dict.fromkeys(role_ids))

        if not unique_role_ids:
            return []

        statement = (
            select(Role).where(Role.id.in_(unique_role_ids)).order_by(Role.name.asc())
        )

        return await self.scalars_all(
            statement,
            operation="get_roles_by_ids",
        )

    async def get_roles_by_codes(
        self,
        role_codes: Sequence[str | SystemRole],
    ) -> list[Role]:
        """Возвращает роли по списку кодов.

        Args:
            role_codes: Последовательность кодов ролей.

        Returns:
            Список найденных ролей.
        """

        normalized_codes = list(
            dict.fromkeys(
                self._normalize_role_value(code)
                for code in role_codes
                if self._normalize_role_value(code)
            ),
        )

        if not normalized_codes:
            return []

        statement = (
            select(Role)
            .where(
                func.lower(Role.code).in_([code.lower() for code in normalized_codes])
            )
            .order_by(Role.name.asc())
        )

        return await self.scalars_all(
            statement,
            operation="get_roles_by_codes",
        )

    # ------------------------------------------------------------------
    # Вспомогательные проверки
    # ------------------------------------------------------------------

    async def _ensure_user_exists(
        self,
        user_id: uuid.UUID,
    ) -> None:
        """Проверяет существование пользователя.

        Args:
            user_id: Идентификатор пользователя.

        Raises:
            EntityNotFoundError: Если пользователь не найден.
        """

        try:
            user = await self.session.get(User, user_id)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="_ensure_user_exists",
                reason=str(exc),
                details={"user_id": str(user_id)},
                cause=exc,
            ) from exc

        if user is None:
            raise EntityNotFoundError(
                "User",
                entity_id=user_id,
                repository=self.repository_name,
            )

    async def _ensure_roles_exist(
        self,
        role_ids: Sequence[uuid.UUID],
    ) -> None:
        """Проверяет существование всех ролей из списка.

        Args:
            role_ids: Последовательность идентификаторов ролей.

        Raises:
            EntityNotFoundError: Если одна или несколько ролей не найдены.
        """

        unique_role_ids = list(dict.fromkeys(role_ids))

        if not unique_role_ids:
            return

        try:
            statement = select(Role.id).where(Role.id.in_(unique_role_ids))
            result = await self.session.execute(statement)
            existing_role_ids = set(result.scalars().all())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="_ensure_roles_exist",
                reason=str(exc),
                details={
                    "role_ids": [str(role_id) for role_id in unique_role_ids],
                },
                cause=exc,
            ) from exc

        missing_role_ids = [
            role_id for role_id in unique_role_ids if role_id not in existing_role_ids
        ]

        if missing_role_ids:
            raise EntityNotFoundError(
                "Role",
                lookup={
                    "missing_role_ids": missing_role_ids,
                },
                repository=self.repository_name,
            )

    # ------------------------------------------------------------------
    # Нормализация
    # ------------------------------------------------------------------

    def _normalize_role_value(
        self,
        value: str | SystemRole,
    ) -> str:
        """Нормализует системное имя или код роли.

        Args:
            value: Системное имя, код роли или ``SystemRole``.

        Returns:
            Нормализованное значение роли в нижнем регистре без пробелов по
            краям.
        """

        if isinstance(value, SystemRole):
            return value.value.strip().lower()

        return str(value).strip().lower()
