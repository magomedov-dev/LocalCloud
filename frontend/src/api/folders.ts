import api from "@/lib/api";
import type {
  FolderCreateRequest,
  FolderRead,
  FolderArchiveResponse,
} from "@/types/folders";

/**
 * API-клиент для работы с папками.
 */
export const foldersApi = {
  /**
   * Создаёт новую папку.
   *
   * Args:
   *   data: Данные для создания папки.
   *
   * Returns:
   *   Promise с созданной папкой.
   */
  create: (data: FolderCreateRequest) =>
    api.post<FolderRead>("/folders/", data).then((r) => r.data),

  /**
   * Запускает фоновое создание ZIP-архива папки.
   *
   * Args:
   *   folderId: Идентификатор папки для архивации.
   *   archiveName: Пользовательское имя архива.
   *
   * Returns:
   *   Promise с данными фоновой задачи архивации.
   */
  archive: (folderId: string, archiveName?: string) =>
    api
      .post<FolderArchiveResponse>(`/folders/${folderId}/archive`, {
        folder_id: folderId,
        archive_name: archiveName ?? null,
        include_deleted: false,
      })
      .then((r) => r.data),
};
