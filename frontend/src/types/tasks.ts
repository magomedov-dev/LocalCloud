/**
 * Статус фоновой задачи.
 */
export type BackgroundTaskStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

/**
 * Тип фоновой задачи.
 */
export type BackgroundTaskType =
  | "create_folder_archive"
  | "clean_trash"
  | "clean_expired_uploads"
  | "clean_expired_public_links"
  | "delete_object_from_storage"
  | "check_storage_integrity"
  | "generate_file_preview"
  | "recalculate_user_quota"
  | "backup_database"
  | "backup_storage";

/**
 * Приоритет фоновой задачи.
 */
export type TaskPriority = "low" | "normal" | "high" | "critical";

/**
 * Полное представление фоновой задачи.
 */
export interface BackgroundTask {
  id: string;
  task_type: BackgroundTaskType;
  status: BackgroundTaskStatus;
  priority: TaskPriority;
  created_by: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error_message: string | null;
  attempts: number;
  max_attempts: number;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Краткое представление фоновой задачи для списков.
 */
export interface BackgroundTaskListItem {
  id: string;
  task_type: BackgroundTaskType;
  status: BackgroundTaskStatus;
  priority: TaskPriority;
  created_by: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  progress_percent: number;
  error_code: string | null;
  attempts_count: number;
  max_attempts: number;
  scheduled_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}
