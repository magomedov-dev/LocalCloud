import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@tests/utils";
import { RenameDialog } from "@/components/files/RenameDialog";
import { nodesApi } from "@/api/nodes";

vi.mock("@/api/nodes", () => ({
  nodesApi: { rename: vi.fn() },
}));

vi.mock("@/lib/folderCache", () => ({
  optimisticallyPatchNode: vi.fn(() => vi.fn()),
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
  friendlyError: vi.fn(() => "Ошибка переименования"),
}));

import { toast } from "sonner";
import { optimisticallyPatchNode } from "@/lib/folderCache";

const mockRename = vi.mocked(nodesApi.rename);

function renderDialog(props: Partial<Parameters<typeof RenameDialog>[0]> = {}) {
  const onOpenChange = vi.fn();
  const utils = renderWithProviders(
    <RenameDialog
      open
      onOpenChange={onOpenChange}
      nodeId="n1"
      currentName="старое"
      folderQueryKey={["nodes", "root"]}
      {...props}
    />,
  );
  return { onOpenChange, ...utils };
}

describe("RenameDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("инициализирует поле текущим названием", () => {
    renderDialog();
    expect(screen.getByLabelText("Новое название")).toHaveValue("старое");
  });

  it("успешно переименовывает: вызывает API, optimistic-патч, toast и закрытие", async () => {
    const user = userEvent.setup();
    mockRename.mockResolvedValue({});
    const { onOpenChange } = renderDialog();

    const input = screen.getByLabelText("Новое название");
    await user.clear(input);
    await user.type(input, "новое");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(mockRename).toHaveBeenCalledWith("n1", "новое"));
    expect(optimisticallyPatchNode).toHaveBeenCalled();
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Переименовано"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("показывает inline-ошибку при пустом названии без вызова API", async () => {
    const user = userEvent.setup();
    renderDialog();
    const input = screen.getByLabelText("Новое название");
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(screen.getByText("Введите название")).toBeInTheDocument();
    expect(mockRename).not.toHaveBeenCalled();
  });

  it("закрывает диалог без вызова API, если название не изменилось", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(mockRename).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("показывает inline-ошибку и toast при отклонении мутации", async () => {
    const user = userEvent.setup();
    mockRename.mockRejectedValue(new Error("conflict"));
    renderDialog();

    const input = screen.getByLabelText("Новое название");
    await user.clear(input);
    await user.type(input, "новое");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(screen.getByText("Ошибка переименования")).toBeInTheDocument(),
    );
    expect(toast.error).toHaveBeenCalledWith("Ошибка переименования");
  });

  it("закрывает диалог по кнопке «Отмена»", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
