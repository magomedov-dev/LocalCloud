/**
 * Статус пользователя.
 */
export type UserStatus = "pending" | "active" | "blocked" | "rejected" | "deleted";

/**
 * Роль пользователя.
 */
export type UserRole = "admin" | "user";

/**
 * Текущий аутентифицированный пользователь.
 */
export interface CurrentUser {
  id: string;
  email: string;
  username: string;
  status: UserStatus;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
  role: UserRole;
}

/**
 * Минимальное представление пользователя для автопоиска при шеринге.
 */
export interface UserLookupItem {
  id: string;
  username: string;
  email: string;
}

/**
 * Полное представление пользователя.
 */
export interface UserRead {
  id: string;
  email: string;
  username: string;
  status: UserStatus;
  last_login_at: string | null;
  approved_at: string | null;
  blocked_at: string | null;
  rejected_at: string | null;
  deleted_at: string | null;
  block_reason: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
  /** Признак учётной записи первичного администратора (нельзя удалить). */
  is_primary_admin: boolean;
}

/**
 * Краткое представление пользователя для списков.
 */
export interface UserListItem {
  id: string;
  email: string;
  username: string;
  status: UserStatus;
  last_login_at: string | null;
  created_at: string;
  /** Признак учётной записи первичного администратора (нельзя удалить). */
  is_primary_admin: boolean;
}
