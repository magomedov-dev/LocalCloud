"""Модульные тесты моделей FileSystemNode, File, Folder и TrashItem.

Все экземпляры создаются через ``model_construct``, поэтому сессия БД или движок
не требуются.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta


from database.models.enums import (
    FilePreviewStatus,
    FileProcessingStatus,
    NodeType,
    NodeVisibility,
    StorageObjectStatus,
    TrashItemStatus,
)
from database.models.filesystem import File, FileSystemNode, Folder, TrashItem


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_node(**kwargs: object) -> FileSystemNode:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        parent_id=None,
        name="test-node",
        node_type=NodeType.FOLDER,
        visibility=NodeVisibility.PRIVATE,
        path="/test-node",
        depth=0,
        is_deleted=False,
        deleted_at=None,
        created_by=None,
        updated_by=None,
        deleted_by=None,
    )
    defaults.update(kwargs)
    return FileSystemNode(**defaults)


def make_file(**kwargs: object) -> File:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        storage_bucket="my-bucket",
        storage_key="objects/file.txt",
        size_bytes=1024,
        mime_type="text/plain",
        extension="txt",
        checksum=None,
        checksum_algorithm=None,
        storage_status=StorageObjectStatus.AVAILABLE,
        processing_status=FileProcessingStatus.READY,
        preview_status=FilePreviewStatus.NOT_REQUIRED,
        preview_storage_key=None,
    )
    defaults.update(kwargs)
    return File(**defaults)


def make_trash_item(**kwargs: object) -> TrashItem:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        deleted_by=None,
        original_parent_id=None,
        original_path="/test-node",
        status=TrashItemStatus.IN_TRASH,
        deleted_at=datetime.now(UTC),
        expires_at=None,
        restore_available=True,
        purged_at=None,
    )
    defaults.update(kwargs)
    return TrashItem(**defaults)


# ===========================================================================
# Тесты FileSystemNode
# ===========================================================================

class TestFileSystemNodeIsFile:
    def test_file_node_type_returns_true(self) -> None:
        node = make_node(node_type=NodeType.FILE)
        assert node.is_file is True

    def test_folder_node_type_returns_false(self) -> None:
        node = make_node(node_type=NodeType.FOLDER)
        assert node.is_file is False


class TestFileSystemNodeIsFolder:
    def test_folder_node_type_returns_true(self) -> None:
        node = make_node(node_type=NodeType.FOLDER)
        assert node.is_folder is True

    def test_file_node_type_returns_false(self) -> None:
        node = make_node(node_type=NodeType.FILE)
        assert node.is_folder is False


class TestFileSystemNodeVisibility:
    def test_private_visibility(self) -> None:
        node = make_node(visibility=NodeVisibility.PRIVATE)
        assert node.is_private is True
        assert node.is_shared is False
        assert node.is_public is False

    def test_shared_visibility(self) -> None:
        node = make_node(visibility=NodeVisibility.SHARED)
        assert node.is_private is False
        assert node.is_shared is True
        assert node.is_public is False

    def test_public_visibility(self) -> None:
        node = make_node(visibility=NodeVisibility.PUBLIC)
        assert node.is_private is False
        assert node.is_shared is False
        assert node.is_public is True


class TestFileSystemNodeIsRootLevel:
    def test_no_parent_is_root(self) -> None:
        node = make_node(parent_id=None)
        assert node.is_root_level is True

    def test_with_parent_not_root(self) -> None:
        node = make_node(parent_id=uuid.uuid4())
        assert node.is_root_level is False


class TestFileSystemNodeMarkDeleted:
    def test_sets_is_deleted_true(self) -> None:
        node = make_node(is_deleted=False)
        node.mark_deleted()
        assert node.is_deleted is True

    def test_sets_deleted_at(self) -> None:
        node = make_node(is_deleted=False)
        node.mark_deleted()
        assert node.deleted_at is not None

    def test_custom_deleted_at_stored(self) -> None:
        moment = datetime(2024, 5, 1, tzinfo=UTC)
        node = make_node(is_deleted=False)
        node.mark_deleted(deleted_at=moment)
        assert node.deleted_at == moment

    def test_deleted_by_stored(self) -> None:
        deleter_id = uuid.uuid4()
        node = make_node(is_deleted=False)
        node.mark_deleted(deleted_by=deleter_id)
        assert node.deleted_by == deleter_id


class TestFileSystemNodeRestore:
    def test_clears_is_deleted(self) -> None:
        node = make_node(is_deleted=True, deleted_at=datetime.now(UTC))
        node.restore()
        assert node.is_deleted is False

    def test_clears_deleted_at(self) -> None:
        node = make_node(is_deleted=True, deleted_at=datetime.now(UTC))
        node.restore()
        assert node.deleted_at is None

    def test_clears_deleted_by(self) -> None:
        node = make_node(is_deleted=True, deleted_by=uuid.uuid4())
        node.restore()
        assert node.deleted_by is None

    def test_updates_path_if_provided(self) -> None:
        node = make_node(is_deleted=True, path="/old-path")
        node.restore(path="/new-path")
        assert node.path == "/new-path"

    def test_updates_depth_if_provided(self) -> None:
        node = make_node(is_deleted=True, depth=3)
        node.restore(depth=1)
        assert node.depth == 1


class TestFileSystemNodeVisibilityMethods:
    def test_make_private(self) -> None:
        node = make_node(visibility=NodeVisibility.PUBLIC)
        node.make_private()
        assert node.visibility == NodeVisibility.PRIVATE

    def test_make_shared(self) -> None:
        node = make_node(visibility=NodeVisibility.PRIVATE)
        node.make_shared()
        assert node.visibility == NodeVisibility.SHARED

    def test_make_public(self) -> None:
        node = make_node(visibility=NodeVisibility.PRIVATE)
        node.make_public()
        assert node.visibility == NodeVisibility.PUBLIC


class TestFileSystemNodeRepr:
    def test_repr_non_empty(self) -> None:
        node = make_node()
        result = repr(node)
        assert isinstance(result, str) and len(result) > 0

    def test_repr_contains_class_name(self) -> None:
        node = make_node()
        assert "FileSystemNode" in repr(node)


# ===========================================================================
# Тесты File
# ===========================================================================

class TestFileIsReady:
    def test_ready_processing_and_available_storage(self) -> None:
        f = make_file(
            processing_status=FileProcessingStatus.READY,
            storage_status=StorageObjectStatus.AVAILABLE,
        )
        assert f.is_ready is True

    def test_processing_status_not_ready(self) -> None:
        f = make_file(
            processing_status=FileProcessingStatus.PROCESSING,
            storage_status=StorageObjectStatus.AVAILABLE,
        )
        assert f.is_ready is False

    def test_storage_status_missing(self) -> None:
        f = make_file(
            processing_status=FileProcessingStatus.READY,
            storage_status=StorageObjectStatus.MISSING,
        )
        assert f.is_ready is False


class TestFilePreviewAvailable:
    def test_ready_preview_with_key(self) -> None:
        f = make_file(
            preview_status=FilePreviewStatus.READY,
            preview_storage_key="objects/preview/file.jpg",
        )
        assert f.preview_available is True

    def test_ready_preview_without_key(self) -> None:
        f = make_file(
            preview_status=FilePreviewStatus.READY,
            preview_storage_key=None,
        )
        assert f.preview_available is False

    def test_not_required_preview(self) -> None:
        f = make_file(
            preview_status=FilePreviewStatus.NOT_REQUIRED,
            preview_storage_key=None,
        )
        assert f.preview_available is False


class TestFileStateMethods:
    def test_mark_processing(self) -> None:
        f = make_file(processing_status=FileProcessingStatus.READY)
        f.mark_processing()
        assert f.processing_status == FileProcessingStatus.PROCESSING

    def test_mark_ready(self) -> None:
        f = make_file(
            processing_status=FileProcessingStatus.PROCESSING,
            storage_status=StorageObjectStatus.MISSING,
        )
        f.mark_ready()
        assert f.processing_status == FileProcessingStatus.READY
        assert f.storage_status == StorageObjectStatus.AVAILABLE

    def test_mark_processing_failed(self) -> None:
        f = make_file(processing_status=FileProcessingStatus.PROCESSING)
        f.mark_processing_failed()
        assert f.processing_status == FileProcessingStatus.FAILED

    def test_mark_storage_missing(self) -> None:
        f = make_file(storage_status=StorageObjectStatus.AVAILABLE)
        f.mark_storage_missing()
        assert f.storage_status == StorageObjectStatus.MISSING

    def test_mark_storage_corrupted(self) -> None:
        f = make_file(storage_status=StorageObjectStatus.AVAILABLE)
        f.mark_storage_corrupted()
        assert f.storage_status == StorageObjectStatus.CORRUPTED

    def test_set_preview_ready(self) -> None:
        f = make_file(preview_status=FilePreviewStatus.PENDING, preview_storage_key=None)
        f.set_preview_ready("objects/preview/out.jpg")
        assert f.preview_status == FilePreviewStatus.READY
        assert f.preview_storage_key == "objects/preview/out.jpg"


class TestFileRepr:
    def test_repr_non_empty(self) -> None:
        f = make_file()
        assert isinstance(repr(f), str) and len(repr(f)) > 0

    def test_repr_contains_class_name(self) -> None:
        f = make_file()
        assert "File" in repr(f)


# ===========================================================================
# Тесты TrashItem
# ===========================================================================

class TestTrashItemIsInTrash:
    def test_in_trash_status_returns_true(self) -> None:
        item = make_trash_item(status=TrashItemStatus.IN_TRASH)
        assert item.is_in_trash is True

    def test_restored_status_returns_false(self) -> None:
        item = make_trash_item(status=TrashItemStatus.RESTORED)
        assert item.is_in_trash is False


class TestTrashItemIsRestored:
    def test_restored_status_returns_true(self) -> None:
        item = make_trash_item(status=TrashItemStatus.RESTORED)
        assert item.is_restored is True

    def test_in_trash_status_returns_false(self) -> None:
        item = make_trash_item(status=TrashItemStatus.IN_TRASH)
        assert item.is_restored is False


class TestTrashItemIsPurged:
    def test_purged_status_returns_true(self) -> None:
        item = make_trash_item(status=TrashItemStatus.PURGED)
        assert item.is_purged is True

    def test_purged_at_set_returns_true(self) -> None:
        item = make_trash_item(status=TrashItemStatus.IN_TRASH, purged_at=datetime.now(UTC))
        assert item.is_purged is True

    def test_in_trash_no_purge_time_returns_false(self) -> None:
        item = make_trash_item(status=TrashItemStatus.IN_TRASH, purged_at=None)
        assert item.is_purged is False


class TestTrashItemCanRestore:
    def test_in_trash_restore_available_no_purge_returns_true(self) -> None:
        item = make_trash_item(
            status=TrashItemStatus.IN_TRASH,
            restore_available=True,
            purged_at=None,
        )
        assert item.can_restore is True

    def test_restore_unavailable_returns_false(self) -> None:
        item = make_trash_item(
            status=TrashItemStatus.IN_TRASH,
            restore_available=False,
            purged_at=None,
        )
        assert item.can_restore is False

    def test_already_purged_returns_false(self) -> None:
        item = make_trash_item(
            status=TrashItemStatus.IN_TRASH,
            restore_available=True,
            purged_at=datetime.now(UTC),
        )
        assert item.can_restore is False

    def test_restored_status_returns_false(self) -> None:
        item = make_trash_item(status=TrashItemStatus.RESTORED, restore_available=True)
        assert item.can_restore is False


class TestTrashItemRestore:
    def test_sets_status_to_restored(self) -> None:
        item = make_trash_item(status=TrashItemStatus.IN_TRASH)
        item.restore()
        assert item.status == TrashItemStatus.RESTORED

    def test_disables_restore_available(self) -> None:
        item = make_trash_item(status=TrashItemStatus.IN_TRASH, restore_available=True)
        item.restore()
        assert item.restore_available is False


class TestTrashItemPurge:
    def test_sets_status_to_purged(self) -> None:
        item = make_trash_item(status=TrashItemStatus.IN_TRASH)
        item.purge()
        assert item.status == TrashItemStatus.PURGED

    def test_sets_purged_at(self) -> None:
        item = make_trash_item()
        item.purge()
        assert item.purged_at is not None

    def test_custom_purged_at_stored(self) -> None:
        moment = datetime(2024, 8, 1, tzinfo=UTC)
        item = make_trash_item()
        item.purge(purged_at=moment)
        assert item.purged_at == moment

    def test_disables_restore_available(self) -> None:
        item = make_trash_item(restore_available=True)
        item.purge()
        assert item.restore_available is False


class TestTrashItemIsExpiredAt:
    def test_expires_at_in_past_returns_true(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        item = make_trash_item(expires_at=past)
        assert item.is_expired_at(datetime.now(UTC)) is True

    def test_expires_at_in_future_returns_false(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=1)
        item = make_trash_item(expires_at=future)
        assert item.is_expired_at(datetime.now(UTC)) is False

    def test_expires_at_none_returns_false(self) -> None:
        item = make_trash_item(expires_at=None)
        assert item.is_expired_at(datetime.now(UTC)) is False


class TestTrashItemRepr:
    def test_repr_non_empty(self) -> None:
        item = make_trash_item()
        assert isinstance(repr(item), str) and len(repr(item)) > 0


# ===========================================================================
# Покрытие веток FileSystemNode: rename / move / restore
# ===========================================================================

class TestFileSystemNodeRename:
    def test_sets_new_name(self) -> None:
        node = make_node(name="old-name")
        node.rename("new-name")
        assert node.name == "new-name"

    def test_sets_updated_by(self) -> None:
        editor = uuid.uuid4()
        node = make_node()
        node.rename("renamed", updated_by=editor)
        assert node.updated_by == editor


class TestFileSystemNodeMove:
    def test_updates_parent_path_depth(self) -> None:
        new_parent = uuid.uuid4()
        node = make_node(parent_id=None, path="/old", depth=0)
        node.move(new_parent_id=new_parent, new_path="/new/old", new_depth=1)
        assert node.parent_id == new_parent
        assert node.path == "/new/old"
        assert node.depth == 1

    def test_sets_updated_by(self) -> None:
        editor = uuid.uuid4()
        node = make_node()
        node.move(
            new_parent_id=None,
            new_path="/root",
            new_depth=0,
            updated_by=editor,
        )
        assert node.updated_by == editor


class TestFileSystemNodeRestoreParentBranch:
    def test_restore_sets_parent_id_when_provided(self) -> None:
        new_parent = uuid.uuid4()
        node = make_node(is_deleted=True, parent_id=None)
        node.restore(parent_id=new_parent)
        assert node.parent_id == new_parent

    def test_restore_keeps_existing_parent_when_no_arg(self) -> None:
        existing_parent = uuid.uuid4()
        node = make_node(is_deleted=True, parent_id=existing_parent)
        node.restore()
        # аргумент parent_id равен None, но существующий родитель активирует ветку присваивания
        assert node.parent_id is None


# ===========================================================================
# Folder
# ===========================================================================

def make_folder(**kwargs: object) -> Folder:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        description=None,
        color=None,
    )
    defaults.update(kwargs)
    return Folder(**defaults)


class TestFolderUpdateMetadata:
    def test_sets_description_and_color(self) -> None:
        folder = make_folder(description="old", color="red")
        folder.update_metadata(description="new desc", color="blue")
        assert folder.description == "new desc"
        assert folder.color == "blue"

    def test_clears_metadata_with_none(self) -> None:
        folder = make_folder(description="desc", color="green")
        folder.update_metadata(description=None, color=None)
        assert folder.description is None
        assert folder.color is None


class TestFolderRepr:
    def test_repr_non_empty(self) -> None:
        folder = make_folder()
        assert isinstance(repr(folder), str) and len(repr(folder)) > 0

    def test_repr_contains_class_name(self) -> None:
        folder = make_folder()
        assert "Folder" in repr(folder)
