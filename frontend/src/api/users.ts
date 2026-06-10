import api from "@/lib/api";
import type { PageResponse } from "@/types/common";
import type { UserRead, UserListItem, UserLookupItem } from "@/types/users";

/**
 * API-клиент для управления пользователями.
 */
export const usersApi = {
  /**
   * Возвращает список пользователей.
   *
   * Args:
   *   params: Параметры пагинации, фильтрации по статусу и поиска.
   *
   * Returns:
   *   Promise с пагинированным списком пользователей.
   */
  list: (params?: { limit?: number; offset?: number; status?: string; search?: string }) =>
    api.get<PageResponse<UserListItem>>("/users", { params }).then((r) => r.data),

  /**
   * Возвращает пользователя по идентификатору.
   *
   * Args:
   *   id: Идентификатор пользователя.
   *
   * Returns:
   *   Promise с полным представлением пользователя.
   */
  get: (id: string) => api.get<UserRead>(`/users/${id}`).then((r) => r.data),

  /**
   * Ищет активных пользователей по email или username для выдачи доступа.
   *
   * Доступно любому авторизованному пользователю; отдаёт минимум полей.
   * Запрос короче двух символов backend трактует как пустой результат.
   *
   * Args:
   *   query: Строка поиска по email или username.
   *
   * Returns:
   *   Promise со списком найденных пользователей.
   */
  lookup: (query: string) =>
    api
      .get<UserLookupItem[]>("/users/lookup", { params: { query } })
      .then((r) => r.data),

  /**
   * Блокирует пользователя.
   *
   * Args:
   *   id: Идентификатор пользователя.
   *   block_reason: Причина блокировки пользователя.
   *
   * Returns:
   *   Promise с обновлённым пользователем.
   */
  block: (id: string, block_reason?: string) =>
    api
      .post<UserRead>(`/users/${id}/block`, { block_reason: block_reason ?? null })
      .then((r) => r.data),

  /**
   * Разблокирует пользователя.
   *
   * Args:
   *   id: Идентификатор пользователя.
   *
   * Returns:
   *   Promise с обновлённым пользователем.
   */
  unblock: (id: string) => api.post<UserRead>(`/users/${id}/unblock`).then((r) => r.data),

  /**
   * Одобряет пользователя.
   *
   * Args:
   *   id: Идентификатор пользователя.
   *
   * Returns:
   *   Promise с обновлённым пользователем.
   */
  approve: (id: string) => api.post<UserRead>(`/users/${id}/approve`).then((r) => r.data),

  /**
   * Отклоняет пользователя.
   *
   * Args:
   *   id: Идентификатор пользователя.
   *   rejection_reason: Причина отклонения пользователя.
   *
   * Returns:
   *   Promise с обновлённым пользователем.
   */
  reject: (id: string, rejection_reason: string) =>
    api.post<UserRead>(`/users/${id}/reject`, { rejection_reason }).then((r) => r.data),

  /**
   * Удаляет пользователя.
   *
   * Args:
   *   id: Идентификатор пользователя.
   *
   * Returns:
   *   Promise с обновлённым пользователем.
   */
  delete: (id: string) => api.delete<UserRead>(`/users/${id}`).then((r) => r.data),

  /**
   * Изменяет пароль пользователя.
   *
   * Args:
   *   id: Идентификатор пользователя.
   *   new_password: Новый пароль пользователя.
   *
   * Returns:
   *   Promise с обновлённым пользователем.
   */
  changePassword: (id: string, new_password: string) =>
    api.post<UserRead>(`/users/${id}/change-password`, { new_password }).then((r) => r.data),
};
