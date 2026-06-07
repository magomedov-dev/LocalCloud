import { downloadsApi } from "@/api/downloads";
import { useArchiveDownload } from "./useArchiveDownload";
import type { NodeListItem } from "@/types/nodes";

/**
 * Hook для bulk-скачивания нескольких nodes одним ZIP-архивом.
 *
 * Использует общий механизм `useArchiveDownload`: запускает фоновую задачу
 * создания архива, ожидает её завершения и инициирует скачивание готового ZIP.
 *
 * Returns:
 *   Объект с методом `downloadItems` и состоянием процесса скачивания архива.
 */
export function useBulkDownload() {
  const { run, active, status, progress } = useArchiveDownload();

  /**
   * Запускает скачивание выбранных nodes одним архивом.
   *
   * Args:
   *   items: Список файлов и/или папок, которые нужно добавить в архив.
   */
  async function downloadItems(items: NodeListItem[]) {
    if (items.length === 0) return;
    const nodeIds = items.map((i) => i.id);
    const archiveName = items.length === 1 ? items[0].name : `archive-${items.length}`;
    await run({
      filename: archiveName,
      requestTask: async () => (await downloadsApi.bulkArchive(nodeIds, archiveName)).task_id,
    });
  }

  return { downloadItems, active, status, progress };
}
