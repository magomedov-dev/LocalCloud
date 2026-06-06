import { createContext, useContext } from "react";

/**
 * Статус задачи загрузки.
 */
export type UploadStatus = "pending" | "uploading" | "done" | "error";

/**
 * Задача загрузки файла.
 */
export interface UploadTask {
  /** Уникальный идентификатор задачи. */
  id: string;
  /** Имя загружаемого файла. */
  filename: string;
  /** Прогресс загрузки в процентах. */
  progress: number;
  /** Текущий статус загрузки. */
  status: UploadStatus;
  /** Текст ошибки или `null`, если ошибки нет. */
  error: string | null;
}

/**
 * Значение контекста загрузок.
 */
export interface UploadContextValue {
  /** Список текущих задач загрузки. */
  tasks: UploadTask[];
  /** Добавляет файлы в очередь загрузки. */
  enqueue: (files: File[], parentNodeId: string | null, folderQueryKey: unknown[]) => void;
  /** Удаляет задачу загрузки из списка. */
  dismiss: (id: string) => void;
  /** Удаляет из списка все завершённые и ошибочные загрузки. */
  dismissAllDone: () => void;
}

/**
 * React-контекст загрузок.
 *
 * Должен использоваться внутри `UploadProvider`.
 */
export const UploadContext = createContext<UploadContextValue | null>(null);

/**
 * Возвращает данные и действия загрузок из `UploadContext`.
 *
 * @throws Если хук используется вне `UploadProvider`.
 */
export function useUpload() {
  const ctx = useContext(UploadContext);
  if (!ctx) throw new Error("useUpload должен использоваться внутри <UploadProvider>");
  return ctx;
}
