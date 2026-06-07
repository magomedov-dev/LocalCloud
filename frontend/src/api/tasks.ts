import api from "@/lib/api";
import type { PageResponse } from "@/types/common";
import type { BackgroundTask, BackgroundTaskListItem } from "@/types/tasks";

/**
 * API-клиент для работы с фоновыми задачами.
 */
export const tasksApi = {
  /**
   * Возвращает список фоновых задач.
   *
   * Args:
   *   params: Параметры пагинации и фильтрации по статусу или типу задачи.
   *
   * Returns:
   *   Promise с пагинированным списком фоновых задач.
   */
  list: (params?: { limit?: number; offset?: number; status?: string; task_type?: string }) =>
    api.get<PageResponse<BackgroundTaskListItem>>("/tasks/", { params }).then((r) => r.data),

  /**
   * Возвращает фоновую задачу по идентификатору.
   *
   * Args:
   *   id: Идентификатор фоновой задачи.
   *
   * Returns:
   *   Promise с полным представлением фоновой задачи.
   */
  get: (id: string) => api.get<BackgroundTask>(`/tasks/${id}`).then((r) => r.data),

  /**
   * Отменяет фоновую задачу.
   *
   * Args:
   *   id: Идентификатор фоновой задачи.
   *   reason: Причина отмены задачи.
   *
   * Returns:
   *   Promise с обновлённой фоновой задачей.
   */
  cancel: (id: string, reason?: string) =>
    api.post<BackgroundTask>(`/tasks/${id}/cancel`, { reason: reason ?? null }).then((r) => r.data),
};
