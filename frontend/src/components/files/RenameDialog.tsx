import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { nodesApi } from "@/api/nodes";
import { optimisticallyPatchNode } from "@/lib/folderCache";
import { friendlyError } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Свойства диалога переименования.
 *
 * `open` определяет, открыт ли диалог.
 * `onOpenChange` вызывается при изменении состояния открытия.
 * `nodeId` — идентификатор переименовываемого файла или папки.
 * `currentName` — текущее название элемента.
 * `folderQueryKey` используется для обновления кеша текущей папки.
 */
interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  nodeId: string;
  currentName: string;
  folderQueryKey: unknown[];
}

/**
 * Диалог переименования файла или папки.
 *
 * Позволяет изменить название элемента, оптимистично обновляет кеш
 * и откатывает изменение при ошибке.
 *
 * Если новое название пустое, показывает inline-ошибку.
 * Если название не изменилось, просто закрывает диалог.
 */
export function RenameDialog({ open, onOpenChange, nodeId, currentName, folderQueryKey }: Props) {
  const [name, setName] = useState(currentName);
  const [error, setError] = useState("");
  const queryClient = useQueryClient();

  /**
   * При открытии диалога синхронизирует поле ввода
   * с текущим названием элемента.
   */
  useEffect(() => {
    if (open) setName(currentName);
  }, [open, currentName]);

  const mutation = useMutation({
    mutationFn: () => nodesApi.rename(nodeId, name.trim()),
    onMutate: () => {
      const rollback = optimisticallyPatchNode(queryClient, folderQueryKey, nodeId, {
        name: name.trim(),
      });
      return { rollback };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: folderQueryKey });
      toast.success("Переименовано");
      setError("");
      onOpenChange(false);
    },
    onError: (err, _vars, ctx) => {
      ctx?.rollback();
      const msg = friendlyError(err, { operation: "rename", name: name.trim() });
      setError(msg);
      toast.error(msg);
    },
  });

  /**
   * Обрабатывает отправку формы переименования.
   *
   * Валидирует название, пропускает сохранение без изменений
   * и запускает мутацию переименования.
   */
  function handleSubmit(e: React.SyntheticEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Введите название");
      return;
    }
    if (name.trim() === currentName) {
      onOpenChange(false);
      return;
    }
    setError("");
    mutation.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Переименовать</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rename-input">Новое название</Label>
            <Input
              id="rename-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              onFocus={(e) => e.target.select()}
            />
            {error && <p className="text-destructive text-xs">{error}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Сохранение…" : "Сохранить"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
