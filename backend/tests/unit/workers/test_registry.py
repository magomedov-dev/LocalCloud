"""Тесты реестра обработчиков задач воркера и загрузки обработчиков."""

from __future__ import annotations


import pytest

from database.models.enums import BackgroundTaskType
from workers.exceptions import WorkerTaskDispatchError
from workers.registry import (
    WorkerTaskRegistry,
    _load_handler,
    build_default_registry,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


async def _dummy_handler_a(ctx):  # noqa: ANN001
    """Заглушка асинхронного обработчика для тестов."""
    ...


async def _dummy_handler_b(ctx):  # noqa: ANN001
    """Ещё одна заглушка асинхронного обработчика для тестов."""
    ...


# ---------------------------------------------------------------------------
# WorkerTaskRegistry.register
# ---------------------------------------------------------------------------


class TestWorkerTaskRegistryRegister:
    def test_registers_handler_for_task_type(self) -> None:
        registry = WorkerTaskRegistry()
        registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)
        assert registry.has_handler(BackgroundTaskType.CLEAN_TRASH)

    def test_replace_false_raises_on_duplicate(self) -> None:
        registry = WorkerTaskRegistry()
        registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)
        with pytest.raises(WorkerTaskDispatchError):
            registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_b)

    def test_replace_true_allows_overwrite(self) -> None:
        registry = WorkerTaskRegistry()
        registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)
        # Не должно выбрасывать исключение
        registry.register(
            BackgroundTaskType.CLEAN_TRASH, _dummy_handler_b, replace=True
        )
        assert registry.get_handler(BackgroundTaskType.CLEAN_TRASH) is _dummy_handler_b

    def test_replace_default_is_false(self) -> None:
        registry = WorkerTaskRegistry()
        registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)
        with pytest.raises(WorkerTaskDispatchError):
            # replace по умолчанию False
            registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)


# ---------------------------------------------------------------------------
# WorkerTaskRegistry.get_handler
# ---------------------------------------------------------------------------


class TestWorkerTaskRegistryGetHandler:
    def test_returns_registered_handler(self) -> None:
        registry = WorkerTaskRegistry()
        registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)
        handler = registry.get_handler(BackgroundTaskType.CLEAN_TRASH)
        assert handler is _dummy_handler_a

    def test_unknown_task_type_raises(self) -> None:
        registry = WorkerTaskRegistry()
        with pytest.raises(WorkerTaskDispatchError):
            registry.get_handler(BackgroundTaskType.CLEAN_TRASH)


# ---------------------------------------------------------------------------
# WorkerTaskRegistry.has_handler
# ---------------------------------------------------------------------------


class TestWorkerTaskRegistryHasHandler:
    def test_true_for_registered_type(self) -> None:
        registry = WorkerTaskRegistry()
        registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)
        assert registry.has_handler(BackgroundTaskType.CLEAN_TRASH) is True

    def test_false_for_unregistered_type(self) -> None:
        registry = WorkerTaskRegistry()
        assert registry.has_handler(BackgroundTaskType.CLEAN_TRASH) is False


# ---------------------------------------------------------------------------
# WorkerTaskRegistry multiple handlers
# ---------------------------------------------------------------------------


class TestWorkerTaskRegistryMultipleHandlers:
    def test_multiple_task_types_all_retrievable(self) -> None:
        registry = WorkerTaskRegistry()
        registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)
        registry.register(BackgroundTaskType.CLEAN_EXPIRED_UPLOADS, _dummy_handler_b)

        assert registry.get_handler(BackgroundTaskType.CLEAN_TRASH) is _dummy_handler_a
        assert (
            registry.get_handler(BackgroundTaskType.CLEAN_EXPIRED_UPLOADS)
            is _dummy_handler_b
        )

    def test_has_handler_true_for_all_registered(self) -> None:
        registry = WorkerTaskRegistry()
        registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)
        registry.register(BackgroundTaskType.CLEAN_EXPIRED_UPLOADS, _dummy_handler_b)

        assert registry.has_handler(BackgroundTaskType.CLEAN_TRASH) is True
        assert registry.has_handler(BackgroundTaskType.CLEAN_EXPIRED_UPLOADS) is True

    def test_has_handler_false_for_unregistered(self) -> None:
        registry = WorkerTaskRegistry()
        registry.register(BackgroundTaskType.CLEAN_TRASH, _dummy_handler_a)

        assert (
            registry.has_handler(BackgroundTaskType.CHECK_STORAGE_INTEGRITY) is False
        )


