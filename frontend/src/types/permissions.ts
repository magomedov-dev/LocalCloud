/**
 * Уровень доступа к node.
 */
export type PermissionLevel = "read" | "download" | "write" | "delete" | "owner";

/**
 * Тип субъекта, которому выдано разрешение.
 */
export type PermissionSubjectType = "user" | "role" | "public_link";

/**
 * Данные для выдачи доступа к node.
 */
export interface PermissionGrantRequest {
  node_id: string;
  user_id: string;
  can_read?: boolean;
  can_download?: boolean;
  can_write?: boolean;
  can_delete?: boolean;
  can_share?: boolean;
  permission_level?: PermissionLevel;
  expires_at?: string | null;
}

/**
 * Полное представление разрешения на node.
 */
export interface NodePermissionRead {
  id: string;
  node_id: string;
  user_id: string;
  subject_type: PermissionSubjectType;
  permission_level: PermissionLevel;
  granted_by: string | null;
  can_read: boolean;
  can_download: boolean;
  can_write: boolean;
  can_delete: boolean;
  can_share: boolean;
  expires_at: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
  created_at: string;
}

/**
 * Краткое представление разрешения на node для списков.
 */
export interface NodePermissionListItem {
  id: string;
  node_id: string;
  user_id: string;
  subject_type: PermissionSubjectType;
  permission_level: PermissionLevel;
  can_read: boolean;
  can_download: boolean;
  can_write: boolean;
  can_delete: boolean;
  can_share: boolean;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

/**
 * Данные для отзыва доступа к node.
 */
export interface PermissionRevokeRequest {
  permission_id?: string;
  node_id?: string;
  user_id?: string;
  revoke_reason?: string | null;
}
