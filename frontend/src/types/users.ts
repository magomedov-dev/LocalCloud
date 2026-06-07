/**
 * Статус пользователя.
 */
export type UserStatus = "pending" | "active" | "blocked" | "rejected" | "deleted";

/**
 * Краткое представление роли для списков.
 */
export interface RoleListItem {
  id: string;
  name: string;
  code: string;
  display_name: string;
  is_system: boolean;
  is_active: boolean;
  created_at: string;
}

/**
 * Текущий аутентифицированный пользователь.
 */
export interface CurrentUser {
  id: string;
  email: string;
  username: string;
  status: UserStatus;
  is_email_verified: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
  roles: RoleListItem[];
}

/**
 * Полное представление пользователя.
 */
export interface UserRead {
  id: string;
  email: string;
  username: string;
  status: UserStatus;
  is_email_verified: boolean;
  last_login_at: string | null;
  approved_at: string | null;
  blocked_at: string | null;
  rejected_at: string | null;
  deleted_at: string | null;
  block_reason: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Краткое представление пользователя для списков.
 */
export interface UserListItem {
  id: string;
  email: string;
  username: string;
  status: UserStatus;
  is_email_verified: boolean;
  last_login_at: string | null;
  created_at: string;
}
