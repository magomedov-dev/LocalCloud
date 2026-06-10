"""Юнит-тесты UnitOfWork и UnitOfWorkFactory (контекст, репозитории, commit/rollback)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from database.unit_of_work import UnitOfWork, UnitOfWorkFactory, create_unit_of_work_factory
from database.exceptions import UnitOfWorkError


def make_mock_session() -> AsyncMock:
    session = AsyncMock()
    # in_transaction() — синхронный метод AsyncSession
    session.in_transaction = MagicMock(return_value=False)
    return session


def make_mock_factory(session: AsyncMock | None = None) -> MagicMock:
    if session is None:
        session = make_mock_session()
    factory = MagicMock(return_value=session)
    return factory


# ---------------------------------------------------------------------------
# __aenter__ / __aexit__
# ---------------------------------------------------------------------------

class TestUnitOfWorkContextManager:
    async def test_aenter_returns_uow(self) -> None:
        session = make_mock_session()
        factory = make_mock_factory(session)
        uow = UnitOfWork(session_factory=factory)
        async with uow as ctx:
            assert ctx is uow

    async def test_aenter_creates_session_from_factory(self) -> None:
        session = make_mock_session()
        factory = make_mock_factory(session)
        uow = UnitOfWork(session_factory=factory)
        async with uow:
            pass
        factory.assert_called_once()

    async def test_aenter_uses_external_session(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session)
        async with uow as ctx:
            assert ctx.session is session

    async def test_aexit_no_exception_does_not_commit_by_default(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            pass
        session.commit.assert_not_awaited()

    async def test_aexit_commit_on_exit_true_commits(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, commit_on_exit=True, close_session_on_exit=False)
        async with uow:
            pass
        session.commit.assert_awaited_once()

    async def test_aexit_exception_triggers_rollback(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("test error")
        session.rollback.assert_awaited()

    async def test_aexit_exception_does_not_commit(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("test error")
        session.commit.assert_not_awaited()

    async def test_aexit_returns_false_does_not_suppress_exception(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        with pytest.raises(RuntimeError, match="do not suppress"):
            async with uow:
                raise RuntimeError("do not suppress")

    async def test_aexit_rollback_on_exit_without_commit_true(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(
            session=session,
            rollback_on_exit_without_commit=True,
            close_session_on_exit=False,
        )
        async with uow:
            pass
        session.rollback.assert_awaited()

    async def test_aexit_rollback_on_exit_without_commit_false_no_rollback(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(
            session=session,
            rollback_on_exit_without_commit=False,
            close_session_on_exit=False,
        )
        async with uow:
            pass
        session.rollback.assert_not_awaited()

    async def test_already_in_context_raises(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            with pytest.raises(UnitOfWorkError):
                await uow.__aenter__()

    async def test_session_factory_called_when_no_external_session(self) -> None:
        session = make_mock_session()
        factory = make_mock_factory(session)
        with patch("database.unit_of_work.get_async_session_factory", return_value=factory):
            uow = UnitOfWork()
            async with uow:
                pass
        factory.assert_called_once()


# ---------------------------------------------------------------------------
# Repository properties
# ---------------------------------------------------------------------------

class TestUnitOfWorkRepositories:
    async def test_users_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            repo = uow.users
            assert repo is not None

    async def test_registration_requests_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.registration_requests is not None

    async def test_refresh_tokens_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.refresh_tokens is not None

    async def test_nodes_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.nodes is not None

    async def test_files_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.files is not None

    async def test_folders_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.folders is not None

    async def test_versions_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.versions is not None

    async def test_trash_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.trash is not None

    async def test_permissions_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.permissions is not None

    async def test_links_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.links is not None

    async def test_upload_sessions_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.upload_sessions is not None

    async def test_upload_parts_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.upload_parts is not None

    async def test_quotas_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.quotas is not None

    async def test_audit_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.audit is not None

    async def test_tasks_repository_created(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            assert uow.tasks is not None

    async def test_repository_cached_on_second_access(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            repo1 = uow.users
            repo2 = uow.users
            assert repo1 is repo2

    async def test_session_property_raises_when_closed(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        # Вручную помечаем как закрытый — имитирует состояние после выхода
        uow._closed = True
        with pytest.raises(UnitOfWorkError):
            _ = uow.session


# ---------------------------------------------------------------------------
# commit / rollback / flush
# ---------------------------------------------------------------------------

class TestUnitOfWorkOperations:
    async def test_commit_calls_session_commit(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            await uow.commit()
        session.commit.assert_awaited_once()

    async def test_commit_sets_committed_flag(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            await uow.commit()
            assert uow._committed is True

    async def test_rollback_calls_session_rollback(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            await uow.rollback()
        session.rollback.assert_awaited()

    async def test_rollback_sets_rolled_back_flag(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            await uow.rollback()
            assert uow._rolled_back is True

    async def test_flush_calls_session_flush(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            await uow.flush()
        session.flush.assert_awaited_once()

    async def test_commit_raises_when_not_entered(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session)
        with pytest.raises(UnitOfWorkError):
            await uow.commit()

    async def test_flush_raises_when_not_entered(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session)
        with pytest.raises(UnitOfWorkError):
            await uow.flush()

    async def test_rollback_noop_when_no_session(self) -> None:
        uow = UnitOfWork()
        # rollback без входа в контекст (нет сессии) не должен выбрасывать
        await uow.rollback()

    async def test_commit_after_commit_flag_skips_second_commit_on_exit(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(
            session=session,
            commit_on_exit=True,
            close_session_on_exit=False,
        )
        async with uow:
            await uow.commit()
        # Только один commit — ручной. commit_on_exit пропускается, т.к. _committed=True
        session.commit.assert_awaited_once()

    async def test_refresh_calls_safe_refresh(self) -> None:
        session = make_mock_session()
        entity = MagicMock()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            result = await uow.refresh(entity)
        session.refresh.assert_awaited_once_with(entity, attribute_names=None)
        assert result is entity

    async def test_flush_and_refresh_calls_both(self) -> None:
        session = make_mock_session()
        entity = MagicMock()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            result = await uow.flush_and_refresh(entity)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once()
        assert result is entity


# ---------------------------------------------------------------------------
# External session
# ---------------------------------------------------------------------------

class TestUnitOfWorkExternalSession:
    async def test_external_session_not_closed_by_default(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session)
        async with uow:
            pass
        session.close.assert_not_awaited()

    async def test_external_session_owns_session_false(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session)
        assert uow._owns_session is False

    async def test_external_session_not_none_after_exit(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session)
        async with uow:
            pass
        # Внешняя сессия должна сохраниться (не сбрасывается в None)
        assert uow._session is session


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------

class TestUnitOfWorkClose:
    async def test_close_idempotent(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=True)
        async with uow:
            pass
        # Повторный close не должен выбрасывать исключений
        await uow.close()

    async def test_close_resets_repositories(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            _ = uow.users
        assert uow._users is None

    async def test_close_owns_session_closes_it(self) -> None:
        session = make_mock_session()
        factory = make_mock_factory(session)
        uow = UnitOfWork(session_factory=factory)
        async with uow:
            pass
        session.close.assert_awaited_once()

    async def test_close_with_active_transaction_ensures_closed(self) -> None:
        session = make_mock_session()
        session.in_transaction = MagicMock(return_value=True)
        factory = make_mock_factory(session)
        uow = UnitOfWork(session_factory=factory)
        with patch(
            "database.unit_of_work.ensure_transaction_closed",
            new=AsyncMock(),
        ) as mock_ensure:
            async with uow:
                pass
        mock_ensure.assert_awaited_once()

    async def test_close_session_error_raises_unit_of_work_error(self) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        session = make_mock_session()
        session.close = AsyncMock(side_effect=SQLAlchemyError("close fail"))
        factory = make_mock_factory(session)
        uow = UnitOfWork(session_factory=factory)
        with pytest.raises(UnitOfWorkError):
            async with uow:
                pass


# ---------------------------------------------------------------------------
# Session property / _ensure_usable guards
# ---------------------------------------------------------------------------

class TestUnitOfWorkGuards:
    async def test_session_property_none_raises(self) -> None:
        uow = UnitOfWork(session_factory=make_mock_factory())
        with pytest.raises(UnitOfWorkError):
            _ = uow.session

    async def test_aenter_session_creation_failure_wrapped(self) -> None:
        factory = MagicMock(side_effect=RuntimeError("boom"))
        uow = UnitOfWork(session_factory=factory)
        with pytest.raises(UnitOfWorkError):
            await uow.__aenter__()

    async def test_commit_without_session_raises(self) -> None:
        uow = UnitOfWork(session_factory=make_mock_factory())
        with pytest.raises(UnitOfWorkError):
            await uow.commit()

    async def test_commit_after_close_raises(self) -> None:
        session = make_mock_session()
        uow = UnitOfWork(session=session, close_session_on_exit=False)
        async with uow:
            pass
        # Внешняя сессия сохраняется после close, поэтому _session не None,
        # но _closed=True -> срабатывает защита по закрытому состоянию.
        with pytest.raises(UnitOfWorkError):
            await uow.commit()


# ---------------------------------------------------------------------------
# UnitOfWorkFactory
# ---------------------------------------------------------------------------

class TestUnitOfWorkFactory:
    def test_factory_creates_uow_instance(self) -> None:
        factory = UnitOfWorkFactory()
        uow = factory()
        assert isinstance(uow, UnitOfWork)

    def test_factory_passes_commit_on_exit(self) -> None:
        factory = UnitOfWorkFactory(commit_on_exit=True)
        uow = factory()
        assert uow._commit_on_exit is True

    def test_factory_passes_rollback_on_exit_without_commit(self) -> None:
        factory = UnitOfWorkFactory(rollback_on_exit_without_commit=False)
        uow = factory()
        assert uow._rollback_on_exit_without_commit is False

    def test_factory_call_can_override_commit_on_exit(self) -> None:
        factory = UnitOfWorkFactory(commit_on_exit=False)
        uow = factory(commit_on_exit=True)
        assert uow._commit_on_exit is True

    def test_factory_call_can_override_rollback_on_exit(self) -> None:
        factory = UnitOfWorkFactory(rollback_on_exit_without_commit=True)
        uow = factory(rollback_on_exit_without_commit=False)
        assert uow._rollback_on_exit_without_commit is False

    def test_factory_with_external_session(self) -> None:
        session = make_mock_session()
        factory = UnitOfWorkFactory()
        uow = factory(session=session)
        assert uow._session is session

    def test_create_unit_of_work_factory_returns_factory(self) -> None:
        result = create_unit_of_work_factory()
        assert isinstance(result, UnitOfWorkFactory)

    def test_create_unit_of_work_factory_with_params(self) -> None:
        result = create_unit_of_work_factory(commit_on_exit=True)
        assert result.commit_on_exit is True
