import { useState } from "react";
import type { ReactNode } from "react";
import type { NodeListItem } from "@/types/nodes";
import { InfoPanelContext } from "./infoPanel-context";

/**
 * Провайдер контекста информационной панели.
 *
 * Хранит выбранный элемент и предоставляет методы
 * для открытия и закрытия информационной панели.
 */
export function InfoPanelProvider({ children }: { children: ReactNode }) {
  const [selectedItem, setSelectedItem] = useState<NodeListItem | null>(null);

  return (
    <InfoPanelContext.Provider
      value={{
        selectedItem,
        openInfo: setSelectedItem,
        closeInfo: () => setSelectedItem(null),
      }}
    >
      {children}
    </InfoPanelContext.Provider>
  );
}
