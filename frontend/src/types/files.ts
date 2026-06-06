import type { NodeRead, NodeListItem } from "./nodes";

/**
 * Статус фоновой обработки файла.
 */
export type FileProcessingStatus = "pending" | "processing" | "ready" | "failed";

/**
 * Статус генерации preview для файла.
 */
export type FilePreviewStatus = "not_required" | "pending" | "generating" | "ready" | "failed";

/**
 * Статус storage-объекта файла.
 */
export type StorageObjectStatus = string;

/**
 * Полное представление файла.
 */
export interface FileRead {
  id: string;
  node_id: string;
  size_bytes: number;
  mime_type: string | null;
  extension: string | null;
  checksum: string | null;
  checksum_algorithm: string | null;
  storage_status: StorageObjectStatus;
  processing_status: FileProcessingStatus;
  preview_status: FilePreviewStatus;
  created_at: string;
  updated_at: string;
  node: NodeRead | null;
  name?: string;
}

/**
 * Краткое представление файла для списков.
 */
export interface FileListItem {
  id: string;
  node_id: string;
  size_bytes: number;
  mime_type: string | null;
  extension: string | null;
  storage_status: StorageObjectStatus;
  processing_status: FileProcessingStatus;
  preview_status: FilePreviewStatus;
  created_at: string;
  updated_at: string;
  node: NodeListItem | null;
}

/**
 * Данные для переименования файла.
 */
export interface FileRenameRequest {
  name: string;
}

/**
 * Ответ API с presigned URL для скачивания файла.
 */
export interface FileDownloadResponse {
  presigned_url: string;
  expires_at: string;
  method: string;
  headers: Record<string, string>;
  file_id?: string;
  filename?: string;
  size_bytes?: number;
  mime_type?: string;
}
