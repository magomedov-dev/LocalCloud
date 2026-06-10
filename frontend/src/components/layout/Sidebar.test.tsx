import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AuthContextValue } from "@/contexts/auth-context";
import type { CurrentUser, RoleListItem } from "@/types";
import { renderWithProviders } from "@/test/utils";
import { Sidebar } from "./Sidebar";

const authState = vi.hoisted(() => ({ value: {} as AuthContextValue }));
const quotaState = vi.hoisted(() => ({ data: undefined as unknown }));

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => authState.value,
}));

vi.mock("@/hooks/useQuota", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useQuota")>();
  return { ...actual, useMyQuota: () => ({ data: quotaState.data }) };
});

function adminRole(): RoleListItem {
  return {
    id: "r1",
    name: "admin",
    code: "admin",
    display_name: "Администратор",
    is_system: true,
    is_active: true,
    created_at: "2024-01-01T00:00:00Z",
  };
}

function makeUser(roles: RoleListItem[] = []): CurrentUser {
  return {
    id: "u1",
    email: "a@b.c",
    username: "alice",
    status: "active",
    is_email_verified: true,
    last_login_at: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    roles,
  };
}

function setAuth(user: CurrentUser | null) {
  authState.value = {
    user,
    isLoading: false,
    isAuthenticated: !!user,
    login: vi.fn(),
    logout: vi.fn(),
  };
}

describe("Sidebar", () => {
  beforeEach(() => {
    setAuth(makeUser());
    quotaState.data = undefined;
  });

  it("отображает основную навигацию", () => {
    renderWithProviders(<Sidebar collapsed={false} onToggle={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Файлы" })).toHaveAttribute("href", "/files");
    expect(screen.getByRole("link", { name: "Корзина" })).toHaveAttribute("href", "/trash");
    expect(screen.getByText("LocalCloud")).toBeInTheDocument();
  });

  it("скрывает админ-раздел для обычного пользователя", () => {
    renderWithProviders(<Sidebar collapsed={false} onToggle={vi.fn()} />);
    expect(screen.queryByRole("link", { name: "Администратор" })).not.toBeInTheDocument();
  });

  it("показывает админ-раздел для администратора", () => {
    setAuth(makeUser([adminRole()]));
    renderWithProviders(<Sidebar collapsed={false} onToggle={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Администратор" })).toHaveAttribute(
      "href",
      "/admin/users",
    );
  });

  it("вызывает onToggle по кнопке сворачивания", async () => {
    const onToggle = vi.fn();
    const u = userEvent.setup();
    renderWithProviders(<Sidebar collapsed={false} onToggle={onToggle} />);
    await u.click(screen.getByRole("button", { name: "Свернуть боковую панель" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("в свёрнутом виде скрывает логотип и меняет aria кнопки", () => {
    renderWithProviders(<Sidebar collapsed onToggle={vi.fn()} />);
    expect(screen.queryByText("LocalCloud")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Развернуть боковую панель" }),
    ).toBeInTheDocument();
  });

  it("отображает квоту с прогрессом, когда данные доступны", () => {
    quotaState.data = { storage_used_bytes: 512, storage_limit_bytes: 1024 };
    renderWithProviders(<Sidebar collapsed={false} onToggle={vi.fn()} />);
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("не показывает блок квоты, когда данных нет", () => {
    quotaState.data = undefined;
    renderWithProviders(<Sidebar collapsed={false} onToggle={vi.fn()} />);
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });

  it("в свёрнутом виде показывает иконку квоты вместо прогресса", () => {
    quotaState.data = { storage_used_bytes: 512, storage_limit_bytes: 1024 };
    renderWithProviders(<Sidebar collapsed onToggle={vi.fn()} />);
    // Прогресс-проценты скрыты в свёрнутом виде.
    expect(screen.queryByText("50%")).not.toBeInTheDocument();
  });

  it("не падает при отсутствии пользователя", () => {
    setAuth(null);
    renderWithProviders(<Sidebar collapsed={false} onToggle={vi.fn()} />);
    expect(screen.queryByRole("link", { name: "Администратор" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Файлы" })).toBeInTheDocument();
  });
});
