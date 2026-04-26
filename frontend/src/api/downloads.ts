import api from "@/lib/api";
import type { FileDownloadResponse } from "@/types/files";
import type { FolderArchiveResponse } from "@/types/folders";

/**
 * API-клиент для скачивания архивов.
 */
export const downloadsApi = {
  /**
   * Возвращает presigned URL для скачивания готового архива.
   *
   * Args:
   *   taskId: Идентификатор фоновой задачи создания архива.
   *   filename: Имя файла архива, которое нужно использовать при скачивании.
   *
   * Returns:
   *   Promise с presigned URL и metadata для скачивания архива.
   */
  archiveUrl: (taskId: string, filename?: string) =>
    api
      .post<FileDownloadResponse>(`/downloads/archive/${taskId}`, null, {
        params: { force_download: true, ...(filename ? { filename } : {}) },
      })
      .then((r) => r.data),

  /**
   * Запускает фоновое создание архива для набора nodes.
   *
   * Args:
   *   nodeIds: Идентификаторы файлов и/или папок, которые нужно добавить
   *     в архив.
   *   archiveName: Пользовательское имя архива.
   *
   * Returns:
   *   Promise с данными созданной фоновой задачи архивации.
   */
  bulkArchive: (nodeIds: string[], archiveName?: string) =>
    api
      .post<FolderArchiveResponse>("/downloads/bulk-archive", {
        node_ids: nodeIds,
        ...(archiveName ? { archive_name: archiveName } : {}),
      })
      .then((r) => r.data),
};
