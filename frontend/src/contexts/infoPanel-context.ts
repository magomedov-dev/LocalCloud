import { createContext, useContext } from "react";
import type { NodeListItem } from "@/types/nodes";

/**
 * Значение контекста информационной панели.
 */
interface InfoPanelContextValue {
  /** Текущий выбранный элемент или `null`, если элемент не выбран. */
  selectedItem: NodeListItem | null;
  /** Открывает информационную панель для выбранного элемента. */
  openInfo: (item: NodeListItem) => void;
  /** Закрывает информационную панель. */
  closeInfo: () => void;
}

/**
 * React-контекст информационной панели.
 *
 * Должен использоваться внутри `InfoPanelProvider`.
 */
export const InfoPanelContext = createContext<InfoPanelContextValue | null>(null);

/**
 * Возвращает данные и действия информационной панели из `InfoPanelContext`.
 *
 * @throws Если хук используется вне `InfoPanelProvider`.
 */
export function useInfoPanel() {
  const ctx = useContext(InfoPanelContext);
  if (!ctx) throw new Error("useInfoPanel должен использоваться внутри InfoPanelProvider");
  return ctx;
}
