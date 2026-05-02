import { useMemo } from "react";
import { useInfiniteQuery, keepPreviousData } from "@tanstack/react-query";
import { nodesApi } from "@/api/nodes";
import type { NodeListItem } from "@/types/nodes";
import type { FolderRead } from "@/types/folders";

/**
 * Размер страницы для folder/root browser query.
 *
 * Значение соответствует backend-ограничению `limit <= 100`.
 */
export const FOLDER_PAGE_SIZE = 100;

/**
 * Одна страница infinite query для папки или root-директории.
 */
export interface FileBrowserPage {
  /** Элементы текущей страницы. */
  items: NodeListItem[];
  /** Общее количество элементов в папке или root-директории. */
  total: number;
  /** Текущая папка или `null`, если открыт root. */
  folder: FolderRead | null;
  /** Breadcrumbs от root до текущей папки. */
  breadcrumbs: NodeListItem[];
}

/**
 * Плоское представление данных file browser.
 *
 * Используется UI-слоем после объединения всех загруженных страниц infinite
 * query.
 */
interface FileBrowserData {
  /** Объединённые элементы всех загруженных страниц. */
  items: NodeListItem[];
  /** Общее количество элементов в папке или root-директории. */
  total: number;
  /** Текущая папка или `null`, если открыт root. */
  folder: FolderRead | null;
  /** Breadcrumbs от root до текущей папки. */
  breadcrumbs: NodeListItem[];
}

/**
 * Формирует query key для папки или root-директории.
 *
 * Этот key также используется helper-функциями optimistic cache updates.
 *
 * Args:
 *   nodeId: Идентификатор node-папки. Если не передан, возвращается key для root.
 *
 * Returns:
 *   Query key для folder/root browser cache.
 */
export function folderQueryKey(nodeId?: string): unknown[] {
  return nodeId ? ["nodes", nodeId, "content"] : ["nodes", "root"];
}

/**
 * Загружает одну страницу содержимого папки или root-директории.
 *
 * Args:
 *   nodeId: Идентификатор node-папки. Если не передан, загружается root.
 *   offset: Смещение первой записи текущей страницы.
 *
 * Returns:
 *   Promise со страницей данных file browser.
 */
async function fetchFolderPage(
  nodeId: string | undefined,
  offset: number,
): Promise<FileBrowserPage> {
  if (!nodeId) {
    const page = await nodesApi.list({ limit: FOLDER_PAGE_SIZE, offset });
    return { items: page.items, total: page.meta.total, folder: null, breadcrumbs: [] };
  }
  const content = await nodesApi.content(nodeId, { limit: FOLDER_PAGE_SIZE, offset });
  return {
    items: content.items,
    total: content.total,
    folder: content.folder,
    breadcrumbs: content.breadcrumbs,
  };
}

/**
 * Hook для загрузки содержимого папки или root-директории.
 *
 * Использует infinite query, чтобы подгружать элементы постранично. Возвращает
 * плоское представление всех загруженных страниц, а также состояние и методы
 * pagination из React Query.
 *
 * Args:
 *   nodeId: Идентификатор node-папки. Если не передан, загружается root.
 *
 * Returns:
 *   Данные file browser, состояния загрузки и методы подгрузки следующей
 *   страницы.
 */
export function useFileBrowser(nodeId?: string) {
  const query = useInfiniteQuery({
    queryKey: folderQueryKey(nodeId),
    initialPageParam: 0,
    queryFn: ({ pageParam }) => fetchFolderPage(nodeId, pageParam),
    getNextPageParam: (lastPage, allPages) => {
      // Останавливаем загрузку, если последняя страница пустая. Это защищает
      // от бесконечного цикла, если `total` и фактические строки разойдутся.
      if (lastPage.items.length === 0) return undefined;
      const loaded = allPages.reduce((sum, p) => sum + p.items.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  // Формируем плоское представление из referentially stable infinite-query
  // data. Memo на `query.data` важен: новый объект на каждый render заставит
  // consumers с `useEffect([data])`, например breadcrumbs, уйти в loop.
  const data: FileBrowserData | undefined = useMemo(() => {
    if (!query.data) return undefined;
    const pages = query.data.pages;
    return {
      items: pages.flatMap((p) => p.items),
      total: pages[pages.length - 1]?.total ?? 0,
      folder: pages[0]?.folder ?? null,
      breadcrumbs: pages[0]?.breadcrumbs ?? [],
    };
  }, [query.data]);

  return {
    data,
    isLoading: query.isLoading,
    error: query.error,
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    fetchNextPage: query.fetchNextPage,
  };
}
