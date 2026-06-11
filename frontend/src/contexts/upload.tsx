import { useCallback, useEffect, useReducer, useRef, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { uploadsApi } from "@/api/uploads";
import { insertNodeIntoFolderCache } from "@/lib/folderCache";
import { friendlyError, isAbortError, UserFacingError } from "@/lib/errors";
import {
  UPLOAD_PART_SIZE,
  MAX_CONCURRENT_UPLOADS,
  UPLOAD_RETRY_MAX,
  UPLOAD_RETRY_BASE_MS,
} from "@/lib/constants";
import type { NodeListItem } from "@/types/nodes";
import { UploadContext, type UploadStatus, type UploadTask } from "./upload-context";

/**
 * Действия редьюсера загрузок.
 */
type Action =
  | { type: "ADD"; tasks: UploadTask[] }
  | { type: "PROGRESS"; id: string; progress: number }
  | { type: "DONE"; id: string }
  | { type: "ERROR"; id: string; error: string }
  | { type: "DISMISS"; id: string }
  | { type: "DISMISS_ALL_DONE" };

/**
 * Формирует сообщение об ошибке загрузки части с учётом HTTP-статуса.
 *
 * Подсказывает пользователю, поможет ли повтор: истёкшая presigned-ссылка
 * (403) и временная недоступность хранилища (5xx) — повторяемые сбои.
 *
 * Args:
 *   status: HTTP-статус ответа MinIO на PUT части.
 *   fileName: Имя загружаемого файла для контекста.
 *
 * Returns:
 *   Готовое сообщение для пользователя.
 */
function partUploadErrorMessage(status: number, fileName: string): string {
  const file = `«${fileName}»`;
  if (status === 403) {
    return `Ссылка для загрузки ${file} истекла. Попробуйте загрузить файл снова.`;
  }
  if (status >= 500) {
    return `Хранилище временно недоступно при загрузке ${file}. Попробуйте позже.`;
  }
  return `Не удалось загрузить ${file} (ошибка ${status}).`;
}

/**
 * Управляет списком задач загрузки.
 */
function reducer(state: UploadTask[], action: Action): UploadTask[] {
  switch (action.type) {
    case "ADD":
      return [...state, ...action.tasks];
    case "PROGRESS":
      return state.map((t) =>
        t.id === action.id ? { ...t, progress: action.progress, status: "uploading" } : t,
      );
    case "DONE":
      return state.map((t) => (t.id === action.id ? { ...t, progress: 100, status: "done" } : t));
    case "ERROR":
      return state.map((t) =>
        t.id === action.id ? { ...t, status: "error", error: action.error } : t,
      );
    case "DISMISS":
      return state.filter((t) => t.id !== action.id);
    case "DISMISS_ALL_DONE":
      return state.filter((t) => t.status !== "done" && t.status !== "error");
    default:
      return state;
  }
}

/**
 * Провайдер контекста загрузок.
 *
 * Управляет очередью загрузки файлов, ограничивает количество
 * одновременных загрузок, отслеживает прогресс и обновляет кэш папки.
 */
export function UploadProvider({ children }: { children: ReactNode }) {
  const [tasks, dispatch] = useReducer(reducer, []);
  const queryClient = useQueryClient();
  const idRef = useRef(0);
  const activeRef = useRef(0);
  const pendingRef = useRef<Array<() => void>>([]);

  // AbortController на каждую активную загрузку: позволяет отменить и сетевые
  // PUT частей, и API-вызовы при закрытии задачи (dismiss) или размонтировании
  // провайдера — иначе запросы продолжали бы выполняться вхолостую.
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());

  // Ключи запросов папок, затронутых завершёнными загрузками в текущей пачке.
  // Инвалидируем их один раз после завершения всей пачки, а не после каждого файла,
  // чтобы рефетч папки и перезагрузка миниатюр не конкурировали с активными
  // загрузками за пул соединений браузера.
  const deferredKeysRef = useRef<Map<string, unknown[]>>(new Map());

  /**
   * Выполняет загрузку одного файла по частям.
   */
  const runUpload = useCallback(
    async (task: UploadTask, file: File, parentNodeId: string | null, qKey: unknown[]) => {
      // Запоминаем sessionId, чтобы при ошибке после создания сессии
      // освободить слот загрузки на бэкенде.
      let sessionId: string | null = null;
      const controller = new AbortController();
      abortControllersRef.current.set(task.id, controller);
      const signal = controller.signal;
      try {
        if (!parentNodeId) {
          throw new UserFacingError("Выберите папку для загрузки файлов");
        }

        const partsCount = Math.max(1, Math.ceil(file.size / UPLOAD_PART_SIZE));
        const partSizeBytes = partsCount === 1 ? file.size : UPLOAD_PART_SIZE;

        // 1. Создаём сессию загрузки.
        // Повторяем попытку при превышении квоты: параллельная загрузка
        // могла ещё освобождать свой слот через abort.
        const createParams = {
          parent_node_id: parentNodeId,
          filename: file.name,
          file_size_bytes: file.size,
          parts_count: partsCount,
          mime_type: file.type || null,
          part_size_bytes: partSizeBytes,
        };
        const session = await (async () => {
          for (let attempt = 0; attempt <= UPLOAD_RETRY_MAX; attempt++) {
            try {
              return await uploadsApi.create(createParams, signal);
            } catch (err: unknown) {
              if (isAbortError(err)) throw err;
              const msg: string =
                (err as { response?: { data?: { message?: string } } })?.response?.data?.message ??
                (err instanceof Error ? err.message : "");
              if (msg.toLowerCase().includes("quota") && attempt < UPLOAD_RETRY_MAX) {
                await new Promise<void>((r) => setTimeout(r, (attempt + 1) * UPLOAD_RETRY_BASE_MS));
                continue;
              }
              throw err;
            }
          }
          throw new Error("Не удалось создать сессию загрузки");
        })();
        sessionId = session.id;

        // 2. Получаем presigned-ссылки для частей файла.
        const { parts } = await uploadsApi.getPresignedParts(session.id, signal);

        const completedParts: { part_number: number; etag: string; size_bytes: number }[] = [];

        // 3. Загружаем каждую часть файла.
        for (const part of parts) {
          const start = (part.part_number - 1) * partSizeBytes;
          const end = Math.min(start + partSizeBytes, file.size);
          const blob = file.slice(start, end);
          const actualSize = end - start;

          // Убираем заголовки, запрещённые браузером.
          const restricted = new Set(["content-length", "host", "connection", "transfer-encoding"]);
          const safeHeaders: Record<string, string> = {};
          for (const [k, v] of Object.entries(part.headers ?? {})) {
            if (!restricted.has(k.toLowerCase())) safeHeaders[k] = v;
          }

          const resp = await fetch(part.url, {
            method: "PUT",
            body: blob,
            headers: safeHeaders,
            signal,
          });

          if (!resp.ok) {
            // Сообщение с учётом статуса: подсказываем, поможет ли повтор.
            throw new UserFacingError(partUploadErrorMessage(resp.status, file.name));
          }

          const rawEtag = resp.headers.get("ETag") ?? resp.headers.get("etag") ?? "";
          const etag = rawEtag.replace(/"/g, "");

          // 4. Подтверждаем загруженную часть.
          await uploadsApi.completePart(
            session.id,
            part.part_number,
            {
              part_number: part.part_number,
              etag,
              size_bytes: actualSize,
            },
            signal,
          );

          completedParts.push({ part_number: part.part_number, etag, size_bytes: actualSize });

          // Прогресс по доле загруженных частей. Потолок 99 %: последний 1 %
          // резервируем за вызовом complete(), чтобы не показывать 100 % до
          // фактического завершения.
          const progress = Math.min(99, Math.round((part.part_number / partsCount) * 100));
          dispatch({ type: "PROGRESS", id: task.id, progress });
        }

        // 5. Завершаем загрузку файла.
        const completed = await uploadsApi.complete(
          session.id,
          {
            upload_session_id: session.id,
            parts: completedParts,
          },
          signal,
        );

        // Сразу добавляем новый файл в кэш папки, чтобы он появился
        // без ожидания фонового рефетча.
        if (completed.node_id) {
          const now = new Date().toISOString();
          const optimisticItem: NodeListItem = {
            id: completed.node_id,
            owner_id: "",
            parent_id: parentNodeId,
            name: file.name,
            node_type: "file",
            visibility: "private",
            path: "",
            depth: 0,
            created_at: now,
            updated_at: now,
            is_deleted: false,
            file_size_bytes: file.size,
            file_mime_type: file.type || null,
          };
          insertNodeIntoFolderCache(queryClient, qKey, optimisticItem);
        }

        // Загрузка успешно завершена — отменять сессию не нужно.
        sessionId = null;

        dispatch({ type: "DONE", id: task.id });

        // Откладываем рефетч папки до завершения всей пачки загрузок.
        // Оптимистичная вставка выше уже показывает файл в списке.
        deferredKeysRef.current.set(JSON.stringify(qKey), qKey);
      } catch (err) {
        // При ошибке или отмене сразу освобождаем слот upload-сессии на бэкенде.
        // abort() намеренно без signal — должен выполниться даже при отмене.
        if (sessionId) {
          try {
            await uploadsApi.abort(sessionId);
          } catch {
            // Best-effort: воркер истечения срока действия и пересинхронизация
            // счётчиков позже приведут состояние в порядок.
          }
        }
        // Отмена (dismiss/размонтирование) — не ошибка: задача уже удаляется
        // из списка, показывать ошибку и тост не нужно.
        if (!isAbortError(err)) {
          const msg = friendlyError(err, { operation: "upload", name: file.name });
          dispatch({ type: "ERROR", id: task.id, error: msg });
        }
      } finally {
        abortControllersRef.current.delete(task.id);
      }
    },
    [queryClient],
  );

  /**
   * Ставит файл в очередь загрузки с учётом лимита параллельных загрузок.
   */
  const scheduleUpload = useCallback(
    (task: UploadTask, file: File, parentNodeId: string | null, qKey: unknown[]) => {
      const run = () => {
        runUpload(task, file, parentNodeId, qKey).finally(() => {
          activeRef.current--;
          const next = pendingRef.current.shift();
          if (next) {
            activeRef.current++;
            next();
          } else if (activeRef.current === 0) {
            // Вся пачка завершена — один раз инвалидируем папки
            // и обновляем данные квоты.
            for (const key of deferredKeysRef.current.values()) {
              queryClient.invalidateQueries({ queryKey: key });
            }
            deferredKeysRef.current.clear();
            queryClient.invalidateQueries({ queryKey: ["quota", "me"] });
          }
        });
      };

      if (activeRef.current < MAX_CONCURRENT_UPLOADS) {
        activeRef.current++;
        run();
      } else {
        pendingRef.current.push(run);
      }
    },
    [runUpload, queryClient],
  );

  /**
   * Добавляет файлы в очередь загрузки.
   */
  const enqueue = useCallback(
    (files: File[], parentNodeId: string | null, folderQueryKey: unknown[]) => {
      const newTasks: UploadTask[] = files.map((file) => ({
        id: String(++idRef.current),
        filename: file.name,
        progress: 0,
        status: "pending" as UploadStatus,
        error: null,
      }));
      dispatch({ type: "ADD", tasks: newTasks });
      newTasks.forEach((task, i) => scheduleUpload(task, files[i], parentNodeId, folderQueryKey));
    },
    [scheduleUpload],
  );

  /**
   * Удаляет задачу загрузки из списка.
   *
   * Если загрузка ещё выполняется, отменяет её сетевые запросы — слот сессии
   * на бэкенде освободит catch-блок `runUpload` (вызов abort).
   */
  const dismiss = useCallback((id: string) => {
    const controller = abortControllersRef.current.get(id);
    if (controller) controller.abort();
    dispatch({ type: "DISMISS", id });
  }, []);

  // Отменяем все незавершённые загрузки при размонтировании провайдера, чтобы
  // их fetch/axios-запросы не продолжались вхолостую.
  useEffect(() => {
    const controllers = abortControllersRef.current;
    return () => {
      for (const controller of controllers.values()) controller.abort();
      controllers.clear();
    };
  }, []);

  /**
   * Удаляет из списка все завершённые и ошибочные загрузки.
   */
  const dismissAllDone = useCallback(() => {
    dispatch({ type: "DISMISS_ALL_DONE" });
  }, []);

  return (
    <UploadContext.Provider value={{ tasks, enqueue, dismiss, dismissAllDone }}>
      {children}
    </UploadContext.Provider>
  );
}
