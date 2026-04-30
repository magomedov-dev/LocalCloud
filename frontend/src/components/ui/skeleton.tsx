import { cn } from "@/lib/utils";

/**
 * Компонент-заглушка для отображения состояния загрузки.
 *
 * Используется как placeholder на месте контента, который ещё загружается:
 * текста, карточек, аватаров, изображений или других элементов интерфейса.
 *
 * По умолчанию имеет приглушённый фон, анимацию пульсации
 * и скруглённые углы.
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("bg-muted animate-pulse rounded-md", className)} {...props} />;
}

export { Skeleton };
