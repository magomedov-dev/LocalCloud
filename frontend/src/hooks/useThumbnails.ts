import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { nodesApi } from "@/api/nodes";
import { getThumbnailCache, setThumbnailCache } from "@/lib/thumbnailCache";
import { thumbnailSupported } from "@/lib/preview";
import type { NodeListItem, ThumbnailBatchItem } from "@/types/nodes";

const GC_MS = 10 * 60 * 1000;
// Опрос генерирующихся превью идёт с экспоненциальной задержкой: быстро в
// начале (поймать только что готовое превью), затем всё реже — чтобы 3
// пользователя в папке не создавали постоянный поток батч-запросов. На фоне
// (вкладка не в фокусе) опрос не идёт вовсе (refetchIntervalInBackground:
// false).
const POLL_BASE_MS = 4000;
const POLL_MAX_MS = 30000;
const MAX_POLLS = 8;
// Серверный лимит node_ids на один батч-запрос; большее число режем на части.
const BATCH_LIMIT = 100;

type BatchResult = Record<string, ThumbnailBatchItem>;

/** Делит массив на части не больше `size`. */
function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

/**
 * Загружает состояние миниатюр для preview-элементов одним batch-запросом.
 *
 * Сервер различает три исхода, и оба терминальных кэшируются (в React Query и
 * `sessionStorage`):
 * - `ready` — есть presigned URL миниатюры;
 * - `none` — миниатюры нет и не будет (нет доступа, тип не поддерживается,
 *   генерация не требуется или не удалась) — такой узел больше не опрашивается;
 * - `pending` — превью генерируется: только эти узлы опрашиваются повторно,
 *   чтобы показать миниатюру, как только она появится, без перезагрузки.
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

  // Терминальное значение из кэша: string — готовый URL, null — миниатюры не
  // будет (оба не перезапрашиваются), undefined — неизвестно/генерируется.
  const cachedValue = (id: string): string | null | undefined => {
    const rq = qc.getQueryData<string | null>(["thumbnail", id]);
    if (rq !== undefined) return rq;
    return getThumbnailCache(id);
  };

  const pendingIds = enabled
    ? previewItems.map((i) => i.id).filter((id) => cachedValue(id) === undefined)
    : [];

  const { data: batch } = useQuery({
    queryKey: ["thumbnails-batch", pendingIds.join(",")],
    queryFn: async ({ signal }) => {
      // Режем на части по серверному лимиту и собираем результат воедино.
      const parts = await Promise.all(
        chunk(pendingIds, BATCH_LIMIT).map((ids) => nodesApi.thumbnailsBatch(ids, signal)),
      );
      const result: BatchResult = Object.assign({}, ...parts);
      for (const [id, item] of Object.entries(result)) {
        if (item.status === "ready" && item.url) {
          qc.setQueryData(["thumbnail", id], item.url);
          setThumbnailCache(id, item.url);
        } else if (item.status === "none") {
          // Окончательное отсутствие миниатюры: кэшируем null, чтобы больше
          // не включать узел в батчи и не опрашивать его впустую.
          qc.setQueryData(["thumbnail", id], null);
          setThumbnailCache(id, null);
        }
        // pending не кэшируем — узел останется в pendingIds и будет опрошен.
      }
      return result;
    },
    enabled: pendingIds.length > 0,
    staleTime: 0,
    gcTime: GC_MS,
    // На фоне (вкладка не в фокусе) не опрашиваем — снимает основную нагрузку.
    refetchIntervalInBackground: false,
    // Опрашиваем, пока сервер сообщает о генерирующихся превью (pending), с
    // экспоненциальной задержкой и не дольше MAX_POLLS попыток — защита от
    // зависших в генерации файлов.
    refetchInterval: (query: Query<BatchResult>) => {
      const data = query.state.data;
      if (!data) return false;
      const hasPending = Object.values(data).some((v) => v.status === "pending");
      if (!hasPending) return false;
      if (query.state.dataUpdateCount >= MAX_POLLS) return false;
      const exp = Math.max(0, query.state.dataUpdateCount - 1);
      return Math.min(POLL_BASE_MS * 2 ** exp, POLL_MAX_MS);
    },
  });

  // Result map: терминальное значение из кэша, иначе текущее значение из
  // batch (ready → URL, pending/none → иконка, отсутствие → ещё грузится).
  const map = new Map<string, string | null>();
  if (!enabled) {
    // Превью отключены: показываем иконку (null) для всех поддерживаемых.
    for (const item of previewItems) map.set(item.id, null);
    return map;
  }
  for (const item of previewItems) {
    const value = cachedValue(item.id);
    if (value !== undefined) {
      map.set(item.id, value);
    } else if (batch && item.id in batch) {
      const entry = batch[item.id];
      map.set(item.id, entry.status === "ready" ? (entry.url ?? null) : null);
    }
  }
  return map;
}
