import { useState, useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { BreadcrumbProvider } from "@/contexts/breadcrumb";
import { UploadProvider } from "@/contexts/upload";
import { InfoPanelProvider } from "@/contexts/infoPanel";
import { useInfoPanel } from "@/contexts/infoPanel-context";
import { UploadPanel } from "@/components/files/UploadPanel";
import { NodeInfoPanel } from "@/components/files/NodeInfoPanel";
import { ErrorBoundary } from "@/components/ErrorBoundary";

const STORAGE_KEY = "sidebar-collapsed";

/**
 * Основной layout приложения.
 *
 * Отвечает за структуру интерфейса: боковую панель, верхнюю панель,
 * основную область с вложенными роутами и информационную панель выбранного элемента.
 *
 * Состояние свёрнутости sidebar сохраняется в `localStorage`.
 */
function AppShellLayout() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });

  /**
   * Сохраняет состояние sidebar в `localStorage`
   * при каждом изменении `collapsed`.
   */
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed));
    } catch {
      // Игнор
    }
  }, [collapsed]);

  const { selectedItem, closeInfo } = useInfoPanel();

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Боковая панель на десктопе */}
      <div className="hidden md:flex">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      </div>

      {/* Основная область и информационная панель */}
      <div className="flex flex-1 overflow-hidden">
        <div className="bg-background flex flex-1 flex-col overflow-hidden">
          <TopBar />
          <main className="flex-1 overflow-y-auto p-4 md:p-6">
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>

        {selectedItem && <NodeInfoPanel item={selectedItem} onClose={closeInfo} />}
      </div>
    </div>
  );
}

/**
 * Корневой shell приложения.
 *
 * Оборачивает основной layout в провайдеры:
 * хлебных крошек, загрузок файлов и информационной панели.
 *
 * Также рендерит глобальную панель загрузки файлов.
 */
export function AppShell() {
  return (
    <BreadcrumbProvider>
      <UploadProvider>
        <InfoPanelProvider>
          <AppShellLayout />
          <UploadPanel />
        </InfoPanelProvider>
      </UploadProvider>
    </BreadcrumbProvider>
  );
}
