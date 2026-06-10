"""Модульные тесты базового репозитория BaseRepository: CRUD-операции,
пагинация, выборки и преобразование ошибок БД."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from sqlalchemy.orm import Mapped, mapped_column

from database.repositories.base import BaseRepository
from database.models.base import Base
from database.models.users import User
from database.models.enums import UserStatus


class _SinglePKModel(Base):
    """Вспомогательная модель с единственным первичным ключом без поля ``id``."""

    __tablename__ = "_single_pk_model_test_tbl"

    code: Mapped[str] = mapped_column(primary_key=True)


class _CompositePKModel(Base):
    """Вспомогательная модель с составным первичным ключом."""

    __tablename__ = "_composite_pk_model_test_tbl"

    part_a: Mapped[str] = mapped_column(primary_key=True)
    part_b: Mapped[str] = mapped_column(primary_key=True)
from database.exceptions import (
    ConstraintViolationError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidPaginationError,
    InvalidQueryError,
    RepositoryError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_repo(session: AsyncMock | None = None) -> tuple[BaseRepository[User], AsyncMock]:
    session = session or AsyncMock()
    return BaseRepository(session=session, model=User), session


def make_integrity_error(sqlstate: str | None = "23505") -> IntegrityError:
    orig = MagicMock()
    orig.sqlstate = sqlstate
    orig.constraint_name = "uq_users_email"
    orig.table_name = "users"
    orig.column_name = "email"
    exc = IntegrityError("integrity", {}, orig)
    exc.orig = orig
    return exc


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        username="testuser",
        password_hash="hash",
        status=UserStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestBaseRepositoryProperties:
    def test_repository_name_returns_class_name(self) -> None:
        repo, _ = make_repo()
        assert repo.repository_name == "BaseRepository"

    def test_model_name_returns_user(self) -> None:
        repo, _ = make_repo()
        assert repo.model_name == "User"

    def test_table_name_returns_users(self) -> None:
        repo, _ = make_repo()
        assert repo.table_name == "users"


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------

class TestGetById:
    async def test_success_returns_entity(self) -> None:
        repo, session = make_repo()
        user = make_user()
        session.get.return_value = user
        result = await repo.get_by_id(user.id)
        assert result is user

    async def test_entity_not_found_returns_none(self) -> None:
        repo, session = make_repo()
        session.get.return_value = None
        result = await repo.get_by_id(uuid.uuid4())
        assert result is None

    async def test_calls_session_get_with_model_and_id(self) -> None:
        repo, session = make_repo()
        entity_id = uuid.uuid4()
        session.get.return_value = None
        await repo.get_by_id(entity_id)
        session.get.assert_awaited_once_with(User, entity_id)

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.get.side_effect = SQLAlchemyError("db error")
        with pytest.raises(RepositoryError):
            await repo.get_by_id(uuid.uuid4())


# ---------------------------------------------------------------------------
# get_required_by_id
# ---------------------------------------------------------------------------

class TestGetRequiredById:
    async def test_entity_found_returned(self) -> None:
        repo, session = make_repo()
        user = make_user()
        session.get.return_value = user
        result = await repo.get_required_by_id(user.id)
        assert result is user

    async def test_entity_not_found_raises_entity_not_found_error(self) -> None:
        repo, session = make_repo()
        session.get.return_value = None
        entity_id = uuid.uuid4()
        with pytest.raises(EntityNotFoundError) as exc_info:
            await repo.get_required_by_id(entity_id)
        assert "User" in exc_info.value.message

    async def test_entity_not_found_error_contains_entity_id(self) -> None:
        repo, session = make_repo()
        session.get.return_value = None
        entity_id = uuid.uuid4()
        with pytest.raises(EntityNotFoundError) as exc_info:
            await repo.get_required_by_id(entity_id)
        assert exc_info.value.details.get("entity_id") == entity_id


# ---------------------------------------------------------------------------
# scalar_one_or_none
# ---------------------------------------------------------------------------

class TestScalarOneOrNone:
    async def test_success_returns_entity(self) -> None:
        repo, session = make_repo()
        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute.return_value = mock_result
        statement = MagicMock()
        result = await repo.scalar_one_or_none(statement)
        assert result is user

    async def test_returns_none_when_not_found(self) -> None:
        repo, session = make_repo()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result
        result = await repo.scalar_one_or_none(MagicMock())
        assert result is None

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.scalar_one_or_none(MagicMock())


# ---------------------------------------------------------------------------
# scalar_required
# ---------------------------------------------------------------------------

class TestScalarRequired:
    async def test_entity_found_returned(self) -> None:
        repo, session = make_repo()
        user = make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        session.execute.return_value = mock_result
        result = await repo.scalar_required(MagicMock())
        assert result is user

    async def test_entity_not_found_raises_entity_not_found_error(self) -> None:
        repo, session = make_repo()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result
        with pytest.raises(EntityNotFoundError):
            await repo.scalar_required(MagicMock())

    async def test_entity_not_found_contains_model_name(self) -> None:
        repo, session = make_repo()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result
        with pytest.raises(EntityNotFoundError) as exc_info:
            await repo.scalar_required(MagicMock())
        assert "User" in exc_info.value.message


# ---------------------------------------------------------------------------
# scalars_all
# ---------------------------------------------------------------------------

class TestScalarsAll:
    async def test_returns_list_of_entities(self) -> None:
        repo, session = make_repo()
        users = [make_user(), make_user()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = users
        session.execute.return_value = mock_result
        result = await repo.scalars_all(MagicMock())
        assert result == users

    async def test_returns_empty_list_when_no_entities(self) -> None:
        repo, session = make_repo()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result
        result = await repo.scalars_all(MagicMock())
        assert result == []

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.scalars_all(MagicMock())


# ---------------------------------------------------------------------------
# create (add)
# ---------------------------------------------------------------------------

class TestCreate:
    async def test_session_add_called(self) -> None:
        repo, session = make_repo()
        user = make_user()
        result = await repo.create(user, flush=False, refresh=False)
        session.add.assert_called_once_with(user)

    async def test_returns_entity(self) -> None:
        repo, session = make_repo()
        user = make_user()
        result = await repo.create(user, flush=False, refresh=False)
        assert result is user

    async def test_flush_true_calls_flush(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.create(user, flush=True, refresh=False)
        session.flush.assert_awaited_once()

    async def test_flush_false_does_not_flush(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.create(user, flush=False, refresh=False)
        session.flush.assert_not_awaited()

    async def test_refresh_true_calls_refresh(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.create(user, flush=True, refresh=True)
        session.refresh.assert_awaited_once()

    async def test_refresh_false_does_not_refresh(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.create(user, flush=False, refresh=False)
        session.refresh.assert_not_awaited()

    async def test_integrity_error_23505_raises_duplicate_entity_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = make_integrity_error("23505")
        with pytest.raises(DuplicateEntityError):
            await repo.create(make_user(), flush=True)

    async def test_integrity_error_23503_raises_constraint_violation_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = make_integrity_error("23503")
        with pytest.raises(ConstraintViolationError):
            await repo.create(make_user(), flush=True)

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = SQLAlchemyError("error")
        with pytest.raises(RepositoryError):
            await repo.create(make_user(), flush=True)


# ---------------------------------------------------------------------------
# create_many (add_all)
# ---------------------------------------------------------------------------

class TestCreateMany:
    async def test_add_all_called_with_entities(self) -> None:
        repo, session = make_repo()
        users = [make_user(), make_user()]
        await repo.create_many(users, flush=False)
        session.add_all.assert_called_once_with(users)

    async def test_returns_list_of_entities(self) -> None:
        repo, session = make_repo()
        users = [make_user(), make_user()]
        result = await repo.create_many(users, flush=False)
        assert result == users

    async def test_empty_entities_returns_empty_list(self) -> None:
        repo, session = make_repo()
        result = await repo.create_many([], flush=False)
        assert result == []
        session.add_all.assert_not_called()

    async def test_flush_true_calls_flush(self) -> None:
        repo, session = make_repo()
        users = [make_user()]
        await repo.create_many(users, flush=True)
        session.flush.assert_awaited_once()

    async def test_flush_false_does_not_flush(self) -> None:
        repo, session = make_repo()
        users = [make_user()]
        await repo.create_many(users, flush=False)
        session.flush.assert_not_awaited()

    async def test_integrity_error_23505_raises_duplicate_entity_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = make_integrity_error("23505")
        with pytest.raises(DuplicateEntityError):
            await repo.create_many([make_user()], flush=True)

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = SQLAlchemyError("error")
        with pytest.raises(RepositoryError):
            await repo.create_many([make_user()], flush=True)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

class TestUpdate:
    async def test_fields_set_on_entity(self) -> None:
        repo, session = make_repo()
        user = make_user()
        new_email = "new@example.com"
        await repo.update(user, {"email": new_email}, flush=False)
        assert user.email == new_email

    async def test_flush_true_calls_flush(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.update(user, {"email": "x@x.com"}, flush=True)
        session.flush.assert_awaited_once()

    async def test_flush_false_does_not_flush(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.update(user, {"email": "x@x.com"}, flush=False)
        session.flush.assert_not_awaited()

    async def test_refresh_true_calls_refresh(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.update(user, {"email": "x@x.com"}, flush=True, refresh=True)
        session.refresh.assert_awaited_once()

    async def test_refresh_false_does_not_refresh(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.update(user, {"email": "x@x.com"}, flush=False, refresh=False)
        session.refresh.assert_not_awaited()

    async def test_field_not_in_allowed_fields_raises_invalid_query_error(self) -> None:
        repo, session = make_repo()
        user = make_user()
        with pytest.raises(InvalidQueryError):
            await repo.update(user, {"email": "x@x.com"}, allowed_fields=["username"], flush=False)

    async def test_non_existent_field_raises_invalid_query_error(self) -> None:
        repo, session = make_repo()
        user = make_user()
        with pytest.raises(InvalidQueryError):
            await repo.update(user, {"nonexistent_field": "value"}, flush=False)

    async def test_integrity_error_23505_raises_duplicate_entity_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = make_integrity_error("23505")
        user = make_user()
        with pytest.raises(DuplicateEntityError):
            await repo.update(user, {"email": "x@x.com"}, flush=True)

    async def test_integrity_error_23503_raises_constraint_violation_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = make_integrity_error("23503")
        user = make_user()
        with pytest.raises(ConstraintViolationError):
            await repo.update(user, {"email": "x@x.com"}, flush=True)

    async def test_returns_updated_entity(self) -> None:
        repo, session = make_repo()
        user = make_user()
        result = await repo.update(user, {"email": "new@example.com"}, flush=False)
        assert result is user

    async def test_exclude_none_skips_none_values(self) -> None:
        repo, session = make_repo()
        user = make_user()
        original_email = user.email
        await repo.update(user, {"email": None}, flush=False, exclude_none=True)
        # Не должно перезаписывать значение на None
        assert user.email == original_email


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

class TestDelete:
    async def test_session_delete_called(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.delete(user, flush=False)
        session.delete.assert_awaited_once_with(user)

    async def test_flush_true_calls_flush(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.delete(user, flush=True)
        session.flush.assert_awaited_once()

    async def test_flush_false_does_not_flush(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.delete(user, flush=False)
        session.flush.assert_not_awaited()

    async def test_integrity_error_raises_constraint_violation_error(self) -> None:
        repo, session = make_repo()
        user = make_user()
        session.delete.side_effect = make_integrity_error("23503")
        with pytest.raises(ConstraintViolationError):
            await repo.delete(user, flush=False)

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        user = make_user()
        session.delete.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.delete(user, flush=False)


# ---------------------------------------------------------------------------
# flush
# ---------------------------------------------------------------------------

class TestFlush:
    async def test_session_flush_called(self) -> None:
        repo, session = make_repo()
        await repo.flush()
        session.flush.assert_awaited_once()

    async def test_integrity_error_23505_raises_duplicate_entity_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = make_integrity_error("23505")
        with pytest.raises(DuplicateEntityError):
            await repo.flush()

    async def test_integrity_error_23503_raises_constraint_violation_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = make_integrity_error("23503")
        with pytest.raises(ConstraintViolationError):
            await repo.flush()

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.flush()


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------

class TestRefresh:
    async def test_session_refresh_called_with_entity(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.refresh(user)
        session.refresh.assert_awaited_once_with(user, attribute_names=None)

    async def test_returns_entity(self) -> None:
        repo, session = make_repo()
        user = make_user()
        result = await repo.refresh(user)
        assert result is user

    async def test_attribute_names_passed_to_session(self) -> None:
        repo, session = make_repo()
        user = make_user()
        await repo.refresh(user, attribute_names=["email"])
        session.refresh.assert_awaited_once_with(user, attribute_names=["email"])

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        user = make_user()
        session.refresh.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.refresh(user)


# ---------------------------------------------------------------------------
# _validate_pagination
# ---------------------------------------------------------------------------

class TestValidatePagination:
    def test_valid_values_no_exception(self) -> None:
        repo, _ = make_repo()
        repo._validate_pagination(offset=0, limit=10)  # Не должно вызывать исключение

    def test_offset_negative_raises_invalid_pagination_error(self) -> None:
        repo, _ = make_repo()
        with pytest.raises(InvalidPaginationError):
            repo._validate_pagination(offset=-1, limit=10)

    def test_limit_zero_raises_invalid_pagination_error(self) -> None:
        repo, _ = make_repo()
        with pytest.raises(InvalidPaginationError):
            repo._validate_pagination(offset=0, limit=0)

    def test_limit_negative_raises_invalid_pagination_error(self) -> None:
        repo, _ = make_repo()
        with pytest.raises(InvalidPaginationError):
            repo._validate_pagination(offset=0, limit=-5)

    def test_limit_exceeds_max_raises_invalid_pagination_error(self) -> None:
        repo, _ = make_repo()
        with pytest.raises(InvalidPaginationError):
            repo._validate_pagination(offset=0, limit=1001)

    def test_limit_at_max_no_exception(self) -> None:
        repo, _ = make_repo()
        repo._validate_pagination(offset=0, limit=1000)  # Не должно вызывать исключение

    def test_offset_zero_no_exception(self) -> None:
        repo, _ = make_repo()
        repo._validate_pagination(offset=0, limit=1)  # Не должно вызывать исключение


# ---------------------------------------------------------------------------
# _handle_integrity_error
# ---------------------------------------------------------------------------

class TestHandleIntegrityError:
    def test_sqlstate_23505_returns_duplicate_entity_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23505")
        result = repo._handle_integrity_error(exc, operation="create")
        assert isinstance(result, DuplicateEntityError)

    def test_sqlstate_23503_returns_constraint_violation_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23503")
        result = repo._handle_integrity_error(exc, operation="create")
        assert isinstance(result, ConstraintViolationError)

    def test_sqlstate_23514_returns_constraint_violation_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23514")
        result = repo._handle_integrity_error(exc, operation="create")
        assert isinstance(result, ConstraintViolationError)

    def test_sqlstate_23502_returns_constraint_violation_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23502")
        result = repo._handle_integrity_error(exc, operation="create")
        assert isinstance(result, ConstraintViolationError)

    def test_unknown_sqlstate_returns_repository_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("99999")
        result = repo._handle_integrity_error(exc, operation="create")
        assert isinstance(result, RepositoryError)

    def test_none_sqlstate_returns_repository_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error(None)
        result = repo._handle_integrity_error(exc, operation="create")
        assert isinstance(result, RepositoryError)

    def test_23505_is_subclass_of_repository_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23505")
        result = repo._handle_integrity_error(exc, operation="create")
        assert isinstance(result, RepositoryError)

    def test_23503_is_subclass_of_repository_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23503")
        result = repo._handle_integrity_error(exc, operation="create")
        assert isinstance(result, RepositoryError)

    def test_cause_stored_in_duplicate_entity_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23505")
        result = repo._handle_integrity_error(exc, operation="create")
        assert result.cause is exc

    def test_cause_stored_in_constraint_violation_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23503")
        result = repo._handle_integrity_error(exc, operation="delete")
        assert result.cause is exc

    def test_23502_returns_constraint_violation_error(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23502")
        result = repo._handle_integrity_error(exc, operation="update")
        assert isinstance(result, ConstraintViolationError)

    def test_constraint_violation_details_carry_sqlstate(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23503")
        result = repo._handle_integrity_error(exc, operation="create")
        assert result.details.get("sqlstate") == "23503"
        assert result.details.get("constraint_name") == "uq_users_email"
        assert result.details.get("table_name") == "users"
        assert result.details.get("column_name") == "email"

    def test_duplicate_entity_uses_constraint_name_as_field(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("23505")
        result = repo._handle_integrity_error(exc, operation="create")
        assert result.details.get("field") == "uq_users_email"

    def test_unknown_sqlstate_details_carry_diagnostics(self) -> None:
        repo, _ = make_repo()
        exc = make_integrity_error("99999")
        result = repo._handle_integrity_error(exc, operation="bulk_delete")
        assert result.details.get("sqlstate") == "99999"
        assert result.details.get("operation") == "bulk_delete"
        assert result.details.get("model") == "User"
        assert result.details.get("table") == "users"

    def test_missing_orig_attribute_returns_repository_error(self) -> None:
        repo, _ = make_repo()
        exc = IntegrityError("integrity", {}, Exception("boom"))
        exc.orig = None
        result = repo._handle_integrity_error(exc, operation="create")
        assert isinstance(result, RepositoryError)
        assert result.details.get("sqlstate") is None


# ---------------------------------------------------------------------------
# Helpers for SELECT-based methods
# ---------------------------------------------------------------------------

def make_scalar_one_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def make_scalar_one_or_none_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def make_scalars_all_result(values: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


# ---------------------------------------------------------------------------
# select / select_where
# ---------------------------------------------------------------------------

class TestSelect:
    def test_select_targets_model(self) -> None:
        repo, _ = make_repo()
        statement = repo.select()
        assert statement.get_final_froms()[0] is User.__table__

    def test_select_where_without_conditions_returns_base_select(self) -> None:
        repo, _ = make_repo()
        statement = repo.select_where()
        assert statement.whereclause is None

    def test_select_where_with_conditions_applies_where(self) -> None:
        repo, _ = make_repo()
        statement = repo.select_where(User.email == "x@x.com")
        assert statement.whereclause is not None


# ---------------------------------------------------------------------------
# get_one_or_none
# ---------------------------------------------------------------------------

class TestGetOneOrNone:
    async def test_returns_entity(self) -> None:
        repo, session = make_repo()
        user = make_user()
        session.execute.return_value = make_scalar_one_or_none_result(user)
        result = await repo.get_one_or_none(User.email == "test@example.com")
        assert result is user

    async def test_returns_none(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalar_one_or_none_result(None)
        result = await repo.get_one_or_none(User.email == "missing@example.com")
        assert result is None

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.get_one_or_none(User.email == "x@x.com")


# ---------------------------------------------------------------------------
# scalar_value
# ---------------------------------------------------------------------------

class TestScalarValue:
    async def test_returns_value(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalar_one_or_none_result(42)
        result = await repo.scalar_value(MagicMock())
        assert result == 42

    async def test_returns_none_when_no_value(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalar_one_or_none_result(None)
        result = await repo.scalar_value(MagicMock())
        assert result is None

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.scalar_value(MagicMock())


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

class TestList:
    async def test_returns_entities(self) -> None:
        repo, session = make_repo()
        users = [make_user(), make_user()]
        session.execute.return_value = make_scalars_all_result(users)
        result = await repo.list()
        assert result == users

    async def test_invalid_pagination_raises_before_query(self) -> None:
        repo, session = make_repo()
        with pytest.raises(InvalidPaginationError):
            await repo.list(offset=-1)
        session.execute.assert_not_awaited()

    async def test_conditions_applied(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list(conditions=[User.email == "x@x.com"])
        statement = session.execute.await_args.args[0]
        assert statement.whereclause is not None

    async def test_order_by_single_expression(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list(order_by=User.email)
        statement = session.execute.await_args.args[0]
        assert statement._order_by_clauses

    async def test_order_by_sequence(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list(order_by=[User.email, User.username])
        statement = session.execute.await_args.args[0]
        assert len(statement._order_by_clauses) == 2

    async def test_offset_and_limit_applied(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list(offset=5, limit=10)
        statement = session.execute.await_args.args[0]
        assert statement._offset == 5
        assert statement._limit == 10

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.list()


# ---------------------------------------------------------------------------
# list_keyset
# ---------------------------------------------------------------------------

class TestListKeyset:
    async def test_returns_entities(self) -> None:
        repo, session = make_repo()
        users = [make_user(), make_user()]
        session.execute.return_value = make_scalars_all_result(users)
        result = await repo.list_keyset(limit=10)
        assert result == users

    async def test_no_offset_and_limit_applied(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list_keyset(limit=25)
        statement = session.execute.await_args.args[0]
        assert statement._offset is None
        assert statement._limit == 25

    async def test_orders_by_primary_key(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list_keyset(limit=10)
        statement = session.execute.await_args.args[0]
        assert len(statement._order_by_clauses) == 1
        assert "users.id" in str(statement)

    async def test_first_page_has_no_whereclause(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list_keyset(limit=10)
        statement = session.execute.await_args.args[0]
        assert statement.whereclause is None

    async def test_after_applies_keyset_condition(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list_keyset(limit=10, after=uuid.uuid4())
        statement = session.execute.await_args.args[0]
        assert statement.whereclause is not None
        assert "users.id >" in str(statement)

    async def test_conditions_applied(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list_keyset(limit=10, conditions=[User.email == "x@x.com"])
        statement = session.execute.await_args.args[0]
        assert statement.whereclause is not None

    async def test_descending_uses_desc_and_less_than(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list_keyset(limit=10, after=uuid.uuid4(), ascending=False)
        rendered = str(session.execute.await_args.args[0])
        assert "users.id <" in rendered
        assert "DESC" in rendered

    async def test_custom_cursor_column(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalars_all_result([])
        await repo.list_keyset(limit=10, cursor_column=User.created_at)
        assert "users.created_at" in str(session.execute.await_args.args[0])

    async def test_invalid_limit_raises_before_query(self) -> None:
        repo, session = make_repo()
        with pytest.raises(InvalidPaginationError):
            await repo.list_keyset(limit=0)
        session.execute.assert_not_awaited()

    async def test_non_id_primary_key_resolved(self) -> None:
        # Курсор по умолчанию берётся из первичного ключа, даже если он не ``id``.
        repo = BaseRepository(session=AsyncMock(), model=_SinglePKModel)
        repo.session.execute.return_value = make_scalars_all_result([])
        await repo.list_keyset(limit=10, after="abc")
        rendered = str(repo.session.execute.await_args.args[0])
        assert "_single_pk_model_test_tbl.code >" in rendered

    async def test_composite_primary_key_without_cursor_raises(self) -> None:
        repo = BaseRepository(session=AsyncMock(), model=_CompositePKModel)
        with pytest.raises(RepositoryError):
            await repo.list_keyset(limit=10)
        repo.session.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------

class TestExists:
    async def test_true_when_record_present(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalar_one_result(True)
        result = await repo.exists(User.email == "x@x.com")
        assert result is True

    async def test_false_when_no_record(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalar_one_result(False)
        result = await repo.exists()
        assert result is False

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.exists()


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------

class TestCount:
    async def test_returns_count(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalar_one_result(7)
        result = await repo.count()
        assert result == 7

    async def test_conditions_applied(self) -> None:
        repo, session = make_repo()
        session.execute.return_value = make_scalar_one_result(3)
        await repo.count(User.email == "x@x.com")
        statement = session.execute.await_args.args[0]
        assert statement.whereclause is not None

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.count()


# ---------------------------------------------------------------------------
# paginate
# ---------------------------------------------------------------------------

class TestPaginate:
    async def test_returns_items_and_total(self) -> None:
        repo, session = make_repo()
        users = [make_user(), make_user()]
        session.execute.side_effect = [
            make_scalars_all_result(users),
            make_scalar_one_result(5),
        ]
        items, total = await repo.paginate(limit=2)
        assert items == users
        assert total == 5

    async def test_invalid_pagination_raises(self) -> None:
        repo, session = make_repo()
        with pytest.raises(InvalidPaginationError):
            await repo.paginate(limit=0)
        session.execute.assert_not_awaited()

    async def test_conditions_forwarded_to_count(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = [
            make_scalars_all_result([]),
            make_scalar_one_result(0),
        ]
        items, total = await repo.paginate(conditions=[User.email == "x@x.com"])
        assert items == []
        assert total == 0
        count_statement = session.execute.await_args_list[1].args[0]
        assert count_statement.whereclause is not None


# ---------------------------------------------------------------------------
# bulk_delete
# ---------------------------------------------------------------------------

class TestBulkDelete:
    async def test_returns_rowcount(self) -> None:
        repo, session = make_repo()
        result_obj = MagicMock()
        result_obj.rowcount = 4
        session.execute.return_value = result_obj
        deleted = await repo.bulk_delete(User.email == "x@x.com")
        assert deleted == 4

    async def test_rowcount_none_returns_zero(self) -> None:
        repo, session = make_repo()
        result_obj = MagicMock()
        result_obj.rowcount = None
        session.execute.return_value = result_obj
        deleted = await repo.bulk_delete()
        assert deleted == 0

    async def test_flush_true_calls_flush(self) -> None:
        repo, session = make_repo()
        result_obj = MagicMock()
        result_obj.rowcount = 1
        session.execute.return_value = result_obj
        await repo.bulk_delete(flush=True)
        session.flush.assert_awaited_once()

    async def test_flush_false_does_not_flush(self) -> None:
        repo, session = make_repo()
        result_obj = MagicMock()
        result_obj.rowcount = 1
        session.execute.return_value = result_obj
        await repo.bulk_delete(flush=False)
        session.flush.assert_not_awaited()

    async def test_conditions_applied(self) -> None:
        repo, session = make_repo()
        result_obj = MagicMock()
        result_obj.rowcount = 0
        session.execute.return_value = result_obj
        await repo.bulk_delete(User.email == "x@x.com", flush=False)
        statement = session.execute.await_args.args[0]
        assert statement.whereclause is not None

    async def test_integrity_error_raises_constraint_violation_error(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = make_integrity_error("23503")
        with pytest.raises(ConstraintViolationError):
            await repo.bulk_delete(flush=False)

    async def test_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.execute.side_effect = SQLAlchemyError("fail")
        with pytest.raises(RepositoryError):
            await repo.bulk_delete()


# ---------------------------------------------------------------------------
# create / create_many / update: проброс ошибок целостности
# ---------------------------------------------------------------------------

class TestIntegrityRethrowChaining:
    async def test_create_integrity_error_chains_cause(self) -> None:
        repo, session = make_repo()
        exc = make_integrity_error("23505")
        session.flush.side_effect = exc
        with pytest.raises(DuplicateEntityError) as exc_info:
            await repo.create(make_user(), flush=True)
        assert exc_info.value.__cause__ is exc

    async def test_create_unknown_integrity_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = make_integrity_error("99999")
        with pytest.raises(RepositoryError):
            await repo.create(make_user(), flush=True)

    async def test_create_many_unknown_integrity_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = make_integrity_error("99999")
        with pytest.raises(RepositoryError):
            await repo.create_many([make_user()], flush=True)

    async def test_create_many_sqlalchemy_error_message(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = SQLAlchemyError("boom")
        with pytest.raises(RepositoryError):
            await repo.create_many([make_user()], flush=True)

    async def test_update_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, session = make_repo()
        session.flush.side_effect = SQLAlchemyError("boom")
        with pytest.raises(RepositoryError):
            await repo.update(make_user(), {"email": "x@x.com"}, flush=True)

    async def test_update_invalid_query_error_not_remapped(self) -> None:
        repo, session = make_repo()
        with pytest.raises(InvalidQueryError):
            await repo.update(
                make_user(),
                {"nope": "value"},
                flush=False,
            )


# ---------------------------------------------------------------------------
# _get_primary_key_column
# ---------------------------------------------------------------------------

class TestGetPrimaryKeyColumn:
    def test_model_with_id_returns_id_column(self) -> None:
        repo, _ = make_repo()
        column = repo._get_primary_key_column()
        assert column is User.id

    def test_composite_primary_key_raises_repository_error(self) -> None:
        repo = BaseRepository(session=AsyncMock(), model=_CompositePKModel)
        with pytest.raises(RepositoryError) as exc_info:
            repo._get_primary_key_column()
        assert exc_info.value.details.get("model") == "_CompositePKModel"
        assert set(exc_info.value.details.get("primary_key_columns")) == {
            "part_a",
            "part_b",
        }

    def test_single_non_id_primary_key_returns_column(self) -> None:
        repo = BaseRepository(session=AsyncMock(), model=_SinglePKModel)
        column = repo._get_primary_key_column()
        assert column is _SinglePKModel.code


# ---------------------------------------------------------------------------
# _apply_order_by
# ---------------------------------------------------------------------------

class TestApplyOrderBy:
    def test_none_returns_statement_unchanged(self) -> None:
        repo, _ = make_repo()
        statement = repo.select()
        result = repo._apply_order_by(statement, None)
        assert result is statement
        assert not result._order_by_clauses

    def test_single_expression_applied(self) -> None:
        repo, _ = make_repo()
        result = repo._apply_order_by(repo.select(), User.email)
        assert len(result._order_by_clauses) == 1

    def test_sequence_applied(self) -> None:
        repo, _ = make_repo()
        result = repo._apply_order_by(repo.select(), [User.email, User.username])
        assert len(result._order_by_clauses) == 2

    def test_string_order_by_treated_as_single(self) -> None:
        repo, _ = make_repo()
        result = repo._apply_order_by(repo.select(), "email")
        assert len(result._order_by_clauses) == 1


# ---------------------------------------------------------------------------
# Внешние обработчики ошибок create/create_many/update
#
# flush() внутри преобразует IntegrityError -> DuplicateEntityError, поэтому
# внешние блоки except в create/create_many/update срабатывают только если
# исходная ошибка доходит до них другим путём. Подменяем метод repo.flush так,
# чтобы он напрямую выбрасывал исходные ошибки.
# ---------------------------------------------------------------------------

class TestCreateOuterHandlers:
    async def test_create_integrity_error_raises_duplicate(self) -> None:
        repo, _ = make_repo()
        repo.flush = AsyncMock(side_effect=make_integrity_error("23505"))
        with pytest.raises(DuplicateEntityError):
            await repo.create(make_user(), flush=True)

    async def test_create_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, _ = make_repo()
        repo.flush = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with pytest.raises(RepositoryError):
            await repo.create(make_user(), flush=True)

    async def test_create_many_integrity_error_raises_duplicate(self) -> None:
        repo, _ = make_repo()
        repo.flush = AsyncMock(side_effect=make_integrity_error("23505"))
        with pytest.raises(DuplicateEntityError):
            await repo.create_many([make_user()], flush=True)

    async def test_create_many_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, _ = make_repo()
        repo.flush = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with pytest.raises(RepositoryError):
            await repo.create_many([make_user()], flush=True)

    async def test_update_integrity_error_raises_duplicate(self) -> None:
        repo, _ = make_repo()
        repo.flush = AsyncMock(side_effect=make_integrity_error("23505"))
        with pytest.raises(DuplicateEntityError):
            await repo.update(make_user(), {"username": "newname"}, flush=True)

    async def test_update_sqlalchemy_error_raises_repository_error(self) -> None:
        repo, _ = make_repo()
        repo.flush = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with pytest.raises(RepositoryError):
            await repo.update(make_user(), {"username": "newname"}, flush=True)
