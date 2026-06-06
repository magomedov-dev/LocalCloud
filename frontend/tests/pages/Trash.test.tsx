import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";
import type { TrashItemListItem } from "@/types/trash";

vi.mock("@/api/trash", () => ({
  trashApi: {
    list: vi.fn(),
    restore: vi.fn(),
    purge: vi.fn(),
    empty: vi.fn(),
  },
}));

const setCrumbs = vi.fn();
vi.mock("@/contexts/breadcrumb-context", () => ({
  useBreadcrumb: () => ({ setCrumbs }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

vi.mock("@/lib/errors", () => ({ friendlyError: vi.fn(() => "friendly error") }));

vi.mock("@/components/files/FileIcon", () => ({
  FileIcon: () => <span data-testid="file-icon" />,
}));

import { trashApi } from "@/api/trash";
import { toast } from "sonner";
import { TrashPage } from "@/pages/Trash";

const list = vi.mocked(trashApi.list);
const restore = vi.mocked(trashApi.restore);
const purge = vi.mocked(trashApi.purge);
const empty = vi.mocked(trashApi.empty);

function makeTrashItem(
  id: string,
  name: string,
  restore_available = true,
): TrashItemListItem {
  return {
    id,
    node_id: `node-${id}`,
    owner_id: "owner",
    deleted_by: "owner",
    original_parent_id: null,
    original_path: `/${name}`,
    status: "in_trash",
    deleted_at: "2026-01-01T00:00:00Z",
    expires_at: null,
    restore_available,
    purged_at: null,
    node: { id: `node-${id}`, name, node_type: "file" } as TrashItemListItem["node"],
  };
}

function mockList(items: TrashItemListItem[]) {
  list.mockResolvedValue({ items, meta: { total: items.length } } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  restore.mockResolvedValue({} as never);
  purge.mockResolvedValue({} as never);
  empty.mockResolvedValue({} as never);
});

describe("TrashPage", () => {
  it("shows loading skeletons", () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    const { container } = renderWithProviders(<TrashPage />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("shows empty state", async () => {
    mockList([]);
    renderWithProviders(<TrashPage />);
    expect(await screen.findByText("Корзина пуста")).toBeInTheDocument();
  });

  it("renders trash items", async () => {
    mockList([makeTrashItem("1", "a.txt"), makeTrashItem("2", "b.txt")]);
    renderWithProviders(<TrashPage />);
    expect(await screen.findByText("a.txt")).toBeInTheDocument();
    expect(screen.getByText("b.txt")).toBeInTheDocument();
    expect(screen.getByText("2 элем.")).toBeInTheDocument();
  });

  it("restores a single item", async () => {
    mockList([makeTrashItem("1", "a.txt")]);
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");
    await user.click(screen.getByTitle("Восстановить"));

    await waitFor(() => expect(restore).toHaveBeenCalledWith("1"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Восстановлено"));
  });

  it("shows error toast when single restore fails", async () => {
    mockList([makeTrashItem("1", "a.txt")]);
    restore.mockRejectedValueOnce(new Error("x"));
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");
    await user.click(screen.getByTitle("Восстановить"));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("friendly error"));
  });

  it("purges a single item via confirm dialog", async () => {
    mockList([makeTrashItem("1", "a.txt")]);
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");
    await user.click(screen.getByTitle("Удалить навсегда"));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Удалить навсегда" }));

    await waitFor(() => expect(purge).toHaveBeenCalledWith("1"));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Удалено навсегда"));
  });

  it("empties the trash after confirmation", async () => {
    mockList([makeTrashItem("1", "a.txt"), makeTrashItem("2", "b.txt")]);
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");
    await user.click(screen.getByRole("button", { name: /Очистить корзину/ }));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Очистить всё" }));

    await waitFor(() => expect(empty).toHaveBeenCalled());
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Корзина очищена"));
  });

  it("rolls back and warns when empty fails", async () => {
    mockList([makeTrashItem("1", "a.txt")]);
    empty.mockRejectedValueOnce(new Error("x"));
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");
    await user.click(screen.getByRole("button", { name: /Очистить корзину/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Очистить всё" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось очистить корзину"),
    );
  });

  it("bulk restores selected items", async () => {
    mockList([makeTrashItem("1", "a.txt"), makeTrashItem("2", "b.txt")]);
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");

    await user.click(screen.getByLabelText("Выбрать все"));
    await user.click(screen.getByRole("button", { name: /Восстановить \(2\)/ }));

    await waitFor(() => expect(restore).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Файлы восстановлены"));
  });

  it("bulk purges selected items", async () => {
    mockList([makeTrashItem("1", "a.txt"), makeTrashItem("2", "b.txt")]);
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");

    await user.click(screen.getByLabelText("Выбрать все"));
    await user.click(screen.getByRole("button", { name: /Удалить навсегда \(2\)/ }));

    await waitFor(() => expect(purge).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Удалено навсегда"));
  });

  it("reports partial failure on bulk purge", async () => {
    mockList([makeTrashItem("1", "a.txt"), makeTrashItem("2", "b.txt")]);
    purge.mockResolvedValueOnce({} as never).mockRejectedValueOnce(new Error("x"));
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");

    await user.click(screen.getByLabelText("Выбрать все"));
    await user.click(screen.getByRole("button", { name: /Удалить навсегда \(2\)/ }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Не удалось удалить")),
    );
  });

  it("reports full failure on bulk purge", async () => {
    mockList([makeTrashItem("1", "a.txt"), makeTrashItem("2", "b.txt")]);
    purge.mockRejectedValue(new Error("x"));
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");

    await user.click(screen.getByLabelText("Выбрать все"));
    await user.click(screen.getByRole("button", { name: /Удалить навсегда \(2\)/ }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("friendly error"));
  });

  it("reports partial failure on bulk restore", async () => {
    mockList([makeTrashItem("1", "a.txt"), makeTrashItem("2", "b.txt")]);
    restore.mockResolvedValueOnce({} as never).mockRejectedValueOnce(new Error("x"));
    const user = userEvent.setup();
    renderWithProviders(<TrashPage />);
    await screen.findByText("a.txt");

    await user.click(screen.getByLabelText("Выбрать все"));
    await user.click(screen.getByRole("button", { name: /Восстановить \(2\)/ }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Не удалось восстановить")),
    );
  });
});
