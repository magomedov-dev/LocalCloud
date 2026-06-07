import api from "@/lib/api";
import type { PageResponse } from "@/types/common";
import type { AuditLog, AuditLogQueryParams } from "@/types/audit";

/**
 * API-клиент для работы с журналом аудита.
 */
export const auditApi = {
  /**
   * Возвращает список записей журнала аудита.
   *
   * Args:
   *   params: Параметры фильтрации, поиска и пагинации записей аудита.
   *
   * Returns:
   *   Promise с пагинированным списком записей аудита.
   */
  list: (params?: AuditLogQueryParams) =>
    api.get<PageResponse<AuditLog>>("/audit/logs", { params }).then((r) => r.data),
};
