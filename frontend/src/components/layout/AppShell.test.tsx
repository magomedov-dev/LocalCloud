import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type { AuthContextValue } from "@/contexts/auth-context";
import type { CurrentUser } from "@/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { makeTestQueryClient } from "@/test/utils";
import { AppShell } from "./AppShell";

const authState = vi.hoisted(() => ({ value: {} as AuthContextValue }));

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => authState.value,
}));

vi.mock("@/hooks/useQuota", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useQuota")>();
  return { ...actual, useMyQuota: () => ({ data: undefined }) };
});

vi.mock("@/api/nodes", () => ({
  nodesApi: { search: vi.fn().mockResolvedValue({ items: [] }) },
}));

vi.mock("@/api/auth", () => ({
  authApi: { changePassword: vi.fn() },
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "system", setTheme: vi.fn() }),
}));

const user: CurrentUser = {
  id: "u1",
  email: "a@b.c",
  username: "alice",
  status: "active",
  is_email_verified: true,
  last_login_at: null,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  roles: [],
};

function renderShell() {
  const client = makeTestQueryClient();
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<div>Содержимое страницы</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    authState.value = {
      user,
      isLoading: false,
      isAuthenticated: true,
      login: vi.fn(),
      logout: vi.fn(),
    };
    try {
      localStorage.clear();
    } catch {
      // localStorage может быть недоступен в окружении теста.
    }
  });

  it("рендерит вложенный маршрут через Outlet", () => {
    renderShell();
    expect(screen.getByText("Содержимое страницы")).toBeInTheDocument();
  });

  it("рендерит chrome: поиск и меню пользователя из TopBar", () => {
    renderShell();
    expect(screen.getByLabelText("Поиск файлов и папок")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Меню пользователя" })).toBeInTheDocument();
  });

  it("рендерит навигацию sidebar", () => {
    renderShell();
    // Sidebar присутствует и на десктопе, и в мобильном Sheet — берём все вхождения.
    expect(screen.getAllByRole("link", { name: "Файлы" }).length).toBeGreaterThan(0);
  });
});
