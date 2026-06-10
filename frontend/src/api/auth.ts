import api from "@/lib/api";
import type {
  LoginRequest,
  LoginResponse,
  LogoutResponse,
  PasswordChangeRequest,
  CurrentUser,
} from "@/types";

/**
 * API-клиент для аутентификации и управления auth-сессиями.
 */
export const authApi = {
  /**
   * Выполняет вход пользователя.
   *
   * Args:
   *   data: Email или username пользователя и пароль.
   *
   * Returns:
   *   Promise с результатом аутентификации и данными текущего пользователя.
   */
  login: (data: LoginRequest) => api.post<LoginResponse>("/auth/login", data).then((r) => r.data),

  /**
   * Выполняет выход из текущей auth-сессии.
   *
   * Returns:
   *   Promise с результатом выхода.
   */
  logout: () => api.post<LogoutResponse>("/auth/logout").then((r) => r.data),

  /**
   * Возвращает текущего аутентифицированного пользователя.
   *
   * Returns:
   *   Promise с данными текущего пользователя.
   */
  me: () => api.get<CurrentUser>("/auth/me").then((r) => r.data),

  /**
   * Изменяет пароль текущего пользователя.
   *
   * Args:
   *   data: Текущий пароль и новый пароль.
   *
   * Returns:
   *   Promise с ответом API.
   */
  changePassword: (data: PasswordChangeRequest) =>
    api.post("/auth/password/change", data).then((r) => r.data),
};
