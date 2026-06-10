import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";

vi.mock("@/api/nodes", () => ({
  nodesApi: { softDelete: vi.fn(() => Promise.resolve({})) },
}));

vi.mock("@/lib/folderCache", () => ({
  removeNodesFromFolderCache: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  }),
}));

vi.mock("@/lib/errors", () => ({
  friendlyError: vi.fn(() => "Ошибка удаления"),
}));

import { nodesApi } from "@/api/nodes";
import { removeNodesFromFolderCache } from "@/lib/folderCache";
import { toast } from "sonner";
import { DeleteConfirmDialog } from "./DeleteConfirmDialog";

const fqk = ["nodes", "root"];

describe("DeleteConfirmDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (nodesApi.softDelete as ReturnType<typeof vi.fn>).mockResolvedValue({});
  });

  it("renders single-item label", () => {
    renderWithProviders(
      <DeleteConfirmDialog
        open
        onOpenChange={vi.fn()}
        items={[{ id: "1", name: "Файл.txt" }]}
        folderQueryKey={fqk}
      />,
    );
    expect(screen.getByText(/«Файл.txt»/)).toBeInTheDocument();
  });

  it("renders multi-item label", () => {
    renderWithProviders(
      <DeleteConfirmDialog
        open
        onOpenChange={vi.fn()}
        items={[
          { id: "1", name: "a" },
          { id: "2", name: "b" },
        ]}
        folderQueryKey={fqk}
      />,
    );
    expect(screen.getByText(/2 выбранных элемента/)).toBeInTheDocument();
  });

  it("deletes successfully and shows success toast (single)", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithProviders(
      <DeleteConfirmDialog
        open
        onOpenChange={onOpenChange}
        items={[{ id: "1", name: "doc" }]}
        folderQueryKey={fqk}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(nodesApi.softDelete).toHaveBeenCalledWith("1"));
    expect(removeNodesFromFolderCache).toHaveBeenCalledWith(expect.anything(), fqk, ["1"]);
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Перемещено в корзину"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows multi success message", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <DeleteConfirmDialog
        open
        onOpenChange={vi.fn()}
        items={[
          { id: "1", name: "a" },
          { id: "2", name: "b" },
        ]}
        folderQueryKey={fqk}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Удалить" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("2 элементов перемещено в корзину"),
    );
  });

  it("shows partial-failure error toast when some fail", async () => {
    (nodesApi.softDelete as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error("nope"));
    const user = userEvent.setup();
    renderWithProviders(
      <DeleteConfirmDialog
        open
        onOpenChange={vi.fn()}
        items={[
          { id: "1", name: "a" },
          { id: "2", name: "b" },
        ]}
        folderQueryKey={fqk}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Удалить" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Не удалось удалить 1 из 2"),
    );
  });

  it("shows friendly error when all fail", async () => {
    (nodesApi.softDelete as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("nope"));
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithProviders(
      <DeleteConfirmDialog
        open
        onOpenChange={onOpenChange}
        items={[{ id: "1", name: "a" }]}
        folderQueryKey={fqk}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Ошибка удаления"));
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(removeNodesFromFolderCache).not.toHaveBeenCalled();
  });

  it("cancel button calls onOpenChange(false)", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithProviders(
      <DeleteConfirmDialog
        open
        onOpenChange={onOpenChange}
        items={[{ id: "1", name: "a" }]}
        folderQueryKey={fqk}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
