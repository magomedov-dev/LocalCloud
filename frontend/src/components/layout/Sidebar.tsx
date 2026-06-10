import { Cloud, Files, Trash2, Shield, ChevronLeft, ChevronRight, HardDrive } from "lucide-react";
import { NavItem } from "./NavItem";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Progress } from "@/components/ui/progress";
import { useAuth } from "@/contexts/auth-context";
import { useMyQuota, formatBytes } from "@/hooks/useQuota";
import { cn } from "@/lib/utils";

/**
 * Свойства боковой панели.
 *
 * `collapsed` определяет, отображается панель в полном или свёрнутом виде.
 * `onToggle` вызывается при переключении состояния панели.
 */
interface Props {
  collapsed: boolean;
  onToggle: () => void;
}

/**
 * Боковая панель приложения.
 *
 * Содержит логотип, основную навигацию, административный раздел,
 * информацию об использованном хранилище и кнопку сворачивания.
 *
 * В свёрнутом состоянии отображает только иконки,
 * а подписи и данные квоты показывает через tooltip.
 */
export function Sidebar({ collapsed, onToggle }: Props) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { data: quota } = useMyQuota();
  const usedPct = quota
    ? Math.min(100, Math.round((quota.storage_used_bytes / quota.storage_limit_bytes) * 100))
    : 0;

  return (
    <TooltipProvider>
      <aside
        className={cn(
          "bg-panel border-border relative flex h-screen flex-col border-r transition-all duration-200",
          collapsed ? "w-[60px]" : "w-[220px]",
        )}
      >
        {/* Логотип */}
        <div
          className={cn("flex h-14 items-center px-3", collapsed ? "justify-center" : "gap-2.5")}
        >
          <div className="bg-primary/20 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg">
            <Cloud className="text-primary h-4 w-4" />
          </div>
          {!collapsed && (
            <span className="text-foreground text-sm font-semibold tracking-tight">LocalCloud</span>
          )}
        </div>

        {/* Навигация */}
        <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 py-1">
          <NavItem to="/files" icon={Files} label="Файлы" collapsed={collapsed} />
          <NavItem to="/trash" icon={Trash2} label="Корзина" collapsed={collapsed} />
          {isAdmin && (
            <>
              <Separator className="bg-border/50 my-2" />
              <NavItem
                to="/admin/users"
                icon={Shield}
                label="Администратор"
                collapsed={collapsed}
              />
            </>
          )}
        </nav>

        {/* Квота */}
        {quota && (
          <div className="px-2 pb-1">
            {collapsed ? (
              <Tooltip delayDuration={0}>
                <TooltipTrigger asChild>
                  <div className="flex justify-center py-1">
                    <HardDrive className="text-muted-foreground h-4 w-4" />
                  </div>
                </TooltipTrigger>
                <TooltipContent side="right" sideOffset={8}>
                  {formatBytes(quota.storage_used_bytes)} / {formatBytes(quota.storage_limit_bytes)}
                </TooltipContent>
              </Tooltip>
            ) : (
              <div className="bg-muted/40 rounded-lg px-3 py-2">
                <div className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-xs">
                  <HardDrive className="h-3 w-3 shrink-0" />
                  <span className="truncate">
                    {formatBytes(quota.storage_used_bytes)} /{" "}
                    {formatBytes(quota.storage_limit_bytes)}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Progress value={usedPct} className="bg-border h-1 flex-1" />
                  <span className="text-muted-foreground shrink-0 text-[10px] tabular-nums">
                    {usedPct}%
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Кнопка сворачивания */}
        <div className="p-2">
          <Button
            variant="ghost"
            size="icon"
            className="text-muted-foreground hover:text-foreground w-full"
            onClick={onToggle}
            aria-label={collapsed ? "Развернуть боковую панель" : "Свернуть боковую панель"}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </Button>
        </div>
      </aside>
    </TooltipProvider>
  );
}
