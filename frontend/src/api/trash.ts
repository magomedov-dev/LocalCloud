import api from "@/lib/api";
import type { PageResponse } from "@/types/common";
import type {
  TrashItemListItem,
  TrashRestoreRequest,
  TrashRestoreResponse,
  TrashPurgeResponse,
} from "@/types/trash";

/**
 * API-клиент для работы с корзиной.
 */
export const trashApi = {
  /**
   * Возвращает список элементов корзины.
   *
   * Args:
   *   params: Параметры пагинации списка элементов корзины.
   *
   * Returns:
   *   Promise с пагинированным списком элементов корзины.
   */
  list: (params?: { limit?: number; offset?: number }) =>
    api.get<PageResponse<TrashItemListItem>>("/trash/", { params }).then((r) => r.data),

  /**
   * Восстанавливает элемент из корзины.
   *
   * Args:
   *   trashItemId: Идентификатор элемента корзины.
   *   data: Дополнительные параметры восстановления, например целевая папка.
   *
   * Returns:
   *   Promise с результатом восстановления.
   */
  restore: (trashItemId: string, data?: Omit<TrashRestoreRequest, "trash_item_id">) =>
    api
      .post<TrashRestoreResponse>(`/trash/${trashItemId}/restore`, {
        trash_item_id: trashItemId,
        ...data,
      })
      .then((r) => r.data),

  /**
   * Окончательно удаляет элемент из корзины.
   *
   * Args:
   *   trashItemId: Идентификатор элемента корзины.
   *
   * Returns:
   *   Promise с результатом окончательного удаления.
   */
  purge: (trashItemId: string) =>
    api.post<TrashPurgeResponse>(`/trash/${trashItemId}/purge`, {}).then((r) => r.data),

  /**
   * Полностью очищает корзину.
   *
   * Returns:
   *   Promise с результатом очистки корзины.
   */
  empty: () => api.post<TrashPurgeResponse>("/trash/empty", {}).then((r) => r.data),
};
