import { cn } from "@/lib/utils";
import type { FileFilter } from "./fileListUtils";

const FILTERS: { value: FileFilter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "folder", label: "Папки" },
  { value: "image", label: "Изображения" },
  { value: "document", label: "Документы" },
  { value: "video", label: "Видео" },
  { value: "audio", label: "Аудио" },
  { value: "archive", label: "Архивы" },
];

/**
 * Свойства панели фильтров файлов.
 *
 * `active` — текущий выбранный фильтр.
 * `onChange` вызывается при выборе нового фильтра.
 */
interface Props {
  active: FileFilter;
  onChange: (filter: FileFilter) => void;
}

/**
 * Панель фильтрации списка файлов.
 *
 * Отображает набор кнопок-фильтров для быстрого отбора элементов
 * по типу: все элементы, папки, изображения, документы, видео, аудио и архивы.
 *
 * Активный фильтр визуально выделяется.
 */
export function FileFilterBar({ active, onChange }: Props) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {FILTERS.map((f) => (
        <button
          key={f.value}
          onClick={() => onChange(f.value)}
          className={cn(
            "rounded-full px-3 py-1 text-xs font-medium transition-colors",
            active === f.value
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground",
          )}
        >
          {f.label}
        </button>
      ))}
    </div>
  );
}
