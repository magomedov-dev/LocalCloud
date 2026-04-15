from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.dependencies import get_tasks_service_dependency
from database.models.enums import BackgroundTaskType
from schemas.common import PageResponse
from schemas.tasks import (
    BackgroundTaskCancelRequest,
    BackgroundTaskCreate,
    BackgroundTaskListItem,
    BackgroundTaskQueryParams,
    BackgroundTaskRead,
    BackgroundTaskRetryRequest,
    TaskResultRead,
)
from security import CurrentActiveUserDependency
from security.permissions import is_admin_user
from services import TasksService

# Маршрутизатор эндпоинтов для управления фоновыми задачами.
router = APIRouter(prefix="/tasks", tags=["tasks"])

# Типы фоновых задач, которые разрешено создавать обычным пользователям.
USER_CREATABLE_TASK_TYPES: frozenset[BackgroundTaskType] = frozenset(
    {
        BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
    }
)


@router.post(
    "/",
    response_model=BackgroundTaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    data: BackgroundTaskCreate,
    current_user: CurrentActiveUserDependency,
    tasks_service: TasksService = Depends(get_tasks_service_dependency),
) -> BackgroundTaskRead:
    """Создаёт фоновую задачу.

    Проверяет, имеет ли текущий пользователь право создать задачу указанного
    типа. Обычные пользователи могут создавать только типы задач из
    `USER_CREATABLE_TASK_TYPES`. Также запрещает создание задачи от имени
    другого пользователя и принудительно устанавливает `created_by` равным
    идентификатору текущего пользователя.

    Args:
        data: Данные для создания фоновой задачи.
        current_user: Текущий активный пользователь, создающий задачу.
        tasks_service: Сервис фоновых задач, выполняющий создание задачи.

    Returns:
        Данные созданной фоновой задачи.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            пытается создать запрещённый тип задачи, создать задачу от имени
            другого пользователя или передал некорректные параметры задачи.
    """

    user_is_admin = bool(is_admin_user(cast(Any, current_user)))
    if (not user_is_admin) and data.task_type not in USER_CREATABLE_TASK_TYPES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для создания этого типа задачи.",
        )

    if data.created_by not in (None, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя создать задачу от имени другого пользователя.",
        )

    request_data = data.model_copy(update={"created_by": current_user.id})
    return await tasks_service.create_task(request_data, actor_id=current_user.id)


@router.get(
    "/",
    response_model=PageResponse[BackgroundTaskListItem],
    status_code=status.HTTP_200_OK,
)
async def list_tasks(
    current_user: CurrentActiveUserDependency,
    params: BackgroundTaskQueryParams = Depends(),
    tasks_service: TasksService = Depends(get_tasks_service_dependency),
) -> PageResponse[BackgroundTaskListItem]:
    """Возвращает список фоновых задач.

    Получает страницу фоновых задач с учётом параметров фильтрации, сортировки
    и пагинации. Результат формируется в контексте текущего пользователя
    и его прав доступа.

    Args:
        current_user: Текущий активный пользователь, запрашивающий список задач.
        params: Параметры запроса для фильтрации, сортировки и пагинации задач.
        tasks_service: Сервис фоновых задач, выполняющий получение списка.

    Returns:
        Страница фоновых задач с метаданными пагинации.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры запроса некорректны или доступ запрещён.
    """

    return await tasks_service.list_tasks(params, actor_id=current_user.id)


@router.get(
    "/{task_id}",
    response_model=BackgroundTaskRead,
    status_code=status.HTTP_200_OK,
)
async def get_task(
    current_user: CurrentActiveUserDependency,
    task_id: UUID = Path(...),
    tasks_service: TasksService = Depends(get_tasks_service_dependency),
) -> BackgroundTaskRead:
    """Возвращает фоновую задачу по идентификатору.

    Получает подробные данные фоновой задачи, если текущий пользователь имеет
    право просматривать эту задачу.

    Args:
        current_user: Текущий активный пользователь, запрашивающий задачу.
        task_id: Уникальный идентификатор фоновой задачи.
        tasks_service: Сервис фоновых задач, выполняющий получение задачи.

    Returns:
        Подробные данные фоновой задачи.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, задача не найдена
            или доступ к ней запрещён.
    """

    return await tasks_service.get_task(task_id, actor_id=current_user.id)


