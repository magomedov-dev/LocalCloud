import { Folder } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { FOLDER_COLORS } from "./folderColors";

/**
 * Свойства диалога выбора цвета папки.
 *
 * `open` определяет, открыт ли диалог.
 * `onOpenChange` вызывается при изменении состояния открытия.
 * `nodeId` — идентификатор папки.
 * `currentColor` — текущий выбранный цвет папки.
 * `onColorChange` вызывается при выборе или сбросе цвета.
 */
interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  nodeId: string;
  currentColor: string | null;
  onColorChange: (color: string | null) => void;
}

/**
 * Диалог выбора цвета папки.
 *
 * Отображает набор доступных цветов из `FOLDER_COLORS`.
 * При выборе цвета вызывает `onColorChange` и закрывает диалог.
 *
 * Также позволяет сбросить цвет папки к значению по умолчанию.
 */
export function FolderColorDialog({ open, onOpenChange, currentColor, onColorChange }: Props) {
  /**
   * Выбирает новый цвет папки и закрывает диалог.
   */
  function handleSelect(color: string) {
    onColorChange(color);
    onOpenChange(false);
  }

  /**
   * Сбрасывает пользовательский цвет папки и закрывает диалог.
   */
  function handleReset() {
    onColorChange(null);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xs">
        <DialogHeader>
          <DialogTitle>Цвет папки</DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-5 gap-2 py-2">
          {FOLDER_COLORS.map((c) => (
            <button
              key={c.value}
              title={c.label}
              onClick={() => handleSelect(c.value)}
              className={cn(
                "flex h-10 w-10 items-center justify-center rounded-lg transition-all hover:scale-110",
                currentColor === c.value && "ring-ring ring-offset-background ring-2 ring-offset-2",
              )}
            >
              <Folder className="h-6 w-6" style={{ color: c.value }} />
            </button>
          ))}
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={handleReset}>
            Сбросить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
