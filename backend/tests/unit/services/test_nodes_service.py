"""Юнит-тесты для NodesService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from database import DatabaseError
from database.models.enums import AuditAction, NodeType, NodeVisibility
from schemas.nodes import (
    NodeCopyRequest,
    NodeCreate,
    NodeMoveRequest,
    NodeQueryParams,
    NodeRenameRequest,
    NodeSearchQuery,
    NodeUpdate,
)
from services.exceptions import (
    PermissionServiceError,
    QuotaExceededServiceError,
    ServiceError,
    ValidationServiceError,
)
from services.nodes import (
    NodesService,
    _audit_metadata,
    _build_tree,
    _can_paginate_list_in_sql,
    _filter_query_nodes,
    _filter_search_nodes,
    _jsonable,
    _matches_range,
    _node_snapshot,
    _normalize_datetime,
    _normalize_sort_by,
    _sort_direction,
    _unique_copy_name,
    get_nodes_service,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def make_uow(**repos):
    uow = AsyncMock()
    uow.commit = AsyncMock()
    uow.flush = AsyncMock()
    uow.refresh = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    for name, repo in repos.items():
        setattr(uow, name, repo)
    return uow


def make_factory(uow):
    return MagicMock(return_value=uow)


def make_audit():
    svc = MagicMock()
    svc.log_user_event = AsyncMock()
    svc.log_system_event = AsyncMock()
    return svc


def make_node_mock(
    node_id=None,
    owner_id=None,
    node_type=NodeType.FOLDER,
    is_deleted=False,
    name="test-node",
    parent_id=None,
):
    node = MagicMock()
    node.id = node_id or uuid.uuid4()
    node.owner_id = owner_id or uuid.uuid4()
    node.parent_id = parent_id
    node.name = name
    node.node_type = node_type
    node.visibility = NodeVisibility.PRIVATE
    node.path = f"/{name}"
    node.depth = 1
    node.created_by = node.owner_id
    node.updated_by = node.owner_id
    node.deleted_by = None
    node.created_at = datetime.now(UTC)
    node.updated_at = datetime.now(UTC)
    node.is_deleted = is_deleted
    node.deleted_at = None
    node.file = None
    return node


def make_access(node=None):
    svc = MagicMock()
    svc.get_accessible_node = AsyncMock(return_value=node or make_node_mock())
    svc.require_access = AsyncMock()
    return svc


def make_nodes_service(uow, access_svc=None, audit_svc=None):
    return NodesService(
        uow_factory=make_factory(uow),
        access_service=access_svc or make_access(),
        audit_service=audit_svc or make_audit(),
    )


# ---------------------------------------------------------------------------
# Тесты: get_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_node_returns_node_read():
    """get_node возвращает NodeRead для доступного узла."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=user_id, node_type=NodeType.FOLDER)

    access = make_access(node=node)
    uow = make_uow()
    service = make_nodes_service(uow, access_svc=access)

    result = await service.get_node(node_id, user_id=user_id)

    assert result is not None
    assert str(result.id) == str(node_id)


@pytest.mark.asyncio
async def test_get_node_raises_permission_error():
    """get_node вызывает PermissionServiceError при отказе в доступе."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()

    access = MagicMock()
    access.get_accessible_node = AsyncMock(
        side_effect=PermissionServiceError(
            "Access denied",
            user_id=user_id,
            resource_type="node",
            resource_id=node_id,
            action="read",
        )
    )
    uow = make_uow()
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.get_node(node_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: create_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_node_success_for_owner():
    """create_node успешно отрабатывает, когда актор создаёт узел в корне как владелец."""
    owner_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=owner_id, parent_id=None)

    nodes_repo = AsyncMock()
    nodes_repo.create_node = AsyncMock(return_value=node)

    users_repo = AsyncMock()
    users_repo.get_required_user_by_id = AsyncMock(return_value=MagicMock(id=owner_id))

    uow = make_uow(nodes=nodes_repo, users=users_repo)
    service = make_nodes_service(uow)

    data = NodeCreate(name="my-folder", node_type=NodeType.FOLDER)
    result = await service.create_node(data, owner_id=owner_id, actor_id=owner_id)

    assert result is not None
    nodes_repo.create_node.assert_called_once()


@pytest.mark.asyncio
async def test_create_node_non_owner_raises_permission_error():
    """create_node вызывает PermissionServiceError, когда не-владелец создаёт узел в корне."""
    owner_id = uuid.uuid4()
    actor_id = uuid.uuid4()  # другой пользователь

    uow = make_uow()
    service = make_nodes_service(uow)

    data = NodeCreate(name="test-folder", node_type=NodeType.FOLDER)

    with pytest.raises(PermissionServiceError):
        await service.create_node(data, owner_id=owner_id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_create_node_with_parent_owner_mismatch_raises_validation_error():
    """create_node вызывает ValidationServiceError, когда родитель принадлежит другому владельцу."""
    owner_id = uuid.uuid4()
    other_owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()

    # Родитель принадлежит другому владельцу
    parent_node = make_node_mock(owner_id=other_owner_id, parent_id=None)

    access = make_access(node=parent_node)
    uow = make_uow()
    service = make_nodes_service(uow, access_svc=access)

    data = NodeCreate(name="test-folder", node_type=NodeType.FOLDER, parent_id=parent_id)

    with pytest.raises(ValidationServiceError):
        await service.create_node(data, owner_id=owner_id, actor_id=owner_id)


# ---------------------------------------------------------------------------
# Тесты: list_nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_nodes_root_returns_page():
    """list_nodes с owner_id=user_id возвращает страницу узлов."""
    user_id = uuid.uuid4()
    node = make_node_mock(owner_id=user_id)

    nodes_repo = AsyncMock()
    nodes_repo.get_root_nodes = AsyncMock(return_value=[node])
    nodes_repo.count_root_nodes = AsyncMock(return_value=1)

    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    params = NodeQueryParams(owner_id=user_id)
    result = await service.list_nodes(params, user_id=user_id)

    assert result is not None
    assert result.meta.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_list_nodes_requires_owner_or_user():
    """list_nodes без owner_id и parent_id вызывает PermissionServiceError."""
    uow = make_uow()
    service = make_nodes_service(uow)

    params = NodeQueryParams()  # нет owner_id, нет parent_id

    with pytest.raises(PermissionServiceError):
        await service.list_nodes(params, user_id=None)


@pytest.mark.asyncio
async def test_list_nodes_non_owner_raises_permission_error():
    """list_nodes вызывает PermissionServiceError, когда user != owner_id."""
    user_id = uuid.uuid4()
    other_id = uuid.uuid4()

    uow = make_uow()
    service = make_nodes_service(uow)

    params = NodeQueryParams(owner_id=other_id)

    with pytest.raises(PermissionServiceError):
        await service.list_nodes(params, user_id=user_id)


# ---------------------------------------------------------------------------
# Тесты: rename_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_node_success():
    """rename_node возвращает ответ с обновлённым узлом."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=user_id, name="old-name")
    renamed_node = make_node_mock(node_id=node_id, owner_id=user_id, name="new-name")

    access = make_access(node=node)
    nodes_repo = AsyncMock()
    nodes_repo.rename_node = AsyncMock(return_value=renamed_node)

    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    data = NodeRenameRequest(name="new-name")
    result = await service.rename_node(node_id, data, actor_id=user_id)

    assert result is not None
    nodes_repo.rename_node.assert_called_once()


