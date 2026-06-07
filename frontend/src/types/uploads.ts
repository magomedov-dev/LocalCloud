/**
 * Статус upload-сессии.
 */
export type UploadSessionStatus =
  | "created"
  | "uploading"
  | "completed"
  | "failed"
  | "aborted"
  | "expired";

/**
 * Данные для создания multipart upload-сессии.
 */
export interface UploadSessionCreateRequest {
  parent_node_id: string;
  filename: string;
  file_size_bytes: number;
  parts_count: number;
  mime_type?: string | null;
  part_size_bytes?: number | null;
  checksum?: string | null;
  checksum_algorithm?: string | null;
}

/**
 * Представление upload-сессии.
 */
export interface UploadSessionRead {
  id: string;
  user_id: string;
  parent_node_id: string;
  file_name: string;
  file_size_bytes: number;
  part_size_bytes: number;
  mime_type: string | null;
  status: UploadSessionStatus;
  parts_count: number;
  uploaded_parts_count: number;
  uploaded_bytes: number;
  expires_at: string;
  completed_at: string | null;
  created_at: string;
  progress_percent: number;
  is_completed: boolean;
  is_terminal: boolean;
}

/**
 * Presigned URL для загрузки одной части multipart upload.
 */
export interface PresignedPart {
  part_number: number;
  url: string;
  headers: Record<string, string>;
}

/**
 * Ответ API со списком presigned URL для частей upload.
 */
export interface PresignedPartsResponse {
  parts: PresignedPart[];
}

/**
 * Данные о завершённой части upload.
 */
export interface UploadPartCompleteRequest {
  part_number: number;
  etag: string;
  size_bytes: number;
}

/**
 * Данные части для финализации multipart upload.
 */
export interface UploadCompletePart {
  part_number: number;
  etag: string;
  size_bytes: number;
}

/**
 * Данные для завершения multipart upload.
 */
export interface UploadCompleteRequest {
  upload_session_id: string;
  parts: UploadCompletePart[];
}

/**
 * Ответ API после завершения multipart upload.
 */
export interface UploadCompleteResponse {
  upload_session: UploadSessionRead;
  file_id: string | null;
  node_id: string | null;
  message: string;
}
