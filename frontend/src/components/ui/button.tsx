import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";
import { buttonVariants } from "./button-variants";

/**
 * Свойства компонента Button.
 *
 * Поддерживает стандартные HTML-атрибуты `button`,
 * варианты оформления из `buttonVariants` и режим `asChild`.
 */
export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

/**
 * Кнопка приложения.
 *
 * Внешний вид управляется через `variant` и `size`.
 * При `asChild` стили и props передаются дочернему компоненту,
 * например ссылке или компоненту роутера.
 */
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  },
);
Button.displayName = "Button";

export { Button };
