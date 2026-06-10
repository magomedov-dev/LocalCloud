import { THUMBNAIL_NEGATIVE_TTL_MS, THUMBNAIL_URL_TTL_MS } from "@/lib/constants";

const PREFIX = "lc:thumb:";
const TTL_MS = THUMBNAIL_URL_TTL_MS;
const NEGATIVE_TTL_MS = THUMBNAIL_NEGATIVE_TTL_MS;

/**
 * Возвращает сохранённое значение thumbnail URL из `sessionStorage`.
 *
 * Возможные значения:
 * - `string` — thumbnail URL найден в кэше и ещё не истёк.
 * - `null` — для элемента уже известно, что thumbnail отсутствует.
 * - `undefined` — значения нет в кэше, оно устарело или storage недоступен.
 *
 * Args:
 *   id: Идентификатор сущности, для которой нужно получить thumbnail URL.
 *
 * Returns:
 *   Закэшированный thumbnail URL, `null` при известном отсутствии thumbnail
 *   или `undefined`, если значения нет в кэше.
 */
export function getThumbnailCache(id: string): string | null | undefined {
  try {
    const raw = sessionStorage.getItem(PREFIX + id);
    if (raw === null) return undefined;

    const sep = raw.indexOf("|");
    if (sep === -1) {
      // Старый формат без timestamp считаем устаревшим и удаляем.
      sessionStorage.removeItem(PREFIX + id);
      return undefined;
    }

    const ts = Number(raw.slice(0, sep));
    const url = raw.slice(sep + 1);
    const value = url === "" ? null : url;
    // Отрицательный результат (превью ещё нет) живёт коротко — оно может вот-вот
    // появиться; положительный URL — весь срок жизни presigned-ссылки.
    const ttl = value === null ? NEGATIVE_TTL_MS : TTL_MS;

    if (!Number.isFinite(ts) || Date.now() - ts > ttl) {
      sessionStorage.removeItem(PREFIX + id);
      return undefined;
    }

    return value;
  } catch {
    return undefined;
  }
}

/**
 * Сохраняет thumbnail URL в `sessionStorage`.
 *
 * Значение сохраняется вместе с timestamp, чтобы `getThumbnailCache` мог
 * проверить TTL. Если `url` равен `null`, в кэш записывается маркер
 * отсутствующего thumbnail.
 *
 * Args:
 *   id: Идентификатор сущности, для которой сохраняется thumbnail URL.
 *   url: Presigned thumbnail URL или `null`, если thumbnail отсутствует.
 */
export function setThumbnailCache(id: string, url: string | null): void {
  try {
    sessionStorage.setItem(PREFIX + id, `${Date.now()}|${url ?? ""}`);
  } catch {
    // Квота sessionStorage превышена или storage недоступен — деградируем тихо.
  }
}
