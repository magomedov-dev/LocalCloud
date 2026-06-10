import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AuthContextValue } from "@/contexts/auth-context";
import type { CurrentUser } from "@/types";
import { renderWithProviders } from "@tests/utils";
import { UserMenu } from "@/components/layout/UserMenu";

const logout = vi.hoisted(() => vi.fn());

const user: CurrentUser = {
  id: "u1",
  email: "alice@example.com",
  username: "alice",
  status: "active",
  last_login_at: null,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  roles: [],
};

const authState = vi.hoisted(() => ({ value: {} as AuthContextValue }));

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => authState.value,
}));

vi.mock("@/api/auth", () => ({
  authApi: { changePassword: vi.fn() },
}));

describe("UserMenu", () => {
  beforeEach(() => {
    logout.mockReset();
    authState.value = {
      user,
      isLoading: false,
      isAuthenticated: true,
      login: vi.fn(),
      logout,
    };
  });

  it("отображает имя и email пользователя в меню", async () => {
    const u = userEvent.setup();
    renderWithProviders(<UserMenu />);
    await u.click(screen.getByRole("button", { name: "Меню пользователя" }));
    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
  });

  it("содержит пункты смены пароля и выхода", async () => {
    const u = userEvent.setup();
    renderWithProviders(<UserMenu />);
    await u.click(screen.getByRole("button", { name: "Меню пользователя" }));
    expect(await screen.findByText("Сменить пароль")).toBeInTheDocument();
    expect(screen.getByText("Выйти")).toBeInTheDocument();
  });

  it("вызывает logout при клике на «Выйти»", async () => {
    const u = userEvent.setup();
    renderWithProviders(<UserMenu />);
    await u.click(screen.getByRole("button", { name: "Меню пользователя" }));
    await u.click(await screen.findByText("Выйти"));
    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("открывает диалог смены пароля", async () => {
    const u = userEvent.setup();
    renderWithProviders(<UserMenu />);
    await u.click(screen.getByRole("button", { name: "Меню пользователя" }));
    await u.click(await screen.findByText("Сменить пароль"));
    expect(await screen.findByLabelText("Текущий пароль")).toBeInTheDocument();
  });
});
