import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Свойства компонента Checkbox.
 *
 * Наследует стандартные атрибуты `input`, кроме `type` и `onChange`.
 * Для обработки изменения состояния используется `onCheckedChange`.
 */
interface CheckboxProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "type" | "onChange"
> {
  onCheckedChange?: (checked: boolean) => void;
}

/**
 * Чекбокс приложения.
 *
 * Отрисовывает стилизованный `input[type="checkbox"]`
 * и передаёт новое состояние через `onCheckedChange`.
 */
const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, onCheckedChange, ...props }, ref) => (
    <input
      type="checkbox"
      ref={ref}
      className={cn(
        "border-primary accent-primary h-4 w-4 shrink-0 cursor-pointer rounded border",
        "focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none",
        className,
      )}
      onChange={(e) => onCheckedChange?.(e.target.checked)}
      {...props}
    />
  ),
);
Checkbox.displayName = "Checkbox";

export { Checkbox };
