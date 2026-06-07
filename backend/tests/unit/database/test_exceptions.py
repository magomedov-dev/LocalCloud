"""Модульные тесты иерархии исключений БД: сообщения, детали, причины и наследование."""
from __future__ import annotations

import uuid

import pytest

from database.exceptions import (
    ConstraintViolationError,
    DatabaseConnectionError,
    DatabaseError,
    DatabaseHealthCheckError,
    DatabaseTimeoutError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidPaginationError,
    InvalidQueryError,
    RepositoryError,
    TransactionCommitError,
    TransactionError,
    TransactionRollbackError,
    UnitOfWorkError,
)


class TestDatabaseError:
    def test_default_message(self) -> None:
        err = DatabaseError()
        assert err.message

    def test_custom_message_stored(self) -> None:
        err = DatabaseError("custom db error")
        assert err.message == "custom db error"

    def test_details_copied(self) -> None:
        original = {"key": "value"}
        err = DatabaseError(details=original)
        original["key"] = "changed"
        assert err.details["key"] == "value"

    def test_empty_details_default(self) -> None:
        err = DatabaseError()
        assert err.details == {}

    def test_cause_stored(self) -> None:
        cause = IOError("connection failed")
        err = DatabaseError(cause=cause)
        assert err.cause is cause
        assert err.__cause__ is cause

    def test_str_without_details(self) -> None:
        err = DatabaseError("simple")
        assert str(err) == "simple"

    def test_str_with_details(self) -> None:
        err = DatabaseError("msg", details={"x": 1})
        result = str(err)
        assert "msg" in result
        assert "Details" in result

    def test_to_dict_required_keys(self) -> None:
        err = DatabaseError("test")
        d = err.to_dict()
        assert d["error"] == "DatabaseError"
        assert d["message"] == "test"

    def test_to_dict_includes_details(self) -> None:
        err = DatabaseError("test", details={"k": "v"})
        assert err.to_dict()["details"]["k"] == "v"

    def test_to_dict_omits_empty_details(self) -> None:
        err = DatabaseError("test")
        assert "details" not in err.to_dict()

    def test_to_dict_includes_cause(self) -> None:
        err = DatabaseError(cause=ValueError("root"))
        assert err.to_dict()["cause"] == "ValueError"

    def test_to_dict_omits_cause_when_none(self) -> None:
        err = DatabaseError()
        assert "cause" not in err.to_dict()


class TestDatabaseConnectionError:
    def test_is_database_error_subclass(self) -> None:
        assert issubclass(DatabaseConnectionError, DatabaseError)

    def test_host_added_to_details(self) -> None:
        err = DatabaseConnectionError(host="localhost")
        assert err.details["host"] == "localhost"

    def test_port_added_to_details(self) -> None:
        err = DatabaseConnectionError(port=5432)
        assert err.details["port"] == 5432

    def test_database_added_to_details(self) -> None:
        err = DatabaseConnectionError(database="mydb")
        assert err.details["database"] == "mydb"

    def test_none_fields_not_in_details(self) -> None:
        err = DatabaseConnectionError()
        assert "host" not in err.details
        assert "port" not in err.details

    def test_all_fields(self) -> None:
        err = DatabaseConnectionError(host="db", port=5432, database="mydb")
        assert err.details["host"] == "db"
        assert err.details["port"] == 5432
        assert err.details["database"] == "mydb"


class TestDatabaseTimeoutError:
    def test_is_database_error_subclass(self) -> None:
        assert issubclass(DatabaseTimeoutError, DatabaseError)

    def test_operation_added_to_details(self) -> None:
        err = DatabaseTimeoutError(operation="query")
        assert err.details["operation"] == "query"

    def test_timeout_seconds_added_to_details(self) -> None:
        err = DatabaseTimeoutError(timeout_seconds=30.0)
        assert err.details["timeout_seconds"] == 30.0

    def test_none_fields_not_in_details(self) -> None:
        err = DatabaseTimeoutError()
        assert "operation" not in err.details


class TestTransactionErrors:
    def test_transaction_error_is_database_error(self) -> None:
        assert issubclass(TransactionError, DatabaseError)

    def test_transaction_error_operation_added(self) -> None:
        err = TransactionError(operation="commit")
        assert err.details["operation"] == "commit"

    def test_commit_error_is_transaction_error(self) -> None:
        assert issubclass(TransactionCommitError, TransactionError)

    def test_commit_error_has_commit_operation(self) -> None:
        err = TransactionCommitError()
        assert err.details.get("operation") == "commit"

    def test_rollback_error_is_transaction_error(self) -> None:
        assert issubclass(TransactionRollbackError, TransactionError)

    def test_rollback_error_has_rollback_operation(self) -> None:
        err = TransactionRollbackError()
        assert err.details.get("operation") == "rollback"

    def test_uow_error_is_transaction_error(self) -> None:
        assert issubclass(UnitOfWorkError, TransactionError)

    def test_uow_error_has_unit_of_work_operation(self) -> None:
        err = UnitOfWorkError()
        assert err.details.get("operation") == "unit_of_work"


