import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";
import type { UserListItem, UserRead, UserStatus } from "@/types/users";
import type { QuotaUsageRead } from "@/types/quotas";

const usersApi = vi.hoisted(() => ({
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

import { UserDetailSheet } from "@/pages/admin/UserDetailSheet";

function listItem(over: Partial<UserListItem> = {}): UserListItem {
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

function detail(over: Partial<UserRead> = {}): UserRead {
  return {
    id: "u1",
    email: "alice@example.com",
    username: "alice",
    status: "active",
    last_login_at: "2026-02-02T12:00:00Z",
    approved_at: "2026-01-02T00:00:00Z",
    blocked_at: null,
    rejected_at: null,
    deleted_at: null,
    block_reason: null,
    rejection_reason: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    is_primary_admin: false,
    ...over,
  };
}

function quota(over: Partial<QuotaUsageRead> = {}): QuotaUsageRead {
  return {
    user_id: "u1",
    storage_limit_bytes: 10 * 1024 ** 3,
    storage_used_bytes: 5 * 1024 ** 3,
    max_file_size_bytes: 100 * 1024 ** 2,
    files_limit: 1000,
    files_used: 10,
    public_links_limit: 50,
    public_links_used: 2,
    active_upload_sessions_limit: 5,
    active_upload_sessions_used: 0,
    available_storage_bytes: 5 * 1024 ** 3,
    usage_percent: 50,
    is_storage_full: false,
    is_files_limit_reached: false,
    is_public_links_limit_reached: false,
    is_active_upload_sessions_limit_reached: false,
    ...over,
  };
}

const noop = () => {};

beforeEach(() => {
  vi.clearAllMocks();
  authState.current = { id: "me" };
  usersApi.get.mockResolvedValue(detail());
  usersApi.approve.mockResolvedValue({});
  usersApi.block.mockResolvedValue({});
  usersApi.unblock.mockResolvedValue({});
  usersApi.delete.mockResolvedValue({});
  usersApi.changePassword.mockResolvedValue({});
  quotasApi.getByUserId.mockResolvedValue(quota());
  quotasApi.updateByUserId.mockResolvedValue({});
  auditApi.list.mockResolvedValue({ items: [], meta: { total: 0 } });
});

describe("UserDetailSheet", () => {
  it("renders nothing visible when user is null", () => {
    renderWithProviders(<UserDetailSheet user={null} onClose={noop} />);
    expect(screen.queryByText("alice@example.com")).not.toBeInTheDocument();
    expect(usersApi.get).not.toHaveBeenCalled();
  });

  it("renders detail info, quotas, and recent activity", async () => {
    auditApi.list.mockResolvedValue({
      items: [
        {
          id: "log-1",
          result: "success",
          action: "user.login",
          message: "ok",
          created_at: "2026-02-01T10:00:00Z",
        },
      ],
      meta: { total: 1 },
    });
    renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);

    // Header
    expect(await screen.findAllByText("alice@example.com"));
    // Detail section
    await waitFor(() => expect(usersApi.get).toHaveBeenCalledWith("u1"));
    expect(await screen.findByText("Зарегистрирован")).toBeInTheDocument();
    expect(screen.getByText("Одобрен")).toBeInTheDocument();
    // Quota section
    expect(screen.getByText("Хранилище")).toBeInTheDocument();
    expect(screen.getByText("Файлы")).toBeInTheDocument();
    // Audit row
    expect(await screen.findByText("user.login")).toBeInTheDocument();
  });

  it("renders blocked/rejected detail fields when present", async () => {
    usersApi.get.mockResolvedValue(
      detail({
        status: "blocked",
        blocked_at: "2026-03-01T00:00:00Z",
        block_reason: "abuse",
        rejected_at: "2026-03-02T00:00:00Z",
        rejection_reason: "dup",
        approved_at: null,
      }),
    );
    renderWithProviders(<UserDetailSheet user={listItem({ status: "blocked" })} onClose={noop} />);

    expect(await screen.findByText("Причина блок.")).toBeInTheDocument();
    expect(screen.getByText("abuse")).toBeInTheDocument();
    expect(screen.getByText("Причина откл.")).toBeInTheDocument();
    expect(screen.getByText("dup")).toBeInTheDocument();
  });

  it("shows 'quota not configured' when quota is null", async () => {
    quotasApi.getByUserId.mockResolvedValue(null);
    renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);

    expect(await screen.findByText("Квота не настроена.")).toBeInTheDocument();
  });

  it("shows 'no records' when audit is empty", async () => {
    renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);
    expect(await screen.findByText("Нет записей.")).toBeInTheDocument();
  });

  it("approves a pending user", async () => {
    const user = userEvent.setup();
    usersApi.get.mockResolvedValue(detail({ status: "pending" }));
    renderWithProviders(<UserDetailSheet user={listItem({ status: "pending" })} onClose={noop} />);

    const btn = await screen.findByRole("button", { name: /Одобрить/ });
    await user.click(btn);

    await waitFor(() => expect(usersApi.approve).toHaveBeenCalledWith("u1"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Одобрен"));
  });

  it("blocks an active user with a reason", async () => {
    const user = userEvent.setup();
    renderWithProviders(<UserDetailSheet user={listItem({ status: "active" })} onClose={noop} />);

    await user.click(await screen.findByRole("button", { name: /Заблокировать/ }));
    // Block input appears.
    const reasonInput = await screen.findByPlaceholderText(
      "Причина блокировки (необязательно)",
    );
    await user.type(reasonInput, "spam");
    // The submit button (now a destructive "Заблокировать").
    const submit = screen
      .getAllByRole("button", { name: "Заблокировать" })
      .at(-1)!;
    await user.click(submit);

    await waitFor(() => expect(usersApi.block).toHaveBeenCalledWith("u1", "spam"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Заблокирован"));
  });

  it("cancels the block input", async () => {
    const user = userEvent.setup();
    renderWithProviders(<UserDetailSheet user={listItem({ status: "active" })} onClose={noop} />);

    await user.click(await screen.findByRole("button", { name: /Заблокировать/ }));
    await screen.findByPlaceholderText("Причина блокировки (необязательно)");
    await user.click(screen.getByRole("button", { name: "Отмена" }));

    await waitFor(() =>
      expect(
        screen.queryByPlaceholderText("Причина блокировки (необязательно)"),
      ).not.toBeInTheDocument(),
    );
  });

  it("shows an error toast when block fails", async () => {
    const user = userEvent.setup();
    usersApi.block.mockRejectedValue(new Error("nope"));
    renderWithProviders(<UserDetailSheet user={listItem({ status: "active" })} onClose={noop} />);

    await user.click(await screen.findByRole("button", { name: /Заблокировать/ }));
    await screen.findByPlaceholderText("Причина блокировки (необязательно)");
    await user.click(screen.getAllByRole("button", { name: "Заблокировать" }).at(-1)!);

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось заблокировать"),
    );
  });

  it("unblocks a blocked user", async () => {
    const user = userEvent.setup();
    usersApi.get.mockResolvedValue(detail({ status: "blocked" }));
    renderWithProviders(<UserDetailSheet user={listItem({ status: "blocked" })} onClose={noop} />);

    await user.click(await screen.findByRole("button", { name: /Разблокировать/ }));

    await waitFor(() => expect(usersApi.unblock).toHaveBeenCalledWith("u1"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Разблокирован"));
  });

  describe("delete button visibility", () => {
    it("HIDES delete for self", async () => {
      authState.current = { id: "u1" };
      renderWithProviders(<UserDetailSheet user={listItem({ id: "u1" })} onClose={noop} />);
      await screen.findByText("Зарегистрирован");
      expect(screen.queryByRole("button", { name: /Удалить/ })).not.toBeInTheDocument();
    });

    it("HIDES delete for a primary admin", async () => {
      renderWithProviders(
        <UserDetailSheet user={listItem({ id: "other", is_primary_admin: true })} onClose={noop} />,
      );
      await screen.findByText("Зарегистрирован");
      expect(screen.queryByRole("button", { name: /Удалить/ })).not.toBeInTheDocument();
    });

    it("HIDES delete for a deleted user", async () => {
      usersApi.get.mockResolvedValue(detail({ id: "other", status: "deleted" }));
      renderWithProviders(
        <UserDetailSheet user={listItem({ id: "other", status: "deleted" })} onClose={noop} />,
      );
      await screen.findByText("Зарегистрирован");
      expect(screen.queryByRole("button", { name: /Удалить/ })).not.toBeInTheDocument();
    });

    it("SHOWS delete for another user and deletes on confirm, closing the sheet", async () => {
      const user = userEvent.setup();
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
      const onClose = vi.fn();
      renderWithProviders(<UserDetailSheet user={listItem({ id: "other" })} onClose={onClose} />);

      await user.click(await screen.findByRole("button", { name: /Удалить/ }));

      expect(confirmSpy).toHaveBeenCalled();
      await waitFor(() => expect(usersApi.delete).toHaveBeenCalledWith("other"));
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Пользователь удалён"));
      await waitFor(() => expect(onClose).toHaveBeenCalled());
      confirmSpy.mockRestore();
    });

    it("does NOT delete when confirm is cancelled", async () => {
      const user = userEvent.setup();
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
      renderWithProviders(<UserDetailSheet user={listItem({ id: "other" })} onClose={noop} />);

      await user.click(await screen.findByRole("button", { name: /Удалить/ }));
      expect(usersApi.delete).not.toHaveBeenCalled();
      confirmSpy.mockRestore();
    });

    it("shows an error toast when delete fails", async () => {
      const user = userEvent.setup();
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
      usersApi.delete.mockRejectedValue(new Error("nope"));
      renderWithProviders(<UserDetailSheet user={listItem({ id: "other" })} onClose={noop} />);

      await user.click(await screen.findByRole("button", { name: /Удалить/ }));
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Не удалось удалить"));
      confirmSpy.mockRestore();
    });
  });

  describe("change password", () => {
    it("changes the password when valid", async () => {
      const user = userEvent.setup();
      renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);

      await user.click(await screen.findByRole("button", { name: /Сменить пароль/ }));
      const input = await screen.findByPlaceholderText("Новый пароль (мин. 8 символов)");

      const save = screen.getByRole("button", { name: "Сохранить" });
      // Disabled while too short.
      await user.type(input, "short");
      expect(save).toBeDisabled();

      await user.clear(input);
      await user.type(input, "longenoughpw");
      expect(save).toBeEnabled();
      await user.click(save);

      await waitFor(() =>
        expect(usersApi.changePassword).toHaveBeenCalledWith("u1", "longenoughpw"),
      );
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Пароль изменён"));
    });

    it("shows an error toast when change password fails", async () => {
      const user = userEvent.setup();
      usersApi.changePassword.mockRejectedValue(new Error("nope"));
      renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);

      await user.click(await screen.findByRole("button", { name: /Сменить пароль/ }));
      const input = await screen.findByPlaceholderText("Новый пароль (мин. 8 символов)");
      await user.type(input, "longenoughpw");
      await user.click(screen.getByRole("button", { name: "Сохранить" }));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("Не удалось изменить пароль"),
      );
    });

    it("cancels the password input", async () => {
      const user = userEvent.setup();
      renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);

      await user.click(await screen.findByRole("button", { name: /Сменить пароль/ }));
      await screen.findByPlaceholderText("Новый пароль (мин. 8 символов)");
      await user.click(screen.getByRole("button", { name: "Отмена" }));

      await waitFor(() =>
        expect(
          screen.queryByPlaceholderText("Новый пароль (мин. 8 символов)"),
        ).not.toBeInTheDocument(),
      );
    });

    it("hides the change-password button for deleted users", async () => {
      usersApi.get.mockResolvedValue(detail({ id: "other", status: "deleted" }));
      renderWithProviders(
        <UserDetailSheet user={listItem({ id: "other", status: "deleted" })} onClose={noop} />,
      );
      await screen.findByText("Зарегистрирован");
      expect(
        screen.queryByRole("button", { name: /Сменить пароль/ }),
      ).not.toBeInTheDocument();
    });
  });

  describe("quota edit", () => {
    it("submits updated quota fields", async () => {
      const user = userEvent.setup();
      renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);

      await user.click(await screen.findByRole("button", { name: /Изменить квоту/ }));

      const save = await screen.findByRole("button", { name: "Сохранить" });
      // Disabled until at least one field has a value.
      expect(save).toBeDisabled();

      // Inputs aren't label-associated; select by their placeholder (derived
      // from the current quota: storage=10, file=100, files=1000, links=50).
      await user.type(screen.getByPlaceholderText("10"), "20");
      await user.type(screen.getByPlaceholderText("100"), "200");
      await user.type(screen.getByPlaceholderText("1000"), "500");
      await user.type(screen.getByPlaceholderText("50"), "30");
      expect(save).toBeEnabled();
      await user.click(save);

      await waitFor(() =>
        expect(quotasApi.updateByUserId).toHaveBeenCalledWith("u1", {
          storage_limit_bytes: 20 * 1024 ** 3,
          max_file_size_bytes: 200 * 1024 ** 2,
          files_limit: 500,
          public_links_limit: 30,
        }),
      );
      await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Квота обновлена"));
    });

    it("shows an error toast when quota update fails", async () => {
      const user = userEvent.setup();
      quotasApi.updateByUserId.mockRejectedValue(new Error("nope"));
      renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);

      await user.click(await screen.findByRole("button", { name: /Изменить квоту/ }));
      await user.type(await screen.findByPlaceholderText("1000"), "500");
      await user.click(screen.getByRole("button", { name: "Сохранить" }));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("Не удалось обновить квоту"),
      );
    });

    it("toggles the quota edit form off via Отмена", async () => {
      const user = userEvent.setup();
      renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);

      await user.click(await screen.findByRole("button", { name: /Изменить квоту/ }));
      expect(await screen.findByText("Хранилище (ГБ)")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /Отмена/ }));
      await waitFor(() =>
        expect(screen.queryByText("Хранилище (ГБ)")).not.toBeInTheDocument(),
      );
    });

    it("renders unlimited placeholders for null limits", async () => {
      quotasApi.getByUserId.mockResolvedValue(
        quota({ files_limit: null, public_links_limit: null }),
      );
      const user = userEvent.setup();
      renderWithProviders(<UserDetailSheet user={listItem()} onClose={noop} />);

      await user.click(await screen.findByRole("button", { name: /Изменить квоту/ }));
      // Both files-limit and links-limit inputs use the ∞ placeholder.
      const infinityInputs = await screen.findAllByPlaceholderText("∞");
      expect(infinityInputs).toHaveLength(2);
    });
  });

  const statuses: [UserStatus, string][] = [
    ["pending", "Ожидает"],
    ["blocked", "Заблокирован"],
    ["rejected", "Отклонён"],
  ];
  it.each(statuses)("renders the %s header status badge", async (status, label) => {
    usersApi.get.mockResolvedValue(detail({ status }));
    renderWithProviders(<UserDetailSheet user={listItem({ status })} onClose={noop} />);
    expect(await screen.findByText(label)).toBeInTheDocument();
  });
});
