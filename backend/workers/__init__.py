from __future__ import annotations

from workers.archives import create_folder_archive_handler
from workers.cleanup import clean_trash_handler, delete_object_from_storage_handler
from workers.context import (
    WorkerContext,
    WorkerServices,
    build_worker_context,
    generate_worker_id,
)
from workers.dispatcher import WorkerDispatcher
from workers.exceptions import (
    WorkerConfigurationError,
    WorkerError,
    WorkerLifecycleError,
    WorkerSchedulerError,
    WorkerShutdownError,
    WorkerTaskDispatchError,
    WorkerTaskError,
    WorkerTaskHandlerError,
    WorkerTaskLockError,
    WorkerTaskNotFoundError,
)
from workers.health import WorkerHealthChecker, WorkerHealthStatus
from workers.integrity import check_storage_integrity_handler
from workers.lifecycle import shutdown_worker, startup_worker
from workers.previews import generate_file_preview_handler
from workers.public_links import clean_expired_public_links_handler
from workers.quotas import recalculate_user_quota_handler
from workers.registry import WorkerTaskRegistry, build_default_registry
from workers.scheduler import WorkerScheduler
from workers.tasks import (
    cast_dict_jsonable,
    failure_result,
    jsonable,
    optional_payload_value,
    payload_datetime,
    payload_int,
    payload_uuid,
    require_payload_value,
    retry_result,
    success_result,
)
from workers.types import (
    WorkerIdentity,
    WorkerRunMode,
    WorkerRuntimeStats,
    WorkerScheduleDefinition,
    WorkerState,
    WorkerTaskExecutionContext,
    WorkerTaskExecutionResult,
    WorkerTaskHandler,
)
from workers.uploads import clean_expired_uploads_handler

__all__ = [
    "WorkerConfigurationError",
    "WorkerContext",
    "WorkerDispatcher",
    "WorkerError",
    "WorkerHealthChecker",
    "WorkerHealthStatus",
    "WorkerIdentity",
    "WorkerLifecycleError",
    "WorkerRunMode",
    "WorkerRuntimeStats",
    "WorkerScheduleDefinition",
    "WorkerScheduler",
    "WorkerSchedulerError",
    "WorkerServices",
    "WorkerShutdownError",
    "WorkerState",
    "WorkerTaskDispatchError",
    "WorkerTaskError",
    "WorkerTaskExecutionContext",
    "WorkerTaskExecutionResult",
    "WorkerTaskHandler",
    "WorkerTaskHandlerError",
    "WorkerTaskLockError",
    "WorkerTaskNotFoundError",
    "WorkerTaskRegistry",
    "build_default_registry",
    "build_worker_context",
    "cast_dict_jsonable",
    "check_storage_integrity_handler",
    "clean_expired_public_links_handler",
    "clean_expired_uploads_handler",
    "clean_trash_handler",
    "create_folder_archive_handler",
    "delete_object_from_storage_handler",
    "failure_result",
    "generate_file_preview_handler",
    "generate_worker_id",
    "jsonable",
    "optional_payload_value",
    "payload_datetime",
    "payload_int",
    "payload_uuid",
    "recalculate_user_quota_handler",
    "require_payload_value",
    "retry_result",
    "shutdown_worker",
    "startup_worker",
    "success_result",
]
