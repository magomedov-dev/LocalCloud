from __future__ import annotations

from importlib import import_module
from typing import cast

from database.models.enums import BackgroundTaskType
from workers.exceptions import WorkerTaskDispatchError
from workers.types import WorkerTaskHandler


class WorkerTaskRegistry:
    """Реестр обработчиков фоновых задач.

    Хранит соответствие между значениями `BackgroundTaskType` и вызываемыми
    обработчиками worker-задач. Позволяет регистрировать обработчики,
    получать их по типу задачи и проверять поддерживаемые типы задач.

    Attributes:
        _handlers: Словарь обработчиков, сгруппированных по типам фоновых
            задач.
    """

    def __init__(self) -> None:
        """Инициализирует пустой реестр обработчиков задач."""

        self._handlers: dict[BackgroundTaskType, WorkerTaskHandler] = {}

    def register(
        self,
        task_type: BackgroundTaskType,
        handler: WorkerTaskHandler,
        *,
        replace: bool = False,
    ) -> None:
        """Регистрирует обработчик для указанного типа фоновой задачи.

        Args:
            task_type: Тип фоновой задачи, для которого регистрируется
                обработчик.
            handler: Обработчик, который будет вызван для задач указанного
                типа.
            replace: Если `True`, разрешает заменить уже зарегистрированный
                обработчик для этого типа задачи.

        Raises:
            WorkerTaskDispatchError: Если обработчик для `task_type` уже
                зарегистрирован, а `replace` равен `False`.
        """

        if not replace and task_type in self._handlers:
            raise WorkerTaskDispatchError(
                "Обработчик для данного типа задачи уже зарегистрирован.",
                task_type=task_type.value,
                operation="register",
                details={"replace": replace},
            )
        self._handlers[task_type] = handler

    def get_handler(self, task_type: BackgroundTaskType) -> WorkerTaskHandler:
        """Возвращает зарегистрированный обработчик для типа фоновой задачи.

        Args:
            task_type: Тип фоновой задачи, для которого нужно получить
                обработчик.

        Returns:
            Обработчик, зарегистрированный для указанного типа задачи.

        Raises:
            WorkerTaskDispatchError: Если для `task_type` не найден
                зарегистрированный обработчик.
        """

        handler = self._handlers.get(task_type)
        if handler is None:
            raise WorkerTaskDispatchError(
                "Для типа фоновой задачи не найден обработчик.",
                task_type=task_type.value,
                operation="get_handler",
            )
        return handler

    def has_handler(self, task_type: BackgroundTaskType) -> bool:
        """Проверяет, зарегистрирован ли обработчик для типа задачи.

        Args:
            task_type: Тип фоновой задачи для проверки.

        Returns:
            `True`, если обработчик для указанного типа задачи зарегистрирован,
            иначе `False`.
        """

        return task_type in self._handlers


def _load_handler(module_name: str, attr_name: str) -> WorkerTaskHandler:
    """Загружает обработчик фоновой задачи из Python-модуля.

    Импортирует модуль по имени, получает из него указанный атрибут и проверяет,
    что найденный объект можно вызвать как обработчик worker-задачи.

    Args:
        module_name: Полное имя Python-модуля, из которого нужно загрузить
            обработчик.
        attr_name: Имя атрибута внутри модуля, содержащего обработчик.

    Returns:
        Загруженный обработчик фоновой задачи.

    Raises:
        WorkerTaskDispatchError: Если модуль не удалось импортировать, если в
            модуле отсутствует атрибут `attr_name` или если найденный атрибут
            не является вызываемым объектом.
    """

    try:
        module = import_module(module_name)
    except Exception as exc:
        raise WorkerTaskDispatchError(
            "Не удалось импортировать модуль обработчика задачи.",
            task_type=None,
            operation="build_default_registry",
            details={"module": module_name, "handler": attr_name},
            cause=exc,
        ) from exc

    try:
        handler = getattr(module, attr_name)
    except AttributeError as exc:
        raise WorkerTaskDispatchError(
            "В модуле не найден указанный обработчик задачи.",
            task_type=None,
            operation="build_default_registry",
            details={"module": module_name, "handler": attr_name},
            cause=exc,
        ) from exc

    if not callable(handler):
        raise WorkerTaskDispatchError(
            "Указанный обработчик задачи не является вызываемым объектом.",
            task_type=None,
            operation="build_default_registry",
            details={
                "module": module_name,
                "handler": attr_name,
                "handler_type": type(handler).__name__,
            },
        )

    return cast(WorkerTaskHandler, handler)


def build_default_registry() -> WorkerTaskRegistry:
    """Создаёт реестр обработчиков фоновых задач по умолчанию.

    Загружает обработчики из worker-модулей и регистрирует их для известных
    значений `BackgroundTaskType`.

    Returns:
        Реестр с обработчиками фоновых задач по умолчанию.

    Raises:
        WorkerTaskDispatchError: Если один из обработчиков не удалось
            импортировать, найти в модуле, привести к вызываемому объекту или
            зарегистрировать в реестре.
    """

    registry = WorkerTaskRegistry()

    create_folder_archive_handler = _load_handler(
        "workers.archives",
        "create_folder_archive_handler",
    )
    clean_trash_handler = _load_handler("workers.cleanup", "clean_trash_handler")
    clean_expired_uploads_handler = _load_handler(
        "workers.uploads",
        "clean_expired_uploads_handler",
    )
    clean_expired_public_links_handler = _load_handler(
        "workers.public_links",
        "clean_expired_public_links_handler",
    )
    delete_object_from_storage_handler = _load_handler(
        "workers.cleanup",
        "delete_object_from_storage_handler",
    )
    check_storage_integrity_handler = _load_handler(
        "workers.integrity",
        "check_storage_integrity_handler",
    )
    generate_file_preview_handler = _load_handler(
        "workers.previews",
        "generate_file_preview_handler",
    )
    recalculate_user_quota_handler = _load_handler(
        "workers.quotas",
        "recalculate_user_quota_handler",
    )

    registry.register(
        BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
        create_folder_archive_handler,
    )
    registry.register(BackgroundTaskType.CLEAN_TRASH, clean_trash_handler)
    registry.register(
        BackgroundTaskType.CLEAN_EXPIRED_UPLOADS,
        clean_expired_uploads_handler,
    )
    registry.register(
        BackgroundTaskType.CLEAN_EXPIRED_PUBLIC_LINKS,
        clean_expired_public_links_handler,
    )
    registry.register(
        BackgroundTaskType.DELETE_OBJECT_FROM_STORAGE,
        delete_object_from_storage_handler,
    )
    registry.register(
        BackgroundTaskType.CHECK_STORAGE_INTEGRITY,
        check_storage_integrity_handler,
    )
    registry.register(
        BackgroundTaskType.GENERATE_FILE_PREVIEW,
        generate_file_preview_handler,
    )
    registry.register(
        BackgroundTaskType.RECALCULATE_USER_QUOTA,
        recalculate_user_quota_handler,
    )

    return registry
