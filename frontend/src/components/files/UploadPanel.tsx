import { CheckCircle2, Loader2, X, XCircle } from "lucide-react";
import { useUpload, type UploadTask } from "@/contexts/upload-context";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Строка задачи загрузки.
 *
 * Отображает имя файла, прогресс загрузки, состояние выполнения
 * и кнопку скрытия для завершённых или ошибочных задач.
 */
function TaskRow({ task }: { task: UploadTask }) {
  const { dismiss } = useUpload();
  const isDone = task.status === "done";
  const isError = task.status === "error";

  return (
    <div className="flex items-center gap-2 py-1">
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium" title={task.filename}>
          {task.filename}
        </p>
        {isError ? (
          <p className="text-destructive truncate text-[10px]">{task.error}</p>
        ) : (
          <Progress value={task.progress} className={cn("mt-1 h-1", isDone && "opacity-50")} />
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {isDone && <CheckCircle2 className="h-4 w-4 text-green-500" />}
        {isError && <XCircle className="text-destructive h-4 w-4" />}
        {task.status === "uploading" && <Loader2 className="text-primary h-4 w-4 animate-spin" />}
        {(isDone || isError) && (
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            onClick={() => dismiss(task.id)}
            aria-label="Убрать"
          >
            <X className="h-3 w-3" />
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * Панель состояния загрузок.
 *
 * Отображает текущие задачи загрузки файлов в правом нижнем углу экрана.
 * Для каждой задачи показывает прогресс, успешное завершение или ошибку.
 *
 * Если задач нет, компонент ничего не рендерит.
 * Завершённые задачи можно скрыть по одной или массово.
 */
export function UploadPanel() {
  const { tasks, dismissAllDone } = useUpload();
  if (!tasks.length) return null;

  const active = tasks.filter((t) => t.status === "uploading" || t.status === "pending").length;
  const finished = tasks.filter((t) => t.status === "done" || t.status === "error").length;

  return (
    <div className="bg-card fixed right-4 bottom-4 z-50 w-72 rounded-xl border shadow-xl">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <p className="text-xs font-semibold">
          {active > 0 ? `Загрузка файлов (${active})` : "Загрузки"}
        </p>
        {finished > 1 && (
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            onClick={dismissAllDone}
            aria-label="Закрыть завершённые"
          >
            <X className="h-3 w-3" />
          </Button>
        )}
      </div>
      <div className="max-h-52 overflow-y-auto px-3 pt-1 pb-2">
        {tasks.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
      </div>
    </div>
  );
}
