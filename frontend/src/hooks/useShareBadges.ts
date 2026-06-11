import { useQuery } from "@tanstack/react-query";
import { publicLinksApi } from "@/api/public-links";
import { permissionsApi } from "@/api/permissions";
import type { NodeListItem } from "@/types/nodes";

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
 * Возвращает badge'и публичного доступа для списка nodes.
 *
 * Грузит два лёгких списка node id (с активной публичной ссылкой и с выданным
 * пользователям доступом) одним DISTINCT-запросом каждый, кэширует на сессию
 * (`refetchOnMount: false`) и пересекает с id текущей папки на клиенте — без
 * выгрузки полных объектов ссылок и без запроса на каждый элемент.
 *
 * Args:
 *   items: Nodes текущей папки, для которых нужно построить share badge'и.
 *
 * Returns:
 *   Map вида `nodeId -> ShareBadge`.
 */
export function useShareBadges(items: NodeListItem[]): Map<string, ShareBadge> {
  const nodeIds = new Set(items.map((i) => i.id));

  // Узлы с активной публичной ссылкой — один лёгкий DISTINCT-запрос, кэшируется
  // на сессию (refetchOnMount: false), а не выгрузка всех объектов ссылок.
  const { data: publicLinkNodeIds } = useQuery({
    queryKey: ACTIVE_LINKS_QUERY_KEY,
    queryFn: () => publicLinksApi.activeNodeIds(),
    staleTime: 10 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  });
  const publicLinkSet = new Set(publicLinkNodeIds ?? []);

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
  for (const id of nodeIds) {
    if (publicLinkSet.has(id)) ensure(id).hasPublicLink = true;
    if (sharedSet.has(id)) ensure(id).hasSharedAccess = true;
  }
  return map;
}
