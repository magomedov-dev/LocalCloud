/**
 * Запись журнала аудита.
 */
export interface AuditLog {
  id: string;
  user_id: string | null;
  action: string;
  result: string;
  entity_type: string | null;
  entity_id: string | null;
  resource_type: string | null;
  request_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  message: string | null;
  error_code: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

/**
 * Параметры запроса списка записей аудита.
 */
export interface AuditLogQueryParams {
  limit?: number;
  offset?: number;
  user_id?: string;
  action?: string;
  resource_type?: string;
  result?: string;
  query?: string;
  date_from?: string;
  date_to?: string;
}
