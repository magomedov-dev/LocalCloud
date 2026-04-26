import type { NodeListItem, NodeRead } from "./nodes";

/**
 * Данные для создания папки.
 */
export interface FolderCreateRequest {
  name: string;
  parent_id?: string | null;
}

/**
 * Данные для частичного обновления папки.
 */
export interface FolderPatchRequest {
  name?: string;
}

/**
 * Ответ API после запуска фоновой задачи архивации папки.
 */
export interface FolderArchiveResponse {
  task_id: string;
  status: string;
  message: string;
}

/**
 * Полное представление папки.
 */
export interface FolderRead {
  id: string;
  node_id: string;
  description: string | null;
  color: string | null;
  created_at: string;
  updated_at: string;
  node: NodeRead | null;
}

/**
 * Содержимое папки.
 */
export interface FolderContent {
  folder: FolderRead;
  breadcrumbs: NodeListItem[];
  items: NodeListItem[];
  total: number;
}
