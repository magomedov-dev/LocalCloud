import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";

/** Провайдер для настройки поведения tooltip-компонентов. */
const TooltipProvider = TooltipPrimitive.Provider;

/** Корневой компонент tooltip. */
const Tooltip = TooltipPrimitive.Root;

/** Элемент, при взаимодействии с которым отображается tooltip. */
const TooltipTrigger = TooltipPrimitive.Trigger;

/**
 * Содержимое tooltip.
 *
 * Рендерит всплывающую подсказку с базовыми стилями,
 * анимацией появления/скрытия и поддержкой позиционирования
 * через свойства Radix Tooltip Content.
 *
 * По умолчанию используется отступ `sideOffset = 4`.
 */
const TooltipContent = React.forwardRef<
  React.ComponentRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Content
    ref={ref}
    sideOffset={sideOffset}
    className={cn(
      "bg-popover text-popover-foreground animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 origin-[--radix-tooltip-content-transform-origin] overflow-hidden rounded-md border px-3 py-1.5 text-sm shadow-md",
      className,
    )}
    {...props}
  />
));
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
