import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";

vi.mock("@/api/folders", () => ({
  foldersApi: { create: vi.fn(() => Promise.resolve({ id: "new" })) },
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
  friendlyError: vi.fn(() => "Дружелюбная ошибка"),
}));

import { foldersApi } from "@/api/folders";
import { toast } from "sonner";
import { friendlyError } from "@/lib/errors";
import { CreateFolderDialog } from "@/components/files/CreateFolderDialog";

describe("CreateFolderDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render content when closed", () => {
    renderWithProviders(<CreateFolderDialog open={false} onOpenChange={vi.fn()} />);
    expect(screen.queryByText("Новая папка")).not.toBeInTheDocument();
  });

  it("validates empty input and shows error without calling api", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CreateFolderDialog open onOpenChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Создать" }));
    expect(await screen.findByText("Введите название папки")).toBeInTheDocument();
    expect(foldersApi.create).not.toHaveBeenCalled();
  });

  it("creates folder, shows success toast and closes", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithProviders(
      <CreateFolderDialog
        open
        onOpenChange={onOpenChange}
        parentNodeId="parent-1"
        currentNodeId="cur-1"
      />,
    );
    await user.type(screen.getByLabelText("Название"), "  МояПапка  ");
    await user.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() =>
      expect(foldersApi.create).toHaveBeenCalledWith({
        name: "МояПапка",
        parent_id: "parent-1",
      }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Папка создана"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("uses null parent_id when none provided", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CreateFolderDialog open onOpenChange={vi.fn()} />);
    await user.type(screen.getByLabelText("Название"), "Root folder");
    await user.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() =>
      expect(foldersApi.create).toHaveBeenCalledWith({
        name: "Root folder",
        parent_id: null,
      }),
    );
  });

  it("shows friendly error on api rejection", async () => {
    (foldersApi.create as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithProviders(<CreateFolderDialog open onOpenChange={onOpenChange} />);
    await user.type(screen.getByLabelText("Название"), "Fail");
    await user.click(screen.getByRole("button", { name: "Создать" }));

    expect(await screen.findByText("Дружелюбная ошибка")).toBeInTheDocument();
    expect(friendlyError).toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith("Дружелюбная ошибка");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("resets state via cancel button", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithProviders(<CreateFolderDialog open onOpenChange={onOpenChange} />);
    await user.type(screen.getByLabelText("Название"), "abc");
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
