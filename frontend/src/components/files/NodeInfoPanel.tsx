import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { FileIcon } from "./FileIcon";
import { getFolderColor } from "./folderColors";
import { formatBytes } from "@/hooks/useQuota";
import { useFeatures } from "@/hooks/useFeatures";
import { nodesApi } from "@/api/nodes";
import { queryClient } from "@/lib/query-client";
import { getThumbnailCache, setThumbnailCache } from "@/lib/thumbnailCache";
import { thumbnailSupported } from "@/lib/preview";
import type { NodeListItem } from "@/types/nodes";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const VISIBILITY_LABELS: Record<string, string> = {
  private: "Приватный",
  shared: "Общий доступ",
  public: "Публичный",
};

/**
 * Форматирует ISO-дату в полный русский формат
 * с датой и временем.
 */
function formatDateFull(iso: string) {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Строка с параметром элемента.
 *
 * Отображает подпись и значение в вертикальном виде.
 */
function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="text-sm break-all">{value}</span>
    </div>
  );
}

/**
 * Свойства информационной панели элемента.
 *
 * `item` — файл или папка, данные которых нужно показать.
 * `onClose` закрывает панель.
 */
interface Props {
  item: NodeListItem;
  onClose: () => void;
}

/**
 * Информационная панель файла или папки.
 *
 * Показывает превью, название и основные метаданные элемента:
 * тип, MIME-тип, размер, видимость, путь, дату изменения и дату создания.
 *
 * Миниатюра показывается для всех типов, которым её рендерит backend
 * (изображения, PDF, видео — см. `thumbnailSupported`), и только когда превью
 * включены флагом развёртывания. Берётся из кеша React Query, затем из
 * `sessionStorage`, а при отсутствии — загружается через API. Это согласовано
 * с миниатюрами в сетке файлов.
 *
 * На мобильных устройствах отображается как выезжающая панель с backdrop,
 * на desktop — как встроенная боковая панель.
 */
export function NodeInfoPanel({ item, onClose }: Props) {
  const features = useFeatures();
  const hasThumbnail =
    features.previews_enabled &&
    item.node_type === "file" &&
    thumbnailSupported(item.file_mime_type);
  const folderColor = item.node_type === "folder" ? getFolderColor(item.id) : null;

  const [previewUrl, setPreviewUrl] = useState<string | null>(() => {
    if (!hasThumbnail) return null;
    const rq = queryClient.getQueryData<string | null>(["thumbnail", item.id]);
    if (rq !== undefined) return rq;
    return getThumbnailCache(item.id) ?? null;
  });
  const [previewLoading, setPreviewLoading] = useState(!previewUrl && hasThumbnail);

  /**
   * Загружает миниатюру файла.
   *
   * Сначала проверяет кеш React Query, затем `sessionStorage`.
   * Если миниатюра не найдена, запрашивает её через API
   * и сохраняет результат в оба кеша.
   */
  useEffect(() => {
    if (!hasThumbnail) {
      setPreviewUrl(null);
      setPreviewLoading(false);
      return;
    }

    const rq = queryClient.getQueryData<string | null>(["thumbnail", item.id]);
    if (rq !== undefined) {
      setPreviewUrl(rq);
      setPreviewLoading(false);
      return;
    }

    const stored = getThumbnailCache(item.id);
    if (stored !== undefined) {
      setPreviewUrl(stored);
      setPreviewLoading(false);
      return;
    }

    setPreviewUrl(null);
    setPreviewLoading(true);
    // Эффект асинхронный: отменяем устаревший результат при смене файла/размонтировании.
    let cancelled = false;
    nodesApi
      .thumbnail(item.id)
      .then((resp) => {
        const url = resp.presigned_url;
        queryClient.setQueryData(["thumbnail", item.id], url);
        setThumbnailCache(item.id, url);
        if (!cancelled) setPreviewUrl(url);
      })
      .catch(() => {
        if (!cancelled) setPreviewUrl(null);
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [item.id, hasThumbnail]);

  return (
    <>
      {/* Затемнение на мобильных (нажмите для закрытия) */}
      <div className="fixed inset-0 z-40 bg-black/50 md:hidden" onClick={onClose} aria-hidden />
      {/* Выдвижная панель на мобильных; встроенная боковая панель на десктопе */}
      <div className="bg-card fixed inset-y-0 right-0 z-50 flex h-full w-[85vw] max-w-xs shrink-0 flex-col border-l shadow-2xl md:static md:z-auto md:w-72 md:max-w-none md:shadow-none">
        {/* Заголовок */}
        <div className="flex items-center justify-between border-b px-4 py-3">
          <span className="text-sm font-semibold">Информация</span>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Предпросмотр */}
        <div className="bg-muted/20 flex min-h-36 items-center justify-center border-b p-6">
          {hasThumbnail && previewLoading ? (
            <Skeleton className="h-32 w-full rounded-lg" />
          ) : hasThumbnail && previewUrl ? (
            <img
              src={previewUrl}
              alt={item.name}
              className="max-h-36 max-w-full rounded-lg object-contain shadow"
            />
          ) : (
            <FileIcon
              nodeType={item.node_type}
              mimeType={item.file_mime_type}
              className="h-16 w-16"
              color={folderColor}
            />
          )}
        </div>

        {/* Имя */}
        <div className="border-b px-4 py-3">
          <p className="text-sm leading-snug font-semibold wrap-break-word" title={item.name}>
            {item.name}
          </p>
        </div>

        {/* Детали */}
        <div className="flex-1 overflow-y-auto px-4 py-4">
          <div className="flex flex-col gap-4">
            <InfoRow label="Тип" value={item.node_type === "folder" ? "Папка" : "Файл"} />
            {item.file_mime_type && <InfoRow label="MIME-тип" value={item.file_mime_type} />}
            {item.file_size_bytes != null && (
              <InfoRow label="Размер" value={formatBytes(item.file_size_bytes)} />
            )}
            <InfoRow
              label="Видимость"
              value={VISIBILITY_LABELS[item.visibility] ?? item.visibility}
            />
            <InfoRow label="Путь" value={item.path} />
            <InfoRow label="Изменён" value={formatDateFull(item.updated_at)} />
            <InfoRow label="Создан" value={formatDateFull(item.created_at)} />
          </div>
        </div>
      </div>
    </>
  );
}
