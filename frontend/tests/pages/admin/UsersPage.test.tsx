import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";
import type { UserListItem, UserStatus } from "@/types/users";

const usersApi = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  approve: vi.fn(),
  block: vi.fn(),
  unblock: vi.fn(),
  delete: vi.fn(),
  changePassword: vi.fn(),
}));
vi.mock("@/api/users", () => ({ usersApi }));

const quotasApi = vi.hoisted(() => ({ getByUserId: vi.fn(), updateByUserId: vi.fn() }));
vi.mock("@/api/quotas", () => ({ quotasApi }));

const auditApi = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/api/audit", () => ({ auditApi }));

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

const authState = vi.hoisted(() => ({ current: { id: "me" } as { id: string } | null }));
vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({ user: authState.current }),
}));

import { UsersPage } from "@/pages/admin/UsersPage";

function makeUser(over: Partial<UserListItem> = {}): UserListItem {
  return {
    id: "u1",
    email: "alice@example.com",
    username: "alice",
    status: "active",
    last_login_at: null,
    created_at: "2026-01-01T00:00:00Z",
    is_primary_admin: false,
    ...over,
  };
}

function page(items: UserListItem[], total = items.length) {
  return { items, meta: { total, limit: 20, offset: 0 } };
}

beforeEach(() => {
  vi.clearAllMocks();
  authState.current = { id: "me" };
  usersApi.list.mockResolvedValue(page([]));
  usersApi.approve.mockResolvedValue({});
  usersApi.unblock.mockResolvedValue({});
  usersApi.delete.mockResolvedValue({});
  usersApi.get.mockResolvedValue(makeUser({ is_primary_admin: false }));
  quotasApi.getByUserId.mockResolvedValue(null);
  auditApi.list.mockResolvedValue({ items: [], meta: { total: 0 } });
});

