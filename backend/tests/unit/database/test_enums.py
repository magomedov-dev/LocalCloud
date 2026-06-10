"""Модульные тесты перечислений (enum) моделей: проверка значений и уникальности членов."""
from __future__ import annotations

from database.models.enums import (
    AuditResourceType,
    AuditResult,
    ArchiveStatus,
    BackgroundTaskStatus,
    BackgroundTaskType,
    FileProcessingStatus,
    HealthStatus,
    NodeType,
    NodeVisibility,
    PermissionLevel,
    PublicLinkStatus,
    QuotaResourceType,
    RegistrationRequestStatus,
    SessionStatus,
    StorageObjectStatus,
    SystemRole,
    TaskPriority,
    TrashItemStatus,
    UploadSessionStatus,
    UserStatus,
)


class TestUserStatus:
    def test_values(self) -> None:
        assert UserStatus.PENDING == "pending"
        assert UserStatus.ACTIVE == "active"
        assert UserStatus.BLOCKED == "blocked"
        assert UserStatus.REJECTED == "rejected"
        assert UserStatus.DELETED == "deleted"

    def test_is_str(self) -> None:
        assert isinstance(UserStatus.ACTIVE, str)

    def test_all_members_unique(self) -> None:
        values = [s.value for s in UserStatus]
        assert len(values) == len(set(values))


class TestSystemRole:
    def test_values(self) -> None:
        assert SystemRole.ADMIN == "admin"
        assert SystemRole.USER == "user"


class TestNodeType:
    def test_values(self) -> None:
        assert NodeType.FILE == "file"
        assert NodeType.FOLDER == "folder"


class TestNodeVisibility:
    def test_private_value(self) -> None:
        assert NodeVisibility.PRIVATE == "private"

    def test_all_have_string_values(self) -> None:
        for member in NodeVisibility:
            assert isinstance(member.value, str)


class TestSessionStatus:
    def test_values(self) -> None:
        assert SessionStatus.ACTIVE == "active"
        assert SessionStatus.REVOKED == "revoked"
        assert SessionStatus.EXPIRED == "expired"


class TestRegistrationRequestStatus:
    def test_values(self) -> None:
        assert RegistrationRequestStatus.PENDING == "pending"
        assert RegistrationRequestStatus.APPROVED == "approved"
        assert RegistrationRequestStatus.REJECTED == "rejected"
        assert RegistrationRequestStatus.CANCELLED == "cancelled"


class TestPermissionLevel:
    def test_values(self) -> None:
        assert PermissionLevel.READ == "read"
        assert PermissionLevel.WRITE == "write"
        assert PermissionLevel.OWNER == "owner"

    def test_download_and_delete(self) -> None:
        assert PermissionLevel.DOWNLOAD == "download"
        assert PermissionLevel.DELETE == "delete"


class TestBackgroundTaskStatus:
    def test_pending_running_completed(self) -> None:
        assert BackgroundTaskStatus.PENDING == "pending"
        assert BackgroundTaskStatus.RUNNING == "running"
        assert BackgroundTaskStatus.COMPLETED == "completed"

    def test_failed_cancelled(self) -> None:
        assert BackgroundTaskStatus.FAILED == "failed"
        assert BackgroundTaskStatus.CANCELLED == "cancelled"


class TestBackgroundTaskType:
    def test_key_types_exist(self) -> None:
        assert BackgroundTaskType.CLEAN_TRASH == "clean_trash"
        assert BackgroundTaskType.CLEAN_EXPIRED_UPLOADS == "clean_expired_uploads"
        assert BackgroundTaskType.RECALCULATE_USER_QUOTA == "recalculate_user_quota"
        assert BackgroundTaskType.CREATE_FOLDER_ARCHIVE == "create_folder_archive"

    def test_all_members_unique(self) -> None:
        values = [t.value for t in BackgroundTaskType]
        assert len(values) == len(set(values))


class TestTaskPriority:
    def test_values(self) -> None:
        assert TaskPriority.LOW == "low"
        assert TaskPriority.NORMAL == "normal"
        assert TaskPriority.HIGH == "high"


class TestHealthStatus:
    def test_ok(self) -> None:
        assert HealthStatus.OK == "ok"


class TestStorageObjectStatus:
    def test_values(self) -> None:
        assert StorageObjectStatus.AVAILABLE == "available"
        assert StorageObjectStatus.MISSING == "missing"
        assert StorageObjectStatus.DELETED == "deleted"


class TestFileProcessingStatus:
    def test_values(self) -> None:
        assert FileProcessingStatus.PENDING == "pending"
        assert FileProcessingStatus.PROCESSING == "processing"
        assert FileProcessingStatus.READY == "ready"
        assert FileProcessingStatus.FAILED == "failed"


class TestUploadSessionStatus:
    def test_values(self) -> None:
        assert UploadSessionStatus.CREATED == "created"
        assert UploadSessionStatus.UPLOADING == "uploading"
        assert UploadSessionStatus.COMPLETED == "completed"
        assert UploadSessionStatus.FAILED == "failed"
        assert UploadSessionStatus.EXPIRED == "expired"

    def test_is_str(self) -> None:
        for member in UploadSessionStatus:
            assert isinstance(member.value, str)


class TestPublicLinkStatus:
    def test_values(self) -> None:
        assert PublicLinkStatus.ACTIVE == "active"
        assert PublicLinkStatus.EXPIRED == "expired"
        assert PublicLinkStatus.DISABLED == "disabled"


class TestAuditResult:
    def test_values(self) -> None:
        assert AuditResult.SUCCESS == "success"
        assert AuditResult.FAILURE == "failure"


class TestAuditResourceType:
    def test_session_and_file(self) -> None:
        assert AuditResourceType.SESSION == "session"
        assert AuditResourceType.FILE == "file"

    def test_all_unique(self) -> None:
        values = [r.value for r in AuditResourceType]
        assert len(values) == len(set(values))


class TestQuotaResourceType:
    def test_storage_bytes(self) -> None:
        assert QuotaResourceType.STORAGE_BYTES == "storage_bytes"
        assert QuotaResourceType.FILE_COUNT == "file_count"

    def test_all_unique(self) -> None:
        values = [q.value for q in QuotaResourceType]
        assert len(values) == len(set(values))


class TestTrashItemStatus:
    def test_values(self) -> None:
        assert TrashItemStatus.IN_TRASH == "in_trash"
        assert TrashItemStatus.RESTORED == "restored"
        assert TrashItemStatus.PURGED == "purged"


class TestArchiveStatus:
    def test_values(self) -> None:
        assert ArchiveStatus.PENDING == "pending"
        assert ArchiveStatus.BUILDING == "building"
        assert ArchiveStatus.READY == "ready"
        assert ArchiveStatus.FAILED == "failed"
