import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronRight, Folder, Loader2 } from "lucide-react";
import { nodesApi } from "@/api/nodes";
import { optimisticallyRemoveNodes } from "@/lib/folderCache";
import { friendlyError } from "@/lib/errors";
import type { NodeListItem } from "@/types/nodes";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/**
 * Элемент навигационного стека выбора папки.
 *
 * `id` — идентификатор папки или `null` для корневого раздела.
 * `name` — отображаемое название папки в хлебных крошках.
 */
interface StackEntry {
  id: string | null;
  name: string;
}

/**
 * Режим работы диалога: перемещение или копирование элементов.
 */
type DialogMode = "move" | "copy";

/**
 * Свойства диалога перемещения.
 *
 * `open` определяет, открыт ли диалог.
 * `onOpenChange` вызывается при изменении состояния открытия.
 * `nodeIds` — идентификаторы перемещаемых элементов.
 * `label` — текстовая подпись перемещаемого элемента или группы элементов.
 * `folderQueryKey` используется для обновления кеша исходной папки.
 * `mode` — `move` (по умолчанию) перемещает элементы, `copy` копирует их.
 * `onMoved` вызывается после успешного перемещения или копирования.
 */
interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  nodeIds: string[];
  label: string;
  folderQueryKey: unknown[];
  mode?: DialogMode;
  onMoved?: () => void;
}

/**
 * Диалог выбора папки для перемещения или копирования элементов.
 *
 * Позволяет перейти по дереву папок, выбрать текущую папку как целевую
 * и переместить или скопировать один или несколько элементов.
 *
 * При перемещении элементы оптимистично удаляются из кеша исходной папки,
 * а при ошибке состояние откатывается. При копировании исходная папка не
 * меняется, поэтому оптимистичного удаления нет — обновляются лишь целевая
 * папка и квота.
 */
