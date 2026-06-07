import api from "@/lib/api";
import type { PageResponse } from "@/types/common";
import type {
  RegistrationCreateRequest,
  RegistrationRead,
  RegistrationApproveRequest,
  RegistrationApproveResponse,
  RegistrationRejectRequest,
} from "@/types/registration";

/**
 * API-клиент для работы с заявками на регистрацию.
 */
export const registrationApi = {
  /**
   * Создаёт заявку на регистрацию.
   *
   * Args:
   *   data: Email, username и пароль нового пользователя.
   *
   * Returns:
   *   Promise с созданной заявкой на регистрацию.
   */
  create: (data: RegistrationCreateRequest) =>
    api.post<RegistrationRead>("/registration/requests", data).then((r) => r.data),

  /**
   * Возвращает список заявок на регистрацию.
   *
   * Args:
   *   params: Параметры пагинации и фильтрации по статусу.
   *
   * Returns:
   *   Promise с пагинированным списком заявок на регистрацию.
   */
  list: (params?: { limit?: number; offset?: number; status?: string }) =>
    api
      .get<PageResponse<RegistrationRead>>("/registration/requests", { params })
      .then((r) => r.data),

  /**
   * Одобряет заявку на регистрацию.
   *
   * Args:
   *   id: Идентификатор заявки на регистрацию.
   *   data: Параметры одобрения заявки.
   *
   * Returns:
   *   Promise с обновлённой заявкой и идентификатором созданного пользователя.
   */
  approve: (id: string, data: RegistrationApproveRequest = {}) =>
    api
      .post<RegistrationApproveResponse>(`/registration/requests/${id}/approve`, data)
      .then((r) => r.data),

  /**
   * Отклоняет заявку на регистрацию.
   *
   * Args:
   *   id: Идентификатор заявки на регистрацию.
   *   data: Причина отклонения и опциональный комментарий администратора.
   *
   * Returns:
   *   Promise с ответом API.
   */
  reject: (id: string, data: RegistrationRejectRequest) =>
    api.post(`/registration/requests/${id}/reject`, data).then((r) => r.data),
};
