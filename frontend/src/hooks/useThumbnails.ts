import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { nodesApi } from "@/api/nodes";
import { getThumbnailCache, setThumbnailCache } from "@/lib/thumbnailCache";
import { thumbnailSupported } from "@/lib/preview";
import type { NodeListItem } from "@/types/nodes";

const GC_MS = 10 * 60 * 1000;
// Опрос ожидающих превью идёт с экспоненциальной задержкой: быстро в начале
// (поймать только что готовое превью), затем всё реже — чтобы 3 пользователя в
// папке не создавали постоянный поток батч-запросов. На фоне (вкладка не в
// фокусе) опрос не идёт вовсе (refetchIntervalInBackground: false).
const POLL_BASE_MS = 4000;
const POLL_MAX_MS = 30000;
const MAX_POLLS = 8;
// Серверный лимит node_ids на один батч-запрос; большее число режем на части.
const BATCH_LIMIT = 100;

type BatchResult = Record<string, string | null>;

/** Делит массив на части не больше `size`. */
function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

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
 *   enabled: Загружать ли превью. Если `false` (превью отключены флагом
 *     развёртывания), запрос не выполняется, и для всех поддерживаемых
 *     элементов возвращается `null` — UI показывает иконку, а не миниатюру.
 *
 * Returns:
 *   Map вида `nodeId -> thumbnail URL | null`.
 */
export function useThumbnails(
  items: NodeListItem[],
  enabled = true,
): Map<string, string | null> {
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

  const pendingIds = enabled
    ? previewItems.map((i) => i.id).filter((id) => positiveUrl(id) === undefined)
    : [];

  const { data: batch } = useQuery({
    queryKey: ["thumbnails-batch", pendingIds.join(",")],
    queryFn: async ({ signal }) => {
      // Режем на части по серверному лимиту и собираем результат воедино.
      const parts = await Promise.all(
        chunk(pendingIds, BATCH_LIMIT).map((ids) => nodesApi.thumbnailsBatch(ids, signal)),
      );
      const result: BatchResult = Object.assign({}, ...parts);
      for (const [id, url] of Object.entries(result)) {
        if (url) {
          qc.setQueryData(["thumbnail", id], url);
          setThumbnailCache(id, url);
        }
      }
      return result;
    },
    enabled: pendingIds.length > 0,
    staleTime: 0,
    gcTime: GC_MS,
    // На фоне (вкладка не в фокусе) не опрашиваем — снимает основную нагрузку.
    refetchIntervalInBackground: false,
    // Опрашиваем, пока есть не готовые превью, с экспоненциальной задержкой и не
    // дольше MAX_POLLS попыток (иначе файлы без превью опрашивались бы вечно).
    refetchInterval: (query: Query<BatchResult>) => {
      const data = query.state.data;
      if (!data) return false;
      const hasPending = Object.values(data).some((v) => v == null);
      if (!hasPending) return false;
      if (query.state.dataUpdateCount >= MAX_POLLS) return false;
      const exp = Math.max(0, query.state.dataUpdateCount - 1);
      return Math.min(POLL_BASE_MS * 2 ** exp, POLL_MAX_MS);
    },
  });

  // Result map: положительный URL из кэша, иначе текущее значение из batch
  // (null = иконка, отсутствие = ещё грузится).
  const map = new Map<string, string | null>();
  if (!enabled) {
    // Превью отключены: показываем иконку (null) для всех поддерживаемых.
    for (const item of previewItems) map.set(item.id, null);
    return map;
  }
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
