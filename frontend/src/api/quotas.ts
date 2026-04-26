import api from "@/lib/api";
import type {
  UserQuota,
  QuotaUsageRead,
  UserQuotaUpdate,
  QuotaIncreaseRequest,
  QuotaIncreaseRequestStatus,
  ServerStorage,
} from "@/types/quotas";

/**
 * API-клиент для работы с пользовательскими квотами.
 */
export const quotasApi = {
  /**
   * Возвращает сводку использования квоты текущего пользователя.
   *
   * Returns:
   *   Promise со сводкой использования квоты.
   */
  me: () => api.get<QuotaUsageRead>("/quotas/me").then((r) => r.data),

  /**
   * Возвращает сводку использования квоты пользователя.
   *
   * Args:
   *   userId: Идентификатор пользователя.
   *
   * Returns:
   *   Promise со сводкой использования квоты пользователя.
   */
  getByUserId: (userId: string) =>
    api.get<QuotaUsageRead>(`/quotas/users/${userId}`).then((r) => r.data),

  /**
   * Обновляет квоту пользователя.
   *
   * Args:
   *   userId: Идентификатор пользователя.
   *   data: Новые значения лимитов квоты.
   *
   * Returns:
   *   Promise с обновлённой квотой пользователя.
   */
  updateByUserId: (userId: string, data: UserQuotaUpdate) =>
    api.put<UserQuota>(`/quotas/users/${userId}`, data).then((r) => r.data),

  /**
   * Возвращает сводку состояния серверного хранилища.
   *
   * Returns:
   *   Promise со статистикой серверного хранилища.
   */
  serverStorage: () => api.get<ServerStorage>("/quotas/server-storage").then((r) => r.data),

  /**
   * Возвращает список запросов на увеличение квоты.
   *
   * Args:
   *   params: Параметры фильтрации по статусу и пагинации.
   *
   * Returns:
   *   Promise со списком запросов на увеличение квоты.
   */
  listIncreaseRequests: (params?: {
    status?: QuotaIncreaseRequestStatus | "";
    limit?: number;
    offset?: number;
  }) =>
    api.get<QuotaIncreaseRequest[]>("/quotas/increase-requests", { params }).then((r) => r.data),

  /**
   * Одобряет запрос на увеличение квоты.
   *
   * Args:
   *   id: Идентификатор запроса на увеличение квоты.
   *
   * Returns:
   *   Promise с обновлённым запросом на увеличение квоты.
   */
  approveIncreaseRequest: (id: string) =>
    api.post<QuotaIncreaseRequest>(`/quotas/increase-requests/${id}/approve`).then((r) => r.data),

  /**
   * Отклоняет запрос на увеличение квоты.
   *
   * Args:
   *   id: Идентификатор запроса на увеличение квоты.
   *   data: Комментарий администратора к отклонению.
   *
   * Returns:
   *   Promise с обновлённым запросом на увеличение квоты.
   */
  rejectIncreaseRequest: (id: string, data: { admin_comment: string | null }) =>
    api
      .post<QuotaIncreaseRequest>(`/quotas/increase-requests/${id}/reject`, data)
      .then((r) => r.data),
};
