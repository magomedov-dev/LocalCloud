from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from api.dependencies import get_permissions_service_dependency
from schemas.common import PageResponse
from schemas.permissions import (
    EffectivePermissionRead,
    NodePermissionListItem,
    NodePermissionRead,
    NodePermissionUpdate,
    PermissionCheckRequest,
    PermissionCheckResponse,
    PermissionGrantRequest,
    PermissionRevokeRequest,
    PermissionUpdateRequest,
)
from security import CurrentActiveUserDependency, RequireShareNodeDependency
from services import PermissionsService

# Маршрутизатор эндпоинтов для управления правами доступа.
router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get(
    "/nodes/{node_id}",
    response_model=PageResponse[NodePermissionListItem],
    status_code=status.HTTP_200_OK,
)
async def list_node_permissions(
    current_user: CurrentActiveUserDependency,
    _: None = RequireShareNodeDependency,
    node_id: UUID = Path(...),
    active_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    permissions_service: PermissionsService = Depends(
        get_permissions_service_dependency
    ),
) -> PageResponse[NodePermissionListItem]:
    """Возвращает список прав доступа для узла.

    Получает страницу разрешений, выданных для указанного узла. Запрос
    выполняется от имени текущего пользователя и требует права на управление
    доступом к этому узлу.

    Args:
        current_user: Текущий активный пользователь, запрашивающий список прав.
        _: Зависимость проверки права на управление доступом к узлу.
            Используется только для авторизации и не применяется внутри функции
            напрямую.
        node_id: Уникальный идентификатор узла.
        active_only: Нужно ли возвращать только активные права доступа.
        offset: Смещение от начала списка прав.
        limit: Максимальное количество прав доступа в ответе.
        permissions_service: Сервис прав доступа, выполняющий получение списка.

    Returns:
        Страница прав доступа к узлу с метаданными пагинации.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            узел не найден, у пользователя нет права на управление доступом
            или параметры пагинации некорректны.
    """

    return await permissions_service.list_node_permissions(
        node_id=node_id,
        actor_id=current_user.id,
        active_only=active_only,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/grant",
    response_model=NodePermissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def grant_permission(
    data: PermissionGrantRequest,
    current_user: CurrentActiveUserDependency,
    permissions_service: PermissionsService = Depends(
        get_permissions_service_dependency
    ),
) -> NodePermissionRead:
    """Выдаёт право доступа к узлу.

    Создаёт новое разрешение на доступ к узлу для указанного пользователя,
    группы или другого субъекта доступа. Операция выполняется от имени текущего
    пользователя.

    Args:
        data: Данные для выдачи права доступа.
        current_user: Текущий активный пользователь, выдающий право доступа.
        permissions_service: Сервис прав доступа, выполняющий создание
            разрешения.

    Returns:
        Данные созданного права доступа.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            узел или субъект доступа не найден, у пользователя нет права
            делиться узлом либо параметры разрешения некорректны.
    """

    return await permissions_service.grant_permission(data, actor_id=current_user.id)


@router.patch(
    "/{permission_id}",
    response_model=NodePermissionRead,
    status_code=status.HTTP_200_OK,
)
async def update_permission(
    data: PermissionUpdateRequest | NodePermissionUpdate,
    current_user: CurrentActiveUserDependency,
    permission_id: UUID = Path(...),
    permissions_service: PermissionsService = Depends(
        get_permissions_service_dependency
    ),
) -> NodePermissionRead:
    """Обновляет выданное право доступа.

    Формирует запрос обновления с идентификатором права из URL и новыми
    параметрами доступа из тела запроса, после чего передаёт его в сервисный
    слой. Операция выполняется от имени текущего пользователя.

    Args:
        data: Новые параметры права доступа.
        current_user: Текущий активный пользователь, обновляющий право доступа.
        permission_id: Уникальный идентификатор обновляемого права доступа.
        permissions_service: Сервис прав доступа, выполняющий обновление
            разрешения.

    Returns:
        Данные права доступа после обновления.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, право доступа
            не найдено, у пользователя нет права изменять разрешение или
            переданные параметры некорректны.
    """

    request_data = PermissionUpdateRequest(
        permission_id=permission_id,
        permission_level=data.permission_level,
        can_read=data.can_read,
        can_download=data.can_download,
        can_write=data.can_write,
        can_delete=data.can_delete,
        can_share=data.can_share,
        expires_at=data.expires_at,
    )
    return await permissions_service.update_permission(
        request_data,
        actor_id=current_user.id,
    )


@router.post(
    "/revoke",
    response_model=NodePermissionRead,
    status_code=status.HTTP_200_OK,
)
async def revoke_permission(
    data: PermissionRevokeRequest,
    current_user: CurrentActiveUserDependency,
    permissions_service: PermissionsService = Depends(
        get_permissions_service_dependency
    ),
) -> NodePermissionRead:
    """Отзывает ранее выданное право доступа.

    Деактивирует или отзывает существующее разрешение на доступ к узлу.
    Операция выполняется от имени текущего пользователя.

    Args:
        data: Данные для отзыва права доступа.
        current_user: Текущий активный пользователь, отзывающий право доступа.
        permissions_service: Сервис прав доступа, выполняющий отзыв разрешения.

    Returns:
        Данные отозванного права доступа.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, право доступа
            не найдено, у пользователя нет права отозвать разрешение или
            отзыв невозможен.
    """

    return await permissions_service.revoke_permission(data, actor_id=current_user.id)


@router.post(
    "/check",
    response_model=PermissionCheckResponse,
    status_code=status.HTTP_200_OK,
)
async def check_permission(
    data: PermissionCheckRequest,
    permissions_service: PermissionsService = Depends(
        get_permissions_service_dependency
    ),
) -> PermissionCheckResponse:
    """Проверяет разрешение на выполнение действия над узлом.

    Проверяет, может ли указанный субъект выполнить запрошенное действие
    над конкретным узлом. Эндпоинт возвращает результат проверки без изменения
    состояния прав доступа.

    Args:
        data: Параметры проверки права доступа.
        permissions_service: Сервис прав доступа, выполняющий проверку.

    Returns:
        Результат проверки разрешения на действие.

    Raises:
        HTTPException: Если параметры проверки некорректны, узел не найден
            или проверка не может быть выполнена.
    """

    return await permissions_service.check_permission(data)


@router.get(
    "/nodes/{node_id}/effective",
    response_model=EffectivePermissionRead,
    status_code=status.HTTP_200_OK,
)
async def get_effective_permissions(
    current_user: CurrentActiveUserDependency,
    node_id: UUID = Path(...),
    allow_deleted: bool = Query(default=False),
    allow_public: bool = Query(default=True),
    permissions_service: PermissionsService = Depends(
        get_permissions_service_dependency
    ),
) -> EffectivePermissionRead:
    """Возвращает эффективные права текущего пользователя на узел.

    Вычисляет итоговый набор прав текущего пользователя на указанный узел
    с учётом прямых разрешений, публичного доступа и дополнительных правил,
    реализованных в сервисном слое.

    Args:
        current_user: Текущий активный пользователь, для которого вычисляются
            эффективные права.
        node_id: Уникальный идентификатор узла.
        allow_deleted: Нужно ли учитывать удалённые узлы при расчёте прав.
        allow_public: Нужно ли учитывать публичные права доступа.
        permissions_service: Сервис прав доступа, выполняющий расчёт
            эффективных прав.

    Returns:
        Эффективные права текущего пользователя на указанный узел.

    Raises:
        HTTPException: Если пользователь не аутентифицирован, неактивен,
            узел не найден, удалённый узел не разрешён параметрами запроса
            или расчёт прав невозможен.
    """

    return await permissions_service.get_effective_permissions(
        node_id=node_id,
        user_id=current_user.id,
        allow_deleted=allow_deleted,
        allow_public=allow_public,
    )
