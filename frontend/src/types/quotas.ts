/**
 * Квота пользователя.
 */
export interface UserQuota {
  id: string;
  user_id: string;
  storage_limit_bytes: number;
  storage_used_bytes: number;
  max_file_size_bytes: number;
  files_limit: number | null;
  files_used: number;
  public_links_limit: number | null;
  public_links_used: number;
  active_upload_sessions_limit: number | null;
  active_upload_sessions_used: number;
  created_at: string;
  updated_at: string;
}

/**
 * Сводка использования квоты пользователя.
 */
export interface QuotaUsageRead {
  user_id: string;
  storage_limit_bytes: number;
  storage_used_bytes: number;
  max_file_size_bytes: number;
  files_limit: number | null;
  files_used: number;
  public_links_limit: number | null;
  public_links_used: number;
  active_upload_sessions_limit: number | null;
  active_upload_sessions_used: number;
  available_storage_bytes: number;
  usage_percent: number;
  is_storage_full: boolean;
  is_files_limit_reached: boolean;
  is_public_links_limit_reached: boolean;
  is_active_upload_sessions_limit_reached: boolean;
}

/**
 * Данные для обновления квоты пользователя.
 */
export interface UserQuotaUpdate {
  storage_limit_bytes?: number | null;
  max_file_size_bytes?: number | null;
  files_limit?: number | null;
  public_links_limit?: number | null;
  active_upload_sessions_limit?: number | null;
}

/**
 * Статус запроса на увеличение квоты.
 */
export type QuotaIncreaseRequestStatus = "pending" | "approved" | "rejected";

/**
 * Запрос пользователя на увеличение квоты.
 */
export interface QuotaIncreaseRequest {
  id: string;
  user_id: string;
  username: string | null;
  email: string | null;
  requested_bytes: number;
  current_limit_bytes: number;
  reason: string | null;
  status: QuotaIncreaseRequestStatus;
  admin_comment: string | null;
  created_at: string;
  reviewed_at: string | null;
}

/**
 * Сводка состояния серверного хранилища.
 */
export interface ServerStorage {
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  allocated_quota_bytes: number;
}
