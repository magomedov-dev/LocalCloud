import type { CurrentUser } from "./users";

/**
 * Данные для входа пользователя.
 */
export interface LoginRequest {
  email_or_username: string;
  password: string;
}

/**
 * Ответ API после успешной или неуспешной попытки входа.
 */
export interface LoginResponse {
  authenticated: boolean;
  user: CurrentUser;
  message: string;
}

/**
 * Ответ API после выхода из аккаунта.
 */
export interface LogoutResponse {
  authenticated: boolean;
  message: string;
}

/**
 * Ответ API после обновления auth-сессии.
 */
export interface RefreshResponse {
  authenticated: boolean;
  user: CurrentUser | null;
  message: string;
}

/**
 * Auth-сессия пользователя.
 */
export interface AuthSession {
  id: string;
  user_id: string;
  status: string;
  expires_at: string;
  revoked_at: string | null;
  revoke_reason: string | null;
  ip_address: string | null;
  user_agent: string | null;
  device_name: string | null;
  is_active: boolean;
  created_at: string;
}

/**
 * Данные для смены пароля текущего пользователя.
 */
export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}
