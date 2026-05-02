import { useState } from "react";
import { Download, FolderInput, Loader2, X, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { nodesApi } from "@/api/nodes";
import { removeNodesFromFolderCache } from "@/lib/folderCache";
import { friendlyError } from "@/lib/errors";
import { useInfoPanel } from "@/contexts/infoPanel-context";
import { useBulkDownload } from "@/hooks/useBulkDownload";
import { MoveDialog } from "./MoveDialog";
import type { NodeListItem } from "@/types/nodes";

/**
 * Свойства панели групповых действий.
 *
 * `items` — выбранные файлы и папки.
 * `folderQueryKey` используется для обновления кеша текущей папки.
 * `onDeselect` вызывается при снятии выбора со всех элементов.
 */
interface Props {
  items: NodeListItem[];
  folderQueryKey: unknown[];
  onDeselect: () => void;
}

/**
 * Панель групповых действий для выбранных элементов.
 *
 * Позволяет скачать, переместить или удалить несколько файлов и папок.
 * Во время скачивания отображает прогресс, а во время удаления —
 * состояние загрузки и блокирует повторные действия.
 */
export function FileMultiActionBar({ items, folderQueryKey, onDeselect }: Props) {
  const queryClient = useQueryClient();
  const { selectedItem: infoPanelItem, closeInfo } = useInfoPanel();
  const [moveOpen, setMoveOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const {
    downloadItems,
    active: downloading,
    status: dlStatus,
    progress: dlProgress,
  } = useBulkDownload();

  const count = items.length;

  /**
   * Возвращает подпись количества элементов
   * с учётом русских форм множественного числа.
   */
  function pluralCount(n: number) {
    if (n === 1) return "1 элемент";
    if (n < 5) return `${n} элемента`;
    return `${n} элементов`;
  }

  /**
   * Перемещает все выбранные элементы в корзину.
   *
   * Выполняет удаление параллельно, удаляет успешно обработанные элементы
   * из кеша текущей папки, обновляет корзину и показывает результат через toast.
   *
   * Если открытая информационная панель относится к удалённому элементу,
   * она закрывается.
   */
  async function handleDeleteAll() {
    const ids = items.map((i) => i.id);
    const deletedIds = new Set(ids);

    setDeleting(true);
    setDeleteOpen(false);

    const results = await Promise.allSettled(ids.map((id) => nodesApi.softDelete(id)));
    const succeededIds = ids.filter((_, i) => results[i].status === "fulfilled");
    const failed = ids.length - succeededIds.length;

    if (succeededIds.length === 0) {
      setDeleting(false);
      const firstError = results.find(
        (r): r is PromiseRejectedResult => r.status === "rejected",
      )?.reason;
      toast.error(
        friendlyError(firstError, {
          operation: "delete",
          name: ids.length === 1 ? items[0]?.name : undefined,
        }),
      );
      return;
    }

    removeNodesFromFolderCache(queryClient, folderQueryKey, succeededIds);
    if (infoPanelItem && deletedIds.has(infoPanelItem.id)) closeInfo();
    onDeselect();
    setDeleting(false);

    queryClient.invalidateQueries({ queryKey: folderQueryKey });
    queryClient.invalidateQueries({ queryKey: ["trash"] });
    if (failed > 0) {
      toast.error(`Не удалось переместить ${failed} из ${count} элементов в корзину`);
    } else {
      toast.success(`${pluralCount(count)} перемещено в корзину`);
    }
  }

  return (
    <>
      <div className="bg-muted/40 flex flex-col gap-1.5 rounded-lg border px-3 py-1.5">
        <div className="flex items-center gap-2">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7 shrink-0"
            onClick={onDeselect}
            aria-label="Снять выделение"
          >
            <X className="h-3.5 w-3.5" />
          </Button>

          <span className="flex-1 truncate text-sm font-medium">
            {pluralCount(count)} <span className="xs:inline hidden">выбрано</span>
          </span>

          <Button
            size="sm"
            variant="outline"
            disabled={downloading || deleting}
            onClick={() => downloadItems(items)}
            title="Скачать"
          >
            {downloading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin sm:mr-2" />
            ) : (
              <Download className="h-3.5 w-3.5 sm:mr-2" />
            )}
            <span className="hidden sm:inline">Скачать</span>
          </Button>

          <Button
            size="sm"
            variant="outline"
            disabled={downloading || deleting}
            onClick={() => setMoveOpen(true)}
            title="Переместить"
          >
            <FolderInput className="h-3.5 w-3.5 sm:mr-2" />
            <span className="hidden sm:inline">Переместить</span>
          </Button>

          <Button
            size="sm"
            variant="destructive"
            disabled={downloading || deleting}
            onClick={() => setDeleteOpen(true)}
            title="Удалить"
          >
            {deleting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin sm:mr-2" />
            ) : (
              <Trash2 className="h-3.5 w-3.5 sm:mr-2" />
            )}
            <span className="hidden sm:inline">{deleting ? "Удаление…" : "Удалить"}</span>
          </Button>
        </div>

        {downloading && (
          <div className="flex flex-col gap-1 pb-0.5">
            <Progress value={dlProgress} className="h-1.5" />
            <span className="text-muted-foreground text-xs">{dlStatus}</span>
          </div>
        )}
      </div>

      <MoveDialog
        open={moveOpen}
        onOpenChange={setMoveOpen}
        nodeIds={items.map((i) => i.id)}
        label={pluralCount(count)}
        folderQueryKey={folderQueryKey}
        onMoved={onDeselect}
      />

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="sm:max-w-sm" hasDescription>
          <DialogHeader>
            <DialogTitle>Удалить {pluralCount(count)}?</DialogTitle>
            <DialogDescription>
              Выбранные элементы будут перемещены в корзину. Вы сможете восстановить их позже.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" disabled={deleting} onClick={() => setDeleteOpen(false)}>
              Отмена
            </Button>
            <Button variant="destructive" disabled={deleting} onClick={handleDeleteAll}>
              {deleting ? (
                <>
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  Удаление…
                </>
              ) : (
                "Удалить"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