# ---------------------------------------------------------------------------
# _load_handler
# ---------------------------------------------------------------------------


class TestLoadHandler:
    def test_loads_callable_from_valid_module(self) -> None:
        # workers.tasks.success_result — известный вызываемый объект в проекте
        handler = _load_handler("workers.tasks", "success_result")
        assert callable(handler)

    def test_raises_for_nonexistent_module(self) -> None:
        with pytest.raises(WorkerTaskDispatchError):
            _load_handler("workers.nonexistent_module_xyz", "some_handler")

    def test_raises_for_nonexistent_attribute(self) -> None:
        with pytest.raises(WorkerTaskDispatchError):
            _load_handler("workers.tasks", "nonexistent_function_xyz")

    def test_raises_for_non_callable_attribute(self) -> None:
        # Используем константу модуля, которая не вызывается.
        # workers.tasks не экспортирует констант, поэтому берём модуль stdlib.
        # math.pi — это float (не вызывается).
        with pytest.raises(WorkerTaskDispatchError):
            _load_handler("math", "pi")

    def test_raises_with_dispatch_error_type(self) -> None:
        exc = None
        try:
            _load_handler("does_not_exist", "handler")
        except WorkerTaskDispatchError as e:
            exc = e
        assert exc is not None
        assert isinstance(exc, WorkerTaskDispatchError)

    def test_loaded_handler_is_the_expected_function(self) -> None:
        from workers.tasks import jsonable

        handler = _load_handler("workers.tasks", "jsonable")
        assert handler is jsonable


# ---------------------------------------------------------------------------
# build_default_registry
# ---------------------------------------------------------------------------


class TestBuildDefaultRegistry:
    def test_returns_registry_instance(self) -> None:
        registry = build_default_registry()
        assert isinstance(registry, WorkerTaskRegistry)

    def test_registers_all_known_task_types(self) -> None:
        registry = build_default_registry()
        expected = {
            BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
            BackgroundTaskType.CLEAN_TRASH,
            BackgroundTaskType.CLEAN_EXPIRED_UPLOADS,
            BackgroundTaskType.CLEAN_EXPIRED_PUBLIC_LINKS,
            BackgroundTaskType.DELETE_OBJECT_FROM_STORAGE,
            BackgroundTaskType.CHECK_STORAGE_INTEGRITY,
            BackgroundTaskType.GENERATE_FILE_PREVIEW,
            BackgroundTaskType.RECALCULATE_USER_QUOTA,
        }
        for task_type in expected:
            assert registry.has_handler(task_type), task_type

    def test_handlers_are_callable(self) -> None:
        registry = build_default_registry()
        for task_type in (
            BackgroundTaskType.CLEAN_TRASH,
            BackgroundTaskType.DELETE_OBJECT_FROM_STORAGE,
        ):
            assert callable(registry.get_handler(task_type))

    def test_clean_trash_handler_wired_correctly(self) -> None:
        from workers.cleanup import clean_trash_handler

        registry = build_default_registry()
        assert (
            registry.get_handler(BackgroundTaskType.CLEAN_TRASH)
            is clean_trash_handler
        )

    def test_fresh_registry_each_call(self) -> None:
        first = build_default_registry()
        second = build_default_registry()
        assert first is not second
