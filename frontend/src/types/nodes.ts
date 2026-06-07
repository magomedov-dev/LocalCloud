/**
 * Тип node в файловом дереве.
 */
export type NodeType = "file" | "folder";

/**
 * Видимость node.
 */
export type NodeVisibility = "private" | "shared" | "public";

/**
 * Полное представление node.
 */
export interface NodeRead {
  id: string;
  owner_id: string;
  parent_id: string | null;
  name: string;
  node_type: NodeType;
  visibility: NodeVisibility;
  path: string;
  depth: number;
  created_by: string | null;
  updated_by: string | null;
  deleted_by: string | null;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
  deleted_at: string | null;
}

/**
 * Краткое представление node для списков.
 */
export interface NodeListItem {
  id: string;
  owner_id: string;
  parent_id: string | null;
  name: string;
  node_type: NodeType;
  visibility: NodeVisibility;
  path: string;
  depth: number;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
  file_size_bytes?: number | null;
  file_mime_type?: string | null;
}

/**
 * Данные для перемещения node.
 */
export interface NodeMoveRequest {
  target_parent_id: string | null;
}
