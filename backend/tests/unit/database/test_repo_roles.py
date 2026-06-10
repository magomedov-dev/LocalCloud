"""Юнит-тесты репозитория ролей (RolesRepository)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidQueryError,
    RepositoryError,
)
from database.models.enums import SystemRole
from database.repositories.roles import RolesRepository


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

def make_session():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.scalar_one = MagicMock(return_value=0)
    result.rowcount = 0
    result.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session, result


def make_repo():
    session, result = make_session()
    return RolesRepository(session=session), session, result


def make_role(**kwargs):
    role = MagicMock()
    defaults = dict(
        id=uuid.uuid4(),
        name="admin",
        code="admin",
        display_name="Admin",
        description=None,
        is_system=False,
        is_active=True,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(role, k, v)
    role.activate = MagicMock()
    role.deactivate = MagicMock()
    return role


def make_user_role(**kwargs):
    ur = MagicMock()
    defaults = dict(
        user_id=uuid.uuid4(),
        role_id=uuid.uuid4(),
        assigned_by=None,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(ur, k, v)
    return ur


# ---------------------------------------------------------------------------
# Тесты: get_role_by_id / get_required_role_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_role_by_id_returns_none_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    res = await repo.get_role_by_id(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_role_by_id_returns_role_when_found():
    repo, session, result = make_repo()
    role = make_role()
    session.get = AsyncMock(return_value=role)
    res = await repo.get_role_by_id(role.id)
    assert res is role


@pytest.mark.asyncio
async def test_get_required_role_by_id_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_role_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_role_by_name / get_role_by_code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_role_by_name_returns_none_for_empty_name():
    repo, session, result = make_repo()
    res = await repo.get_role_by_name("  ")
    assert res is None


@pytest.mark.asyncio
async def test_get_role_by_name_returns_role_when_found():
    repo, session, result = make_repo()
    role = make_role()
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_role_by_name("admin")
    assert res is role


@pytest.mark.asyncio
async def test_get_required_role_by_name_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_role_by_name("nonexistent")


@pytest.mark.asyncio
async def test_get_required_role_by_name_returns_role():
    repo, session, result = make_repo()
    role = make_role()
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_required_role_by_name("admin")
    assert res is role


@pytest.mark.asyncio
async def test_get_role_by_code_returns_none_for_empty_code():
    repo, session, result = make_repo()
    res = await repo.get_role_by_code("   ")
    assert res is None


@pytest.mark.asyncio
async def test_get_role_by_code_returns_role_when_found():
    repo, session, result = make_repo()
    role = make_role()
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_role_by_code(SystemRole.ADMIN)
    assert res is role


# ---------------------------------------------------------------------------
# Тесты: role_exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_role_exists_raises_when_no_params():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.role_exists()


@pytest.mark.asyncio
async def test_role_exists_returns_false_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=0)
    res = await repo.role_exists(name="someRole")
    assert res is False


@pytest.mark.asyncio
async def test_role_exists_returns_true_when_found():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.role_exists(code="admin")
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: create_role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_role_raises_for_empty_name():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_role(name="", display_name="Test", check_duplicate=False)


@pytest.mark.asyncio
async def test_create_role_raises_for_empty_display_name():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.create_role(name="test", display_name="  ", check_duplicate=False)


@pytest.mark.asyncio
async def test_create_role_success():
    repo, session, result = make_repo()
    role = make_role()

    async def fake_create(entity, flush=True, refresh=False):
        return role

    repo.create = fake_create  # type: ignore
    res = await repo.create_role(
        name="moderator",
        display_name="Moderator",
        check_duplicate=False,
    )
    assert res is role


@pytest.mark.asyncio
async def test_create_role_raises_on_duplicate():
    repo, session, result = make_repo()
    # Имитируем, что role_exists возвращает True
    result.scalar_one = MagicMock(return_value=1)
    with pytest.raises(DuplicateEntityError):
        await repo.create_role(
            name="admin",
            display_name="Admin",
            check_duplicate=True,
        )


# ---------------------------------------------------------------------------
# Тесты: activate_role / deactivate_role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_activate_role_raises_when_not_found():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.activate_role(uuid.uuid4())


@pytest.mark.asyncio
async def test_activate_role_success():
    repo, session, result = make_repo()
    role = make_role(is_active=False)
    session.get = AsyncMock(return_value=role)
    res = await repo.activate_role(role.id)
    role.activate.assert_called_once()
    assert res is role


@pytest.mark.asyncio
async def test_deactivate_role_raises_for_system_role():
    repo, session, result = make_repo()
    role = make_role(is_system=True)
    session.get = AsyncMock(return_value=role)
    with pytest.raises(InvalidQueryError):
        await repo.deactivate_role(role.id, forbid_system_role=True)


@pytest.mark.asyncio
async def test_deactivate_role_success():
    repo, session, result = make_repo()
    role = make_role(is_system=False)
    session.get = AsyncMock(return_value=role)
    res = await repo.deactivate_role(role.id)
    role.deactivate.assert_called_once()
    assert res is role


# ---------------------------------------------------------------------------
# Тесты: delete_role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_role_raises_for_system_role():
    repo, session, result = make_repo()
    role = make_role(is_system=True)
    session.get = AsyncMock(return_value=role)
    with pytest.raises(InvalidQueryError):
        await repo.delete_role(role.id, forbid_system_role=True)


@pytest.mark.asyncio
async def test_delete_role_success():
    repo, session, result = make_repo()
    role = make_role(is_system=False)
    session.get = AsyncMock(return_value=role)

    async def fake_delete(entity, flush=True):
        pass

    repo.delete = fake_delete  # type: ignore
    res = await repo.delete_role(role.id)
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: list_roles
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_roles_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.list_roles()
    assert res == []


@pytest.mark.asyncio
async def test_list_roles_with_active_filter():
    repo, session, result = make_repo()
    role = make_role(is_active=True)
    result.scalars.return_value.all.return_value = [role]
    res = await repo.list_roles(only_active=True)
    assert len(res) == 1


# ---------------------------------------------------------------------------
# Тесты: assign_role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assign_role_returns_existing_when_ignore():
    repo, session, result = make_repo()
    user_id = uuid.uuid4()
    role_id = uuid.uuid4()
    user_role = make_user_role(user_id=user_id, role_id=role_id)
    result.scalar_one_or_none = MagicMock(return_value=user_role)

    res = await repo.assign_role(
        user_id=user_id,
        role_id=role_id,
        check_user_exists=False,
        check_role_exists=False,
        ignore_existing=True,
    )
    assert res is user_role


@pytest.mark.asyncio
async def test_assign_role_raises_duplicate_when_not_ignore():
    repo, session, result = make_repo()
    user_id = uuid.uuid4()
    role_id = uuid.uuid4()
    user_role = make_user_role(user_id=user_id, role_id=role_id)
    result.scalar_one_or_none = MagicMock(return_value=user_role)

    with pytest.raises(DuplicateEntityError):
        await repo.assign_role(
            user_id=user_id,
            role_id=role_id,
            check_user_exists=False,
            check_role_exists=False,
            ignore_existing=False,
        )


@pytest.mark.asyncio
async def test_assign_role_creates_new_when_not_existing():
    repo, session, result = make_repo()
    user_id = uuid.uuid4()
    role_id = uuid.uuid4()
    result.scalar_one_or_none = MagicMock(return_value=None)

    res = await repo.assign_role(
        user_id=user_id,
        role_id=role_id,
        check_user_exists=False,
        check_role_exists=False,
        ignore_existing=True,
    )
    session.add.assert_called_once()


# ---------------------------------------------------------------------------
# Тесты: remove_role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_role_returns_false_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.remove_role(
        user_id=uuid.uuid4(),
        role_id=uuid.uuid4(),
        required=False,
    )
    assert res is False


@pytest.mark.asyncio
async def test_remove_role_raises_when_required_and_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.remove_role(
            user_id=uuid.uuid4(),
            role_id=uuid.uuid4(),
            required=True,
        )


@pytest.mark.asyncio
async def test_remove_role_success():
    repo, session, result = make_repo()
    user_role = make_user_role()
    result.scalar_one_or_none = MagicMock(return_value=user_role)
    res = await repo.remove_role(user_id=user_role.user_id, role_id=user_role.role_id)
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: user_has_role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_has_role_raises_when_no_params():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.user_has_role(user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_user_has_role_raises_when_multiple_params():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.user_has_role(
            user_id=uuid.uuid4(),
            role_id=uuid.uuid4(),
            role_name="admin",
        )


@pytest.mark.asyncio
async def test_user_has_role_returns_true():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=True)
    res = await repo.user_has_role(user_id=uuid.uuid4(), role_id=uuid.uuid4())
    assert res is True


@pytest.mark.asyncio
async def test_user_has_role_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.user_has_role(user_id=uuid.uuid4(), role_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_user_roles / get_user_role_names / get_user_role_codes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_roles_returns_list():
    repo, session, result = make_repo()
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    result.scalars.return_value = scalars_result
    res = await repo.get_user_roles(uuid.uuid4())
    assert res == []


@pytest.mark.asyncio
async def test_get_user_roles_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.get_user_roles(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_user_role_names_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = ["admin"]
    res = await repo.get_user_role_names(uuid.uuid4())
    assert res == ["admin"]


@pytest.mark.asyncio
async def test_get_user_role_codes_returns_list():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = ["admin"]
    res = await repo.get_user_role_codes(uuid.uuid4())
    assert res == ["admin"]


# ---------------------------------------------------------------------------
# Тесты: get_user_role / exists_user_role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_role_returns_none_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.get_user_role(user_id=uuid.uuid4(), role_id=uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_get_user_role_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    with pytest.raises(RepositoryError):
        await repo.get_user_role(user_id=uuid.uuid4(), role_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_exists_user_role_returns_bool():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=True)
    res = await repo.exists_user_role(user_id=uuid.uuid4(), role_id=uuid.uuid4())
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: clear_user_roles
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear_user_roles_returns_count():
    repo, session, result = make_repo()
    result.rowcount = 3
    count = await repo.clear_user_roles(user_id=uuid.uuid4())
    assert count == 3


# ---------------------------------------------------------------------------
# Тесты: get_roles_by_ids / get_roles_by_codes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_roles_by_ids_returns_empty_for_empty_input():
    repo, session, result = make_repo()
    res = await repo.get_roles_by_ids([])
    assert res == []


@pytest.mark.asyncio
async def test_get_roles_by_ids_returns_roles():
    repo, session, result = make_repo()
    role = make_role()
    result.scalars.return_value.all.return_value = [role]
    res = await repo.get_roles_by_ids([role.id])
    assert len(res) == 1


@pytest.mark.asyncio
async def test_get_roles_by_codes_returns_empty_for_empty_input():
    repo, session, result = make_repo()
    res = await repo.get_roles_by_codes([])
    assert res == []


@pytest.mark.asyncio
async def test_get_roles_by_codes_returns_roles():
    repo, session, result = make_repo()
    role = make_role()
    result.scalars.return_value.all.return_value = [role]
    res = await repo.get_roles_by_codes(["admin"])
    assert len(res) == 1


# ---------------------------------------------------------------------------
# Дополнительные хелперы
# ---------------------------------------------------------------------------

def make_integrity_error(sqlstate="23505", constraint="uq_user_roles"):
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = constraint
    orig.table_name = "user_roles"
    orig.column_name = None
    err = IntegrityError("stmt", {}, orig)
    err.orig = orig
    return err


# ---------------------------------------------------------------------------
# Тесты: get_role_by_name / get_role_by_code case_sensitive branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_role_by_name_case_sensitive():
    repo, session, result = make_repo()
    role = make_role()
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_role_by_name("admin", case_sensitive=True)
    assert res is role


@pytest.mark.asyncio
async def test_get_role_by_code_returns_none_for_empty_code_case_sensitive():
    repo, session, result = make_repo()
    res = await repo.get_role_by_code("", case_sensitive=True)
    assert res is None


@pytest.mark.asyncio
async def test_get_role_by_code_case_sensitive():
    repo, session, result = make_repo()
    role = make_role()
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_role_by_code("admin", case_sensitive=True)
    assert res is role


# ---------------------------------------------------------------------------
# Тесты: get_required_role_by_code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_required_role_by_code_returns_role():
    repo, session, result = make_repo()
    role = make_role()
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_required_role_by_code(SystemRole.ADMIN)
    assert res is role


@pytest.mark.asyncio
async def test_get_required_role_by_code_raises_when_not_found():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo.get_required_role_by_code("missing")


# ---------------------------------------------------------------------------
# Тесты: get_admin_role / get_user_role_model and required variants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_admin_role_returns_role():
    repo, session, result = make_repo()
    role = make_role(code="admin")
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_admin_role()
    assert res is role


@pytest.mark.asyncio
async def test_get_user_role_model_returns_role():
    repo, session, result = make_repo()
    role = make_role(code="user")
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_user_role_model()
    assert res is role


@pytest.mark.asyncio
async def test_get_required_admin_role_returns_role():
    repo, session, result = make_repo()
    role = make_role(code="admin")
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_required_admin_role()
    assert res is role


@pytest.mark.asyncio
async def test_get_required_user_role_model_returns_role():
    repo, session, result = make_repo()
    role = make_role(code="user")
    result.scalar_one_or_none = MagicMock(return_value=role)
    res = await repo.get_required_user_role_model()
    assert res is role


# ---------------------------------------------------------------------------
# Тесты: role_exists branches (name + code + exclude + case_sensitive)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_role_exists_with_all_params_case_sensitive():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=1)
    res = await repo.role_exists(
        name="Admin",
        code="Admin",
        exclude_role_id=uuid.uuid4(),
        case_sensitive=True,
    )
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: create_role empty code and duplicate code branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_role_raises_for_empty_code():
    repo, session, result = make_repo()
    # code раскрывается в пустую строку, хотя name не пустой
    with pytest.raises(InvalidQueryError):
        await repo.create_role(
            name="test",
            code="   ",
            display_name="Test",
            check_duplicate=False,
        )


@pytest.mark.asyncio
async def test_create_role_raises_on_duplicate_code():
    repo, session, result = make_repo()
    # role_exists по name -> False, по code -> True
    repo.role_exists = AsyncMock(side_effect=[False, True])  # type: ignore
    with pytest.raises(DuplicateEntityError):
        await repo.create_role(
            name="moderator",
            code="mod",
            display_name="Moderator",
            check_duplicate=True,
        )


@pytest.mark.asyncio
async def test_create_role_strips_description():
    repo, session, result = make_repo()
    created = {}

    async def fake_create(entity, flush=True, refresh=False):
        created["entity"] = entity
        return entity

    repo.create = fake_create  # type: ignore
    res = await repo.create_role(
        name="editor",
        display_name="Editor",
        description="  some desc  ",
        check_duplicate=False,
    )
    assert res.description == "some desc"


# ---------------------------------------------------------------------------
# Тесты: ensure_system_roles
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_system_roles_creates_missing():
    repo, session, result = make_repo()
    # get_role_by_code возвращает None для обоих -> создаются оба
    result.scalar_one_or_none = MagicMock(return_value=None)
    roles = await repo.ensure_system_roles()
    assert len(roles) == 2
    assert session.add.call_count == 2
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_ensure_system_roles_uses_existing():
    repo, session, result = make_repo()
    admin = make_role(code="admin")
    user = make_role(code="user")
    repo.get_role_by_code = AsyncMock(side_effect=[admin, user])  # type: ignore
    roles = await repo.ensure_system_roles(flush=False)
    assert roles == [admin, user]
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Тесты: update_role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_role_raises_for_protected_system_field():
    repo, session, result = make_repo()
    role = make_role(is_system=True)
    with pytest.raises(InvalidQueryError):
        await repo.update_role(role, {"name": "newname"})


@pytest.mark.asyncio
async def test_update_role_normalizes_values():
    repo, session, result = make_repo()
    role = make_role(is_system=False)
    captured = {}

    async def fake_update(entity, values, **kwargs):
        captured.update(values)
        return entity

    repo.update = fake_update  # type: ignore
    res = await repo.update_role(
        role,
        {
            "name": "  NewName ",
            "code": " NewCode ",
            "display_name": "  Display ",
            "description": "  Desc ",
        },
    )
    assert res is role
    assert captured["name"] == "newname"
    assert captured["code"] == "newcode"
    assert captured["display_name"] == "Display"
    assert captured["description"] == "Desc"


@pytest.mark.asyncio
async def test_update_role_keeps_none_values():
    repo, session, result = make_repo()
    role = make_role(is_system=False)
    captured = {}

    async def fake_update(entity, values, **kwargs):
        captured.update(values)
        return entity

    repo.update = fake_update  # type: ignore
    await repo.update_role(
        role,
        {"name": None, "code": None, "display_name": None, "description": None},
    )
    assert captured["name"] is None
    assert captured["description"] is None


# ---------------------------------------------------------------------------
# Тесты: activate_role flush=False / deactivate non-system
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_activate_role_no_flush():
    repo, session, result = make_repo()
    role = make_role(is_active=False)
    session.get = AsyncMock(return_value=role)
    res = await repo.activate_role(role.id, flush=False)
    assert res is role
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_role_allows_system_when_not_forbidden():
    repo, session, result = make_repo()
    role = make_role(is_system=True)
    session.get = AsyncMock(return_value=role)
    res = await repo.deactivate_role(role.id, forbid_system_role=False)
    role.deactivate.assert_called_once()
    assert res is role


# ---------------------------------------------------------------------------
# Тесты: delete_role разрешает системную роль, если не запрещено
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_role_allows_system_when_not_forbidden():
    repo, session, result = make_repo()
    role = make_role(is_system=True)
    session.get = AsyncMock(return_value=role)

    async def fake_delete(entity, flush=True):
        pass

    repo.delete = fake_delete  # type: ignore
    res = await repo.delete_role(role.id, forbid_system_role=False)
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: list_roles filters and ordering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_roles_with_system_search_and_order_by_created():
    repo, session, result = make_repo()
    role = make_role()
    result.scalars.return_value.all.return_value = [role]
    res = await repo.list_roles(
        only_system=True,
        search="  admin  ",
        order_by_name=False,
    )
    assert res == [role]


# ---------------------------------------------------------------------------
# Тесты: assign_role flush/refresh + — ветки ошибок
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assign_role_with_refresh():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)
    res = await repo.assign_role(
        user_id=uuid.uuid4(),
        role_id=uuid.uuid4(),
        check_user_exists=False,
        check_role_exists=False,
        flush=True,
        refresh=True,
    )
    session.refresh.assert_awaited_once()
    assert res is not None


@pytest.mark.asyncio
async def test_assign_role_checks_user_and_role_exist():
    repo, session, result = make_repo()
    user = MagicMock()
    session.get = AsyncMock(return_value=user)
    role = make_role()
    # get_user_role -> None; get_required_role_by_id через get_by_id -> role
    repo.get_required_role_by_id = AsyncMock(return_value=role)  # type: ignore
    repo.get_user_role = AsyncMock(return_value=None)  # type: ignore
    res = await repo.assign_role(
        user_id=uuid.uuid4(),
        role_id=role.id,
        check_user_exists=True,
        check_role_exists=True,
    )
    assert res is not None


@pytest.mark.asyncio
async def test_assign_role_integrity_error_maps_to_repository_error():
    repo, session, result = make_repo()
    repo.get_user_role = AsyncMock(return_value=None)  # type: ignore
    # бросаем сырой IntegrityError внутри try-блока assign_role, чтобы сработал
    # локальный обработчик except IntegrityError.
    repo.flush = AsyncMock(side_effect=make_integrity_error())  # type: ignore
    with pytest.raises(DuplicateEntityError):
        await repo.assign_role(
            user_id=uuid.uuid4(),
            role_id=uuid.uuid4(),
            check_user_exists=False,
            check_role_exists=False,
        )


@pytest.mark.asyncio
async def test_assign_role_sqlalchemy_error_maps_to_repository_error():
    repo, session, result = make_repo()
    repo.get_user_role = AsyncMock(return_value=None)  # type: ignore
    repo.flush = AsyncMock(side_effect=SQLAlchemyError("boom"))  # type: ignore
    with pytest.raises(RepositoryError):
        await repo.assign_role(
            user_id=uuid.uuid4(),
            role_id=uuid.uuid4(),
            assigned_by=uuid.uuid4(),
            check_user_exists=False,
            check_role_exists=False,
        )


# ---------------------------------------------------------------------------
# Тесты: assign_role_by_name / by_code / admin / user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assign_role_by_name():
    repo, session, result = make_repo()
    role = make_role()
    repo.get_required_role_by_name = AsyncMock(return_value=role)  # type: ignore
    repo.assign_role = AsyncMock(return_value="UR")  # type: ignore
    res = await repo.assign_role_by_name(
        user_id=uuid.uuid4(),
        role_name="admin",
    )
    assert res == "UR"


@pytest.mark.asyncio
async def test_assign_role_by_code():
    repo, session, result = make_repo()
    role = make_role()
    repo.get_required_role_by_code = AsyncMock(return_value=role)  # type: ignore
    repo.assign_role = AsyncMock(return_value="UR")  # type: ignore
    res = await repo.assign_role_by_code(
        user_id=uuid.uuid4(),
        role_code=SystemRole.USER,
    )
    assert res == "UR"


@pytest.mark.asyncio
async def test_assign_admin_role():
    repo, session, result = make_repo()
    repo.assign_role_by_code = AsyncMock(return_value="UR")  # type: ignore
    res = await repo.assign_admin_role(user_id=uuid.uuid4())
    assert res == "UR"
    assert repo.assign_role_by_code.await_args.kwargs["role_code"] == SystemRole.ADMIN


@pytest.mark.asyncio
async def test_assign_user_role():
    repo, session, result = make_repo()
    repo.assign_role_by_code = AsyncMock(return_value="UR")  # type: ignore
    res = await repo.assign_user_role(user_id=uuid.uuid4())
    assert res == "UR"
    assert repo.assign_role_by_code.await_args.kwargs["role_code"] == SystemRole.USER


# ---------------------------------------------------------------------------
# Тесты: remove_role — ветки ошибок + by_name / by_code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_role_integrity_error():
    repo, session, result = make_repo()
    user_role = make_user_role()
    repo.get_user_role = AsyncMock(return_value=user_role)  # type: ignore
    session.delete = AsyncMock(side_effect=make_integrity_error("23503"))
    with pytest.raises(RepositoryError):
        await repo.remove_role(user_id=uuid.uuid4(), role_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_remove_role_sqlalchemy_error():
    repo, session, result = make_repo()
    user_role = make_user_role()
    repo.get_user_role = AsyncMock(return_value=user_role)  # type: ignore
    session.delete = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.remove_role(user_id=uuid.uuid4(), role_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_remove_role_by_name():
    repo, session, result = make_repo()
    role = make_role()
    repo.get_required_role_by_name = AsyncMock(return_value=role)  # type: ignore
    repo.remove_role = AsyncMock(return_value=True)  # type: ignore
    res = await repo.remove_role_by_name(user_id=uuid.uuid4(), role_name="admin")
    assert res is True


@pytest.mark.asyncio
async def test_remove_role_by_code():
    repo, session, result = make_repo()
    role = make_role()
    repo.get_required_role_by_code = AsyncMock(return_value=role)  # type: ignore
    repo.remove_role = AsyncMock(return_value=True)  # type: ignore
    res = await repo.remove_role_by_code(user_id=uuid.uuid4(), role_code="admin")
    assert res is True


# ---------------------------------------------------------------------------
# Тесты: user_has_role с role_name / role_code; user_is_admin
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_has_role_with_role_name():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=True)
    res = await repo.user_has_role(user_id=uuid.uuid4(), role_name="admin")
    assert res is True


@pytest.mark.asyncio
async def test_user_has_role_with_role_code_no_active_filter():
    repo, session, result = make_repo()
    result.scalar_one = MagicMock(return_value=False)
    res = await repo.user_has_role(
        user_id=uuid.uuid4(),
        role_code=SystemRole.ADMIN,
        only_active_roles=False,
    )
    assert res is False


@pytest.mark.asyncio
async def test_user_is_admin():
    repo, session, result = make_repo()
    repo.user_has_role = AsyncMock(return_value=True)  # type: ignore
    res = await repo.user_is_admin(uuid.uuid4())
    assert res is True
    assert repo.user_has_role.await_args.kwargs["role_code"] == SystemRole.ADMIN


# ---------------------------------------------------------------------------
# Тесты: exists_user_role db error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exists_user_role_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.exists_user_role(user_id=uuid.uuid4(), role_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_user_roles ordering branch / get_user_role_assignments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_roles_order_by_assigned_at():
    repo, session, result = make_repo()
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    result.scalars.return_value = scalars_result
    res = await repo.get_user_roles(
        uuid.uuid4(),
        only_active_roles=False,
        order_by_name=False,
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_user_role_assignments_returns_list():
    repo, session, result = make_repo()
    ur = make_user_role()
    result.scalars.return_value.all.return_value = [ur]
    res = await repo.get_user_role_assignments(uuid.uuid4())
    assert res == [ur]


@pytest.mark.asyncio
async def test_get_user_role_assignments_unordered():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_user_role_assignments(
        uuid.uuid4(),
        order_by_assigned_at=False,
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_user_role_assignments_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_user_role_assignments(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_user_role_names_order_by_assigned_at():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_user_role_names(
        uuid.uuid4(),
        only_active_roles=False,
        order_by_name=False,
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_user_role_names_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_user_role_names(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_user_role_codes_order_by_assigned_at():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    res = await repo.get_user_role_codes(
        uuid.uuid4(),
        only_active_roles=False,
        order_by_code=False,
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_user_role_codes_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_user_role_codes(uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_users_by_role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_users_by_role_raises_when_no_params():
    repo, session, result = make_repo()
    with pytest.raises(InvalidQueryError):
        await repo.get_users_by_role()


@pytest.mark.asyncio
async def test_get_users_by_role_with_role_id():
    repo, session, result = make_repo()
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    result.scalars.return_value = scalars_result
    res = await repo.get_users_by_role(role_id=uuid.uuid4())
    assert res == []


@pytest.mark.asyncio
async def test_get_users_by_role_resolves_by_name_with_active_filter():
    repo, session, result = make_repo()
    role = make_role()
    repo.get_required_role_by_name = AsyncMock(return_value=role)  # type: ignore
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    result.scalars.return_value = scalars_result
    res = await repo.get_users_by_role(
        role_name="admin",
        only_active_users=True,
        order_by_username=False,
    )
    assert res == []


@pytest.mark.asyncio
async def test_get_users_by_role_resolves_by_code():
    repo, session, result = make_repo()
    role = make_role()
    repo.get_required_role_by_code = AsyncMock(return_value=role)  # type: ignore
    scalars_result = MagicMock()
    scalars_result.unique.return_value.all.return_value = []
    result.scalars.return_value = scalars_result
    res = await repo.get_users_by_role(role_code=SystemRole.USER)
    assert res == []


@pytest.mark.asyncio
async def test_get_users_by_role_raises_on_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_users_by_role(role_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: replace_user_roles
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replace_user_roles_success():
    repo, session, result = make_repo()
    repo._ensure_user_exists = AsyncMock()  # type: ignore
    repo._ensure_roles_exist = AsyncMock()  # type: ignore
    role_ids = [uuid.uuid4(), uuid.uuid4()]
    res = await repo.replace_user_roles(
        user_id=uuid.uuid4(),
        role_ids=role_ids,
        assigned_by=uuid.uuid4(),
    )
    assert len(res) == 2
    session.add_all.assert_called_once()


@pytest.mark.asyncio
async def test_replace_user_roles_empty_does_not_add():
    repo, session, result = make_repo()
    res = await repo.replace_user_roles(
        user_id=uuid.uuid4(),
        role_ids=[],
        check_user_exists=False,
        check_roles_exist=False,
    )
    assert res == []
    session.add_all.assert_not_called()


@pytest.mark.asyncio
async def test_replace_user_roles_integrity_error():
    repo, session, result = make_repo()
    repo.flush = AsyncMock(side_effect=make_integrity_error("23503"))  # type: ignore
    with pytest.raises(RepositoryError):
        await repo.replace_user_roles(
            user_id=uuid.uuid4(),
            role_ids=[uuid.uuid4()],
            check_user_exists=False,
            check_roles_exist=False,
        )


@pytest.mark.asyncio
async def test_replace_user_roles_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.replace_user_roles(
            user_id=uuid.uuid4(),
            role_ids=[uuid.uuid4()],
            assigned_by=uuid.uuid4(),
            check_user_exists=False,
            check_roles_exist=False,
        )


# ---------------------------------------------------------------------------
# Тесты: replace_user_roles_by_codes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replace_user_roles_by_codes_success():
    repo, session, result = make_repo()
    role = make_role(code="admin")
    repo.get_roles_by_codes = AsyncMock(return_value=[role])  # type: ignore
    repo.replace_user_roles = AsyncMock(return_value=["UR"])  # type: ignore
    res = await repo.replace_user_roles_by_codes(
        user_id=uuid.uuid4(),
        role_codes=["admin"],
    )
    assert res == ["UR"]


@pytest.mark.asyncio
async def test_replace_user_roles_by_codes_raises_for_missing():
    repo, session, result = make_repo()
    # запрошен "admin", но ничего не найдено
    repo.get_roles_by_codes = AsyncMock(return_value=[])  # type: ignore
    with pytest.raises(EntityNotFoundError):
        await repo.replace_user_roles_by_codes(
            user_id=uuid.uuid4(),
            role_codes=["admin"],
        )


# ---------------------------------------------------------------------------
# Тесты: clear_user_roles — ветки ошибок
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear_user_roles_integrity_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=make_integrity_error("23503"))
    with pytest.raises(RepositoryError):
        await repo.clear_user_roles(user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_clear_user_roles_sqlalchemy_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.clear_user_roles(user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: _ensure_user_exists / _ensure_roles_exist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_user_exists_raises_when_missing():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EntityNotFoundError):
        await repo._ensure_user_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_user_exists_ok():
    repo, session, result = make_repo()
    session.get = AsyncMock(return_value=MagicMock())
    await repo._ensure_user_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_user_exists_db_error():
    repo, session, result = make_repo()
    session.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._ensure_user_exists(uuid.uuid4())


@pytest.mark.asyncio
async def test_ensure_roles_exist_empty_returns_early():
    repo, session, result = make_repo()
    await repo._ensure_roles_exist([])


@pytest.mark.asyncio
async def test_ensure_roles_exist_all_present():
    repo, session, result = make_repo()
    rid = uuid.uuid4()
    result.scalars.return_value.all.return_value = [rid]
    await repo._ensure_roles_exist([rid])


@pytest.mark.asyncio
async def test_ensure_roles_exist_raises_for_missing():
    repo, session, result = make_repo()
    result.scalars.return_value.all.return_value = []
    with pytest.raises(EntityNotFoundError):
        await repo._ensure_roles_exist([uuid.uuid4()])


@pytest.mark.asyncio
async def test_ensure_roles_exist_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo._ensure_roles_exist([uuid.uuid4()])


@pytest.mark.asyncio
async def test_get_first_admin_user_id_returns_id():
    repo, session, result = make_repo()
    admin_id = uuid.uuid4()
    result.scalar_one_or_none = MagicMock(return_value=admin_id)

    assert await repo.get_first_admin_user_id() == admin_id
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_first_admin_user_id_returns_none_when_no_admins():
    repo, session, result = make_repo()
    result.scalar_one_or_none = MagicMock(return_value=None)

    assert await repo.get_first_admin_user_id() is None


@pytest.mark.asyncio
async def test_get_first_admin_user_id_db_error():
    repo, session, result = make_repo()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))
    with pytest.raises(RepositoryError):
        await repo.get_first_admin_user_id()
