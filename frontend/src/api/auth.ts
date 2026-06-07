import api from "@/lib/api";
import type {
  LoginRequest,
  LoginResponse,
  LogoutResponse,
  PasswordChangeRequest,
  PasswordResetRequest,
  PasswordResetRequestResponse,
  PasswordResetConfirmRequest,
  PasswordResetConfirmResponse,
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

  /**
   * Запрашивает сброс пароля.
   *
   * Args:
   *   data: Email пользователя, для которого нужно запросить сброс пароля.
   *
   * Returns:
   *   Promise с reset token, временем истечения и сообщением API.
   */
  requestPasswordReset: (data: PasswordResetRequest) =>
    api
      .post<PasswordResetRequestResponse>("/auth/password/reset/request", data)
      .then((r) => r.data),

  /**
   * Подтверждает сброс пароля.
   *
   * Args:
   *   data: Reset token и новый пароль.
   *
   * Returns:
   *   Promise с сообщением API.
   */
  confirmPasswordReset: (data: PasswordResetConfirmRequest) =>
    api
      .post<PasswordResetConfirmResponse>("/auth/password/reset/confirm", data)
      .then((r) => r.data),
};
