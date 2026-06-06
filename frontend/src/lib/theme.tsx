import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ReactNode } from "react";

export function ThemeProvider({
  children,
}: {
  /** Дочерние React-элементы, для которых будет доступна тема приложения. */
  children: ReactNode;
}) {
  /**
   * Провайдер темы приложения.
   *
   * Оборачивает приложение в `next-themes` provider и настраивает переключение
   * темы через CSS-класс на корневом элементе. По умолчанию используется
   * системная тема пользователя, а выбранное значение сохраняется в
   * `localStorage` по ключу `theme`.
   *
   * Args:
   *   children: Дочерние React-элементы приложения.
   */
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      themes={["light", "dark"]}
      storageKey="theme"
    >
      {children}
    </NextThemesProvider>
  );
}