export function MoveDialog({
  open,
  onOpenChange,
  nodeIds,
  label,
  folderQueryKey,
  mode = "move",
  onMoved,
}: Props) {
  const isCopy = mode === "copy";
  const queryClient = useQueryClient();
  const [stack, setStack] = useState<StackEntry[]>([{ id: null, name: "Файлы" }]);
  const [moving, setMoving] = useState(false);

  const currentEntry = stack[stack.length - 1];
  const currentFolderId = currentEntry.id;

  const excludeSet = new Set(nodeIds);

  /**
   * Сбрасывает навигационный стек к корню
   * при каждом открытии диалога.
   */
  useEffect(() => {
    if (open) setStack([{ id: null, name: "Файлы" }]);
  }, [open]);

  const { data, isLoading } = useQuery({
    queryKey: ["move-browser", currentFolderId ?? "root"],
    queryFn: async (): Promise<NodeListItem[]> => {
      if (currentFolderId === null) {
        const page = await nodesApi.list();
        return page.items;
      }
      const content = await nodesApi.content(currentFolderId);
      return content.items;
    },
    enabled: open,
    staleTime: 10_000,
  });

  const folders = (data ?? [])
    .filter((i) => i.node_type === "folder" && !excludeSet.has(i.id))
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));

  /**
   * Переходит внутрь выбранной папки,
   * добавляя её в навигационный стек.
   */
  function navigateInto(entry: StackEntry) {
    setStack((prev) => [...prev, entry]);
  }

  /**
   * Возвращает навигацию к выбранному уровню хлебных крошек.
   */
  function goTo(index: number) {
    setStack((prev) => prev.slice(0, index + 1));
  }

  const invalidateDestination = () => {
    if (currentFolderId) {
      queryClient.invalidateQueries({ queryKey: ["nodes", currentFolderId, "content"] });
    } else {
      queryClient.invalidateQueries({ queryKey: ["nodes", "root"] });
    }
  };

  /**
   * Перемещает выбранные элементы в текущую папку.
   *
   * Сначала оптимистично удаляет элементы из исходного кеша,
   * затем выполняет запросы перемещения параллельно.
   *
   * После завершения обновляет исходную и целевую папки,
   * показывает toast-уведомление и вызывает `onMoved`.
   */
  async function handleMove() {
    setMoving(true);

    const rollback = optimisticallyRemoveNodes(queryClient, folderQueryKey, nodeIds);
    onOpenChange(false);

    try {
      const results = await Promise.allSettled(
        nodeIds.map((id) => nodesApi.move(id, { target_parent_id: currentFolderId })),
      );
      const rejected = results.filter(
        (r): r is PromiseRejectedResult => r.status === "rejected",
      );
      const failed = rejected.length;

      if (failed === nodeIds.length) {
        rollback();
        // Показываем конкретную причину (конфликт имён, нет прав и т. д.),
        // подставляя имя только когда перемещается один элемент.
        toast.error(
          friendlyError(rejected[0]?.reason, {
            operation: "move",
            name: nodeIds.length === 1 ? label : undefined,
          }),
        );
        return;
      }

      queryClient.invalidateQueries({ queryKey: folderQueryKey });

      if (failed > 0) {
        toast.error(`Не удалось переместить ${failed} из ${nodeIds.length} элементов`);
      } else if (nodeIds.length === 1) {
        toast.success(`«${label}» перемещено`);
      } else {
        toast.success(`Перемещено ${nodeIds.length} элементов`);
      }
      invalidateDestination();
      onMoved?.();
    } catch (err) {
      rollback();
      toast.error(
        friendlyError(err, {
          operation: "move",
          name: nodeIds.length === 1 ? label : undefined,
        }),
      );
    } finally {
      setMoving(false);
    }
  }

  /**
   * Копирует выбранные элементы в текущую папку.
   *
   * В отличие от перемещения, исходная папка не меняется, поэтому
   * оптимистичного удаления нет. После завершения обновляются целевая папка,
   * кеш исходной папки (для актуализации при копировании «на месте») и квота.
   */
  async function handleCopy() {
    setMoving(true);
    onOpenChange(false);

    try {
      const results = await Promise.allSettled(
        nodeIds.map((id) => nodesApi.copy(id, { target_parent_id: currentFolderId })),
      );
      const rejected = results.filter(
        (r): r is PromiseRejectedResult => r.status === "rejected",
      );
      const failed = rejected.length;

      if (failed === nodeIds.length) {
        toast.error(
          friendlyError(rejected[0]?.reason, {
            operation: "copy",
            name: nodeIds.length === 1 ? label : undefined,
          }),
        );
        return;
      }

      if (failed > 0) {
        toast.error(`Не удалось скопировать ${failed} из ${nodeIds.length} элементов`);
      } else if (nodeIds.length === 1) {
        toast.success(`«${label}» скопировано`);
      } else {
        toast.success(`Скопировано ${nodeIds.length} элементов`);
      }
      queryClient.invalidateQueries({ queryKey: folderQueryKey });
      invalidateDestination();
      queryClient.invalidateQueries({ queryKey: ["quota", "me"] });
      onMoved?.();
    } catch (err) {
      toast.error(
        friendlyError(err, {
          operation: "copy",
          name: nodeIds.length === 1 ? label : undefined,
        }),
      );
    } finally {
      setMoving(false);
    }
  }

  const title = isCopy
    ? nodeIds.length === 1
      ? `Копировать «${label}»`
      : `Копировать ${label}`
    : nodeIds.length === 1
      ? `Переместить «${label}»`
      : `Переместить ${label}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        {/* Путь навигации */}
        <div className="flex flex-wrap items-center gap-0.5 text-sm">
          {stack.map((entry, i) => (
            <span key={i} className="flex items-center gap-0.5">
              {i > 0 && <ChevronRight className="text-muted-foreground h-3.5 w-3.5 shrink-0" />}
              <button
                className={cn(
                  "hover:bg-accent rounded px-1 py-0.5",
                  i === stack.length - 1
                    ? "pointer-events-none font-medium"
                    : "text-muted-foreground",
                )}
                onClick={() => goTo(i)}
              >
                {entry.name}
              </button>
            </span>
          ))}
        </div>

        {/* Список папок */}
        <div className="flex max-h-70 min-h-45 flex-col overflow-y-auto rounded-lg border">
          {isLoading ? (
            <div className="flex flex-1 items-center justify-center py-10">
              <Loader2 className="text-muted-foreground h-5 w-5 animate-spin" />
            </div>
          ) : folders.length === 0 ? (
            <div className="text-muted-foreground flex flex-1 items-center justify-center py-10 text-sm">
              Нет папок
            </div>
          ) : (
            <div className="flex flex-col gap-0.5 p-1">
              {folders.map((folder) => (
                <button
                  key={folder.id}
                  className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm"
                  onClick={() => navigateInto({ id: folder.id, name: folder.name })}
                >
                  <Folder className="h-4 w-4 shrink-0 text-yellow-500" />
                  <span className="min-w-0 flex-1 truncate text-left">{folder.name}</span>
                  <ChevronRight className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
                </button>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" disabled={moving} onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button disabled={moving} onClick={isCopy ? handleCopy : handleMove}>
            {moving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isCopy ? "Копировать сюда" : "Переместить сюда"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