def make_nodes_repo():
    repo = AsyncMock()
    repo.create_node = AsyncMock()
    repo.get_root_nodes = AsyncMock(return_value=[])
    repo.count_root_nodes = AsyncMock(return_value=0)
    repo.get_children = AsyncMock(return_value=[])
    repo.count_children = AsyncMock(return_value=0)
    repo.search_nodes = AsyncMock(return_value=[])
    repo.get_required_by_id = AsyncMock()
    repo.rename_node = AsyncMock()
    repo.move_node = AsyncMock()
    repo.update_visibility = AsyncMock()
    repo.restore_node = AsyncMock()
    repo.mark_purged = AsyncMock()
    repo.refresh = AsyncMock()
    repo.get_breadcrumbs = AsyncMock(return_value=[])
    repo.get_descendants = AsyncMock(return_value=[])
    repo.count_user_nodes = AsyncMock(return_value=0)
    repo.count_user_files = AsyncMock(return_value=0)
    repo.count_user_folders = AsyncMock(return_value=0)
    return repo


# ---------------------------------------------------------------------------
# Тесты: create_node (extra branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_node_with_parent_success_logs_audit():
    """create_node создаёт дочерний узел и пишет событие аудита."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(owner_id=owner_id, parent_id=None)
    created = make_node_mock(owner_id=owner_id, parent_id=parent_id)

    nodes_repo = make_nodes_repo()
    nodes_repo.create_node = AsyncMock(return_value=created)
    access = make_access(node=parent)
    audit = make_audit()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    data = NodeCreate(name="child", node_type=NodeType.FOLDER, parent_id=parent_id)
    result = await service.create_node(data, owner_id=owner_id)

    assert result.success is True
    nodes_repo.create_node.assert_called_once()
    audit.log_user_event.assert_awaited_once()
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_node_database_error_wrapped():
    """create_node преобразует DatabaseError в ServiceError."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.create_node = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    data = NodeCreate(name="folder", node_type=NodeType.FOLDER)
    with pytest.raises(ServiceError):
        await service.create_node(data, owner_id=owner_id, actor_id=owner_id)


@pytest.mark.asyncio
async def test_create_node_unexpected_error_wrapped():
    """create_node преобразует непредвиденную ошибку в ServiceError."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.create_node = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    data = NodeCreate(name="folder", node_type=NodeType.FOLDER)
    with pytest.raises(ServiceError):
        await service.create_node(data, owner_id=owner_id, actor_id=owner_id)


# ---------------------------------------------------------------------------
# Тесты: get_node (оборачивание ошибок)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_node_database_error_wrapped():
    """get_node преобразует DatabaseError в ServiceError."""
    access = MagicMock()
    access.get_accessible_node = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow()
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_node(uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_node_unexpected_error_wrapped():
    """get_node преобразует непредвиденную ошибку в ServiceError."""
    access = MagicMock()
    access.get_accessible_node = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow()
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_node(uuid.uuid4(), user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: list_nodes (extra branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_nodes_with_parent_sql_path():
    """list_nodes с родителем использует get_children/count_children в быстром SQL-пути."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id)
    child = make_node_mock(owner_id=owner_id, parent_id=parent_id)

    nodes_repo = make_nodes_repo()
    nodes_repo.get_children = AsyncMock(return_value=[child])
    nodes_repo.count_children = AsyncMock(return_value=1)
    access = make_access(node=parent)
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    params = NodeQueryParams(parent_id=parent_id, owner_id=owner_id)
    result = await service.list_nodes(params, user_id=owner_id)

    assert result.meta.total == 1
    nodes_repo.get_children.assert_called_once()
    nodes_repo.count_children.assert_called_once()


@pytest.mark.asyncio
async def test_list_nodes_parent_derives_owner_for_anonymous():
    """list_nodes выводит владельца из родителя, когда owner_id и user_id равны None."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id)
    child = make_node_mock(owner_id=owner_id, parent_id=parent_id)

    nodes_repo = make_nodes_repo()
    nodes_repo.get_children = AsyncMock(return_value=[child])
    nodes_repo.count_children = AsyncMock(return_value=1)
    access = make_access(node=parent)
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    params = NodeQueryParams(parent_id=parent_id)
    result = await service.list_nodes(params, user_id=None)
    assert result.meta.total == 1


@pytest.mark.asyncio
async def test_list_nodes_parent_owner_mismatch_raises_validation():
    """list_nodes вызывает ValidationServiceError, когда фильтр владельца отличается от родителя."""
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=uuid.uuid4())
    access = make_access(node=parent)
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow, access_svc=access)

    params = NodeQueryParams(parent_id=parent_id, owner_id=uuid.uuid4())
    with pytest.raises(ValidationServiceError):
        await service.list_nodes(params, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_list_nodes_python_filter_path():
    """list_nodes использует медленный путь фильтрации в Python, когда задана видимость."""
    owner_id = uuid.uuid4()
    public = make_node_mock(owner_id=owner_id)
    public.visibility = NodeVisibility.PUBLIC
    private = make_node_mock(owner_id=owner_id)
    private.visibility = NodeVisibility.PRIVATE

    nodes_repo = make_nodes_repo()
    nodes_repo.get_root_nodes = AsyncMock(return_value=[public, private])
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    params = NodeQueryParams(owner_id=owner_id, visibility=NodeVisibility.PUBLIC)
    result = await service.list_nodes(params, user_id=owner_id)

    assert result.meta.total == 1
    assert result.items[0].visibility == NodeVisibility.PUBLIC


@pytest.mark.asyncio
async def test_list_nodes_invalid_sort_raises_validation():
    """list_nodes вызывает ValidationServiceError для неподдерживаемого поля сортировки."""
    owner_id = uuid.uuid4()
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow)

    params = NodeQueryParams(owner_id=owner_id, sort_by="bogus")
    with pytest.raises(ValidationServiceError):
        await service.list_nodes(params, user_id=owner_id)


@pytest.mark.asyncio
async def test_list_nodes_database_error_wrapped():
    """list_nodes преобразует DatabaseError в ServiceError."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.get_root_nodes = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    params = NodeQueryParams(owner_id=owner_id)
    with pytest.raises(ServiceError):
        await service.list_nodes(params, user_id=owner_id)


