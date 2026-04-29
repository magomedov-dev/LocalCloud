import { NavLink } from "react-router-dom";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

/**
 * Свойства элемента навигации.
 *
 * `to` — путь для перехода.
 * `icon` — иконка из `lucide-react`.
 * `label` — текстовая подпись пункта меню.
 * `collapsed` — определяет, отображать только иконку или иконку с текстом.
 */
interface Props {
  to: string;
  icon: LucideIcon;
  label: string;
  collapsed: boolean;
}

/**
 * Элемент навигационного меню.
 *
 * Рендерит ссылку `NavLink` с иконкой и подписью.
 * Для активного маршрута применяет выделенные стили.
 *
 * В свёрнутом состоянии sidebar скрывает текстовую подпись
 * и показывает её во всплывающей подсказке справа.
 */
export function NavItem({ to, icon: Icon, label, collapsed }: Props) {
  return (
    <Tooltip delayDuration={0}>
      <TooltipTrigger asChild>
        <NavLink
          to={to}
          className={({ isActive }) =>
            cn(
              "flex flex-row items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "bg-primary/15 text-primary"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
              collapsed && "justify-center px-2",
            )
          }
        >
          <Icon className="h-4 w-4 shrink-0" />
          {!collapsed && <span>{label}</span>}
        </NavLink>
      </TooltipTrigger>
      {collapsed && (
        <TooltipContent side="right" sideOffset={8}>
          {label}
        </TooltipContent>
      )}
    </Tooltip>
  );
}
