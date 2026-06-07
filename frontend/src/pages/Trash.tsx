import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";
import { trashApi } from "@/api/trash";
import { useBreadcrumb } from "@/contexts/breadcrumb-context";
import { FileIcon } from "@/components/files/FileIcon";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { TrashItemListItem } from "@/types/trash";

const QUERY_KEY = ["trash"];

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

// ── Single row ────────────────────────────────────────────────────────────────

interface RowProps {
  item: TrashItemListItem;
  selected: boolean;
  isBatchRunning: boolean;
  onToggle: (id: string) => void;
}

function TrashRow({ item, selected, isBatchRunning, onToggle }: RowProps) {
  const queryClient = useQueryClient();
  const [purgeOpen, setPurgeOpen] = useState(false);

  const restore = useMutation({
    mutationFn: () => trashApi.restore(item.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["nodes"] });
      toast.success("Восстановлено");
    },
    onError: () => toast.error("Не удалось восстановить"),
  });

  const purge = useMutation({
    mutationFn: () => trashApi.purge(item.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["quota", "me"] });
      toast.success("Удалено навсегда");
      setPurgeOpen(false);
    },
    onError: () => toast.error("Не удалось удалить"),
  });

  const node = item.node;
  const disabled = isBatchRunning;

  return (
    <>
      <div className="hover:bg-muted/40 flex items-center gap-3 rounded-lg border px-4 py-3 transition-opacity duration-150">
        <Checkbox
          checked={selected}
          onCheckedChange={() => onToggle(item.id)}
          disabled={disabled}
          aria-label={`Выбрать ${node?.name ?? item.original_path}`}
        />

        <FileIcon nodeType={node?.node_type ?? "file"} className="h-5 w-5 shrink-0" />

        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">
            {node?.name ?? item.original_path.split("/").pop() ?? "—"}
          </span>
          <span className="text-muted-foreground truncate text-xs">{item.original_path}</span>
        </div>

        <span className="text-muted-foreground shrink-0 text-xs">
          {formatDate(item.deleted_at)}
        </span>

        <div className="flex shrink-0 items-center gap-1">
          {item.restore_available && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              disabled={disabled || restore.isPending}
              onClick={() => restore.mutate()}
              title="Восстановить"
            >
              <RotateCcw className="h-4 w-4" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="text-destructive hover:text-destructive h-7 w-7"
            disabled={disabled}
            onClick={() => setPurgeOpen(true)}
            title="Удалить навсегда"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <Dialog open={purgeOpen} onOpenChange={setPurgeOpen}>
        <DialogContent className="sm:max-w-sm" hasDescription>
          <DialogHeader>
            <DialogTitle>Удалить навсегда?</DialogTitle>
            <DialogDescription>
              «{node?.name ?? item.original_path}» будет удалён без возможности восстановления.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPurgeOpen(false)}>
              Отмена
            </Button>
            <Button variant="destructive" disabled={purge.isPending} onClick={() => purge.mutate()}>
              {purge.isPending ? "Удаление…" : "Удалить навсегда"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function TrashPage() {
  const { setCrumbs } = useBreadcrumb();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [emptyOpen, setEmptyOpen] = useState(false);

  // Идентификаторы, оптимистично удалённые из списка в текущей пачке.
  const [deletedIds, setDeletedIds] = useState<Set<string>>(new Set());
  const [emptyingTrash, setEmptyingTrash] = useState(false);
  const [bulkPurging, setBulkPurging] = useState(false);
  const [bulkPurgeTotal, setBulkPurgeTotal] = useState(0);
  const [bulkRestoring, setBulkRestoring] = useState(false);

  useEffect(() => {
    setCrumbs([{ label: "Корзина" }]);
  }, [setCrumbs]);

  const { data, isLoading } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => trashApi.list({ limit: 100 }),
    staleTime: 30_000,
  });

  const items = data?.items ?? [];
  // Показываем только элементы, которые ещё не удалены в текущей пачке.
  const visibleItems = items.filter((i) => !deletedIds.has(i.id));

  const isBatchRunning = emptyingTrash || bulkPurging || bulkRestoring;

  // ── Empty trash — single batch API call, list clears at once ──
  async function handleEmptyTrash() {
    setEmptyOpen(false);
    setEmptyingTrash(true);

    // Очищаем весь список за один раз (одно плавное исчезновение через анимацию строки).
    setDeletedIds(new Set(items.map((i) => i.id)));

    try {
      await trashApi.empty();
      toast.success("Корзина очищена");
    } catch {
      setDeletedIds(new Set()); // rollback — items reappear
      toast.error("Не удалось очистить корзину");
    } finally {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["quota", "me"] });
      setEmptyingTrash(false);
    }
  }

  // ── Bulk purge (selected subset) — parallel calls, items vanish as each completes ──
  async function handleBulkPurge() {
    const ids = [...selected];
    setSelected(new Set());
    setBulkPurgeTotal(ids.length);
    setBulkPurging(true);

    let failed = 0;
    await Promise.all(
      ids.map(async (id) => {
        try {
          await trashApi.purge(id);
          setDeletedIds((prev) => new Set([...prev, id]));
        } catch {
          failed++;
        }
      }),
    );

    setBulkPurging(false);
    queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: ["quota", "me"] });
    if (failed > 0) {
      toast.error(`Не удалось удалить ${failed} элем.`);
    } else {
      toast.success("Удалено навсегда");
    }
  }

  // ── Bulk restore (selected subset) — parallel calls, rows vanish as each completes ──
  async function handleBulkRestore() {
    const ids = visibleItems
      .filter((i) => selected.has(i.id) && i.restore_available)
      .map((i) => i.id);
    if (ids.length === 0) return;
    setSelected(new Set());
    setBulkRestoring(true);

    let failed = 0;
    await Promise.all(
      ids.map(async (id) => {
        try {
          await trashApi.restore(id);
          setDeletedIds((prev) => new Set([...prev, id]));
        } catch {
          failed++;
        }
      }),
    );

    setBulkRestoring(false);
    queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: ["nodes"] });
    if (failed > 0) {
      toast.error(`Не удалось восстановить ${failed} элем.`);
    } else {
      toast.success("Файлы восстановлены");
    }
  }

  function toggleItem(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === visibleItems.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visibleItems.map((i) => i.id)));
    }
  }

  const allSelected = visibleItems.length > 0 && selected.size === visibleItems.length;
  const someSelected = selected.size > 0;
  const restorable = visibleItems.filter((i) => selected.has(i.id) && i.restore_available).length;

  const deletedCount = deletedIds.size;

  return (
    <div className="flex flex-col gap-4">
      {/* Заголовок */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Корзина</h1>
        {items.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            className="text-destructive hover:text-destructive"
            disabled={isBatchRunning}
            onClick={() => setEmptyOpen(true)}
          >
            {emptyingTrash ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Очистка…
              </>
            ) : (
              <>
                <Trash2 className="mr-2 h-4 w-4" />
                Очистить корзину
              </>
            )}
          </Button>
        )}
      </div>

      {/* Панель массовых действий */}
      {someSelected && (
        <div className="bg-muted/50 flex items-center gap-2 rounded-lg border px-4 py-2">
          <span className="text-muted-foreground flex-1 text-sm">Выбрано: {selected.size}</span>
          {restorable > 0 && (
            <Button
              size="sm"
              variant="outline"
              disabled={isBatchRunning}
              onClick={handleBulkRestore}
            >
              <RotateCcw className="mr-2 h-3.5 w-3.5" />
              Восстановить ({restorable})
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            className="text-destructive hover:text-destructive"
            disabled={isBatchRunning}
            onClick={handleBulkPurge}
          >
            {bulkPurging ? (
              <>
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                {deletedCount}/{bulkPurgeTotal}
              </>
            ) : (
              <>
                <X className="mr-2 h-3.5 w-3.5" />
                Удалить навсегда ({selected.size})
              </>
            )}
          </Button>
        </div>
      )}

      {/* Список */}
      {isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-lg" />
          ))}
        </div>
      ) : visibleItems.length === 0 && !isBatchRunning ? (
        <div className="text-muted-foreground flex flex-col items-center justify-center gap-3 py-20">
          <Trash2 className="h-12 w-12 opacity-30" />
          <p className="text-sm">Корзина пуста</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {/* Строка выбора всех */}
          <div className="flex items-center gap-3 px-4 py-1">
            <Checkbox
              checked={allSelected}
              onCheckedChange={toggleAll}
              disabled={isBatchRunning}
              aria-label="Выбрать все"
            />
            <span className="text-muted-foreground text-xs">{visibleItems.length} элем.</span>
          </div>

          {visibleItems.map((item) => (
            <TrashRow
              key={item.id}
              item={item}
              selected={selected.has(item.id)}
              isBatchRunning={isBatchRunning}
              onToggle={toggleItem}
            />
          ))}
        </div>
      )}

      {/* Подтверждение полной очистки */}
      <Dialog open={emptyOpen} onOpenChange={setEmptyOpen}>
        <DialogContent className="sm:max-w-sm" hasDescription>
          <DialogHeader>
            <DialogTitle>Очистить корзину?</DialogTitle>
            <DialogDescription>
              Все {items.length} элем. будут удалены навсегда без возможности восстановления.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEmptyOpen(false)}>
              Отмена
            </Button>
            <Button variant="destructive" onClick={handleEmptyTrash}>
              Очистить всё
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
