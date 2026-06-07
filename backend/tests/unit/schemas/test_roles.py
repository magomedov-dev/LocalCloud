"""Модульные тесты схем ролей."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from database.models.enums import SystemRole
from schemas.roles import (
    RoleAssignRequest,
    RoleCreate,
    RoleListItem,
    RoleRead,
    RoleRemoveRequest,
    RoleUpdate,
    UserRoleRead,
)


# ---------------------------------------------------------------------------
# RoleCreate
# ---------------------------------------------------------------------------


class TestRoleCreate:
    """Тесты схемы создания роли."""

    def test_valid_creation(self) -> None:
        role = RoleCreate(
            name="editor",
            code="editor",
            display_name="Editor",
        )
        assert role.name == "editor"
        assert role.code == "editor"
        assert role.display_name == "Editor"
        assert role.is_system is False
        assert role.is_active is True

    def test_name_is_stripped(self) -> None:
        role = RoleCreate(name="  admin  ", code="admin", display_name="Admin")
        assert role.name == "admin"

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleCreate(name="   ", code="admin", display_name="Admin")

    def test_name_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleCreate(name="a" * 65, code="admin", display_name="Admin")

    def test_code_normalised_to_lowercase(self) -> None:
        role = RoleCreate(name="admin", code="ADMIN", display_name="Admin")
        assert role.code == "admin"

    def test_code_from_system_role_enum(self) -> None:
        role = RoleCreate(
            name="admin", code=SystemRole.ADMIN, display_name="Administrator"
        )
        assert role.code == "admin"

    def test_code_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleCreate(name="role", code="x" * 65, display_name="Role")

    def test_empty_code_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleCreate(name="role", code="  ", display_name="Role")

    def test_display_name_stripped(self) -> None:
        role = RoleCreate(name="role", code="role", display_name="  Role  ")
        assert role.display_name == "Role"

    def test_empty_display_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleCreate(name="role", code="role", display_name="   ")

    def test_description_normalised_to_none_when_blank(self) -> None:
        role = RoleCreate(name="role", code="role", display_name="Role", description="  ")
        assert role.description is None

    def test_description_stripped(self) -> None:
        role = RoleCreate(
            name="role", code="role", display_name="Role", description="  desc  "
        )
        assert role.description == "desc"

    def test_is_system_flag(self) -> None:
        role = RoleCreate(
            name="role", code="role", display_name="Role", is_system=True
        )
        assert role.is_system is True

    def test_is_active_flag_false(self) -> None:
        role = RoleCreate(
            name="role", code="role", display_name="Role", is_active=False
        )
        assert role.is_active is False


# ---------------------------------------------------------------------------
# RoleUpdate
# ---------------------------------------------------------------------------


class TestRoleUpdate:
    """Тесты схемы обновления роли."""

    def test_all_none_is_valid(self) -> None:
        update = RoleUpdate()
        assert update.name is None
        assert update.code is None
        assert update.display_name is None
        assert update.is_active is None

    def test_partial_update_name_only(self) -> None:
        update = RoleUpdate(name="new_name")
        assert update.name == "new_name"

    def test_name_stripped(self) -> None:
        update = RoleUpdate(name="  editor  ")
        assert update.name == "editor"

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleUpdate(name="  ")

    def test_code_normalised(self) -> None:
        update = RoleUpdate(code="MODERATOR")
        assert update.code == "moderator"

    def test_code_from_system_role(self) -> None:
        update = RoleUpdate(code=SystemRole.USER)
        assert update.code == "user"

    def test_display_name_stripped(self) -> None:
        update = RoleUpdate(display_name="  New Name  ")
        assert update.display_name == "New Name"

    def test_empty_display_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleUpdate(display_name="   ")

    def test_description_normalised(self) -> None:
        update = RoleUpdate(description="   ")
        assert update.description is None

    def test_is_active_can_be_set(self) -> None:
        update = RoleUpdate(is_active=False)
        assert update.is_active is False


# ---------------------------------------------------------------------------
# RoleRead
# ---------------------------------------------------------------------------


class TestRoleRead:
    """Тесты схемы чтения роли."""

    def _make_role_data(self, **overrides: object) -> dict:
        now = datetime.now(tz=timezone.utc)
        return {
            "id": str(uuid.uuid4()),
            "name": "admin",
            "code": "admin",
            "display_name": "Administrator",
            "description": None,
            "is_system": True,
            "is_active": True,
            "created_at": now.isoformat(),
            **overrides,
        }

    def test_valid_construction(self) -> None:
        data = self._make_role_data()
        role = RoleRead(**data)
        assert role.name == "admin"
        assert role.is_system is True

    def test_from_orm_like_object(self) -> None:
        from unittest.mock import MagicMock

        now = datetime.now(tz=timezone.utc)
        orm_obj = MagicMock()
        orm_obj.id = uuid.uuid4()
        orm_obj.name = "user"
        orm_obj.code = "user"
        orm_obj.display_name = "User"
        orm_obj.description = None
        orm_obj.is_system = False
        orm_obj.is_active = True
        orm_obj.created_at = now

        role = RoleRead.model_validate(orm_obj)
        assert role.name == "user"
        assert role.is_active is True

    def test_missing_required_field_raises(self) -> None:
        data = self._make_role_data()
        del data["name"]
        with pytest.raises(ValidationError):
            RoleRead(**data)


# ---------------------------------------------------------------------------
# RoleListItem
# ---------------------------------------------------------------------------


class TestRoleListItem:
    """Тесты элемента списка ролей."""

    def test_valid_construction(self) -> None:
        item = RoleListItem(
            id=uuid.uuid4(),
            name="viewer",
            code="viewer",
            display_name="Viewer",
            is_system=False,
            is_active=True,
        )
        assert item.name == "viewer"

    def test_from_orm_like_object(self) -> None:
        from unittest.mock import MagicMock

        orm_obj = MagicMock()
        orm_obj.id = uuid.uuid4()
        orm_obj.name = "editor"
        orm_obj.code = "editor"
        orm_obj.display_name = "Editor"
        orm_obj.is_system = False
        orm_obj.is_active = True

        item = RoleListItem.model_validate(orm_obj)
        assert item.code == "editor"


# ---------------------------------------------------------------------------
# RoleAssignRequest
# ---------------------------------------------------------------------------


class TestRoleAssignRequest:
    """Тесты запроса назначения роли пользователю."""

    def test_with_role_id(self) -> None:
        req = RoleAssignRequest(user_id=uuid.uuid4(), role_id=uuid.uuid4())
        assert req.role_id is not None

    def test_with_role_code(self) -> None:
        req = RoleAssignRequest(user_id=uuid.uuid4(), role_code="admin")
        assert req.role_code == "admin"

    def test_role_code_normalised_to_lowercase(self) -> None:
        req = RoleAssignRequest(user_id=uuid.uuid4(), role_code="ADMIN")
        assert req.role_code == "admin"

    def test_role_code_from_system_role(self) -> None:
        req = RoleAssignRequest(user_id=uuid.uuid4(), role_code=SystemRole.ADMIN)
        assert req.role_code == "admin"

    def test_neither_role_id_nor_code_raises_when_role_code_explicitly_none(self) -> None:
        # Когда role_code явно равен None и role_id также None,
        # срабатывает field_validator и вызывает ошибку.
        with pytest.raises(ValidationError):
            RoleAssignRequest(user_id=uuid.uuid4(), role_code=None, role_id=None)

    def test_empty_role_code_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleAssignRequest(user_id=uuid.uuid4(), role_code="   ")

    def test_role_code_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleAssignRequest(user_id=uuid.uuid4(), role_code="x" * 65)

    def test_assigned_by_optional(self) -> None:
        req = RoleAssignRequest(
            user_id=uuid.uuid4(),
            role_id=uuid.uuid4(),
            assigned_by=uuid.uuid4(),
        )
        assert req.assigned_by is not None


# ---------------------------------------------------------------------------
# RoleRemoveRequest
# ---------------------------------------------------------------------------


class TestRoleRemoveRequest:
    """Тесты запроса снятия роли с пользователя."""

    def test_with_role_id(self) -> None:
        req = RoleRemoveRequest(user_id=uuid.uuid4(), role_id=uuid.uuid4())
        assert req.role_id is not None

    def test_with_role_code(self) -> None:
        req = RoleRemoveRequest(user_id=uuid.uuid4(), role_code="user")
        assert req.role_code == "user"

    def test_neither_raises_when_both_explicitly_none(self) -> None:
        with pytest.raises(ValidationError):
            RoleRemoveRequest(user_id=uuid.uuid4(), role_code=None, role_id=None)

    def test_role_code_normalised(self) -> None:
        req = RoleRemoveRequest(user_id=uuid.uuid4(), role_code="USER")
        assert req.role_code == "user"


# ---------------------------------------------------------------------------
# UserRoleRead
# ---------------------------------------------------------------------------


class TestUserRoleRead:
    """Тесты схемы чтения связи пользователь-роль."""

    def test_valid_construction(self) -> None:
        now = datetime.now(tz=timezone.utc)
        record = UserRoleRead(
            user_id=uuid.uuid4(),
            role_id=uuid.uuid4(),
            assigned_at=now,
        )
        assert record.assigned_by is None
        assert record.role is None

    def test_with_role_list_item(self) -> None:
        now = datetime.now(tz=timezone.utc)
        role_item = RoleListItem(
            id=uuid.uuid4(),
            name="admin",
            code="admin",
            display_name="Admin",
            is_system=True,
            is_active=True,
        )
        record = UserRoleRead(
            user_id=uuid.uuid4(),
            role_id=uuid.uuid4(),
            assigned_at=now,
            role=role_item,
        )
        assert record.role is not None
        assert record.role.code == "admin"


# ---------------------------------------------------------------------------
# Дополнение покрытия: запасные ветки валидаторов и краевые случаи
# ---------------------------------------------------------------------------


class TestRoleBaseValidatorEdges:
    """Тесты краевых случаев валидаторов базовой схемы роли."""

    def test_empty_name_after_strip_raises(self) -> None:
        # BaseSchema обрезает пробелы, поэтому min_length=1 отклоняет значение первым.
        with pytest.raises(ValidationError):
            RoleCreate(name="\t\n ", code="role", display_name="Role")

    def test_empty_display_name_after_strip_raises(self) -> None:
        # BaseSchema обрезает пробелы, поэтому min_length=1 отклоняет значение первым.
        with pytest.raises(ValidationError):
            RoleCreate(name="role", code="role", display_name="\t\n ")

    def test_code_non_string_non_enum_passes_through(self) -> None:
        # normalize_code получает int -> срабатывает запасная ветка `return value`,
        # затем тип поля str|SystemRole отклоняет нестроковое значение.
        with pytest.raises(ValidationError):
            RoleCreate(name="role", code=5, display_name="Role")


class TestRoleUpdateValidatorEdges:
    """Тесты краевых случаев валидаторов схемы обновления роли."""

    def test_name_none_returns_none(self) -> None:
        update = RoleUpdate(name=None)
        assert update.name is None

    def test_name_empty_after_strip_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleUpdate(name="\t ")

    def test_code_none_returns_none(self) -> None:
        update = RoleUpdate(code=None)
        assert update.code is None

    def test_code_empty_after_strip_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleUpdate(code="   ")

    def test_code_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleUpdate(code="x" * 65)

    def test_code_non_string_non_enum_passes_through(self) -> None:
        # Срабатывает запасная ветка `return value`; затем тип поля отклоняет int.
        with pytest.raises(ValidationError):
            RoleUpdate(code=7)

    def test_display_name_none_returns_none(self) -> None:
        update = RoleUpdate(display_name=None)
        assert update.display_name is None

    def test_display_name_empty_after_strip_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleUpdate(display_name="\t ")

    def test_description_none_returns_none(self) -> None:
        update = RoleUpdate(description=None)
        assert update.description is None


class TestRoleAssignRequestValidatorEdges:
    """Тесты краевых случаев валидаторов запроса назначения роли."""

    def test_role_code_non_string_non_enum_passes_through(self) -> None:
        # normalize_role_code срабатывает на `return value`; тип поля отклоняет int.
        with pytest.raises(ValidationError):
            RoleAssignRequest(user_id=uuid.uuid4(), role_code=9)


class TestRoleRemoveRequestValidatorEdges:
    """Тесты краевых случаев валидаторов запроса снятия роли."""

    def test_role_code_from_system_role(self) -> None:
        req = RoleRemoveRequest(user_id=uuid.uuid4(), role_code=SystemRole.ADMIN)
        assert req.role_code == "admin"

    def test_empty_role_code_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleRemoveRequest(user_id=uuid.uuid4(), role_code="   ")

    def test_role_code_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleRemoveRequest(user_id=uuid.uuid4(), role_code="x" * 65)

    def test_role_code_non_string_non_enum_passes_through(self) -> None:
        with pytest.raises(ValidationError):
            RoleRemoveRequest(user_id=uuid.uuid4(), role_code=3)
