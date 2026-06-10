import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { nodesApi } from "@/api/nodes";
import { getThumbnailCache, setThumbnailCache } from "@/lib/thumbnailCache";
import { thumbnailSupported } from "@/lib/preview";
import type { NodeListItem } from "@/types/nodes";

const GC_MS = 10 * 60 * 1000;
const POLL_MS = 6000;
const MAX_POLLS = 12;

type BatchResult = Record<string, string | null>;

/**
 * Загружает presigned thumbnail URL для preview-элементов одним batch-запросом.
 *
 * Кэшируются только положительные результаты (готовый URL) — в React Query и
 * `sessionStorage`. Для ещё не готовых превью (`null`) запрос периодически
 * повторяется: превью книг и видео генерируется на сервере с задержкой, и опрос
 * позволяет показать миниатюру, как только она появится, без перезагрузки.
 *
 * Возвращает `Map`, где:
 * - ключ отсутствует — thumbnail ещё загружается, UI может показать skeleton.
 * - значение `null` — thumbnail отсутствует/ещё не готов, UI показывает icon.
 * - значение `string` — presigned URL, UI показывает `<img>`.
 *
 * Args:
 *   items: Элементы текущего списка nodes.
 *
 * Returns:
 *   Map вида `nodeId -> thumbnail URL | null`.
 */
export function useThumbnails(items: NodeListItem[]): Map<string, string | null> {
  const qc = useQueryClient();

  const previewItems = items.filter(
    (i) => i.node_type === "file" && thumbnailSupported(i.file_mime_type),
  );

  // Запрашиваем все элементы без готового (положительного) URL: и неизвестные,
  // и те, для которых превью пока не готово — чтобы опросить их повторно.
  const positiveUrl = (id: string): string | undefined => {
    const rq = qc.getQueryData<string | null>(["thumbnail", id]);
    if (typeof rq === "string") return rq;
    const stored = getThumbnailCache(id);
    return typeof stored === "string" ? stored : undefined;
  };

  const pendingIds = previewItems.map((i) => i.id).filter((id) => positiveUrl(id) === undefined);

  const { data: batch } = useQuery({
    queryKey: ["thumbnails-batch", pendingIds.join(",")],
    queryFn: async ({ signal }) => {
      const result = await nodesApi.thumbnailsBatch(pendingIds, signal);
      for (const [id, url] of Object.entries(result)) {
        if (url) {
          qc.setQueryData(["thumbnail", id], url);
          setThumbnailCache(id, url);
        }
      }
      return result as BatchResult;
    },
    enabled: pendingIds.length > 0,
    staleTime: 0,
    gcTime: GC_MS,
    // Опрашиваем, пока есть не готовые превью, но не дольше MAX_POLLS попыток —
    // иначе файлы, у которых превью не будет никогда, опрашивались бы вечно.
    refetchInterval: (query: Query<BatchResult>) => {
      const data = query.state.data;
      if (!data) return false;
      const hasPending = Object.values(data).some((v) => v == null);
      if (!hasPending) return false;
      return query.state.dataUpdateCount >= MAX_POLLS ? false : POLL_MS;
    },
  });

  // Result map: положительный URL из кэша, иначе текущее значение из batch
  // (null = иконка, отсутствие = ещё грузится).
  const map = new Map<string, string | null>();
  for (const item of previewItems) {
    const url = positiveUrl(item.id);
    if (url !== undefined) {
      map.set(item.id, url);
    } else if (batch && item.id in batch) {
      map.set(item.id, batch[item.id]);
    }
  }
  return map;
}