@pytest.mark.asyncio
async def test_list_nodes_load_paginates_over_repository_limit():
    """_load_list_nodes повторяет цикл, пока не получит порцию меньше лимита страницы."""
    owner_id = uuid.uuid4()
    full_page = [make_node_mock(owner_id=owner_id) for _ in range(1000)]
    tail = [make_node_mock(owner_id=owner_id)]

    nodes_repo = make_nodes_repo()
    nodes_repo.get_root_nodes = AsyncMock(side_effect=[full_page, tail])
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    # заданная видимость включает медленный путь Python, вызывающий _load_list_nodes.
    params = NodeQueryParams(
        owner_id=owner_id, visibility=NodeVisibility.PRIVATE, limit=5, offset=0
    )
    result = await service.list_nodes(params, user_id=owner_id)

    assert result.meta.total == 1001
    assert nodes_repo.get_root_nodes.await_count == 2


# ---------------------------------------------------------------------------
# Тесты: search_nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_nodes_root_owner_success():
    """search_nodes в корне возвращает страницу для владельца."""
    owner_id = uuid.uuid4()
    node = make_node_mock(owner_id=owner_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.search_nodes = AsyncMock(return_value=[node])
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    params = NodeSearchQuery(query="test")
    result = await service.search_nodes(params, user_id=owner_id)
    assert result.meta.total == 1


@pytest.mark.asyncio
async def test_search_nodes_anonymous_raises_permission():
    """search_nodes в корне без владельца вызывает PermissionServiceError."""
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow)

    params = NodeSearchQuery(query="test")
    with pytest.raises(PermissionServiceError):
        await service.search_nodes(params, user_id=None)


