import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { foldersApi } from "@/api/folders";
import { friendlyError } from "@/lib/errors";
import { useUpload } from "@/contexts/upload-context";

/**
 * Hook для загрузки папки с сохранением вложенной структуры.
 *
 * Создаёт недостающие директории на backend по данным `webkitRelativePath`,
 * группирует файлы по целевым папкам и добавляет каждую группу в upload queue.
 *
 * Returns:
 *   Объект с методом `uploadFolder`.
 */
export function useFolderUpload() {
  const { enqueue } = useUpload();
  const queryClient = useQueryClient();

  const uploadFolder = useCallback(
    /**
     * Загружает папку в указанную родительскую node.
     *
     * Args:
     *   files: Список файлов, выбранных через folder upload input.
     *   parentNodeId: Идентификатор родительской папки, куда загружается
     *     структура.
     *   folderQueryKey: Query key текущей папки для последующей инвалидации
     *     кэша.
     */
    async (files: File[], parentNodeId: string, folderQueryKey: unknown[]) => {
      const validFiles = files.filter((f) => f.size > 0 && f.webkitRelativePath);
      if (!validFiles.length) return;

      // Собираем все уникальные директории, которые должны существовать.
      // Пример webkitRelativePath: "myproject/src/utils/helper.ts"
      // Нужные dirs: "myproject", "myproject/src", "myproject/src/utils".
      const dirSet = new Set<string>();
      for (const file of validFiles) {
        const parts = file.webkitRelativePath.split("/");
        for (let depth = 1; depth < parts.length; depth++) {
          dirSet.add(parts.slice(0, depth).join("/"));
        }
      }

      // Сортируем от верхнего уровня к нижнему, чтобы родительские папки
      // создавались раньше дочерних.
      const sortedDirs = Array.from(dirSet).sort(
        (a, b) => a.split("/").length - b.split("/").length,
      );

      // Map dirPath → node_id. Пустой путь — исходная папка загрузки.
      const pathNodeId = new Map<string, string>();
      pathNodeId.set("", parentNodeId);

      if (sortedDirs.length > 0) {
        const toastId = toast.loading(`Создание структуры папок (0 / ${sortedDirs.length})…`);
        let done = 0;

        for (const dirPath of sortedDirs) {
          const segments = dirPath.split("/");
          const name = segments[segments.length - 1];
          const parentPath = segments.slice(0, -1).join("/");
          const pid = pathNodeId.get(parentPath);

          if (!pid) {
            // Если родителя не удалось создать, всё поддере
            done++;
            continue;
          }

          try {
            const folder = await foldersApi.create({ name, parent_id: pid });
            pathNodeId.set(dirPath, folder.node_id);
          } catch (err) {
            toast.error(friendlyError(err, { operation: "createFolder", name }));
          }

          done++;
          toast.loading(`Создание структуры папок (${done} / ${sortedDirs.length})…`, {
            id: toastId,
          });
        }

        toast.dismiss(toastId);

        // Показываем созданные папки в текущем view после обновления query.
        queryClient.invalidateQueries({ queryKey: folderQueryKey });
      }

      // Группируем файлы по node_id папки назначения.
      const groups = new Map<string, File[]>();
      for (const file of validFiles) {
        const parts = file.webkitRelativePath.split("/");
        const dirPath = parts.slice(0, -1).join("/");
        const targetId = pathNodeId.get(dirPath);
        if (!targetId) continue;
        if (!groups.has(targetId)) groups.set(targetId, []);
        groups.get(targetId)!.push(file);
      }

      // Каждая группа загружается в свою папку назначения.
      for (const [targetId, groupFiles] of groups) {
        enqueue(groupFiles, targetId, folderQueryKey);
      }
    },
    [enqueue, queryClient],
  );

  return { uploadFolder };
}