class TestRepositoryError:
    def test_is_database_error_subclass(self) -> None:
        assert issubclass(RepositoryError, DatabaseError)

    def test_repository_added_to_details(self) -> None:
        err = RepositoryError(repository="UserRepository")
        assert err.details["repository"] == "UserRepository"

    def test_operation_added_to_details(self) -> None:
        err = RepositoryError(operation="create")
        assert err.details["operation"] == "create"

    def test_none_fields_not_in_details(self) -> None:
        err = RepositoryError()
        assert "repository" not in err.details


class TestDuplicateEntityError:
    def test_is_repository_error(self) -> None:
        assert issubclass(DuplicateEntityError, RepositoryError)

    def test_entity_name_in_details(self) -> None:
        err = DuplicateEntityError("User")
        assert err.details["entity"] == "User"

    def test_field_in_details(self) -> None:
        err = DuplicateEntityError("User", field="email")
        assert err.details["field"] == "email"

    def test_value_in_details(self) -> None:
        err = DuplicateEntityError("User", field="email", value="a@b.com")
        assert err.details["value"] == "a@b.com"

    def test_auto_message_without_field(self) -> None:
        err = DuplicateEntityError("User")
        assert "User" in err.message

    def test_auto_message_with_field_and_value(self) -> None:
        err = DuplicateEntityError("User", field="email", value="a@b.com")
        assert "email" in err.message
        assert "a@b.com" in err.message

    def test_custom_message_overrides_auto(self) -> None:
        err = DuplicateEntityError("User", message="custom message")
        assert err.message == "custom message"

    def test_operation_is_create(self) -> None:
        err = DuplicateEntityError("User")
        assert err.details.get("operation") == "create"


class TestEntityNotFoundError:
    def test_is_repository_error(self) -> None:
        assert issubclass(EntityNotFoundError, RepositoryError)

    def test_entity_name_in_details(self) -> None:
        err = EntityNotFoundError("User")
        assert err.details["entity"] == "User"

    def test_entity_id_in_details(self) -> None:
        uid = uuid.uuid4()
        err = EntityNotFoundError("User", entity_id=uid)
        assert err.details["entity_id"] == uid

    def test_lookup_in_details(self) -> None:
        err = EntityNotFoundError("User", lookup={"email": "a@b.com"})
        assert err.details["lookup"]["email"] == "a@b.com"

    def test_auto_message(self) -> None:
        err = EntityNotFoundError("User")
        assert "User" in err.message

    def test_custom_message(self) -> None:
        err = EntityNotFoundError("User", message="User not found at all")
        assert err.message == "User not found at all"

    def test_operation_is_get(self) -> None:
        err = EntityNotFoundError("User")
        assert err.details.get("operation") == "get"


class TestConstraintViolationError:
    def test_is_repository_error(self) -> None:
        assert issubclass(ConstraintViolationError, RepositoryError)

    def test_constraint_name_in_details(self) -> None:
        err = ConstraintViolationError(constraint_name="uq_users_email")
        assert err.details["constraint_name"] == "uq_users_email"

    def test_table_name_in_details(self) -> None:
        err = ConstraintViolationError(table_name="users")
        assert err.details["table_name"] == "users"

    def test_column_name_in_details(self) -> None:
        err = ConstraintViolationError(column_name="email")
        assert err.details["column_name"] == "email"

    def test_none_fields_not_in_details(self) -> None:
        err = ConstraintViolationError()
        assert "constraint_name" not in err.details


class TestInvalidQueryErrors:
    def test_invalid_query_is_repository_error(self) -> None:
        assert issubclass(InvalidQueryError, RepositoryError)

    def test_invalid_pagination_is_invalid_query(self) -> None:
        assert issubclass(InvalidPaginationError, InvalidQueryError)

    def test_invalid_pagination_limit_in_details(self) -> None:
        err = InvalidPaginationError(limit=0)
        assert err.details["limit"] == 0

    def test_invalid_pagination_offset_in_details(self) -> None:
        err = InvalidPaginationError(offset=-5)
        assert err.details["offset"] == -5

    def test_invalid_pagination_max_limit_in_details(self) -> None:
        err = InvalidPaginationError(max_limit=100)
        assert err.details["max_limit"] == 100

    def test_invalid_pagination_operation(self) -> None:
        err = InvalidPaginationError()
        assert err.details.get("operation") == "paginate"


class TestDatabaseHealthCheckError:
    def test_is_database_error(self) -> None:
        assert issubclass(DatabaseHealthCheckError, DatabaseError)

    def test_default_message(self) -> None:
        err = DatabaseHealthCheckError()
        assert err.message

    def test_custom_message(self) -> None:
        err = DatabaseHealthCheckError("health check failed")
        assert err.message == "health check failed"