@router.get(
    "/{task_id}/result",
    response_model=TaskResultRead,
    status_code=status.HTTP_200_OK,
)
async def get_task_result(
    current_user: CurrentActiveUserDependency,
    task_id: UUID = Path(...),
    tasks_service: TasksService = Depends(get_tasks_service_dependency),
) -> TaskResultRead:
    """Возвращает результат выполнения фоновой задачи.

    Получает сохранённый результат выполнения задачи, если он доступен
    и текущий пользователь имеет право просматривать эту задачу.

    Args:
        current_user: Текущий активный пользователь, запрашивающий результат.
        task_id: Уникальный идентификатор фоновой задачи.
        tasks_service: Сервис фоновых задач, выполняющий получение результата.

    Returns:
        Результат выполнения фоновой задачи.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, задача не найдена,
            результат ещё недоступен или доступ запрещён.
    """

    return await tasks_service.get_task_result(task_id, actor_id=current_user.id)


@router.get(
    "/{task_id}/progress",
    response_model=TaskResultRead,
    status_code=status.HTTP_200_OK,
)
async def get_task_progress(
    current_user: CurrentActiveUserDependency,
    task_id: UUID = Path(...),
    tasks_service: TasksService = Depends(get_tasks_service_dependency),
) -> TaskResultRead:
    """Возвращает текущий прогресс фоновой задачи.

    Получает данные результата задачи, которые могут включать текущий прогресс,
    статус выполнения и промежуточные сведения. Использует тот же сервисный
    метод, что и получение результата задачи.

    Args:
        current_user: Текущий активный пользователь, запрашивающий прогресс.
        task_id: Уникальный идентификатор фоновой задачи.
        tasks_service: Сервис фоновых задач, выполняющий получение прогресса.

    Returns:
        Текущий прогресс или результат выполнения фоновой задачи.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, задача не найдена
            или доступ к прогрессу запрещён.
    """

    return await tasks_service.get_task_result(task_id, actor_id=current_user.id)


@router.post(
    "/{task_id}/cancel",
    response_model=BackgroundTaskRead,
    status_code=status.HTTP_200_OK,
)
async def cancel_task(
    data: BackgroundTaskCancelRequest,
    current_user: CurrentActiveUserDependency,
    task_id: UUID = Path(...),
    tasks_service: TasksService = Depends(get_tasks_service_dependency),
) -> BackgroundTaskRead:
    """Отменяет фоновую задачу.

    Передаёт запрос на отмену фоновой задачи в сервисный слой. Операция
    выполняется от имени текущего пользователя и зависит от его прав доступа
    и текущего состояния задачи.

    Args:
        data: Данные для отмены фоновой задачи.
        current_user: Текущий активный пользователь, отменяющий задачу.
        task_id: Уникальный идентификатор отменяемой задачи.
        tasks_service: Сервис фоновых задач, выполняющий отмену задачи.

    Returns:
        Данные фоновой задачи после запроса на отмену.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, задача не найдена,
            доступ запрещён или задачу нельзя отменить в текущем состоянии.
    """

    return await tasks_service.cancel_task(task_id, data, actor_id=current_user.id)


@router.post(
    "/{task_id}/retry",
    response_model=BackgroundTaskRead,
    status_code=status.HTTP_200_OK,
)
async def retry_task(
    data: BackgroundTaskRetryRequest,
    current_user: CurrentActiveUserDependency,
    task_id: UUID = Path(...),
    tasks_service: TasksService = Depends(get_tasks_service_dependency),
) -> BackgroundTaskRead:
    """Повторно ставит фоновую задачу в очередь.

    Передаёт запрос на повторный запуск задачи в сервисный слой. Операция
    выполняется от имени текущего пользователя и обычно применима к задачам,
    завершившимся ошибкой или отменённым задачам, если это разрешено бизнес-
    логикой.

    Args:
        data: Данные для повторной постановки задачи в очередь.
        current_user: Текущий активный пользователь, повторно запускающий
            задачу.
        task_id: Уникальный идентификатор задачи.
        tasks_service: Сервис фоновых задач, выполняющий повторный запуск.

    Returns:
        Данные фоновой задачи после повторной постановки в очередь.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, задача не найдена,
            доступ запрещён или задачу нельзя повторно поставить в очередь
            в текущем состоянии.
    """

    return await tasks_service.retry_task(task_id, data, actor_id=current_user.id)
