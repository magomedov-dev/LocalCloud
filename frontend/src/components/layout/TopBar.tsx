import { Menu } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useBreadcrumb } from "@/contexts/breadcrumb-context";
import { UserMenu } from "./UserMenu";
import { SearchBar } from "./SearchBar";
import { ThemeToggle } from "./ThemeToggle";
import { Button } from "@/components/ui/button";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "@/components/ui/sheet";
import { Sidebar } from "./Sidebar";
import { useEffect, useState } from "react";

/**
 * Верхняя панель приложения.
 *
 * Содержит кнопку открытия мобильного меню, хлебные крошки,
 * строку поиска, переключатель темы и меню пользователя.
 *
 * На мобильных устройствах sidebar открывается как выезжающая панель.
 */
export function TopBar() {
  const { crumbs } = useBreadcrumb();
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  /**
   * Закрывает мобильное меню при изменении маршрута.
   */
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  return (
    <header
      className="bg-panel sticky top-0 z-30 flex h-14 items-center gap-3 px-4"
      style={{ boxShadow: "0 1px 0 0 var(--color-border)" }}
    >
      {/* Кнопка меню на мобильных */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Открыть меню">
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-55 p-0">
          <SheetTitle className="sr-only">Меню навигации</SheetTitle>
          <Sidebar collapsed={false} onToggle={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>

      {/* Навигационные крошки */}
      <div className="hidden min-w-0 flex-1 overflow-hidden sm:block">
        {crumbs.length > 0 && (
          <Breadcrumb>
            <BreadcrumbList>
              {crumbs.map((crumb, idx) => {
                const isLast = idx === crumbs.length - 1;
                return (
                  <span key={idx} className="flex items-center gap-1.5">
                    {idx > 0 && <BreadcrumbSeparator />}
                    <BreadcrumbItem>
                      {isLast || !crumb.href ? (
                        <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                      ) : (
                        <BreadcrumbLink asChild>
                          <Link to={crumb.href}>{crumb.label}</Link>
                        </BreadcrumbLink>
                      )}
                    </BreadcrumbItem>
                  </span>
                );
              })}
            </BreadcrumbList>
          </Breadcrumb>
        )}
      </div>

      {/* Поиск */}
      <SearchBar />

      <ThemeToggle />

      {/* Меню пользователя */}
      <UserMenu />
    </header>
  );
}
