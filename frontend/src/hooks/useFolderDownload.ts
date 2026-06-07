import { useQueryClient } from "@tanstack/react-query";
import { nodesApi } from "@/api/nodes";
import { foldersApi } from "@/api/folders";
import { useArchiveDownload } from "./useArchiveDownload";

/**
 * Hook для скачивания папки ZIP-архивом.
 *
 * Использует общий механизм `useArchiveDownload`: получает metadata папки,
 * запускает фоновую задачу архивации, ожидает её завершения и инициирует
 * скачивание готового архива.
 *
 * Returns:
 *   Объект с методом `downloadFolder` и идентификатором папки, которая сейчас
 *   архивируется.
 */
export function useFolderDownload() {
  const queryClient = useQueryClient();
  const { run, activeId } = useArchiveDownload();

  /**
   * Запускает скачивание папки ZIP-архивом.
   *
   * Args:
   *   nodeId: Идентификатор node-папки.
   *   folderName: Имя папки, используемое как имя ZIP-архива.
   */
  async function downloadFolder(nodeId: string, folderName: string) {
    await run({
      activeId: nodeId,
      filename: folderName,
      requestTask: async () => {
        // Получаем folder metadata id из node, затем ставим задачу архивации.
        const content = await nodesApi.content(nodeId);
        const resp = await foldersApi.archive(content.folder.id, folderName);
        return resp.task_id;
      },
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ["nodes", nodeId, "content"] });
      },
    });
  }

  return { downloadFolder, downloading: activeId };
}
