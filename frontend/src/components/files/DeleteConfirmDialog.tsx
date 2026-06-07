import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { nodesApi } from "@/api/nodes";
import { removeNodesFromFolderCache } from "@/lib/folderCache";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Свойства диалога подтверждения удаления.
 *
 * `open` определяет, открыт ли диалог.
 * `onOpenChange` вызывается при изменении состояния открытия.
 * `items` — список элементов, которые нужно переместить в корзину.
 * `folderQueryKey` используется для обновления кеша текущей папки.
 */
interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: Array<{ id: string; name: string }>;
  folderQueryKey: unknown[];
}

/**
 * Диалог подтверждения удаления элементов.
 *
 * Перемещает выбранные файлы или папки в корзину через API,
 * обновляет кеш текущей папки и инвалидирует данные корзины.
 *
 * Во время выполнения запроса диалог остаётся открытым
 * и показывает состояние `Удаление…`.
 */
export function DeleteConfirmDialog({ open, onOpenChange, items, folderQueryKey }: Props) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: async () => {
      const results = await Promise.allSettled(items.map((i) => nodesApi.softDelete(i.id)));
      const succeededIds = items
        .filter((_, i) => results[i].status === "fulfilled")
        .map((i) => i.id);
      return { succeededIds, failed: items.length - succeededIds.length };
    },
    onSuccess: ({ succeededIds, failed }) => {
      if (succeededIds.length === 0) {
        toast.error("Не удалось удалить");
        return;
      }
      removeNodesFromFolderCache(queryClient, folderQueryKey, succeededIds);
      queryClient.invalidateQueries({ queryKey: folderQueryKey });
      queryClient.invalidateQueries({ queryKey: ["trash"] });
      if (failed > 0) {
        toast.error(`Не удалось удалить ${failed} из ${items.length}`);
      } else {
        toast.success(
          items.length === 1
            ? "Перемещено в корзину"
            : `${items.length} элементов перемещено в корзину`,
        );
      }
      onOpenChange(false);
    },
    onError: () => toast.error("Не удалось удалить"),
  });

  const label =
    items.length === 1 ? `«${items[0]?.name}»` : `${items.length} выбранных элемента(ов)`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm" hasDescription>
        <DialogHeader>
          <DialogTitle>Удалить?</DialogTitle>
          <DialogDescription>
            {label} будет перемещено в корзину. Вы сможете восстановить позже.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={mutation.isPending}
            onClick={() => onOpenChange(false)}
          >
            Отмена
          </Button>
          <Button
            variant="destructive"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
            {mutation.isPending ? "Удаление…" : "Удалить"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
