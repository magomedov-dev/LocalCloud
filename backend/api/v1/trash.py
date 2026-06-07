from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from api.dependencies import get_trash_service_dependency
from schemas.common import PageResponse
from schemas.trash import (
    TrashCleanupRequest,
    TrashEmptyRequest,
    TrashItemListItem,
    TrashPurgeRequest,
    TrashPurgeResponse,
    TrashQueryParams,
    TrashRestoreRequest,
    TrashRestoreResponse,
)
from security import CurrentActiveUserDependency, CurrentAdminUserDependency
from services import TrashService

# Маршрутизатор эндпоинтов для работы с корзиной.
router = APIRouter(prefix="/trash", tags=["trash"])


@router.get(
    "/",
    response_model=PageResponse[TrashItemListItem],
    status_code=status.HTTP_200_OK,
)
async def list_trash_items(
    current_user: CurrentActiveUserDependency,
    params: TrashQueryParams = Depends(),
    trash_service: TrashService = Depends(get_trash_service_dependency),
) -> PageResponse[TrashItemListItem]:
    """Возвращает список элементов корзины.

    Получает страницу элементов корзины с учётом параметров фильтрации,
    сортировки и пагинации. Результат формируется в контексте текущего
    пользователя и его прав доступа.

    Args:
        current_user: Текущий активный пользователь, запрашивающий элементы
            корзины.
        params: Параметры запроса для фильтрации, сортировки и пагинации
            элементов корзины.
        trash_service: Сервис корзины, выполняющий получение списка элементов.

    Returns:
        Страница элементов корзины с метаданными пагинации.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры запроса некорректны или доступ запрещён.
    """

    return await trash_service.list_trash(params, actor_id=current_user.id)


@router.post(
    "/{trash_item_id}/restore",
    response_model=TrashRestoreResponse,
    status_code=status.HTTP_200_OK,
)
async def restore_trash_item(
    data: TrashRestoreRequest,
    current_user: CurrentActiveUserDependency,
    trash_item_id: UUID = Path(...),
    trash_service: TrashService = Depends(get_trash_service_dependency),
) -> TrashRestoreResponse:
    """Восстанавливает элемент из корзины.

    Подставляет идентификатор элемента корзины из URL в данные запроса
    и передаёт восстановление в сервисный слой. Операция выполняется от имени
    текущего пользователя.

    Args:
        data: Параметры восстановления элемента из корзины.
        current_user: Текущий активный пользователь, выполняющий восстановление.
        trash_item_id: Уникальный идентификатор элемента корзины.
        trash_service: Сервис корзины, выполняющий восстановление элемента.

    Returns:
        Результат восстановления элемента из корзины.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, элемент корзины
            не найден, доступ запрещён или элемент нельзя восстановить.
    """

    request_data = data.model_copy(update={"trash_item_id": trash_item_id})
    return await trash_service.restore(request_data, actor_id=current_user.id)


@router.post(
    "/{trash_item_id}/purge",
    response_model=TrashPurgeResponse,
    status_code=status.HTTP_200_OK,
)
async def purge_trash_item(
    current_user: CurrentActiveUserDependency,
    trash_item_id: UUID = Path(...),
    trash_service: TrashService = Depends(get_trash_service_dependency),
    data: dict[str, str | None] | None = None,
) -> TrashPurgeResponse:
    """Окончательно удаляет элемент из корзины.

    Подставляет идентификатор элемента корзины из URL в список удаляемых
    элементов, очищает список `node_ids` и запускает окончательное удаление
    через сервисный слой. Операция необратимо удаляет элемент в рамках
    бизнес-логики сервиса.

    Args:
        data: Параметры окончательного удаления из корзины.
        current_user: Текущий активный пользователь, выполняющий удаление.
        trash_item_id: Уникальный идентификатор элемента корзины.
        trash_service: Сервис корзины, выполняющий окончательное удаление.

    Returns:
        Результат окончательного удаления элемента из корзины.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, элемент корзины
            не найден, доступ запрещён или элемент нельзя окончательно удалить.
    """

    reason = None if data is None else data.get("reason")
    request_data = TrashPurgeRequest(
        trash_item_ids=[trash_item_id],
        node_ids=None,
        reason=reason,
    )
    return await trash_service.purge(request_data, actor_id=current_user.id)


@router.post(
    "/empty",
    response_model=TrashPurgeResponse,
    status_code=status.HTTP_200_OK,
)
async def empty_trash(
    data: TrashEmptyRequest,
    current_user: CurrentActiveUserDependency,
    trash_service: TrashService = Depends(get_trash_service_dependency),
) -> TrashPurgeResponse:
    """Очищает корзину текущего пользователя.

    Окончательно удаляет элементы корзины, подходящие под параметры запроса,
    в контексте текущего пользователя.

    Args:
        data: Параметры очистки корзины.
        current_user: Текущий активный пользователь, очищающий корзину.
        trash_service: Сервис корзины, выполняющий очистку.

    Returns:
        Результат очистки корзины.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            параметры очистки некорректны, доступ запрещён или очистку нельзя
            выполнить.
    """

    return await trash_service.empty_trash(data, actor_id=current_user.id)


@router.post(
    "/cleanup",
    response_model=TrashPurgeResponse,
    status_code=status.HTTP_200_OK,
)
async def cleanup_trash(
    data: TrashCleanupRequest,
    current_admin: CurrentAdminUserDependency,
    trash_service: TrashService = Depends(get_trash_service_dependency),
) -> TrashPurgeResponse:
    """Запускает очистку устаревших элементов корзины.

    Выполняет административную очистку элементов корзины, срок хранения которых
    истёк или которые соответствуют параметрам очистки. Операция выполняется
    от имени текущего администратора.

    Args:
        data: Параметры очистки устаревших элементов корзины.
        current_admin: Текущий авторизованный администратор, запускающий
            очистку.
        trash_service: Сервис корзины, выполняющий административную очистку.

    Returns:
        Результат очистки устаревших элементов корзины.

    Raises:
        HTTPException: Если администратор не аутентифицирован, доступ запрещён,
            параметры очистки некорректны или очистку невозможно выполнить.
    """

    return await trash_service.cleanup_expired(data, actor_id=current_admin.id)
