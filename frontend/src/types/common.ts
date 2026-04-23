/**
 * Метаданные пагинированного ответа.
 */
export interface PageMeta {
  limit: number;
  offset: number;
  total: number;
  count: number;
  has_next: boolean;
  has_previous: boolean;
  page: number;
  pages: number;
}

/**
 * Универсальный формат пагинированного ответа API.
 *
 * Type Parameters:
 *   T: Тип элемента в списке.
 */
export interface PageResponse<T> {
  items: T[];
  meta: PageMeta;
}
