import type { InfiniteData, QueryClient } from "@tanstack/react-query";
import type { FileBrowserPage } from "@/hooks/useFileBrowser";
import type { NodeListItem } from "@/types/nodes";

/**
 * Тип кэша browser-запроса папки или root-директории.
 *
 * Browser-кэш хранится как infinite query, поэтому значение в React Query
 * имеет форму `InfiniteData<FileBrowserPage>`, а не плоский объект страницы.
 * Все optimistic updates для browser-ключей `["nodes", ...]` должны изменять
 * кэш через эти helper-функции.
 */
type FolderCache = InfiniteData<FileBrowserPage>;

/**
 * Добавляет node в последнюю загруженную страницу кэша папки.
 *
 * Grid визуально пересортировывает элементы самостоятельно, поэтому точное
 * размещение node по страницам не критично. Функция ничего не делает, если
 * кэш ещё не заполнен, имеет несовместимую форму или node уже есть в одной из
 * загруженных страниц.
 *
 * Args:
 *   qc: Экземпляр React Query `QueryClient`.
 *   key: Query key browser-кэша папки или root-директории.
 *   item: Node, который нужно добавить в кэш.
 */
export function insertNodeIntoFolderCache(
  qc: QueryClient,
  key: unknown[],
  item: NodeListItem,
): void {
  qc.setQueryData<FolderCache>(key, (old) => {
    // Защита от non-infinite cache: plain query вместо infinite query.
    if (!old || !Array.isArray(old.pages) || old.pages.length === 0) return old;
    if (old.pages.some((p) => p.items.some((i) => i.id === item.id))) return old;

    const lastIdx = old.pages.length - 1;
    const pages = old.pages.map((p, idx) =>
      idx === lastIdx ? { ...p, items: [...p.items, item], total: p.total + 1 } : p,
    );
    return { ...old, pages };
  });
}

/**
 * Удаляет nodes из всех загруженных страниц кэша папки.
 *
 * Используется для optimistic delete или move. Для каждой страницы функция
 * удаляет элементы с указанными id и уменьшает `total` на количество реально
 * удалённых элементов.
 *
 * Args:
 *   qc: Экземпляр React Query `QueryClient`.
 *   key: Query key browser-кэша папки или root-директории.
 *   ids: Идентификаторы nodes, которые нужно удалить из кэша.
 */
export function removeNodesFromFolderCache(
  qc: QueryClient,
  key: unknown[],
  ids: Iterable<string>,
): void {
  const idSet = new Set(ids);
  if (idSet.size === 0) return;

  qc.setQueryData<FolderCache>(key, (old) => {
    if (!old || !Array.isArray(old.pages)) return old;
    const pages = old.pages.map((p) => {
      const kept = p.items.filter((i) => !idSet.has(i.id));
      const removed = p.items.length - kept.length;
      return removed > 0 ? { ...p, items: kept, total: Math.max(0, p.total - removed) } : p;
    });
    return { ...old, pages };
  });
}

/**
 * Поверхностно обновляет один node во всех загруженных страницах кэша.
 *
 * Подходит для optimistic rename и похожих операций, где нужно заменить часть
 * полей `NodeListItem`. Функция ничего не делает, если node с указанным id
 * отсутствует в кэше.
 *
 * Args:
 *   qc: Экземпляр React Query `QueryClient`.
 *   key: Query key browser-кэша папки или root-директории.
 *   id: Идентификатор node, который нужно обновить.
 *   patch: Частичный набор полей `NodeListItem`, который нужно применить.
 */
export function patchNodeInFolderCache(
  qc: QueryClient,
  key: unknown[],
  id: string,
  patch: Partial<NodeListItem>,
): void {
  qc.setQueryData<FolderCache>(key, (old) => {
    if (!old || !Array.isArray(old.pages)) return old;
    const pages = old.pages.map((p) => ({
      ...p,
      items: p.items.map((i) => (i.id === id ? { ...i, ...patch } : i)),
    }));
    return { ...old, pages };
  });
}

/**
 * Оптимистично удаляет nodes из кэша и возвращает rollback-функцию.
 *
 * Сохраняет точный снимок предыдущего значения кэша, применяет удаление через
 * `removeNodesFromFolderCache` и возвращает функцию, которая восстанавливает
 * исходный снимок. Типичный сценарий: вызвать перед request, выполнить
 * `rollback()` при полной ошибке или инвалидировать query при частичной ошибке.
 *
 * Args:
 *   qc: Экземпляр React Query `QueryClient`.
 *   key: Query key browser-кэша папки или root-директории.
 *   ids: Идентификаторы nodes, которые нужно удалить оптимистично.
 *
 * Returns:
 *   Функция отката, восстанавливающая предыдущее значение кэша.
 */
export function optimisticallyRemoveNodes(
  qc: QueryClient,
  key: unknown[],
  ids: Iterable<string>,
): () => void {
  const snapshot = qc.getQueryData<FolderCache>(key);
  removeNodesFromFolderCache(qc, key, ids);
  return () => {
    qc.setQueryData(key, snapshot);
  };
}

/**
 * Оптимистично обновляет node в кэше и возвращает rollback-функцию.
 *
 * Сохраняет точный снимок предыдущего значения кэша, применяет patch через
 * `patchNodeInFolderCache` и возвращает функцию, которая восстанавливает
 * исходный снимок.
 *
 * Args:
 *   qc: Экземпляр React Query `QueryClient`.
 *   key: Query key browser-кэша папки или root-директории.
 *   id: Идентификатор node, который нужно обновить.
 *   patch: Частичный набор полей `NodeListItem`, который нужно применить
 *     оптимистично.
 *
 * Returns:
 *   Функция отката, восстанавливающая предыдущее значение кэша.
 */
export function optimisticallyPatchNode(
  qc: QueryClient,
  key: unknown[],
  id: string,
  patch: Partial<NodeListItem>,
): () => void {
  const snapshot = qc.getQueryData<FolderCache>(key);
  patchNodeInFolderCache(qc, key, id, patch);
  return () => {
    qc.setQueryData(key, snapshot);
  };
}
