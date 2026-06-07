import api from "@/lib/api";
import type { PageResponse } from "@/types/common";
import type { NodeListItem, NodeMoveRequest } from "@/types/nodes";
import type { FolderContent } from "@/types/folders";
import type { FileDownloadResponse } from "@/types/files";

/**
 * API-клиент для работы с nodes файлового дерева.
 */
export const nodesApi = {
  /**
   * Возвращает список nodes.
   *
   * Args:
   *   params: Параметры фильтрации по родительской папке и пагинации.
   *
   * Returns:
   *   Promise с пагинированным списком nodes.
   */
  list: (params?: { parent_id?: string | null; limit?: number; offset?: number }) =>
    api.get<PageResponse<NodeListItem>>("/nodes/", { params }).then((r) => r.data),

  /**
   * Возвращает содержимое node-папки.
   *
   * Args:
   *   nodeId: Идентификатор node-папки.
   *   params: Параметры пагинации содержимого папки.
   *
   * Returns:
   *   Promise с данными папки, breadcrumbs, элементами и общим количеством.
   */
  content: (nodeId: string, params?: { limit?: number; offset?: number }) =>
    api.get<FolderContent>(`/nodes/${nodeId}/content`, { params }).then((r) => r.data),

  /**
   * Переименовывает node.
   *
   * Args:
   *   id: Идентификатор node.
   *   name: Новое имя node.
   *
   * Returns:
   *   Promise с ответом API.
   */
  rename: (id: string, name: string) =>
    api.post(`/nodes/${id}/rename`, { name }).then((r) => r.data),

  /**
   * Возвращает presigned URL для скачивания node.
   *
   * Args:
   *   id: Идентификатор node.
   *   forceDownload: Нужно ли принудительно скачать файл вместо inline-отображения.
   *
   * Returns:
   *   Promise с presigned URL и metadata для скачивания.
   */
  download: (id: string, forceDownload = true) =>
    api
      .post<FileDownloadResponse>(
        `/nodes/${id}/download`,
        {},
        { params: { force_download: forceDownload } },
      )
      .then((r) => r.data),

  /**
   * Возвращает presigned URL thumbnail для node.
   *
   * Args:
   *   id: Идентификатор node.
   *
   * Returns:
   *   Promise с presigned URL и metadata thumbnail.
   */
  thumbnail: (id: string) =>
    api.get<FileDownloadResponse>(`/nodes/${id}/thumbnail`).then((r) => r.data),

  /**
   * Возвращает thumbnail URL для набора nodes.
   *
   * Args:
   *   nodeIds: Идентификаторы nodes, для которых нужно получить thumbnails.
   *   signal: Abort signal для отмены запроса.
   *
   * Returns:
   *   Promise со словарём `nodeId -> thumbnail URL | null`.
   */
  thumbnailsBatch: (nodeIds: string[], signal?: AbortSignal) =>
    api
      .post<{
        thumbnails: Record<string, string | null>;
      }>("/nodes/thumbnails/batch", { node_ids: nodeIds }, { signal })
      .then((r) => r.data.thumbnails),

  /**
   * Перемещает node в корзину.
   *
   * Args:
   *   id: Идентификатор node.
   *
   * Returns:
   *   Promise с ответом API.
   */
  softDelete: (id: string) => api.delete(`/nodes/${id}`).then((r) => r.data),

  /**
   * Ищет nodes по строке запроса.
   *
   * Args:
   *   query: Поисковая строка.
   *   params: Параметры пагинации результатов поиска.
   *
   * Returns:
   *   Promise с пагинированным списком найденных nodes.
   */
  search: (query: string, params?: { limit?: number; offset?: number }) =>
    api
      .get<PageResponse<NodeListItem>>("/nodes/search", { params: { query, ...params } })
      .then((r) => r.data),

  /**
   * Перемещает node в другую папку.
   *
   * Args:
   *   id: Идентификатор node.
   *   data: Данные с целевой родительской папкой.
   *
   * Returns:
   *   Promise с ответом API.
   */
  move: (id: string, data: NodeMoveRequest) =>
    api.post(`/nodes/${id}/move`, data).then((r) => r.data),

  /**
   * Формирует URL для streaming-доступа к node.
   *
   * Args:
   *   id: Идентификатор node.
   *
   * Returns:
   *   URL streaming endpoint.
   */
  streamUrl: (id: string) => `/api/v1/nodes/${id}/stream`,
};
