import type { NodeListItem } from "./nodes";

/**
 * Тип доступа, доступный по публичной ссылке.
 */
export type PublicLinkPermissionType = "view" | "download" | "upload";

/**
 * Статус публичной ссылки.
 */
export type PublicLinkStatus = "active" | "disabled" | "expired" | "revoked";

/**
 * Данные для создания публичной ссылки.
 */
export interface PublicLinkCreateRequest {
  node_id: string;
  permission_type?: PublicLinkPermissionType;
  expires_at?: string | null;
  max_downloads?: number | null;
  password?: string | null;
  description?: string | null;
}

/**
 * Данные для обновления публичной ссылки.
 *
 * Все поля необязательны; нужно передать хотя бы одно. Нельзя одновременно
 * задавать `password` и `clear_password`.
 */
export interface PublicLinkUpdateRequest {
  permission_type?: PublicLinkPermissionType;
  status?: PublicLinkStatus;
  expires_at?: string | null;
  max_downloads?: number | null;
  password?: string | null;
  clear_password?: boolean;
  description?: string | null;
  is_active?: boolean;
}

/**
 * Полное представление публичной ссылки.
 */
export interface PublicLinkRead {
  id: string;
  node_id: string;
  created_by: string | null;
  token: string;
  permission_type: PublicLinkPermissionType;
  status: PublicLinkStatus;
  expires_at: string | null;
  max_downloads: number | null;
  download_count: number;
  view_count: number;
  is_active: boolean;
  revoked_at: string | null;
  revoke_reason: string | null;
  last_accessed_at: string | null;
  description: string | null;
  created_at: string;
  has_password: boolean;
  node: NodeListItem | null;
  is_download_limit_reached: boolean;
  is_revoked: boolean;
}

/**
 * Краткое представление публичной ссылки для списков.
 */
export interface PublicLinkListItem {
  id: string;
  node_id: string;
  token: string;
  permission_type: PublicLinkPermissionType;
  status: PublicLinkStatus;
  expires_at: string | null;
  download_count: number;
  is_active: boolean;
  created_at: string;
  has_password: boolean;
  node: NodeListItem | null;
}

/**
 * Данные для отзыва публичной ссылки.
 */
export interface PublicLinkRevokeRequest {
  revoke_reason?: string | null;
}

/**
 * Публичное представление публичной ссылки.
 *
 * Используется для страниц доступа по token, где не должны раскрываться
 * административные или приватные поля ссылки.
 */
export interface PublicLinkPublicRead {
  id: string;
  node_id: string;
  permission_type: PublicLinkPermissionType;
  status: PublicLinkStatus;
  expires_at: string | null;
  has_password: boolean;
  description: string | null;
  node: import("./nodes").NodeListItem | null;
}

/**
 * Ответ API после проверки доступа к публичной ссылке.
 *
 * Используется страницей открытия ссылки: по `requires_password` решается,
 * показывать ли запрос пароля, а `allowed` подтверждает успешную проверку.
 */
export interface PublicLinkAccessResponse {
  allowed: boolean;
  link: PublicLinkPublicRead | null;
  requires_password: boolean;
  message: string | null;
}

/**
 * Ответ API с presigned URL для скачивания по публичной ссылке.
 */
export interface PublicLinkDownloadResponse {
  presigned_url: string;
  expires_at: string;
  method: string;
  headers: Record<string, string>;
  filename: string | null;
  size_bytes: number | null;
  mime_type: string | null;
}

/**
 * Статус фоновой задачи создания архива по публичной ссылке.
 *
 * Название отличается от admin `BackgroundTaskStatus` из `./tasks`, потому что
 * набор значений другой. Это позволяет barrel-файлу `@/types` реэкспортировать
 * оба типа без конфликта имён.
 */
export type ArchiveTaskStatus = "pending" | "in_progress" | "completed" | "failed";

/**
 * Ответ API о состоянии архивации папки по публичной ссылке.
 */
export interface PublicLinkFolderArchiveResponse {
  task_id: string;
  status: ArchiveTaskStatus;
  presigned_url: string | null;
  expires_at: string | null;
  filename: string | null;
  size_bytes: number | null;
}
