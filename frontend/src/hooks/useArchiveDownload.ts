import { useState } from "react";
import { toast } from "sonner";
import { tasksApi } from "@/api/tasks";
import { downloadsApi } from "@/api/downloads";
import { downloadBlobFromUrl } from "@/lib/download";
import { ARCHIVE_POLL_MS, ARCHIVE_TIMEOUT_MS } from "@/lib/constants";

/**
 * Приостанавливает выполнение на указанное количество миллисекунд.
 *
 * Args:
 *   ms: Количество миллисекунд ожидания.
 *
 * Returns:
 *   Promise, который завершается после истечения задержки.
 */
function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

const STATUS_LABELS: Record<string, string> = {
  pending: "В очереди…",
  running: "Архивируется…",
  completed: "Готово",
  failed: "Ошибка",
  cancelled: "Отменено",
};

/**
 * Состояние процесса скачивания архива.
 */
interface ArchiveDownloadState {
  /** Активен ли сейчас процесс подготовки или скачивания архива. */
  active: boolean;
  /** Текущий человекочитаемый статус процесса. */
  status: string;
  /** Текущий прогресс процесса в процентах. */
  progress: number;
  /** Идентификатор активного элемента, например node id, или `null`. */
  activeId: string | null;
}

interface RunOptions {
  /** Запрашивает создание архивной задачи и возвращает её идентификатор. */
  requestTask: () => Promise<string>;
  /** Имя архива без расширения. Также используется в toast-сообщениях. */
  filename: string;
  /** Идентификатор элемента, который будет доступен как `activeId` во время выполнения. */
  activeId?: string | null;
  /** Callback, который вызывается после запуска скачивания. */
  onSuccess?: () => void;
}

/**
 * Hook для фоновой подготовки и скачивания ZIP-архива.
 *
 * Запускает создание фоновой задачи архивации, polling'ом ожидает её
 * завершения, получает presigned URL готового архива и инициирует скачивание
 * через браузер. Во время работы обновляет состояние прогресса и один
 * live-updating toast.
 *
 * Returns:
 *   Объект с методом `run` и текущим состоянием процесса скачивания архива.
 */
export function useArchiveDownload() {
  const [state, setState] = useState<ArchiveDownloadState>({
    active: false,
    status: "",
    progress: 0,
    activeId: null,
  });

  /**
   * Запускает процесс подготовки и скачивания архива.
   *
   * Args:
   *   options: Параметры запуска: функция создания задачи, имя архива,
   *     активный item id и callback успешного завершения.
   */
  async function run({ requestTask, filename, activeId = null, onSuccess }: RunOptions) {
    if (state.active) return;

    setState({ active: true, status: "В очереди…", progress: 10, activeId });
    const toastId = toast.loading(`Подготовка «${filename}»… В очереди`);
    const deadline = Date.now() + ARCHIVE_TIMEOUT_MS;

    try {
      const taskId = await requestTask();

      let task = await tasksApi.get(taskId);
      while (
        task.status !== "completed" &&
        task.status !== "failed" &&
        task.status !== "cancelled"
      ) {
        if (Date.now() > deadline) throw new Error("Превышено время ожидания (15 мин)");
        await sleep(ARCHIVE_POLL_MS);
        task = await tasksApi.get(taskId);
        const label = STATUS_LABELS[task.status] ?? task.status;
        setState({
          active: true,
          status: label,
          progress: task.status === "running" ? 60 : 30,
          activeId,
        });
        toast.loading(`Подготовка «${filename}»… ${label}`, { id: toastId });
      }

      if (task.status !== "completed") {
        throw new Error(task.error_message ?? "Архивация завершилась с ошибкой");
      }

      setState({ active: true, status: "Получение ссылки…", progress: 90, activeId });
      toast.loading("Получение ссылки…", { id: toastId });
      const dl = await downloadsApi.archiveUrl(taskId, `${filename}.zip`);
      downloadBlobFromUrl(dl.presigned_url, dl.filename ?? `${filename}.zip`);

      setState({ active: true, status: "Готово", progress: 100, activeId });
      toast.success(`«${filename}» скачивается`, { id: toastId });
      onSuccess?.();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Неизвестная ошибка";
      toast.error(`Не удалось скачать «${filename}»: ${msg}`, { id: toastId });
    } finally {
      setState({ active: false, status: "", progress: 0, activeId: null });
    }
  }

  return { run, ...state };
}