@pytest.mark.asyncio
async def test_search_nodes_not_owner_raises_permission():
    """search_nodes вызывает PermissionServiceError, когда user != owner."""
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow)

    params = NodeSearchQuery(query="test", owner_id=uuid.uuid4())
    with pytest.raises(PermissionServiceError):
        await service.search_nodes(params, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_search_nodes_in_parent_success():
    """search_nodes внутри родителя проверяет доступ и выводит владельца."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id)
    node = make_node_mock(owner_id=owner_id, parent_id=parent_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.search_nodes = AsyncMock(return_value=[node])
    access = make_access(node=parent)
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    params = NodeSearchQuery(query="test", parent_id=parent_id)
    result = await service.search_nodes(params, user_id=None)
    assert result.meta.total == 1


@pytest.mark.asyncio
async def test_search_nodes_parent_owner_mismatch_raises_validation():
    """search_nodes вызывает ValidationServiceError при несовпадении владельца родителя."""
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=uuid.uuid4())
    access = make_access(node=parent)
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow, access_svc=access)

    params = NodeSearchQuery(query="t", parent_id=parent_id, owner_id=uuid.uuid4())
    with pytest.raises(ValidationServiceError):
        await service.search_nodes(params, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_search_nodes_database_error_wrapped():
    """search_nodes преобразует DatabaseError в ServiceError."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.search_nodes = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    params = NodeSearchQuery(query="t")
    with pytest.raises(ServiceError):
        await service.search_nodes(params, user_id=owner_id)


@pytest.mark.asyncio
async def test_search_nodes_unexpected_error_wrapped():
    """search_nodes преобразует непредвиденную ошибку в ServiceError."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.search_nodes = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    params = NodeSearchQuery(query="t")
    with pytest.raises(ServiceError):
        await service.search_nodes(params, user_id=owner_id)


# ---------------------------------------------------------------------------
# Тесты: update_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_node_rename_only():
    """update_node переименовывает узел и сообщает действие аудита NODE_RENAMED."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)

    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    nodes_repo.rename_node = AsyncMock(return_value=node)
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    data = NodeUpdate(name="renamed")
    result = await service.update_node(node_id, data, actor_id=actor_id)

    assert result.success is True
    nodes_repo.rename_node.assert_called_once()
    nodes_repo.move_node.assert_not_called()
    args, kwargs = audit.log_user_event.call_args
    assert kwargs["action"] == AuditAction.NODE_RENAMED


@pytest.mark.asyncio
async def test_update_node_move_only():
    """update_node перемещает узел, когда parent_id есть в наборе полей."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    new_parent = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)

    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    nodes_repo.move_node = AsyncMock(return_value=node)
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    data = NodeUpdate(parent_id=new_parent)
    result = await service.update_node(node_id, data, actor_id=actor_id)

    assert result.success is True
    nodes_repo.move_node.assert_called_once()
    # require_access вызван для WRITE узла и WRITE родителя.
    assert access.require_access.await_count >= 2
    _, kwargs = audit.log_user_event.call_args
    assert kwargs["action"] == AuditAction.NODE_MOVED


@pytest.mark.asyncio
async def test_update_node_move_to_root_no_parent_access():
    """update_node при перемещении в корень (parent_id=None) не требует доступа к родителю."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)

    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    nodes_repo.move_node = AsyncMock(return_value=node)
    access = make_access(node=node)
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    data = NodeUpdate(parent_id=None)
    result = await service.update_node(node_id, data, actor_id=actor_id)

    assert result.success is True
    nodes_repo.move_node.assert_called_once()
    # Только проверка WRITE для узла, без проверки родителя.
    assert access.require_access.await_count == 1


@pytest.mark.asyncio
async def test_update_node_visibility_only():
    """update_node меняет видимость и сообщает действие аудита NODE_UPDATED."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)

    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    nodes_repo.update_visibility = AsyncMock(return_value=node)
    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    data = NodeUpdate(visibility=NodeVisibility.PUBLIC)
    result = await service.update_node(
        node_id, data, actor_id=actor_id, recursive_visibility=True
    )

    assert result.success is True
    nodes_repo.update_visibility.assert_called_once()
    _, kwargs = audit.log_user_event.call_args
    assert kwargs["action"] == AuditAction.NODE_UPDATED


@pytest.mark.asyncio
async def test_update_node_database_error_wrapped():
    """update_node преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access(node=node)
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.update_node(node_id, NodeUpdate(name="x"), actor_id=actor_id)


@pytest.mark.asyncio
async def test_update_node_unexpected_error_wrapped():
    """update_node преобразует непредвиденную ошибку в ServiceError."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access(node=node)
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.update_node(node_id, NodeUpdate(name="x"), actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: move_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_node_to_parent_success():
    """move_node перемещает в целевого родителя и логирует событие аудита."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    target_id = uuid.uuid4()
    moved = make_node_mock(node_id=node_id, owner_id=actor_id, parent_id=target_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.move_node = AsyncMock(return_value=moved)
    access = make_access()
    audit = make_audit()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    data = NodeMoveRequest(target_parent_id=target_id)
    result = await service.move_node(node_id, data, actor_id=actor_id)

    assert result.success is True
    nodes_repo.move_node.assert_called_once()
    assert access.require_access.await_count == 2
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_move_node_to_root_success():
    """move_node в корень проверяет только доступ к узлу."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    moved = make_node_mock(node_id=node_id, owner_id=actor_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.move_node = AsyncMock(return_value=moved)
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    data = NodeMoveRequest(target_parent_id=None)
    result = await service.move_node(node_id, data, actor_id=actor_id)

    assert result.success is True
    assert access.require_access.await_count == 1


@pytest.mark.asyncio
async def test_move_node_permission_error_passthrough():
    """move_node пробрасывает PermissionServiceError из проверок доступа."""
    actor_id = uuid.uuid4()
    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", action="write")
    )
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.move_node(
            uuid.uuid4(), NodeMoveRequest(target_parent_id=None), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_move_node_database_error_wrapped():
    """move_node преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.move_node = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.move_node(
            uuid.uuid4(), NodeMoveRequest(target_parent_id=None), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_move_node_unexpected_error_wrapped():
    """move_node преобразует непредвиденную ошибку в ServiceError."""
    actor_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.move_node = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.move_node(
            uuid.uuid4(), NodeMoveRequest(target_parent_id=None), actor_id=actor_id
        )


# ---------------------------------------------------------------------------
# Тесты: update_visibility / delete_node / restore_node (через _mutate_node)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_visibility_success():
    """update_visibility проверяет право SHARE и обновляет видимость."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.update_visibility = AsyncMock(return_value=node)
    access = make_access()
    audit = make_audit()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    result = await service.update_visibility(
        node_id, NodeVisibility.SHARED, actor_id=actor_id, recursive=True
    )
    assert result.success is True
    nodes_repo.update_visibility.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_node_success():
    """delete_node перемещает узел в корзину и пишет аудит."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    trash_repo = AsyncMock()
    trash_repo.create_trash_item = AsyncMock()
    access = make_access()
    audit = make_audit()
    uow = make_uow(nodes=nodes_repo, trash=trash_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    result = await service.delete_node(node_id, actor_id=actor_id)
    assert result.success is True
    trash_repo.create_trash_item.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_node_success():
    """restore_node восстанавливает узел и пишет аудит."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.restore_node = AsyncMock(return_value=node)
    access = make_access()
    audit = make_audit()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    result = await service.restore_node(node_id, actor_id=actor_id)
    assert result.success is True
    nodes_repo.restore_node.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_mutate_node_database_error_wrapped():
    """_mutate_node преобразует DatabaseError в ServiceError (через update_visibility)."""
    actor_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.update_visibility = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.update_visibility(
            uuid.uuid4(), NodeVisibility.PRIVATE, actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_mutate_node_unexpected_error_wrapped():
    """_mutate_node преобразует непредвиденную ошибку в ServiceError (через update_visibility)."""
    actor_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.update_visibility = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.update_visibility(
            uuid.uuid4(), NodeVisibility.PRIVATE, actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_mutate_node_audit_failure_does_not_break(caplog):
    """_safe_log_node_event поглощает сбои аудита и возвращает успех."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.update_visibility = AsyncMock(return_value=node)
    access = make_access()
    audit = make_audit()
    audit.log_user_event = AsyncMock(side_effect=RuntimeError("audit down"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    result = await service.update_visibility(
        node_id, NodeVisibility.PRIVATE, actor_id=actor_id
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# Тесты: purge_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_node_success():
    """purge_node помечает узел purged и возвращает ответ без узла."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    access = make_access()
    audit = make_audit()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access, audit_svc=audit)

    result = await service.purge_node(node_id, actor_id=actor_id)
    assert result.success is True
    assert result.node is None
    nodes_repo.mark_purged.assert_called_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_node_database_error_wrapped():
    """purge_node преобразует DatabaseError в ServiceError."""
    actor_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.purge_node(uuid.uuid4(), actor_id=actor_id)


@pytest.mark.asyncio
async def test_purge_node_unexpected_error_wrapped():
    """purge_node преобразует непредвиденную ошибку в ServiceError."""
    actor_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.purge_node(uuid.uuid4(), actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: get_breadcrumbs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_breadcrumbs_success():
    """get_breadcrumbs возвращает элементы хлебных крошек для цепочки предков."""
    user_id = uuid.uuid4()
    node_id = uuid.uuid4()
    root = make_node_mock(owner_id=user_id, name="root")
    leaf = make_node_mock(node_id=node_id, owner_id=user_id, name="leaf")
    nodes_repo = make_nodes_repo()
    nodes_repo.get_breadcrumbs = AsyncMock(return_value=[root, leaf])
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    result = await service.get_breadcrumbs(node_id, user_id=user_id)
    assert len(result) == 2
    assert result[1].name == "leaf"


@pytest.mark.asyncio
async def test_get_breadcrumbs_database_error_wrapped():
    """get_breadcrumbs преобразует DatabaseError в ServiceError."""
    nodes_repo = make_nodes_repo()
    nodes_repo.get_breadcrumbs = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_breadcrumbs(uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_get_breadcrumbs_unexpected_error_wrapped():
    """get_breadcrumbs преобразует непредвиденную ошибку в ServiceError."""
    access = MagicMock()
    access.require_access = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_breadcrumbs(uuid.uuid4(), user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: get_tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tree_success_builds_nested_tree():
    """get_tree собирает вложенное дерево из потомков."""
    user_id = uuid.uuid4()
    root_id = uuid.uuid4()
    root = make_node_mock(node_id=root_id, owner_id=user_id, name="root")
    child_a = make_node_mock(
        owner_id=user_id, name="a.txt", node_type=NodeType.FILE, parent_id=root_id
    )
    child_b = make_node_mock(
        owner_id=user_id, name="b", node_type=NodeType.FOLDER, parent_id=root_id
    )
    nodes_repo = make_nodes_repo()
    nodes_repo.get_descendants = AsyncMock(return_value=[root, child_a, child_b])
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    tree = await service.get_tree(root_id, user_id=user_id)
    assert str(tree.id) == str(root_id)
    assert len(tree.children) == 2


@pytest.mark.asyncio
async def test_get_tree_missing_root_raises_service_error():
    """get_tree вызывает ServiceError, когда потомки не содержат корень."""
    user_id = uuid.uuid4()
    root_id = uuid.uuid4()
    other = make_node_mock(owner_id=user_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.get_descendants = AsyncMock(return_value=[other])
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_tree(root_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_tree_database_error_wrapped():
    """get_tree преобразует DatabaseError в ServiceError."""
    nodes_repo = make_nodes_repo()
    nodes_repo.get_descendants = AsyncMock(side_effect=DatabaseError("db"))
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_tree(uuid.uuid4(), user_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: count_user_nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_user_nodes_success():
    """count_user_nodes возвращает количество всего/файлов/папок для собственных узлов."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.count_user_nodes = AsyncMock(return_value=5)
    nodes_repo.count_user_files = AsyncMock(return_value=3)
    nodes_repo.count_user_folders = AsyncMock(return_value=2)
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    counts = await service.count_user_nodes(owner_id=owner_id, user_id=owner_id)
    assert counts["total"] == 5
    assert counts[NodeType.FILE] == 3
    assert counts[NodeType.FOLDER] == 2


@pytest.mark.asyncio
async def test_count_user_nodes_not_owner_raises_permission():
    """count_user_nodes вызывает PermissionServiceError для другого владельца."""
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.count_user_nodes(owner_id=uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_count_user_nodes_database_error_wrapped():
    """count_user_nodes преобразует DatabaseError в ServiceError."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.count_user_nodes = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    with pytest.raises(ServiceError):
        await service.count_user_nodes(owner_id=owner_id, user_id=owner_id)


@pytest.mark.asyncio
async def test_count_user_nodes_unexpected_error_wrapped():
    """count_user_nodes преобразует непредвиденную ошибку в ServiceError."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.count_user_nodes = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    with pytest.raises(ServiceError):
        await service.count_user_nodes(owner_id=owner_id, user_id=owner_id)


# ---------------------------------------------------------------------------
# Тесты: module-level helpers
# ---------------------------------------------------------------------------


def test_can_paginate_list_in_sql_true_and_false():
    """_can_paginate_list_in_sql возвращает True для простых параметров и False при наличии фильтров."""
    assert _can_paginate_list_in_sql(NodeQueryParams()) is True
    assert (
        _can_paginate_list_in_sql(NodeQueryParams(visibility=NodeVisibility.PUBLIC))
        is False
    )
    assert _can_paginate_list_in_sql(NodeQueryParams(is_deleted=True)) is False


def test_sort_direction_and_normalize():
    """_sort_direction и _normalize_sort_by ведут себя как описано."""
    assert _sort_direction(True) == "desc"
    assert _sort_direction(False) == "asc"
    assert _normalize_sort_by("  Name ") == "name"
    with pytest.raises(ValidationServiceError):
        _normalize_sort_by("unknown")


def test_matches_range_and_normalize_datetime():
    """_matches_range учитывает границы, а _normalize_datetime возвращает UTC."""
    naive = datetime(2025, 1, 1, 12, 0, 0)
    assert _normalize_datetime(naive).tzinfo == UTC
    aware = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert _normalize_datetime(aware).tzinfo == UTC

    assert _matches_range(None, None, None) is True
    assert _matches_range(None, aware, None) is False
    assert _matches_range(aware, datetime(2024, 1, 1, tzinfo=UTC), None) is True
    assert _matches_range(aware, datetime(2026, 1, 1, tzinfo=UTC), None) is False
    assert _matches_range(aware, None, datetime(2024, 1, 1, tzinfo=UTC)) is False


def test_filter_query_and_search_nodes():
    """_filter_query_nodes и _filter_search_nodes применяют фильтры по видимости и удалению."""
    owner_id = uuid.uuid4()
    public = make_node_mock(owner_id=owner_id)
    public.visibility = NodeVisibility.PUBLIC
    deleted = make_node_mock(owner_id=owner_id, is_deleted=True)
    deleted.visibility = NodeVisibility.PUBLIC

    params = NodeQueryParams(visibility=NodeVisibility.PUBLIC)
    filtered = _filter_query_nodes([public, deleted], params)
    assert public in filtered
    assert deleted not in filtered  # is_deleted по умолчанию False отфильтровывает его

    search_params = NodeSearchQuery(query="x", visibility=NodeVisibility.PUBLIC)
    searched = _filter_search_nodes([public, deleted], search_params)
    assert public in searched
    assert deleted not in searched


def test_build_tree_missing_root_raises():
    """_build_tree вызывает ServiceError, когда отсутствует id корня."""
    node = make_node_mock()
    with pytest.raises(ServiceError):
        _build_tree([node], root_node_id=uuid.uuid4())


def test_jsonable_and_audit_metadata():
    """_jsonable преобразует типы, а _audit_metadata выбирает ключевые поля."""
    assert _jsonable(None) is None
    assert _jsonable("s") == "s"
    val = uuid.uuid4()
    assert _jsonable(val) == str(val)
    assert _jsonable(NodeType.FILE) == NodeType.FILE.value
    dt = datetime(2025, 1, 1, tzinfo=UTC)
    assert _jsonable(dt) == dt.isoformat()
    assert _jsonable(object()) is not None  # откатывается к str

    node = make_node_mock()
    snapshot = _node_snapshot(node)
    meta = _audit_metadata(snapshot)
    assert "id" in meta and "name" in meta
    assert "created_at" not in meta  # нет в списке разрешённых для аудита


def test_node_snapshot_handles_invalid_request_error():
    """_node_snapshot устойчив к узлу, чья связь с файлом бросает InvalidRequestError."""
    from sqlalchemy.exc import InvalidRequestError

    node = make_node_mock()
    type(node).file = property(
        lambda self: (_ for _ in ()).throw(InvalidRequestError("not loaded"))
    )
    snapshot = _node_snapshot(node)
    assert snapshot["file_size_bytes"] is None
    assert snapshot["file_mime_type"] is None


# ---------------------------------------------------------------------------
# Тесты: get_nodes_service factory
# ---------------------------------------------------------------------------


def test_get_nodes_service_with_overrides_returns_new_instance():
    """get_nodes_service возвращает новый экземпляр, когда передана зависимость."""
    uow = make_uow(nodes=make_nodes_repo())
    svc = get_nodes_service(uow_factory=make_factory(uow))
    assert isinstance(svc, NodesService)


def test_get_nodes_service_singleton():
    """get_nodes_service возвращает кешированный синглтон без переопределений."""
    a = get_nodes_service()
    b = get_nodes_service()
    assert a is b


def test_matches_deleted_none_and_jsonable_enum_and_empty_error():
    """Покрывает ветку None в _matches_deleted, _jsonable на не-строковом Enum и _empty_result_error."""
    from enum import Enum

    from services.nodes import _empty_result_error, _matches_deleted

    node = make_node_mock()
    assert _matches_deleted(node, None) is True

    class Color(Enum):
        RED = "red"

    assert _jsonable(Color.RED) == "red"

    err = _empty_result_error("op")
    assert isinstance(err, ServiceError)
    assert err.operation == "op"


@pytest.mark.asyncio
async def test_update_node_service_error_passthrough():
    """update_node пробрасывает ServiceError, возникший по ходу операции."""
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    node = make_node_mock(node_id=node_id, owner_id=actor_id)
    nodes_repo = make_nodes_repo()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    nodes_repo.rename_node = AsyncMock(
        side_effect=ValidationServiceError("bad", field="name")
    )
    access = make_access(node=node)
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ValidationServiceError):
        await service.update_node(node_id, NodeUpdate(name="x"), actor_id=actor_id)


@pytest.mark.asyncio
async def test_get_tree_service_error_passthrough():
    """get_tree пробрасывает ServiceError, возникший при проверке доступа."""
    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", action="read")
    )
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.get_tree(uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_count_user_nodes_service_error_passthrough():
    """count_user_nodes пробрасывает ServiceError из репозитория."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.count_user_nodes = AsyncMock(side_effect=ServiceError("boom"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    with pytest.raises(ServiceError):
        await service.count_user_nodes(owner_id=owner_id, user_id=owner_id)


@pytest.mark.asyncio
async def test_search_nodes_load_paginates_over_repository_limit():
    """_load_search_nodes повторяет цикл, пока не получит порцию меньше лимита страницы."""
    owner_id = uuid.uuid4()
    full_page = [make_node_mock(owner_id=owner_id) for _ in range(1000)]
    tail = [make_node_mock(owner_id=owner_id)]
    nodes_repo = make_nodes_repo()
    nodes_repo.search_nodes = AsyncMock(side_effect=[full_page, tail])
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    params = NodeSearchQuery(query="x", limit=5, offset=0)
    result = await service.search_nodes(params, user_id=owner_id)
    assert result.meta.total == 1001
    assert nodes_repo.search_nodes.await_count == 2


@pytest.mark.asyncio
async def test_list_nodes_service_error_passthrough():
    """list_nodes пробрасывает ServiceError из репозитория."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.get_root_nodes = AsyncMock(side_effect=ServiceError("boom"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    with pytest.raises(ServiceError):
        await service.list_nodes(NodeQueryParams(owner_id=owner_id), user_id=owner_id)


@pytest.mark.asyncio
async def test_move_node_service_error_passthrough():
    """move_node пробрасывает ServiceError из репозитория."""
    actor_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.move_node = AsyncMock(side_effect=ServiceError("boom"))
    access = make_access()
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.move_node(
            uuid.uuid4(), NodeMoveRequest(target_parent_id=None), actor_id=actor_id
        )


@pytest.mark.asyncio
async def test_purge_node_service_error_passthrough():
    """purge_node пробрасывает ServiceError, возникший при проверке доступа."""
    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", action="manage")
    )
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.purge_node(uuid.uuid4(), actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_breadcrumbs_service_error_passthrough():
    """get_breadcrumbs пробрасывает ServiceError, возникший при проверке доступа."""
    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", action="read")
    )
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.get_breadcrumbs(uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_mutate_node_service_error_passthrough():
    """_mutate_node пробрасывает ServiceError, возникший при проверке доступа."""
    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", action="share")
    )
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.update_visibility(
            uuid.uuid4(), NodeVisibility.PRIVATE, actor_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_list_nodes_unexpected_error_wrapped():
    """list_nodes преобразует непредвиденную ошибку в ServiceError."""
    owner_id = uuid.uuid4()
    nodes_repo = make_nodes_repo()
    nodes_repo.get_root_nodes = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow)

    with pytest.raises(ServiceError):
        await service.list_nodes(NodeQueryParams(owner_id=owner_id), user_id=owner_id)


@pytest.mark.asyncio
async def test_get_tree_unexpected_error_wrapped():
    """get_tree преобразует непредвиденную ошибку в ServiceError."""
    access = MagicMock()
    access.require_access = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(nodes=make_nodes_repo())
    service = make_nodes_service(uow, access_svc=access)

    with pytest.raises(ServiceError):
        await service.get_tree(uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_list_nodes_slow_path_with_parent_get_children():
    """Медленный путь list_nodes загружает детей через _load_list_nodes при фильтрации."""
    owner_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    parent = make_node_mock(node_id=parent_id, owner_id=owner_id)
    child = make_node_mock(owner_id=owner_id, parent_id=parent_id)
    child.visibility = NodeVisibility.PUBLIC

    nodes_repo = make_nodes_repo()
    nodes_repo.get_children = AsyncMock(return_value=[child])
    access = make_access(node=parent)
    uow = make_uow(nodes=nodes_repo)
    service = make_nodes_service(uow, access_svc=access)

    params = NodeQueryParams(
        parent_id=parent_id, owner_id=owner_id, visibility=NodeVisibility.PUBLIC
    )
    result = await service.list_nodes(params, user_id=owner_id)

    assert result.meta.total == 1
    nodes_repo.get_children.assert_called_once()


# ---------------------------------------------------------------------------
# Тесты: _unique_copy_name
# ---------------------------------------------------------------------------


def test_unique_copy_name_no_conflict_returns_desired():
    """_unique_copy_name возвращает исходное имя без конфликта."""
    assert _unique_copy_name(set(), "report.pdf", is_file=True) == "report.pdf"


def test_unique_copy_name_file_preserves_extension():
    """_unique_copy_name сохраняет расширение файла при конфликте."""
    assert (
        _unique_copy_name({"report.pdf"}, "report.pdf", is_file=True)
        == "report (копия).pdf"
    )


def test_unique_copy_name_folder_appends_suffix():
    """_unique_copy_name добавляет суффикс к имени папки при конфликте."""
    assert _unique_copy_name({"docs"}, "docs", is_file=False) == "docs (копия)"


def test_unique_copy_name_increments_counter():
    """_unique_copy_name увеличивает счётчик при множественных конфликтах."""
    existing = {"docs", "docs (копия)"}
    assert _unique_copy_name(existing, "docs", is_file=False) == "docs (копия 2)"


# ---------------------------------------------------------------------------
# Тесты: copy_node
# ---------------------------------------------------------------------------


def make_file_node_mock(node_id=None, owner_id=None, name="file.txt", parent_id=None):
    return make_node_mock(
        node_id=node_id,
        owner_id=owner_id,
        node_type=NodeType.FILE,
        name=name,
        parent_id=parent_id,
    )


def make_file_row(
    *,
    size_bytes=10,
    mime_type="text/plain",
    bucket="files",
    key="users/x/files/a/versions/b",
):
    row = MagicMock()
    row.storage_bucket = bucket
    row.storage_key = key
    row.size_bytes = size_bytes
    row.mime_type = mime_type
    row.extension = "txt"
    row.checksum = "abc"
    row.checksum_algorithm = "sha256"
    return row


def make_quota_mock(
    *, available=1000, files_limit=None, files_used=0, used=0, limit=1000
):
    quota = MagicMock()
    quota.available_storage_bytes = available
    quota.files_limit = files_limit
    quota.files_used = files_used
    quota.storage_used_bytes = used
    quota.storage_limit_bytes = limit
    return quota


def make_files_repo(*, file_rows=None, created_node_id=None):
    repo = AsyncMock()
    if file_rows is not None:
        repo.get_required_by_node_id = AsyncMock(
            side_effect=lambda node_id: file_rows[node_id]
        )
    else:
        repo.get_required_by_node_id = AsyncMock()
    created = MagicMock()
    created.id = uuid.uuid4()
    created.node_id = created_node_id or uuid.uuid4()
    repo.create_file_with_node = AsyncMock(return_value=created)
    return repo


def make_quotas_repo(quota):
    repo = AsyncMock()
    repo.get_required_by_user_id = AsyncMock(return_value=quota)
    repo.increase_used_space = AsyncMock()
    repo.increase_files_used = AsyncMock()
    return repo


def make_versions_repo():
    repo = AsyncMock()
    repo.create_version = AsyncMock()
    return repo


def make_storage():
    svc = MagicMock()
    svc.copy_file_object = AsyncMock()
    svc.delete_file_object = AsyncMock()
    return svc


def make_copy_service(uow, storage, access_svc=None, audit_svc=None):
    return NodesService(
        uow_factory=make_factory(uow),
        access_service=access_svc or make_access(),
        audit_service=audit_svc or make_audit(),
        storage_service=storage,
    )


@pytest.mark.asyncio
async def test_copy_node_single_file():
    """copy_node для одиночного файла копирует объект и создаёт файл с версией."""
    actor_id = uuid.uuid4()
    file_node_id = uuid.uuid4()
    file_node = make_file_node_mock(
        node_id=file_node_id, owner_id=actor_id, name="report.txt"
    )
    file_row = make_file_row(size_bytes=42)

    nodes_repo = make_nodes_repo()
    nodes_repo.get_descendants = AsyncMock(return_value=[file_node])
    nodes_repo.get_root_nodes = AsyncMock(return_value=[])
    new_node = make_file_node_mock(owner_id=actor_id, name="report.txt")
    nodes_repo.get_required_by_id = AsyncMock(return_value=new_node)

    new_file_node_id = uuid.uuid4()
    files_repo = make_files_repo(
        file_rows={file_node_id: file_row}, created_node_id=new_file_node_id
    )
    quotas_repo = make_quotas_repo(make_quota_mock(available=1000))
    versions_repo = make_versions_repo()
    storage = make_storage()

    uow = make_uow(
        nodes=nodes_repo,
        files=files_repo,
        quotas=quotas_repo,
        versions=versions_repo,
    )
    audit = make_audit()
    service = make_copy_service(uow, storage, audit_svc=audit)

    result = await service.copy_node(
        file_node_id, NodeCopyRequest(target_parent_id=None), actor_id=actor_id
    )

    assert result.success is True
    storage.copy_file_object.assert_awaited_once()
    files_repo.create_file_with_node.assert_awaited_once()
    versions_repo.create_version.assert_awaited_once()
    quotas_repo.increase_used_space.assert_awaited_once()
    quotas_repo.increase_files_used.assert_awaited_once()
    audit.log_user_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_copy_node_folder_with_child_file():
    """copy_node рекурсивно копирует папку с дочерним файлом."""
    actor_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    child_id = uuid.uuid4()
    folder = make_node_mock(
        node_id=folder_id, owner_id=actor_id, node_type=NodeType.FOLDER, name="docs"
    )
    child = make_file_node_mock(
        node_id=child_id, owner_id=actor_id, name="a.txt", parent_id=folder_id
    )
    file_row = make_file_row(size_bytes=5)

    nodes_repo = make_nodes_repo()
    nodes_repo.get_descendants = AsyncMock(return_value=[folder, child])
    nodes_repo.get_root_nodes = AsyncMock(return_value=[])
    new_folder = MagicMock(node_id=uuid.uuid4())
    nodes_repo.get_required_by_id = AsyncMock(
        return_value=make_node_mock(owner_id=actor_id, node_type=NodeType.FOLDER)
    )
    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(
        return_value=MagicMock(description=None, color=None)
    )
    folders_repo.create_folder = AsyncMock(return_value=new_folder)

    files_repo = make_files_repo(file_rows={child_id: file_row})
    quotas_repo = make_quotas_repo(make_quota_mock(available=1000))
    versions_repo = make_versions_repo()
    storage = make_storage()

    uow = make_uow(
        nodes=nodes_repo,
        folders=folders_repo,
        files=files_repo,
        quotas=quotas_repo,
        versions=versions_repo,
    )
    service = make_copy_service(uow, storage)

    result = await service.copy_node(
        folder_id, NodeCopyRequest(target_parent_id=None), actor_id=actor_id
    )

    assert result.success is True
    folders_repo.create_folder.assert_awaited_once()
    files_repo.create_file_with_node.assert_awaited_once()
    storage.copy_file_object.assert_awaited_once()
    # Дочерний файл создаётся под новой папкой (по её node_id).
    _, kwargs = files_repo.create_file_with_node.call_args
    assert kwargs["parent_id"] == new_folder.node_id


@pytest.mark.asyncio
async def test_copy_node_quota_exceeded():
    """copy_node при превышении квоты выбрасывает QuotaExceededServiceError."""
    actor_id = uuid.uuid4()
    file_node_id = uuid.uuid4()
    file_node = make_file_node_mock(node_id=file_node_id, owner_id=actor_id)
    file_row = make_file_row(size_bytes=500)

    nodes_repo = make_nodes_repo()
    nodes_repo.get_descendants = AsyncMock(return_value=[file_node])

    files_repo = make_files_repo(file_rows={file_node_id: file_row})
    quotas_repo = make_quotas_repo(make_quota_mock(available=100))
    versions_repo = make_versions_repo()
    storage = make_storage()

    uow = make_uow(
        nodes=nodes_repo,
        files=files_repo,
        quotas=quotas_repo,
        versions=versions_repo,
    )
    service = make_copy_service(uow, storage)

    with pytest.raises(QuotaExceededServiceError):
        await service.copy_node(
            file_node_id, NodeCopyRequest(target_parent_id=None), actor_id=actor_id
        )

    storage.copy_file_object.assert_not_awaited()
    uow.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_copy_node_name_conflict_renames_root():
    """copy_node переименовывает корень при конфликте имени в целевой папке."""
    actor_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    folder = make_node_mock(
        node_id=folder_id, owner_id=actor_id, node_type=NodeType.FOLDER, name="docs"
    )

    existing = make_node_mock(owner_id=actor_id, name="docs")
    nodes_repo = make_nodes_repo()
    nodes_repo.get_descendants = AsyncMock(return_value=[folder])
    nodes_repo.get_root_nodes = AsyncMock(return_value=[existing])
    nodes_repo.get_required_by_id = AsyncMock(
        return_value=make_node_mock(owner_id=actor_id, node_type=NodeType.FOLDER)
    )
    folders_repo = AsyncMock()
    folders_repo.get_required_by_node_id = AsyncMock(
        return_value=MagicMock(description=None, color=None)
    )
    folders_repo.create_folder = AsyncMock(
        return_value=MagicMock(node_id=uuid.uuid4())
    )

    files_repo = make_files_repo(file_rows={})
    quotas_repo = make_quotas_repo(make_quota_mock(available=1000))
    versions_repo = make_versions_repo()
    storage = make_storage()

    uow = make_uow(
        nodes=nodes_repo,
        folders=folders_repo,
        files=files_repo,
        quotas=quotas_repo,
        versions=versions_repo,
    )
    service = make_copy_service(uow, storage)

    await service.copy_node(
        folder_id, NodeCopyRequest(target_parent_id=None), actor_id=actor_id
    )

    _, kwargs = folders_repo.create_folder.call_args
    assert kwargs["name"] == "docs (копия)"


@pytest.mark.asyncio
async def test_copy_node_storage_failure_rolls_back_objects():
    """copy_node при ошибке хранилища удаляет уже скопированные объекты."""
    actor_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    child1_id = uuid.uuid4()
    child2_id = uuid.uuid4()
    folder = make_node_mock(
        node_id=folder_id, owner_id=actor_id, node_type=NodeType.FOLDER, name="docs"
    )
    child1 = make_file_node_mock(
        node_id=child1_id, owner_id=actor_id, name="a.txt", parent_id=folder_id
    )
    child2 = make_file_node_mock(
        node_id=child2_id, owner_id=actor_id, name="b.txt", parent_id=folder_id
    )
    row1 = make_file_row(size_bytes=5, key="users/x/files/1/versions/1")
    row2 = make_file_row(size_bytes=5, key="users/x/files/2/versions/2")

    nodes_repo = make_nodes_repo()
    nodes_repo.get_descendants = AsyncMock(return_value=[folder, child1, child2])
    nodes_repo.get_root_nodes = AsyncMock(return_value=[])
    new_folder = make_node_mock(owner_id=actor_id, node_type=NodeType.FOLDER)
    nodes_repo.create_folder_node = AsyncMock(return_value=new_folder)

    files_repo = make_files_repo(file_rows={child1_id: row1, child2_id: row2})
    quotas_repo = make_quotas_repo(make_quota_mock(available=1000))
    versions_repo = make_versions_repo()
    storage = make_storage()
    # Первый файл копируется успешно, второй падает.
    storage.copy_file_object = AsyncMock(side_effect=[None, RuntimeError("boom")])

    uow = make_uow(
        nodes=nodes_repo,
        files=files_repo,
        quotas=quotas_repo,
        versions=versions_repo,
    )
    service = make_copy_service(uow, storage)

    with pytest.raises(ServiceError):
        await service.copy_node(
            folder_id, NodeCopyRequest(target_parent_id=None), actor_id=actor_id
        )

    # Уже скопированный объект первого файла удаляется best-effort.
    storage.delete_file_object.assert_awaited_once()
    uow.commit.assert_not_awaited()
