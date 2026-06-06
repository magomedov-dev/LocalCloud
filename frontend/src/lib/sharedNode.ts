import type { NodeListItem } from "@/types/nodes";
import type { SharedNodeItem } from "@/types/permissions";

/**
 * Приводит элемент «Доступно мне» к форме NodeListItem.
 *
 * Нужно для переиспользования существующих компонентов (превью, миниатюры,
 * иконки), которые работают с `NodeListItem`. Поля, которых нет у общего узла,
 * заполняются безопасными значениями: `depth` = 0, `is_deleted` = false.
 */
export function toNodeListItem(item: SharedNodeItem): NodeListItem {
  return {
    id: item.id,
    owner_id: item.owner_id,
    parent_id: item.parent_id,
    name: item.name,
    node_type: item.node_type,
    visibility: item.visibility,
    path: item.path,
    depth: 0,
    created_at: item.created_at,
    updated_at: item.updated_at,
    is_deleted: false,
    file_size_bytes: item.file_size_bytes,
    file_mime_type: item.file_mime_type,
  };
}
