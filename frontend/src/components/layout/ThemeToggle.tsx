import { useTheme } from "next-themes";
import { Sun, Moon, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const CYCLE: Array<"system" | "light" | "dark"> = ["system", "light", "dark"];

const LABELS = { system: "Системная тема", light: "Светлая тема", dark: "Тёмная тема" };

/**
 * Переключатель темы приложения.
 *
 * Циклически переключает тему между системной, светлой и тёмной.
 * Текущая тема отображается через соответствующую иконку
 * и текстовую подсказку.
 */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  const current = (CYCLE.includes(theme as "system" | "light" | "dark") ? theme : "system") as
    | "system"
    | "light"
    | "dark";
  const next = CYCLE[(CYCLE.indexOf(current) + 1) % CYCLE.length];

  const Icon = current === "light" ? Sun : current === "dark" ? Moon : Monitor;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setTheme(next)}
          aria-label={LABELS[current]}
        >
          <Icon className="h-4 w-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{LABELS[current]}</TooltipContent>
    </Tooltip>
  );
}
