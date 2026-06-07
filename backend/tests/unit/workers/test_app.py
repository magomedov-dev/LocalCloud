"""Unit-тесты для workers.app — entrypoint/bootstrap worker-процесса."""
from __future__ import annotations

import argparse
import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import workers.app as app
from workers.app import (
    WorkerCliArgs,
    _build_arg_parser,
    _install_signal_handlers,
    _parse_args,
    main,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_context(scheduler_enabled: bool = True, poll_interval: float = 1.0):
    ctx = MagicMock()
    ctx.worker_id = "w-001"
    ctx.worker_settings = MagicMock()
    ctx.worker_settings.worker_scheduler_enabled = scheduler_enabled
    ctx.worker_settings.worker_poll_interval_seconds = poll_interval
    return ctx


def make_dispatcher_stats():
    stats = MagicMock()
    stats.fetched_count = 1
    stats.started_count = 1
    stats.completed_count = 1
    stats.failed_count = 0
    stats.retried_count = 0
    stats.skipped_count = 0
    return stats


def make_cli_args(
    *,
    once: bool = True,
    scheduler_only: bool = False,
    no_scheduler: bool = False,
    worker_id: str | None = None,
    poll_interval: float | None = None,
) -> WorkerCliArgs:
    return WorkerCliArgs(
        once=once,
        scheduler_only=scheduler_only,
        no_scheduler=no_scheduler,
        worker_id=worker_id,
        poll_interval=poll_interval,
    )


# ---------------------------------------------------------------------------
# _build_arg_parser / _parse_args
# ---------------------------------------------------------------------------

class TestArgParsing:
    def test_build_arg_parser_returns_parser(self) -> None:
        parser = _build_arg_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parse_args_defaults(self) -> None:
        with patch("sys.argv", ["prog"]):
            args = _parse_args()
        assert isinstance(args, WorkerCliArgs)
        assert args.once is False
        assert args.scheduler_only is False
        assert args.no_scheduler is False
        assert args.worker_id is None
        assert args.poll_interval is None

    def test_parse_args_all_flags(self) -> None:
        argv = [
            "prog",
            "--once",
            "--scheduler-only",
            "--worker-id",
            "custom-w",
            "--poll-interval",
            "2.5",
        ]
        with patch("sys.argv", argv):
            args = _parse_args()
        assert args.once is True
        assert args.scheduler_only is True
        assert args.no_scheduler is False
        assert args.worker_id == "custom-w"
        assert args.poll_interval == 2.5

    def test_parse_args_no_scheduler(self) -> None:
        with patch("sys.argv", ["prog", "--no-scheduler"]):
            args = _parse_args()
        assert args.no_scheduler is True

    def test_parse_args_mutually_exclusive_flags_exit(self) -> None:
        with patch("sys.argv", ["prog", "--scheduler-only", "--no-scheduler"]):
            with pytest.raises(SystemExit):
                _parse_args()

    def test_parse_args_non_positive_poll_interval_exit(self) -> None:
        with patch("sys.argv", ["prog", "--poll-interval", "0"]):
            with pytest.raises(SystemExit):
                _parse_args()

    def test_parse_args_negative_poll_interval_exit(self) -> None:
        with patch("sys.argv", ["prog", "--poll-interval", "-1"]):
            with pytest.raises(SystemExit):
                _parse_args()


# ---------------------------------------------------------------------------
# _install_signal_handlers
# ---------------------------------------------------------------------------

class TestInstallSignalHandlers:
    @pytest.mark.asyncio
    async def test_registers_handlers_via_loop(self) -> None:
        loop = MagicMock()
        stop_event = asyncio.Event()
        with patch("workers.app.asyncio.get_running_loop", return_value=loop):
            _install_signal_handlers(stop_event)

        registered_sigs = {c.args[0] for c in loop.add_signal_handler.call_args_list}
        assert registered_sigs == {signal.SIGINT, signal.SIGTERM}

    @pytest.mark.asyncio
    async def test_handler_sets_stop_event(self) -> None:
        loop = MagicMock()
        stop_event = asyncio.Event()
        with patch("workers.app.asyncio.get_running_loop", return_value=loop):
            _install_signal_handlers(stop_event)

        # Извлекаем зарегистрированный колбэк и вызываем его.
        first_call = loop.add_signal_handler.call_args_list[0]
        callback = first_call.args[1]
        signame = first_call.args[2]
        assert not stop_event.is_set()
        callback(signame)
        assert stop_event.is_set()

    @pytest.mark.asyncio
    async def test_handler_idempotent_when_already_set(self) -> None:
        loop = MagicMock()
        stop_event = asyncio.Event()
        stop_event.set()
        with (
            patch("workers.app.asyncio.get_running_loop", return_value=loop),
            patch.object(app.logger, "info") as mock_info,
        ):
            _install_signal_handlers(stop_event)
            callback = loop.add_signal_handler.call_args_list[0].args[1]
            signame = loop.add_signal_handler.call_args_list[0].args[2]
            callback(signame)
        # Флаг уже установлен: запрос остановки не пишет info-лог.
        mock_info.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_signal_signal_when_not_implemented(self) -> None:
        loop = MagicMock()
        loop.add_signal_handler.side_effect = NotImplementedError
        stop_event = asyncio.Event()
        with (
            patch("workers.app.asyncio.get_running_loop", return_value=loop),
            patch("workers.app.signal.signal") as mock_signal,
        ):
            _install_signal_handlers(stop_event)

        registered_sigs = {c.args[0] for c in mock_signal.call_args_list}
        assert registered_sigs == {signal.SIGINT, signal.SIGTERM}

    @pytest.mark.asyncio
    async def test_fallback_handler_sets_stop_event(self) -> None:
        loop = MagicMock()
        loop.add_signal_handler.side_effect = RuntimeError
        stop_event = asyncio.Event()
        with (
            patch("workers.app.asyncio.get_running_loop", return_value=loop),
            patch("workers.app.signal.signal") as mock_signal,
        ):
            _install_signal_handlers(stop_event)

        # signal.signal(sig, handler) — вызываем запасной обработчик.
        handler = mock_signal.call_args_list[0].args[1]
        handler(signal.SIGINT, None)
        assert stop_event.is_set()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

class TestMain:
    @pytest.mark.asyncio
    async def test_once_runs_scheduler_and_dispatcher_then_shutdown(self) -> None:
        context = make_context(scheduler_enabled=True)
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=3)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())

        order: list[str] = []
        startup = AsyncMock(side_effect=lambda **_: order.append("startup") or context)
        shutdown = AsyncMock(side_effect=lambda _c: order.append("shutdown"))

        with (
            patch("workers.app._parse_args", return_value=make_cli_args(once=True)),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", startup),
            patch("workers.app.shutdown_worker", shutdown),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
        ):
            await main()

        startup.assert_awaited_once_with(worker_id=None)
        scheduler.run_due_schedules.assert_awaited_once()
        dispatcher.run_once.assert_awaited_once()
        shutdown.assert_awaited_once_with(context)
        assert order == ["startup", "shutdown"]

    @pytest.mark.asyncio
    async def test_wires_collaborators_with_context_and_registry(self) -> None:
        context = make_context()
        registry = MagicMock()
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=0)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())

        with (
            patch("workers.app._parse_args", return_value=make_cli_args(once=True)),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", AsyncMock(return_value=context)),
            patch("workers.app.shutdown_worker", AsyncMock()),
            patch("workers.app.build_default_registry", return_value=registry),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher) as mock_disp_cls,
            patch("workers.app.WorkerScheduler", return_value=scheduler) as mock_sched_cls,
        ):
            await main()

        mock_disp_cls.assert_called_once_with(context=context, registry=registry)
        mock_sched_cls.assert_called_once_with(context=context)

    @pytest.mark.asyncio
    async def test_passes_explicit_worker_id(self) -> None:
        context = make_context()
        startup = AsyncMock(return_value=context)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=0)

        with (
            patch(
                "workers.app._parse_args",
                return_value=make_cli_args(once=True, worker_id="explicit-w"),
            ),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", startup),
            patch("workers.app.shutdown_worker", AsyncMock()),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
        ):
            await main()

        startup.assert_awaited_once_with(worker_id="explicit-w")

    @pytest.mark.asyncio
    async def test_scheduler_only_skips_dispatcher(self) -> None:
        context = make_context(scheduler_enabled=True)
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=0)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())

        with (
            patch(
                "workers.app._parse_args",
                return_value=make_cli_args(once=True, scheduler_only=True),
            ),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", AsyncMock(return_value=context)),
            patch("workers.app.shutdown_worker", AsyncMock()),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
        ):
            await main()

        scheduler.run_due_schedules.assert_awaited_once()
        dispatcher.run_once.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_scheduler_skips_scheduler(self) -> None:
        context = make_context(scheduler_enabled=True)
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=0)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())

        with (
            patch(
                "workers.app._parse_args",
                return_value=make_cli_args(once=True, no_scheduler=True),
            ),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", AsyncMock(return_value=context)),
            patch("workers.app.shutdown_worker", AsyncMock()),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
        ):
            await main()

        scheduler.run_due_schedules.assert_not_called()
        dispatcher.run_once.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scheduler_disabled_in_settings_skips_scheduler(self) -> None:
        context = make_context(scheduler_enabled=False)
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=0)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())

        with (
            patch("workers.app._parse_args", return_value=make_cli_args(once=True)),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", AsyncMock(return_value=context)),
            patch("workers.app.shutdown_worker", AsyncMock()),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
        ):
            await main()

        scheduler.run_due_schedules.assert_not_called()

    @pytest.mark.asyncio
    async def test_scheduler_exception_is_caught(self) -> None:
        context = make_context(scheduler_enabled=True)
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(side_effect=RuntimeError("boom"))
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())
        shutdown = AsyncMock()

        with (
            patch("workers.app._parse_args", return_value=make_cli_args(once=True)),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", AsyncMock(return_value=context)),
            patch("workers.app.shutdown_worker", shutdown),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
        ):
            await main()  # не должно выбрасывать исключение

        # Диспетчер всё равно запускается, несмотря на сбой планировщика; shutdown происходит.
        dispatcher.run_once.assert_awaited_once()
        shutdown.assert_awaited_once_with(context)

    @pytest.mark.asyncio
    async def test_dispatcher_exception_is_caught(self) -> None:
        context = make_context(scheduler_enabled=True)
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=0)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(side_effect=RuntimeError("dispatch boom"))
        shutdown = AsyncMock()

        with (
            patch("workers.app._parse_args", return_value=make_cli_args(once=True)),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", AsyncMock(return_value=context)),
            patch("workers.app.shutdown_worker", shutdown),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
        ):
            await main()  # не должно выбрасывать исключение

        shutdown.assert_awaited_once_with(context)

    @pytest.mark.asyncio
    async def test_explicit_poll_interval_overrides_settings(self) -> None:
        context = make_context(scheduler_enabled=False, poll_interval=99.0)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=0)

        wait_for = AsyncMock()

        with (
            patch(
                "workers.app._parse_args",
                return_value=make_cli_args(once=False, poll_interval=0.01),
            ),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", AsyncMock(return_value=context)),
            patch("workers.app.shutdown_worker", AsyncMock()),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
            patch("workers.app.asyncio.wait_for", wait_for) as mock_wait,
        ):
            # Первый wait_for завершает цикл, выбрасывая остановку после одной итерации:
            # имитируем остановку, прерывая цикл.
            async def stop_loop(coro, *_a, **_kw):
                # Закрываем неожиданную корутину stop_event.wait().
                coro.close()
                # Имитируем запрос остановки после первого цикла.
                raise _StopLoop()

            mock_wait.side_effect = stop_loop
            with pytest.raises(_StopLoop):
                await main()

        # Цикл не --once, поэтому wait_for вызывается с переопределённым интервалом.
        assert mock_wait.call_args.kwargs["timeout"] == 0.01

    @pytest.mark.asyncio
    async def test_polling_loop_continues_on_timeout_then_stops(self) -> None:
        context = make_context(scheduler_enabled=False)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=0)

        call_count = {"n": 0}

        async def wait_for(coro, timeout):  # noqa: ARG001
            # Закрываем неожиданную корутину stop_event.wait().
            coro.close()
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TimeoutError
            # Вторая итерация: сигнализируем остановку через sentinel-исключение.
            raise _StopLoop()

        with (
            patch(
                "workers.app._parse_args",
                return_value=make_cli_args(once=False, poll_interval=0.01),
            ),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", AsyncMock(return_value=context)),
            patch("workers.app.shutdown_worker", AsyncMock()),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
            patch("workers.app.asyncio.wait_for", wait_for),
        ):
            with pytest.raises(_StopLoop):
                await main()

        # Прошло две итерации: диспетчер выполнен дважды (таймаут -> continue).
        assert dispatcher.run_once.await_count == 2

    @pytest.mark.asyncio
    async def test_startup_failure_still_calls_shutdown_with_none(self) -> None:
        startup = AsyncMock(side_effect=RuntimeError("startup failed"))
        shutdown = AsyncMock()

        with (
            patch("workers.app._parse_args", return_value=make_cli_args(once=True)),
            patch("workers.app._install_signal_handlers"),
            patch("workers.app.startup_worker", startup),
            patch("workers.app.shutdown_worker", shutdown),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=MagicMock()),
            patch("workers.app.WorkerScheduler", return_value=MagicMock()),
        ):
            with pytest.raises(RuntimeError, match="startup failed"):
                await main()

        # При сбое startup context равен None; shutdown всё равно вызывается с None.
        shutdown.assert_awaited_once_with(None)

    @pytest.mark.asyncio
    async def test_stop_event_already_set_skips_work_loop(self) -> None:
        context = make_context(scheduler_enabled=True)
        dispatcher = MagicMock()
        dispatcher.run_once = AsyncMock(return_value=make_dispatcher_stats())
        scheduler = MagicMock()
        scheduler.run_due_schedules = AsyncMock(return_value=0)
        shutdown = AsyncMock()

        def install(stop_event: asyncio.Event) -> None:
            stop_event.set()

        with (
            patch("workers.app._parse_args", return_value=make_cli_args(once=False)),
            patch("workers.app._install_signal_handlers", side_effect=install),
            patch("workers.app.startup_worker", AsyncMock(return_value=context)),
            patch("workers.app.shutdown_worker", shutdown),
            patch("workers.app.build_default_registry", return_value=MagicMock()),
            patch("workers.app.WorkerDispatcher", return_value=dispatcher),
            patch("workers.app.WorkerScheduler", return_value=scheduler),
        ):
            await main()

        # Тело цикла не выполняется, так как stop_event уже установлен.
        scheduler.run_due_schedules.assert_not_called()
        dispatcher.run_once.assert_not_called()
        shutdown.assert_awaited_once_with(context)


class _StopLoop(Exception):
    """Sentinel-исключение для выхода из цикла опроса в тестах."""
