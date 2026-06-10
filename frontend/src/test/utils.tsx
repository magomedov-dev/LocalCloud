import type { ReactElement, ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, type RenderOptions } from "@testing-library/react";

/**
 * Создаёт QueryClient с отключёнными повторами и кэшем для детерминированных
 * тестов.
 */
export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

interface ProvidersOptions {
  /** Начальные записи истории для MemoryRouter. */
  routerEntries?: string[];
  /** Готовый QueryClient (по умолчанию создаётся новый). */
  queryClient?: QueryClient;
}

/**
 * Оборачивает узел в провайдеры react-query и react-router для тестов.
 */
export function withProviders(
  ui: ReactNode,
  { routerEntries = ["/"], queryClient }: ProvidersOptions = {},
): ReactElement {
  const client = queryClient ?? makeTestQueryClient();
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={routerEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

/**
 * Рендерит компонент со всеми общими провайдерами.
 */
export function renderWithProviders(
  ui: ReactElement,
  options: ProvidersOptions & Omit<RenderOptions, "wrapper"> = {},
) {
  const { routerEntries, queryClient, ...renderOptions } = options;
  const client = queryClient ?? makeTestQueryClient();
  return {
    queryClient: client,
    ...render(withProviders(ui, { routerEntries, queryClient: client }), renderOptions),
  };
}
