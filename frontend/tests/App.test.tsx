import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@tests/utils";

// AuthProvider вызывает authApi.me() при монтировании — мокаем весь модуль.
vi.mock("@/api/auth", () => ({
  authApi: {
    me: vi.fn(() => Promise.reject(new Error("unauthenticated"))),
    login: vi.fn(() => Promise.resolve({})),
    logout: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  }),
  Toaster: () => null,
}));

import App from "@/App";

describe("App", () => {
  it("монтирует дерево маршрутов и показывает страницу логина", async () => {
    renderWithProviders(<App />, { routerEntries: ["/login"] });
    // Неаутентифицированного пользователя на /login ждёт форма входа.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /войти|вход/i }),
      ).toBeInTheDocument();
    });
  });

  it("неизвестный маршрут показывает 404", async () => {
    renderWithProviders(<App />, { routerEntries: ["/totally-unknown"] });
    await waitFor(() => {
      expect(screen.getByText(/404/)).toBeInTheDocument();
    });
  });
});
