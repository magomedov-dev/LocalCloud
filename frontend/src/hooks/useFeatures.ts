import { useQuery } from "@tanstack/react-query";
import { configApi } from "@/api/config";
import type { ClientFeatureFlags } from "@/types/config";

/** Query key конфигурации клиента (флагов функциональности). */
export const CLIENT_CONFIG_QUERY_KEY = ["client-config"] as const;

/**
 * Значения флагов по умолчанию.
 *
 * Пока конфигурация не загружена (или запрос не удался), считаем все
 * возможности включёнными — UI не должен внезапно прятать функциональность
 * из-за сетевой ошибки. Реальные ограничения приходят с бэкенда.
 */
const DEFAULT_FLAGS: ClientFeatureFlags = {
  previews_enabled: true,
  file_viewer_enabled: true,
  media_playback_enabled: true,
  file_editing_enabled: true,
};

/**
 * Возвращает флаги функциональности развёртывания.
 *
 * Загружает публичную конфигурацию (`GET /config`) одним запросом и кэширует
 * её на сессию: конфигурация задаётся переменными окружения и в пределах
 * сессии не меняется. До загрузки и при ошибке возвращает дефолты (всё
 * включено), чтобы не прятать UI из-за временной недоступности.
 *
 * Returns:
 *   Флаги функциональности приложения.
 */
export function useFeatures(): ClientFeatureFlags {
  const { data } = useQuery({
    queryKey: CLIENT_CONFIG_QUERY_KEY,
    queryFn: () => configApi.get(),
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    retry: false,
  });
  return data?.features ?? DEFAULT_FLAGS;
}
