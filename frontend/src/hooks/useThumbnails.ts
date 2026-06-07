import { useQuery, useQueryClient } from "@tanstack/react-query";
import { nodesApi } from "@/api/nodes";
import { getThumbnailCache, setThumbnailCache } from "@/lib/thumbnailCache";
import type { NodeListItem } from "@/types/nodes";

const STALE_MS = 4 * 60 * 1000;
const GC_MS = 10 * 60 * 1000;

/**
 * Загружает presigned thumbnail URL для image-элементов одним batch-запросом.
 *
 * Использует многоуровневый кэш:
 * 1. React Query in-memory cache — мгновенный доступ, но сбрасывается при refresh.
 * 2. `sessionStorage` — переживает refresh страницы, но очищается при закрытии tab.
 * 3. Batch API request — выполняется только для id, отсутствующих в обоих кэшах.
 *
 * Возвращает `Map`, где:
 * - ключ отсутствует — thumbnail ещё загружается, UI может показать skeleton.
 * - значение `null` — thumbnail отсутствует, UI может показать icon fallback.
 * - значение `string` — presigned URL, UI может показать `<img>`.
 *
 * Args:
 *   items: Элементы текущего списка nodes.
 *
 * Returns:
 *   Map вида `nodeId -> thumbnail URL | null`.
 */
export function useThumbnails(items: NodeListItem[]): Map<string, string | null> {
  const qc = useQueryClient();

  const imageItems = items.filter(
    (i) => i.node_type === "file" && i.file_mime_type?.startsWith("image/"),
  );

  // Пропускаем id, которые уже есть в React Query cache или sessionStorage.
  const uncachedIds = imageItems
    .map((i) => i.id)
    .filter((id) => {
      if (qc.getQueryData(["thumbnail", id]) !== undefined) return false;
      if (getThumbnailCache(id) !== undefined) return false;
      return true;
    });

  useQuery({
    queryKey: ["thumbnails-batch", uncachedIds.join(",")],
    queryFn: async ({ signal }) => {
      const batch = await nodesApi.thumbnailsBatch(uncachedIds, signal);
      for (const [id, url] of Object.entries(batch)) {
        const value = url ?? null;
        qc.setQueryData(["thumbnail", id], value);
        setThumbnailCache(id, value);
      }
      return batch;
    },
    enabled: uncachedIds.length > 0,
    staleTime: STALE_MS,
    gcTime: GC_MS,
  });

  // Собираем result map: сначала React Query cache, затем sessionStorage.
  const map = new Map<string, string | null>();
  for (const item of imageItems) {
    const rq = qc.getQueryData<string | null>(["thumbnail", item.id]);
    if (rq !== undefined) {
      map.set(item.id, rq);
      continue;
    }
    const stored = getThumbnailCache(item.id);
    if (stored !== undefined) {
      map.set(item.id, stored);
    }
  }
  return map;
}