describe("UsersPage", () => {
  it("renders a user row with status badge", async () => {
    usersApi.list.mockResolvedValue(page([makeUser()]));
    renderWithProviders(<UsersPage />);

    expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("Активен")).toBeInTheDocument();
  });

  const statuses: [UserStatus, string][] = [
    ["pending", "Ожидает"],
    ["active", "Активен"],
    ["blocked", "Заблокирован"],
    ["rejected", "Отклонён"],
    ["deleted", "Удалён"],
  ];
  it.each(statuses)("renders the %s status label", async (status, label) => {
    usersApi.list.mockResolvedValue(page([makeUser({ status })]));
    renderWithProviders(<UsersPage />);
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  it("approves a pending user", async () => {
    const user = userEvent.setup();
    usersApi.list.mockResolvedValue(page([makeUser({ id: "p1", status: "pending" })]));
    renderWithProviders(<UsersPage />);

    await user.click(await screen.findByTitle("Одобрить"));

    await waitFor(() => expect(usersApi.approve).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Пользователь одобрен"));
  });

  it("shows an error toast when approve fails", async () => {
    const user = userEvent.setup();
    usersApi.approve.mockRejectedValue(new Error("nope"));
    usersApi.list.mockResolvedValue(page([makeUser({ status: "pending" })]));
    renderWithProviders(<UsersPage />);

    await user.click(await screen.findByTitle("Одобрить"));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Не удалось одобрить"));
  });

  it("unblocks a blocked user", async () => {
    const user = userEvent.setup();
    usersApi.list.mockResolvedValue(page([makeUser({ id: "b1", status: "blocked" })]));
    renderWithProviders(<UsersPage />);

    await user.click(await screen.findByTitle("Разблокировать"));

    await waitFor(() => expect(usersApi.unblock).toHaveBeenCalledWith("b1"));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Пользователь разблокирован"),
    );
  });

  it("shows an error toast when unblock fails", async () => {
    const user = userEvent.setup();
    usersApi.unblock.mockRejectedValue(new Error("nope"));
    usersApi.list.mockResolvedValue(page([makeUser({ status: "blocked" })]));
    renderWithProviders(<UsersPage />);

    await user.click(await screen.findByTitle("Разблокировать"));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось разблокировать"),
    );
  });

  it("opens the detail sheet when clicking the block shortcut on an active user", async () => {
    const user = userEvent.setup();
    usersApi.list.mockResolvedValue(page([makeUser({ status: "active" })]));
    renderWithProviders(<UsersPage />);

    await user.click(await screen.findByTitle("Заблокировать"));

    // Detail sheet renders the user's email as its title.
    await waitFor(() => expect(usersApi.get).toHaveBeenCalledWith("u1"));
  });

  describe("delete button visibility", () => {
    it("HIDES delete for the current user (self)", async () => {
      authState.current = { id: "u1" };
      usersApi.list.mockResolvedValue(page([makeUser({ id: "u1" })]));
      renderWithProviders(<UsersPage />);

      await screen.findByText("alice@example.com");
      expect(screen.queryByTitle("Удалить")).not.toBeInTheDocument();
    });

    it("HIDES delete for a primary admin", async () => {
      usersApi.list.mockResolvedValue(
        page([makeUser({ id: "other", is_primary_admin: true })]),
      );
      renderWithProviders(<UsersPage />);

      await screen.findByText("alice@example.com");
      expect(screen.queryByTitle("Удалить")).not.toBeInTheDocument();
    });

    it("HIDES delete for an already deleted user", async () => {
      usersApi.list.mockResolvedValue(page([makeUser({ id: "other", status: "deleted" })]));
      renderWithProviders(<UsersPage />);

      await screen.findByText("alice@example.com");
      expect(screen.queryByTitle("Удалить")).not.toBeInTheDocument();
    });

    it("SHOWS delete for another non-primary user and deletes on confirm", async () => {
      const user = userEvent.setup();
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
      usersApi.list.mockResolvedValue(page([makeUser({ id: "other" })]));
      renderWithProviders(<UsersPage />);

      const del = await screen.findByTitle("Удалить");
      await user.click(del);

      expect(confirmSpy).toHaveBeenCalled();
      await waitFor(() => expect(usersApi.delete).toHaveBeenCalledWith("other"));
      await waitFor(() =>
        expect(toast.success).toHaveBeenCalledWith("Пользователь удалён"),
      );
      confirmSpy.mockRestore();
    });

    it("does NOT delete when confirm is cancelled", async () => {
      const user = userEvent.setup();
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
      usersApi.list.mockResolvedValue(page([makeUser({ id: "other" })]));
      renderWithProviders(<UsersPage />);

      await user.click(await screen.findByTitle("Удалить"));

      expect(usersApi.delete).not.toHaveBeenCalled();
      confirmSpy.mockRestore();
    });

    it("shows an error toast when delete fails", async () => {
      const user = userEvent.setup();
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
      usersApi.delete.mockRejectedValue(new Error("nope"));
      usersApi.list.mockResolvedValue(page([makeUser({ id: "other" })]));
      renderWithProviders(<UsersPage />);

      await user.click(await screen.findByTitle("Удалить"));
      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("Не удалось удалить пользователя"),
      );
      confirmSpy.mockRestore();
    });
  });

  it("searches by text and resets to first page", async () => {
    const user = userEvent.setup();
    usersApi.list.mockResolvedValue(page([makeUser()]));
    renderWithProviders(<UsersPage />);

    await screen.findByText("alice@example.com");
    await user.type(screen.getByPlaceholderText("Поиск по email или имени…"), "bob");

    await waitFor(() =>
      expect(usersApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "bob", offset: 0 }),
      ),
    );
  });

  it("filters by status", async () => {
    const user = userEvent.setup();
    usersApi.list.mockResolvedValue(page([makeUser()]));
    renderWithProviders(<UsersPage />);

    await screen.findByText("alice@example.com");
    await user.click(screen.getByRole("button", { name: "Заблокированные" }));

    await waitFor(() =>
      expect(usersApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "blocked" }),
      ),
    );
  });

  it("opens the detail sheet by clicking a row", async () => {
    const user = userEvent.setup();
    usersApi.list.mockResolvedValue(page([makeUser()]));
    renderWithProviders(<UsersPage />);

    await user.click(await screen.findByText("alice@example.com"));

    await waitFor(() => expect(usersApi.get).toHaveBeenCalledWith("u1"));
  });

  it("shows the empty state when no users match", async () => {
    usersApi.list.mockResolvedValue(page([]));
    renderWithProviders(<UsersPage />);
    expect(await screen.findByText("Пользователи не найдены.")).toBeInTheDocument();
  });

  it("renders skeletons while loading", () => {
    let resolve!: (v: ReturnType<typeof page>) => void;
    usersApi.list.mockReturnValue(new Promise((r) => (resolve = r)));
    const { container } = renderWithProviders(<UsersPage />);

    expect(container.querySelectorAll("table tbody tr").length).toBe(5);
    resolve(page([]));
  });

  it("paginates across pages", async () => {
    const user = userEvent.setup();
    usersApi.list.mockResolvedValue(page([makeUser()], 50));
    renderWithProviders(<UsersPage />);

    await screen.findByText("alice@example.com");
    expect(screen.getByText(/Стр\. 1 \/ 3/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Вперёд/ }));

    await waitFor(() =>
      expect(usersApi.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ offset: 20 }),
      ),
    );
  });

  it("handles a self-row that is active without crashing (no delete, block shortcut present)", async () => {
    authState.current = { id: "u1" };
    usersApi.list.mockResolvedValue(page([makeUser({ id: "u1", status: "active" })]));
    renderWithProviders(<UsersPage />);

    await screen.findByText("alice@example.com");
    expect(screen.getByTitle("Заблокировать")).toBeInTheDocument();
    expect(screen.queryByTitle("Удалить")).not.toBeInTheDocument();
  });
});
