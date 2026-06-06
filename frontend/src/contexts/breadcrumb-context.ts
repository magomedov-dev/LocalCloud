import { createContext, useContext } from "react";

/**
 * Элемент хлебных крошек.
 */
export interface BreadcrumbItem {
  /** Текст элемента. */
  label: string;
  /** Ссылка элемента. Если не указана, элемент считается неактивным. */
  href?: string;
}

/**
 * Значение контекста хлебных крошек.
 */
interface BreadcrumbContextValue {
  /** Текущий список хлебных крошек. */
  crumbs: BreadcrumbItem[];
  /** Обновляет список хлебных крошек. */
  setCrumbs: (crumbs: BreadcrumbItem[]) => void;
}

/**
 * React-контекст хлебных крошек.
 *
 * Должен использоваться внутри `BreadcrumbProvider`.
 */
export const BreadcrumbContext = createContext<BreadcrumbContextValue | null>(null);

/**
 * Возвращает данные хлебных крошек из `BreadcrumbContext`.
 *
 * @throws Если хук используется вне `BreadcrumbProvider`.
 */
export function useBreadcrumb() {
  const ctx = useContext(BreadcrumbContext);
  if (!ctx) throw new Error("useBreadcrumb должен использоваться внутри <BreadcrumbProvider>");
  return ctx;
}
