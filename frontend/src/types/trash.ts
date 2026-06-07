import type { NodeListItem } from "./nodes";

/**
 * Статус элемента корзины.
 */
export type TrashItemStatus = "in_trash" | "restored" | "purged";

/**
 * Краткое представление элемента корзины.
 */
export interface TrashItemListItem {
  id: string;
  node_id: string;
  owner_id: string;
  deleted_by: string | null;
  original_parent_id: string | null;
  original_path: string;
  status: TrashItemStatus;
  deleted_at: string;
  expires_at: string | null;
  restore_available: boolean;
  purged_at: string | null;
  node: NodeListItem | null;
}

/**
 * Данные для восстановления элемента из корзины.
 */
export interface TrashRestoreRequest {
  trash_item_id?: string;
  node_id?: string;
  target_parent_id?: string | null;
}

/**
 * Ответ API после восстановления элемента из корзины.
 */
export interface TrashRestoreResponse {
  message: string;
  node_id: string;
  restored_path: string | null;
}

/**
 * Ответ API после окончательного удаления элемента из корзины.
 */
export interface TrashPurgeResponse {
  message: string;
}
