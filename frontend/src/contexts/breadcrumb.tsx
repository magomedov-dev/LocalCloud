import { useState, type ReactNode } from "react";
import { BreadcrumbContext, type BreadcrumbItem } from "./breadcrumb-context";

/**
 * Провайдер контекста хлебных крошек.
 *
 * Хранит текущий список хлебных крошек и предоставляет
 * метод для его обновления дочерним компонентам.
 */
export function BreadcrumbProvider({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbs] = useState<BreadcrumbItem[]>([]);
  return (
    <BreadcrumbContext.Provider value={{ crumbs, setCrumbs }}>
      {children}
    </BreadcrumbContext.Provider>
  );
}
