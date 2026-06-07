import * as React from "react";
import { type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";
import { badgeVariants } from "./badge-variants";

/**
 * Свойства компонента Badge.
 *
 * Поддерживает стандартные HTML-атрибуты `div`
 * и варианты оформления из `badgeVariants`.
 */
export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

/**
 * Бейдж для отображения коротких статусов, меток или категорий.
 *
 * Внешний вид управляется через `variant`, дополнительные классы
 * можно передать через `className`.
 */
function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge };
