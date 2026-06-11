"""Юнит-тесты для UploadsService."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from database.exceptions import DatabaseError, EntityNotFoundError
from database.models.enums import (
    NodeType,
    UploadPartStatus,
    UploadSessionStatus,
)
from schemas.uploads import (
    UploadAbortRequest,
    UploadCompleteRequest,
    UploadPartCompleteRequest,
    UploadQueryParams,
    UploadSessionCreateRequest,
)
from services.exceptions import (
    ConflictServiceError,
    PermissionServiceError,
    ServiceError,
    UploadServiceError,
    ValidationServiceError,
)
from services.uploads import UploadsService, get_uploads_service
from storage.exceptions import StorageError
from storage.types import StoragePresignedUrl, StoragePresignedUrlMethod


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def make_uow(**repos):
    uow = AsyncMock()
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()
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
    return svc


def make_access(node=None):
    svc = MagicMock()
    svc.get_accessible_node = AsyncMock(return_value=node or make_folder_node())
    svc.require_access = AsyncMock()
    return svc


def make_folder_node(node_id=None, owner_id=None, node_type=NodeType.FOLDER):
    node = MagicMock()
    node.id = node_id or uuid.uuid4()
    node.owner_id = owner_id or uuid.uuid4()
    node.node_type = node_type
    return node


def make_storage(
    *,
    multipart=None,
    part_urls=None,
):
    storage = MagicMock()
    storage.multipart_part_size_bytes = 5 * 1024 * 1024
    storage.default_files_bucket = "files"
    storage.presigned_upload_expire_seconds = 3600
    storage.ensure_storage_ready = AsyncMock()
    storage.init_multipart_upload = AsyncMock(
        return_value=multipart or make_multipart_upload()
    )
    storage.create_upload_part_urls = AsyncMock(
        return_value=part_urls if part_urls is not None else []
    )
    storage.complete_multipart_upload = AsyncMock()
    storage.abort_multipart_upload = AsyncMock()
    return storage


def make_multipart_upload(
    *,
    bucket="files",
    object_key="users/x/uploads/y/source",
    upload_id="upload-123",
    expires_at=None,
):
    mp = MagicMock()
    mp.bucket = bucket
    mp.object_key = object_key
    mp.upload_id = upload_id
    mp.expires_at = expires_at
    return mp


def make_part_url(part_number=1, expires_at=None):
    presigned = StoragePresignedUrl(
        url="https://minio.local/part",
        method=StoragePresignedUrlMethod.PUT,
        bucket="files",
        object_key="key",
        expires_in_seconds=3600,
        expires_at=expires_at,
        headers={},
    )
    wrap = MagicMock()
    wrap.part_number = part_number
    wrap.url = presigned
    return wrap


def make_session(
    *,
    session_id=None,
    user_id=None,
    parent_node_id=None,
    status=UploadSessionStatus.CREATED,
    parts_count=1,
    file_size_bytes=1024,
    part_size_bytes=1024,
    uploaded_parts_count=0,
    uploaded_bytes=0,
    expires_at=None,
    file_name="test.txt",
    mime_type="text/plain",
    storage_bucket="files",
    storage_key="users/x/uploads/y/source",
    upload_id="upload-123",
    checksum="abc",
    checksum_algorithm="sha256",
):
    session = MagicMock()
    session.id = session_id or uuid.uuid4()
    session.user_id = user_id or uuid.uuid4()
    session.parent_node_id = parent_node_id or uuid.uuid4()
    session.file_name = file_name
    session.file_size_bytes = file_size_bytes
    session.part_size_bytes = part_size_bytes
    session.mime_type = mime_type
    session.checksum = checksum
    session.checksum_algorithm = checksum_algorithm
    session.status = status
    session.parts_count = parts_count
    session.uploaded_parts_count = uploaded_parts_count
    session.uploaded_bytes = uploaded_bytes
    session.expires_at = expires_at or (datetime.now(UTC) + timedelta(hours=1))
    session.completed_at = None
    session.aborted_at = None
    session.failed_at = None
    session.failure_reason = None
    session.client_ip = None
    session.user_agent = None
    session.created_at = datetime.now(UTC)
    session.storage_bucket = storage_bucket
    session.storage_key = storage_key
    session.upload_id = upload_id
    return session


def make_part(
    *,
    part_id=None,
    session_id=None,
    part_number=1,
    size_bytes=1024,
    status=UploadPartStatus.PENDING,
    etag=None,
    checksum=None,
):
    part = MagicMock()
    part.id = part_id or uuid.uuid4()
    part.upload_session_id = session_id or uuid.uuid4()
    part.part_number = part_number
    part.size_bytes = size_bytes
    part.status = status
    part.etag = etag
    part.checksum = checksum
    part.uploaded_at = None
    part.failed_at = None
    part.failure_reason = None
    part.created_at = datetime.now(UTC)
    return part


def make_service(uow, *, storage=None, access=None, audit=None):
    return UploadsService(
        settings=MagicMock(),
        uow_factory=make_factory(uow),
        storage_service=storage or make_storage(),
        access_service=access or make_access(),
        audit_service=audit or make_audit(),
    )


def make_quotas(
    *,
    can_store=True,
    can_session=True,
    active_count=1,
):
    quotas = AsyncMock()
    quotas.can_store_file = AsyncMock(return_value=can_store)
    quotas.check_active_upload_sessions_limit_allowed = AsyncMock(
        return_value=can_session
    )
    quotas.count_user_active_upload_sessions = AsyncMock(return_value=active_count)
    quotas.set_active_upload_sessions_used = AsyncMock()
    quotas.increase_used_space = AsyncMock()
    quotas.increase_files_used = AsyncMock()
    quotas.decrease_active_upload_sessions_used = AsyncMock()
    return quotas


# ---------------------------------------------------------------------------
# initiate_upload
# ---------------------------------------------------------------------------


def make_initiate_request(
    *,
    parent_node_id=None,
    file_size_bytes=1024,
    parts_count=1,
    part_size_bytes=None,
):
    return UploadSessionCreateRequest(
        parent_node_id=parent_node_id or uuid.uuid4(),
        filename="test.txt",
        file_size_bytes=file_size_bytes,
        part_size_bytes=part_size_bytes,
        parts_count=parts_count,
        mime_type="text/plain",
        checksum="abc",
        checksum_algorithm="sha256",
    )


@pytest.mark.asyncio
async def test_initiate_upload_success():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    data = make_initiate_request(parent_node_id=parent_id, file_size_bytes=1024, parts_count=1)

    node = make_folder_node(node_id=parent_id, owner_id=user_id)
    access = make_access(node=node)

    session = make_session(
        user_id=user_id,
        parent_node_id=parent_id,
        parts_count=1,
        status=UploadSessionStatus.CREATED,
    )
    sessions_repo = AsyncMock()
    sessions_repo.create_session = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.create_parts_by_sizes = AsyncMock()
    quotas = make_quotas()

    storage = make_storage(part_urls=[make_part_url(part_number=1)])
    audit = make_audit()

    uow = make_uow(
        upload_sessions=sessions_repo,
        upload_parts=parts_repo,
        quotas=quotas,
    )
    service = make_service(uow, storage=storage, access=access, audit=audit)

    read, urls = await service.initiate_upload(
        data, user_id=user_id, client_ip="  ", user_agent="agent"
    )

    assert str(read.id) == str(session.id)
    assert urls.upload_session_id == session.id
    storage.ensure_storage_ready.assert_awaited_once()
    storage.init_multipart_upload.assert_awaited_once()
    sessions_repo.create_session.assert_awaited_once()
    # client_ip "  " нормализуется в None
    _, kwargs = sessions_repo.create_session.call_args
    assert kwargs["client_ip"] is None
    assert kwargs["user_agent"] == "agent"
    quotas.set_active_upload_sessions_used.assert_awaited_once()
    uow.commit.assert_awaited_once()
    # два события аудита
    assert audit.log_success.await_count == 2


@pytest.mark.asyncio
async def test_initiate_upload_not_folder_raises_validation():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    data = make_initiate_request(parent_node_id=parent_id)
    node = make_folder_node(node_id=parent_id, owner_id=user_id, node_type=NodeType.FILE)
    access = make_access(node=node)
    uow = make_uow(upload_sessions=AsyncMock(), upload_parts=AsyncMock(), quotas=make_quotas())
    storage = make_storage()
    service = make_service(uow, storage=storage, access=access)

    with pytest.raises(ValidationServiceError):
        await service.initiate_upload(data, user_id=user_id)
    # загрузка в хранилище не была инициализирована -> прерывать нечего
    storage.abort_multipart_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_initiate_upload_owner_mismatch_raises_permission():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    data = make_initiate_request(parent_node_id=parent_id)
    node = make_folder_node(node_id=parent_id, owner_id=uuid.uuid4())
    access = make_access(node=node)
    uow = make_uow(upload_sessions=AsyncMock(), upload_parts=AsyncMock(), quotas=make_quotas())
    service = make_service(uow, access=access)

    with pytest.raises(PermissionServiceError):
        await service.initiate_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_initiate_upload_quota_exceeded_raises_upload_error():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    data = make_initiate_request(parent_node_id=parent_id)
    node = make_folder_node(node_id=parent_id, owner_id=user_id)
    access = make_access(node=node)
    quotas = make_quotas(can_store=False)
    uow = make_uow(upload_sessions=AsyncMock(), upload_parts=AsyncMock(), quotas=quotas)
    service = make_service(uow, access=access)

    with pytest.raises(UploadServiceError):
        await service.initiate_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_initiate_upload_session_quota_exceeded_raises_upload_error():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    data = make_initiate_request(parent_node_id=parent_id)
    node = make_folder_node(node_id=parent_id, owner_id=user_id)
    access = make_access(node=node)
    quotas = make_quotas(can_session=False)
    uow = make_uow(upload_sessions=AsyncMock(), upload_parts=AsyncMock(), quotas=quotas)
    service = make_service(uow, access=access)

    with pytest.raises(UploadServiceError):
        await service.initiate_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_initiate_upload_invalid_file_size_raises_validation():
    # _build_part_sizes вызывается до try-блока; несоответствие parts_count
    user_id = uuid.uuid4()
    data = make_initiate_request(file_size_bytes=10, parts_count=5, part_size_bytes=10)
    uow = make_uow(upload_sessions=AsyncMock(), upload_parts=AsyncMock(), quotas=make_quotas())
    service = make_service(uow)
    with pytest.raises(ValidationServiceError):
        await service.initiate_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_initiate_upload_storage_error_wrapped():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    data = make_initiate_request(parent_node_id=parent_id)
    storage = make_storage()
    storage.ensure_storage_ready = AsyncMock(side_effect=StorageError("boom"))
    uow = make_uow(upload_sessions=AsyncMock(), upload_parts=AsyncMock(), quotas=make_quotas())
    service = make_service(uow, storage=storage)

    with pytest.raises(ServiceError):
        await service.initiate_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_initiate_upload_database_error_aborts_storage():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    data = make_initiate_request(parent_node_id=parent_id)
    node = make_folder_node(node_id=parent_id, owner_id=user_id)
    access = make_access(node=node)
    sessions_repo = AsyncMock()
    sessions_repo.create_session = AsyncMock(side_effect=DatabaseError("db"))
    quotas = make_quotas()
    storage = make_storage()
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=AsyncMock(), quotas=quotas)
    service = make_service(uow, storage=storage, access=access)

    with pytest.raises(ServiceError):
        await service.initiate_upload(data, user_id=user_id)
    # multipart хранилища был инициализирован, затем прерван при ошибке БД
    storage.abort_multipart_upload.assert_awaited()


@pytest.mark.asyncio
async def test_initiate_upload_unexpected_error_aborts_storage():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    data = make_initiate_request(parent_node_id=parent_id)
    node = make_folder_node(node_id=parent_id, owner_id=user_id)
    access = make_access(node=node)
    sessions_repo = AsyncMock()
    sessions_repo.create_session = AsyncMock(side_effect=RuntimeError("oops"))
    quotas = make_quotas()
    storage = make_storage()
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=AsyncMock(), quotas=quotas)
    service = make_service(uow, storage=storage, access=access)

    with pytest.raises(ServiceError):
        await service.initiate_upload(data, user_id=user_id)
    storage.abort_multipart_upload.assert_awaited()


@pytest.mark.asyncio
async def test_abort_storage_upload_safely_swallows_errors():
    storage = make_storage()
    storage.abort_multipart_upload = AsyncMock(side_effect=RuntimeError("nope"))
    uow = make_uow()
    service = make_service(uow, storage=storage)
    # Не должно бросать исключение
    await service._abort_storage_upload_safely(make_multipart_upload())
    # Ветка None
    await service._abort_storage_upload_safely(None)


@pytest.mark.asyncio
async def test_initiate_upload_uses_default_part_size_branch():
    # part_size_bytes None -> используется ветка по умолчанию в _build_part_sizes
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    # файл 6 МБ, часть по умолчанию 5 МБ -> 2 части
    data = make_initiate_request(
        parent_node_id=parent_id,
        file_size_bytes=6 * 1024 * 1024,
        parts_count=2,
        part_size_bytes=None,
    )
    node = make_folder_node(node_id=parent_id, owner_id=user_id)
    access = make_access(node=node)
    session = make_session(user_id=user_id, parent_node_id=parent_id, parts_count=2)
    sessions_repo = AsyncMock()
    sessions_repo.create_session = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    quotas = make_quotas()
    storage = make_storage(
        part_urls=[make_part_url(part_number=1), make_part_url(part_number=2)]
    )
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo, quotas=quotas)
    service = make_service(uow, storage=storage, access=access)

    read, urls = await service.initiate_upload(data, user_id=user_id)
    assert len(urls.parts) == 2


# ---------------------------------------------------------------------------
# get_upload_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_upload_session_success():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    result = await service.get_upload_session(session.id, user_id=user_id)
    assert str(result.id) == str(session.id)


@pytest.mark.asyncio
async def test_get_upload_session_not_owner_raises_permission():
    user_id = uuid.uuid4()
    session = make_session(user_id=uuid.uuid4())
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.get_upload_session(session.id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_upload_session_not_found_wrapped():
    user_id = uuid.uuid4()
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(
        side_effect=EntityNotFoundError("nope")
    )
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_upload_session(uuid.uuid4(), user_id=user_id)


@pytest.mark.asyncio
async def test_get_upload_session_unexpected_error_wrapped():
    user_id = uuid.uuid4()
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_upload_session(uuid.uuid4(), user_id=user_id)


# ---------------------------------------------------------------------------
# list_uploads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_uploads_success():
    user_id = uuid.uuid4()
    params = UploadQueryParams(limit=10, offset=0)
    session = make_session(user_id=user_id)
    sessions_repo = AsyncMock()
    sessions_repo.count_user_sessions_filtered = AsyncMock(return_value=1)
    sessions_repo.search_user_sessions = AsyncMock(return_value=[session])
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    result = await service.list_uploads(params, user_id=user_id)
    assert result.meta.total == 1
    assert result.meta.count == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_list_uploads_with_parent_checks_access():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    params = UploadQueryParams(limit=10, offset=0, parent_node_id=parent_id)
    sessions_repo = AsyncMock()
    sessions_repo.count_user_sessions_filtered = AsyncMock(return_value=0)
    sessions_repo.search_user_sessions = AsyncMock(return_value=[])
    access = make_access()
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow, access=access)

    await service.list_uploads(params, user_id=user_id)
    access.require_access.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_uploads_other_user_raises_permission():
    user_id = uuid.uuid4()
    params = UploadQueryParams(limit=10, offset=0, user_id=uuid.uuid4())
    uow = make_uow(upload_sessions=AsyncMock())
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.list_uploads(params, user_id=user_id)


@pytest.mark.asyncio
async def test_list_uploads_invalid_sort_field_raises_validation():
    user_id = uuid.uuid4()
    params = UploadQueryParams(limit=10, offset=0, sort_by="bogus")
    sessions_repo = AsyncMock()
    sessions_repo.count_user_sessions_filtered = AsyncMock(return_value=0)
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.list_uploads(params, user_id=user_id)


def test_validate_pagination_invalid_limit_raises():
    from services.uploads import _validate_pagination

    with pytest.raises(ValidationServiceError):
        _validate_pagination(limit=0, offset=0)
    with pytest.raises(ValidationServiceError):
        _validate_pagination(limit=10_000, offset=0)


def test_validate_pagination_negative_offset_raises():
    from services.uploads import _validate_pagination

    with pytest.raises(ValidationServiceError):
        _validate_pagination(limit=10, offset=-1)


def test_validate_pagination_ok():
    from services.uploads import _validate_pagination

    _validate_pagination(limit=10, offset=0)


@pytest.mark.asyncio
async def test_list_uploads_database_error_wrapped():
    user_id = uuid.uuid4()
    params = UploadQueryParams(limit=10, offset=0)
    sessions_repo = AsyncMock()
    sessions_repo.count_user_sessions_filtered = AsyncMock(
        side_effect=DatabaseError("db")
    )
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.list_uploads(params, user_id=user_id)


@pytest.mark.asyncio
async def test_list_uploads_unexpected_error_wrapped():
    user_id = uuid.uuid4()
    params = UploadQueryParams(limit=10, offset=0)
    sessions_repo = AsyncMock()
    sessions_repo.count_user_sessions_filtered = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.list_uploads(params, user_id=user_id)


# ---------------------------------------------------------------------------
# get_upload_parts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_upload_parts_success():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id)
    part = make_part(session_id=session.id, status=UploadPartStatus.UPLOADED, etag="e", size_bytes=1024)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_session_parts = AsyncMock(return_value=[part])
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    result = await service.get_upload_parts(session.id, user_id=user_id)
    assert len(result) == 1
    assert result[0].part_number == 1


@pytest.mark.asyncio
async def test_get_upload_parts_not_owner_raises_permission():
    user_id = uuid.uuid4()
    session = make_session(user_id=uuid.uuid4())
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=AsyncMock())
    service = make_service(uow)
    with pytest.raises(PermissionServiceError):
        await service.get_upload_parts(session.id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_upload_parts_database_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_session_parts = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_upload_parts(session.id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_upload_parts_unexpected_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_session_parts = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.get_upload_parts(session.id, user_id=user_id)


# ---------------------------------------------------------------------------
# create_part_urls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_part_urls_all_pending_marks_uploading():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.CREATED, parts_count=2)
    parts = [
        make_part(session_id=session.id, part_number=1, status=UploadPartStatus.PENDING),
        make_part(session_id=session.id, part_number=2, status=UploadPartStatus.UPLOADED),
    ]
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uploading_session = make_session(
        session_id=session.id, user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=2
    )
    sessions_repo.mark_uploading = AsyncMock(return_value=uploading_session)
    parts_repo = AsyncMock()
    parts_repo.get_session_parts = AsyncMock(return_value=parts)
    storage = make_storage(part_urls=[make_part_url(part_number=1)])
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow, storage=storage)

    result = await service.create_part_urls(session.id, user_id=user_id)
    # выбрана только ожидающая часть 1
    assert len(result.parts) == 1
    sessions_repo.mark_uploading.assert_awaited_once()
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_part_urls_with_explicit_part_numbers():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=2)
    parts = [
        make_part(session_id=session.id, part_number=1),
        make_part(session_id=session.id, part_number=2),
    ]
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_session_parts = AsyncMock(return_value=parts)
    storage = make_storage(part_urls=[make_part_url(part_number=2)])
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow, storage=storage)

    result = await service.create_part_urls(session.id, user_id=user_id, part_numbers=[2])
    assert len(result.parts) == 1
    # уже UPLOADING -> без mark_uploading
    sessions_repo.mark_uploading.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_part_urls_unknown_part_number_raises_validation():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    parts = [make_part(session_id=session.id, part_number=1)]
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_session_parts = AsyncMock(return_value=parts)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.create_part_urls(session.id, user_id=user_id, part_numbers=[99])


@pytest.mark.asyncio
async def test_create_part_urls_terminal_session_raises_upload_error():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.COMPLETED)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=AsyncMock())
    service = make_service(uow)

    with pytest.raises(UploadServiceError):
        await service.create_part_urls(session.id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_part_urls_expired_session_raises_upload_error():
    user_id = uuid.uuid4()
    session = make_session(
        user_id=user_id,
        status=UploadSessionStatus.UPLOADING,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=AsyncMock())
    service = make_service(uow)

    with pytest.raises(UploadServiceError):
        await service.create_part_urls(session.id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_part_urls_storage_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    parts = [make_part(session_id=session.id, part_number=1)]
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_session_parts = AsyncMock(return_value=parts)
    storage = make_storage()
    storage.create_upload_part_urls = AsyncMock(side_effect=StorageError("boom"))
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow, storage=storage)

    with pytest.raises(ServiceError):
        await service.create_part_urls(session.id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_part_urls_database_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_session_parts = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.create_part_urls(session.id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_part_urls_unexpected_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_session_parts = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.create_part_urls(session.id, user_id=user_id)


# ---------------------------------------------------------------------------
# confirm_part
# ---------------------------------------------------------------------------


def make_part_complete(part_number=1, size_bytes=1024, etag="etag123", checksum=None):
    return UploadPartCompleteRequest(
        part_number=part_number,
        etag=etag,
        size_bytes=size_bytes,
        checksum=checksum,
    )


@pytest.mark.asyncio
async def test_confirm_part_success_marks_uploading():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.CREATED, parts_count=1)
    part = make_part(session_id=session.id, part_number=1, size_bytes=1024)
    progressed = make_session(
        session_id=session.id,
        user_id=user_id,
        status=UploadSessionStatus.UPLOADING,
        parts_count=1,
        uploaded_parts_count=1,
        uploaded_bytes=1024,
    )
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    sessions_repo.mark_uploading = AsyncMock()
    sessions_repo.recalculate_progress_from_parts = AsyncMock(return_value=progressed)
    parts_repo = AsyncMock()
    parts_repo.get_required_by_session_and_part_number = AsyncMock(return_value=part)
    parts_repo.mark_part_uploaded = AsyncMock()
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    result = await service.confirm_part(session.id, make_part_complete(), user_id=user_id)
    assert result.upload_session_id == session.id
    assert result.progress_percent == 100.0
    sessions_repo.mark_uploading.assert_awaited_once()
    parts_repo.mark_part_uploaded.assert_awaited_once()
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_part_already_uploading_skips_mark():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    part = make_part(session_id=session.id, part_number=1, size_bytes=1024)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    sessions_repo.recalculate_progress_from_parts = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_required_by_session_and_part_number = AsyncMock(return_value=part)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    await service.confirm_part(session.id, make_part_complete(), user_id=user_id)
    sessions_repo.mark_uploading.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_part_size_mismatch_raises_validation():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    part = make_part(session_id=session.id, part_number=1, size_bytes=2048)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_required_by_session_and_part_number = AsyncMock(return_value=part)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    with pytest.raises(ValidationServiceError):
        await service.confirm_part(
            session.id, make_part_complete(size_bytes=1024), user_id=user_id
        )


@pytest.mark.asyncio
async def test_confirm_part_inactive_session_raises_upload_error():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.ABORTED)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=AsyncMock())
    service = make_service(uow)

    with pytest.raises(UploadServiceError):
        await service.confirm_part(session.id, make_part_complete(), user_id=user_id)


@pytest.mark.asyncio
async def test_confirm_part_database_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_required_by_session_and_part_number = AsyncMock(
        side_effect=DatabaseError("db")
    )
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.confirm_part(session.id, make_part_complete(), user_id=user_id)


@pytest.mark.asyncio
async def test_confirm_part_unexpected_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_required_by_session_and_part_number = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)

    with pytest.raises(ServiceError):
        await service.confirm_part(session.id, make_part_complete(), user_id=user_id)


# ---------------------------------------------------------------------------
# complete_upload
# ---------------------------------------------------------------------------


def make_complete_request(session_id, parts, checksum=None):
    return UploadCompleteRequest(
        upload_session_id=session_id,
        parts=parts,
        checksum=checksum,
    )


def make_file_with_node(file_id=None, node_id=None):
    file = MagicMock()
    file.id = file_id or uuid.uuid4()
    file.node_id = node_id or uuid.uuid4()
    return file


def build_complete_service(
    *,
    user_id,
    session=None,
    parts_db=None,
    needs_preview=False,
    file=None,
):
    session = session or make_session(
        user_id=user_id,
        status=UploadSessionStatus.UPLOADING,
        parts_count=1,
        uploaded_parts_count=1,
        uploaded_bytes=1024,
        mime_type="image/png" if needs_preview else "application/octet-stream",
        file_name="img.png" if needs_preview else "test.bin",
    )
    parts_db = parts_db or [
        make_part(session_id=session.id, part_number=1, status=UploadPartStatus.UPLOADED, etag="etag123", size_bytes=1024)
    ]
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    sessions_repo.recalculate_progress_from_parts = AsyncMock(return_value=session)
    completed = make_session(
        session_id=session.id,
        user_id=user_id,
        status=UploadSessionStatus.COMPLETED,
        parts_count=session.parts_count,
        uploaded_parts_count=session.parts_count,
        uploaded_bytes=session.file_size_bytes,
    )
    sessions_repo.mark_completed = AsyncMock(return_value=completed)

    parts_repo = AsyncMock()

    async def _get_session_parts(sid, *, offset=0, limit=1000):
        # Все части одной страницей (их меньше лимита).
        return list(parts_db) if offset == 0 else []

    parts_repo.get_session_parts = AsyncMock(side_effect=_get_session_parts)

    async def _get_part(sid, num):
        for p in parts_db:
            if p.part_number == num:
                return p
        raise EntityNotFoundError("missing")

    parts_repo.get_required_by_session_and_part_number = AsyncMock(side_effect=_get_part)
    parts_repo.mark_part_uploaded = AsyncMock(
        side_effect=lambda sid, num, **kw: make_part(
            session_id=sid, part_number=num, status=UploadPartStatus.UPLOADED, etag=kw.get("etag")
        )
    )

    file = file or make_file_with_node()
    files_repo = AsyncMock()
    files_repo.create_file_with_node = AsyncMock(return_value=file)

    tasks_repo = AsyncMock()
    task = MagicMock()
    tasks_repo.create_task = AsyncMock(return_value=task)

    quotas = make_quotas()

    uow = make_uow(
        upload_sessions=sessions_repo,
        upload_parts=parts_repo,
        files=files_repo,
        tasks=tasks_repo,
        quotas=quotas,
    )
    return uow, session, file, tasks_repo, quotas


@pytest.mark.asyncio
async def test_complete_upload_success():
    user_id = uuid.uuid4()
    uow, session, file, tasks_repo, quotas = build_complete_service(user_id=user_id)
    storage = make_storage()
    audit = make_audit()
    service = make_service(uow, storage=storage, audit=audit)

    data = make_complete_request(session.id, [make_part_complete(part_number=1, etag="etag123")])
    result = await service.complete_upload(data, user_id=user_id)

    assert result.file_id == file.id
    assert result.node_id == file.node_id
    storage.complete_multipart_upload.assert_awaited_once()
    quotas.increase_used_space.assert_awaited_once()
    quotas.increase_files_used.assert_awaited_once()
    quotas.decrease_active_upload_sessions_used.assert_awaited_once()
    tasks_repo.create_task.assert_not_awaited()
    assert audit.log_success.await_count == 2
    uow.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_upload_batch_loads_parts_no_n_plus_1():
    """Завершение загружает части одним батчем, без SELECT на каждую часть."""
    user_id = uuid.uuid4()
    parts_db = [
        make_part(part_number=n, status=UploadPartStatus.UPLOADED, etag=f"e{n}", size_bytes=1024)
        for n in (1, 2, 3)
    ]
    session = make_session(
        user_id=user_id,
        status=UploadSessionStatus.UPLOADING,
        parts_count=3,
        uploaded_parts_count=3,
        uploaded_bytes=3072,
        mime_type="application/octet-stream",
        file_name="big.bin",
    )
    uow, session, file, tasks_repo, quotas = build_complete_service(
        user_id=user_id, session=session, parts_db=parts_db
    )
    service = make_service(uow, storage=make_storage())

    data = make_complete_request(
        session.id,
        [make_part_complete(part_number=n, etag=f"e{n}") for n in (1, 2, 3)],
    )
    await service.complete_upload(data, user_id=user_id)

    # Один батч-запрос частей; per-part get_required не вызывается.
    uow.upload_parts.get_session_parts.assert_awaited()
    uow.upload_parts.get_required_by_session_and_part_number.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_upload_with_preview_creates_task():
    user_id = uuid.uuid4()
    uow, session, file, tasks_repo, quotas = build_complete_service(
        user_id=user_id, needs_preview=True
    )
    storage = make_storage()
    service = make_service(uow, storage=storage)

    data = make_complete_request(session.id, [make_part_complete(part_number=1, etag="etag123")])
    await service.complete_upload(data, user_id=user_id)
    tasks_repo.create_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_upload_confirms_not_yet_uploaded_part():
    user_id = uuid.uuid4()
    # часть в БД в статусе pending -> _confirm_completion_parts должен пометить её uploaded
    pending_part = make_part(part_number=1, status=UploadPartStatus.PENDING, etag=None, size_bytes=1024)
    session = make_session(
        user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1,
        uploaded_parts_count=0, uploaded_bytes=0,
    )
    pending_part.upload_session_id = session.id
    uow, session, file, tasks_repo, quotas = build_complete_service(
        user_id=user_id, session=session, parts_db=[pending_part]
    )
    storage = make_storage()
    service = make_service(uow, storage=storage)
    data = make_complete_request(session.id, [make_part_complete(part_number=1, etag="newetag")])
    await service.complete_upload(data, user_id=user_id)
    uow.upload_parts.mark_part_uploaded.assert_awaited()


@pytest.mark.asyncio
async def test_complete_upload_wrong_parts_count_raises_validation():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=2)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=AsyncMock())
    service = make_service(uow)
    data = make_complete_request(session.id, [make_part_complete(part_number=1)])
    with pytest.raises(ValidationServiceError):
        await service.complete_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_complete_upload_invalid_part_numbers_raises_validation():
    # parts_count == len(parts), но номера не совпадают с ожидаемым диапазоном
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=2)
    parts_db = [
        make_part(session_id=session.id, part_number=1, status=UploadPartStatus.UPLOADED, etag="e1", size_bytes=1024),
        make_part(session_id=session.id, part_number=3, status=UploadPartStatus.UPLOADED, etag="e3", size_bytes=1024),
    ]
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    sessions_repo.recalculate_progress_from_parts = AsyncMock(return_value=session)
    parts_repo = AsyncMock()

    async def _get_session_parts(sid, *, offset=0, limit=1000):
        # Все части одной страницей (их меньше лимита).
        return list(parts_db) if offset == 0 else []

    parts_repo.get_session_parts = AsyncMock(side_effect=_get_session_parts)

    async def _get_part(sid, num):
        for p in parts_db:
            if p.part_number == num:
                return p
        raise EntityNotFoundError("missing")

    parts_repo.get_required_by_session_and_part_number = AsyncMock(side_effect=_get_part)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)
    data = make_complete_request(
        session.id,
        [make_part_complete(part_number=1, etag="e1"), make_part_complete(part_number=3, etag="e3")],
    )
    with pytest.raises(ValidationServiceError):
        await service.complete_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_complete_upload_storage_error_marks_failed():
    user_id = uuid.uuid4()
    uow, session, file, tasks_repo, quotas = build_complete_service(user_id=user_id)
    storage = make_storage()
    storage.complete_multipart_upload = AsyncMock(side_effect=StorageError("boom"))
    # путь mark_failed использует новый uow из фабрики; переиспользуем тот же uow
    uow.upload_sessions.get_session_by_id = AsyncMock(return_value=session)
    uow.upload_sessions.mark_failed = AsyncMock(return_value=session)
    service = make_service(uow, storage=storage)

    data = make_complete_request(session.id, [make_part_complete(part_number=1, etag="etag123")])
    with pytest.raises(ServiceError):
        await service.complete_upload(data, user_id=user_id)
    uow.upload_sessions.mark_failed.assert_awaited()


@pytest.mark.asyncio
async def test_complete_upload_inactive_session_raises_upload_error():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.COMPLETED)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=AsyncMock())
    service = make_service(uow)
    data = make_complete_request(session.id, [make_part_complete(part_number=1)])
    with pytest.raises(UploadServiceError):
        await service.complete_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_complete_upload_database_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_required_by_session_and_part_number = AsyncMock(
        side_effect=DatabaseError("db")
    )
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)
    data = make_complete_request(session.id, [make_part_complete(part_number=1)])
    with pytest.raises(ServiceError):
        await service.complete_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_complete_upload_unexpected_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=1)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    parts_repo = AsyncMock()
    parts_repo.get_required_by_session_and_part_number = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    uow = make_uow(upload_sessions=sessions_repo, upload_parts=parts_repo)
    service = make_service(uow)
    data = make_complete_request(session.id, [make_part_complete(part_number=1)])
    with pytest.raises(ServiceError):
        await service.complete_upload(data, user_id=user_id)


# ---------------------------------------------------------------------------
# Обнаружение дубликатов в _confirm_completion_parts (через complete_upload)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_completion_parts_duplicate_raises_conflict():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING, parts_count=2)
    part = make_part(session_id=session.id, part_number=1, status=UploadPartStatus.UPLOADED, etag="e", size_bytes=1024)
    parts_repo = AsyncMock()
    parts_repo.get_required_by_session_and_part_number = AsyncMock(return_value=part)
    service = make_service(make_uow())
    # вызываем хелпер напрямую с дублирующимися номерами частей
    dup = [make_part_complete(part_number=1), make_part_complete(part_number=1)]
    uow = make_uow(upload_parts=parts_repo)
    with pytest.raises(ConflictServiceError):
        await service._confirm_completion_parts(
            uow, upload_session=session, parts=dup, operation="complete_upload"
        )


# ---------------------------------------------------------------------------
# abort_upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abort_upload_active_session():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING)
    aborted = make_session(
        session_id=session.id, user_id=user_id, status=UploadSessionStatus.ABORTED
    )
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    sessions_repo.mark_aborted = AsyncMock(return_value=aborted)
    quotas = make_quotas()
    storage = make_storage()
    audit = make_audit()
    uow = make_uow(upload_sessions=sessions_repo, quotas=quotas)
    service = make_service(uow, storage=storage, audit=audit)

    data = UploadAbortRequest(upload_session_id=session.id, reason="user cancel")
    result = await service.abort_upload(data, user_id=user_id)
    assert result.status == UploadSessionStatus.ABORTED
    storage.abort_multipart_upload.assert_awaited_once()
    quotas.decrease_active_upload_sessions_used.assert_awaited_once()
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_abort_upload_terminal_session_returns_current():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.COMPLETED)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    storage = make_storage()
    quotas = make_quotas()
    uow = make_uow(upload_sessions=sessions_repo, quotas=quotas)
    service = make_service(uow, storage=storage)

    data = UploadAbortRequest(upload_session_id=session.id)
    result = await service.abort_upload(data, user_id=user_id)
    assert result.status == UploadSessionStatus.COMPLETED
    storage.abort_multipart_upload.assert_not_awaited()
    sessions_repo.mark_aborted.assert_not_awaited()


@pytest.mark.asyncio
async def test_abort_upload_not_owner_raises_permission():
    user_id = uuid.uuid4()
    session = make_session(user_id=uuid.uuid4(), status=UploadSessionStatus.UPLOADING)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo, quotas=make_quotas())
    service = make_service(uow)
    data = UploadAbortRequest(upload_session_id=session.id)
    with pytest.raises(PermissionServiceError):
        await service.abort_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_abort_upload_storage_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    storage = make_storage()
    storage.abort_multipart_upload = AsyncMock(side_effect=StorageError("boom"))
    uow = make_uow(upload_sessions=sessions_repo, quotas=make_quotas())
    service = make_service(uow, storage=storage)

    data = UploadAbortRequest(upload_session_id=session.id)
    with pytest.raises(ServiceError):
        await service.abort_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_abort_upload_database_error_wrapped():
    user_id = uuid.uuid4()
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(upload_sessions=sessions_repo, quotas=make_quotas())
    service = make_service(uow)
    data = UploadAbortRequest(upload_session_id=uuid.uuid4())
    with pytest.raises(ServiceError):
        await service.abort_upload(data, user_id=user_id)


@pytest.mark.asyncio
async def test_abort_upload_unexpected_error_wrapped():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING)
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    sessions_repo.mark_aborted = AsyncMock(side_effect=RuntimeError("boom"))
    storage = make_storage()
    uow = make_uow(upload_sessions=sessions_repo, quotas=make_quotas())
    service = make_service(uow, storage=storage)
    data = UploadAbortRequest(upload_session_id=session.id)
    with pytest.raises(ServiceError):
        await service.abort_upload(data, user_id=user_id)


# ---------------------------------------------------------------------------
# get_progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_progress_success():
    user_id = uuid.uuid4()
    session = make_session(
        user_id=user_id, file_size_bytes=1000, uploaded_bytes=500, uploaded_parts_count=1, parts_count=2
    )
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    result = await service.get_progress(session.id, user_id=user_id)
    assert result.upload_session_id == session.id
    assert result.progress_percent == 50.0


@pytest.mark.asyncio
async def test_get_progress_not_owner_raises_permission():
    user_id = uuid.uuid4()
    session = make_session(user_id=uuid.uuid4())
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)

    with pytest.raises(PermissionServiceError):
        await service.get_progress(session.id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_progress_database_error_wrapped():
    user_id = uuid.uuid4()
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(side_effect=DatabaseError("db"))
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)
    with pytest.raises(ServiceError):
        await service.get_progress(uuid.uuid4(), user_id=user_id)


@pytest.mark.asyncio
async def test_get_progress_unexpected_error_wrapped():
    user_id = uuid.uuid4()
    sessions_repo = AsyncMock()
    sessions_repo.get_required_session_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(upload_sessions=sessions_repo)
    service = make_service(uow)
    with pytest.raises(ServiceError):
        await service.get_progress(uuid.uuid4(), user_id=user_id)


# ---------------------------------------------------------------------------
# Ветки _mark_failed_safely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_failed_safely_none_session_returns():
    user_id = uuid.uuid4()
    sessions_repo = AsyncMock()
    sessions_repo.get_session_by_id = AsyncMock(return_value=None)
    uow = make_uow(upload_sessions=sessions_repo, quotas=make_quotas())
    service = make_service(uow)
    await service._mark_failed_safely(uuid.uuid4(), reason="x", user_id=user_id)
    sessions_repo.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_failed_safely_terminal_session_returns():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.COMPLETED)
    sessions_repo = AsyncMock()
    sessions_repo.get_session_by_id = AsyncMock(return_value=session)
    uow = make_uow(upload_sessions=sessions_repo, quotas=make_quotas())
    service = make_service(uow)
    await service._mark_failed_safely(session.id, reason="x", user_id=user_id)
    sessions_repo.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_failed_safely_marks_and_logs():
    user_id = uuid.uuid4()
    session = make_session(user_id=user_id, status=UploadSessionStatus.UPLOADING)
    failed = make_session(session_id=session.id, user_id=user_id, status=UploadSessionStatus.FAILED)
    sessions_repo = AsyncMock()
    sessions_repo.get_session_by_id = AsyncMock(return_value=session)
    sessions_repo.mark_failed = AsyncMock(return_value=failed)
    quotas = make_quotas()
    audit = make_audit()
    uow = make_uow(upload_sessions=sessions_repo, quotas=quotas)
    service = make_service(uow, audit=audit)
    await service._mark_failed_safely(session.id, reason="storage down", user_id=user_id)
    sessions_repo.mark_failed.assert_awaited_once()
    quotas.decrease_active_upload_sessions_used.assert_awaited_once()
    audit.log_success.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_failed_safely_swallows_errors():
    user_id = uuid.uuid4()
    sessions_repo = AsyncMock()
    sessions_repo.get_session_by_id = AsyncMock(side_effect=RuntimeError("boom"))
    uow = make_uow(upload_sessions=sessions_repo, quotas=make_quotas())
    service = make_service(uow)
    # не должно бросать исключение
    await service._mark_failed_safely(uuid.uuid4(), reason="x", user_id=user_id)


# ---------------------------------------------------------------------------
# _safe_log_upload_event поглощает ошибки аудита
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_log_upload_event_swallows_audit_error():
    from database.models.enums import AuditAction

    audit = make_audit()
    audit.log_success = AsyncMock(side_effect=RuntimeError("audit down"))
    uow = make_uow()
    service = make_service(uow, audit=audit)
    session = make_session()
    snapshot = {
        "id": session.id,
        "user_id": session.user_id,
        "parent_node_id": session.parent_node_id,
        "file_name": "f",
        "file_size_bytes": 10,
        "parts_count": 1,
        "uploaded_parts_count": 0,
        "uploaded_bytes": 0,
        "status": UploadSessionStatus.CREATED,
        "expires_at": session.expires_at,
    }
    # не должно бросать исключение
    await service._safe_log_upload_event(
        user_id=session.user_id,
        action=AuditAction.UPLOAD_SESSION_CREATED,
        snapshot=snapshot,
        message="m",
    )


# ---------------------------------------------------------------------------
# Чистые вспомогательные функции
# ---------------------------------------------------------------------------


def test_build_part_sizes_non_positive_file_size_raises():
    from services.uploads import _build_part_sizes

    with pytest.raises(ValidationServiceError):
        _build_part_sizes(
            file_size_bytes=0,
            part_size_bytes=None,
            parts_count=1,
            default_part_size_bytes=1024,
        )


def test_build_part_sizes_non_positive_parts_count_raises():
    from services.uploads import _build_part_sizes

    with pytest.raises(ValidationServiceError):
        _build_part_sizes(
            file_size_bytes=1024,
            part_size_bytes=None,
            parts_count=0,
            default_part_size_bytes=1024,
        )


def test_build_part_sizes_mismatch_raises():
    from services.uploads import _build_part_sizes

    with pytest.raises(ValidationServiceError):
        _build_part_sizes(
            file_size_bytes=100,
            part_size_bytes=10,
            parts_count=5,
            default_part_size_bytes=1024,
        )


def test_build_part_sizes_explicit_part_size_multiple_parts():
    from services.uploads import _build_part_sizes

    sizes = _build_part_sizes(
        file_size_bytes=25,
        part_size_bytes=10,
        parts_count=3,
        default_part_size_bytes=1024,
    )
    assert sizes == [10, 10, 5]


def test_calculate_progress_percent_branches():
    from services.uploads import _calculate_progress_percent

    assert _calculate_progress_percent({"file_size_bytes": 0, "uploaded_bytes": 10}) == 0
    assert _calculate_progress_percent({"file_size_bytes": 100, "uploaded_bytes": 0}) == 0
    assert _calculate_progress_percent({"file_size_bytes": 100, "uploaded_bytes": 50}) == 50
    assert _calculate_progress_percent({"file_size_bytes": 100, "uploaded_bytes": 1000}) == 100
    assert _calculate_progress_percent({"file_size_bytes": "x", "uploaded_bytes": 10}) == 0


def test_filename_extension_branches():
    from services.uploads import _filename_extension

    assert _filename_extension("a.TXT") == "txt"
    assert _filename_extension("noext") is None


def test_normalize_optional_text_branches():
    from services.uploads import _normalize_optional_text

    assert _normalize_optional_text(None) is None
    assert _normalize_optional_text("   ") is None
    assert _normalize_optional_text("  x ") == "x"


def test_optional_uuid_branches():
    from services.uploads import _optional_uuid

    val = uuid.uuid4()
    assert _optional_uuid(val) == val
    assert _optional_uuid("not-uuid") is None


def test_jsonable_handles_various_types():
    from datetime import datetime as dt

    from services.uploads import _jsonable

    assert _jsonable(None) is None
    assert _jsonable("s") == "s"
    val = uuid.uuid4()
    assert _jsonable(val) == str(val)
    now = dt.now(UTC)
    assert _jsonable(now) == now.isoformat()
    import enum

    class PlainEnum(enum.Enum):
        A = "a-value"

    assert _jsonable(PlainEnum.A) == "a-value"
    assert _jsonable({"a": val}) == {"a": str(val)}
    assert _jsonable([val]) == [str(val)]

    class Weird:
        def __str__(self):
            return "weird"

    assert _jsonable(Weird()) == "weird"


def test_empty_result_error_is_service_error():
    from services.uploads import _empty_result_error

    err = _empty_result_error("op")
    assert isinstance(err, ServiceError)
    assert err.operation == "op"


def test_audit_upload_shape():
    from services.uploads import _audit_upload

    sid = uuid.uuid4()
    out = _audit_upload({"id": sid, "status": UploadSessionStatus.CREATED})
    assert out["id"] == str(sid)
    assert out["status"] == "created"


# ---------------------------------------------------------------------------
# фабрика get_uploads_service
# ---------------------------------------------------------------------------


def test_get_uploads_service_with_overrides_returns_new_instance():
    storage = make_storage()
    svc = get_uploads_service(
        settings=MagicMock(),
        uow_factory=make_factory(make_uow()),
        storage_service=storage,
        access_service=make_access(),
        audit_service=make_audit(),
    )
    assert isinstance(svc, UploadsService)
    assert svc.storage_service is storage


def test_get_uploads_service_singleton(monkeypatch):
    import services.uploads as uploads_module

    sentinel = MagicMock()
    monkeypatch.setattr(uploads_module, "_uploads_service", None)
    monkeypatch.setattr(uploads_module, "UploadsService", lambda *a, **k: sentinel)
    first = get_uploads_service()
    second = get_uploads_service()
    assert first is sentinel
    assert first is second
