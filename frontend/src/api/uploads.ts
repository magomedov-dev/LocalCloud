import api from "@/lib/api";
import type {
  UploadSessionCreateRequest,
  UploadSessionRead,
  PresignedPartsResponse,
  UploadPartCompleteRequest,
  UploadCompleteRequest,
  UploadCompleteResponse,
} from "@/types/uploads";

/**
 * API-клиент для работы с multipart upload-сессиями.
 */
export const uploadsApi = {
  /**
   * Создаёт multipart upload-сессию.
   *
   * Args:
   *   data: Данные загружаемого файла и параметры multipart upload.
   *
   * Returns:
   *   Promise с созданной upload-сессией.
   */
  create: (data: UploadSessionCreateRequest) =>
    api.post<UploadSessionRead>("/uploads/", data).then((r) => r.data),

  /**
   * Возвращает presigned URL для загрузки частей multipart upload.
   *
   * Args:
   *   id: Идентификатор upload-сессии.
   *
   * Returns:
   *   Promise со списком presigned URL для частей upload.
   */
  getPresignedParts: (id: string) =>
    api.post<PresignedPartsResponse>(`/uploads/${id}/parts/presigned`).then((r) => r.data),

  /**
   * Помечает часть upload как загруженную.
   *
   * Args:
   *   id: Идентификатор upload-сессии.
   *   partNumber: Номер загруженной части.
   *   data: ETag и размер загруженной части.
   *
   * Returns:
   *   Promise с ответом API.
   */
  completePart: (id: string, partNumber: number, data: UploadPartCompleteRequest) =>
    api.post(`/uploads/${id}/parts/${partNumber}/complete`, data).then((r) => r.data),

  /**
   * Завершает multipart upload.
   *
   * Args:
   *   id: Идентификатор upload-сессии.
   *   data: Список загруженных частей для финализации upload.
   *
   * Returns:
   *   Promise с результатом завершения upload.
   */
  complete: (id: string, data: UploadCompleteRequest) =>
    api.post<UploadCompleteResponse>(`/uploads/${id}/complete`, data).then((r) => r.data),

  /**
   * Отменяет multipart upload-сессию.
   *
   * Endpoint берёт `upload_session_id` из path, но body-модель всё ещё требует
   * это поле, поэтому оно отправляется в теле запроса, чтобы backend не вернул
   * `422 Unprocessable Entity`.
   *
   * Args:
   *   id: Идентификатор upload-сессии.
   *   reason: Причина отмены upload-сессии.
   *
   * Returns:
   *   Promise с ответом API.
   */
  abort: (id: string, reason?: string) =>
    api
      .post(`/uploads/${id}/abort`, { upload_session_id: id, reason: reason ?? null })
      .then((r) => r.data),
};
