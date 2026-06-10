import { useMemo } from "react";
import { useInfiniteQuery, keepPreviousData } from "@tanstack/react-query";
import { permissionsApi } from "@/api/permissions";
import type { SharedNodeItem } from "@/types/permissions";

const PAGE_SIZE = 100;

/** Ключ кеша списка «Доступно мне». */
export const SHARED_QUERY_KEY = ["permissions", "shared-with-me"] as const;

/**
 * Загружает узлы вкладки «Доступно мне» постранично.
 *
 * Использует infinite query поверх `permissionsApi.sharedWithMe` и возвращает
 * плоский список всех загруженных страниц вместе с состоянием пагинации.
 *
 * Returns:
 *   Список доступных узлов, флаги загрузки и метод подгрузки следующей страницы.
 */
export function useSharedWithMe() {
  const query = useInfiniteQuery({
    queryKey: SHARED_QUERY_KEY,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      permissionsApi.sharedWithMe({ limit: PAGE_SIZE, offset: pageParam }),
    getNextPageParam: (lastPage, allPages) => {
      if (lastPage.items.length === 0) return undefined;
      const loaded = allPages.reduce((sum, p) => sum + p.items.length, 0);
      return loaded < lastPage.meta.total ? loaded : undefined;
    },
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const items: SharedNodeItem[] = useMemo(
    () => (query.data ? query.data.pages.flatMap((p) => p.items) : []),
    [query.data],
  );

  return {
    items,
    total: query.data?.pages[query.data.pages.length - 1]?.meta.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    fetchNextPage: query.fetchNextPage,
  };
}
