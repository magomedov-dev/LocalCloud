"""Юнит-тесты для PublicLinksService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.exceptions import DatabaseError
from database.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    NodeType,
    NodeVisibility,
    PublicLinkPermissionType,
    PublicLinkStatus,
    StorageObjectStatus,
)
from schemas.public_links import (
    PublicLinkAccessRequest,
    PublicLinkCreateRequest,
    PublicLinkQueryParams,
    PublicLinkRevokeRequest,
    PublicLinkUpdateRequest,
)
from security.password import hash_password
from services.exceptions import (
    PermissionServiceError,
    PublicLinkServiceError,
    ServiceError,
    ValidationServiceError,
)
from services.public_links import PublicLinksService
from storage import StorageError


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
    svc.log_success = AsyncMock()
    svc.log_event = AsyncMock()
    return svc


def make_presigned_url_result():
    result = MagicMock()
    result.url = "https://example.com/file"
    result.expires_at = datetime.now(UTC) + timedelta(hours=1)
    result.expires_in_seconds = 3600
    result.method = MagicMock()
    result.method.value = "GET"
    result.headers = {"x-test": "1"}
    return result


def make_storage():
    svc = MagicMock()
    svc.create_download_url = AsyncMock(return_value=make_presigned_url_result())
    svc.build_archive_key = MagicMock(return_value="archive/key.zip")
    svc.default_archives_bucket = "archives"
    return svc


def make_node_mock(node_id=None, owner_id=None, node_type=NodeType.FILE, name="test.txt"):
    node = MagicMock()
    node.id = node_id or uuid.uuid4()
    node.owner_id = owner_id or uuid.uuid4()
    node.parent_id = None
    node.name = name
    node.node_type = node_type
    node.visibility = NodeVisibility.PRIVATE
    node.path = f"/{name}"
    node.depth = 1
    node.created_at = datetime.now(UTC)
    node.updated_at = datetime.now(UTC)
    node.is_deleted = False
    return node


def make_link_mock(
    link_id=None,
    node_id=None,
    *,
    node=None,
    password_hash=None,
    can_view=True,
    can_download=True,
    status=PublicLinkStatus.ACTIVE,
):
    link = MagicMock()
    link.id = link_id or uuid.uuid4()
    link.node_id = node_id or (node.id if node is not None else uuid.uuid4())
    link.created_by = uuid.uuid4()
    link.token = "tok_" + uuid.uuid4().hex[:8]
    link.permission_type = PublicLinkPermissionType.DOWNLOAD
    link.status = status
    link.expires_at = None
    link.max_downloads = None
    link.download_count = 0
    link.view_count = 0
    link.upload_count = 0
    link.is_active = True
    link.revoked_at = None
    link.revoked_by = None
    link.revoke_reason = None
    link.last_accessed_at = None
    link.last_downloaded_at = None
    link.last_uploaded_at = None
    link.description = None
    link.created_at = datetime.now(UTC)
    link.password_hash = password_hash
    link.is_download_limit_reached = False
    link.is_revoked = status == PublicLinkStatus.REVOKED
    link.node = node
    link.can_view_at = MagicMock(return_value=can_view)
    link.can_download_at = MagicMock(return_value=can_download)
    return link


def make_file_mock(node_id=None, status=StorageObjectStatus.AVAILABLE, node=None):
    file = MagicMock()
    file.id = uuid.uuid4()
    file.node_id = node_id or uuid.uuid4()
    file.node = node
    file.size_bytes = 1024
    file.mime_type = "text/plain"
    file.storage_status = status
    file.storage_bucket = "files"
    file.storage_key = "key/file.txt"
    return file


def make_task_mock(task_id=None, status=BackgroundTaskStatus.PENDING, related_entity_id=None):
    task = MagicMock()
    task.id = task_id or uuid.uuid4()
    task.status = status
    task.related_entity_id = related_entity_id or uuid.uuid4()
    task.payload = None
    task.result_data = None
    return task


def make_access(node=None):
    svc = MagicMock()
    svc.get_accessible_node = AsyncMock(return_value=node or make_node_mock())
    svc.require_access = AsyncMock()
    return svc


def make_service(uow, access_svc=None, audit_svc=None, storage_svc=None):
    from core.config import get_settings

    return PublicLinksService(
        settings=get_settings(),
        uow_factory=make_factory(uow),
        access_service=access_svc or make_access(),
        audit_service=audit_svc or make_audit(),
        storage_service=storage_svc or make_storage(),
    )


# ---------------------------------------------------------------------------
# Тесты: create_link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_link_success_with_password():
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)
    link = make_link_mock(node=node, node_id=node.id)

    links_repo = AsyncMock()
    links_repo.token_exists = AsyncMock(return_value=False)
    links_repo.create_link = AsyncMock(return_value=link)

    access = make_access(node=node)
    audit = make_audit()
    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=access, audit_svc=audit)

    data = PublicLinkCreateRequest(node_id=node.id, password="secret")
    result = await service.create_link(data, actor_id=actor_id)

    assert str(result.id) == str(link.id)
    links_repo.create_link.assert_awaited_once()
    # пароль был захеширован (не None) и передан в репозиторий
    assert links_repo.create_link.await_args.kwargs["password_hash"] is not None
    uow.commit.assert_awaited_once()
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_link_success_no_password():
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FOLDER)
    link = make_link_mock(node=node, node_id=node.id)

    links_repo = AsyncMock()
    links_repo.token_exists = AsyncMock(return_value=False)
    links_repo.create_link = AsyncMock(return_value=link)

    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=make_access(node=node))

    data = PublicLinkCreateRequest(node_id=node.id)
    result = await service.create_link(data, actor_id=actor_id)

    assert result.node_id == node.id
    assert links_repo.create_link.await_args.kwargs["password_hash"] is None


@pytest.mark.asyncio
async def test_create_link_unsupported_node_type_raises_validation():
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.SHORTCUT) if hasattr(
        NodeType, "SHORTCUT"
    ) else make_node_mock()
    # явно подставляем неподдерживаемый тип
    node.node_type = MagicMock()
    node.node_type.value = "weird"

    uow = make_uow(links=AsyncMock())
    service = make_service(uow, access_svc=make_access(node=node))

    data = PublicLinkCreateRequest(node_id=node.id)
    with pytest.raises(ValidationServiceError):
        await service.create_link(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_create_link_permission_denied():
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    access = MagicMock()
    access.get_accessible_node = AsyncMock(
        side_effect=PermissionServiceError("denied", action="share")
    )
    uow = make_uow(links=AsyncMock())
    service = make_service(uow, access_svc=access)

    data = PublicLinkCreateRequest(node_id=node_id)
    with pytest.raises(PermissionServiceError):
        await service.create_link(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_create_link_token_generation_failed():
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)

    links_repo = AsyncMock()
    links_repo.token_exists = AsyncMock(return_value=True)  # всегда существует -> исчерпание

    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=make_access(node=node))

    data = PublicLinkCreateRequest(node_id=node.id)
    with pytest.raises(PublicLinkServiceError):
        await service.create_link(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_create_link_database_error_wrapped():
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)

    links_repo = AsyncMock()
    links_repo.token_exists = AsyncMock(return_value=False)
    links_repo.create_link = AsyncMock(side_effect=DatabaseError("boom"))

    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=make_access(node=node))

    data = PublicLinkCreateRequest(node_id=node.id)
    with pytest.raises(ServiceError):
        await service.create_link(data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_create_link_unexpected_error_wrapped():
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)

    links_repo = AsyncMock()
    links_repo.token_exists = AsyncMock(return_value=False)
    links_repo.create_link = AsyncMock(side_effect=RuntimeError("kaboom"))

    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=make_access(node=node))

    data = PublicLinkCreateRequest(node_id=node.id)
    with pytest.raises(ServiceError):
        await service.create_link(data, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: get_link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_link_success():
    actor_id = uuid.uuid4()
    link = make_link_mock()

    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    access = make_access()
    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=access)

    result = await service.get_link(link.id, actor_id=actor_id)
    assert str(result.id) == str(link.id)
    access.require_access.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_link_permission_denied():
    actor_id = uuid.uuid4()
    link = make_link_mock()

    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("nope", action="share")
    )
    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.get_link(link.id, actor_id=actor_id)


@pytest.mark.asyncio
async def test_get_link_database_error_wrapped():
    actor_id = uuid.uuid4()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("missing"))
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_link(uuid.uuid4(), actor_id=actor_id)


@pytest.mark.asyncio
async def test_get_link_unexpected_error_wrapped():
    actor_id = uuid.uuid4()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_link(uuid.uuid4(), actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: list_links
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_links_by_node():
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    link = make_link_mock(node_id=node_id)

    links_repo = AsyncMock()
    links_repo.list_node_links = AsyncMock(return_value=[link])
    links_repo.count_node_links = AsyncMock(return_value=1)

    access = make_access()
    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=access)

    params = PublicLinkQueryParams(node_id=node_id, limit=50, offset=0)
    result = await service.list_links(params, actor_id=actor_id)

    assert result.meta.total == 1
    assert result.meta.count == 1
    access.require_access.assert_awaited_once()
    links_repo.list_node_links.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_links_by_user_with_password_filter():
    actor_id = uuid.uuid4()
    link_with = make_link_mock(password_hash="h")
    link_without = make_link_mock(password_hash=None)

    links_repo = AsyncMock()
    links_repo.search_links = AsyncMock(return_value=[link_with, link_without])
    links_repo.count_user_links = AsyncMock(return_value=2)

    uow = make_uow(links=links_repo)
    service = make_service(uow)

    params = PublicLinkQueryParams(limit=50, offset=0, has_password=True)
    result = await service.list_links(params, actor_id=actor_id)

    # только защищённая паролем ссылка проходит фильтр
    assert result.meta.count == 1
    assert result.meta.total == 2
    links_repo.search_links.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_links_limit_normalized_and_negative_offset():
    actor_id = uuid.uuid4()
    links_repo = AsyncMock()
    links_repo.search_links = AsyncMock(return_value=[])
    links_repo.count_user_links = AsyncMock(return_value=0)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    # sort_by неизвестен -> нормализуется в created_at; limit проходит через _limit
    params = PublicLinkQueryParams(limit=100, offset=0, sort_by="unknown_field")
    result = await service.list_links(params, actor_id=actor_id)

    assert result.meta.limit == 100
    assert result.meta.offset == 0
    assert links_repo.search_links.await_args.kwargs["sort_by"] == "created_at"


@pytest.mark.asyncio
async def test_list_links_database_error_wrapped():
    actor_id = uuid.uuid4()
    links_repo = AsyncMock()
    links_repo.search_links = AsyncMock(side_effect=DatabaseError("db"))
    links_repo.count_user_links = AsyncMock(return_value=0)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    params = PublicLinkQueryParams(limit=10, offset=0)
    with pytest.raises(ServiceError):
        await service.list_links(params, actor_id=actor_id)


@pytest.mark.asyncio
async def test_list_links_permission_denied():
    actor_id = uuid.uuid4()
    node_id = uuid.uuid4()
    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", action="share")
    )
    uow = make_uow(links=AsyncMock())
    service = make_service(uow, access_svc=access)

    params = PublicLinkQueryParams(node_id=node_id, limit=10, offset=0)
    with pytest.raises(PermissionServiceError):
        await service.list_links(params, actor_id=actor_id)


@pytest.mark.asyncio
async def test_list_links_unexpected_error_wrapped():
    actor_id = uuid.uuid4()
    links_repo = AsyncMock()
    links_repo.search_links = AsyncMock(side_effect=RuntimeError("boom"))
    links_repo.count_user_links = AsyncMock(return_value=0)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    params = PublicLinkQueryParams(limit=10, offset=0)
    with pytest.raises(ServiceError):
        await service.list_links(params, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: update_link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_link_success_with_password():
    actor_id = uuid.uuid4()
    link = make_link_mock()
    updated = make_link_mock(link_id=link.id)

    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    links_repo.update_link = AsyncMock(return_value=updated)

    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkUpdateRequest(password="newpass", description="updated")
    result = await service.update_link(link.id, data, actor_id=actor_id)

    assert str(result.id) == str(updated.id)
    assert links_repo.update_link.await_args.kwargs["password_hash"] is not None
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_link_clear_password():
    actor_id = uuid.uuid4()
    link = make_link_mock()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    links_repo.update_link = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkUpdateRequest(clear_password=True)
    await service.update_link(link.id, data, actor_id=actor_id)

    assert links_repo.update_link.await_args.kwargs["password_hash"] is None


@pytest.mark.asyncio
async def test_update_link_unset_fields_are_omitted():
    actor_id = uuid.uuid4()

    link = make_link_mock()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    links_repo.update_link = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkUpdateRequest(status=PublicLinkStatus.DISABLED)
    await service.update_link(link.id, data, actor_id=actor_id)

    kwargs = links_repo.update_link.await_args.kwargs
    # Неустановленные поля НЕ пробрасываются в репозиторий: иначе чужой sentinel
    # _UNSET сервиса ломал бы частичное обновление. Репозиторий применит свой.
    assert "password_hash" not in kwargs
    assert "expires_at" not in kwargs
    assert "max_downloads" not in kwargs
    assert "description" not in kwargs
    assert kwargs["status"] == PublicLinkStatus.DISABLED


@pytest.mark.asyncio
async def test_update_link_explicit_field_values_passed():
    actor_id = uuid.uuid4()
    expires = datetime.now(UTC) + timedelta(days=1)
    link = make_link_mock()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    links_repo.update_link = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkUpdateRequest(
        expires_at=expires, max_downloads=5, description="d"
    )
    await service.update_link(link.id, data, actor_id=actor_id)

    kwargs = links_repo.update_link.await_args.kwargs
    assert kwargs["expires_at"] == expires
    assert kwargs["max_downloads"] == 5
    assert kwargs["description"] == "d"


@pytest.mark.asyncio
async def test_update_link_permission_denied():
    actor_id = uuid.uuid4()
    link = make_link_mock()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", action="share")
    )
    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=access)

    data = PublicLinkUpdateRequest(is_active=False)
    with pytest.raises(PermissionServiceError):
        await service.update_link(link.id, data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_update_link_database_error_wrapped():
    actor_id = uuid.uuid4()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("nope"))
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkUpdateRequest(is_active=False)
    with pytest.raises(ServiceError):
        await service.update_link(uuid.uuid4(), data, actor_id=actor_id)


@pytest.mark.asyncio
async def test_update_link_unexpected_error_wrapped():
    actor_id = uuid.uuid4()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkUpdateRequest(is_active=False)
    with pytest.raises(ServiceError):
        await service.update_link(uuid.uuid4(), data, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: revoke_link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_link_success_with_reason():
    actor_id = uuid.uuid4()
    link = make_link_mock()
    revoked = make_link_mock(link_id=link.id, status=PublicLinkStatus.REVOKED)

    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    links_repo.revoke_link = AsyncMock(return_value=revoked)

    audit = make_audit()
    uow = make_uow(links=links_repo)
    service = make_service(uow, audit_svc=audit)

    data = PublicLinkRevokeRequest(revoke_reason="spam")
    result = await service.revoke_link(link.id, data, actor_id=actor_id)

    assert str(result.id) == str(revoked.id)
    assert links_repo.revoke_link.await_args.kwargs["reason"] == "spam"
    uow.commit.assert_awaited_once()
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_revoke_link_success_no_data():
    actor_id = uuid.uuid4()
    link = make_link_mock()
    revoked = make_link_mock(link_id=link.id, status=PublicLinkStatus.REVOKED)

    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    links_repo.revoke_link = AsyncMock(return_value=revoked)

    uow = make_uow(links=links_repo)
    service = make_service(uow)

    result = await service.revoke_link(link.id, None, actor_id=actor_id)
    assert str(result.id) == str(revoked.id)
    assert links_repo.revoke_link.await_args.kwargs["reason"] is None


@pytest.mark.asyncio
async def test_revoke_link_permission_denied():
    actor_id = uuid.uuid4()
    link = make_link_mock()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    access = MagicMock()
    access.require_access = AsyncMock(
        side_effect=PermissionServiceError("denied", action="share")
    )
    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=access)

    with pytest.raises(PermissionServiceError):
        await service.revoke_link(link.id, None, actor_id=actor_id)


@pytest.mark.asyncio
async def test_revoke_link_database_error_wrapped():
    actor_id = uuid.uuid4()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(side_effect=DatabaseError("x"))
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.revoke_link(uuid.uuid4(), None, actor_id=actor_id)


@pytest.mark.asyncio
async def test_revoke_link_unexpected_error_wrapped():
    actor_id = uuid.uuid4()
    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(side_effect=RuntimeError("x"))
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.revoke_link(uuid.uuid4(), None, actor_id=actor_id)


# ---------------------------------------------------------------------------
# Тесты: validate_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_access_success_no_password():
    node = make_node_mock()
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    links_repo.register_view = AsyncMock()

    audit = make_audit()
    uow = make_uow(links=links_repo)
    service = make_service(uow, audit_svc=audit)

    data = PublicLinkAccessRequest(token="tok")
    result = await service.validate_access(data)

    assert result.allowed is True
    assert result.link is not None
    links_repo.register_view.assert_awaited_once()
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_access_password_required_missing():
    link = make_link_mock(password_hash=hash_password("secret"))
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    result = await service.validate_access(data)

    assert result.allowed is False
    assert result.requires_password is True
    assert result.message == "Требуется пароль."


@pytest.mark.asyncio
async def test_validate_access_wrong_password_logs_security_failure():
    link = make_link_mock(password_hash=hash_password("secret"))
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    audit = make_audit()
    uow = make_uow(links=links_repo)
    service = make_service(uow, audit_svc=audit)

    data = PublicLinkAccessRequest(token="tok", password="wrong")
    result = await service.validate_access(data)

    assert result.allowed is False
    assert result.requires_password is True
    assert result.message == "Неверный пароль."
    audit.log_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_access_correct_password_succeeds():
    node = make_node_mock()
    link = make_link_mock(
        node=node, node_id=node.id, password_hash=hash_password("secret")
    )
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    links_repo.register_view = AsyncMock()
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok", password="secret")
    result = await service.validate_access(data)

    assert result.allowed is True
    links_repo.register_view.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_access_not_viewable_raises():
    link = make_link_mock(can_view=False)
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(PublicLinkServiceError):
        await service.validate_access(data)


@pytest.mark.asyncio
async def test_validate_access_database_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=DatabaseError("db")
    )
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(ServiceError):
        await service.validate_access(data)


@pytest.mark.asyncio
async def test_validate_access_unexpected_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=RuntimeError("x")
    )
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(ServiceError):
        await service.validate_access(data)


# ---------------------------------------------------------------------------
# Тесты: get_public_link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_public_link_success():
    node = make_node_mock()
    link = make_link_mock(node=node, node_id=node.id)
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    result = await service.get_public_link("tok")
    assert result.node_id == node.id


@pytest.mark.asyncio
async def test_get_public_link_not_viewable_raises():
    link = make_link_mock(can_view=False)
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    with pytest.raises(PublicLinkServiceError):
        await service.get_public_link("tok")


@pytest.mark.asyncio
async def test_get_public_link_database_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=DatabaseError("db")
    )
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_public_link("tok")


@pytest.mark.asyncio
async def test_get_public_link_unexpected_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=RuntimeError("x")
    )
    uow = make_uow(links=links_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_public_link("tok")


# ---------------------------------------------------------------------------
# Тесты: create_public_download_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_public_download_url_success():
    node = make_node_mock(node_type=NodeType.FILE, name="doc.pdf")
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)
    file = make_file_mock(node_id=node.id, node=node)

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    links_repo.register_download = AsyncMock()
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    storage = make_storage()
    audit = make_audit()
    uow = make_uow(links=links_repo, nodes=nodes_repo, files=files_repo)
    service = make_service(uow, storage_svc=storage, audit_svc=audit)

    data = PublicLinkAccessRequest(token="tok")
    result = await service.create_public_download_url(data)

    assert result.presigned_url == "https://example.com/file"
    assert result.filename == "doc.pdf"
    assert result.size_bytes == 1024
    storage.create_download_url.assert_awaited_once()
    links_repo.register_download.assert_awaited_once()
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_public_download_url_uses_explicit_presigned_expiry():
    node = make_node_mock(node_type=NodeType.FILE)
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)
    file = make_file_mock(node_id=node.id, node=node)

    explicit_expiry = datetime.now(UTC) + timedelta(hours=2)
    presigned = make_presigned_url_result()
    presigned.expires_at = explicit_expiry
    storage = make_storage()
    storage.create_download_url = AsyncMock(return_value=presigned)

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    links_repo.register_download = AsyncMock()
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)

    uow = make_uow(links=links_repo, nodes=nodes_repo, files=files_repo)
    service = make_service(uow, storage_svc=storage)

    data = PublicLinkAccessRequest(token="tok")
    result = await service.create_public_download_url(data)

    assert result.expires_at == explicit_expiry.astimezone(UTC)


@pytest.mark.asyncio
async def test_create_public_download_url_not_downloadable_raises():
    link = make_link_mock(can_download=False)
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo, nodes=AsyncMock(), files=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(PublicLinkServiceError):
        await service.create_public_download_url(data)


@pytest.mark.asyncio
async def test_create_public_download_url_missing_password_raises_permission():
    link = make_link_mock(password_hash=hash_password("secret"))
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo, nodes=AsyncMock(), files=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(PermissionServiceError):
        await service.create_public_download_url(data)


@pytest.mark.asyncio
async def test_create_public_download_url_wrong_password_raises_permission():
    link = make_link_mock(password_hash=hash_password("secret"))
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo, nodes=AsyncMock(), files=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok", password="wrong")
    with pytest.raises(PermissionServiceError):
        await service.create_public_download_url(data)


@pytest.mark.asyncio
async def test_create_public_download_url_folder_raises_validation():
    node = make_node_mock(node_type=NodeType.FOLDER)
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    uow = make_uow(links=links_repo, nodes=nodes_repo, files=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(ValidationServiceError):
        await service.create_public_download_url(data)


@pytest.mark.asyncio
async def test_create_public_download_url_file_unavailable_raises():
    node = make_node_mock(node_type=NodeType.FILE)
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)
    file = make_file_mock(
        node_id=node.id, node=node, status=StorageObjectStatus.PENDING
    )
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)
    uow = make_uow(links=links_repo, nodes=nodes_repo, files=files_repo)
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(PublicLinkServiceError):
        await service.create_public_download_url(data)


@pytest.mark.asyncio
async def test_create_public_download_url_deleted_node_raises():
    node = make_node_mock(node_type=NodeType.FILE)
    deleted_node = make_node_mock(node_type=NodeType.FILE)
    deleted_node.is_deleted = True
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)
    file = make_file_mock(node_id=node.id, node=deleted_node)
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)
    uow = make_uow(links=links_repo, nodes=nodes_repo, files=files_repo)
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(PublicLinkServiceError):
        await service.create_public_download_url(data)


@pytest.mark.asyncio
async def test_create_public_download_url_storage_error_wrapped():
    node = make_node_mock(node_type=NodeType.FILE)
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)
    file = make_file_mock(node_id=node.id, node=node)
    storage = make_storage()
    storage.create_download_url = AsyncMock(side_effect=StorageError("down"))

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)
    uow = make_uow(links=links_repo, nodes=nodes_repo, files=files_repo)
    service = make_service(uow, storage_svc=storage)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(ServiceError):
        await service.create_public_download_url(data)


@pytest.mark.asyncio
async def test_create_public_download_url_database_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=DatabaseError("db")
    )
    uow = make_uow(links=links_repo, nodes=AsyncMock(), files=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(ServiceError):
        await service.create_public_download_url(data)


@pytest.mark.asyncio
async def test_create_public_download_url_unexpected_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=RuntimeError("x")
    )
    uow = make_uow(links=links_repo, nodes=AsyncMock(), files=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(ServiceError):
        await service.create_public_download_url(data)


# ---------------------------------------------------------------------------
# Тесты: create_public_folder_archive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_public_folder_archive_success():
    node = make_node_mock(node_type=NodeType.FOLDER, name="myfolder")
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)
    task = make_task_mock(status=BackgroundTaskStatus.PENDING)
    updated_task = make_task_mock(task_id=task.id, status=BackgroundTaskStatus.PENDING)

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    tasks_repo = AsyncMock()
    tasks_repo.create_user_task = AsyncMock(return_value=task)
    tasks_repo.update = AsyncMock(return_value=updated_task)

    storage = make_storage()
    uow = make_uow(links=links_repo, nodes=nodes_repo, tasks=tasks_repo)
    service = make_service(uow, storage_svc=storage)

    data = PublicLinkAccessRequest(token="tok")
    result = await service.create_public_folder_archive(data)

    assert result.task_id == updated_task.id
    assert result.status == BackgroundTaskStatus.PENDING
    tasks_repo.create_user_task.assert_awaited_once()
    assert tasks_repo.create_user_task.await_args.kwargs["created_by"] == node.owner_id
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_public_folder_archive_not_folder_raises_validation():
    node = make_node_mock(node_type=NodeType.FILE)
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    uow = make_uow(links=links_repo, nodes=nodes_repo, tasks=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(ValidationServiceError):
        await service.create_public_folder_archive(data)


@pytest.mark.asyncio
async def test_create_public_folder_archive_not_downloadable_raises():
    link = make_link_mock(can_download=False)
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo, nodes=AsyncMock(), tasks=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(PublicLinkServiceError):
        await service.create_public_folder_archive(data)


@pytest.mark.asyncio
async def test_create_public_folder_archive_wrong_password_raises():
    link = make_link_mock(password_hash=hash_password("secret"))
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    uow = make_uow(links=links_repo, nodes=AsyncMock(), tasks=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok", password="wrong")
    with pytest.raises(PermissionServiceError):
        await service.create_public_folder_archive(data)


@pytest.mark.asyncio
async def test_create_public_folder_archive_database_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=DatabaseError("db")
    )
    uow = make_uow(links=links_repo, nodes=AsyncMock(), tasks=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(ServiceError):
        await service.create_public_folder_archive(data)


@pytest.mark.asyncio
async def test_create_public_folder_archive_unexpected_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=RuntimeError("x")
    )
    uow = make_uow(links=links_repo, nodes=AsyncMock(), tasks=AsyncMock())
    service = make_service(uow)

    data = PublicLinkAccessRequest(token="tok")
    with pytest.raises(ServiceError):
        await service.create_public_folder_archive(data)


# ---------------------------------------------------------------------------
# Тесты: get_public_folder_archive_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_archive_status_not_completed_returns_status_only():
    node_id = uuid.uuid4()
    link = make_link_mock(node_id=node_id)
    task = make_task_mock(
        status=BackgroundTaskStatus.RUNNING, related_entity_id=node_id
    )

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    uow = make_uow(links=links_repo, tasks=tasks_repo)
    service = make_service(uow)

    result = await service.get_public_folder_archive_status("tok", task.id)
    assert result.status == BackgroundTaskStatus.RUNNING
    assert result.presigned_url is None


@pytest.mark.asyncio
async def test_get_archive_status_completed_returns_presigned():
    node_id = uuid.uuid4()
    link = make_link_mock(node_id=node_id)
    task = make_task_mock(
        status=BackgroundTaskStatus.COMPLETED, related_entity_id=node_id
    )
    task.payload = {"archive_name": "myfolder.zip"}
    task.result_data = {
        "archive_bucket": "archives",
        "archive_key": "k.zip",
        "archive_size_bytes": 2048,
    }

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    storage = make_storage()
    uow = make_uow(links=links_repo, tasks=tasks_repo)
    service = make_service(uow, storage_svc=storage)

    result = await service.get_public_folder_archive_status("tok", task.id)
    assert result.status == BackgroundTaskStatus.COMPLETED
    assert result.presigned_url == "https://example.com/file"
    assert result.filename == "myfolder.zip"
    assert result.size_bytes == 2048
    storage.create_download_url.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_archive_status_completed_uses_fallback_fields():
    node_id = uuid.uuid4()
    link = make_link_mock(node_id=node_id)
    task = make_task_mock(
        status=BackgroundTaskStatus.COMPLETED, related_entity_id=node_id
    )
    # нет payload, откат к ключам storage_* из result_data и имени архива по умолчанию
    task.payload = None
    task.result_data = {
        "storage_bucket": "archives",
        "storage_key": "fb.zip",
        "size_bytes": 99,
    }

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    storage = make_storage()
    uow = make_uow(links=links_repo, tasks=tasks_repo)
    service = make_service(uow, storage_svc=storage)

    result = await service.get_public_folder_archive_status("tok", task.id)
    assert result.size_bytes == 99
    assert result.filename == f"archive-{task.id}.zip"


@pytest.mark.asyncio
async def test_get_archive_status_task_node_mismatch_raises():
    link = make_link_mock(node_id=uuid.uuid4())
    task = make_task_mock(related_entity_id=uuid.uuid4())  # другой узел

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    uow = make_uow(links=links_repo, tasks=tasks_repo)
    service = make_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.get_public_folder_archive_status("tok", task.id)


@pytest.mark.asyncio
async def test_get_archive_status_storage_error_wrapped():
    node_id = uuid.uuid4()
    link = make_link_mock(node_id=node_id)
    task = make_task_mock(
        status=BackgroundTaskStatus.COMPLETED, related_entity_id=node_id
    )
    task.payload = {"archive_name": "a.zip"}
    task.result_data = {"archive_bucket": "b", "archive_key": "k"}
    storage = make_storage()
    storage.create_download_url = AsyncMock(side_effect=StorageError("down"))

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    tasks_repo = AsyncMock()
    tasks_repo.get_required_by_id = AsyncMock(return_value=task)
    uow = make_uow(links=links_repo, tasks=tasks_repo)
    service = make_service(uow, storage_svc=storage)

    with pytest.raises(ServiceError):
        await service.get_public_folder_archive_status("tok", task.id)


@pytest.mark.asyncio
async def test_get_archive_status_database_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=DatabaseError("db")
    )
    uow = make_uow(links=links_repo, tasks=AsyncMock())
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_public_folder_archive_status("tok", uuid.uuid4())


@pytest.mark.asyncio
async def test_get_archive_status_unexpected_error_wrapped():
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(
        side_effect=RuntimeError("x")
    )
    uow = make_uow(links=links_repo, tasks=AsyncMock())
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_public_folder_archive_status("tok", uuid.uuid4())


# ---------------------------------------------------------------------------
# Тесты: audit logging is failure-safe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_log_event_swallows_audit_errors():
    actor_id = uuid.uuid4()
    node = make_node_mock(node_type=NodeType.FILE)
    link = make_link_mock(node=node, node_id=node.id)

    links_repo = AsyncMock()
    links_repo.token_exists = AsyncMock(return_value=False)
    links_repo.create_link = AsyncMock(return_value=link)

    audit = make_audit()
    audit.log_success = AsyncMock(side_effect=RuntimeError("audit down"))
    uow = make_uow(links=links_repo)
    service = make_service(uow, access_svc=make_access(node=node), audit_svc=audit)

    data = PublicLinkCreateRequest(node_id=node.id)
    # сбой аудита НЕ должен пробрасываться
    result = await service.create_link(data, actor_id=actor_id)
    assert str(result.id) == str(link.id)


@pytest.mark.asyncio
async def test_safe_log_security_failure_swallows_audit_errors():
    link = make_link_mock(password_hash=hash_password("secret"))
    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    audit = make_audit()
    audit.log_event = AsyncMock(side_effect=RuntimeError("audit down"))
    uow = make_uow(links=links_repo)
    service = make_service(uow, audit_svc=audit)

    data = PublicLinkAccessRequest(token="tok", password="wrong")
    # сбой аудита НЕ должен пробрасываться; всё равно возвращает ответ о неверном пароле
    result = await service.validate_access(data)
    assert result.allowed is False


@pytest.mark.asyncio
async def test_create_link_with_metadata_in_revoke_audit():
    actor_id = uuid.uuid4()
    link = make_link_mock()
    revoked = make_link_mock(link_id=link.id, status=PublicLinkStatus.REVOKED)

    links_repo = AsyncMock()
    links_repo.get_required_by_id = AsyncMock(return_value=link)
    links_repo.revoke_link = AsyncMock(return_value=revoked)
    audit = make_audit()
    uow = make_uow(links=links_repo)
    service = make_service(uow, audit_svc=audit)

    data = PublicLinkRevokeRequest(revoke_reason="abuse")
    await service.revoke_link(link.id, data, actor_id=actor_id)

    # метаданные включают revoke_reason в полезной нагрузке аудита
    call_kwargs = audit.log_success.await_args.kwargs
    assert call_kwargs["metadata"]["revoke_reason"] == "abuse"


# ---------------------------------------------------------------------------
# Тесты: factory
# ---------------------------------------------------------------------------


def test_get_public_links_service_with_deps_creates_new_instance():
    from services.public_links import get_public_links_service

    uow = make_uow(links=AsyncMock())
    svc = get_public_links_service(
        uow_factory=make_factory(uow),
        access_service=make_access(),
        audit_service=make_audit(),
        storage_service=make_storage(),
    )
    assert isinstance(svc, PublicLinksService)


def test_get_public_links_service_singleton(monkeypatch):
    import services.public_links as mod

    # сбрасываем синглтон модуля, чтобы ветка без зависимостей собрала новый экземпляр
    monkeypatch.setattr(mod, "_public_links_service", None)
    # избегаем обращения к реальному config/storage, подменяя конструктор
    monkeypatch.setattr(
        mod, "PublicLinksService", lambda: MagicMock(spec=PublicLinksService)
    )
    first = mod.get_public_links_service()
    second = mod.get_public_links_service()
    assert first is second


# ---------------------------------------------------------------------------
# Тесты: module-level helpers
# ---------------------------------------------------------------------------


def test_normalize_sort_by_known_and_unknown():
    from services.public_links import _normalize_sort_by

    assert _normalize_sort_by("  DOWNLOAD_COUNT ") == "download_count"
    assert _normalize_sort_by("bogus") == "created_at"


def test_normalize_datetime_naive_and_aware():
    from datetime import timezone

    from services.public_links import _normalize_datetime

    naive = datetime(2024, 1, 1, 12, 0, 0)
    assert _normalize_datetime(naive).tzinfo == UTC

    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=3)))
    normalized = _normalize_datetime(aware)
    assert normalized.tzinfo == UTC
    assert normalized.hour == 9


def test_expires_at_without_explicit_value_uses_seconds():
    from services.public_links import _expires_at

    before = datetime.now(UTC)
    result = _expires_at(None, 60)
    assert result >= before + timedelta(seconds=59)


def test_jsonable_handles_various_types():
    from enum import Enum

    from services.public_links import _jsonable

    class Color(Enum):
        RED = "red"

    uid = uuid.uuid4()
    dt = datetime(2024, 1, 1, tzinfo=UTC)
    assert _jsonable(uid) == str(uid)
    assert _jsonable(dt) == dt.isoformat()
    assert _jsonable(Color.RED) == "red"
    assert _jsonable({"a": 1}) == {"a": 1}
    assert _jsonable([1, 2]) == [1, 2]
    assert _jsonable(None) is None
    assert _jsonable("x") == "x"
    # откат к str() для неподдерживаемых объектов
    obj = object()
    assert _jsonable(obj) == str(obj)


def test_limit_clamps_low_and_high():
    from services.public_links import MAX_PAGE_LIMIT, _limit

    assert _limit(0) == 1
    assert _limit(-5) == 1
    assert _limit(50) == 50
    assert _limit(MAX_PAGE_LIMIT + 100) == MAX_PAGE_LIMIT


def test_empty_result_error_factory():
    from services.public_links import _empty_result_error

    err = _empty_result_error("op")
    assert isinstance(err, ServiceError)
    assert err.operation == "op"


def test_include_by_password_filter_dead_helper():
    from services.public_links import _include_by_password_filter

    link_with = make_link_mock(password_hash="h")
    link_without = make_link_mock(password_hash=None)
    assert _include_by_password_filter(link_with, None) is True
    assert _include_by_password_filter(link_with, True) is True
    assert _include_by_password_filter(link_without, True) is False


@pytest.mark.asyncio
async def test_create_public_download_url_naive_presigned_expiry():
    node = make_node_mock(node_type=NodeType.FILE)
    link = make_link_mock(node=node, node_id=node.id, password_hash=None)
    file = make_file_mock(node_id=node.id, node=node)

    presigned = make_presigned_url_result()
    presigned.expires_at = datetime(2030, 1, 1, 0, 0, 0)  # наивный
    storage = make_storage()
    storage.create_download_url = AsyncMock(return_value=presigned)

    links_repo = AsyncMock()
    links_repo.get_required_available_link_by_token = AsyncMock(return_value=link)
    links_repo.register_download = AsyncMock()
    nodes_repo = AsyncMock()
    nodes_repo.get_required_by_id = AsyncMock(return_value=node)
    files_repo = AsyncMock()
    files_repo.get_required_by_node_id = AsyncMock(return_value=file)
    uow = make_uow(links=links_repo, nodes=nodes_repo, files=files_repo)
    service = make_service(uow, storage_svc=storage)

    data = PublicLinkAccessRequest(token="tok")
    result = await service.create_public_download_url(data)
    assert result.expires_at.tzinfo == UTC
