import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Объединяет CSS-классы и разрешает конфликты Tailwind CSS.
 *
 * Сначала передаёт входные значения в `clsx`, чтобы собрать условные классы
 * в одну строку, затем применяет `tailwind-merge`, чтобы удалить конфликтующие
 * Tailwind-классы.
 *
 * Args:
 *   ...inputs: Список CSS-классов, условных значений или массивов классов.
 *
 * Returns:
 *   Итоговая строка CSS-классов.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
