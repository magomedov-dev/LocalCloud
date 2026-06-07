import api from "@/lib/api";
import type { PageResponse } from "@/types/common";
import type {
  PublicLinkCreateRequest,
  PublicLinkRead,
  PublicLinkListItem,
  PublicLinkRevokeRequest,
  PublicLinkPublicRead,
  PublicLinkDownloadResponse,
  PublicLinkFolderArchiveResponse,
} from "@/types/public-links";

/**
 * API-клиент для работы с публичными ссылками.
 */
export const publicLinksApi = {
  /**
   * Создаёт публичную ссылку.
   *
   * Args:
   *   data: Данные для создания публичной ссылки.
   *
   * Returns:
   *   Promise с созданной публичной ссылкой.
   */
  create: (data: PublicLinkCreateRequest) =>
    api.post<PublicLinkRead>("/public-links/", data).then((r) => r.data),

  /**
   * Возвращает список публичных ссылок.
   *
   * Args:
   *   params: Параметры пагинации и фильтрации публичных ссылок.
   *
   * Returns:
   *   Promise с пагинированным списком публичных ссылок.
   */
  list: (params?: { limit?: number; offset?: number; node_id?: string; is_active?: boolean }) =>
    api.get<PageResponse<PublicLinkListItem>>("/public-links/", { params }).then((r) => r.data),

  /**
   * Возвращает активные публичные ссылки для node.
   *
   * Args:
   *   nodeId: Идентификатор node.
   *
   * Returns:
   *   Promise с пагинированным списком активных публичных ссылок node.
   */
  listForNode: (nodeId: string) =>
    api
      .get<PageResponse<PublicLinkListItem>>("/public-links/", {
        params: { node_id: nodeId, is_active: true, limit: 10 },
      })
      .then((r) => r.data),

  /**
   * Возвращает публичную ссылку по идентификатору.
   *
   * Args:
   *   id: Идентификатор публичной ссылки.
   *
   * Returns:
   *   Promise с полным представлением публичной ссылки.
   */
  get: (id: string) => api.get<PublicLinkRead>(`/public-links/${id}`).then((r) => r.data),

  /**
   * Возвращает публичное представление ссылки по token.
   *
   * Args:
   *   token: Token публичной ссылки.
   *
   * Returns:
   *   Promise с публичным представлением ссылки.
   */
  getPublic: (token: string) =>
    api.get<PublicLinkPublicRead>(`/public-links/public/${token}`).then((r) => r.data),

  /**
   * Возвращает presigned URL для скачивания файла по публичной ссылке.
   *
   * Args:
   *   token: Token публичной ссылки.
   *
   * Returns:
   *   Promise с presigned URL и metadata для скачивания.
   */
  download: (token: string) =>
    api
      .post<PublicLinkDownloadResponse>(`/public-links/public/${token}/download`)
      .then((r) => r.data),

  /**
   * Отзывает публичную ссылку.
   *
   * Args:
   *   id: Идентификатор публичной ссылки.
   *   data: Данные для отзыва публичной ссылки.
   *
   * Returns:
   *   Promise с обновлённой публичной ссылкой.
   */
  revoke: (id: string, data: PublicLinkRevokeRequest = {}) =>
    api.post<PublicLinkRead>(`/public-links/${id}/revoke`, data).then((r) => r.data),

  /**
   * Запускает фоновое создание архива папки по публичной ссылке.
   *
   * Args:
   *   token: Token публичной ссылки на папку.
   *
   * Returns:
   *   Promise с состоянием задачи создания архива.
   */
  startFolderArchive: (token: string) =>
    api
      .post<PublicLinkFolderArchiveResponse>(`/public-links/public/${token}/folder-download`, {
        token,
      })
      .then((r) => r.data),

  /**
   * Проверяет состояние фоновой задачи создания архива папки.
   *
   * Args:
   *   token: Token публичной ссылки на папку.
   *   taskId: Идентификатор фоновой задачи создания архива.
   *
   * Returns:
   *   Promise с текущим состоянием задачи и ссылкой на архив, если он готов.
   */
  pollFolderArchive: (token: string, taskId: string) =>
    api
      .get<PublicLinkFolderArchiveResponse>(
        `/public-links/public/${token}/folder-download/${taskId}`,
      )
      .then((r) => r.data),
};
