"""Юнит-тесты безопасных транзакционных хелперов (commit/rollback/flush/refresh)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from sqlalchemy.exc import SQLAlchemyError, TimeoutError as SATimeoutError

from database.transactions import (
    safe_commit,
    safe_rollback,
    safe_flush,
    safe_refresh,
    ensure_transaction_closed,
)
from database.exceptions import (
    DatabaseTimeoutError,
    TransactionCommitError,
    TransactionError,
    TransactionRollbackError,
)


# ---------------------------------------------------------------------------
# safe_commit
# ---------------------------------------------------------------------------

class TestSafeCommit:
    async def test_success_calls_commit(self) -> None:
        session = AsyncMock()
        await safe_commit(session)
        session.commit.assert_awaited_once()

    async def test_success_no_exception(self) -> None:
        session = AsyncMock()
        # Не должно выбрасывать исключений
        await safe_commit(session)

    async def test_sqlalchemy_error_raises_commit_error(self) -> None:
        session = AsyncMock()
        session.commit.side_effect = SQLAlchemyError("db error")
        with pytest.raises(TransactionCommitError) as exc_info:
            await safe_commit(session)
        assert exc_info.value.cause is not None

    async def test_sqlalchemy_error_attempts_rollback(self) -> None:
        session = AsyncMock()
        session.commit.side_effect = SQLAlchemyError("db error")
        with pytest.raises(TransactionCommitError):
            await safe_commit(session)
        session.rollback.assert_awaited_once()

    async def test_sqlalchemy_error_cause_stored(self) -> None:
        session = AsyncMock()
        original_error = SQLAlchemyError("original")
        session.commit.side_effect = original_error
        with pytest.raises(TransactionCommitError) as exc_info:
            await safe_commit(session)
        assert exc_info.value.cause is original_error

    async def test_timeout_error_raises_database_timeout_error(self) -> None:
        session = AsyncMock()
        session.commit.side_effect = SATimeoutError("timeout")
        with pytest.raises(DatabaseTimeoutError):
            await safe_commit(session)

    async def test_timeout_error_cause_stored(self) -> None:
        session = AsyncMock()
        original_error = SATimeoutError("timeout")
        session.commit.side_effect = original_error
        with pytest.raises(DatabaseTimeoutError) as exc_info:
            await safe_commit(session)
        assert exc_info.value.cause is original_error

    async def test_rollback_failure_after_commit_error_stored_in_details(self) -> None:
        session = AsyncMock()
        session.commit.side_effect = SQLAlchemyError("commit failed")
        session.rollback.side_effect = SQLAlchemyError("rollback also failed")

        with pytest.raises(TransactionCommitError) as exc_info:
            await safe_commit(session)

        details = exc_info.value.details
        assert "rollback_error" in details

    async def test_custom_operation_passed_to_build_error_details(self) -> None:
        # operation попадает в исходный словарь details, передаваемый в ошибку,
        # хотя TransactionCommitError выставляет свой ключ 'operation' = "commit".
        # Проверяем, что ошибка выброшена и commit был вызван.
        session = AsyncMock()
        session.commit.side_effect = SQLAlchemyError("fail")
        with pytest.raises(TransactionCommitError):
            await safe_commit(session, operation="my_op")


# ---------------------------------------------------------------------------
# safe_rollback
# ---------------------------------------------------------------------------

class TestSafeRollback:
    async def test_success_calls_rollback(self) -> None:
        session = AsyncMock()
        await safe_rollback(session)
        session.rollback.assert_awaited_once()

    async def test_success_no_exception(self) -> None:
        session = AsyncMock()
        await safe_rollback(session)

    async def test_sqlalchemy_error_suppress_false_raises(self) -> None:
        session = AsyncMock()
        session.rollback.side_effect = SQLAlchemyError("rollback failed")
        with pytest.raises(TransactionRollbackError):
            await safe_rollback(session, suppress_errors=False)

    async def test_sqlalchemy_error_suppress_true_no_exception(self) -> None:
        session = AsyncMock()
        session.rollback.side_effect = SQLAlchemyError("rollback failed")
        # Не должно выбрасывать при suppress_errors=True
        await safe_rollback(session, suppress_errors=True)

    async def test_sqlalchemy_error_default_suppress_false_raises(self) -> None:
        session = AsyncMock()
        session.rollback.side_effect = SQLAlchemyError("fail")
        with pytest.raises(TransactionRollbackError):
            await safe_rollback(session)

    async def test_rollback_error_cause_stored(self) -> None:
        session = AsyncMock()
        original = SQLAlchemyError("rollback fail")
        session.rollback.side_effect = original
        with pytest.raises(TransactionRollbackError) as exc_info:
            await safe_rollback(session)
        assert exc_info.value.cause is original

    async def test_suppress_true_logs_warning(self) -> None:
        session = AsyncMock()
        session.rollback.side_effect = SQLAlchemyError("rollback failed")
        with patch("database.transactions.logger") as mock_logger:
            await safe_rollback(session, suppress_errors=True)
        mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# safe_flush
# ---------------------------------------------------------------------------

class TestSafeFlush:
    async def test_success_calls_flush(self) -> None:
        session = AsyncMock()
        await safe_flush(session)
        session.flush.assert_awaited_once()

    async def test_success_no_exception(self) -> None:
        session = AsyncMock()
        await safe_flush(session)

    async def test_sqlalchemy_error_raises_transaction_error(self) -> None:
        session = AsyncMock()
        session.flush.side_effect = SQLAlchemyError("flush error")
        with pytest.raises(TransactionError):
            await safe_flush(session)

    async def test_sqlalchemy_error_cause_stored(self) -> None:
        session = AsyncMock()
        original = SQLAlchemyError("flush error")
        session.flush.side_effect = original
        with pytest.raises(TransactionError) as exc_info:
            await safe_flush(session)
        assert exc_info.value.cause is original

    async def test_timeout_error_raises_database_timeout_error(self) -> None:
        session = AsyncMock()
        session.flush.side_effect = SATimeoutError("timeout")
        with pytest.raises(DatabaseTimeoutError):
            await safe_flush(session)

    async def test_timeout_error_cause_stored(self) -> None:
        session = AsyncMock()
        original = SATimeoutError("timeout")
        session.flush.side_effect = original
        with pytest.raises(DatabaseTimeoutError) as exc_info:
            await safe_flush(session)
        assert exc_info.value.cause is original

    async def test_custom_operation_in_details(self) -> None:
        session = AsyncMock()
        session.flush.side_effect = SQLAlchemyError("fail")
        with pytest.raises(TransactionError) as exc_info:
            await safe_flush(session, operation="my_flush_op")
        assert "my_flush_op" in str(exc_info.value.details)


# ---------------------------------------------------------------------------
# safe_refresh
# ---------------------------------------------------------------------------

class TestSafeRefresh:
    async def test_success_calls_refresh(self) -> None:
        session = AsyncMock()
        instance = MagicMock()
        await safe_refresh(session, instance)
        session.refresh.assert_awaited_once_with(instance, attribute_names=None)

    async def test_success_returns_same_instance(self) -> None:
        session = AsyncMock()
        instance = MagicMock()
        result = await safe_refresh(session, instance)
        assert result is instance

    async def test_sqlalchemy_error_raises_transaction_error(self) -> None:
        session = AsyncMock()
        session.refresh.side_effect = SQLAlchemyError("refresh error")
        with pytest.raises(TransactionError):
            await safe_refresh(session, MagicMock())

    async def test_sqlalchemy_error_cause_stored(self) -> None:
        session = AsyncMock()
        original = SQLAlchemyError("refresh error")
        session.refresh.side_effect = original
        with pytest.raises(TransactionError) as exc_info:
            await safe_refresh(session, MagicMock())
        assert exc_info.value.cause is original

    async def test_timeout_error_raises_database_timeout_error(self) -> None:
        session = AsyncMock()
        session.refresh.side_effect = SATimeoutError("timeout")
        with pytest.raises(DatabaseTimeoutError):
            await safe_refresh(session, MagicMock())

    async def test_timeout_error_cause_stored(self) -> None:
        session = AsyncMock()
        original = SATimeoutError("timeout")
        session.refresh.side_effect = original
        with pytest.raises(DatabaseTimeoutError) as exc_info:
            await safe_refresh(session, MagicMock())
        assert exc_info.value.cause is original

    async def test_with_attribute_names_passes_to_session(self) -> None:
        session = AsyncMock()
        instance = MagicMock()
        attrs = ["email", "username"]
        await safe_refresh(session, instance, attribute_names=attrs)
        session.refresh.assert_awaited_once_with(instance, attribute_names=attrs)

    async def test_attribute_names_none_by_default(self) -> None:
        session = AsyncMock()
        instance = MagicMock()
        await safe_refresh(session, instance)
        _, kwargs = session.refresh.call_args
        assert kwargs["attribute_names"] is None


# ---------------------------------------------------------------------------
# ensure_transaction_closed
# ---------------------------------------------------------------------------

class TestEnsureTransactionClosed:
    def _make_session(self, *, in_transaction: bool) -> AsyncMock:
        """Создать AsyncMock-сессию, где in_transaction() синхронный."""
        session = AsyncMock()
        # in_transaction() — синхронный метод AsyncSession
        session.in_transaction = MagicMock(return_value=in_transaction)
        return session

    async def test_not_in_transaction_no_rollback(self) -> None:
        session = self._make_session(in_transaction=False)
        await ensure_transaction_closed(session)
        session.rollback.assert_not_awaited()

    async def test_in_transaction_calls_safe_rollback(self) -> None:
        session = self._make_session(in_transaction=True)
        await ensure_transaction_closed(session)
        session.rollback.assert_awaited_once()

    async def test_not_in_transaction_returns_early(self) -> None:
        session = self._make_session(in_transaction=False)
        # Не должно выбрасывать исключений
        await ensure_transaction_closed(session)

    async def test_in_transaction_with_rollback_error_propagates(self) -> None:
        session = self._make_session(in_transaction=True)
        session.rollback.side_effect = SQLAlchemyError("rb fail")
        with pytest.raises(TransactionRollbackError):
            await ensure_transaction_closed(session)
