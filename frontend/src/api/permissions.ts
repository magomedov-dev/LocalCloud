import api from "@/lib/api";
import type { PageResponse } from "@/types/common";
import type {
  PermissionGrantRequest,
  NodePermissionRead,
  NodePermissionListItem,
  PermissionRevokeRequest,
} from "@/types/permissions";

/**
 * API-клиент для управления permissions на nodes.
 */
export const permissionsApi = {
  /**
   * Выдаёт доступ к node.
   *
   * Args:
   *   data: Данные для выдачи доступа пользователю.
   *
   * Returns:
   *   Promise с созданным разрешением.
   */
  grant: (data: PermissionGrantRequest) =>
    api.post<NodePermissionRead>("/permissions/grant", data).then((r) => r.data),

  /**
   * Возвращает список разрешений для node.
   *
   * Args:
   *   nodeId: Идентификатор node.
   *   params: Параметры пагинации и фильтрации активных разрешений.
   *
   * Returns:
   *   Promise с пагинированным списком разрешений node.
   */
  listForNode: (
    nodeId: string,
    params?: { limit?: number; offset?: number; active_only?: boolean },
  ) =>
    api
      .get<PageResponse<NodePermissionListItem>>(`/permissions/nodes/${nodeId}`, { params })
      .then((r) => r.data),

  /**
   * Отзывает доступ к node.
   *
   * Args:
   *   data: Данные для отзыва разрешения.
   *
   * Returns:
   *   Promise с отозванным разрешением.
   */
  revoke: (data: PermissionRevokeRequest) =>
    api.post<NodePermissionRead>("/permissions/revoke", data).then((r) => r.data),
};
