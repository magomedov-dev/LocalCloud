import { useCallback, useRef, useState, type ReactNode } from "react";
import { Upload } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Свойства зоны перетаскивания файлов.
 *
 * `onDrop` вызывается со списком файлов после их сброса в область.
 * `disabled` отключает обработку сброшенных файлов.
 * `children` — содержимое, поверх которого отображается drag-and-drop overlay.
 */
interface Props {
  onDrop: (files: File[]) => void;
  disabled?: boolean;
  children: ReactNode;
}

/**
 * Зона для загрузки файлов через drag-and-drop.
 *
 * Отслеживает перетаскивание внешних файлов, показывает overlay-подсказку
 * и передаёт выбранные файлы в `onDrop` после сброса.
 *
 * Внутренний счётчик drag-событий предотвращает преждевременное скрытие overlay
 * при переходе курсора между дочерними элементами.
 */
export function DropZone({ onDrop, disabled, children }: Props) {
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);

  /**
   * Обрабатывает вход drag-события в область.
   *
   * Активирует overlay только для внешних файлов,
   * игнорируя внутренние drag-and-drop операции.
   */
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current++;
    const hasFiles = Array.from(e.dataTransfer.items).some((i) => i.kind === "file");
    if (hasFiles) setIsDragging(true);
  }, []);

  /**
   * Обрабатывает выход drag-события из области.
   *
   * Скрывает overlay только когда drag-событие полностью покинуло контейнер.
   */
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current === 0) setIsDragging(false);
  }, []);

  /**
   * Разрешает сброс файлов в область
   * и задаёт визуальный эффект копирования.
   */
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  /**
   * Обрабатывает сброс файлов.
   *
   * Сбрасывает drag-состояние, фильтрует пустые файлы
   * и передаёт список файлов в `onDrop`, если компонент не отключён.
   */
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current = 0;
      setIsDragging(false);
      if (disabled) return;
      const files = Array.from(e.dataTransfer.files).filter((f) => f.size > 0);
      if (files.length) onDrop(files);
    },
    [onDrop, disabled],
  );

  return (
    <div
      className="relative min-h-0 flex-1"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {children}

      {isDragging && (
        <div
          className={cn(
            "pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-3",
            "border-primary bg-primary/5 rounded-xl border-2 border-dashed",
          )}
        >
          <Upload className="text-primary h-10 w-10" />
          <p className="text-primary text-sm font-medium">Отпустите файлы для загрузки</p>
        </div>
      )}
    </div>
  );
}
