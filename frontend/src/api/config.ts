import api from "@/lib/api";
import type { ClientConfig } from "@/types/config";

/**
 * API-клиент публичной конфигурации приложения.
 */
export const configApi = {
  /**
   * Возвращает публичную конфигурацию клиента (флаги функциональности).
   *
   * Доступна без аутентификации, поэтому UI может получить её ещё до входа.
   *
   * Returns:
   *   Promise с конфигурацией клиента.
   */
  get: () => api.get<ClientConfig>("/config").then((r) => r.data),
};
