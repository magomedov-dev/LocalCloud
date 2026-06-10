import { useQuery } from "@tanstack/react-query";
import { publicLinksApi } from "@/api/public-links";
import { permissionsApi } from "@/api/permissions";
import type { NodeListItem } from "@/types/nodes";
import type { PublicLinkListItem } from "@/types/public-links";

/** Общий query key узлов с выданным пользователям доступом. */
export const SHARED_BY_ME_QUERY_KEY = ["permissions", "shared-by-me"] as const;

/**
 * Индикаторы shared-состояния node.
 */
export interface ShareBadge {
  /** Есть ли у node активная публичная ссылка. */
  hasPublicLink: boolean;
  /** Есть ли у node выданный shared-доступ другим пользователям. */
  hasSharedAccess: boolean;
}

/**
 * Общий query key активных публичных ссылок.
 *
 * Используется также в ShareDialog mutations, чтобы изменения публичных ссылок
 * автоматически инвалидировали кэш badge'ей.
 */
export const ACTIVE_LINKS_QUERY_KEY = ["public-links", "all-active"] as const;

/**
 * Размер страницы при загрузке публичных ссылок.
 *
 * Значение соответствует backend-ограничению `limit <= 100`.
 */
const LINKS_PAGE_SIZE = 100;

/**
 * Максимальное количество страниц активных публичных ссылок для загрузки.
 *
 * Ограничение защищает от бесконечного цикла и патологически больших аккаунтов.
 * При текущем значении максимум будет загружено 2000 ссылок.
 */
const MAX_LINK_PAGES = 20;

/**
 * Загружает все активные публичные ссылки пользователя.
 *
 * Проходит по страницам API и собирает ссылки в один список. Останавливается,
 * если последняя страница неполная, достигнут `total` из metadata или достигнут
 * safety-limit `MAX_LINK_PAGES`.
 *
 * Returns:
 *   Promise со списком активных публичных ссылок пользователя.
 */
async function fetchAllActiveLinks(): Promise<PublicLinkListItem[]> {
  const all: PublicLinkListItem[] = [];
  for (let offset = 0, page = 0; page < MAX_LINK_PAGES; page++, offset += LINKS_PAGE_SIZE) {
    const res = await publicLinksApi.list({
      is_active: true,
      limit: LINKS_PAGE_SIZE,
      offset,
    });
    all.push(...res.items);
    if (res.items.length < LINKS_PAGE_SIZE || all.length >= res.meta.total) break;
  }
  return all;
}

/**
 * Возвращает badge'и публичного доступа для списка nodes.
 *
 * Загружает активные публичные ссылки пользователя один раз, постранично, затем
 * фильтрует их на клиенте по node id текущей папки. Такой подход убирает
 * прежнее ограничение первой страницы в 100 ссылок и избегает N×2 запросов на
 * каждый элемент, которые могли забивать browser connection pool.
 *
 * Args:
 *   items: Nodes текущей папки, для которых нужно построить share badge'и.
 *
 * Returns:
 *   Map вида `nodeId -> ShareBadge`.
 */
export function useShareBadges(items: NodeListItem[]): Map<string, ShareBadge> {
  const nodeIds = new Set(items.map((i) => i.id));

  const { data } = useQuery({
    queryKey: ACTIVE_LINKS_QUERY_KEY,
    queryFn: fetchAllActiveLinks,
    staleTime: 10 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  });

  // Узлы, к которым текущий пользователь выдал доступ другим пользователям.
  const { data: sharedByMe } = useQuery({
    queryKey: SHARED_BY_ME_QUERY_KEY,
    queryFn: () => permissionsApi.sharedByMe(),
    staleTime: 10 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  });
  const sharedSet = new Set(sharedByMe ?? []);

  const map = new Map<string, ShareBadge>();
  const ensure = (id: string): ShareBadge => {
    let badge = map.get(id);
    if (!badge) {
      badge = { hasPublicLink: false, hasSharedAccess: false };
      map.set(id, badge);
    }
    return badge;
  };
  for (const link of data ?? []) {
    if (nodeIds.has(link.node_id)) ensure(link.node_id).hasPublicLink = true;
  }
  for (const id of nodeIds) {
    if (sharedSet.has(id)) ensure(id).hasSharedAccess = true;
  }
  return map;
}
