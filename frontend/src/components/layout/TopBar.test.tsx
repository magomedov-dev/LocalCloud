import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AuthContextValue } from "@/contexts/auth-context";
import type { BreadcrumbItem } from "@/contexts/breadcrumb-context";
import type { CurrentUser } from "@/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { renderWithProviders } from "@/test/utils";
import { TopBar } from "./TopBar";

function renderTopBar() {
  return renderWithProviders(
    <TooltipProvider>
      <TopBar />
    </TooltipProvider>,
  );
}

const crumbsState = vi.hoisted(() => ({ crumbs: [] as BreadcrumbItem[] }));
const authState = vi.hoisted(() => ({ value: {} as AuthContextValue }));

vi.mock("@/contexts/breadcrumb-context", () => ({
  useBreadcrumb: () => ({ crumbs: crumbsState.crumbs, setCrumbs: vi.fn() }),
}));

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

describe("TopBar", () => {
  beforeEach(() => {
    crumbsState.crumbs = [];
    authState.value = {
      user,
      isLoading: false,
      isAuthenticated: true,
      login: vi.fn(),
      logout: vi.fn(),
    };
  });

  it("рендерит поиск, переключатель темы и меню пользователя", () => {
    renderTopBar();
    expect(screen.getByLabelText("Поиск файлов и папок")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Системная тема" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Меню пользователя" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Открыть меню" })).toBeInTheDocument();
  });

  it("не отображает хлебные крошки при пустом списке", () => {
    renderTopBar();
    expect(screen.queryByText("Файлы")).not.toBeInTheDocument();
  });

  it("отображает хлебные крошки: ссылку и активную страницу", () => {
    crumbsState.crumbs = [
      { label: "Файлы", href: "/files" },
      { label: "Документы" },
    ];
    renderTopBar();
    expect(screen.getByRole("link", { name: "Файлы" })).toHaveAttribute("href", "/files");
    expect(screen.getByText("Документы")).toBeInTheDocument();
  });

  it("открывает мобильное меню по кнопке", async () => {
    const u = userEvent.setup();
    renderTopBar();
    await u.click(screen.getByRole("button", { name: "Открыть меню" }));
    expect(await screen.findByText("Меню навигации")).toBeInTheDocument();
  });
});
